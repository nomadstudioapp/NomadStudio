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

import threading
from pathlib import Path

from flask import Blueprint, jsonify, request

from ..services import flow_engine, package_service
from ..services.local_access import local_only, request_is_local
from ..services.package_service import PackageError
from .models_api_shared import _registry_transaction

packages_bp = Blueprint("packages", __name__)

APP_DIR = Path(__file__).resolve().parents[1]  # app/ — tests point this at a copy

_lock = threading.Lock()


def _lang() -> str:
    return str(request.args.get("lang") or request.form.get("lang") or "en")[:10]


def _builtin_flow_ids() -> set[str]:
    return {str(e.get("id")) for e in flow_engine._load_index_entries() if e.get("id")}


def install_bundled_packages() -> list[str]:
    """Install or update the packages shipped with the app (bundled-packages/)
    — called once at startup so a fresh install already has the free engines
    and base flows. Respects packages the user uninstalled. Never raises: a
    broken bundled package is logged and skipped, the app still starts."""
    import logging

    log = logging.getLogger(__name__)
    done: list[str] = []
    with _lock:
        index = package_service.read_index(APP_DIR)
        plan = package_service.plan_bundled(APP_DIR, index, _builtin_flow_ids())
        if not plan:
            return done
        for zip_path, action in plan:
            try:
                result = package_service.install(APP_DIR, zip_path, index, _builtin_flow_ids())
                package_service.mark_bundled(index, result["manifest"])
                with _registry_transaction() as data:
                    package_service.apply_to_registry(data, APP_DIR, result)
                done.append(f"{action} {result['manifest']['id']} {result['manifest']['version']}")
            except Exception:  # noqa: BLE001
                log.exception("bundled package failed: %s", zip_path.name)
        package_service.write_index(APP_DIR, index)
    if done:
        log.info("bundled packages: %s", ", ".join(done))
    return done


@packages_bp.get("/api/packages")
def list_packages():
    return jsonify({
        "ok": True,
        "packages": package_service.list_packages(APP_DIR, _lang()),
        "local": request_is_local(),
    })


@packages_bp.post("/api/packages/inspect")
@local_only
def inspect_package():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"ok": False, "error": "Choose a package (.zip) to install"}), 400
    try:
        token, path = package_service.save_upload(APP_DIR, upload.stream, upload.filename)
    except PackageError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    try:
        summary = package_service.inspect_zip(path, package_service.read_index(APP_DIR), _builtin_flow_ids(), _lang())
    except PackageError as exc:
        package_service.discard_upload(APP_DIR, token)
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "token": token, "package": summary})


@packages_bp.post("/api/packages/install")
@local_only
def install_package():
    token = str((request.get_json(silent=True) or {}).get("token", ""))
    path = package_service.upload_path(APP_DIR, token)
    if path is None:
        return jsonify({"ok": False, "error": "The upload expired. Choose the package again."}), 404
    if not _lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Another package is being installed"}), 409
    try:
        index = package_service.read_index(APP_DIR)
        result = package_service.install(APP_DIR, path, index, _builtin_flow_ids())
        with _registry_transaction() as data:
            package_service.apply_to_registry(data, APP_DIR, result)
        package_service.write_index(APP_DIR, index)
    except PackageError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        package_service.discard_upload(APP_DIR, token)
        _lock.release()
    return jsonify({"ok": True, "package": result["summary"]})


@packages_bp.post("/api/packages/discard")
@local_only
def discard_package():
    package_service.discard_upload(APP_DIR, str((request.get_json(silent=True) or {}).get("token", "")))
    return jsonify({"ok": True})


@packages_bp.delete("/api/packages/<pkg_id>")
@local_only
def uninstall_package(pkg_id: str):
    if not _lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Another package operation is running"}), 409
    try:
        index = package_service.read_index(APP_DIR)
        package_service.uninstall(APP_DIR, pkg_id, index)
        with _registry_transaction(deleted_import_ids={pkg_id}) as data:
            package_service.remove_from_registry(data, pkg_id)
        package_service.write_index(APP_DIR, index)
    except PackageError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    finally:
        _lock.release()
    return jsonify({"ok": True})
