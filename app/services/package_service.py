"""Package importer — first version (docs/PACKAGE_FORMAT.md).

Supported today: packages that contribute **engines**, **flows** and
**workflows** (the engine and flow types A and C of §1). Anything else in
``contributes`` (addons, template packs, presets, step types, tags) is
rejected with a clear message until it is implemented. Signatures (§11.4) are
not checked yet: every package installs as unofficial.

Install is two steps, as in §11.1:
1. ``inspect_upload`` reads and validates the ZIP without installing and
   returns a summary plus a token;
2. ``install`` extracts to ``packages/.staging/``, validates the content and
   moves it to ``packages/<id>/``, then the caller applies the contributions
   to the registry (``apply_to_registry``) and the index is rewritten.

Where things go (§12.1 — the sibling ``data/`` folder is not implemented yet,
so ``<data>`` is ``app/data`` for now):

    <data>/packages/
    ├── index.json
    ├── .staging/            uploads and extraction in progress
    └── <package id>/        manifest.json, engines/, flows/, workflows/ …

Nothing here touches the registry directly: ``apply_to_registry`` and
``remove_from_registry`` mutate the dict the route passes inside its
registry transaction.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
ID_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9-]+)+$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")
FLOW_CATEGORIES = {"create", "refine", "mix"}
ENGINE_CATEGORIES = {"image", "upscale", "compose"}

# §2.2 container limits
MAX_ZIP_BYTES = 200 * 2**20
MAX_UNPACKED_BYTES = 2**30
MAX_FILES = 5000
MAX_RATIO = 100
MAX_PATH_CHARS = 180  # relative path inside the package (Windows 260-char limit, §12.1)
IGNORED = ("__MACOSX/", ".DS_Store", "Thumbs.db", "__pycache__/")

SUPPORTED_CONTRIBUTIONS = {"engines", "flows", "workflows"}
TOKEN_TTL_S = 3600


class PackageError(ValueError):
    """A package that cannot be installed; the message is shown to the user."""


# ── Locations ───────────────────────────────────────────────────────────────


def packages_dir(app_dir: Path) -> Path:
    return app_dir / "data" / "packages"


def _staging(app_dir: Path) -> Path:
    path = packages_dir(app_dir) / ".staging"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ── Index ───────────────────────────────────────────────────────────────────


def _empty_index() -> dict[str, Any]:
    return {"schema_version": 1, "generated_at": None, "packages": {}, "flows": {}, "engines": {}}


def read_index(app_dir: Path) -> dict[str, Any]:
    base = packages_dir(app_dir)
    for name in ("index.json", "index.json.bak"):
        try:
            data = json.loads((base / name).read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("packages"), dict):
                for key in ("flows", "engines"):
                    data.setdefault(key, {})
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
    return _empty_index()


def write_index(app_dir: Path, index: dict[str, Any]) -> None:
    """Atomic write; the previous good index is kept as index.json.bak (§12.3)."""
    base = packages_dir(app_dir)
    base.mkdir(parents=True, exist_ok=True)
    index["generated_at"] = _now()
    target = base / "index.json"
    tmp = base / f"index.json.{uuid.uuid4().hex[:8]}.tmp"
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    if target.exists():
        shutil.copy2(target, base / "index.json.bak")
    os.replace(tmp, target)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Texts (§7.1) ────────────────────────────────────────────────────────────


def text_for(texts: Any, lang: str, default_lang: str = "en") -> str:
    """Pick a text from {lang: str}: app language → default_lang → en → any."""
    if isinstance(texts, str):
        return texts
    if not isinstance(texts, dict):
        return ""
    for key in (lang, default_lang, "en"):
        if texts.get(key):
            return str(texts[key])
    return next((str(v) for v in texts.values() if v), "")


# ── Container (§2.2) ────────────────────────────────────────────────────────


def _is_ignored(name: str) -> bool:
    return any(part in name for part in IGNORED)


def _check_member_name(name: str) -> None:
    if "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise PackageError(f"Unsafe path in package: {name}")
    parts = PurePosixPath(name).parts
    if ".." in parts:
        raise PackageError(f"Unsafe path in package: {name}")
    if len(name) > MAX_PATH_CHARS:
        raise PackageError(f"Path too long in package ({len(name)} characters): {name[:60]}…")


def _read_container(zip_path: Path) -> tuple[dict[str, Any], list[zipfile.ZipInfo]]:
    if zip_path.stat().st_size > MAX_ZIP_BYTES:
        raise PackageError("Package is larger than 200 MB")
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise PackageError("Not a valid ZIP file") from exc
    with zf:
        members = [m for m in zf.infolist() if not m.is_dir() and not _is_ignored(m.filename)]
        if len(members) > MAX_FILES:
            raise PackageError("Package has more than 5,000 files")
        total = 0
        lowered: dict[str, str] = {}
        for m in members:
            _check_member_name(m.filename)
            if (m.external_attr >> 16) & 0o170000 == 0o120000:
                raise PackageError(f"Package contains a symbolic link: {m.filename}")
            if m.compress_size and m.file_size / m.compress_size > MAX_RATIO:
                raise PackageError(f"Suspicious compression ratio: {m.filename}")
            total += m.file_size
            low = m.filename.lower()
            if low in lowered and lowered[low] != m.filename:
                raise PackageError(f"Two files differ only in letter case: {m.filename}")
            lowered[low] = m.filename
        if total > MAX_UNPACKED_BYTES:
            raise PackageError("Package is larger than 1 GB unpacked")
        if "manifest.json" not in {m.filename for m in members}:
            raise PackageError("manifest.json is missing from the root of the ZIP")
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PackageError(f"manifest.json is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise PackageError("manifest.json must be a JSON object")
    return manifest, members


# ── Manifest (§3) ───────────────────────────────────────────────────────────


def validate_manifest(manifest: dict[str, Any], files: set[str]) -> list[str]:
    """Raise PackageError for errors; return warnings."""
    warnings: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise PackageError(f"Unsupported schema_version (this app reads {SCHEMA_VERSION})")
    pkg_id = str(manifest.get("id", ""))
    if not ID_RE.match(pkg_id):
        raise PackageError(f"Invalid package id: {pkg_id!r}")
    if not SEMVER_RE.match(str(manifest.get("version", ""))):
        raise PackageError("version must be SemVer, e.g. 1.0.0")
    default_lang = str(manifest.get("default_lang", "")).strip()
    if not default_lang:
        raise PackageError("default_lang is required")
    name = manifest.get("name")
    if not isinstance(name, dict) or not str(name.get(default_lang, "")).strip():
        raise PackageError(f"name needs a text in default_lang ({default_lang})")
    author = manifest.get("author")
    if not isinstance(author, dict) or not str(author.get("name", "")).strip():
        raise PackageError("author.name is required")
    if not str(manifest.get("license", "")).strip():
        raise PackageError("license is required (SPDX id or \"proprietary\")")

    contributes = manifest.get("contributes")
    if not isinstance(contributes, dict) or not contributes:
        raise PackageError("contributes must declare at least one contribution")
    unsupported = sorted(set(contributes) - SUPPORTED_CONTRIBUTIONS)
    if unsupported:
        raise PackageError("This version of Nomad Studio cannot install: " + ", ".join(unsupported))
    for key in SUPPORTED_CONTRIBUTIONS & set(contributes):
        items = contributes[key]
        if not isinstance(items, list) or not all(isinstance(p, str) for p in items):
            raise PackageError(f"contributes.{key} must be a list of file paths")
        for rel in items:
            if rel not in files:
                raise PackageError(f"contributes.{key}: file not found (check letter case): {rel}")
    if len(contributes.get("engines", [])) > 1:
        raise PackageError("A package can contribute one engine (its id is the package id)")
    if "LICENSE" not in files:
        warnings.append("no-license")
    return warnings


def _load_json_member(zf: zipfile.ZipFile, rel: str) -> Any:
    try:
        return json.loads(zf.read(rel).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"{rel} is not valid JSON: {exc}") from exc


def validate_engine(engine: Any, rel: str) -> None:
    if not isinstance(engine, dict):
        raise PackageError(f"{rel}: an engine must be a JSON object")
    if str(engine.get("category", "")) not in ENGINE_CATEGORIES:
        raise PackageError(f"{rel}: category must be one of {sorted(ENGINE_CATEGORIES)}")
    if not str(engine.get("name", "")).strip():
        raise PackageError(f"{rel}: name is required")
    if not isinstance(engine.get("workflow"), dict) or not engine["workflow"]:
        raise PackageError(f"{rel}: workflow (ComfyUI API format) is required")
    if not isinstance(engine.get("analysis"), dict):
        raise PackageError(f"{rel}: analysis is required")


def validate_flow(flow: Any, rel: str, files: set[str]) -> None:
    if not isinstance(flow, dict):
        raise PackageError(f"{rel}: a flow must be a JSON object")
    flow_id = str(flow.get("id", ""))
    category = str(flow.get("category", ""))
    if category not in FLOW_CATEGORIES:
        raise PackageError(f"{rel}: category must be create, refine or mix")
    if not flow_id.startswith(category + ".") or len(flow_id) <= len(category) + 1:
        raise PackageError(f"{rel}: id must start with '{category}.'")
    if not card_fields(flow, "en")["label"]:
        raise PackageError(f"{rel}: the card needs a label")
    if not isinstance(flow.get("steps"), list) or not flow["steps"]:
        raise PackageError(f"{rel}: steps are required")
    for step in flow["steps"]:
        wf = step.get("workflow_file") if isinstance(step, dict) else None
        if wf and wf not in files:
            raise PackageError(f"{rel}: workflow_file not in the package: {wf}")


def card_fields(flow: dict[str, Any], lang: str, default_lang: str = "en") -> dict[str, Any]:
    """Card texts for the hub. Accepts the package format (card.label/desc as
    texts, §6.1) and the legacy flat fields (label, card_desc, card_tags)."""
    card = flow.get("card") if isinstance(flow.get("card"), dict) else {}
    return {
        "label": text_for(card.get("label"), lang, default_lang) or str(flow.get("label", "")),
        "desc": text_for(card.get("desc"), lang, default_lang) or str(flow.get("card_desc", "")),
        "tags": list(card.get("tags") or flow.get("card_tags") or []),
    }


# ── Inspect (upload → summary) ──────────────────────────────────────────────


def inspect_zip(zip_path: Path, index: dict[str, Any], builtin_flow_ids: set[str], lang: str = "en") -> dict[str, Any]:
    """Validate a package without installing it and describe what it would do."""
    manifest, members = _read_container(zip_path)
    files = {m.filename for m in members}
    warnings = validate_manifest(manifest, files)
    pkg_id = manifest["id"]
    contributes = manifest["contributes"]
    default_lang = manifest["default_lang"]

    engines: list[dict[str, Any]] = []
    flows: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as zf:
        for rel in contributes.get("engines", []):
            engine = _load_json_member(zf, rel)
            validate_engine(engine, rel)
            engines.append({"id": pkg_id, "name": engine["name"], "category": engine["category"]})
        for rel in contributes.get("workflows", []):
            if not isinstance(_load_json_member(zf, rel), dict):
                raise PackageError(f"{rel}: a workflow must be a JSON object")
        for rel in contributes.get("flows", []):
            flow = _load_json_member(zf, rel)
            validate_flow(flow, rel, files)
            owner = (index.get("flows", {}).get(flow["id"]) or {}).get("package")
            if flow["id"] in builtin_flow_ids or (owner and owner != pkg_id):
                raise PackageError(f"Flow id already in use: {flow['id']}")
            card = card_fields(flow, lang, default_lang)
            flows.append({"id": flow["id"], "category": flow["category"], "label": card["label"], "desc": card["desc"]})

    installed = index.get("packages", {}).get(pkg_id)
    operation = "install"
    if installed:
        operation = "reinstall" if installed.get("version") == manifest["version"] else "update"

    missing = _missing_requirements(manifest, index, engines)
    return {
        "id": pkg_id,
        "version": manifest["version"],
        "installedVersion": installed.get("version") if installed else None,
        "operation": operation,
        "name": text_for(manifest.get("name"), lang, default_lang),
        "summary": text_for(manifest.get("summary"), lang, default_lang),
        "author": manifest["author"].get("name"),
        "license": manifest.get("license"),
        "defaultLang": default_lang,
        "signature": "unsigned",
        "engines": engines,
        "flows": flows,
        "requiresMissing": missing,
        "warnings": warnings,
        "sizeBytes": zip_path.stat().st_size,
    }


def _missing_requirements(manifest: dict[str, Any], index: dict[str, Any], own_engines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    missing = []
    installed_engines = {**index.get("engines", {}), **{e["id"]: {"category": e["category"]} for e in own_engines}}
    for req in (manifest.get("requires") or {}).get("engines", []) or []:
        if not isinstance(req, dict):
            continue
        if req.get("id") and req["id"] not in installed_engines:
            missing.append({"engine": req["id"]})
        elif req.get("category") and not any(e.get("category") == req["category"] for e in installed_engines.values()):
            missing.append({"engineCategory": req["category"]})
    return missing


def save_upload(app_dir: Path, stream, filename: str) -> tuple[str, Path]:
    """Store an uploaded ZIP in .staging and return (token, path)."""
    _cleanup_staging(app_dir)
    token = uuid.uuid4().hex
    path = _staging(app_dir) / f"upload-{token}.zip"
    written = 0
    with path.open("wb") as fh:
        while True:
            chunk = stream.read(1 << 20)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_ZIP_BYTES:
                fh.close()
                path.unlink(missing_ok=True)
                raise PackageError("Package is larger than 200 MB")
            fh.write(chunk)
    return token, path


def upload_path(app_dir: Path, token: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{32}", str(token or "")):
        return None
    path = _staging(app_dir) / f"upload-{token}.zip"
    return path if path.is_file() else None


def discard_upload(app_dir: Path, token: str) -> None:
    path = upload_path(app_dir, token)
    if path:
        path.unlink(missing_ok=True)


def _cleanup_staging(app_dir: Path) -> None:
    now = time.time()
    for item in _staging(app_dir).iterdir():
        try:
            if now - item.stat().st_mtime > TOKEN_TTL_S:
                shutil.rmtree(item) if item.is_dir() else item.unlink()
        except OSError:
            pass


# ── Install / uninstall ─────────────────────────────────────────────────────


def install(app_dir: Path, zip_path: Path, index: dict[str, Any], builtin_flow_ids: set[str]) -> dict[str, Any]:
    """Extract and move the package into place and update the index in memory.
    Returns {"manifest", "engine", "flows", "summary"} for apply_to_registry.
    Any error before the final move leaves the installation as it was."""
    summary = inspect_zip(zip_path, index, builtin_flow_ids)
    manifest, members = _read_container(zip_path)
    pkg_id = manifest["id"]
    base = packages_dir(app_dir)
    stage = _staging(app_dir) / f"{pkg_id}-{uuid.uuid4().hex[:6]}"
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for m in members:
                target = (stage / m.filename).resolve()
                if not str(target).startswith(str(stage.resolve()) + os.sep):
                    raise PackageError(f"Unsafe path in package: {m.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(m) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        engine = None
        if manifest["contributes"].get("engines"):
            engine = json.loads((stage / manifest["contributes"]["engines"][0]).read_text(encoding="utf-8"))
        flows = [json.loads((stage / rel).read_text(encoding="utf-8")) for rel in manifest["contributes"].get("flows", [])]

        final = base / pkg_id
        if final.exists():
            previous = base / ".previous"
            previous.mkdir(exist_ok=True)
            shutil.rmtree(previous / pkg_id, ignore_errors=True)
            os.replace(final, previous / pkg_id)
        os.replace(stage, final)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    # Index (§12.2)
    for flow_id, info in list(index.get("flows", {}).items()):
        if info.get("package") == pkg_id:
            del index["flows"][flow_id]
    index.get("engines", {}).pop(pkg_id, None)
    default_lang = manifest["default_lang"]
    for rel, flow in zip(manifest["contributes"].get("flows", []), flows):
        index["flows"][flow["id"]] = {
            "package": pkg_id,
            "category": flow["category"],
            "slug": flow["id"].split(".", 1)[1].replace("_", "-"),
            "file": f"{pkg_id}/{rel}",
            "state": "active",
            "status": str(flow.get("status", "active")),
            "complexity": flow.get("complexity"),
            "group": _group_id(manifest, flow),
            "label": card_fields(flow, default_lang, default_lang)["label"],
        }
    if engine:
        index["engines"][pkg_id] = {"category": engine["category"], "name": engine["name"], "state": "active"}
    index["packages"][pkg_id] = {
        "version": manifest["version"],
        "installed_at": _now(),
        "state": "missing_requirements" if summary["requiresMissing"] else "active",
        "state_detail": summary["requiresMissing"] or None,
        "default_lang": default_lang,
        "name": manifest["name"],
        "summary": manifest.get("summary"),
        "author": manifest["author"].get("name"),
        "license": manifest.get("license"),
        "info_url": manifest.get("info_url"),
        "store_url": manifest.get("store_url"),
        "signature": {"status": "unsigned"},
        "group": manifest.get("group"),
        "flows": [f["id"] for f in flows],
        "engines": [pkg_id] if engine else [],
        "has_code": False,
    }
    return {"manifest": manifest, "engine": engine, "flows": flows, "summary": summary}


def _group_id(manifest: dict[str, Any], flow: dict[str, Any]) -> str:
    group = manifest.get("group")
    if isinstance(group, dict) and group.get("id"):
        return str(group["id"])
    return str(flow.get("group") or "core")


def uninstall(app_dir: Path, pkg_id: str, index: dict[str, Any]) -> dict[str, Any]:
    if pkg_id not in index.get("packages", {}):
        raise PackageError(f"Package not installed: {pkg_id}")
    info = index["packages"].pop(pkg_id)
    for flow_id, flow in list(index.get("flows", {}).items()):
        if flow.get("package") == pkg_id:
            del index["flows"][flow_id]
    index.get("engines", {}).pop(pkg_id, None)
    base = packages_dir(app_dir).resolve()
    for folder in (base / pkg_id, base / ".previous" / pkg_id):
        if folder.is_dir() and folder.resolve().parent in (base, base / ".previous"):
            shutil.rmtree(folder)
    return info


# ── Registry integration ────────────────────────────────────────────────────


def apply_to_registry(data: dict[str, Any], app_dir: Path, result: dict[str, Any]) -> None:
    """Register the installed engine as an import and the package's flows as
    an installed pack (read by flow_engine and the hub)."""
    manifest = result["manifest"]
    pkg_id = manifest["id"]
    engine = result["engine"]
    imports = data.setdefault("imports", [])
    if engine:
        previous = next((r for r in imports if r.get("id") == pkg_id), None)
        record = {
            "id": pkg_id,
            "category": engine["category"],
            "name": engine["name"],
            "createdAt": (previous or {}).get("createdAt") or _now(),
            "comfyApiUrl": "",  # the app setting is used (§8.1)
            "workflow": engine["workflow"],
            "analysis": engine["analysis"],
            "basicValues": engine.get("basicValues", {}),
            "advancedValues": engine.get("advancedValues", {}),
            "annotation": engine.get("annotation", {}),
            "package": pkg_id,
            "packageVersion": manifest["version"],
        }
        if previous:
            # An update keeps what the user tuned on this engine.
            record["basicValues"] = {**record["basicValues"], **(previous.get("basicValues") or {})}
            record["advancedValues"] = {**record["advancedValues"], **(previous.get("advancedValues") or {})}
            imports[imports.index(previous)] = record
        else:
            imports.append(record)
        if engine["category"] == "image":
            active = [i for i in (data.get("activeImportIds") or []) if isinstance(i, str)]
            if pkg_id not in active:
                active.append(pkg_id)
            data["activeImportIds"] = active
            data["activeImportId"] = active[0]
    packs = [p for p in data.get("installedPacks", []) if p.get("packId") != pkg_id]
    if result["flows"]:
        packs.append({
            "packId": pkg_id,
            "packDir": str(packages_dir(app_dir) / pkg_id),
            "name": text_for(manifest.get("name"), "en", manifest["default_lang"]),
            "version": manifest["version"],
            "installDate": _now(),
            "package": True,
        })
    data["installedPacks"] = packs


def remove_from_registry(data: dict[str, Any], pkg_id: str) -> None:
    data["imports"] = [r for r in data.get("imports", []) if r.get("id") != pkg_id]
    active = [i for i in (data.get("activeImportIds") or []) if i != pkg_id]
    data["activeImportIds"] = active
    if data.get("activeImportId") == pkg_id or data.get("activeImportId") not in active:
        data["activeImportId"] = active[0] if active else None
    data["installedPacks"] = [p for p in data.get("installedPacks", []) if p.get("packId") != pkg_id]


# ── Listing ─────────────────────────────────────────────────────────────────


def list_packages(app_dir: Path, lang: str = "en") -> list[dict[str, Any]]:
    index = read_index(app_dir)
    engines = index.get("engines", {})
    out = []
    for pkg_id, info in sorted(index.get("packages", {}).items()):
        default_lang = info.get("default_lang") or "en"
        missing = []
        try:
            manifest = json.loads((packages_dir(app_dir) / pkg_id / "manifest.json").read_text(encoding="utf-8"))
            missing = _missing_requirements(manifest, index, [])
        except (OSError, json.JSONDecodeError):
            info = {**info, "state": "broken"}
        out.append({
            "id": pkg_id,
            "version": info.get("version"),
            "name": text_for(info.get("name"), lang, default_lang) or pkg_id,
            "summary": text_for(info.get("summary"), lang, default_lang),
            "author": info.get("author"),
            "state": "broken" if info.get("state") == "broken" else ("missing_requirements" if missing else "active"),
            "requiresMissing": missing,
            "signature": (info.get("signature") or {}).get("status", "unsigned"),
            "flows": [{"id": f, "label": (index.get("flows", {}).get(f) or {}).get("label") or f} for f in info.get("flows", [])],
            "engines": [{"id": e, "name": engines.get(e, {}).get("name") or e, "category": engines.get(e, {}).get("category")}
                        for e in info.get("engines", [])],
            "installedAt": info.get("installed_at"),
            "infoUrl": info.get("info_url"),
        })
    return out
