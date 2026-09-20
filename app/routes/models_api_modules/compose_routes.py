from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

from flask import jsonify, request

from app.config import DEFAULT_COMFY_URL
from app.services.http_client import http_json, http_bytes, http_multipart_upload_image
from app.services import gpu_coordinator
from app.routes.models_api_shared import (
    _apply_basic_values_to_workflow,
    _apply_comfy_output_policy,
    _apply_resize_toggle_to_workflow,
    _compose_model_by_id,
    _compose_models_catalog,
    _ensure_registry,
    _inject_uploaded_image_into_workflow,
    _parse_image_data_url,
    _registry_transaction,
    _safe_comfy_url,
    _save_registry,
    _select_output_images,
    _try_save_image_to_output_dir,
    models_api_bp,
)


@models_api_bp.get("/models/compose/settings")
def get_models_compose_settings():
    data = _ensure_registry()
    compose = (
        data.get("composeSettings", {})
        if isinstance(data.get("composeSettings"), dict)
        else {}
    )
    models = _compose_models_catalog(data)
    selected_model = _compose_model_by_id(data, str(compose.get("modelId", "")))
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
                    compose.get("comfyApiUrl", DEFAULT_COMFY_URL)
                ).strip()
                or DEFAULT_COMFY_URL,
                "modelId": selected_model.get("id"),
            },
            "selectedModel": selected_model,
            "selectedImport": selected_import,
        }
    )


@models_api_bp.patch("/models/compose/settings")
def update_models_compose_settings():
    payload = request.get_json(silent=True) or {}
    with _registry_transaction() as data:
        compose = data.setdefault("composeSettings", {})

        if "comfyApiUrl" in payload:
            try:
                compose["comfyApiUrl"] = _safe_comfy_url(
                    str(payload.get("comfyApiUrl", "")).strip()
                )
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400

        models = _compose_models_catalog(data)
        current_model = _compose_model_by_id(data, str(compose.get("modelId", "")))
        if "modelId" in payload:
            current_model = _compose_model_by_id(data, str(payload.get("modelId", "")))
            compose["modelId"] = current_model.get("id", "")

        if not str(compose.get("comfyApiUrl", "")).strip():
            compose["comfyApiUrl"] = (
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
                "comfyApiUrl": compose.get("comfyApiUrl"),
                "modelId": compose.get("modelId"),
            },
            "selectedModel": current_model,
            "selectedImport": selected_import,
        }
    )


@models_api_bp.post("/models/compose/generate")
def generate_composed_image():
    payload = request.get_json(silent=True) or {}

    data = _ensure_registry()
    compose = (
        data.get("composeSettings", {})
        if isinstance(data.get("composeSettings"), dict)
        else {}
    )
    model = _compose_model_by_id(
        data,
        str(payload.get("modelId", "")).strip()
        or str(compose.get("modelId", "")).strip(),
    )
    if not model:
        return jsonify(
            {
                "error": "No compose workflow imports available. Import a ComfyUI workflow with category 'compose' first."
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
        return jsonify({"error": "Selected compose workflow import was not found"}), 404

    comfy_api_url = (
        str(payload.get("comfyApiUrl", "")).strip()
        or str(compose.get("comfyApiUrl", "")).strip()
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

    positive_prompt = str(payload.get("positivePrompt", "")).strip()
    base_prompt = str(payload.get("basePrompt", "")).strip()
    style_prompt = str(payload.get("stylePrompt", "")).strip()
    advanced_display_raw = payload.get("advancedDisplay", [])
    advanced_display = [
        {"label": str(e.get("label", "")), "value": str(e.get("value", ""))}
        for e in (
            advanced_display_raw if isinstance(advanced_display_raw, list) else []
        )
        if isinstance(e, dict)
    ]
    if positive_prompt:
        merged_basic["positive"] = positive_prompt

    negative_prompt = str(payload.get("negativePrompt", "")).strip()
    if negative_prompt:
        merged_basic["negative"] = negative_prompt

    width_val = payload.get("width")
    height_val = payload.get("height")
    if isinstance(width_val, (int, float)) and int(width_val) >= 64:
        merged_basic["width"] = int(width_val)
    if isinstance(height_val, (int, float)) and int(height_val) >= 64:
        merged_basic["height"] = int(height_val)

    seed_val = payload.get("seed")
    if isinstance(seed_val, (int, float)) and not isinstance(seed_val, bool):
        merged_basic["seed"] = int(seed_val)

    prepared_workflow = _apply_basic_values_to_workflow(
        record, merged_basic, merged_advanced, num_images=1
    )

    # Resolve detected metadata for targeted image injection and resize toggle.
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
    input_image_node_id = str(detected.get("inputImageNodeId", "")).strip() or None
    style_image_node_id = str(detected.get("styleImageNodeId", "")).strip() or None
    resize_node_ids = (
        detected.get("resizeNodeIds", [])
        if isinstance(detected.get("resizeNodeIds"), list)
        else []
    )

    # Apply resize toggle (from advancedValues payload or default to True).
    resize_enabled_raw = merged_advanced.pop("resize_enabled", None)
    if resize_node_ids:
        resize_enabled = (
            resize_enabled_raw
            if isinstance(resize_enabled_raw, bool)
            else bool(resize_enabled_raw)
            if resize_enabled_raw is not None
            else True
        )
        _apply_resize_toggle_to_workflow(
            prepared_workflow, resize_node_ids, resize_enabled
        )

    # Upload and inject main input image.
    image_data_url = str(payload.get("imageDataUrl", "")).strip()
    comfy_filename = None
    if image_data_url and model.get("hasImageInput"):
        try:
            mime, raw_bytes = _parse_image_data_url(image_data_url)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        image_ext = "png"
        if mime == "image/jpeg":
            image_ext = "jpg"
        elif mime == "image/webp":
            image_ext = "webp"

        upload_filename = f"oj-compose-{uuid.uuid4().hex}.{image_ext}"
        try:
            upload_result = http_multipart_upload_image(
                f"{comfy_api_url}/upload/image",
                upload_filename,
                raw_bytes,
                mime,
            )
            comfy_filename = (
                str(upload_result.get("name", "")).strip() or upload_filename
            )
        except Exception as exc:
            return jsonify({"error": f"ComfyUI image upload failed: {exc}"}), 502

    # Upload and inject style reference image (for dual-image workflows).
    style_comfy_filename = None
    style_data_url = str(payload.get("styleImageDataUrl", "")).strip()
    if style_data_url and style_image_node_id:
        try:
            style_mime, style_bytes = _parse_image_data_url(style_data_url)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        style_ext = "png"
        if style_mime == "image/jpeg":
            style_ext = "jpg"
        elif style_mime == "image/webp":
            style_ext = "webp"

        style_upload_filename = f"oj-compose-style-{uuid.uuid4().hex}.{style_ext}"
        try:
            style_upload_result = http_multipart_upload_image(
                f"{comfy_api_url}/upload/image",
                style_upload_filename,
                style_bytes,
                style_mime,
            )
            style_comfy_filename = (
                str(style_upload_result.get("name", "")).strip()
                or style_upload_filename
            )
        except Exception as exc:
            return jsonify({"error": f"ComfyUI style image upload failed: {exc}"}), 502

    if comfy_filename:
        _inject_uploaded_image_into_workflow(
            prepared_workflow,
            comfy_filename,
            node_id=input_image_node_id,
            style_filename=style_comfy_filename,
            style_node_id=style_image_node_id,
        )

    # Strip internal metadata keys before sending to ComfyUI (they are not nodes).
    comfy_prompt = {k: v for k, v in prepared_workflow.items() if not k.startswith("_")}
    _apply_comfy_output_policy(data, comfy_prompt)

    try:
        with gpu_coordinator.held("comfy"):
            client_id = str(payload.get("clientId", "")).strip() or uuid.uuid4().hex
            prompt_response = http_json(
                f"{comfy_api_url}/prompt",
                method="POST",
                payload={"prompt": comfy_prompt, "client_id": client_id},
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
            "source": "compose",
            "session": prompt_id,
            "workflow": str(record.get("id", "")),
            "workflow_name": str(record.get("name", "") or record.get("id", "")),
            "positive": positive_prompt,
            "base_prompt": base_prompt,
            "style_prompt": style_prompt,
            "negative": negative_prompt,
            "seed": str(merged_basic.get("seed", "")),
            "width": str(merged_basic.get("width", "")),
            "height": str(merged_basic.get("height", "")),
            "advanced_display": json.dumps(advanced_display, ensure_ascii=False),
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        saved_filename = _try_save_image_to_output_dir(
            data, image_bytes, meta, "compose", 0
        )
    except Exception as exc:
        return jsonify({"error": f"ComfyUI compose workflow failed: {exc}"}), 502

    return jsonify(
        {
            "ok": True,
            "modelId": model.get("id"),
            "promptId": prompt_id,
            "savedFilename": saved_filename,
        }
    )


@models_api_bp.get("/models/compose/progress")
def get_compose_progress():
    data = _ensure_registry()
    compose = (
        data.get("composeSettings", {})
        if isinstance(data.get("composeSettings"), dict)
        else {}
    )
    model_id = (
        str(request.args.get("modelId", "")).strip()
        or str(compose.get("modelId", "")).strip()
    )
    model = _compose_model_by_id(data, model_id)

    comfy_api_url = (
        str(request.args.get("comfyApiUrl", "")).strip()
        or str(compose.get("comfyApiUrl", "")).strip()
        or str(model.get("comfyApiUrl", "")).strip()
        or str(data.get("settings", {}).get("comfyApiUrl", "")).strip()
    )
    if not comfy_api_url:
        return jsonify({"error": "ComfyUI URI not configured"}), 400

    try:
        result = _http_json(f"{comfy_api_url}/progress", timeout=15)
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

    value_raw = result.get("value", 0) if isinstance(result, dict) else 0
    max_raw = result.get("max", 0) if isinstance(result, dict) else 0
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
            "node": result.get("node") if isinstance(result, dict) else None,
        }
    )
