from __future__ import annotations

import base64
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from flask import jsonify, request

from app import paths
from app.routes.models_api_shared import models_api_bp

logger = logging.getLogger(__name__)

_TEMPLATE_PACKS_PATH = paths.data_file("template_packs.json")
_FIELD_VALUES_PATH = paths.data_file("template_pack_field_values.json")
_STATIC_IMAGES_DIR = paths.IMAGES_DIR
_TEMPLATE_PACKS_IMAGES_DIR = _STATIC_IMAGES_DIR / "template_packs"
_template_packs_cache: list[dict[str, Any]] | None = None
_field_values_cache: dict[str, dict[str, dict[str, list[str]]]] | None = None
_DATA_URL_RE = re.compile(r"^data:image/(?P<ext>[a-zA-Z0-9.+-]+);base64,(?P<data>.+)$", re.DOTALL)


def _load_template_packs() -> list[dict[str, Any]]:
    global _template_packs_cache
    if _template_packs_cache is not None:
        return _template_packs_cache
    try:
        with open(_TEMPLATE_PACKS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        _template_packs_cache = data if isinstance(data, list) else []
    except FileNotFoundError:
        # No template packs installed yet (empty install): nothing to load.
        _template_packs_cache = []
    except Exception:
        logger.exception("Failed to load template packs")
        _template_packs_cache = []
    return _template_packs_cache


def _save_template_packs(items: list[dict[str, Any]]) -> None:
    global _template_packs_cache
    _TEMPLATE_PACKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_TEMPLATE_PACKS_PATH, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)
    _template_packs_cache = items


def _load_field_values() -> dict[str, dict[str, dict[str, list[str]]]]:
    global _field_values_cache
    if _field_values_cache is not None:
        return _field_values_cache
    try:
        with open(_FIELD_VALUES_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        _field_values_cache = data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("Failed to load template pack field values")
        _field_values_cache = {}
    return _field_values_cache


def _save_field_values(data: dict[str, dict[str, dict[str, list[str]]]]) -> None:
    global _field_values_cache
    _FIELD_VALUES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_FIELD_VALUES_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    _field_values_cache = data


def _coerce_id(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _slugify_pack_name(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "pack"


def _decode_image_data_url(data_url: str) -> tuple[bytes, str] | None:
    match = _DATA_URL_RE.match(str(data_url or "").strip())
    if not match:
        return None
    ext = match.group("ext").lower()
    if ext == "jpeg":
        ext = "jpg"
    try:
        return base64.b64decode(match.group("data")), ext
    except Exception:
        return None


@models_api_bp.get("/template-packs")
def list_template_packs():
    return jsonify({"templatePacks": _load_template_packs()})


@models_api_bp.post("/template-packs")
def create_template_pack():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    items = _load_template_packs()
    max_id = max((_coerce_id(it.get("id")) or 0 for it in items), default=0)
    record = {
        "id": max_id + 1,
        "name": name,
        "pack": str(payload.get("pack", "") or "").strip(),
        "theme": str(payload.get("theme", "") or "").strip(),
        "template": str(payload.get("template", "") or "").strip(),
        "images": [],
    }
    items.append(record)
    _save_template_packs(items)
    return jsonify({"ok": True, "templatePack": record}), 201


@models_api_bp.patch("/template-packs/<int:pack_id>")
def update_template_pack(pack_id: int):
    payload = request.get_json(silent=True) or {}
    EDITABLE_KEYS = {"name", "pack", "theme", "template"}
    updates = {k: str(v or "").strip() for k, v in payload.items() if k in EDITABLE_KEYS}
    if not updates:
        return jsonify({"error": "No editable fields provided"}), 400

    items = _load_template_packs()
    target = next((it for it in items if _coerce_id(it.get("id")) == pack_id), None)
    if target is None:
        return jsonify({"error": f"Template {pack_id} not found"}), 404

    target.update(updates)
    _save_template_packs(items)
    return jsonify({"ok": True, "templatePack": target})


@models_api_bp.delete("/template-packs/<int:pack_id>")
def delete_template_pack(pack_id: int):
    items = _load_template_packs()
    target = next((it for it in items if _coerce_id(it.get("id")) == pack_id), None)
    if target is None:
        return jsonify({"error": f"Template {pack_id} not found"}), 404

    items = [it for it in items if _coerce_id(it.get("id")) != pack_id]
    _save_template_packs(items)
    return jsonify({"ok": True, "id": pack_id})


@models_api_bp.post("/template-packs/<int:pack_id>/images")
def add_template_pack_image(pack_id: int):
    payload = request.get_json(silent=True) or {}
    image_data_url = str(payload.get("imageDataUrl", "") or "").strip()
    prompt = str(payload.get("prompt", "") or "").strip()
    if not image_data_url:
        return jsonify({"error": "imageDataUrl is required"}), 400

    decoded = _decode_image_data_url(image_data_url)
    if decoded is None:
        return jsonify({"error": "Could not decode image data"}), 400
    raw_bytes, ext = decoded

    items = _load_template_packs()
    target = next((it for it in items if _coerce_id(it.get("id")) == pack_id), None)
    if target is None:
        return jsonify({"error": f"Template {pack_id} not found"}), 404

    pack_slug = _slugify_pack_name(target.get("pack", ""))
    pack_dir = _TEMPLATE_PACKS_IMAGES_DIR / pack_slug
    pack_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{pack_id}_{uuid.uuid4().hex[:8]}.{ext}"
    (pack_dir / filename).write_bytes(raw_bytes)

    images = target.get("images")
    if not isinstance(images, list):
        images = []
    images.append({"filename": f"template_packs/{pack_slug}/{filename}", "prompt": prompt})
    target["images"] = images
    _save_template_packs(items)
    return jsonify({"ok": True, "templatePack": target}), 201


@models_api_bp.delete("/template-packs/<int:pack_id>/images/<int:image_index>")
def delete_template_pack_image(pack_id: int, image_index: int):
    items = _load_template_packs()
    target = next((it for it in items if _coerce_id(it.get("id")) == pack_id), None)
    if target is None:
        return jsonify({"error": f"Template {pack_id} not found"}), 404

    images = target.get("images")
    if not isinstance(images, list) or image_index < 0 or image_index >= len(images):
        return jsonify({"error": "Image index out of range"}), 404

    removed = images.pop(image_index)
    filename = str(removed.get("filename", "") or "").strip()
    if filename:
        try:
            file_path = (_STATIC_IMAGES_DIR / filename).resolve()
            file_path.relative_to(_STATIC_IMAGES_DIR.resolve())  # guard against path traversal
            if file_path.is_file():
                file_path.unlink()
        except Exception:
            logger.warning("Failed deleting template image file: %s", filename)

    target["images"] = images
    _save_template_packs(items)
    return jsonify({"ok": True, "templatePack": target})


@models_api_bp.get("/template-packs/field-values/<path:pack>/<path:theme>")
def get_template_pack_field_values(pack: str, theme: str):
    all_values = _load_field_values()
    pack_values = all_values.get(pack, {})
    return jsonify({"pack": pack, "theme": theme, "values": pack_values.get(theme, {})})


@models_api_bp.put("/template-packs/field-values/<path:pack>/<path:theme>")
def update_template_pack_field_values(pack: str, theme: str):
    payload = request.get_json(silent=True) or {}
    raw_values = payload.get("values")
    if not isinstance(raw_values, dict):
        return jsonify({"error": "values must be an object"}), 400

    clean: dict[str, list[str]] = {}
    for key, values in raw_values.items():
        if not isinstance(values, list):
            continue
        clean[str(key)] = [str(v).strip() for v in values if str(v).strip()]

    all_values = _load_field_values()
    all_values.setdefault(pack, {})[theme] = clean
    _save_field_values(all_values)
    return jsonify({"ok": True, "pack": pack, "theme": theme, "values": clean})
