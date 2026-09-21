"""Pixel Matcher — Flask routes."""

from __future__ import annotations

import base64
import logging

from flask import Blueprint, jsonify, request

from app.routes.models_api_shared import (
    _ensure_registry,
    _try_save_image_to_output_dir,
)

from . import service as pixel_service

logger = logging.getLogger(__name__)

pixel_matcher_bp = Blueprint("pixel_matcher", __name__)


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

    # Scale factor
    try:
        scale_factor = int(_get("scaleFactor", "scale_factor", 2))
        scale_factor = max(1, min(scale_factor, 8))
    except (TypeError, ValueError):
        scale_factor = 2

    raw_auto = _get("autoDetect", "auto_detect", True)
    auto_detect = raw_auto not in ("false", False, 0, "0")
    raw_sharpen = _get("sharpen", "sharpen", True)
    sharpen = raw_sharpen not in ("false", False, 0, "0")

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
    }
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