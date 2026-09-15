from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_registry_lock = threading.Lock()

# Separate from _registry_lock (which only guards the physical file I/O in
# _atomic_write/save_registry) — this one serializes the whole logical
# read-modify-write cycle. Without it, two near-simultaneous route handlers
# (e.g. two Settings toggles saved back to back) each call ensure_registry()
# (deliberately lock-free/fast, see its docstring), mutate their OWN
# in-memory copy of the dict, then save_registry() — and whichever finishes
# second overwrites the first's change, silently losing it. registry_path is
# effectively a singleton file for this whole process, so one lock is enough.
_mutation_lock = threading.Lock()


def build_default_registry(
    default_comfy_url: str,
    default_lmstudio_url: str,
    default_context_size: int,
    default_upscale_model_id: str,
    default_upscale_scale: int,
    default_output_dir: str = "",
) -> dict[str, Any]:
    return {
        "activeImportId": None,
        "imports": [],
        "settings": {
            "comfyApiUrl": default_comfy_url,
            "lmStudioApiUrl": default_lmstudio_url,
            "lmStudioModel": "",
            "lmStudioModels": [],
            "lmStudioFavoriteModels": [],
            "lmStudioShowFavoritesOnly": False,
            "lmStudioAutoDisconnect": False,
            "lmStudioContextSize": default_context_size,
            "lmStudioOutputLog": [],
            "outputDir": default_output_dir,
            "allowConcurrentComfyLmstudio": False,
            "commonQueueComfyLmstudio": False,
        },
        "upscaleSettings": {
            "comfyApiUrl": default_comfy_url,
            "modelId": default_upscale_model_id,
            "scale": default_upscale_scale,
        },
    }


def _read_json_safe(path: Path) -> dict[str, Any] | None:
    """Read and parse a JSON file, returning None on failure."""
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        return json.loads(raw)
    except Exception:
        logger.warning("Failed to parse JSON from %s", path)
        return None


def ensure_registry(
    registry_path: Path, default_data: dict[str, Any]
) -> dict[str, Any]:
    # Reads don't hold the global lock — they're fast and a concurrent write using
    # atomic-rename means we either see the old or new complete file, never a partial write.
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    # Try main file first
    data = _read_json_safe(registry_path)
    if data is not None:
        return data

    # Main file missing or corrupt — try backup
    backup_path = registry_path.with_suffix(".json.bak")
    data = _read_json_safe(backup_path)
    if data is not None:
        logger.warning(
            "Registry corrupt/missing, restored from backup: %s", backup_path
        )
        # Acquire lock only for the write
        with _registry_lock:
            _atomic_write(registry_path, data)
        return data

    # No backup either — use defaults and persist them
    with _registry_lock:
        # Re-check under lock to avoid double-init race
        data = _read_json_safe(registry_path)
        if data is not None:
            return data
        _atomic_write(registry_path, default_data)
    return default_data


def _atomic_write(
    registry_path: Path, data: dict[str, Any], fsync: bool = True
) -> None:
    """Write JSON atomically: write to temp file then rename."""
    content = json.dumps(data, indent=2)
    dir_path = registry_path.parent
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(dir_path), suffix=".tmp", prefix=".registry_"
        )
        try:
            os.write(fd, content.encode("utf-8"))
            if fsync:
                os.fsync(fd)
        finally:
            os.close(fd)
        # On Windows, os.replace is atomic if on the same volume
        os.replace(tmp_path, str(registry_path))
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def save_registry(registry_path: Path, data: dict[str, Any]) -> None:
    with _registry_lock:
        # Backup without fsync — convenience copy, not critical path
        if registry_path.exists():
            backup_path = registry_path.with_suffix(".json.bak")
            try:
                existing = _read_json_safe(registry_path)
                if existing is not None:
                    _atomic_write(backup_path, existing, fsync=False)
            except Exception:
                logger.warning("Failed to create registry backup")

        _atomic_write(registry_path, data)
