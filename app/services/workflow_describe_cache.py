"""workflow_describe_cache — LM Studio describe cache helpers."""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Describe cache helpers
# ---------------------------------------------------------------------------


def _describe_cache_key(image_hash: str, describe_type: str) -> str:
    return f"{str(image_hash or '').strip()}:{str(describe_type or '').strip().lower()}"


def _get_describe_cache(settings: dict[str, Any]) -> dict[str, Any]:
    cache = settings.get("lmStudioDescribeCache")
    if isinstance(cache, dict):
        return cache
    return {}


def _describe_cache_get(
    settings: dict[str, Any], image_hash: str, describe_type: str
) -> dict[str, Any] | None:
    cache = _get_describe_cache(settings)
    key = _describe_cache_key(image_hash, describe_type)
    entry = cache.get(key)
    if isinstance(entry, dict):
        return entry
    return None
