"""workflow_style_utils — style page / profile image helpers."""
from __future__ import annotations

import base64
from typing import Any
from urllib.parse import unquote

from app.services.workflow_utils import _coerce_int_scalar

# ---------------------------------------------------------------------------
# Style / page helpers
# ---------------------------------------------------------------------------


def _get_next_page_number(pages: list[dict[str, Any]]) -> int:
    if not pages:
        return 1
    existing = set()
    for p in pages:
        try:
            existing.add(int(p.get("id", 0)))
        except (TypeError, ValueError):
            pass
    n = 1
    while n in existing:
        n += 1
    return n


def _get_style_page_entry(style: dict[str, Any], page_id: str) -> dict[str, Any]:
    pid = str(page_id or "").strip()
    if not pid:
        return {}
    page_images = style.get("page_images", {})
    if isinstance(page_images, dict):
        candidate = page_images.get(pid)
        if isinstance(candidate, dict):
            return candidate
    return {}


def _style_has_image_for_page(style: dict[str, Any], page_id: str) -> bool:
    entry = _get_style_page_entry(style, page_id)
    return bool(
        str(entry.get("image_filename", "") or "").strip()
        or str(entry.get("image_url", "") or "").strip()
    )


def _style_preview_page_path(style_id: int, page_id: str) -> str:
    """Returns a relative path like page_1/1.png for use under STYLES_IMAGES_DIR."""
    pid = str(page_id or "page_1").strip() or "page_1"
    return f"{pid}/{int(style_id)}.png"


def _coerce_profile_slot(raw_value: Any) -> int:
    value = _coerce_int_scalar(raw_value)
    if value is None:
        return 1
    return max(1, min(3, int(value)))


def _get_style_profile_entry(
    style: dict[str, Any], profile_slot: int
) -> dict[str, Any]:
    slot = _coerce_profile_slot(profile_slot)
    profile_images = style.get("profile_images", {})
    if isinstance(profile_images, dict):
        candidate = profile_images.get(str(slot))
        if isinstance(candidate, dict):
            return candidate

    if slot == 1:
        return {
            "image_filename": str(style.get("image_filename", "") or "").strip(),
            "image_url": str(style.get("image_url", "") or "").strip(),
        }

    return {}


def _style_has_image_for_slot(style: dict[str, Any], profile_slot: int) -> bool:
    entry = _get_style_profile_entry(style, profile_slot)
    return bool(
        str(entry.get("image_filename", "") or "").strip()
        or str(entry.get("image_url", "") or "").strip()
    )


def _decode_data_url_image_bytes(data_url: str) -> bytes | None:
    raw = str(data_url or "").strip()
    if not raw.startswith("data:image/"):
        return None
    if "," not in raw:
        return None
    header, payload = raw.split(",", 1)
    if ";base64" not in header.lower():
        return None
    try:
        return base64.b64decode(payload)
    except Exception:
        return None


def _extract_filename_from_image_url(image_url: str) -> str:
    value = str(image_url or "").strip()
    marker = "/api/images/"
    idx = value.find(marker)
    if idx < 0:
        return ""
    suffix = value[idx + len(marker):]
    if "?" in suffix:
        suffix = suffix.split("?", 1)[0]
    if "#" in suffix:
        suffix = suffix.split("#", 1)[0]
    return unquote(suffix).strip()


def _style_preview_filename(style_id: int, profile_slot: int = 1) -> str:
    slot = _coerce_profile_slot(profile_slot)
    if slot <= 1:
        return f"{int(style_id)}.png"
    return f"{int(style_id)}-p{slot}.png"
