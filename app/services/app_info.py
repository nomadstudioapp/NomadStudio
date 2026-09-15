"""What this running copy of Nomad Studio is: version, portable or dev.

A portable build ships ``portable.json`` next to the ``app`` package (see
docs/APP_UPDATES.md §2). A checkout of the repo has none and reports itself
as ``dev``. Read once at import: the file only changes when ``app/`` is
replaced by an update, which restarts the process anyway.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PORTABLE_FILE = Path(__file__).resolve().parents[2] / "portable.json"
STARTED_AT = time.time()


def _read_portable() -> dict[str, Any] | None:
    if not PORTABLE_FILE.is_file():
        return None
    try:
        data = json.loads(PORTABLE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A broken portable.json must not stop the app from starting — the
        # health check would then fail and trigger a pointless rollback.
        logger.exception("app_info: could not read %s", PORTABLE_FILE)
        return None
    return data if isinstance(data, dict) else None


_PORTABLE = _read_portable()


def health() -> dict[str, Any]:
    """Payload for GET /api/health. No I/O and no external services."""
    portable = _PORTABLE or {}
    return {
        "status": "ok",
        "version": str(portable.get("version") or "dev"),
        "portable": _PORTABLE is not None,
        "platform": portable.get("platform"),
        "data_schema": portable.get("data_schema"),
        "uptime_s": round(time.time() - STARTED_AT, 1),
    }
