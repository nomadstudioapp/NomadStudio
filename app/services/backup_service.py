"""Backups of Nomad Studio's own data: create, list, restore.

A backup is a ZIP with a ``manifest.json`` and files laid out by their path
under ``app/``. Two tiers:

- **Data** (always, a few MB): settings and engines (import_registry.json),
  everything in ``data/`` (profiles, Sessions, depots, styles, template
  packs, stories…) and imported workflow logos.
- **Images** (optional, can be GBs): style previews and Build characters and
  backgrounds.

Never included: generated images (they already live in the user's own output
folder), ComfyUI models, and files shipped with the app or its packages.

Creating and restoring run as background jobs (a big image tier takes
minutes) — see ``start_create`` / ``start_restore`` and ``get_job``. The
reset button (docs/SETUP_WIZARD.md) will run a backup as its first step.

Every function takes ``app_dir`` so tests can point it at a copy.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import registry_service

logger = logging.getLogger(__name__)

FORMAT = "nomad-studio-backup"
FORMAT_VERSION = 1

REGISTRY_REL = "workflows/import_registry.json"
DATA_SOURCES = (REGISTRY_REL, "data", "images/workflow_logos")
IMAGE_SOURCES = ("images/styles", "static/images/characters", "static/images/backgrounds")

_NAME_RE = re.compile(r"^nomad-studio-backup-[0-9]{8}-[0-9]{6}(-[a-z-]+)?\.zip$")
_SKIP_RE = re.compile(r"\.bak($|[-.])|\.partial$|\.tmp$", re.IGNORECASE)
_STORED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".zip"}

# Settings that describe THIS install, not the data being restored.
_KEEP_ON_RESTORE = ("backupDir",)


def default_backup_dir(app_dir: Path) -> Path:
    """``backups/`` next to ``app/`` (sibling of app/ and data/ in the
    portable layout, docs/PACKAGE_FORMAT.md)."""
    return app_dir.parent / "backups"


def resolve_backup_dir(app_dir: Path, settings: dict[str, Any]) -> Path:
    raw = str(settings.get("backupDir", "") or "").strip()
    return Path(raw) if raw and os.path.isabs(raw) else default_backup_dir(app_dir)


# ── Inventory ───────────────────────────────────────────────────────────────


def _iter_files(app_dir: Path, sources: tuple[str, ...]):
    """Yield (absolute path, archive name) for every file in *sources*."""
    for rel in sources:
        src = app_dir / rel
        if src.is_file():
            if not _SKIP_RE.search(src.name):
                yield src, rel
        elif src.is_dir():
            for path in sorted(src.rglob("*")):
                if path.is_file() and not _SKIP_RE.search(path.name):
                    yield path, path.relative_to(app_dir).as_posix()


def estimate(app_dir: Path) -> dict[str, int]:
    def total(sources):
        size = count = 0
        for path, _ in _iter_files(app_dir, sources):
            try:
                size += path.stat().st_size
                count += 1
            except OSError:
                pass
        return size, count

    data_bytes, data_files = total(DATA_SOURCES)
    image_bytes, image_files = total(IMAGE_SOURCES)
    return {"dataBytes": data_bytes, "dataFiles": data_files, "imageBytes": image_bytes, "imageFiles": image_files}


def read_manifest(zip_path: Path) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    except Exception:  # noqa: BLE001 — not a backup, or damaged
        return None
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        return None
    return manifest


def list_backups(backup_dir: Path) -> list[dict[str, Any]]:
    if not backup_dir.is_dir():
        return []
    out = []
    for path in backup_dir.glob("nomad-studio-backup-*.zip"):
        if not _NAME_RE.match(path.name):
            continue
        manifest = read_manifest(path)
        stat = path.stat()
        out.append({
            "name": path.name,
            "sizeBytes": stat.st_size,
            "createdAt": (manifest or {}).get("createdAt")
                or datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "includesImages": bool((manifest or {}).get("includesImages")),
            "reason": (manifest or {}).get("reason", "manual"),
            "appVersion": (manifest or {}).get("appVersion"),
            "valid": manifest is not None,
        })
    out.sort(key=lambda b: b["name"], reverse=True)
    return out


def safe_backup_path(backup_dir: Path, name: str) -> Path | None:
    """Only a bare backup file name inside *backup_dir* — never a path."""
    if not _NAME_RE.match(str(name or "")):
        return None
    path = backup_dir / name
    return path if path.is_file() else None


# ── Jobs ────────────────────────────────────────────────────────────────────

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_busy = threading.Lock()  # one backup/restore at a time


def get_job(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _new_job(kind: str) -> dict[str, Any]:
    job = {"id": uuid.uuid4().hex[:12], "kind": kind, "state": "running", "phase": "", "done": 0, "total": 0, "result": None, "error": ""}
    with _jobs_lock:
        _jobs[job["id"]] = job
    return job


def _update(job: dict[str, Any], **fields: Any) -> None:
    with _jobs_lock:
        job.update(fields)


def _run(job: dict[str, Any], work: Callable[[], Any]) -> None:
    def target():
        try:
            result = work()
            _update(job, state="done", result=result)
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI
            logger.exception("backup job %s failed", job["id"])
            _update(job, state="error", error=str(exc))
        finally:
            _busy.release()

    threading.Thread(target=target, daemon=True, name=f"backup-{job['kind']}").start()


def is_busy() -> bool:
    return _busy.locked()


# ── Create ──────────────────────────────────────────────────────────────────


def create_backup(
    app_dir: Path,
    backup_dir: Path,
    include_images: bool,
    reason: str = "manual",
    app_version: str | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Write the ZIP (to ``.partial`` first, renamed when complete)."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    files = list(_iter_files(app_dir, DATA_SOURCES))
    if include_images:
        files += list(_iter_files(app_dir, IMAGE_SOURCES))
    total = sum(p.stat().st_size for p, _ in files)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = {"manual": "", "before-restore": "-before-restore", "before-reset": "-before-reset"}.get(reason, "")
    name = f"nomad-studio-backup-{stamp}{suffix}.zip"
    final = backup_dir / name
    partial = backup_dir / (name + ".partial")

    manifest = {
        "format": FORMAT,
        "formatVersion": FORMAT_VERSION,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "appVersion": app_version,
        "reason": reason,
        "includesImages": include_images,
        "sources": list(DATA_SOURCES) + (list(IMAGE_SOURCES) if include_images else []),
        "files": len(files),
        "bytes": total,
    }

    done = 0
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            for path, arcname in files:
                compress = zipfile.ZIP_STORED if path.suffix.lower() in _STORED_EXT else zipfile.ZIP_DEFLATED
                zf.write(path, arcname, compress_type=compress)
                done += path.stat().st_size
                if progress:
                    progress(done, total, arcname)
        os.replace(partial, final)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return {"name": name, "sizeBytes": final.stat().st_size, "files": len(files), "includesImages": include_images}


def start_create(app_dir: Path, backup_dir: Path, include_images: bool, reason: str = "manual", app_version: str | None = None) -> dict[str, Any] | None:
    if not _busy.acquire(blocking=False):
        return None
    job = _new_job("create")
    _update(job, phase="writing")
    _run(job, lambda: create_backup(
        app_dir, backup_dir, include_images, reason, app_version,
        progress=lambda d, t, f: _update(job, done=d, total=t, file=f),
    ))
    return get_job(job["id"])


# ── Restore ─────────────────────────────────────────────────────────────────


def _allowed_member(name: str, sources: list[str]) -> bool:
    if name == "manifest.json":
        return True
    parts = name.split("/")
    if not name or name.startswith("/") or "\\" in name or ".." in parts or ":" in parts[0]:
        return False
    return any(name == src or name.startswith(src + "/") for src in sources)


def restore_backup(
    app_dir: Path,
    zip_path: Path,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Replace the current data (and images, if the backup has them) with the
    backup's. Sources the backup does not include are left untouched.

    The caller makes a safety backup first (``start_restore`` does)."""
    manifest = read_manifest(zip_path)
    if manifest is None:
        raise ValueError("Not a Nomad Studio backup")
    if int(manifest.get("formatVersion", 0)) > FORMAT_VERSION:
        raise ValueError("This backup was made by a newer version of Nomad Studio")
    sources = [s for s in manifest.get("sources", []) if s in DATA_SOURCES + IMAGE_SOURCES]
    if REGISTRY_REL not in sources:
        raise ValueError("Backup has no settings file")

    staging = app_dir.parent / f".restore-{uuid.uuid4().hex[:8]}"
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            bad = [m.filename for m in members if not _allowed_member(m.filename, sources)]
            if bad:
                raise ValueError(f"Backup contains unexpected files: {bad[:3]}")
            total = sum(m.file_size for m in members)
            done = 0
            for m in members:
                if m.filename == "manifest.json":
                    continue
                zf.extract(m, staging)
                done += m.file_size
                if progress:
                    progress(done, total, m.filename)

        current_settings = (registry_service._read_json_safe(app_dir / REGISTRY_REL) or {}).get("settings", {})
        restored_registry = json.loads((staging / REGISTRY_REL).read_text(encoding="utf-8"))
        settings = restored_registry.setdefault("settings", {})
        for key in _KEEP_ON_RESTORE:
            if key in current_settings:
                settings[key] = current_settings[key]
            else:
                settings.pop(key, None)

        with registry_service._mutation_lock, registry_service._registry_lock:
            for rel in sources:
                if rel == REGISTRY_REL:
                    continue
                target = app_dir / rel
                if target.is_dir():
                    for child in target.iterdir():
                        if _SKIP_RE.search(child.name):
                            continue  # keep the app's own .bak safety files
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                staged = staging / rel
                if staged.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    for child in staged.iterdir():
                        shutil.move(str(child), str(target / child.name))
            registry_path = app_dir / REGISTRY_REL
            tmp = registry_path.with_name(registry_path.name + ".restore-tmp")
            tmp.write_text(json.dumps(restored_registry, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, registry_path)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return {"restored": zip_path.name, "includesImages": bool(manifest.get("includesImages")), "createdAt": manifest.get("createdAt")}


def start_restore(app_dir: Path, backup_dir: Path, zip_path: Path, app_version: str | None = None) -> dict[str, Any] | None:
    if not _busy.acquire(blocking=False):
        return None
    job = _new_job("restore")

    def work():
        manifest = read_manifest(zip_path)
        if manifest is None:
            raise ValueError("Not a Nomad Studio backup")
        _update(job, phase="safety-backup", done=0, total=0)
        safety = create_backup(
            app_dir, backup_dir, bool(manifest.get("includesImages")), "before-restore", app_version,
            progress=lambda d, t, f: _update(job, done=d, total=t, file=f),
        )
        _update(job, phase="restoring", done=0, total=0)
        result = restore_backup(app_dir, zip_path, progress=lambda d, t, f: _update(job, done=d, total=t, file=f))
        result["safetyBackup"] = safety["name"]
        return result

    _run(job, work)
    return get_job(job["id"])
