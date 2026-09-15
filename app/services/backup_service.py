"""Backups of Nomad Studio's own data: create, list, restore.

A backup is a ZIP with a ``manifest.json`` and files laid out by their path
inside the data folder (app/paths.py). Two tiers:

- **Data** (always, a few MB): settings and engines (import_registry.json),
  the app stores (profiles, Sessions, depots, styles, template packs,
  stories…), installed packages and imported workflow logos.
- **Images** (optional, can be GBs): style previews and Build characters and
  backgrounds.

Never included: generated images (they already live in the user's own output
folder), ComfyUI models, update downloads and files shipped with the app.

Format 1 backups (made before the data folder existed) stored paths relative
to the ``app`` package (``workflows/import_registry.json``, ``data/…``,
``static/images/…``); they are mapped to the data folder on restore.

Creating and restoring run as background jobs (a big image tier takes
minutes) — see ``start_create`` / ``start_restore`` and ``get_job``. The
reset button (docs/SETUP_WIZARD.md) will run a backup as its first step.

Every function takes ``data_dir`` so tests can point it at a copy.
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

from .. import paths
from . import registry_service

logger = logging.getLogger(__name__)

FORMAT = "nomad-studio-backup"
FORMAT_VERSION = 2

REGISTRY_REL = "import_registry.json"
LOGOS_REL = "images/workflow_logos"
IMAGE_SOURCES = ("images/styles", "images/characters", "images/backgrounds")
# Top-level entries of the data folder that are never part of a backup.
_EXCLUDED_TOP = {"images", "updates", "version.json"}

_NAME_RE = re.compile(r"^nomad-studio-backup-[0-9]{8}-[0-9]{6}(-[a-z-]+)?\.zip$")
_SKIP_RE = re.compile(r"\.bak($|[-.])|\.partial$|\.tmp$|^\.restore-|^\.staging$", re.IGNORECASE)
_STORED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".zip"}

# Settings that describe THIS install, not the data being restored.
_KEEP_ON_RESTORE = ("backupDir",)
_REASON_SUFFIX = {"manual": "", "before-restore": "-before-restore", "before-reset": "-before-reset", "before-update": "-before-update"}


def default_backup_dir(data_dir: Path) -> Path:
    """``backups/`` next to the data folder (``~/Nomad Studio/backups`` in a
    portable install) — outside the program folder."""
    return data_dir.parent / "backups"


def resolve_backup_dir(data_dir: Path, settings: dict[str, Any]) -> Path:
    raw = str(settings.get("backupDir", "") or "").strip()
    return Path(raw) if raw and os.path.isabs(raw) else default_backup_dir(data_dir)


# ── Inventory ───────────────────────────────────────────────────────────────


def data_sources(data_dir: Path) -> tuple[str, ...]:
    """Everything at the top of the data folder except images and update
    files, plus the workflow logos. The registry always goes first."""
    names = [REGISTRY_REL]
    if data_dir.is_dir():
        for child in sorted(data_dir.iterdir(), key=lambda p: p.name):
            if child.name in _EXCLUDED_TOP or child.name == REGISTRY_REL or _SKIP_RE.search(child.name):
                continue
            names.append(child.name)
    names.append(LOGOS_REL)
    return tuple(names)


def _iter_files(data_dir: Path, sources: tuple[str, ...]):
    """Yield (absolute path, archive name) for every file in *sources*."""
    for rel in sources:
        src = data_dir / rel
        if src.is_file():
            if not _SKIP_RE.search(src.name):
                yield src, rel
        elif src.is_dir():
            for path in sorted(src.rglob("*")):
                rel_parts = path.relative_to(data_dir).parts
                if path.is_file() and not any(_SKIP_RE.search(part) for part in rel_parts):
                    yield path, path.relative_to(data_dir).as_posix()


def estimate(data_dir: Path) -> dict[str, int]:
    def total(sources):
        size = count = 0
        for path, _ in _iter_files(data_dir, sources):
            try:
                size += path.stat().st_size
                count += 1
            except OSError:
                pass
        return size, count

    data_bytes, data_files = total(data_sources(data_dir))
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
    data_dir: Path,
    backup_dir: Path,
    include_images: bool,
    reason: str = "manual",
    app_version: str | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Write the ZIP (to ``.partial`` first, renamed when complete)."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    sources = data_sources(data_dir)
    files = list(_iter_files(data_dir, sources))
    if include_images:
        files += list(_iter_files(data_dir, IMAGE_SOURCES))
    total = sum(p.stat().st_size for p, _ in files)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"nomad-studio-backup-{stamp}{_REASON_SUFFIX.get(reason, '')}.zip"
    final = backup_dir / name
    partial = backup_dir / (name + ".partial")

    manifest = {
        "format": FORMAT,
        "formatVersion": FORMAT_VERSION,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "appVersion": app_version,
        "reason": reason,
        "includesImages": include_images,
        "sources": list(sources) + (list(IMAGE_SOURCES) if include_images else []),
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


def start_create(data_dir: Path, backup_dir: Path, include_images: bool, reason: str = "manual", app_version: str | None = None) -> dict[str, Any] | None:
    if not _busy.acquire(blocking=False):
        return None
    job = _new_job("create")
    _update(job, phase="writing")
    _run(job, lambda: create_backup(
        data_dir, backup_dir, include_images, reason, app_version,
        progress=lambda d, t, f: _update(job, done=d, total=t, file=f),
    ))
    return get_job(job["id"])


# ── Restore ─────────────────────────────────────────────────────────────────


def _safe_rel(name: str) -> bool:
    parts = name.split("/")
    return bool(name) and not name.startswith("/") and "\\" not in name and ".." not in parts and ":" not in parts[0]


def _plan_members(manifest: dict[str, Any], members: list[zipfile.ZipInfo]) -> tuple[list[str], list[tuple[zipfile.ZipInfo, str]]]:
    """(sources in the data folder, [(member, target path in the data folder)]).
    Raises ValueError on anything unexpected."""
    legacy = int(manifest.get("formatVersion", 0)) <= 1
    raw_sources = [str(s) for s in manifest.get("sources", []) if isinstance(s, str)]
    planned: list[tuple[zipfile.ZipInfo, str]] = []
    bad: list[str] = []
    for m in members:
        if m.filename == "manifest.json":
            continue
        target = (paths.legacy_to_data(m.filename) if legacy else m.filename) if _safe_rel(m.filename) else None
        if (not target or not _safe_rel(target) or target.split("/")[0] in {"updates", "version.json"}
                or not (legacy or any(target == s or target.startswith(s + "/") for s in raw_sources))):
            bad.append(m.filename)
        else:
            planned.append((m, target))
    if bad:
        raise ValueError(f"Backup contains unexpected files: {bad[:3]}")
    if legacy:
        # Format 1 had the sources "workflows/import_registry.json", "data",
        # "images/…" and "static/images/…": what gets replaced is whatever the
        # backup actually contains, one top-level entry (or image folder) each.
        sources = sorted({"/".join(t.split("/")[:2]) if t.startswith("images/") else t.split("/")[0] for _, t in planned})
    else:
        sources = raw_sources
    if REGISTRY_REL not in sources or not any(t == REGISTRY_REL for _, t in planned):
        raise ValueError("Backup has no settings file")
    return sources, planned


def restore_backup(
    data_dir: Path,
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

    staging = data_dir.parent / f".restore-{uuid.uuid4().hex[:8]}"
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            sources, planned = _plan_members(manifest, members)
            total = sum(m.file_size for m, _ in planned)
            done = 0
            for m, target in planned:
                dest = staging / target
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(m) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
                done += m.file_size
                if progress:
                    progress(done, total, target)

        current_settings = (registry_service._read_json_safe(data_dir / REGISTRY_REL) or {}).get("settings", {})
        restored_registry = json.loads((staging / REGISTRY_REL).read_text(encoding="utf-8"))
        settings = restored_registry.setdefault("settings", {})
        for key in _KEEP_ON_RESTORE:
            if key in current_settings:
                settings[key] = current_settings[key]
            else:
                settings.pop(key, None)
        paths.fix_pack_dirs(restored_registry, data_dir / "packages")

        with registry_service._mutation_lock, registry_service._registry_lock:
            for rel in sources:
                if rel == REGISTRY_REL:
                    continue
                target = data_dir / rel
                staged = staging / rel
                if target.is_dir():
                    for child in target.iterdir():
                        if _SKIP_RE.search(child.name):
                            continue  # keep the app's own .bak safety files
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                elif target.is_file() and staged.exists():
                    target.unlink()
                if staged.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    for child in staged.iterdir():
                        shutil.move(str(child), str(target / child.name))
                elif staged.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(staged), str(target))
            paths.fix_pack_dirs(restored_registry, data_dir / "packages")
            registry_path = data_dir / REGISTRY_REL
            tmp = registry_path.with_name(registry_path.name + ".restore-tmp")
            tmp.write_text(json.dumps(restored_registry, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, registry_path)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return {"restored": zip_path.name, "includesImages": bool(manifest.get("includesImages")), "createdAt": manifest.get("createdAt")}


def start_restore(data_dir: Path, backup_dir: Path, zip_path: Path, app_version: str | None = None) -> dict[str, Any] | None:
    if not _busy.acquire(blocking=False):
        return None
    job = _new_job("restore")

    def work():
        manifest = read_manifest(zip_path)
        if manifest is None:
            raise ValueError("Not a Nomad Studio backup")
        _update(job, phase="safety-backup", done=0, total=0)
        safety = create_backup(
            data_dir, backup_dir, bool(manifest.get("includesImages")), "before-restore", app_version,
            progress=lambda d, t, f: _update(job, done=d, total=t, file=f),
        )
        _update(job, phase="restoring", done=0, total=0)
        result = restore_backup(data_dir, zip_path, progress=lambda d, t, f: _update(job, done=d, total=t, file=f))
        result["safetyBackup"] = safety["name"]
        return result

    _run(job, work)
    return get_job(job["id"])
