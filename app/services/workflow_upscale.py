"""workflow_upscale — upscale model catalog and scale helpers."""
from __future__ import annotations

import base64
import re
from typing import Any

from app.services.workflow_utils import _workflow_load_image_nodes

# ---------------------------------------------------------------------------
# Upscale helpers
# ---------------------------------------------------------------------------


def _resolve_upscale_scale(model: dict[str, Any], requested_scale: Any) -> float:
    mode = str(model.get("scaleMode", "selectable")).strip().lower()
    if mode == "fixed":
        try:
            fixed = float(model.get("fixedScale", 2.0))
        except Exception:
            fixed = 2.0
        return max(0.25, min(8.0, fixed))

    try:
        value = float(requested_scale)
    except Exception:
        try:
            value = float(model.get("defaultScale", 2.0))
        except Exception:
            value = 2.0

    try:
        min_scale = float(model.get("minScale", 0.25))
    except Exception:
        min_scale = 0.25
    try:
        max_scale = float(model.get("maxScale", 8.0))
    except Exception:
        max_scale = 8.0

    if min_scale <= 0:
        min_scale = 0.25
    if max_scale < min_scale:
        max_scale = min_scale

    return max(min_scale, min(max_scale, value))


def _parse_image_data_url(data_url: str) -> tuple[str, bytes]:
    text = str(data_url or "").strip()
    match = re.match(
        r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise ValueError("imageDataUrl must be a valid base64 data URL")
    mime = match.group(1).lower()
    raw_b64 = re.sub(r"\s+", "", match.group(2))
    try:
        raw_bytes = base64.b64decode(raw_b64, validate=True)
    except Exception as exc:
        raise ValueError(f"Invalid base64 image data: {exc}") from exc
    return mime, raw_bytes


def _pick_upscale_scale_key(record: dict[str, Any]) -> str | None:
    analysis = (
        record.get("analysis", {})
        if isinstance(record.get("analysis", {}), dict)
        else {}
    )
    detected = (
        analysis.get("detected", {})
        if isinstance(analysis.get("detected", {}), dict)
        else {}
    )
    advanced = (
        analysis.get("advancedParameters", [])
        if isinstance(analysis.get("advancedParameters", []), list)
        else []
    )

    scale_node_id = str(detected.get("scaleNodeId", "") or "").strip()
    scale_input_key = str(detected.get("scaleInputKey", "") or "").strip().lower()
    if scale_node_id and scale_input_key in {"scale", "scale_by"}:
        preferred = f"{scale_node_id}.{scale_input_key}"
        for item in advanced:
            if not isinstance(item, dict):
                continue
            if str(item.get("key", "")).strip() == preferred:
                return preferred

    for item in advanced:
        if not isinstance(item, dict):
            continue
        node_class = str(item.get("nodeClass", "")).strip()
        input_key = str(item.get("inputKey", "")).strip().lower()
        if node_class in {"ImageScaleBy", "ImageScale"} and input_key in {
            "scale_by",
            "scale",
        }:
            key = str(item.get("key", "")).strip()
            if key:
                return key

    for item in advanced:
        if not isinstance(item, dict):
            continue
        input_key = str(item.get("inputKey", "")).strip().lower()
        if "scale" not in input_key:
            continue
        key = str(item.get("key", "")).strip()
        if key:
            return key
    return None


def _build_upscale_models_from_imports(data: dict[str, Any]) -> list[dict[str, Any]]:
    imports = (
        data.get("imports", []) if isinstance(data.get("imports", []), list) else []
    )
    models: list[dict[str, Any]] = []

    for record in imports:
        if not isinstance(record, dict):
            continue
        if str(record.get("category", "")).strip().lower() != "upscale":
            continue
        workflow = (
            record.get("workflow", {})
            if isinstance(record.get("workflow", {}), dict)
            else {}
        )
        if not _workflow_load_image_nodes(workflow):
            continue

        analysis = (
            record.get("analysis", {})
            if isinstance(record.get("analysis", {}), dict)
            else {}
        )
        detected = (
            analysis.get("detected", {})
            if isinstance(analysis.get("detected", {}), dict)
            else {}
        )

        scale_key = _pick_upscale_scale_key(record)
        scale_default_raw = detected.get("scaleDefault", 2.0)
        try:
            scale_default = float(scale_default_raw)
        except Exception:
            scale_default = 2.0
        scale_default = max(0.25, min(8.0, scale_default))

        model_item = {
            "id": str(record.get("id", "")),
            "name": str(record.get("name", "Upscale Workflow")),
            "importId": str(record.get("id", "")),
            "comfyApiUrl": str(record.get("comfyApiUrl", "")).strip(),
            "scaleMode": "fixed",
            "fixedScale": scale_default,
            "scaleKey": None,
        }
        if scale_key:
            model_item["scaleMode"] = "selectable"
            model_item["scaleKey"] = scale_key
            model_item["minScale"] = 0.25
            model_item["maxScale"] = 8.0
            model_item["defaultScale"] = scale_default
        models.append(model_item)

    return models


def _upscale_models_catalog(data: dict[str, Any]) -> list[dict[str, Any]]:
    return _build_upscale_models_from_imports(data)


def _upscale_model_by_id(data: dict[str, Any], model_id: str) -> dict[str, Any]:
    catalog = _upscale_models_catalog(data)
    if not catalog:
        return {}
    target = str(model_id or "").strip()
    for model in catalog:
        if str(model.get("id", "")).strip() == target:
            return model
    return catalog[0]
