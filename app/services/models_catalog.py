"""Catalog of model files → where to download them (PACKAGE_FORMAT.md §8.2.2, D15).

A package says WHICH model it needs (requires.models: name, folder, size,
sha256); this catalog says WHERE it can be downloaded. Addresses expire —
repos move, models become gated — and a package already sold can't be
republished for every broken link, so the addresses live here, in one place:

* ``app/static/data/models_catalog.json`` ships with the app (works offline);
* ``models.json`` in the public Nomad Studio Packs repo is the live copy,
  fetched at most once a day (or on "Check again") into
  ``<data>/cache/models_catalog.json``. Until that repo exists the setting
  ``modelsCatalogUrl`` is empty and only the bundled copy is used.

Entries are keyed by SHA-256 (the file's identity) and also found by name.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from app.paths import DATA_DIR

from .http_client import http_json

logger = logging.getLogger(__name__)

BUNDLED = Path(__file__).resolve().parents[1] / "static" / "data" / "models_catalog.json"
CACHE = DATA_DIR / "cache" / "models_catalog.json"
REFRESH_SECONDS = 24 * 3600
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

_lock = threading.Lock()
_state: dict[str, Any] = {"catalog": None, "loaded_at": 0.0, "source": ""}


def _valid(data: Any) -> bool:
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        return False
    for m in data["models"]:
        if not isinstance(m, dict) or not isinstance(m.get("sources"), list):
            return False
        if m.get("sha256") is not None and not _SHA_RE.match(str(m["sha256"])):
            return False
        if any(not str((s or {}).get("url", "")).startswith("https://") for s in m["sources"]):
            return False
    return True


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if _valid(data) else None


def _newest(*catalogs: dict[str, Any] | None) -> dict[str, Any] | None:
    good = [c for c in catalogs if c]
    return max(good, key=lambda c: str(c.get("updated", ""))) if good else None


def load(remote_url: str = "", force: bool = False) -> dict[str, Any]:
    """The catalog to use: the newest valid one of bundled / cached / remote.
    The remote copy is fetched when ``force`` or when the cache is older than
    a day; any failure falls back silently to what is already there."""
    with _lock:
        fresh = time.monotonic() - _state["loaded_at"] < 60
        if _state["catalog"] is not None and fresh and not force:
            return _state["catalog"]
        bundled = _read(BUNDLED)
        cached = _read(CACHE)
        remote = None
        stale = not CACHE.exists() or time.time() - CACHE.stat().st_mtime > REFRESH_SECONDS
        if remote_url and (force or stale):
            try:
                data = http_json(remote_url, timeout=15)
                if _valid(data):
                    remote = data
                    CACHE.parent.mkdir(parents=True, exist_ok=True)
                    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
                else:
                    logger.warning("models catalog at %s is not valid — ignored", remote_url)
            except Exception as exc:  # noqa: BLE001 — offline is normal
                logger.info("models catalog: could not fetch %s (%s)", remote_url, exc)
        catalog = _newest(remote, cached, bundled) or {"schema_version": 1, "models": []}
        _state.update(catalog=catalog, loaded_at=time.monotonic(),
                      source="remote" if catalog is remote else "cache" if catalog is cached else "bundled")
        return catalog


def source() -> str:
    return _state.get("source") or "bundled"


def lookup(catalog: dict[str, Any], name: str, sha256: str | None = None, size: int | None = None) -> dict[str, Any] | None:
    """Entry for a file: by SHA-256 first (identity), else by name — and then,
    when the package gave a size, only an entry of that exact size."""
    models = catalog.get("models") or []
    if sha256:
        # The current revision, or an earlier one the publisher replaced
        # (previous_sha256) — a package built against the old file still
        # finds its model, and gets the current one.
        hit = next((m for m in models if m.get("sha256") == sha256
                    or sha256 in (m.get("previous_sha256") or [])), None)
        if hit:
            return hit
    lname = str(name or "").lower()
    for m in models:
        if lname in {str(n).lower() for n in m.get("names") or []}:
            if size and m.get("size") and m["size"] != size:
                continue
            return m
    return None
