from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from flask import jsonify, request

from app.services.comfy_paths import for_comfy
from app.config import (
    LMSTUDIO_MAX_OUTPUT_TOKENS,
)
from app.services.http_client import http_bytes, http_json, http_multipart_upload_image
from app.services import gpu_coordinator
from app.services import image_service
from app.services import registry_service
from app.services.workflow_service import (
    _apply_basic_values_to_workflow,
    _apply_clip_last_layer_bypass,
    _apply_resize_toggle_to_workflow,
    _bypass_optional_image_input_nodes,
    _clip_text,
    _coerce_int_scalar,
    _compute_comfy_poll_timeouts,
    _extract_applied_seeds,
    _extract_clip_last_layer_keys,
    _inject_uploaded_image_into_workflow,
    _normalize_basic_values_aliases,
    _normalize_clip_last_layer_advanced_values,
    _normalize_record_negative,
    _parse_workflow_payload,
    _prune_stale_clip_last_layer_overrides,
    _safe_comfy_url,
    _select_output_images,
    _workflow_load_image_nodes,
)
from app.routes.models_api_shared import (
    _apply_comfy_output_policy,
    _append_lmstudio_output_log,
    _describe_cache_set,
    _ensure_registry,
    _registry_transaction,
    _resolve_output_dir,
    _safe_session_subdir,
    _save_registry,
    _try_save_image_to_output_dir,
    logger,
    models_api_bp,
)

@models_api_bp.post("/models/imports/<import_id>/generate")
def generate_from_import(import_id: str):
    payload = request.get_json(silent=True) or {}
    input_basic_values = payload.get("basicValues", {})
    input_advanced_values = payload.get("advancedValues", {})
    input_num_images = payload.get("numImages", 1)
    input_client_id = str(payload.get("clientId", "")).strip()

    data = _ensure_registry()
    record = next((item for item in data.get("imports", []) if item.get("id") == import_id), None)
    if record is None:
        return jsonify({"error": "import not found"}), 404

    comfy_api_url = str(record.get("comfyApiUrl", "")).strip() or str(data.get("settings", {}).get("comfyApiUrl", "")).strip()
    if not comfy_api_url:
        return jsonify({"error": "ComfyUI URI not configured"}), 400

    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    merged_basic = {**record.get("basicValues", {}), **(input_basic_values if isinstance(input_basic_values, dict) else {})}
    merged_basic = _normalize_basic_values_aliases(merged_basic)
    merged_advanced = {**record.get("advancedValues", {}), **(input_advanced_values if isinstance(input_advanced_values, dict) else {})}
    merged_advanced = _normalize_clip_last_layer_advanced_values(record.get("workflow", {}), merged_advanced)
    merged_advanced = _prune_stale_clip_last_layer_overrides(
        record.get("workflow", {}),
        merged_advanced,
        input_advanced_values if isinstance(input_advanced_values, dict) else {},
    )
    try:
        num_images = int(input_num_images)
    except (TypeError, ValueError):
        num_images = 1
    num_images = max(1, min(num_images, 8))

    try:
        prepared_workflow = _apply_basic_values_to_workflow(
                record, merged_basic, merged_advanced, num_images=num_images,
                disabled_subgraphs=payload.get("disabledSubgraphs"),
            )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    applied_noise_node_id = str(record.get("analysis", {}).get("detected", {}).get("noiseNodeId") or "").strip()
    if not applied_noise_node_id:
        for node_id, node in prepared_workflow.items():
            if isinstance(node, dict) and str(node.get("class_type", "")) == "RandomNoise":
                applied_noise_node_id = str(node_id)
                break

    applied_noise_seed = None
    if applied_noise_node_id and applied_noise_node_id in prepared_workflow:
        node_inputs = prepared_workflow.get(applied_noise_node_id, {}).get("inputs", {})
        if isinstance(node_inputs, dict):
            if "noise_seed" in node_inputs:
                applied_noise_seed = node_inputs.get("noise_seed")
            elif "seed" in node_inputs:
                applied_noise_seed = node_inputs.get("seed")

    applied_sampler_seed = None
    applied_sampler_id = str(record.get("analysis", {}).get("detected", {}).get("samplerNodeId") or "").strip()
    if applied_sampler_id and applied_sampler_id in prepared_workflow:
        node_inputs = prepared_workflow.get(applied_sampler_id, {}).get("inputs", {})
        if isinstance(node_inputs, dict) and "seed" in node_inputs:
            applied_sampler_seed = node_inputs.get("seed")

    _apply_comfy_output_policy(data, prepared_workflow)

    try:
        client_id = input_client_id or uuid.uuid4().hex
        # Held for the whole submit+poll window, not just the POST — the
        # actual GPU work happens between these HTTP calls, not during them
        # (see gpu_coordinator.py).
        with gpu_coordinator.held("comfy"):
            prompt_response = http_json(
                f"{comfy_api_url}/prompt",
                method="POST",
                payload={"prompt": for_comfy(prepared_workflow, comfy_api_url), "client_id": client_id},
                timeout=300,
            )
            prompt_id = str(prompt_response.get("prompt_id", "")).strip()
            if not prompt_id:
                return jsonify({"error": f"ComfyUI prompt failed: {prompt_response}"}), 502

            history_payload = {}
            for _ in range(720):
                time.sleep(0.5)
                history_payload = http_json(f"{comfy_api_url}/history/{prompt_id}", timeout=300)
                if isinstance(history_payload, dict) and prompt_id in history_payload:
                    outputs = history_payload.get(prompt_id, {}).get("outputs", {})
                    if outputs:
                        break

        preferred_save_nodes = record.get("analysis", {}).get("detected", {}).get("saveImageNodeIds", []) or []
        output_node_id, image_entries = _select_output_images(history_payload, prompt_id, preferred_save_nodes)
        if not image_entries:
            return jsonify({"error": "No image output found in ComfyUI history"}), 502

        # Resolve filename_prefix before the loop so we can use it in saved filenames.
        filename_prefix: str | None = None
        if output_node_id and output_node_id in record.get("workflow", {}):
            filename_prefix = record.get("workflow", {}).get(output_node_id, {}).get("inputs", {}).get("filename_prefix")

        images_payload: list[dict[str, Any]] = []
        for idx, image_entry in enumerate(image_entries[:num_images]):
            query = urlencode(
                {
                    "filename": image_entry.get("filename", ""),
                    "subfolder": image_entry.get("subfolder", ""),
                    "type": image_entry.get("type", "output"),
                }
            )
            image_bytes = http_bytes(f"{comfy_api_url}/view?{query}", timeout=300)

            meta: dict[str, str] = {
                "positive": str(merged_basic.get("positive", "") or ""),
                "negative": str(merged_basic.get("negative", "") or ""),
                "seed": str(merged_basic.get("seed", applied_noise_seed or applied_sampler_seed or "0") or "0"),
                "width": str(merged_basic.get("width", "") or ""),
                "height": str(merged_basic.get("height", "") or ""),
                "source": "generate",
                "session": client_id,
                "job": prompt_id,
                "workflow": str(record.get("id", "")),
                "workflow_name": str(record.get("name", "") or ""),
                "checkpoint": str(merged_basic.get("checkpoint", "") or ""),
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            if isinstance(merged_advanced, dict) and merged_advanced:
                meta["advanced_values"] = json.dumps(merged_advanced, ensure_ascii=False)
            saved_filename = _try_save_image_to_output_dir(data, image_bytes, meta, filename_prefix or "comfy-output", idx)

            images_payload.append(
                {
                    "imageDataUrl": "",
                    "filename": image_entry.get("filename"),
                    "subfolder": image_entry.get("subfolder"),
                    "type": image_entry.get("type"),
                    "savedFilename": saved_filename,
                }
            )

    except Exception as exc:
        return jsonify({"error": f"ComfyUI request failed: {exc}"}), 502

    # Re-fetch a fresh copy under the lock for this last small write instead
    # of reusing `data`/`record` from the top of the function — the actual
    # generation above can run for minutes (ComfyUI submit + poll loop),
    # during which another request may have already changed this same
    # import; holding the registry's mutation lock for that whole stretch
    # would also freeze every other read/write in the app for minutes.
    # "remember": false (the MCP) leaves the engine's saved values alone —
    # otherwise an agent's size, negative and seed become the defaults Create
    # shows next, and a seed nobody chose sticks to every later call.
    if payload.get("remember", True) is not False:
        with _registry_transaction() as tx_data:
            tx_record = next(
                (item for item in tx_data.get("imports", []) if item.get("id") == import_id), None
            )
            if tx_record is not None:
                tx_record["basicValues"] = merged_basic
                tx_record["advancedValues"] = merged_advanced

    return jsonify(
        {
            "images": images_payload,
            "promptId": prompt_id,
            "clientId": client_id,
            "outputNodeId": output_node_id,
            "filenamePrefix": filename_prefix or "comfy-output",
            "numImages": len(images_payload),
            "basicValues": merged_basic,
            "appliedSeed": merged_basic.get("seed"),
            "appliedNoiseNodeId": applied_noise_node_id or None,
            "appliedNoiseSeed": applied_noise_seed,
            "appliedSamplerSeed": applied_sampler_seed,
        }
    )


@models_api_bp.post("/models/imports/<import_id>/submit")
def submit_import_generate(import_id: str):
    """Submit a workflow to ComfyUI and return promptId immediately (no polling)."""
    payload = request.get_json(silent=True) or {}
    input_basic_values = payload.get("basicValues", {})
    input_advanced_values = payload.get("advancedValues", {})
    input_num_images = payload.get("numImages", 1)
    input_client_id = str(payload.get("clientId", "")).strip()
    input_image_data_url = str(payload.get("imageDataUrl", "")).strip()

    data = _ensure_registry()
    record = next((item for item in data.get("imports", []) if item.get("id") == import_id), None)
    if record is None:
        return jsonify({"error": "import not found"}), 404

    comfy_api_url = str(record.get("comfyApiUrl", "")).strip() or str(data.get("settings", {}).get("comfyApiUrl", "")).strip()
    if not comfy_api_url:
        return jsonify({"error": "ComfyUI URI not configured"}), 400
    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    merged_basic = {**record.get("basicValues", {}), **(input_basic_values if isinstance(input_basic_values, dict) else {})}
    merged_basic = _normalize_basic_values_aliases(merged_basic)
    merged_advanced = {**record.get("advancedValues", {}), **(input_advanced_values if isinstance(input_advanced_values, dict) else {})}
    merged_advanced = _normalize_clip_last_layer_advanced_values(record.get("workflow", {}), merged_advanced)
    merged_advanced = _prune_stale_clip_last_layer_overrides(
        record.get("workflow", {}),
        merged_advanced,
        input_advanced_values if isinstance(input_advanced_values, dict) else {},
    )
    try:
        num_images = int(input_num_images)
    except (TypeError, ValueError):
        num_images = 1
    num_images = max(1, min(num_images, 8))

    try:
        prepared_workflow = _apply_basic_values_to_workflow(
                record, merged_basic, merged_advanced, num_images=num_images,
                disabled_subgraphs=payload.get("disabledSubgraphs"),
            )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    applied_noise_node_id, applied_noise_seed, applied_sampler_seed = _extract_applied_seeds(record, prepared_workflow)

    # Upload input image to ComfyUI and inject into LoadImage node if workflow supports it.
    has_image_input = bool(record.get("analysis", {}).get("detected", {}).get("hasImageInput", False))
    if input_image_data_url and has_image_input:
        try:
            image_mime, image_bytes = _parse_image_data_url(input_image_data_url)
            upload_filename = f"new-input-{uuid.uuid4().hex[:8]}.png"
            upload_result = http_multipart_upload_image(
                f"{comfy_api_url}/upload/image",
                upload_filename,
                image_bytes,
                image_mime,
            )
            comfy_filename = str(upload_result.get("name", "")).strip()
            if comfy_filename:
                _inject_uploaded_image_into_workflow(prepared_workflow, comfy_filename)
        except Exception as exc:
            return jsonify({"error": f"Image upload failed: {exc}"}), 502
    elif has_image_input:
        # No input image selected in New modal: bypass image-dependent branches.
        detected = record.get("analysis", {}).get("detected", {}) if isinstance(record.get("analysis", {}).get("detected", {}), dict) else {}
        _bypass_optional_image_input_nodes(prepared_workflow, detected, merged_basic)

    _apply_comfy_output_policy(data, prepared_workflow)

    # Fire-and-forget: the actual GPU work runs between this submission and
    # whenever poll_import_result() observes it's done, not during this
    # request — so we wait HERE (before submitting) for LM Studio to be
    # idle, hand the held slot off to poll_import_result under `prompt_id`
    # once we know it, and let that route release it. ttl is the safety net
    # in case the client stops polling before that happens.
    _gpu_wait_token = uuid.uuid4().hex
    gpu_coordinator.acquire("comfy", _gpu_wait_token)
    try:
        client_id = input_client_id or uuid.uuid4().hex
        prompt_response = http_json(
            f"{comfy_api_url}/prompt",
            method="POST",
            payload={"prompt": for_comfy(prepared_workflow, comfy_api_url), "client_id": client_id},
            timeout=30,
        )
        prompt_id = str(prompt_response.get("prompt_id", "")).strip()
        if not prompt_id:
            gpu_coordinator.release("comfy", _gpu_wait_token)
            return jsonify({"error": f"ComfyUI rejected the prompt: {prompt_response}"}), 502
    except Exception as exc:
        gpu_coordinator.release("comfy", _gpu_wait_token)
        return jsonify({"error": f"ComfyUI submit failed: {exc}"}), 502

    gpu_coordinator.release("comfy", _gpu_wait_token)
    gpu_coordinator.acquire("comfy", prompt_id, ttl=600)

    return jsonify(
        {
            "promptId": prompt_id,
            "clientId": client_id,
            "comfyApiUrl": comfy_api_url,
            "basicValues": merged_basic,
            "advancedValues": merged_advanced,
            "appliedSeed": merged_basic.get("seed"),
            "appliedNoiseNodeId": applied_noise_node_id or None,
            "appliedNoiseSeed": applied_noise_seed,
            "appliedSamplerSeed": applied_sampler_seed,
        }
    )


def _ping_comfy(comfy_api_url: str, timeout: int = 12) -> bool:
    """Return True if the ComfyUI instance responds to /system_stats within timeout."""
    try:
        http_json(f"{comfy_api_url}/system_stats", timeout=timeout)
        return True
    except Exception:
        return False


@models_api_bp.post("/models/imports/prepare-queue")
def prepare_queue_workflow():
    """Prepare workflow JSON for direct JS submission to ComfyUI.

    Returns the prepared workflow + metadata without submitting to ComfyUI.
    JS calls this, then POSTs the workflow directly to ComfyUI /prompt.
    """
    payload = request.get_json(silent=True) or {}
    input_basic_values = payload.get("basicValues", {})
    input_advanced_values = payload.get("advancedValues", {})
    input_num_images = payload.get("numImages", 1)
    input_client_id = str(payload.get("clientId", "")).strip()
    input_image_data_url = str(payload.get("imageDataUrl", "")).strip()
    input_target_import_id = str(payload.get("targetImportId", "")).strip()

    data = _ensure_registry()
    active_ids: list[str] = data.get("activeImportIds", [])
    if not isinstance(active_ids, list):
        active_ids = []
    # Backward-compat: if activeImportIds was never populated, fall back to the
    # singular activeImportId so legacy registries can still generate.
    legacy_single = str(data.get("activeImportId", "")).strip()
    if not active_ids and legacy_single:
        active_ids = [legacy_single]

    if input_target_import_id:
        active_ids = [imp_id for imp_id in active_ids if imp_id == input_target_import_id]
        if not active_ids:
            # Last-chance: allow any import in the registry if it matches the target
            all_ids = {str(item.get("id", "")) for item in data.get("imports", []) if isinstance(item, dict)}
            if input_target_import_id in all_ids:
                active_ids = [input_target_import_id]
            else:
                return jsonify({"error": f"Target import '{input_target_import_id}' not found."}), 400

    all_imports: list[dict] = data.get("imports", [])
    default_comfy = str(data.get("settings", {}).get("comfyApiUrl", "")).strip()

    if not active_ids:
        return jsonify({"error": "No active imports in queue. Activate at least one import first."}), 400

    skipped: list[dict] = []

    for imp_id in active_ids:
        record = next((item for item in all_imports if item.get("id") == imp_id), None)
        if record is None:
            continue

        raw_url = str(record.get("comfyApiUrl", "")).strip() or default_comfy
        if not raw_url:
            skipped.append({"id": imp_id, "name": record.get("name", imp_id), "comfyApiUrl": "", "reason": "no_url"})
            continue
        try:
            comfy_api_url = _safe_comfy_url(raw_url)
        except ValueError:
            skipped.append({"id": imp_id, "name": record.get("name", imp_id), "comfyApiUrl": raw_url, "reason": "invalid_url"})
            continue

        merged_basic = {**record.get("basicValues", {}), **(input_basic_values if isinstance(input_basic_values, dict) else {})}
        merged_basic = _normalize_basic_values_aliases(merged_basic)
        merged_advanced = {**record.get("advancedValues", {}), **(input_advanced_values if isinstance(input_advanced_values, dict) else {})}
        merged_advanced = _normalize_clip_last_layer_advanced_values(record.get("workflow", {}), merged_advanced)
        merged_advanced = _prune_stale_clip_last_layer_overrides(
            record.get("workflow", {}),
            merged_advanced,
            input_advanced_values if isinstance(input_advanced_values, dict) else {},
        )
        try:
            num_images = max(1, min(int(input_num_images), 8))
        except (TypeError, ValueError):
            num_images = 1

        try:
            prepared_workflow = _apply_basic_values_to_workflow(
                record, merged_basic, merged_advanced, num_images=num_images,
                disabled_subgraphs=payload.get("disabledSubgraphs"),
            )
        except ValueError as exc:
            skipped.append({"id": imp_id, "name": record.get("name", imp_id), "comfyApiUrl": comfy_api_url, "reason": str(exc)})
            continue

        applied_noise_node_id, applied_noise_seed, applied_sampler_seed = _extract_applied_seeds(record, prepared_workflow)

        # Handle image upload if needed
        has_image_input = bool(record.get("analysis", {}).get("detected", {}).get("hasImageInput", False))
        if input_image_data_url and has_image_input:
            try:
                image_mime, image_bytes = _parse_image_data_url(input_image_data_url)
                upload_filename = f"new-input-{uuid.uuid4().hex[:8]}.png"
                upload_result = http_multipart_upload_image(
                    f"{comfy_api_url}/upload/image",
                    upload_filename,
                    image_bytes,
                    image_mime,
                )
                comfy_filename = str(upload_result.get("name", "")).strip()
                if comfy_filename:
                    _inject_uploaded_image_into_workflow(prepared_workflow, comfy_filename)
            except Exception as exc:
                return jsonify({"error": f"Image upload failed: {exc}"}), 502
        elif has_image_input:
            detected = record.get("analysis", {}).get("detected", {}) if isinstance(record.get("analysis", {}).get("detected", {}), dict) else {}
            _bypass_optional_image_input_nodes(prepared_workflow, detected, merged_basic)

        client_id = input_client_id or uuid.uuid4().hex

        _apply_comfy_output_policy(data, prepared_workflow)
        # The browser submits this straight to ComfyUI: wait here if another
        # installation is using LM Studio on the same GPU (superqueue).
        gpu_coordinator.wait_external("comfy")

        return jsonify({
            "workflow": prepared_workflow,
            "clientId": client_id,
            "comfyApiUrl": comfy_api_url,
            "importId": imp_id,
            "importName": record.get("name", imp_id),
            "basicValues": merged_basic,
            "advancedValues": merged_advanced,
            "appliedSeed": merged_basic.get("seed"),
            "appliedNoiseNodeId": applied_noise_node_id or None,
            "appliedNoiseSeed": applied_noise_seed,
            "appliedSamplerSeed": applied_sampler_seed,
            "skipped": skipped,
        })

    return jsonify({"error": "No valid import found in active queue", "skipped": skipped}), 400


@models_api_bp.post("/models/imports/submit-queue")
def submit_queue_generate():
    """Try each import in activeImportIds in order; submit to first reachable ComfyUI.

    Returns the same shape as submit_import_generate plus:
      - importId: the import that was used
      - skipped: [{id, name, comfyApiUrl}] list of imports that were unreachable
      - allUnreachable: true if no import could be reached
    """
    payload = request.get_json(silent=True) or {}
    input_basic_values = payload.get("basicValues", {})
    input_advanced_values = payload.get("advancedValues", {})
    input_num_images = payload.get("numImages", 1)
    input_client_id = str(payload.get("clientId", "")).strip()
    input_image_data_url = str(payload.get("imageDataUrl", "")).strip()
    input_target_import_id = str(payload.get("targetImportId", "")).strip()

    data = _ensure_registry()
    active_ids: list[str] = data.get("activeImportIds", [])
    if not isinstance(active_ids, list):
        active_ids = []

    # If a specific import is targeted, restrict to only that one.
    if input_target_import_id:
        active_ids = [imp_id for imp_id in active_ids if imp_id == input_target_import_id]
        if not active_ids:
            return jsonify({"error": f"Target import '{input_target_import_id}' is not in the active queue."}), 400

    all_imports: list[dict] = data.get("imports", [])
    default_comfy = str(data.get("settings", {}).get("comfyApiUrl", "")).strip()

    if not active_ids:
        return jsonify({"error": "No active imports in queue. Activate at least one import first."}), 400

    skipped: list[dict] = []

    for imp_id in active_ids:
        record = next((item for item in all_imports if item.get("id") == imp_id), None)
        if record is None:
            continue

        raw_url = str(record.get("comfyApiUrl", "")).strip() or default_comfy
        if not raw_url:
            skipped.append({"id": imp_id, "name": record.get("name", imp_id), "comfyApiUrl": "", "reason": "no_url"})
            continue
        try:
            comfy_api_url = _safe_comfy_url(raw_url)
        except ValueError:
            skipped.append({"id": imp_id, "name": record.get("name", imp_id), "comfyApiUrl": raw_url, "reason": "invalid_url"})
            continue

        if not _ping_comfy(comfy_api_url):
            skipped.append({"id": imp_id, "name": record.get("name", imp_id), "comfyApiUrl": comfy_api_url, "reason": "unreachable"})
            continue

        # This import is reachable — submit the workflow.
        merged_basic = {**record.get("basicValues", {}), **(input_basic_values if isinstance(input_basic_values, dict) else {})}
        merged_basic = _normalize_basic_values_aliases(merged_basic)
        merged_advanced = {**record.get("advancedValues", {}), **(input_advanced_values if isinstance(input_advanced_values, dict) else {})}
        merged_advanced = _normalize_clip_last_layer_advanced_values(record.get("workflow", {}), merged_advanced)
        merged_advanced = _prune_stale_clip_last_layer_overrides(
            record.get("workflow", {}),
            merged_advanced,
            input_advanced_values if isinstance(input_advanced_values, dict) else {},
        )
        try:
            num_images = int(input_num_images)
        except (TypeError, ValueError):
            num_images = 1
        num_images = max(1, min(num_images, 8))

        try:
            prepared_workflow = _apply_basic_values_to_workflow(
                record, merged_basic, merged_advanced, num_images=num_images,
                disabled_subgraphs=payload.get("disabledSubgraphs"),
            )
        except ValueError as exc:
            skipped.append({"id": imp_id, "name": record.get("name", imp_id), "comfyApiUrl": comfy_api_url, "reason": str(exc)})
            continue
        applied_noise_node_id, applied_noise_seed, applied_sampler_seed = _extract_applied_seeds(record, prepared_workflow)

        has_image_input = bool(record.get("analysis", {}).get("detected", {}).get("hasImageInput", False))
        if input_image_data_url and has_image_input:
            try:
                image_mime, image_bytes = _parse_image_data_url(input_image_data_url)
                upload_filename = f"new-input-{uuid.uuid4().hex[:8]}.png"
                upload_result = http_multipart_upload_image(
                    f"{comfy_api_url}/upload/image",
                    upload_filename,
                    image_bytes,
                    image_mime,
                )
                comfy_filename = str(upload_result.get("name", "")).strip()
                if comfy_filename:
                    _inject_uploaded_image_into_workflow(prepared_workflow, comfy_filename)
            except Exception as exc:
                return jsonify({"error": f"Image upload failed: {exc}"}), 502
        elif has_image_input:
            detected = record.get("analysis", {}).get("detected", {}) if isinstance(record.get("analysis", {}).get("detected", {}), dict) else {}
            _bypass_optional_image_input_nodes(prepared_workflow, detected, merged_basic)

        _apply_comfy_output_policy(data, prepared_workflow)

        # Same wait-before-submit / hand-off-to-prompt_id pattern as
        # submit_import_generate — see the comment there.
        _gpu_wait_token = uuid.uuid4().hex
        gpu_coordinator.acquire("comfy", _gpu_wait_token)
        try:
            client_id = input_client_id or uuid.uuid4().hex
            prompt_response = http_json(
                f"{comfy_api_url}/prompt",
                method="POST",
                payload={"prompt": for_comfy(prepared_workflow, comfy_api_url), "client_id": client_id},
                timeout=30,
            )
            prompt_id = str(prompt_response.get("prompt_id", "")).strip()
            if not prompt_id:
                gpu_coordinator.release("comfy", _gpu_wait_token)
                skipped.append({"id": imp_id, "name": record.get("name", imp_id), "comfyApiUrl": comfy_api_url, "reason": "rejected"})
                continue
        except Exception as exc:
            gpu_coordinator.release("comfy", _gpu_wait_token)
            skipped.append({"id": imp_id, "name": record.get("name", imp_id), "comfyApiUrl": comfy_api_url, "reason": str(exc)})
            continue

        gpu_coordinator.release("comfy", _gpu_wait_token)
        gpu_coordinator.acquire("comfy", prompt_id, ttl=600)

        return jsonify(
            {
                "promptId": prompt_id,
                "clientId": client_id,
                "comfyApiUrl": comfy_api_url,
                "importId": imp_id,
                "importName": record.get("name", imp_id),
                "basicValues": merged_basic,
                "advancedValues": merged_advanced,
                "appliedSeed": merged_basic.get("seed"),
                "appliedNoiseNodeId": applied_noise_node_id or None,
                "appliedNoiseSeed": applied_noise_seed,
                "appliedSamplerSeed": applied_sampler_seed,
                "skipped": skipped,
                "allUnreachable": False,
            }
        )

    # All imports were unreachable / skipped.
    return jsonify({"allUnreachable": True, "skipped": skipped, "error": "No reachable ComfyUI found in active queue"}), 503


@models_api_bp.post("/models/imports/<import_id>/result")
def poll_import_result(import_id: str):
    """Check ComfyUI history for a previously submitted prompt. Returns {ready: false} or images."""
    payload = request.get_json(silent=True) or {}
    prompt_id = str(payload.get("promptId", "")).strip()
    client_id = str(payload.get("clientId", "")).strip()
    session_name = str(payload.get("session", "")).strip()
    comfy_api_url_raw = str(payload.get("comfyApiUrl", "")).strip()
    width_hint = _coerce_int_scalar(payload.get("width"))
    height_hint = _coerce_int_scalar(payload.get("height"))
    num_images_hint = _coerce_int_scalar(payload.get("numImages"))
    client_basic_values = payload.get("basicValues", {}) if isinstance(payload.get("basicValues"), dict) else {}
    client_advanced_values = payload.get("advancedValues", {}) if isinstance(payload.get("advancedValues"), dict) else {}

    data = _ensure_registry()
    record = next((item for item in data.get("imports", []) if item.get("id") == import_id), None)
    if record is None:
        return jsonify({"error": "import not found"}), 404
    if not prompt_id:
        return jsonify({"error": "promptId is required"}), 400

    comfy_api_url = comfy_api_url_raw or str(record.get("comfyApiUrl", "")).strip() or str(data.get("settings", {}).get("comfyApiUrl", "")).strip()
    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        basic_values = record.get("basicValues", {}) if isinstance(record.get("basicValues", {}), dict) else {}
        width = width_hint if isinstance(width_hint, int) and width_hint > 0 else _coerce_int_scalar(basic_values.get("width")) or 512
        height = height_hint if isinstance(height_hint, int) and height_hint > 0 else _coerce_int_scalar(basic_values.get("height")) or 512
        num_images = num_images_hint if isinstance(num_images_hint, int) and num_images_hint > 0 else 1
        history_timeout, view_timeout = _compute_comfy_poll_timeouts(width, height, num_images)

        history_payload = http_json(f"{comfy_api_url}/history/{prompt_id}", timeout=history_timeout)
    except Exception as exc:
        # Keep polling resilient: transient ComfyUI/network hiccups should not abort
        # the whole generation flow on the frontend.
        logger.warning("Transient ComfyUI history poll failure for prompt '%s': %s", prompt_id, exc)
        return jsonify({"ready": False, "transientError": f"ComfyUI history request failed: {exc}"})

    def _queue_contains_prompt(value: Any) -> bool:
        if isinstance(value, dict):
            for nested in value.values():
                if _queue_contains_prompt(nested):
                    return True
            return False
        if isinstance(value, (list, tuple)):
            for nested in value:
                if _queue_contains_prompt(nested):
                    return True
            return False
        return str(value or "").strip() == prompt_id

    queue_payload: dict[str, Any] = {}
    try:
        maybe_queue = http_json(f"{comfy_api_url}/queue", timeout=6)
        if isinstance(maybe_queue, dict):
            queue_payload = maybe_queue
    except Exception:
        queue_payload = {}

    status_payload: dict[str, Any] = {}
    try:
        maybe_status = http_json(f"{comfy_api_url}/status", timeout=6)
        if isinstance(maybe_status, dict):
            status_payload = maybe_status
    except Exception:
        status_payload = {}

    queue_running = queue_payload.get("queue_running", []) if isinstance(queue_payload.get("queue_running", []), list) else []
    queue_pending = queue_payload.get("queue_pending", []) if isinstance(queue_payload.get("queue_pending", []), list) else []
    in_running = _queue_contains_prompt(queue_running)
    in_pending = _queue_contains_prompt(queue_pending)

    queue_remaining = None
    exec_info = status_payload.get("exec_info", {}) if isinstance(status_payload.get("exec_info", {}), dict) else {}
    queue_remaining_raw = exec_info.get("queue_remaining")
    if isinstance(queue_remaining_raw, (int, float)):
        queue_remaining = int(queue_remaining_raw)

    pending_state = "waiting_output"
    if in_running:
        pending_state = "running"
    elif in_pending:
        pending_state = "queued"
    elif isinstance(queue_remaining, int) and queue_remaining > 0:
        pending_state = "running"

    if prompt_id not in history_payload:
        return jsonify({"ready": False, "state": pending_state, "promptSeen": False, "queueRemaining": queue_remaining})

    outputs = history_payload.get(prompt_id, {}).get("outputs", {})
    if not outputs:
        return jsonify({"ready": False, "state": pending_state, "promptSeen": True, "queueRemaining": queue_remaining})

    # ComfyUI has actually finished executing this prompt — release the slot
    # acquired at submit time (submit_import_generate/submit_queue_generate)
    # so a waiting LM Studio request can proceed. Everything below is local
    # post-processing (saving files), no more GPU work involved.
    gpu_coordinator.release("comfy", prompt_id)

    preferred_save_nodes = record.get("analysis", {}).get("detected", {}).get("saveImageNodeIds", []) or []
    output_node_id, image_entries = _select_output_images(history_payload, prompt_id, preferred_save_nodes)
    if not image_entries:
        return jsonify({"ready": False, "state": "waiting_output", "promptSeen": True, "queueRemaining": queue_remaining})

    # Resolve filename_prefix before the loop.
    filename_prefix: str | None = None
    if output_node_id and output_node_id in record.get("workflow", {}):
        filename_prefix = record.get("workflow", {}).get(output_node_id, {}).get("inputs", {}).get("filename_prefix")

    basic_values = record.get("basicValues", {}) if isinstance(record.get("basicValues", {}), dict) else {}
    advanced_values = record.get("advancedValues", {}) if isinstance(record.get("advancedValues", {}), dict) else {}
    # Prefer values sent by the client (from the submit response) so the saved
    # metadata always reflects the prompt that was actually used for this generation,
    # not a potentially stale registry value overwritten by a concurrent generation.
    if client_basic_values:
        basic_values = {**basic_values, **client_basic_values}
    if client_advanced_values:
        advanced_values = {**advanced_values, **client_advanced_values}

    history_workflow = history_payload.get(prompt_id, {}).get("prompt", [None, None, None])
    prepared_workflow = history_workflow[2] if isinstance(history_workflow, list) and len(history_workflow) >= 3 and isinstance(history_workflow[2], dict) else {}
    loras_used = _extract_loras_used_from_workflow(prepared_workflow)

    images_payload: list[dict[str, Any]] = []
    for idx, image_entry in enumerate(image_entries):
        query = urlencode(
            {
                "filename": image_entry.get("filename", ""),
                "subfolder": image_entry.get("subfolder", ""),
                "type": image_entry.get("type", "output"),
            }
        )
        try:
            image_bytes = http_bytes(f"{comfy_api_url}/view?{query}", timeout=view_timeout)

            meta: dict[str, str] = {
                "positive": str(basic_values.get("positive", "") or ""),
                "negative": str(basic_values.get("negative", "") or ""),
                "seed": str(basic_values.get("seed", "0") or "0"),
                "width": str(basic_values.get("width", "") or ""),
                "height": str(basic_values.get("height", "") or ""),
                "source": "generate",
                "session": session_name or client_id or "",
                "job": prompt_id,
                "workflow": str(record.get("id", "")),
                "workflow_name": str(record.get("name", "") or ""),
                "checkpoint": str(basic_values.get("checkpoint", "") or ""),
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            if isinstance(advanced_values, dict) and advanced_values:
                meta["advanced_values"] = json.dumps(advanced_values, ensure_ascii=False)
            if loras_used:
                meta["loras_used"] = json.dumps(loras_used, ensure_ascii=False)
            saved_filename = _try_save_image_to_output_dir(data, image_bytes, meta, filename_prefix or "comfy-output", idx)
            preview_data_url = ""
            if not saved_filename:
                preview_data_url = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
                logger.warning(
                    "Image could not be saved to outputDir; returning inline preview for prompt '%s'",
                    prompt_id,
                )

            images_payload.append(
                {
                    "imageDataUrl": preview_data_url,
                    "filename": image_entry.get("filename"),
                    "subfolder": image_entry.get("subfolder"),
                    "type": image_entry.get("type"),
                    "savedFilename": saved_filename,
                }
            )
        except Exception:
            logger.exception("Failed to fetch image bytes for prompt '%s' from ComfyUI", prompt_id)

    if not images_payload:
        return jsonify({"ready": False, "state": "waiting_output", "promptSeen": True, "queueRemaining": queue_remaining})

    return jsonify(
        {
            "ready": True,
            "images": images_payload,
            "outputNodeId": output_node_id,
            "filenamePrefix": filename_prefix or "comfy-output",
            "numImages": len(images_payload),
        }
    )


@models_api_bp.post("/models/prompt-params")
def parse_prompt_params_route():
    """What the Midjourney-style --parameters at the end of a prompt mean
    (NomadStudio#27) — for the pills under Create's prompt box. Same parser
    the graph builder applies (workflow_service._apply_prompt_params), so what
    the pills say is what generation does. Body: {text}. Response: {prompt,
    params: {aspect, no, seed, model, speed, quantization, steps, repeat,
    ignored, invalid}}."""
    from app.services.prompt_params import parse

    payload = request.get_json(silent=True) or {}
    parsed = parse(str(payload.get("text", "") or "")[:20000])
    return jsonify({"prompt": parsed.prompt, "params": parsed.as_dict()})
