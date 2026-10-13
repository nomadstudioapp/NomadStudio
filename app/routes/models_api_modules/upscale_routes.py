from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

from flask import jsonify, request

from app.services.comfy_paths import for_comfy
from app.config import DEFAULT_COMFY_URL
from app.services.http_client import http_json, http_bytes, http_multipart_upload_image
from app.services import gpu_coordinator
from app.routes.models_api_shared import (
    _apply_basic_values_to_workflow,
    _apply_comfy_output_policy,
    _ensure_registry,
    _inject_uploaded_image_into_workflow,
    _parse_image_data_url,
    _registry_transaction,
    _resolve_upscale_scale,
    _safe_comfy_url,
    _save_registry,
    _select_output_images,
    _try_save_image_to_output_dir,
    _upscale_model_by_id,
    _upscale_models_catalog,
    models_api_bp,
)


@models_api_bp.get("/models/upscale/settings")
def get_models_upscale_settings():
    data = _ensure_registry()
    upscale = (
        data.get("upscaleSettings", {})
        if isinstance(data.get("upscaleSettings"), dict)
        else {}
    )
    models = _upscale_models_catalog(data)
    selected_model = _upscale_model_by_id(data, str(upscale.get("modelId", "")))
    selected_import_id = str(
        selected_model.get("importId", "") or selected_model.get("id", "")
    ).strip()
    selected_record = next(
        (
            item
            for item in data.get("imports", [])
            if str(item.get("id", "")) == selected_import_id
        ),
        None,
    )
    scale = _resolve_upscale_scale(
        selected_model,
        upscale.get(
            "scale",
            selected_model.get("defaultScale", selected_model.get("fixedScale", 2)),
        ),
    )

    selected_import = None
    if isinstance(selected_record, dict):
        analysis = (
            selected_record.get("analysis", {})
            if isinstance(selected_record.get("analysis", {}), dict)
            else {}
        )
        selected_import = {
            "id": selected_record.get("id"),
            "name": selected_record.get("name"),
            "basicValues": selected_record.get("basicValues", {}),
            "advancedValues": selected_record.get("advancedValues", {}),
            "basicParameters": analysis.get("basicParameters", []),
            "advancedParameters": analysis.get("advancedParameters", []),
            "detected": analysis.get("detected", {}),
        }

    return jsonify(
        {
            "models": models,
            "settings": {
                "comfyApiUrl": str(
                    upscale.get("comfyApiUrl", DEFAULT_COMFY_URL)
                ).strip()
                or DEFAULT_COMFY_URL,
                "modelId": selected_model.get("id"),
                "scale": scale,
            },
            "selectedModel": selected_model,
            "selectedImport": selected_import,
        }
    )


@models_api_bp.patch("/models/upscale/settings")
def update_models_upscale_settings():
    payload = request.get_json(silent=True) or {}
    with _registry_transaction() as data:
        upscale = data.setdefault("upscaleSettings", {})

        if "comfyApiUrl" in payload:
            try:
                upscale["comfyApiUrl"] = _safe_comfy_url(
                    str(payload.get("comfyApiUrl", "")).strip()
                )
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400

        models = _upscale_models_catalog(data)
        current_model = _upscale_model_by_id(data, str(upscale.get("modelId", "")))
        if "modelId" in payload:
            current_model = _upscale_model_by_id(data, str(payload.get("modelId", "")))
            upscale["modelId"] = current_model.get("id")

        requested_scale = payload.get(
            "scale",
            upscale.get(
                "scale",
                current_model.get("defaultScale", current_model.get("fixedScale", 2)),
            ),
        )
        upscale["scale"] = _resolve_upscale_scale(current_model, requested_scale)

        if not str(upscale.get("comfyApiUrl", "")).strip():
            upscale["comfyApiUrl"] = (
                str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip()
                or DEFAULT_COMFY_URL
            )

        selected_import_id = str(
            current_model.get("importId", "") or current_model.get("id", "")
        ).strip()
        selected_record = next(
            (
                item
                for item in data.get("imports", [])
                if str(item.get("id", "")) == selected_import_id
            ),
            None,
        )

        selected_import = None
        if isinstance(selected_record, dict):
            analysis = (
                selected_record.get("analysis", {})
                if isinstance(selected_record.get("analysis", {}), dict)
                else {}
            )
            selected_import = {
                "id": selected_record.get("id"),
                "name": selected_record.get("name"),
                "basicValues": selected_record.get("basicValues", {}),
                "advancedValues": selected_record.get("advancedValues", {}),
                "basicParameters": analysis.get("basicParameters", []),
                "advancedParameters": analysis.get("advancedParameters", []),
                "detected": analysis.get("detected", {}),
            }
    return jsonify(
        {
            "models": models,
            "settings": {
                "comfyApiUrl": upscale.get("comfyApiUrl"),
                "modelId": upscale.get("modelId"),
                "scale": upscale.get("scale"),
            },
            "selectedModel": current_model,
            "selectedImport": selected_import,
        }
    )


@models_api_bp.post("/models/upscale/prepare")
def prepare_upscale_workflow():
    """Prepare upscale workflow for direct JS submission to ComfyUI.

    Uploads the source image to ComfyUI, builds the workflow, and returns
    {workflow, clientId, comfyApiUrl, importId} — same contract as
    /models/imports/prepare-queue so the frontend can submit directly and
    stream progress via /images/comfy/progress-stream.
    """
    payload = request.get_json(silent=True) or {}
    image_data_url = str(payload.get("imageDataUrl", "")).strip()
    if not image_data_url:
        return jsonify({"error": "imageDataUrl is required"}), 400

    data = _ensure_registry()
    upscale = (
        data.get("upscaleSettings", {})
        if isinstance(data.get("upscaleSettings"), dict)
        else {}
    )
    model = _upscale_model_by_id(
        data,
        str(payload.get("modelId", "")).strip()
        or str(upscale.get("modelId", "")).strip(),
    )
    if not model:
        return jsonify({"error": "No upscale workflow imports available. Import a ComfyUI workflow with a LoadImage node first."}), 400

    import_id = (str(model.get("importId", "")).strip() or str(model.get("id", "")).strip())
    record = next(
        (item for item in data.get("imports", []) if str(item.get("id", "")) == import_id),
        None,
    )
    if record is None:
        return jsonify({"error": "Selected upscale workflow import was not found"}), 404

    requested_scale = payload.get(
        "scale",
        upscale.get("scale", model.get("defaultScale", model.get("fixedScale", 2))),
    )
    scale = _resolve_upscale_scale(model, requested_scale)

    comfy_api_url = (
        str(payload.get("comfyApiUrl", "")).strip()
        or str(upscale.get("comfyApiUrl", "")).strip()
        or str(model.get("comfyApiUrl", "")).strip()
        or str(record.get("comfyApiUrl", "")).strip()
        or str(data.get("settings", {}).get("comfyApiUrl", "")).strip()
    )
    if not comfy_api_url:
        return jsonify({"error": "ComfyUI URI not configured"}), 400

    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        mime, raw_bytes = _parse_image_data_url(image_data_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    image_ext = "png"
    if mime == "image/jpeg":
        image_ext = "jpg"
    elif mime == "image/webp":
        image_ext = "webp"

    upload_filename = f"oj-upscale-{uuid.uuid4().hex}.{image_ext}"
    try:
        upload_result = http_multipart_upload_image(
            f"{comfy_api_url}/upload/image",
            upload_filename,
            raw_bytes,
            mime,
        )
        comfy_filename = str(upload_result.get("name", "")).strip() or upload_filename
    except Exception as exc:
        return jsonify({"error": f"ComfyUI image upload failed: {exc}"}), 502

    merged_basic = {**record.get("basicValues", {})}
    merged_advanced = {**record.get("advancedValues", {})}

    payload_advanced = payload.get("advancedValues", {})
    if isinstance(payload_advanced, dict):
        for key, value in payload_advanced.items():
            key_text = str(key or "").strip()
            if not key_text:
                continue
            if isinstance(value, (str, int, float, bool)):
                merged_advanced[key_text] = value

    prompt_refinement = str(payload.get("promptRefinement", "")).strip()
    if prompt_refinement:
        merged_basic["positive"] = prompt_refinement

    scale_key = str(model.get("scaleKey", "")).strip()
    if str(model.get("scaleMode", "")).lower() == "selectable" and scale_key:
        merged_advanced[scale_key] = scale

    prepared_workflow = _apply_basic_values_to_workflow(
        record, merged_basic, merged_advanced, num_images=1
    )
    if not _inject_uploaded_image_into_workflow(prepared_workflow, comfy_filename):
        return jsonify({"error": "Selected workflow has no LoadImage node for input image"}), 400

    _apply_comfy_output_policy(data, prepared_workflow)
    gpu_coordinator.wait_external("comfy")  # browser submits directly (superqueue)
    client_id = uuid.uuid4().hex

    return jsonify({
        "workflow":     prepared_workflow,
        "clientId":     client_id,
        "comfyApiUrl":  comfy_api_url,
        "importId":     import_id,
        "modelId":      model.get("id"),
        "scale":        scale,
    })


@models_api_bp.post("/models/upscale/generate")
def generate_upscaled_image():
    payload = request.get_json(silent=True) or {}
    image_data_url = str(payload.get("imageDataUrl", "")).strip()
    if not image_data_url:
        return jsonify({"error": "imageDataUrl is required"}), 400

    data = _ensure_registry()
    upscale = (
        data.get("upscaleSettings", {})
        if isinstance(data.get("upscaleSettings"), dict)
        else {}
    )
    model = _upscale_model_by_id(
        data,
        str(payload.get("modelId", "")).strip()
        or str(upscale.get("modelId", "")).strip(),
    )
    if not model:
        return jsonify(
            {
                "error": "No upscale workflow imports available. Import a ComfyUI workflow with a LoadImage node first."
            }
        ), 400
    import_id = (
        str(model.get("importId", "")).strip() or str(model.get("id", "")).strip()
    )

    record = next(
        (
            item
            for item in data.get("imports", [])
            if str(item.get("id", "")) == import_id
        ),
        None,
    )
    if record is None:
        return jsonify({"error": "Selected upscale workflow import was not found"}), 404

    requested_scale = payload.get(
        "scale",
        upscale.get("scale", model.get("defaultScale", model.get("fixedScale", 2))),
    )
    scale = _resolve_upscale_scale(model, requested_scale)

    comfy_api_url = (
        str(payload.get("comfyApiUrl", "")).strip()
        or str(upscale.get("comfyApiUrl", "")).strip()
        or str(model.get("comfyApiUrl", "")).strip()
        or str(record.get("comfyApiUrl", "")).strip()
        or str(data.get("settings", {}).get("comfyApiUrl", "")).strip()
    )
    if not comfy_api_url:
        return jsonify({"error": "ComfyUI URI not configured"}), 400

    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        mime, raw_bytes = _parse_image_data_url(image_data_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    image_ext = "png"
    if mime == "image/jpeg":
        image_ext = "jpg"
    elif mime == "image/webp":
        image_ext = "webp"

    upload_filename = f"oj-upscale-{uuid.uuid4().hex}.{image_ext}"

    try:
        upload_result = http_multipart_upload_image(
            f"{comfy_api_url}/upload/image",
            upload_filename,
            raw_bytes,
            mime,
        )
        comfy_filename = str(upload_result.get("name", "")).strip() or upload_filename
    except Exception as exc:
        return jsonify({"error": f"ComfyUI image upload failed: {exc}"}), 502

    merged_basic = {**record.get("basicValues", {})}
    merged_advanced = {**record.get("advancedValues", {})}

    payload_advanced = payload.get("advancedValues", {})
    if isinstance(payload_advanced, dict):
        for key, value in payload_advanced.items():
            key_text = str(key or "").strip()
            if not key_text:
                continue
            if isinstance(value, (str, int, float, bool)):
                merged_advanced[key_text] = value

    prompt_refinement = str(payload.get("promptRefinement", "")).strip()
    if prompt_refinement:
        merged_basic["positive"] = prompt_refinement

    scale_key = str(model.get("scaleKey", "")).strip()
    if str(model.get("scaleMode", "")).lower() == "selectable" and scale_key:
        merged_advanced[scale_key] = scale

    prepared_workflow = _apply_basic_values_to_workflow(
        record, merged_basic, merged_advanced, num_images=1
    )
    if not _inject_uploaded_image_into_workflow(prepared_workflow, comfy_filename):
        return jsonify(
            {"error": "Selected workflow has no LoadImage node for input image"}
        ), 400

    _apply_comfy_output_policy(data, prepared_workflow)

    try:
        with gpu_coordinator.held("comfy"):
            prompt_response = http_json(
                f"{comfy_api_url}/prompt",
                method="POST",
                payload={"prompt": for_comfy(prepared_workflow, comfy_api_url), "client_id": uuid.uuid4().hex},
                timeout=30,
            )
            prompt_id = str(prompt_response.get("prompt_id", "")).strip()
            if not prompt_id:
                return jsonify(
                    {"error": f"ComfyUI rejected prompt: {prompt_response}"}
                ), 502

            history_payload = {}
            for _ in range(720):
                time.sleep(0.5)
                history_payload = http_json(
                    f"{comfy_api_url}/history/{prompt_id}", timeout=120
                )
                if isinstance(history_payload, dict) and prompt_id in history_payload:
                    outputs = history_payload.get(prompt_id, {}).get("outputs", {})
                    if outputs:
                        break

        preferred_save_nodes = (
            record.get("analysis", {}).get("detected", {}).get("saveImageNodeIds", [])
            or []
        )
        output_node_id, image_entries = _select_output_images(
            history_payload, prompt_id, preferred_save_nodes
        )
        if not image_entries:
            return jsonify({"error": "No output image found in ComfyUI history"}), 502

        first = image_entries[0]
        query = urlencode(
            {
                "filename": first.get("filename", ""),
                "subfolder": first.get("subfolder", ""),
                "type": first.get("type", "output"),
            }
        )
        image_bytes = http_bytes(f"{comfy_api_url}/view?{query}", timeout=180)

        meta: dict[str, str] = {
            "source": "upscale",
            "session": prompt_id,
            "workflow": str(record.get("id", "")),
            "workflow_name": str(record.get("name", "") or ""),
            "checkpoint": str(merged_basic.get("checkpoint", "") or ""),
            "positive": str(merged_basic.get("positive", "") or ""),
            "negative": str(merged_basic.get("negative", "") or ""),
            "advanced_values": json.dumps(merged_advanced, ensure_ascii=False),
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        saved_filename = _try_save_image_to_output_dir(
            data, image_bytes, meta, "upscale", 0
        )
    except Exception as exc:
        return jsonify({"error": f"ComfyUI upscale workflow failed: {exc}"}), 502

    return jsonify(
        {
            "ok": True,
            "modelId": model.get("id"),
            "scale": scale,
            "width": None,
            "height": None,
            "promptId": prompt_id,
            "outputImageDataUrl": "",
            "savedFilename": saved_filename,
        }
    )


@models_api_bp.get("/models/upscale/progress")
def get_upscale_progress():
    data = _ensure_registry()
    upscale = (
        data.get("upscaleSettings", {})
        if isinstance(data.get("upscaleSettings"), dict)
        else {}
    )
    model_id = (
        str(request.args.get("modelId", "")).strip()
        or str(upscale.get("modelId", "")).strip()
    )
    model = _upscale_model_by_id(data, model_id)

    comfy_api_url = (
        str(request.args.get("comfyApiUrl", "")).strip()
        or str(upscale.get("comfyApiUrl", "")).strip()
        or str(model.get("comfyApiUrl", "")).strip()
        or str(data.get("settings", {}).get("comfyApiUrl", "")).strip()
    )
    if not comfy_api_url:
        return jsonify({"error": "ComfyUI URI not configured"}), 400

    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        payload = http_json(f"{comfy_api_url}/progress", timeout=15)
    except Exception as exc:
        return jsonify(
            {
                "ok": True,
                "available": False,
                "percent": -1,
                "value": 0,
                "max": 0,
                "node": None,
                "warning": f"ComfyUI progress endpoint unavailable: {exc}",
            }
        )

    value_raw = payload.get("value", 0) if isinstance(payload, dict) else 0
    max_raw = payload.get("max", 0) if isinstance(payload, dict) else 0
    try:
        value = float(value_raw)
    except Exception:
        value = 0.0
    try:
        max_value = float(max_raw)
    except Exception:
        max_value = 0.0

    percent = 0
    if max_value > 0:
        percent = max(0, min(100, int(round(value / max_value * 100))))

    return jsonify(
        {
            "ok": True,
            "available": True,
            "percent": percent,
            "value": value,
            "max": max_value,
            "node": payload.get("node") if isinstance(payload, dict) else None,
        }
    )
