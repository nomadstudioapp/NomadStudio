"""Chroma Key — Flask routes."""

from __future__ import annotations

import base64
import logging

from flask import Blueprint, jsonify, request

from app.routes.models_api_shared import (
    _ensure_registry,
    _try_save_image_to_output_dir,
)

from . import service as chroma_key_service

logger = logging.getLogger(__name__)

chroma_key_bp = Blueprint("chroma_key", __name__)


def _decode_data_url(data_url: str) -> bytes:
    """Decode a base64 data URL into raw bytes."""
    if "," not in data_url:
        raise ValueError("Invalid data URL: missing comma separator")
    _, encoded = data_url.split(",", 1)
    try:
        return base64.b64decode(encoded)
    except Exception as exc:
        raise ValueError(f"Invalid base64 image data: {exc}") from exc


@chroma_key_bp.post("/models/chroma-key/process")
def process_chroma_key():
    """Remove a solid/vignetted background by chroma keying."""
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

    raw_auto = _get("autoDetect", "auto_detect", True)
    auto_detect = raw_auto not in ("false", False, 0, "0")

    bg_color_hex = str(_get("bgColor", "bg_color", "") or "").strip()
    if auto_detect:
        bg_color_hex = None

    try:
        tolerance = float(_get("tolerance", "tolerance", 30.0))
        tolerance = max(1.0, min(tolerance, 100.0))
    except (TypeError, ValueError):
        tolerance = 30.0

    try:
        feather = float(_get("feather", "feather", 25.0))
        feather = max(1.0, min(feather, 100.0))
    except (TypeError, ValueError):
        feather = 25.0

    try:
        despeckle_min_size = int(_get("despeckleMinSize", "despeckle_min_size", 15))
        despeckle_min_size = max(0, min(despeckle_min_size, 200))
    except (TypeError, ValueError):
        despeckle_min_size = 15

    raw_decontaminate = _get("decontaminate", "decontaminate", True)
    decontaminate = raw_decontaminate not in ("false", False, 0, "0")

    try:
        blur_sigma = float(_get("blurSigma", "blur_sigma", 0.8))
        blur_sigma = max(0.0, min(blur_sigma, 5.0))
    except (TypeError, ValueError):
        blur_sigma = 0.8

    try:
        choke = float(_get("choke", "choke", 0.0))
        choke = max(0.0, min(choke, 10.0))
    except (TypeError, ValueError):
        choke = 0.0

    try:
        image_bytes = _decode_data_url(image_data_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        result_bytes, coverage = chroma_key_service.process_image_bytes(
            image_bytes=image_bytes,
            bg_color_hex=bg_color_hex,
            tolerance=tolerance,
            feather=feather,
            despeckle_min_size=despeckle_min_size,
            decontaminate=decontaminate,
            blur_sigma=blur_sigma,
            choke=choke,
        )
    except Exception as exc:
        logger.exception("Chroma key processing failed")
        return jsonify({"error": f"Processing failed: {exc}"}), 500

    data_url = "data:image/png;base64," + base64.b64encode(result_bytes).decode()
    response = {"ok": True, "dataUrl": data_url}
    if coverage is not None:
        response["bgCoverage"] = round(coverage, 3)
        if coverage < 0.85:
            response["warning"] = (
                "Background doesn't look very flat/uniform (coverage %.0f%%). "
                "This image may not be a great fit for chroma keying — "
                "consider an AI-based Remove Background flow instead, or set "
                "a manual background color." % (coverage * 100)
            )

    # By default this just returns a base64 dataUrl (cheap — used by the live
    # preview panel, which never persists anything). Pass "save": true to also
    # write it to the output directory and get back an "imageUrl" — used by
    # the real "Remove Background" generate action.
    if payload.get("save", False):
        data = _ensure_registry()
        metadata = {
            "source": "chroma-key",
            "seed": "0",
            "auto_detect": str(auto_detect),
            "tolerance": str(tolerance),
            "feather": str(feather),
        }
        if bg_color_hex:
            metadata["bg_color"] = bg_color_hex
        if coverage is not None:
            metadata["bg_coverage"] = str(round(coverage, 3))
        if choke:
            metadata["choke"] = str(choke)

        saved_rel = _try_save_image_to_output_dir(
            data,
            result_bytes,
            metadata,
            filename_prefix="chroma-key",
            idx=0,
        )
        if not saved_rel:
            return jsonify({"error": "Failed to save output image"}), 500
        response["imageUrl"] = f"/api/images/{saved_rel}"

    return jsonify(response)


@chroma_key_bp.post("/models/chroma-key/detect")
def detect_chroma_key_background():
    """Auto-detect the dominant background color (and its coverage/confidence)
    from the current image — used by the "Detect" button so the user can see
    (and start tweaking from) the value auto-detect would otherwise use."""
    payload = request.get_json(silent=True) or {}

    image_data_url = str(payload.get("imageDataUrl", "")).strip()
    if not image_data_url:
        return jsonify({"error": "imageDataUrl is required"}), 400

    try:
        image_bytes = _decode_data_url(image_data_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        bg_color_hex, coverage = chroma_key_service.detect_background_from_bytes(image_bytes)
    except Exception as exc:
        logger.exception("Chroma key detection failed")
        return jsonify({"error": f"Detection failed: {exc}"}), 500

    response = {"ok": True, "bgColorHex": bg_color_hex, "bgCoverage": round(coverage, 3)}
    if coverage < 0.85:
        response["warning"] = (
            "Background doesn't look very flat/uniform (coverage %.0f%%). "
            "Detection may be unreliable for this image." % (coverage * 100)
        )
    return jsonify(response)
