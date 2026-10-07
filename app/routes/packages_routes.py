"""Packages — install, list and uninstall (app/services/package_service.py).

    POST   /api/packages/inspect      multipart "file" → summary + token (nothing installed)
    POST   /api/packages/install      {"token"} → installs the inspected package
    POST   /api/packages/discard      {"token"} → forget an inspected upload
    GET    /api/packages              installed packages
    DELETE /api/packages/<id>         uninstall

Installing and uninstalling change what the whole install can run, so they
are only allowed from the computer Nomad Studio runs on (local_access).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import zipfile
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_from_directory
from werkzeug.security import safe_join

from .. import paths
from ..services import flow_engine, package_service
from ..services.local_access import local_only, request_is_local
from ..services.package_service import PackageError
from .models_api_shared import _registry_transaction

packages_bp = Blueprint("packages", __name__)

# Tests point these at temporary folders.
DATA_DIR = paths.DATA_DIR
BUNDLED_DIR = paths.BUNDLED_PACKAGES_DIR

_lock = threading.Lock()


def _lang() -> str:
    return str(request.args.get("lang") or request.form.get("lang") or "en")[:10]


def _builtin_flow_ids() -> set[str]:
    return {str(e.get("id")) for e in flow_engine._load_index_entries() if e.get("id")}


def _sync_styles(result: dict) -> None:
    """contributes.styles (§10.3): copy the package's styles into
    Build > Styles. Styles live in styles.json, not the registry."""
    manifest = result["manifest"]
    if not (manifest.get("contributes") or {}).get("styles"):
        return
    from .models_api_modules.styles_routes import sync_package_styles

    pkg_id = manifest["id"]
    sync_package_styles(pkg_id, package_service.packages_dir(DATA_DIR) / pkg_id, manifest)


def _sync_template_packs(result: dict) -> None:
    """contributes.template_packs (§10.1): copy the package's themes into
    template_packs.json (Create > Template Packs, From Template, Build >
    Templates) and their field values into template_pack_field_values.json."""
    manifest = result["manifest"]
    if not (manifest.get("contributes") or {}).get("template_packs"):
        return
    from .models_api_modules.template_packs_routes import sync_package_template_packs

    pkg_id = manifest["id"]
    sync_package_template_packs(pkg_id, package_service.packages_dir(DATA_DIR) / pkg_id, manifest)


def _sync_contents(result: dict) -> None:
    _sync_styles(result)
    _sync_template_packs(result)


def install_bundled_packages() -> list[str]:
    """Install or update the packages shipped with the app (bundled-packages/)
    — called once at startup so a fresh install already has the free engines
    and base flows. Respects packages the user uninstalled. Never raises: a
    broken bundled package is logged and skipped, the app still starts."""
    import logging

    log = logging.getLogger(__name__)
    done: list[str] = []
    with _lock:
        index = package_service.read_index(DATA_DIR)
        plan = package_service.plan_bundled(BUNDLED_DIR, index, _builtin_flow_ids())
        if not plan:
            return done
        for zip_path, action in plan:
            try:
                result = package_service.install(DATA_DIR, zip_path, index, _builtin_flow_ids())
                package_service.mark_bundled(index, result["manifest"])
                with _registry_transaction() as data:
                    package_service.apply_to_registry(data, DATA_DIR, result)
                _sync_contents(result)
                done.append(f"{action} {result['manifest']['id']} {result['manifest']['version']}")
            except Exception:  # noqa: BLE001
                log.exception("bundled package failed: %s", zip_path.name)
        package_service.write_index(DATA_DIR, index)
    if done:
        log.info("bundled packages: %s", ", ".join(done))
    return done


@packages_bp.get("/api/packages")
def list_packages():
    return jsonify({
        "ok": True,
        "packages": package_service.list_packages(DATA_DIR, _lang()),
        "local": request_is_local(),
    })


@packages_bp.get("/api/packages/texts")
def package_texts():
    """The text installed packages carry for one language, keyed by the
    original (services/i18n.js merges it into flow.flowLabels)."""
    lang = str(request.args.get("lang") or "en")[:10]
    response = jsonify({"ok": True, "lang": lang, "labels": package_service.texts_for(DATA_DIR, lang)})
    response.headers["Cache-Control"] = "no-store"
    return response


# The in-app Marketplace catalogue (tools/packages/build_marketplace_catalog.py)
# carries the sha256 of every zip sold on Ko-fi: a match means the upload is
# an untouched official Nomad Studio pack. Re-read when the file changes.
MARKETPLACE_CATALOG = Path(__file__).resolve().parents[1] / "static" / "marketplace" / "catalog.json"
_official_cache: dict = {"mtime": None, "hashes": frozenset()}


def official_hashes() -> frozenset:
    try:
        mtime = MARKETPLACE_CATALOG.stat().st_mtime
    except OSError:
        return frozenset()
    if _official_cache["mtime"] != mtime:
        try:
            catalog = json.loads(MARKETPLACE_CATALOG.read_text(encoding="utf-8"))
            hashes = frozenset(h for p in catalog.get("products", []) for h in p.get("sha256", []))
        except (OSError, ValueError):
            hashes = frozenset()
        _official_cache.update(mtime=mtime, hashes=hashes)
    return _official_cache["hashes"]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle_members(path: Path) -> list[str] | None:
    """A bundle (e.g. Studio Pro) is a zip of package zips plus a README, with
    no manifest of its own. Returns the inner zip names, or None if `path` is
    an ordinary package."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
    except zipfile.BadZipFile:
        return None
    if "manifest.json" in names:
        return None
    inner = [n for n in names if n.lower().endswith(".zip")]
    rest = [n for n in names if n not in inner]
    if not inner or any(not n.lower().endswith((".txt", ".md")) for n in rest):
        return None
    return inner


def _inspect_one(token: str, path: Path, index: dict, builtin: set[str], official: frozenset) -> dict:
    summary = package_service.inspect_zip(path, index, builtin, _lang())
    return {"token": token, "package": summary, "official": _file_sha256(path) in official}


@packages_bp.post("/api/packages/inspect")
@local_only
def inspect_package():
    """One package, or a bundle of them: the reply always carries `packages`
    (one {token, package, official} each); `token`/`package` stay for a single
    package, as older callers read them."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"ok": False, "error": "Choose a package (.zip) to install"}), 400
    try:
        token, path = package_service.save_upload(DATA_DIR, upload.stream, upload.filename)
    except PackageError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    index = package_service.read_index(DATA_DIR)
    builtin = _builtin_flow_ids()
    official = official_hashes()
    inner = _bundle_members(path)
    if inner is None:
        try:
            item = _inspect_one(token, path, index, builtin, official)
        except PackageError as exc:
            package_service.discard_upload(DATA_DIR, token)
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "token": token, "package": item["package"], "packages": [item]})
    # Bundle: each inner zip becomes an upload of its own, inspected (and
    # later installed) exactly like a package dropped on its own.
    items: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            for name in inner:
                inner_token, inner_path = package_service.save_upload(DATA_DIR, io.BytesIO(zf.read(name)), name)
                try:
                    items.append(_inspect_one(inner_token, inner_path, index, builtin, official))
                except PackageError:
                    package_service.discard_upload(DATA_DIR, inner_token)
                    raise
    except PackageError as exc:
        for item in items:
            package_service.discard_upload(DATA_DIR, item["token"])
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        package_service.discard_upload(DATA_DIR, token)
    return jsonify({"ok": True, "packages": items, "bundle": True})


@packages_bp.post("/api/packages/install")
@local_only
def install_package():
    token = str((request.get_json(silent=True) or {}).get("token", ""))
    path = package_service.upload_path(DATA_DIR, token)
    if path is None:
        return jsonify({"ok": False, "error": "The upload expired. Choose the package again."}), 404
    if not _lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Another package is being installed"}), 409
    try:
        index = package_service.read_index(DATA_DIR)
        result = package_service.install(DATA_DIR, path, index, _builtin_flow_ids())
        with _registry_transaction() as data:
            package_service.apply_to_registry(data, DATA_DIR, result)
        package_service.write_index(DATA_DIR, index)
        _sync_contents(result)
    except PackageError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        package_service.discard_upload(DATA_DIR, token)
        _lock.release()
    return jsonify({"ok": True, "package": result["summary"]})


@packages_bp.post("/api/packages/discard")
@local_only
def discard_package():
    package_service.discard_upload(DATA_DIR, str((request.get_json(silent=True) or {}).get("token", "")))
    return jsonify({"ok": True})


@packages_bp.get("/packages/<pkg_id>/<path:rel>")
def serve_package_file(pkg_id: str, rel: str):
    """Static files a package carries alongside its flows — today just
    preset cover images (§10, Photo Packs gallery), same idea
    PACKAGE_FORMAT.md §9.8 already names for a step-type's own ui/*
    (`/packages/<id>/ui/…`): the file lives inside data/packages/<pkg_id>/,
    not app/static/, so it can't go through url_for('static', …) — same
    safe_join + send_from_directory pattern user_images_routes.py already
    uses for the data-folder image kinds."""
    base = package_service.packages_dir(DATA_DIR) / pkg_id
    full = safe_join(str(base), rel)
    if not full or not os.path.isfile(full):
        abort(404)
    # A package's HTML would run inside the app's origin: never served. Of
    # extras/ (files for use outside the app, §10.1) only the images are.
    lowered = rel.lower()
    if lowered.endswith((".html", ".htm", ".xhtml")) or (
        lowered.startswith("extras/") and not lowered.endswith(package_service.IMAGE_EXTS)
    ):
        abort(404)
    response = send_from_directory(base, rel)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@packages_bp.delete("/api/packages/<pkg_id>")
@local_only
def uninstall_package(pkg_id: str):
    if not _lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Another package operation is running"}), 409
    try:
        index = package_service.read_index(DATA_DIR)
        package_service.uninstall(DATA_DIR, pkg_id, index)
        with _registry_transaction(deleted_import_ids={pkg_id}) as data:
            package_service.remove_from_registry(data, pkg_id)
        package_service.write_index(DATA_DIR, index)
        from .models_api_modules.styles_routes import remove_package_styles
        from .models_api_modules.template_packs_routes import remove_package_template_packs

        remove_package_styles(pkg_id)
        remove_package_template_packs(pkg_id)
    except PackageError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    finally:
        _lock.release()
    return jsonify({"ok": True})
