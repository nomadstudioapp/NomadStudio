"""Update the portable app from a release ZIP (docs/APP_UPDATES.md §6.3, §7).

The ZIP comes from the user (Settings › Updates › Update from file), which
also lets internal builds be tested while the repo is private, or from GitHub
Releases, found and downloaded by update_check.py. Both end in run_job().

Folder layout of a portable install (the folder the user unzipped)::

    NomadStudio/                 ROOT
    ├── NomadStudio.bat          launcher (replaced by the new version's copy)
    ├── app/                     the program — REPO_DIR, replaced as a whole
    ├── app.new/                 prepared update (extracted ZIP)
    ├── app.old/                 previous version, kept until the next update
    ├── .nomad-update/           apply script copied out of app/ before the switch
    ├── update-pending.json      prepared and waiting for the restart
    ├── update-result.json       what the last apply did (read by Settings)
    └── update.log

The user's data is not in there (app/paths.py), so replacing ``app/`` never
touches it; a data backup is made anyway before every update (§7.2).

Steps:
1. ``inspect_zip``   — structure, portable.json, platform, newer version.
2. ``start_prepare`` — extract ``app/`` to ``app.new/`` and back up the data
   (background job).
3. ``apply``         — start ``launcher/apply_update.ps1`` detached and exit.
   The script waits for this process to end, swaps the folders, starts the
   new version and checks ``/api/health``; if the new version does not
   answer, it puts the old one back (§7.5).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .. import paths
from . import app_info, backup_service

logger = logging.getLogger(__name__)

EXIT_CODE_UPDATE = 3  # NomadStudio.bat closes its window instead of pausing
MAX_UPLOAD_BYTES = 1 << 30
MAX_UNPACKED_BYTES = 4 << 30
MAX_FILES = 200_000
REQUIRED_COMMON = ("app/portable.json", "app/app.py", "app/app/__init__.py")
# Per platform: the root launcher and the apply script the release must carry.
# Windows ships a ZIP and a PowerShell script; Linux and macOS a .tar.gz (it
# keeps the executable bits) and the bash twin, apply_update.sh (2026-10-04).
PLATFORM_FILES = {
    "windows-x64": ("NomadStudio.bat", "apply_update.ps1"),
    "linux-x64": ("NomadStudio.sh", "apply_update.sh"),
    "macos-arm64": ("NomadStudio.command", "apply_update.sh"),
}
UPLOAD_TTL_S = 6 * 3600


def _platform_files(platform: str | None) -> tuple[str, str]:
    return PLATFORM_FILES.get(str(platform or ""), PLATFORM_FILES["windows-x64"])

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


class UpdateError(ValueError):
    """An update that cannot go ahead; the message is shown to the user."""


# ── Versions ────────────────────────────────────────────────────────────────


def parse_version(version: str) -> tuple[tuple[int, int, int], tuple[tuple[int, Any], ...] | None]:
    m = _SEMVER_RE.match(str(version or "").strip())
    if not m:
        raise ValueError(f"not a version: {version!r}")
    core = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    pre = None
    if m.group(4):
        pre = tuple((0, int(p)) if p.isdigit() else (1, p) for p in m.group(4).split("."))
    return core, pre


def compare_versions(a: str, b: str) -> int:
    """SemVer precedence: -1 if a < b, 0 if equal, 1 if a > b.
    1.0.0-internal.5 < 1.0.0-internal.6 < 1.0.0."""
    (ca, pa), (cb, pb) = parse_version(a), parse_version(b)
    if ca != cb:
        return -1 if ca < cb else 1
    if pa == pb:
        return 0
    if pa is None:
        return 1
    if pb is None:
        return -1
    for x, y in zip(pa, pb):
        if x != y:
            return -1 if x < y else 1
    return -1 if len(pa) < len(pb) else (1 if len(pa) > len(pb) else 0)


# ── This install ────────────────────────────────────────────────────────────


def root_dir() -> Path:
    return paths.REPO_DIR.parent


def current() -> dict[str, Any]:
    portable = app_info._PORTABLE or {}
    return {
        "version": str(portable.get("version") or "dev"),
        "platform": portable.get("platform"),
        "commit": portable.get("commit"),
        "portable": app_info._PORTABLE is not None,
    }


def unsupported_reason() -> str | None:
    """Why this copy cannot update itself (None when it can)."""
    if app_info._PORTABLE is None:
        return "dev"
    if not sys.platform.startswith(("win", "linux", "darwin")):
        return "platform"
    if paths.REPO_DIR.name != "app":
        return "layout"
    return None


def _updates_dir() -> Path:
    path = paths.UPDATES_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


# ── Upload + inspect ────────────────────────────────────────────────────────


def _cleanup_uploads() -> None:
    now = time.time()
    for item in _updates_dir().glob("upload-*.zip"):
        try:
            if now - item.stat().st_mtime > UPLOAD_TTL_S:
                item.unlink()
        except OSError:
            pass


def save_upload(stream) -> tuple[str, Path]:
    _cleanup_uploads()
    token = uuid.uuid4().hex
    path = _updates_dir() / f"upload-{token}.zip"
    written = 0
    with path.open("wb") as fh:
        while True:
            chunk = stream.read(1 << 20)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                fh.close()
                path.unlink(missing_ok=True)
                raise UpdateError("The file is larger than 1 GB: it is not a Nomad Studio release")
            fh.write(chunk)
    return token, path


def upload_path(token: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{32}", str(token or "")):
        return None
    path = paths.UPDATES_DIR / f"upload-{token}.zip"
    return path if path.is_file() else None


def discard_upload(token: str) -> None:
    path = upload_path(token)
    if path:
        path.unlink(missing_ok=True)


def _is_gzip(path: Path) -> bool:
    with path.open("rb") as fh:
        return fh.read(2) == b"\x1f\x8b"


def _release_entries(path: Path) -> list[tuple[str, int, str]]:
    """(name, size, kind) of every member of a release archive — kind is
    "file", "dir" or "link". ZIP (Windows) or .tar.gz (Linux, macOS), told
    apart by content, not by the upload's name."""
    if _is_gzip(path):
        try:
            with tarfile.open(path, "r:gz") as tf:
                out = []
                for m in tf.getmembers():
                    name = m.name[2:] if m.name.startswith("./") else m.name
                    kind = "dir" if m.isdir() else ("file" if m.isfile() else "link")
                    out.append((name.rstrip("/"), m.size if m.isfile() else 0, kind))
                return out
        except (tarfile.TarError, OSError, EOFError):
            raise UpdateError("This file is not a valid release archive") from None
    try:
        with zipfile.ZipFile(path) as zf:
            out = []
            for i in zf.infolist():
                is_link = (i.external_attr >> 16) & 0o170000 == 0o120000  # Unix symlink bit
                kind = "link" if is_link else ("dir" if i.is_dir() else "file")
                out.append((i.filename.rstrip("/"), i.file_size, kind))
            return out
    except (zipfile.BadZipFile, OSError):
        raise UpdateError("This file is not a valid ZIP or .tar.gz") from None


def _read_member(path: Path, name: str) -> bytes:
    if _is_gzip(path):
        with tarfile.open(path, "r:gz") as tf:
            for m in tf.getmembers():
                if m.name in (name, "./" + name) and m.isfile():
                    return tf.extractfile(m).read()
        raise KeyError(name)
    with zipfile.ZipFile(path) as zf:
        return zf.read(name)


def _member_ok(name: str, kind: str, launcher: str) -> bool:
    if not name or "\\" in name or name.startswith("/") or ":" in name.split("/")[0]:
        return False
    parts = PurePosixPath(name).parts
    if ".." in parts:
        return False
    if kind == "link":  # links could point outside the install
        return False
    return name == launcher or name == "app" or name.startswith("app/")


def inspect_zip(zip_path: Path, installed: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a release archive (ZIP or .tar.gz) against this install.
    Raises UpdateError. The name stays: it is the API the routes call."""
    installed = installed or current()
    launcher, script = _platform_files(installed.get("platform"))
    required = (launcher, *REQUIRED_COMMON, "app/launcher/" + script)
    entries = _release_entries(zip_path)
    names = {n for n, _, _ in entries}
    missing = [m for m in required if m not in names]
    if missing:
        raise UpdateError("This file is not a Nomad Studio release for this system (missing " + ", ".join(missing) + ")")
    if len(entries) > MAX_FILES:
        raise UpdateError("The release has too many files")
    bad = [n for n, _, kind in entries if not _member_ok(n, kind, launcher)]
    if bad:
        raise UpdateError(f"The release contains unexpected paths: {bad[:3]}")
    unpacked = sum(size for _, size, _ in entries)
    if unpacked > MAX_UNPACKED_BYTES:
        raise UpdateError("The release is too large once extracted")
    infos = entries
    try:
        portable = json.loads(_read_member(zip_path, "app/portable.json").decode("utf-8"))
    except (ValueError, KeyError):
        raise UpdateError("The release has a damaged portable.json") from None
    version = str(portable.get("version") or "")
    try:
        parse_version(version)
    except ValueError:
        raise UpdateError(f"The release has an invalid version: {version!r}") from None
    if portable.get("platform") != installed.get("platform"):
        raise UpdateError(f"This release is for {portable.get('platform')}, this install is {installed.get('platform')}")
    cmp = compare_versions(version, installed["version"]) if installed.get("version") not in (None, "dev") else 1
    if cmp <= 0:
        raise UpdateError(
            f"Version {version} is not newer than the installed {installed.get('version')}"
            if cmp < 0 else f"Version {version} is already installed")
    return {
        "version": version,
        "from": installed.get("version"),
        "platform": portable.get("platform"),
        "commit": portable.get("commit"),
        "builtAt": portable.get("built_at"),
        "channel": portable.get("channel"),
        "files": len(infos),
        "unpackedBytes": unpacked,
        "zipBytes": zip_path.stat().st_size,
    }


# ── Prepare (background job) ────────────────────────────────────────────────

_job: dict[str, Any] | None = None
_job_lock = threading.Lock()


def get_job() -> dict[str, Any] | None:
    with _job_lock:
        return dict(_job) if _job else None


def _set_job(**fields: Any) -> None:
    with _job_lock:
        if _job is not None:
            _job.update(fields)


def pending() -> dict[str, Any] | None:
    if unsupported_reason():
        return None
    path = root_dir() / "update-pending.json"
    if not path.is_file() or not (root_dir() / "app.new").is_dir():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def last_result() -> dict[str, Any] | None:
    if unsupported_reason():
        return None
    path = root_dir() / "update-result.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and not data.get("dismissed") else None


def dismiss_result() -> None:
    path = root_dir() / "update-result.json"
    data = last_result()
    if data is not None:
        data["dismissed"] = True
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _extract_app(zip_path: Path, dest: Path) -> None:
    tmp = dest.with_name(dest.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    if _is_gzip(zip_path):
        # .tar.gz (Linux, macOS): the "data" filter refuses anything that would
        # land outside tmp and keeps the executable bits the bundled Python and
        # launchers need — the reason these builds are not ZIPs.
        with tarfile.open(zip_path, "r:gz") as tf:
            members = []
            for m in tf.getmembers():
                name = m.name[2:] if m.name.startswith("./") else m.name
                if name.startswith("app/") and m.isfile():
                    m.name = name[len("app/"):]
                    members.append(m)
            total = sum(m.size for m in members) or 1
            done = 0
            for m in members:
                tf.extract(m, tmp, filter="data")
                done += m.size
                _set_job(done=done, total=total)
        shutil.rmtree(dest, ignore_errors=True)
        os.replace(tmp, dest)
        return
    with zipfile.ZipFile(zip_path) as zf:
        members = [i for i in zf.infolist() if i.filename.startswith("app/") and not i.is_dir()]
        total = sum(i.file_size for i in members) or 1
        done = 0
        for info in members:
            target = tmp / info.filename[len("app/"):]
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            done += info.file_size
            _set_job(done=done, total=total)
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(tmp, dest)


def set_job_progress(**fields: Any) -> None:
    _set_job(**fields)


def run_job(version: str, phase: str, work, auto: bool = False) -> dict[str, Any]:
    """Run ``work()`` (returns the pending-update info) as THE update job in
    the background. One at a time: preparing a chosen file and downloading a
    release (update_check.py) share it, so Settings follows both the same way."""
    global _job
    reason = unsupported_reason()
    if reason:
        raise UpdateError("This copy of Nomad Studio cannot update itself (" + reason + ")")
    if pending():
        raise UpdateError("An update is already prepared: install it or discard it first")
    with _job_lock:
        if _job and _job.get("state") == "running":
            raise UpdateError("An update is already being prepared")
        _job = {"id": uuid.uuid4().hex[:12], "state": "running", "phase": phase, "done": 0, "total": 0,
                "version": version, "auto": auto, "error": "", "result": None}

    def runner() -> None:
        try:
            info = work()
            _set_job(state="done", phase="ready", result=info)
        except Exception as exc:  # noqa: BLE001 — shown in Settings
            logger.exception("preparing update %s failed", version)
            shutil.rmtree(root_dir() / "app.new", ignore_errors=True)
            _set_job(state="error", error=str(exc))

    threading.Thread(target=runner, daemon=True, name="update-prepare").start()
    return get_job() or {}


def prepare_from(zip_path: Path, summary: dict[str, Any], backup_dir: Path) -> dict[str, Any]:
    """Extract a checked release next to the install, back up the data and
    write update-pending.json. Runs inside run_job."""
    root = root_dir()
    _set_job(phase="extracting", done=0, total=0)
    _extract_app(zip_path, root / "app.new")
    script_dir = root / ".nomad-update"
    script_dir.mkdir(exist_ok=True)
    script = _platform_files(current().get("platform"))[1]
    shutil.copy2(root / "app.new" / "launcher" / script, script_dir / script)
    _set_job(phase="backup", done=0, total=0)
    if backup_service.is_busy():
        raise UpdateError("A backup or restore is running; try again when it finishes")
    backup = backup_service.create_backup(paths.DATA_DIR, backup_dir, False, "before-update", summary["from"])
    info = {"from": summary["from"], "to": summary["version"], "commit": summary.get("commit"),
            "prepared_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "backup": str(backup_dir / backup["name"])}
    (root / "update-pending.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    zip_path.unlink(missing_ok=True)
    return info


def start_prepare(token: str, backup_dir: Path) -> dict[str, Any]:
    reason = unsupported_reason()
    if reason:
        raise UpdateError("This copy of Nomad Studio cannot update itself (" + reason + ")")
    zip_path = upload_path(token)
    if zip_path is None:
        raise UpdateError("The upload expired. Choose the release ZIP again.")
    summary = inspect_zip(zip_path)
    return run_job(summary["version"], "extracting", lambda: prepare_from(zip_path, summary, backup_dir))


def discard_prepared() -> None:
    root = root_dir()
    shutil.rmtree(root / "app.new", ignore_errors=True)
    shutil.rmtree(root / "app.new.partial", ignore_errors=True)
    (root / "update-pending.json").unlink(missing_ok=True)


# ── Apply ───────────────────────────────────────────────────────────────────


def apply(port: int) -> dict[str, Any]:
    """Hand over to the apply script and exit this process (§7.3)."""
    reason = unsupported_reason()
    if reason:
        raise UpdateError("This copy of Nomad Studio cannot update itself (" + reason + ")")
    info = pending()
    if info is None:
        raise UpdateError("There is no prepared update")
    root = root_dir()
    launcher, script_name = _platform_files(current().get("platform"))
    script = root / ".nomad-update" / script_name
    if not script.is_file():
        raise UpdateError("The prepared update is incomplete; prepare it again")
    (root / "update-result.json").unlink(missing_ok=True)
    if not sys.platform.startswith("win"):
        # Linux / macOS: the bash twin, in a session of its own so it survives
        # this process and the terminal it may have been started from.
        cmd = ["/bin/bash", str(script), str(root), str(os.getpid()), str(info["to"]),
               str(info.get("from") or ""), str(port), launcher]
        try:
            subprocess.Popen(cmd, cwd=str(root), start_new_session=True, close_fds=True,  # noqa: S603 — fixed script, local app
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            raise UpdateError("Could not start the update script") from None
        logger.info("update %s → %s: handing over to %s", info.get("from"), info["to"], script)
        threading.Timer(1.0, lambda: os._exit(EXIT_CODE_UPDATE)).start()
        return info
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script),
        "-Root", str(root), "-WaitPid", str(os.getpid()), "-From", str(info.get("from") or ""),
        "-To", str(info["to"]), "-Port", str(port),
    ]
    # A hidden console of its own (CREATE_NO_WINDOW), not DETACHED_PROCESS:
    # PowerShell started without any console exits at once (measured). Break
    # away from the parent's job when Windows allows it, so closing the
    # launcher window cannot take the script down with it.
    base_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    for flags in (base_flags | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0), base_flags):
        try:
            subprocess.Popen(cmd, cwd=str(root), creationflags=flags, close_fds=True,  # noqa: S603 — fixed script, local app
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            break
        except OSError:
            if flags == base_flags:
                raise UpdateError("Could not start the update script") from None
    logger.info("update %s → %s: handing over to %s", info.get("from"), info["to"], script)
    # Give the HTTP response time to reach the browser, then exit so the
    # script can rename app/ (Windows keeps a running program's folder locked).
    threading.Timer(1.0, lambda: os._exit(EXIT_CODE_UPDATE)).start()
    return info

