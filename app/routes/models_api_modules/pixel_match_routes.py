from __future__ import annotations

import base64
import logging

from flask import jsonify, request

from app.routes.models_api_shared import (
    _ensure_registry,
    _try_save_image_to_output_dir,
    models_api_bp,
)
from app.services import pixel_matcher_service

logger = logging.getLogger(__name__)


def _decode_data_url(data_url: str) -> bytes:
    """Decode a base64 data URL into raw bytes."""
    if "," not in data_url:
        raise ValueError("Invalid data URL: missing comma separator")
    _, encoded = data_url.split(",", 1)
    try:
        return base64.b64decode(encoded)
    except Exception as exc:
        raise ValueError(f"Invalid base64 image data: {exc}") from exc


@models_api_bp.post("/models/pixel-match/process")
def process_pixel_match():
    """Apply pixel-art conversion to an uploaded image.

    Request JSON:
        imageDataUrl  – base64 data URL of the source image (required)
        pixelSize     – grid cell size in px (int, 2-32); null → auto-detect
        numColors     – palette size (int, 2-256); default 16
        scaleFactor   – output scale multiplier (int, 1/2/4/8); default 2
        autoDetect    – auto-detect pixelSize when not provided (bool); default true
        sharpen       – apply a final sharpen pass (bool); default true
        dither        – Bayer ordered-dither matrix size (0/2/4/8); default 0 (off)

    Response JSON:
        {"ok": true, "imageUrl": "/api/images/<filename>"}
    """
    payload = request.get_json(silent=True) or {}

    image_data_url = str(payload.get("imageDataUrl", "")).strip()
    if not image_data_url:
        return jsonify({"error": "imageDataUrl is required"}), 400

    # Parse optional parameters with safe coercion
    raw_pixel_size = payload.get("pixelSize")
    try:
        pixel_size = int(raw_pixel_size) if raw_pixel_size is not None else None
        if pixel_size is not None:
            pixel_size = max(2, min(pixel_size, 32))
    except (TypeError, ValueError):
        pixel_size = None

    try:
        num_colors = int(payload.get("numColors", 16))
        num_colors = max(2, min(num_colors, 256))
    except (TypeError, ValueError):
        num_colors = 16

    try:
        scale_factor = int(payload.get("scaleFactor", 2))
        scale_factor = max(1, min(scale_factor, 8))
    except (TypeError, ValueError):
        scale_factor = 2

    auto_detect = bool(payload.get("autoDetect", True))
    sharpen = bool(payload.get("sharpen", True))

    try:
        dither = int(payload.get("dither", 0) or 0)
        dither = dither if dither in (0, 2, 4, 8) else 0
    except (TypeError, ValueError):
        dither = 0

    try:
        image_bytes = _decode_data_url(image_data_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        result_bytes = pixel_matcher_service.process_image_bytes(
            image_bytes=image_bytes,
            pixel_size=pixel_size,
            num_colors=num_colors,
            scale_factor=scale_factor,
            auto_detect=auto_detect,
            sharpen=sharpen,
            dither=dither,
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
