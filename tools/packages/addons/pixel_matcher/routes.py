"""Pixel Matcher — Flask routes."""

from __future__ import annotations

import base64
import logging

from flask import Blueprint, jsonify, request

from app.routes.models_api_shared import (
    _ensure_registry,
    _try_save_image_to_output_dir,
)

from . import palettes as palette_store
from . import service as pixel_service

logger = logging.getLogger(__name__)

pixel_matcher_bp = Blueprint("pixel_matcher", __name__)


# ── Palettes (imported .pal/.gpl/.hex/.txt/.act) ─────────────────────────────

@pixel_matcher_bp.get("/models/pixel-match/palettes")
def list_palettes():
    return jsonify({
        "palettes": palette_store.list_palettes(),
        "extensions": list(palette_store.SUPPORTED_EXTENSIONS),
    })


@pixel_matcher_bp.post("/models/pixel-match/palettes")
def import_palette():
    """Body: {filename, dataBase64} — the raw file, base64-encoded (a .pal
    can be binary RIFF, so the browser never decodes it as text)."""
    payload = request.get_json(silent=True) or {}
    filename = str(payload.get("filename", "")).strip()
    if not filename:
        return jsonify({"error": "filename is required"}), 400
    try:
        data = base64.b64decode(str(payload.get("dataBase64", "")))
    except Exception:
        return jsonify({"error": "Invalid base64 data"}), 400
    try:
        palette = palette_store.add_palette(filename, data)
    except palette_store.PaletteError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "palette": palette})


@pixel_matcher_bp.patch("/models/pixel-match/palettes/<palette_id>")
def rename_palette(palette_id: str):
    payload = request.get_json(silent=True) or {}
    palette = palette_store.rename_palette(palette_id, payload.get("name", ""))
    if palette is None:
        return jsonify({"error": "Palette not found or empty name"}), 404
    return jsonify({"ok": True, "palette": palette})


@pixel_matcher_bp.delete("/models/pixel-match/palettes/<palette_id>")
def delete_palette(palette_id: str):
    if not palette_store.delete_palette(palette_id):
        return jsonify({"error": "Palette not found"}), 404
    return jsonify({"ok": True})


def _decode_data_url(data_url: str) -> bytes:
    """Decode a base64 data URL into raw bytes."""
    if "," not in data_url:
        raise ValueError("Invalid data URL: missing comma separator")
    _, encoded = data_url.split(",", 1)
    try:
        return base64.b64decode(encoded)
    except Exception as exc:
        raise ValueError(f"Invalid base64 image data: {exc}") from exc


@pixel_matcher_bp.post("/models/pixel-match/process")
def process_pixel_match():
    """Apply pixel-art conversion."""
    payload = request.get_json(silent=True) or {}

    image_data_url = str(payload.get("imageDataUrl", "")).strip()
    if not image_data_url:
        return jsonify({"error": "imageDataUrl is required"}), 400

    # Accept both camelCase (API calls) and snake_case (advancedValues from UI)
    def _get(camel, snake, default=None):
        v = payload.get(camel)
        if v is None:
            v = payload.get(snake)
        return v if v is not None else default

    # Pixel size
    raw_pixel_size = _get("pixelSize", "pixel_size")
    try:
        pixel_size = int(raw_pixel_size) if raw_pixel_size is not None else None
        if pixel_size is not None:
            pixel_size = max(2, min(pixel_size, 64))
    except (TypeError, ValueError):
        pixel_size = None

    # Num colors
    try:
        num_colors = int(_get("numColors", "num_colors", 16))
        num_colors = max(2, min(num_colors, 256))
    except (TypeError, ValueError):
        num_colors = 16

    # Scale factor (flow.json's default is 1× — keep the fallback the same)
    try:
        scale_factor = int(_get("scaleFactor", "scale_factor", 1))
        scale_factor = max(1, min(scale_factor, 8))
    except (TypeError, ValueError):
        scale_factor = 1

    # Ordered dithering: 0 = off, 2/4/8 = Bayer matrix size
    try:
        dither = int(_get("dither", "dither", 0))
        dither = dither if dither in (2, 4, 8) else 0
    except (TypeError, ValueError):
        dither = 0

    raw_auto = _get("autoDetect", "auto_detect", True)
    auto_detect = raw_auto not in ("false", False, 0, "0")
    raw_sharpen = _get("sharpen", "sharpen", True)
    sharpen = raw_sharpen not in ("false", False, 0, "0")

    # Imported palette: overrides num_colors (KMeans is skipped)
    palette_id = str(_get("paletteId", "palette", "") or "").strip()
    palette = palette_store.get_palette(palette_id) if palette_id else None
    if palette_id and palette is None:
        return jsonify({"error": "The selected palette no longer exists"}), 400
    palette_rgb = [palette_store.hex_to_rgb(c) for c in palette["colors"]] if palette else None

    try:
        image_bytes = _decode_data_url(image_data_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        result_bytes = pixel_service.process_image_bytes(
            image_bytes=image_bytes,
            pixel_size=pixel_size,
            num_colors=num_colors,
            scale_factor=scale_factor,
            auto_detect=auto_detect,
            sharpen=sharpen,
            dither=dither,
            palette=palette_rgb,
        )
    except Exception as exc:
        logger.exception("Pixel matcher processing failed")
        return jsonify({"error": f"Processing failed: {exc}"}), 500

    data = _ensure_registry()
    metadata = {
        "source": "pixel-match",
        "seed": "0",
        "num_colors": str(num_colors),
        "scale_factor": str(scale_factor),
        "auto_detect": str(auto_detect),
        "dither": str(dither),
    }
    if palette:
        metadata["palette"] = palette["name"]
        metadata["num_colors"] = str(len(palette["colors"]))
    if pixel_size is not None:
        metadata["pixel_size"] = str(pixel_size)

    saved_rel = _try_save_image_to_output_dir(
        data,
        result_bytes,
        metadata,
        filename_prefix="pixel-match",
        idx=0,
    )
    if not saved_rel:
        return jsonify({"error": "Failed to save output image"}), 500

    return jsonify({"ok": True, "imageUrl": f"/api/images/{saved_rel}"})