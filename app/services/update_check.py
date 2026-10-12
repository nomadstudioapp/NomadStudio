"""Find, download and check new releases on GitHub (docs/APP_UPDATES.md §5–6).

What the user sees: nothing until a new version is downloaded and prepared;
then a notice "Nomad Studio X is ready" with "Restart and update". Never
installs or restarts by itself (U4).

    check()           at most once a day (or "Check now"): GET the latest
                      Release of portable.json's update_repo — no credentials,
                      no identifiers (U7), ETag so an unchanged answer is free.
    start_download()  download the ZIP of this platform (resumable .part),
                      check its sha256 and hand it to update_service.run_job,
                      the same pipeline as "Update from file".
    start_background() the daily loop that does both when the settings allow.

Checksum: the sha256 GitHub publishes for every release asset ("digest") and,
when the Release carries it, the line of SHA256SUMS.txt (the build writes it).
Both come over HTTPS from the project's own repo. The Ed25519 signature of
§6.3 comes later, with the official key (§3).

Test source before the repo is public (§11): NOMAD_UPDATE_SOURCE =
``github:<owner>/<repo>`` or ``file:///D:/tests/updates/`` — a folder with
latest.json (a GitHub release object; asset URLs may be bare file names in
that folder) and, for the beta channel, releases.json (a list of them).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .. import paths
from . import app_info, update_service
from .update_service import UpdateError, compare_versions, parse_version

logger = logging.getLogger(__name__)

CHECK_EVERY_S = 24 * 3600
FIRST_CHECK_DELAY_S = 30
LOOP_EVERY_S = 3600
TIMEOUT_S = 20
MAX_NOTES_BYTES = 256 * 1024

_state_lock = threading.Lock()
_check_lock = threading.Lock()
_started = False

DEFAULT_STATE: dict[str, Any] = {
    "auto_check": True,
    "auto_download": True,
    "skipped": [],
    "last_check": 0,
    "last_error": "",
    "etag": "",
    "etag_url": "",
    "latest": None,
    "auto_attempt": None,  # {"version", "at"}: a failed automatic download waits a day
}


# ── State (data/updates/state.json) ──────────────────────────────────────────


def _state_path() -> Path:
    return paths.UPDATES_DIR / "state.json"


def _still_newer(latest: dict[str, Any] | None) -> dict[str, Any] | None:
    """The saved latest release, unless it is no longer newer than this copy
    (after updating, state.json still names the version now installed)."""
    if not latest:
        return None
    installed = str(update_service.current().get("version") or "dev")
    try:
        if installed != "dev" and compare_versions(latest["version"], installed) <= 0:
            return None
    except (KeyError, ValueError):
        return None
    return latest


def load_state() -> dict[str, Any]:
    with _state_lock:
        try:
            data = json.loads(_state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    state = dict(DEFAULT_STATE)
    if isinstance(data, dict):
        state.update({k: v for k, v in data.items() if k in DEFAULT_STATE})
    state["latest"] = _still_newer(state.get("latest"))
    return state


def _update_state(**fields: Any) -> dict[str, Any]:
    state = load_state()
    state.update(fields)
    with _state_lock:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    return state


def set_settings(auto_check: bool | None = None, auto_download: bool | None = None) -> None:
    fields: dict[str, Any] = {}
    if auto_check is not None:
        fields["auto_check"] = bool(auto_check)
    if auto_download is not None:
        fields["auto_download"] = bool(auto_download)
    if fields:
        _update_state(**fields)


def skip(version: str) -> None:
    state = load_state()
    skipped = [v for v in state["skipped"] if v != version] + [version]
    _update_state(skipped=skipped[-20:])


def unskip(version: str) -> None:
    state = load_state()
    _update_state(skipped=[v for v in state["skipped"] if v != version])


# ── Where to look ────────────────────────────────────────────────────────────


def _portable() -> dict[str, Any]:
    return app_info._PORTABLE or {}


def channel() -> str:
    ch = str(_portable().get("channel") or "stable")
    return ch if ch in ("stable", "beta", "store") else "stable"


def source() -> str:
    env = os.getenv("NOMAD_UPDATE_SOURCE", "").strip()
    if env:
        return env
    repo = str(_portable().get("update_repo") or "").strip()
    return f"github:{repo}" if repo else ""


def disabled_reason() -> str | None:
    """Why this copy does not look for updates (None when it does)."""
    reason = update_service.unsupported_reason()
    if reason:
        return reason
    if channel() == "store":
        return "store"
    if not source():
        return "no-source"
    return None


def _user_agent() -> str:
    return f"NomadStudio/{update_service.current().get('version') or 'dev'}"


def _local_path(url: str) -> Path:
    parsed = urlparse(url)
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]  # file:///D:/x → D:/x
    return Path(path)


def _http_get(url: str, etag: str = "", accept: str = "application/vnd.github+json") -> tuple[int, bytes, str]:
    """(status, body, etag). 304 → empty body. file:// reads the file."""
    if url.startswith("file:"):
        return 200, _local_path(url).read_bytes(), ""
    headers = {"Accept": accept, "User-Agent": _user_agent()}
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:  # noqa: S310 — https/file URLs we build
            return res.status, res.read(), res.headers.get("ETag", "")
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, b"", etag
        raise


def _releases_url(src: str, ch: str) -> str:
    if src.startswith("github:"):
        repo = src[len("github:"):].strip("/")
        if ch == "beta":
            return f"https://api.github.com/repos/{repo}/releases?per_page=10"
        return f"https://api.github.com/repos/{repo}/releases/latest"
    if src.startswith("file:"):
        folder = src if src.endswith("/") else src + "/"
        if ch == "beta" and _local_path(folder + "releases.json").is_file():
            return folder + "releases.json"
        return folder + "latest.json"
    raise UpdateError(f"Unknown update source: {src}")


def _asset_url(src: str, url: str) -> str:
    """file:// sources may name assets by their bare file name."""
    if src.startswith("file:") and "://" not in url:
        return (src if src.endswith("/") else src + "/") + url
    return url


# ── Check ────────────────────────────────────────────────────────────────────


def _pick(releases: list[dict[str, Any]], installed: str, platform: str, ch: str, src: str) -> dict[str, Any] | None:
    """The newest release for this platform that is newer than ``installed``."""
    best: dict[str, Any] | None = None
    for rel in releases:
        if not isinstance(rel, dict) or rel.get("draft"):
            continue
        if rel.get("prerelease") and ch != "beta":
            continue
        version = str(rel.get("tag_name") or "").lstrip("v")
        try:
            parse_version(version)
        except ValueError:
            continue
        if installed not in ("", "dev") and compare_versions(version, installed) <= 0:
            continue
        if best and compare_versions(version, best["version"]) <= 0:
            continue
        assets = {str(a.get("name")): a for a in rel.get("assets") or [] if isinstance(a, dict)}
        prefix = f"NomadStudio-{version}-{platform}."
        archive = next((a for n, a in assets.items() if n.startswith(prefix) and n.endswith((".zip", ".tar.gz"))), None)
        if archive is None:
            logger.info("release %s has no archive for %s", version, platform)
            continue
        digest = str(archive.get("digest") or "")
        sums = assets.get("SHA256SUMS.txt")
        notes = assets.get("release-notes.json")
        best = {
            "version": version,
            "tag": rel.get("tag_name"),
            "name": rel.get("name") or f"Nomad Studio {version}",
            "url": rel.get("html_url") or "",
            "publishedAt": rel.get("published_at") or "",
            "body": str(rel.get("body") or "")[:4000],
            "asset": {
                "name": archive["name"],
                "url": _asset_url(src, str(archive.get("browser_download_url") or "")),
                "size": int(archive.get("size") or 0),
                "sha256": digest[len("sha256:"):].lower() if digest.startswith("sha256:") else "",
            },
            "sumsUrl": _asset_url(src, str(sums.get("browser_download_url") or "")) if sums else "",
            "notesUrl": _asset_url(src, str(notes.get("browser_download_url") or "")) if notes else "",
        }
    return best


def _fetch_notes(url: str) -> dict[str, Any] | None:
    """release-notes.json (§3.1): highlights per language. Best effort."""
    if not url:
        return None
    try:
        _, body, _ = _http_get(url, accept="application/octet-stream")
        if len(body) > MAX_NOTES_BYTES:
            return None
        data = json.loads(body.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 — notes are optional
        logger.info("release notes not available at %s", url)
        return None


def check(force: bool = False) -> dict[str, Any]:
    """Ask GitHub (or the test source) for a newer release. Quiet on
    failure: the error is logged and kept for Settings, never raised."""
    if disabled_reason():
        return load_state()
    with _check_lock:
        state = load_state()
        if not force and time.time() - float(state.get("last_check") or 0) < CHECK_EVERY_S:
            return state
        installed = update_service.current()
        version = str(installed.get("version") or "dev")
        src = source()
        try:
            url = _releases_url(src, channel())
            etag = state["etag"] if state.get("etag_url") == url else ""
            status, body, new_etag = _http_get(url, etag)
            if status == 304:
                latest = state.get("latest")  # load_state already dropped it if installed
            else:
                data = json.loads(body.decode("utf-8"))
                releases = data if isinstance(data, list) else [data]
                latest = _pick(releases, version, str(installed.get("platform") or ""), channel(), src)
                if latest:
                    latest["notes"] = _fetch_notes(latest.pop("notesUrl", ""))
            return _update_state(last_check=time.time(), last_error="", etag=new_etag, etag_url=url, latest=latest)
        except Exception as exc:  # noqa: BLE001 — no network, rate limit, bad JSON…
            logger.info("update check failed: %s", exc)
            return _update_state(last_check=time.time(), last_error=str(exc)[:300])


# ── Download ─────────────────────────────────────────────────────────────────


def _expected_sha256(release: dict[str, Any]) -> list[str]:
    """Every checksum the release publishes for its archive (at least one)."""
    found = []
    if release["asset"].get("sha256"):
        found.append(release["asset"]["sha256"])
    if release.get("sumsUrl"):
        _, body, _ = _http_get(release["sumsUrl"], accept="application/octet-stream")
        for line in body.decode("utf-8", "replace").splitlines():
            parts = line.strip().split()
            if len(parts) == 2 and parts[1].lstrip("*") == release["asset"]["name"]:
                found.append(parts[0].lower())
    if not found:
        raise UpdateError("The release publishes no checksum for its archive, so it cannot be checked")
    return found


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(release: dict[str, Any]) -> Path:
    """Download the release archive to data/updates/downloads (resuming a
    .part left by an earlier try) and check its sha256. Returns the file."""
    asset = release["asset"]
    name = os.path.basename(asset["name"])
    folder = paths.UPDATES_DIR / "downloads"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.iterdir():  # other versions left behind
        if not old.name.startswith(name):
            try:
                old.unlink()
            except OSError:
                pass
    final = folder / name
    part = folder / (name + ".part")
    size = int(asset.get("size") or 0)
    # The archive, its extraction and app.old live side by side for a while.
    free = shutil.disk_usage(update_service.root_dir()).free
    if size and free < size * 3:
        raise UpdateError(f"Not enough free space: the update needs about {size * 3 // 2**20} MB")
    expected = _expected_sha256(release)

    if not final.is_file():
        url = asset["url"]
        if url.startswith("file:"):
            shutil.copyfile(_local_path(url), part)
            update_service.set_job_progress(done=size, total=size)
        else:
            have = part.stat().st_size if part.is_file() else 0
            headers = {"User-Agent": _user_agent(), "Accept": "application/octet-stream"}
            if have:
                headers["Range"] = f"bytes={have}-"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as res:  # noqa: S310 — the release's own URL
                if have and res.status != 206:
                    have = 0  # the server ignored Range: start again
                total = have + int(res.headers.get("Content-Length") or 0) or size
                done = have
                with part.open("ab" if have else "wb") as fh:
                    for chunk in iter(lambda: res.read(1 << 20), b""):
                        fh.write(chunk)
                        done += len(chunk)
                        update_service.set_job_progress(done=done, total=total)
        os.replace(part, final)

    update_service.set_job_progress(phase="verifying", done=0, total=0)
    actual = _sha256(final)
    if any(actual != e for e in expected):
        final.unlink(missing_ok=True)
        raise UpdateError("The downloaded file does not match the release checksum; it was deleted")
    return final


def start_download(backup_dir: Path, auto: bool = False) -> dict[str, Any]:
    """Download the latest release found by check() and prepare it, as the
    update job Settings follows (phases downloading → verifying → extracting
    → backup → ready)."""
    release = load_state().get("latest")
    if not release:
        raise UpdateError("There is no new version to download")

    def work() -> dict[str, Any]:
        path = download(release)
        try:
            summary = update_service.inspect_zip(path)
            if summary["version"] != release["version"]:
                raise UpdateError(f"The archive holds version {summary['version']}, not {release['version']}")
        except UpdateError:
            path.unlink(missing_ok=True)
            raise
        info = update_service.prepare_from(path, summary, backup_dir)
        info["notes"] = release.get("notes")
        info["url"] = release.get("url")
        (update_service.root_dir() / "update-pending.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        return info

    if auto:
        _update_state(auto_attempt={"version": release["version"], "at": time.time()})
    return update_service.run_job(release["version"], "downloading", work, auto=auto)


# ── Daily loop ───────────────────────────────────────────────────────────────


def _tick(backup_dir_fn) -> None:
    state = load_state()
    if not state["auto_check"]:
        return
    state = check()
    latest = state.get("latest")
    if not latest or not state["auto_download"] or latest["version"] in state["skipped"]:
        return
    if update_service.pending():
        return
    job = update_service.get_job()
    if job and job.get("state") == "running":
        return
    attempt = state.get("auto_attempt") or {}
    if attempt.get("version") == latest["version"] and time.time() - float(attempt.get("at") or 0) < CHECK_EVERY_S:
        return  # failed today already; the next check tries again
    start_download(backup_dir_fn(), auto=True)


def start_background(backup_dir_fn) -> None:
    """Start the daily check (and automatic download) in a thread. Once per
    process; does nothing in a development copy or a Store install."""
    global _started
    if _started or disabled_reason():
        return
    _started = True

    def loop() -> None:
        time.sleep(FIRST_CHECK_DELAY_S)  # never in the way of startup
        while True:
            try:
                _tick(backup_dir_fn)
            except Exception:  # noqa: BLE001 — logged, retried next hour
                logger.exception("automatic update check failed")
            time.sleep(LOOP_EVERY_S)

    threading.Thread(target=loop, daemon=True, name="update-check").start()


def overview() -> dict[str, Any]:
    """What Settings and the notice need (no URLs or ETags)."""
    state = load_state()
    latest = state.get("latest")
    last = float(state.get("last_check") or 0)
    return {
        "disabled": disabled_reason(),
        "channel": channel(),
        "autoCheck": state["auto_check"],
        "autoDownload": state["auto_download"],
        "lastCheck": datetime.fromtimestamp(last, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if last else "",
        "lastError": state.get("last_error") or "",
        "latest": None if not latest else {
            "version": latest["version"],
            "name": latest.get("name"),
            "url": latest.get("url"),
            "publishedAt": latest.get("publishedAt"),
            "size": latest["asset"].get("size"),
            "notes": latest.get("notes"),
            "body": latest.get("body"),
            "skipped": latest["version"] in state["skipped"],
        },
        "skipped": state["skipped"],
    }
