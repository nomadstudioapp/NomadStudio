from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from flask import jsonify, request

from app.routes.models_api_shared import (
    _ensure_registry,
    _load_source_image_bytes_for_style,
    models_api_bp,
)
from app import paths
from app.services import image_service

logger = logging.getLogger(__name__)

_BACKGROUNDS_PATH = paths.data_file("sfw_backgrounds.json")
_BACKGROUNDS_IMAGES_DIR = paths.user_images("backgrounds")
_backgrounds_cache: list[dict] | None = None


def _save_backgrounds(items: list[dict]) -> None:
    global _backgrounds_cache
    _BACKGROUNDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_BACKGROUNDS_PATH, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)
    _backgrounds_cache = items


def _slugify_keyword(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:64]


def _unique_background_keyword(base: str, existing: set[str]) -> str:
    root = _slugify_keyword(base) or "custom_background"
    candidate = root
    idx = 2
    while candidate in existing:
        candidate = f"{root}_{idx}"
        idx += 1
    return candidate


def _scale_image_bytes_for_preview(source_bytes: bytes, max_side: int = 1280) -> bytes:
    try:
        from PIL import Image  # type: ignore
        import io

        with Image.open(io.BytesIO(source_bytes)) as image:
            width, height = image.size
            largest = max(width, height)
            if largest > max_side:
                ratio = max_side / float(largest)
                image = image.resize(
                    (max(1, int(width * ratio)), max(1, int(height * ratio))),
                    Image.LANCZOS,
                )
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            return output.getvalue()
    except Exception:
        logger.exception(
            "Failed to scale background image preview; saving original bytes"
        )
    return source_bytes


def _load_backgrounds() -> list[dict]:
    global _backgrounds_cache
    if _backgrounds_cache is not None:
        return _backgrounds_cache
    try:
        with open(_BACKGROUNDS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        _backgrounds_cache = data if isinstance(data, list) else []
    except Exception:
        logger.exception("Failed to load backgrounds")
        _backgrounds_cache = []
    return _backgrounds_cache


@models_api_bp.get("/backgrounds")
def get_backgrounds():
    return jsonify({"backgrounds": _load_backgrounds()})


@models_api_bp.post("/backgrounds")
def create_background():
    payload = request.get_json(silent=True) or {}
    description = str(payload.get("description", "") or "").strip()
    prompt = str(payload.get("prompt", "") or "").strip()
    neutral_prompt = str(payload.get("neutralPrompt", "") or "").strip()
    base_keyword = str(payload.get("keyword", "") or "").strip() or description

    if not description:
        return jsonify({"error": "description is required"}), 400

    items = _load_backgrounds()
    existing_keywords = {
        str(item.get("keyword", "") or "").strip().lower()
        for item in items
        if isinstance(item, dict)
    }
    keyword = _unique_background_keyword(base_keyword, existing_keywords)

    created = {
        "keyword": keyword,
        "description": description,
        "prompt": prompt or description,
        "neutral_prompt": neutral_prompt or prompt or description,
    }
    items.append(created)
    _save_backgrounds(items)
    return jsonify({"ok": True, "background": created}), 201


_IDENTIFIER_RE = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")


@models_api_bp.patch("/backgrounds/<keyword>")
def update_background(keyword: str):
    """Update editable fields (description, prompt, neutral_prompt, and now
    `keyword` itself — the "Identifier" in the edit panel) of a background.
    See update_character's docstring (characters_routes.py) for why renaming
    it also renames the reference image file on disk to match."""
    key = str(keyword or "").strip()
    payload = request.get_json(silent=True) or {}
    EDITABLE_KEYS = {"description", "prompt", "neutral_prompt"}
    updates = {k: str(v or "").strip() for k, v in payload.items() if k in EDITABLE_KEYS}

    new_keyword = None
    if "keyword" in payload:
        new_keyword = str(payload.get("keyword") or "").strip().lower()
        if len(new_keyword) > 16:
            return jsonify({"error": "Identifier must be 16 characters or fewer."}), 400
        if not _IDENTIFIER_RE.match(new_keyword):
            return jsonify(
                {"error": "Identifier must be lowercase letters/numbers, using - or _ to separate words (no spaces or other symbols)."}
            ), 400

    if not updates and new_keyword is None:
        return jsonify({"error": "No editable fields provided"}), 400

    items = _load_backgrounds()
    target = next(
        (it for it in items if isinstance(it, dict) and it.get("keyword") == key), None
    )
    if target is None:
        return jsonify({"error": f"Background '{key}' not found"}), 404

    if new_keyword is not None and new_keyword != key:
        if any(isinstance(it, dict) and it.get("keyword") == new_keyword for it in items):
            return jsonify({"error": f"Identifier '{new_keyword}' is already in use"}), 400
        old_image = _BACKGROUNDS_IMAGES_DIR / f"{key}.png"
        new_image = _BACKGROUNDS_IMAGES_DIR / f"{new_keyword}.png"
        try:
            if old_image.is_file():
                old_image.rename(new_image)
        except OSError:
            logger.exception("Failed to rename background image %s -> %s", old_image, new_image)
        target["keyword"] = new_keyword

    target.update(updates)
    _save_backgrounds(items)
    return jsonify({"ok": True, "background": target})


@models_api_bp.delete("/backgrounds/<keyword>")
def delete_background(keyword: str):
    """Delete a background by keyword. Also best-effort deletes its
    reference image file, same convention as delete_style (styles_routes.py)."""
    key = str(keyword or "").strip()
    items = _load_backgrounds()
    target = next(
        (it for it in items if isinstance(it, dict) and it.get("keyword") == key), None
    )
    if target is None:
        return jsonify({"error": f"Background '{key}' not found"}), 404

    remaining = [it for it in items if it is not target]
    _save_backgrounds(remaining)

    image_path = _BACKGROUNDS_IMAGES_DIR / f"{key}.png"
    try:
        image_path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Failed to delete background image file %s", image_path)

    return jsonify({"ok": True})


@models_api_bp.patch("/backgrounds/<keyword>/image")
def update_background_image(keyword: str):
    key = str(keyword or "").strip()
    if not key:
        return jsonify({"error": "keyword is required"}), 400

    data = _ensure_registry()
    payload = request.get_json(silent=True) or {}
    image_filename = str(payload.get("imageFilename", "") or "").strip()
    image_url = str(payload.get("imageUrl", "") or "").strip()

    if not image_filename and not image_url:
        return jsonify({"error": "imageFilename or imageUrl is required"}), 400

    source_bytes = _load_source_image_bytes_for_style(data, image_filename, image_url)
    if source_bytes is None:
        return jsonify({"error": "Background image source not found"}), 400

    source_bytes = _scale_image_bytes_for_preview(source_bytes)

    _BACKGROUNDS_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    target_name = f"{key}.png"
    saved_path = image_service.save_image(
        str(_BACKGROUNDS_IMAGES_DIR),
        target_name,
        source_bytes,
        {
            "source": "backgrounds",
            "keyword": key,
        },
    )

    return jsonify(
        {
            "ok": True,
            "keyword": key,
            "image_filename": saved_path.name,
        }
    )
