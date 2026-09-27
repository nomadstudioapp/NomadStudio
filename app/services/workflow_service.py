from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from typing import Any

from app.config import (
    DEFAULT_LMSTUDIO_CONTEXT_SIZE,
    DEFAULT_LMSTUDIO_TEMPERATURE,
    LMSTUDIO_CONTEXT_SIZE_MAX,
    LMSTUDIO_CONTEXT_SIZE_MIN,
    LMSTUDIO_TEMPERATURE_MAX,
    LMSTUDIO_TEMPERATURE_MIN,
    MAX_URL_LENGTH,
)
from app.services.prompt_params import parse as parse_prompt_params, size_for_aspect
from app.services.subgraph_toggles import apply_disabled_subgraphs, extract_optional_subgraphs

# ---------------------------------------------------------------------------
# Re-exports from sub-modules (keep importable from workflow_service for compat)
# ---------------------------------------------------------------------------

from app.services.workflow_utils import (  # noqa: F401
    CLIP_LAST_LAYER_ALLOWED_VALUES,
    CLIP_LAST_LAYER_INPUT_KEYS,
    _as_scalar,
    _coerce_int_scalar,
    _extract_checkpoint_loader_keys,
    _extract_checkpoint_options_from_object_info,
    _extract_lora_loader_keys,
    _extract_lora_options_from_object_info,
    _extract_seed_from_inputs,
    _extract_unet_loader_keys,
    _extract_unet_options_from_object_info,
    _is_link,
    _is_negative_like_key,
    _is_prompt_like_key,
    _is_sampler_like_node,
    _workflow_load_image_nodes,
)
from app.services.workflow_style_utils import (  # noqa: F401
    _coerce_profile_slot,
    _decode_data_url_image_bytes,
    _extract_filename_from_image_url,
    _get_next_page_number,
    _get_style_page_entry,
    _get_style_profile_entry,
    _style_has_image_for_page,
    _style_has_image_for_slot,
    _style_preview_filename,
    _style_preview_page_path,
)
from app.services.workflow_clip import (  # noqa: F401
    _advanced_input_metadata,
    _apply_clip_last_layer_bypass,
    _extract_clip_last_layer_keys,
    _normalize_clip_last_layer_advanced_values,
    _prune_stale_clip_last_layer_overrides,
    _validate_clip_last_layer_advanced_values,
)
from app.services.workflow_quality import (  # noqa: F401
    _coerce_quality_value,
    _extract_quality_blocks_from_text,
    _extract_quality_presets,
    _extract_quantization_options,
    _normalize_quality_token,
    _quality_field_aliases,
    _resolve_quality_target_key,
)
from app.services.workflow_describe_cache import (  # noqa: F401
    _describe_cache_get,
    _describe_cache_key,
    _get_describe_cache,
)
from app.services.workflow_upscale import (  # noqa: F401
    _build_upscale_models_from_imports,
    _parse_image_data_url,
    _pick_upscale_scale_key,
    _resolve_upscale_scale,
    _upscale_model_by_id,
    _upscale_models_catalog,
)
from app.services.workflow_compose import (  # noqa: F401
    _build_compose_models_from_imports,
    _compose_model_by_id,
    _compose_models_catalog,
)

# ---------------------------------------------------------------------------
# Text / node resolution helpers
# ---------------------------------------------------------------------------


def _resolve_text_from_node(
    workflow: dict[str, Any], node_id: str, visited: set[str] | None = None
) -> str:
    if visited is None:
        visited = set()
    if node_id in visited:
        return ""
    visited.add(node_id)

    node = workflow.get(node_id, {})
    class_type = str(node.get("class_type", ""))
    inputs = node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}

    if class_type == "ConditioningZeroOut":
        return ""

    for key in ("value", "text", "prompt", "string"):
        scalar = _as_scalar(inputs.get(key))
        if isinstance(scalar, str) and scalar.strip():
            return scalar.strip()

    for key in ("text", "conditioning", "prompt", "positive", "negative"):
        link = inputs.get(key)
        if _is_link(link):
            resolved = _resolve_text_from_node(workflow, str(link[0]), visited)
            if resolved:
                return resolved

    for value in inputs.values():
        if _is_link(value):
            resolved = _resolve_text_from_node(workflow, str(value[0]), visited)
            if resolved:
                return resolved

    return ""


def _extract_dimension_from_sampler(
    workflow: dict[str, Any], sampler_node: dict[str, Any]
) -> tuple[int, int, str | None]:
    default_width = 512
    default_height = 512

    def resolve_int(value: Any, visited: set[str] | None = None) -> int | None:
        if visited is None:
            visited = set()
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if _is_link(value):
            node_id = str(value[0])
            if node_id in visited:
                return None
            visited.add(node_id)
            node = workflow.get(node_id, {}) if isinstance(workflow, dict) else {}
            node_inputs = (
                node.get("inputs", {})
                if isinstance(node.get("inputs", {}), dict)
                else {}
            )
            for key in ("value", "width", "height", "seed", "noise_seed"):
                if key in node_inputs:
                    resolved = resolve_int(node_inputs.get(key), visited)
                    if isinstance(resolved, int):
                        return resolved
        return None

    inputs = (
        sampler_node.get("inputs", {})
        if isinstance(sampler_node.get("inputs", {}), dict)
        else {}
    )

    direct_width = resolve_int(inputs.get("width"))
    direct_height = resolve_int(inputs.get("height"))
    if (
        isinstance(direct_width, int)
        and isinstance(direct_height, int)
        and direct_width > 0
        and direct_height > 0
    ):
        return direct_width, direct_height, None

    latent_link = inputs.get("latent_image")
    if not _is_link(latent_link):
        return default_width, default_height, None

    latent_node_id = str(latent_link[0])
    latent_node = workflow.get(latent_node_id, {})
    latent_inputs = (
        latent_node.get("inputs", {})
        if isinstance(latent_node.get("inputs", {}), dict)
        else {}
    )

    width = resolve_int(latent_inputs.get("width", default_width))
    height = resolve_int(latent_inputs.get("height", default_height))

    if not isinstance(width, int):
        width = default_width
    if not isinstance(height, int):
        height = default_height

    return width, height, latent_node_id




# ---------------------------------------------------------------------------
# Workflow analysis
# ---------------------------------------------------------------------------


def _parse_workflow_config_node(workflow: dict) -> dict | None:
    """Return the parsed JSON from the 'config' metadata node, or None if absent/invalid."""
    if not isinstance(workflow, dict):
        return None
    node = workflow.get("config")
    if not isinstance(node, dict):
        return None
    if str(node.get("class_type", "")).strip() != "PrimitiveStringMultiline":
        return None
    inputs = node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
    raw = str(inputs.get("value", "") or "").strip()
    if not raw:
        return None
    try:
        result = json.loads(raw)
    except Exception:
        return None
    return result if isinstance(result, dict) else None


def _analyze_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(workflow, dict):
        raise ValueError("workflow must be a JSON object of nodes")

    save_image_ids: list[str] = []

    # Read optional compose metadata before filtering (keys starting with "_" are not nodes).
    compose_meta = (
        workflow.get("_compose_metadata", {})
        if isinstance(workflow.get("_compose_metadata"), dict)
        else {}
    )
    _cm_input_image_node_id = str(compose_meta.get("inputImageNodeId", "")).strip()
    _cm_style_image_node_id = str(compose_meta.get("styleImageNodeId", "")).strip()
    _cm_resize_node_ids = (
        [str(x) for x in compose_meta.get("resizeNodeIds", []) if str(x).strip()]
        if isinstance(compose_meta.get("resizeNodeIds"), list)
        else []
    )
    _cm_resize_default_enabled = bool(compose_meta.get("resizeDefaultEnabled", True))

    # Extract config node data before filtering (it is not a real ComfyUI node).
    _config_data = _parse_workflow_config_node(workflow)
    # Exclude internal metadata keys and the config node — they are not ComfyUI nodes.
    workflow = {k: v for k, v in workflow.items() if not str(k).startswith("_") and k != "config"}

    sampler_id: str | None = None

    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        if class_type == "SaveImage":
            save_image_ids.append(node_id)
        if sampler_id is None and _is_sampler_like_node(class_type, inputs):
            sampler_id = node_id

    if sampler_id is None:
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            inputs = (
                node.get("inputs", {})
                if isinstance(node.get("inputs", {}), dict)
                else {}
            )
            if _is_sampler_like_node(str(node.get("class_type", "")), inputs):
                sampler_id = node_id
                break

    basic = {
        "positive": "",
        "negative": "",
        "seed": 0,
        "width": 512,
        "height": 512,
    }
    load_image_node_ids = _workflow_load_image_nodes(workflow)

    detected = {
        "saveImageNodeIds": save_image_ids,
        "samplerNodeId": sampler_id,
        "guiderNodeId": None,
        "noiseNodeId": None,
        "positiveNodeId": None,
        "negativeNodeId": None,
        "hasNegativePrompt": False,
        "latentNodeId": None,
        "scaleNodeId": None,
        "scaleInputKey": None,
        "scaleDefault": None,
        "hasImageScaleBy": False,
        "saveImageCount": len(save_image_ids),
        "loadImageNodeIds": load_image_node_ids,
        "hasImageInput": len(load_image_node_ids) > 0,
        "inputImageNodeId": _cm_input_image_node_id
        or (load_image_node_ids[0] if load_image_node_ids else ""),
        "styleImageNodeId": _cm_style_image_node_id,
        "hasStyleImageInput": bool(_cm_style_image_node_id),
        "resizeNodeIds": _cm_resize_node_ids,
    }

    advanced_parameters: list[dict[str, Any]] = []

    sampler_custom_id: str | None = None
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        if class_type == "SamplerCustomAdvanced" and sampler_custom_id is None:
            sampler_custom_id = node_id

    def apply_prompt_links_from_node(node_id: str) -> None:
        node = workflow.get(node_id, {}) if isinstance(workflow, dict) else {}
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )

        def _capture_negative_from_node(candidate_node_id: str) -> bool:
            candidate_node = (
                workflow.get(candidate_node_id, {})
                if isinstance(workflow, dict)
                else {}
            )
            if not isinstance(candidate_node, dict):
                return False
            candidate_inputs = (
                candidate_node.get("inputs", {})
                if isinstance(candidate_node.get("inputs", {}), dict)
                else {}
            )
            for neg_key, neg_value in candidate_inputs.items():
                if not _is_negative_like_key(neg_key):
                    continue
                if _is_link(neg_value):
                    linked_negative_node_id = str(neg_value[0])
                    linked_negative_text = _resolve_text_from_node(
                        workflow, linked_negative_node_id
                    )
                    if linked_negative_text.strip():
                        detected["negativeNodeId"] = linked_negative_node_id
                        basic["negative"] = linked_negative_text
                        detected["hasNegativePrompt"] = True
                        return True
                elif isinstance(neg_value, str) and neg_value.strip():
                    detected["negativeNodeId"] = str(candidate_node_id)
                    basic["negative"] = neg_value.strip()
                    detected["hasNegativePrompt"] = True
                    return True
            return False

        positive_candidates = ["positive", "conditioning", "prompt", "text"]
        negative_candidates = [
            "negative",
            "negative_prompt",
            "negative_conditioning",
            "uncond",
        ]

        for input_key in positive_candidates:
            value = inputs.get(input_key)
            if _is_link(value):
                candidate_node_id = str(value[0])
                candidate_text = _resolve_text_from_node(workflow, candidate_node_id)
                # Keep node mapping even when source text is empty so runtime prompt
                # injection still has a valid target after import.
                detected["positiveNodeId"] = candidate_node_id
                if candidate_text:
                    basic["positive"] = candidate_text
                if not detected["hasNegativePrompt"]:
                    _capture_negative_from_node(candidate_node_id)
                break
            elif isinstance(value, str) and value.strip():
                detected["positiveNodeId"] = str(node_id)
                basic["positive"] = value.strip()
                break

        if not basic["positive"]:
            for input_key, value in inputs.items():
                if not _is_prompt_like_key(input_key) or _is_negative_like_key(
                    input_key
                ):
                    continue
                if _is_link(value):
                    candidate_node_id = str(value[0])
                    candidate_text = _resolve_text_from_node(
                        workflow, candidate_node_id
                    )
                    detected["positiveNodeId"] = candidate_node_id
                    if candidate_text:
                        basic["positive"] = candidate_text
                    if not detected["hasNegativePrompt"]:
                        _capture_negative_from_node(candidate_node_id)
                    break
                elif isinstance(value, str) and value.strip():
                    detected["positiveNodeId"] = str(node_id)
                    basic["positive"] = value.strip()
                    break

        for input_key in negative_candidates:
            value = inputs.get(input_key)
            if _is_link(value):
                candidate_negative_node_id = str(value[0])
                candidate_negative_text = _resolve_text_from_node(
                    workflow, candidate_negative_node_id
                )
                candidate_negative_node = workflow.get(candidate_negative_node_id, {})
                candidate_negative_class = (
                    str(candidate_negative_node.get("class_type", ""))
                    if isinstance(candidate_negative_node, dict)
                    else ""
                )
                if candidate_negative_class != "ConditioningZeroOut":
                    detected["negativeNodeId"] = candidate_negative_node_id
                    if candidate_negative_text.strip():
                        basic["negative"] = candidate_negative_text
                        detected["hasNegativePrompt"] = True
                    break
            elif isinstance(value, str) and value.strip():
                detected["negativeNodeId"] = str(node_id)
                basic["negative"] = value.strip()
                detected["hasNegativePrompt"] = True
                break

        if not detected["hasNegativePrompt"]:
            for input_key, value in inputs.items():
                if not _is_negative_like_key(input_key):
                    continue
                if _is_link(value):
                    candidate_negative_node_id = str(value[0])
                    candidate_negative_text = _resolve_text_from_node(
                        workflow, candidate_negative_node_id
                    )
                    detected["negativeNodeId"] = candidate_negative_node_id
                    if candidate_negative_text.strip():
                        basic["negative"] = candidate_negative_text
                        detected["hasNegativePrompt"] = True
                    break
                elif isinstance(value, str) and value.strip():
                    detected["negativeNodeId"] = str(node_id)
                    basic["negative"] = value.strip()
                    detected["hasNegativePrompt"] = True
                    break

    if sampler_id is not None:
        sampler_node = workflow.get(sampler_id, {})
        sampler_inputs = (
            sampler_node.get("inputs", {})
            if isinstance(sampler_node.get("inputs", {}), dict)
            else {}
        )

        seed = _extract_seed_from_inputs(sampler_inputs)
        if isinstance(seed, int):
            basic["seed"] = seed

        width, height, latent_node_id = _extract_dimension_from_sampler(
            workflow, sampler_node
        )
        basic["width"] = width
        basic["height"] = height
        detected["latentNodeId"] = latent_node_id
        apply_prompt_links_from_node(sampler_id)

        excluded_inputs = {
            "seed",
            "positive",
            "negative",
            "latent_image",
            "model",
            "width",
            "height",
        }
        for input_key, input_value in sampler_inputs.items():
            scalar = _as_scalar(input_value)
            if scalar is None or input_key in excluded_inputs:
                continue
            metadata = _advanced_input_metadata(
                str(sampler_node.get("class_type", "")), input_key
            )
            advanced_parameters.append(
                {
                    "key": f"{sampler_id}.{input_key}",
                    "label": input_key.replace("_", " ").title(),
                    "value": scalar,
                    "nodeId": sampler_id,
                    "nodeClass": str(sampler_node.get("class_type", "")),
                    "inputKey": input_key,
                    **metadata,
                }
            )

    if sampler_custom_id is not None:
        sampler_custom_node = workflow.get(sampler_custom_id, {})
        sampler_custom_inputs = (
            sampler_custom_node.get("inputs", {})
            if isinstance(sampler_custom_node.get("inputs", {}), dict)
            else {}
        )

        width, height, latent_node_id = _extract_dimension_from_sampler(
            workflow, sampler_custom_node
        )
        if not detected.get("latentNodeId"):
            basic["width"] = width
            basic["height"] = height
            detected["latentNodeId"] = latent_node_id

        noise_link = sampler_custom_inputs.get("noise")
        if _is_link(noise_link) and not detected.get("noiseNodeId"):
            noise_node_id = str(noise_link[0])
            detected["noiseNodeId"] = noise_node_id
            noise_node = (
                workflow.get(noise_node_id, {}) if isinstance(workflow, dict) else {}
            )
            noise_inputs = (
                noise_node.get("inputs", {})
                if isinstance(noise_node.get("inputs", {}), dict)
                else {}
            )
            noise_seed = _coerce_int_scalar(
                noise_inputs.get("noise_seed", noise_inputs.get("seed"))
            )
            if isinstance(noise_seed, int):
                basic["seed"] = noise_seed

        guider_link = sampler_custom_inputs.get("guider")
        if _is_link(guider_link) and not detected.get("guiderNodeId"):
            guider_node_id = str(guider_link[0])
            if guider_node_id in workflow:
                detected["guiderNodeId"] = guider_node_id
                apply_prompt_links_from_node(guider_node_id)

        # Expose linked advanced sampler inputs so import analysis shows full Flux chain.
        for input_key in ("noise", "guider", "sampler", "sigmas", "latent_image"):
            input_value = sampler_custom_inputs.get(input_key)
            if not _is_link(input_value):
                continue
            target_node_id = str(input_value[0])
            target_index = int(input_value[1]) if len(input_value) > 1 else 0
            advanced_parameters.append(
                {
                    "key": f"{sampler_custom_id}.{input_key}",
                    "label": input_key.replace("_", " ").title(),
                    "value": f"[{target_node_id}, {target_index}]",
                    "nodeId": sampler_custom_id,
                    "nodeClass": str(sampler_custom_node.get("class_type", "")),
                    "inputKey": input_key,
                    "isLinked": True,
                }
            )

    # If RandomNoise exists, it is the canonical seed source for this workflow.
    if not detected.get("noiseNodeId"):
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            if str(node.get("class_type", "")) == "RandomNoise":
                detected["noiseNodeId"] = str(node_id)
                break

    if detected.get("noiseNodeId"):
        noise_node = (
            workflow.get(str(detected.get("noiseNodeId")), {})
            if isinstance(workflow, dict)
            else {}
        )
        noise_inputs = (
            noise_node.get("inputs", {})
            if isinstance(noise_node.get("inputs", {}), dict)
            else {}
        )
        noise_seed = _coerce_int_scalar(
            noise_inputs.get("noise_seed", noise_inputs.get("seed"))
        )
        if isinstance(noise_seed, int):
            basic["seed"] = noise_seed

    if not basic["positive"]:
        if sampler_id is not None:
            apply_prompt_links_from_node(str(sampler_id))

    if not basic["positive"]:
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type", ""))
            if "TextEncode" in class_type or "PrimitiveString" in class_type:
                text = _resolve_text_from_node(workflow, node_id)
                if text:
                    if not detected.get("positiveNodeId"):
                        detected["positiveNodeId"] = str(node_id)
                    basic["positive"] = text
                    break

    # Keep prompt node ids even when text is intentionally blank.
    if not detected.get("positiveNodeId") or not detected.get("negativeNodeId"):
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type", ""))
            if "TextEncode" not in class_type:
                continue
            meta = (
                node.get("_meta", {}) if isinstance(node.get("_meta", {}), dict) else {}
            )
            title = str(meta.get("title", "")).strip().lower()
            if not detected.get("positiveNodeId") and "positive" in title:
                detected["positiveNodeId"] = str(node_id)
            if not detected.get("negativeNodeId") and "negative" in title:
                detected["negativeNodeId"] = str(node_id)
            if detected.get("positiveNodeId") and detected.get("negativeNodeId"):
                break

    known_advanced_keys = {item["key"] for item in advanced_parameters}

    # Prefer dedicated image-scale nodes for upscale workflows.
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        if class_type not in {"ImageScaleBy", "ImageScale"}:
            continue
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        for candidate_key in ("scale_by", "scale"):
            if candidate_key not in inputs:
                continue
            scale_scalar = _as_scalar(inputs.get(candidate_key))
            if scale_scalar is None:
                continue
            detected["scaleNodeId"] = str(node_id)
            detected["scaleInputKey"] = candidate_key
            detected["scaleDefault"] = scale_scalar
            detected["hasImageScaleBy"] = class_type == "ImageScaleBy"
            break
        if detected.get("scaleNodeId"):
            break

    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        for input_key, input_value in inputs.items():
            scalar = _as_scalar(input_value)
            if scalar is None:
                continue
            if input_key in {"width", "height", "seed", "text", "value"}:
                continue
            composite_key = f"{node_id}.{input_key}"
            if composite_key in known_advanced_keys:
                continue
            metadata = _advanced_input_metadata(class_type, input_key)
            advanced_parameters.append(
                {
                    "key": composite_key,
                    "label": input_key.replace("_", " ").title(),
                    "value": scalar,
                    "nodeId": node_id,
                    "nodeClass": class_type,
                    "inputKey": input_key,
                    **metadata,
                }
            )
            known_advanced_keys.add(composite_key)

    boolean_parameters: list[dict[str, Any]] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type", "")) != "PrimitiveBoolean":
            continue
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        raw_value = inputs.get("value", True)
        default_value = (
            bool(raw_value) if not isinstance(raw_value, bool) else raw_value
        )
        meta = node.get("_meta", {}) if isinstance(node.get("_meta", {}), dict) else {}
        label = str(meta.get("title", "") or "").strip() or "Enable"
        boolean_parameters.append(
            {
                "key": f"{node_id}.value",
                "label": label,
                "value": default_value,
                "nodeId": node_id,
                "nodeClass": "PrimitiveBoolean",
                "inputKey": "value",
            }
        )

    basic_parameters = [
        {
            "key": "positive",
            "label": "Positive",
            "type": "text",
            "value": basic["positive"],
        },
    ]
    if detected["hasNegativePrompt"] or str(basic.get("negative", "")).strip():
        detected["hasNegativePrompt"] = True
        basic_parameters.append(
            {
                "key": "negative",
                "label": "Negative",
                "type": "text",
                "value": basic["negative"],
            }
        )
    basic_parameters.extend(
        [
            {"key": "seed", "label": "Seed", "type": "number", "value": basic["seed"]},
            {
                "key": "width",
                "label": "Width",
                "type": "number",
                "value": basic["width"],
            },
            {
                "key": "height",
                "label": "Height",
                "type": "number",
                "value": basic["height"],
            },
        ]
    )
    if _cm_resize_node_ids:
        basic_parameters.append(
            {
                "key": "resize_enabled",
                "label": "Resize images",
                "type": "boolean",
                "value": _cm_resize_default_enabled,
            }
        )

    # Extract downloads: prefer config node format, fall back to legacy Downloads node.
    downloads: list[dict[str, str]] = []
    _downloads_raw = (
        str(_config_data.get("downloads", "") or "").strip() if _config_data else ""
    )
    if not _downloads_raw:
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            if str(node.get("class_type", "")) != "PrimitiveStringMultiline":
                continue
            meta = node.get("_meta", {}) if isinstance(node.get("_meta", {}), dict) else {}
            if str(meta.get("title", "")).strip() != "Downloads":
                continue
            inputs = (
                node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
            )
            _downloads_raw = str(inputs.get("value", "")).strip()
            break
    for line in _downloads_raw.splitlines():
        line = line.strip()
        if not line or ";uri:" not in line:
            continue
        # Format: subfolder:filename;uri:url
        left, url = line.split(";uri:", 1)
        if ":" in left:
            subfolder, filename = left.split(":", 1)
        else:
            subfolder, filename = "", left
        downloads.append(
            {
                "subfolder": subfolder.strip(),
                "filename": filename.strip(),
                "url": url.strip(),
            }
        )

    quality_presets = _extract_quality_presets(workflow, advanced_parameters)

    if not quality_presets and _config_data and sampler_id:
        profiles = _config_data.get("profiles", {})
        if isinstance(profiles, dict):
            for level_id in ["draft", "medium", "high"]:
                level_data = profiles.get(level_id)
                if not isinstance(level_data, dict):
                    continue
                preset_values: dict[str, Any] = {}
                for field in ("steps", "cfg"):
                    if field in level_data:
                        preset_values[f"{sampler_id}.{field}"] = level_data[field]
                if preset_values:
                    quality_presets.append(
                        {
                            "id": level_id,
                            "label": level_id.title(),
                            "values": preset_values,
                        }
                    )

    quantization = _extract_quantization_options(workflow, _config_data)
    optional_subgraphs = extract_optional_subgraphs(workflow)

    return {
        "detected": detected,
        "basicParameters": basic_parameters,
        "basicValues": basic,
        "advancedParameters": advanced_parameters,
        "booleanParameters": boolean_parameters,
        "downloads": downloads,
        "qualityPresets": quality_presets,
        "quantization": quantization,
        "configNode": _config_data or {},
        "optionalSubgraphs": optional_subgraphs,
    }


# ---------------------------------------------------------------------------
# Record / negative normalization
# ---------------------------------------------------------------------------


def _normalize_record_negative(record: dict[str, Any]) -> bool:
    workflow = (
        record.get("workflow", {})
        if isinstance(record.get("workflow", {}), dict)
        else {}
    )
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
    basic_values = (
        record.get("basicValues", {})
        if isinstance(record.get("basicValues", {}), dict)
        else {}
    )

    negative_node_id = detected.get("negativeNodeId")
    if not negative_node_id:
        if detected.get("hasNegativePrompt"):
            detected["hasNegativePrompt"] = False
            analysis["detected"] = detected
            record["analysis"] = analysis
            return True
        return False

    negative_text = _resolve_text_from_node(workflow, str(negative_node_id))
    negative_node = (
        workflow.get(str(negative_node_id), {}) if isinstance(workflow, dict) else {}
    )
    negative_class = (
        str(negative_node.get("class_type", ""))
        if isinstance(negative_node, dict)
        else ""
    )
    has_negative_slot = negative_class != "ConditioningZeroOut"

    changed = False
    if detected.get("hasNegativePrompt") != has_negative_slot:
        detected["hasNegativePrompt"] = has_negative_slot
        changed = True

    if not has_negative_slot and detected.get("negativeNodeId") is not None:
        detected["negativeNodeId"] = None
        changed = True

    if has_negative_slot and str(basic_values.get("negative", "")) != str(
        negative_text
    ):
        basic_values["negative"] = str(negative_text)
        record["basicValues"] = basic_values
        changed = True

    if not has_negative_slot and str(basic_values.get("negative", "")).strip():
        basic_values["negative"] = ""
        record["basicValues"] = basic_values
        changed = True

    analysis["detected"] = detected
    record["analysis"] = analysis
    return changed



# ---------------------------------------------------------------------------
# Payload / URL helpers
# ---------------------------------------------------------------------------


def _parse_workflow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    workflow = payload.get("workflow")
    if isinstance(workflow, str):
        workflow = json.loads(workflow)
    if not isinstance(workflow, dict):
        raise ValueError("workflow is required and must be an object")
    return workflow


def _safe_comfy_url(raw: str) -> str:
    value = raw.strip().rstrip("/")
    if not value:
        raise ValueError("ComfyUI URI is required")
    if len(value) > MAX_URL_LENGTH:
        raise ValueError(f"ComfyUI URI exceeds max length ({MAX_URL_LENGTH})")
    if not value.startswith("http://") and not value.startswith("https://"):
        raise ValueError("ComfyUI URI must start with http:// or https://")
    return value


def _safe_http_url(raw: str, label: str) -> str:
    value = raw.strip().rstrip("/")
    if not value:
        raise ValueError(f"{label} URI is required")
    if len(value) > MAX_URL_LENGTH:
        raise ValueError(f"{label} URI exceeds max length ({MAX_URL_LENGTH})")
    if not value.startswith("http://") and not value.startswith("https://"):
        raise ValueError(f"{label} URI must start with http:// or https://")
    return value


# ---------------------------------------------------------------------------
# Text clipping
# ---------------------------------------------------------------------------


def _clip_text(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars]


# ---------------------------------------------------------------------------
# LM Studio context / temperature coercion
# ---------------------------------------------------------------------------


def _coerce_context_size(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        return DEFAULT_LMSTUDIO_CONTEXT_SIZE
    return max(LMSTUDIO_CONTEXT_SIZE_MIN, min(parsed, LMSTUDIO_CONTEXT_SIZE_MAX))


# Every studio call clears this comfortably; it exists so a short prompt does
# not load the model with a tiny window and so the value never depends on a
# number someone guessed months ago.
_AUTO_CONTEXT_FLOOR = 16384


def _auto_context_size(*texts: Any) -> int:
    """Size the context window from the text actually being sent.

    This replaces a stored number the user had to guess. As a slider it was
    the worst kind of control: what it advertised was not measurable, and what
    it really did was not advertised.

    Measured on the Templateize call, same prompt, moving the stored value
    across a 32x range — 2048 -> 8.6s/9.3s, 16384 -> 8.4s/9.5s, 65535 ->
    8.7s/8.5s. The "lower = faster replies" the label promised does not show
    up at all.

    What it did control was truncation. Every studio route derives its
    _clip_text budget from this number, so the bottom half of the slider
    quietly cut the user's own prompt before sending it — at 512 the
    Templateize budget was 614 characters, and the cyberpunk prompt that
    exposed all of this is 572. Forty-two characters from being cut
    mid-sentence, with nothing on screen to say so.

    So: derive it instead. Roughly four characters per token, doubled for the
    system prompt and the model's own answer, and rounded up the power-of-two
    ladder LM Studio's own presets use.

    Pass every string that will travel with the call — for the flows that keep
    a conversation going, that means the accumulated previous answers too, not
    just the new input.

    The floor is what makes this safe rather than clever: studio inputs are
    clipped to at most 4000 characters and the system prompts run to about
    2000, so a whole call is on the order of 2000 tokens and _AUTO_CONTEXT_FLOOR
    already has room to spare. The arithmetic only matters for the long
    accumulated conversations, which is exactly where a fixed number was
    wrong before.
    """
    chars = sum(len(str(t)) for t in texts if t)
    needed = (chars // 2) + 2048
    size = _AUTO_CONTEXT_FLOOR
    while size < needed and size < LMSTUDIO_CONTEXT_SIZE_MAX:
        size *= 2
    return max(LMSTUDIO_CONTEXT_SIZE_MIN, min(size, LMSTUDIO_CONTEXT_SIZE_MAX))


def _coerce_lmstudio_temperature(value: Any) -> float:
    try:
        parsed = float(value)
    except Exception:
        return DEFAULT_LMSTUDIO_TEMPERATURE
    return max(LMSTUDIO_TEMPERATURE_MIN, min(parsed, LMSTUDIO_TEMPERATURE_MAX))



# ---------------------------------------------------------------------------
# Workflow image injection / resize / link helpers
# ---------------------------------------------------------------------------


def _inject_uploaded_image_into_workflow(
    prepared_workflow: dict[str, Any],
    comfy_filename: str,
    *,
    node_id: str | None = None,
    style_filename: str | None = None,
    style_node_id: str | None = None,
) -> bool:
    """Inject one or two images into LoadImage nodes.

    If *node_id* is given, inject *comfy_filename* into that specific node;
    otherwise fall back to the first detected LoadImage node.
    If *style_filename* and *style_node_id* are given, also inject the style
    image into that node.
    """

    def _set_image(wf: dict[str, Any], target_id: str, filename: str) -> bool:
        node = wf.get(target_id, {})
        if not isinstance(node, dict):
            return False
        inputs = node.setdefault("inputs", {})
        if not isinstance(inputs, dict):
            return False
        inputs["image"] = filename
        return True

    nodes = _workflow_load_image_nodes(prepared_workflow)
    if not nodes:
        return False

    # Inject main input image
    main_target = node_id if node_id and node_id in prepared_workflow else nodes[0]
    _set_image(prepared_workflow, main_target, comfy_filename)

    # Inject style image if provided
    if style_filename and style_node_id and style_node_id in prepared_workflow:
        _set_image(prepared_workflow, style_node_id, style_filename)

    return True


def _apply_resize_toggle_to_workflow(
    prepared_workflow: dict[str, Any],
    resize_node_ids: list[str],
    enabled: bool,
) -> None:
    """When resize is disabled, set scale_longer_dimension to a no-op value on all resize nodes."""
    for nid in resize_node_ids:
        node = prepared_workflow.get(nid)
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        if "scale_longer_dimension" in inputs:
            inputs["scale_longer_dimension"] = (
                inputs["scale_longer_dimension"] if enabled else 99999
            )


def _replace_links_from_node_output(
    workflow: dict[str, Any],
    source_node_id: str,
    output_index: int,
    replacement: Any,
) -> int:
    replaced = 0
    if not isinstance(workflow, dict):
        return replaced

    src = str(source_node_id)
    out_idx = int(output_index)

    for _, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        for key, value in list(inputs.items()):
            if not _is_link(value):
                continue
            if str(value[0]) != src:
                continue
            if int(value[1]) != out_idx:
                continue
            inputs[key] = deepcopy(replacement)
            replaced += 1
    return replaced


def _swap_save_image_for_preview(prepared_workflow: dict[str, Any]) -> int:
    """Replace every ``SaveImage`` node with ``PreviewImage`` in place, so
    ComfyUI writes the result to its own ``temp/`` folder instead of the
    permanent ``output/`` folder — used for Vanish Session generations
    (Create only), which must never leave a file the app could point back
    to. ``PreviewImage`` takes the same ``images`` input, just no
    ``filename_prefix``, so this is a pure class_type swap. Returns how many
    nodes were changed (0 is fine — some graphs may already use a different
    terminal node)."""
    if not isinstance(prepared_workflow, dict):
        return 0
    swapped = 0
    for node in prepared_workflow.values():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type", "")) != "SaveImage":
            continue
        node["class_type"] = "PreviewImage"
        inputs = node.get("inputs")
        if isinstance(inputs, dict):
            inputs.pop("filename_prefix", None)
        swapped += 1
    return swapped


def _fallback_latent_node_id_for_image_bypass(
    workflow: dict[str, Any], detected: dict[str, Any]
) -> str | None:
    latent_id = str(detected.get("latentNodeId", "")).strip()
    if latent_id and latent_id in workflow:
        return latent_id

    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type", "")) == "EmptyFlux2LatentImage":
            return str(node_id)

    return None


def _bypass_optional_image_input_nodes(
    prepared_workflow: dict[str, Any],
    detected: dict[str, Any],
    merged_basic: dict[str, Any],
) -> dict[str, int]:
    """
    Bypass image-dependent branches when workflow supports optional image input
    but no image was provided by the user.

    Strategy:
    - Replace GetImageSize width/height outputs with explicit numeric width/height.
    - Replace VAEEncode latent outputs with the workflow latent source (EmptyFlux2LatentImage-like node).
    """
    counters = {
        "getImageSizeWidthLinks": 0,
        "getImageSizeHeightLinks": 0,
        "vaeEncodeLatentLinks": 0,
    }

    if not isinstance(prepared_workflow, dict):
        return counters

    load_image_node_ids = _workflow_load_image_nodes(prepared_workflow)
    if not load_image_node_ids:
        return counters

    width = _coerce_int_scalar(merged_basic.get("width")) or 512
    height = _coerce_int_scalar(merged_basic.get("height")) or 512
    latent_fallback_id = _fallback_latent_node_id_for_image_bypass(
        prepared_workflow, detected
    )

    for node_id, node in prepared_workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )

        if class_type == "GetImageSize":
            image_link = inputs.get("image")
            if _is_link(image_link) and str(image_link[0]) in load_image_node_ids:
                counters["getImageSizeWidthLinks"] += _replace_links_from_node_output(
                    prepared_workflow, str(node_id), 0, int(width)
                )
                counters["getImageSizeHeightLinks"] += _replace_links_from_node_output(
                    prepared_workflow, str(node_id), 1, int(height)
                )
            continue

        if class_type == "VAEEncode" and latent_fallback_id:
            pixels_link = inputs.get("pixels")
            if _is_link(pixels_link) and str(pixels_link[0]) in load_image_node_ids:
                counters["vaeEncodeLatentLinks"] += _replace_links_from_node_output(
                    prepared_workflow, str(node_id), 0, [str(latent_fallback_id), 0]
                )

    return counters



# ---------------------------------------------------------------------------
# Text target node / LoRA chain helpers
# ---------------------------------------------------------------------------


def _find_text_target_node(
    workflow: dict[str, Any],
    node_id: str,
    target: str = "positive",
    visited: set[str] | None = None,
) -> tuple[str | None, str | None]:
    if visited is None:
        visited = set()
    if node_id in visited:
        return None, None
    visited.add(node_id)

    node = workflow.get(node_id, {})
    if not isinstance(node, dict):
        return None, None
    inputs = node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}

    target_mode = str(target or "positive").strip().lower()
    if target_mode == "negative":
        preferred_scalar_keys = (
            "negative_prompt",
            "negative",
            "neg_prompt",
            "negative_conditioning",
            "uncond",
        )
        link_keys = (
            "negative",
            "negative_prompt",
            "negative_conditioning",
            "uncond",
            "conditioning",
            "prompt",
            "text",
            "positive",
        )
        fallback_scalar_keys = ("value", "text", "prompt", "string")
    else:
        preferred_scalar_keys = ("prompt", "positive", "text", "string", "value")
        link_keys = ("positive", "conditioning", "prompt", "text", "negative")
        fallback_scalar_keys = ()

    for key in preferred_scalar_keys:
        if isinstance(inputs.get(key), str):
            return node_id, key

    for key in fallback_scalar_keys:
        if isinstance(inputs.get(key), str):
            return node_id, key

    for key in link_keys:
        value = inputs.get(key)
        if _is_link(value):
            found_node, found_key = _find_text_target_node(
                workflow, str(value[0]), target=target_mode, visited=visited
            )
            if found_node and found_key:
                return found_node, found_key

    for value in inputs.values():
        if _is_link(value):
            found_node, found_key = _find_text_target_node(
                workflow, str(value[0]), target=target_mode, visited=visited
            )
            if found_node and found_key:
                return found_node, found_key

    return None, None


def _next_numeric_node_id(workflow: dict[str, Any]) -> str:
    used_ids = {str(node_id) for node_id in workflow.keys()}
    max_numeric = 0
    for node_id in used_ids:
        if re.fullmatch(r"\d+", node_id):
            try:
                max_numeric = max(max_numeric, int(node_id))
            except Exception:
                continue

    candidate = max_numeric + 1 if max_numeric > 0 else 10000
    while str(candidate) in used_ids:
        candidate += 1
    return str(candidate)


def _collect_node_output_consumers(
    workflow: dict[str, Any], source_node_id: str
) -> list[tuple[str, str, int]]:
    consumers: list[tuple[str, str, int]] = []
    source = str(source_node_id)
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        for input_key, input_value in inputs.items():
            if not _is_link(input_value):
                continue
            if str(input_value[0]) != source:
                continue
            output_index = (
                int(input_value[1])
                if len(input_value) > 1 and isinstance(input_value[1], int)
                else 0
            )
            consumers.append((str(node_id), str(input_key), output_index))
    return consumers


def _normalize_lora_chain_payload(
    raw_items: Any, max_items: int = 4
) -> list[dict[str, Any]]:
    if raw_items is None:
        return []
    if not isinstance(raw_items, list):
        raise ValueError("LoRA chain must be a list")

    max_additional = max(0, int(max_items) - 1)
    if len(raw_items) > max_additional:
        raise ValueError(f"LoRA chain exceeds limit ({max_items} total LoRAs)")

    normalized: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        lora_name = str(item.get("lora_name", "")).strip()
        if not lora_name:
            continue

        entry: dict[str, Any] = {"lora_name": lora_name}

        strength_model_raw = item.get("strength_model")
        if strength_model_raw is not None and str(strength_model_raw).strip() != "":
            try:
                entry["strength_model"] = float(strength_model_raw)
            except Exception as exc:
                raise ValueError(
                    f"Invalid strength_model for LoRA '{lora_name}': {exc}"
                ) from exc

        strength_clip_raw = item.get("strength_clip")
        if strength_clip_raw is not None and str(strength_clip_raw).strip() != "":
            try:
                entry["strength_clip"] = float(strength_clip_raw)
            except Exception as exc:
                raise ValueError(
                    f"Invalid strength_clip for LoRA '{lora_name}': {exc}"
                ) from exc

        normalized.append(entry)

    return normalized


def _ensure_lora_loader_node(
    workflow: dict[str, Any], advanced_values: dict[str, Any]
) -> None:
    """Bootstrap the *first* LoraLoaderModelOnly node for a base workflow that
    ships with none (Krea 2 / Z-Image Turbo / Flux Klein / Ideogram 4 — Qwen
    Image already has one baked in for its Lightning LoRA and needs no help
    here). Mutates *workflow* in place.

    No-ops if the workflow already has a LoRA node — `_apply_lora_chain_to_workflow`
    (below) already owns that case, and needs an existing node to clone as a
    template. This function exists purely to give it one to work with, by
    finding the workflow's UNETLoader, inserting a fresh LoraLoaderModelOnly
    right after it, and rewiring whoever consumed the loader's MODEL output
    (a KSampler directly, or something else like a model-patch node) to go
    through the new node instead.

    Picked via a sentinel advanced-value key, "<unet_node_id>.__insert_lora"
    (set by the frontend's LoRA treeview, flow-step-workflow-picker.js) —
    never written into any node's `inputs` itself, same protection
    `__lora_chain` already relies on (the generic advanced-values loop in
    `_apply_basic_values_to_workflow` skips any key starting with "__").
    """
    if not isinstance(workflow, dict) or not isinstance(advanced_values, dict):
        return
    if _extract_lora_loader_keys(workflow):
        return  # a LoRA node already exists — the chain function owns this workflow

    unet_keys = _extract_unet_loader_keys(workflow)
    if not unet_keys:
        return

    def _current_unet_name(key: str) -> str:
        node_id = key.split(".", 1)[0]
        node = workflow.get(node_id)
        inputs = node.get("inputs") if isinstance(node, dict) and isinstance(node.get("inputs"), dict) else {}
        return str(inputs.get("unet_name", "") or "")

    # Same "skip the unconditional branch" heuristic _extract_quantization_options
    # already uses for Ideogram 4's dual-UNETLoader CFG pair — v1 only wires
    # the main branch.
    unconditional_key = next(
        (k for k in unet_keys if "unconditional" in _current_unet_name(k).lower()), None
    )
    target_key = next((k for k in unet_keys if k != unconditional_key), unet_keys[0])
    unet_node_id = target_key.split(".", 1)[0]

    insert_key = f"{unet_node_id}.__insert_lora"
    lora_name = str(advanced_values.get(insert_key, "") or "").strip()
    if not lora_name:
        return

    consumers = _collect_node_output_consumers(workflow, unet_node_id)
    if not consumers:
        return

    new_node_id = _next_numeric_node_id(workflow)
    workflow[new_node_id] = {
        "class_type": "LoraLoaderModelOnly",
        "inputs": {
            "model": [unet_node_id, 0],
            "lora_name": lora_name,
            "strength_model": 1,
        },
        "_meta": {"title": "Load LoRA (Model only)"},
    }

    for node_id, input_key, output_index in consumers:
        node = workflow.get(node_id)
        if not isinstance(node, dict):
            continue
        node_inputs = node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        current = node_inputs.get(input_key)
        if _is_link(current) and str(current[0]) == unet_node_id:
            node_inputs[input_key] = [new_node_id, output_index]


def _apply_lora_chain_to_workflow(
    workflow: dict[str, Any], advanced_values: dict[str, Any], max_items: int = 4
) -> None:
    if not isinstance(workflow, dict) or not isinstance(advanced_values, dict):
        return

    lora_keys = _extract_lora_loader_keys(workflow)
    if not lora_keys:
        return

    base_key = str(lora_keys[0])
    if "." not in base_key:
        return

    base_node_id = base_key.split(".", 1)[0]
    chain_key = f"{base_node_id}.__lora_chain"
    chain_items = _normalize_lora_chain_payload(
        advanced_values.get(chain_key), max_items=max_items
    )
    if not chain_items:
        return

    base_node = workflow.get(base_node_id, {})
    if not isinstance(base_node, dict):
        raise ValueError("LoRA chain could not be applied: base LoRA node missing")

    base_inputs = (
        base_node.get("inputs", {})
        if isinstance(base_node.get("inputs", {}), dict)
        else {}
    )
    base_selected_lora = str(
        advanced_values.get(base_key, base_inputs.get("lora_name", ""))
    ).strip()
    if base_selected_lora:
        base_inputs["lora_name"] = base_selected_lora
    if not _is_link(base_inputs.get("model")):
        raise ValueError("LoRA chain requires base LoRA node with linked model input")

    # Capture existing downstream consumers before creating chained nodes,
    # then redirect them to the last chained node.
    existing_consumers = _collect_node_output_consumers(workflow, base_node_id)
    template_node = deepcopy(base_node)

    previous_node_id = str(base_node_id)
    final_node_id = previous_node_id
    new_node_ids: list[str] = []

    for item in chain_items:
        lora_name = str(item.get("lora_name", "")).strip()
        if not lora_name:
            continue
        next_node = deepcopy(template_node)
        next_inputs = next_node.setdefault("inputs", {})
        next_inputs["model"] = [previous_node_id, 0]
        if "clip" in next_inputs and isinstance(next_inputs["clip"], list):
            next_inputs["clip"] = [previous_node_id, 1]
        next_inputs["lora_name"] = lora_name

        if "strength_model" in item and "strength_model" in next_inputs:
            next_inputs["strength_model"] = item.get("strength_model")
        if "strength_clip" in item and "strength_clip" in next_inputs:
            next_inputs["strength_clip"] = item.get("strength_clip")

        new_node_id = _next_numeric_node_id(workflow)
        workflow[new_node_id] = next_node
        new_node_ids.append(new_node_id)
        previous_node_id = new_node_id
        final_node_id = new_node_id

    for node_id, input_key, output_index in existing_consumers:
        if node_id in new_node_ids:
            continue
        node = workflow.get(node_id, {})
        if not isinstance(node, dict):
            continue
        node_inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        current = node_inputs.get(input_key)
        if not _is_link(current):
            continue
        if str(current[0]) != str(base_node_id):
            continue
        node_inputs[input_key] = [final_node_id, output_index]


def _extract_loras_used_from_workflow(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(workflow, dict):
        return []

    supported_classes = {"LoraLoader", "LoraLoaderModelOnly"}
    items: list[dict[str, Any]] = []

    def _is_lora_loader_node(node: dict[str, Any]) -> bool:
        class_type = str(node.get("class_type", "")).strip()
        if class_type in supported_classes:
            return True
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        if "lora_name" not in inputs:
            return False
        meta = node.get("_meta", {}) if isinstance(node.get("_meta", {}), dict) else {}
        title = str(meta.get("title", "")).strip().lower()
        class_lower = class_type.lower()
        return ("lora" in class_lower) or ("load lora" in title) or (title == "lora")

    def _sort_key(value: str) -> tuple[int, str]:
        text = str(value)
        if text.isdigit():
            return (0, f"{int(text):012d}")
        return (1, text)

    for node_id in sorted(workflow.keys(), key=_sort_key):
        node = workflow.get(node_id, {})
        if not isinstance(node, dict):
            continue
        if not _is_lora_loader_node(node):
            continue

        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        raw_lora_name = inputs.get("lora_name")
        if _is_link(raw_lora_name):
            lora_name = _resolve_text_from_node(workflow, str(raw_lora_name[0]))
        else:
            lora_name = str(raw_lora_name or "").strip()
        if not lora_name:
            continue

        entry: dict[str, Any] = {"lora_name": lora_name}

        strength_model = _as_scalar(inputs.get("strength_model"))
        if (
            isinstance(strength_model, (int, float, str))
            and str(strength_model).strip() != ""
        ):
            entry["strength_model"] = strength_model

        strength_clip = _as_scalar(inputs.get("strength_clip"))
        if (
            isinstance(strength_clip, (int, float, str))
            and str(strength_clip).strip() != ""
        ):
            entry["strength_clip"] = strength_clip

        items.append(entry)

    return items



# ---------------------------------------------------------------------------
# Basic values normalization / application
# ---------------------------------------------------------------------------


def _normalize_basic_values_aliases(raw_basic_values: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_basic_values, dict):
        return {}

    basic_values = dict(raw_basic_values)

    positive_value = str(basic_values.get("positive", "") or "").strip()
    prompt_value = str(basic_values.get("prompt", "") or "").strip()
    if not positive_value and prompt_value:
        basic_values["positive"] = basic_values.get("prompt")
    elif positive_value and not prompt_value:
        basic_values["prompt"] = basic_values.get("positive")

    negative_value = str(basic_values.get("negative", "") or "").strip()
    negative_prompt_value = str(basic_values.get("negative_prompt", "") or "").strip()
    if not negative_value and negative_prompt_value:
        basic_values["negative"] = basic_values.get("negative_prompt")
    elif negative_value and not negative_prompt_value:
        basic_values["negative_prompt"] = basic_values.get("negative")

    return basic_values


def _active_lora_file_names(
    workflow: dict[str, Any], advanced_values: dict[str, Any]
) -> list[str]:
    """Base names of the LoRAs this generation will actually run with.

    Read from the workflow's own LoraLoader nodes and from any `*.lora_name`
    advanced override, because a LoRA picked at generate time only exists in
    the overrides — trusting the stored annotation alone would attach the
    keywords of a LoRA the user just swapped out.
    """
    names: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        candidate = os.path.basename(str(raw or "").replace("\\", "/")).strip()
        if candidate and candidate.lower() not in seen:
            seen.add(candidate.lower())
            names.append(candidate)

    for key, value in (advanced_values or {}).items():
        if not str(key).endswith("lora_name"):
            continue
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    _add(entry.get("lora_name"))
                else:
                    _add(entry)
        else:
            _add(value)

    for node in (workflow or {}).values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if isinstance(inputs, dict) and not _is_link(inputs.get("lora_name")):
            _add(inputs.get("lora_name"))

    return names


def _prefix_lora_trigger_words(
    record: dict[str, Any],
    workflow: dict[str, Any],
    advanced_values: dict[str, Any],
    disabled: Any,
    positive: str,
) -> str:
    """Prepend the active LoRAs' trigger words to the positive prompt.

    A LoRA usually needs its trigger words present to do its job, and when
    they are missing it does not fail — it just underperforms, silently, with
    nothing to tell the user why. The words are captured per LoRA at import
    time (`annotation.loras[].triggerWords`) and injected here.

    Here, specifically, rather than anywhere upstream: this is the single
    point every Create flow passes through, and it sits *after* the LLM steps.
    Trigger words are magic tokens, not prose — routed through Assist or
    Compose they would be reworded or dropped when the model rewrites the
    prompt. Injected at generation they arrive intact, and the behaviour is
    identical across flows that use an LLM and flows that don't.

    `disabled` is the per-LoRA opt-out from the generate panel: a list of file
    names whose keywords should be skipped this time without deleting the
    stored value.
    """
    text = str(positive or "")
    annotation = record.get("annotation") if isinstance(record, dict) else None
    stored = (annotation or {}).get("loras") if isinstance(annotation, dict) else None
    if not isinstance(stored, list) or not stored:
        return text

    off = {
        os.path.basename(str(item or "").replace("\\", "/")).strip().lower()
        for item in (disabled if isinstance(disabled, (list, tuple, set)) else [])
    }
    active = {name.lower() for name in _active_lora_file_names(workflow, advanced_values)}
    if not active:
        return text

    existing = _prompt_words_present(text)
    words: list[str] = []
    seen: set[str] = set()
    for entry in stored:
        if not isinstance(entry, dict):
            continue
        file_name = os.path.basename(str(entry.get("fileName", "") or "")).strip()
        if not file_name or file_name.lower() not in active or file_name.lower() in off:
            continue
        for word in str(entry.get("triggerWords", "") or "").split(","):
            word = word.strip()
            if not word:
                continue
            key = word.lower()
            # Don't repeat a trigger the user already typed: some models are
            # sensitive to duplicated tokens. Whole words only — "photo" is
            # not already there because the prompt says "photography".
            if key in seen or _word_present(key, existing):
                continue
            seen.add(key)
            words.append(word)

    if not words:
        return text
    inside = _lora_words_inside_json(text, words)
    if inside is not None:
        return inside
    prefix = ", ".join(words)
    return f"{prefix}, {text}" if text.strip() else prefix


# Where trigger words belong inside a JSON prompt, best fit first. The Layout
# flows compose an Ideogram document whose `style_description.aesthetics` is
# "art style, movement, visual treatment" — which is what trigger words are.
_JSON_WORD_FIELDS = ("style", "aesthetics", "prompt", "positive", "description",
                     "high_level_description", "subject", "text")


def _word_present(word: str, haystack: str) -> bool:
    """Is this trigger word already in the prompt, as a whole word?"""
    return re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", haystack) is not None


def _prompt_words_present(text: str) -> str:
    """The text to check a trigger word against before adding it. In a JSON
    prompt only the values count: `style_description` has a field named
    `photo`, and a field name must not suppress a real trigger word."""
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            document = json.loads(stripped)
        except ValueError:
            return text.lower()

        def strings(node):
            if isinstance(node, str):
                yield node
            elif isinstance(node, dict):
                for value in node.values():
                    yield from strings(value)
            elif isinstance(node, list):
                for value in node:
                    yield from strings(value)

        return " ".join(strings(document)).lower()
    return text.lower()


def _lora_words_inside_json(text: str, words: list[str]) -> str | None:
    """Put the words *inside* a JSON prompt instead of in front of it.

    Simple JSON and the Layout flows send a JSON document as the prompt.
    Prepending "word1, word2, {…}" leaves loose tokens hanging outside the
    structure the flow just built, so they go into the field that describes
    the style instead.

    Returns the new JSON, the text unchanged when the document has nowhere
    sensible to put them, or None when the prompt is not JSON at all (the
    caller then prepends, as before)."""
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        return None
    try:
        document = json.loads(stripped)
    except ValueError:
        return None
    if not isinstance(document, dict):
        return None

    def add(value: str) -> str:
        value = value.strip()
        return f"{value}, {', '.join(words)}" if value else ", ".join(words)

    style = document.get("style_description")
    if isinstance(style, dict):
        for key in ("aesthetics", "medium", "photo"):
            if isinstance(style.get(key), str):
                style[key] = add(style[key])
                break
        else:
            return text
    elif isinstance(style, str):
        document["style_description"] = add(style)
    else:
        for key in _JSON_WORD_FIELDS:
            if isinstance(document.get(key), str):
                document[key] = add(document[key])
                break
        else:
            # A JSON prompt with no text field: leave it alone rather than
            # hang tokens off the outside of the document.
            return text
    return json.dumps(document, ensure_ascii=False, indent=2 if "\n" in stripped else None)


def _apply_prompt_params(
    record: dict[str, Any], basic_values: dict[str, Any], advanced_values: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Midjourney-style ``--ar 16:9 --no text --seed 1 --steps 8`` at the end of
    the prompt (NomadStudio#27, app/services/prompt_params.py). Every path that
    builds a graph goes through here, so they work wherever the prompt was
    typed. The parameters never reach the engine as text — unusable ones are
    dropped too (the UI shows why). Engine/speed/quantization/--r are the
    caller's business (selectors, the MCP), not the graph's."""
    positive = str(basic_values.get("positive", "") or "")
    params = parse_prompt_params(positive)
    if not params.found:
        return basic_values, advanced_values
    basic = dict(basic_values)
    advanced = dict(advanced_values) if isinstance(advanced_values, dict) else {}
    basic["positive"] = basic["prompt"] = params.prompt
    if params.aspect:
        try:
            area = int(basic.get("width") or 0) * int(basic.get("height") or 0)
        except (TypeError, ValueError):
            area = 0
        # Multiples of 16, like Create's own sizes (HD 16:9 = 1536x864).
        basic["width"], basic["height"] = size_for_aspect(params.aspect, area or 1024 * 1024, multiple=16)
    if params.no:
        base = str(basic.get("negative", "") or "").strip().rstrip(",").strip()
        basic["negative"] = basic["negative_prompt"] = ", ".join(p for p in (base, params.no) if p)
    if params.seed is not None:
        basic["seed"] = params.seed
    if params.steps is not None:
        sampler_id = str(((record.get("analysis") or {}).get("detected") or {}).get("samplerNodeId") or "").strip()
        if sampler_id:
            advanced[f"{sampler_id}.steps"] = params.steps
    return basic, advanced


def _apply_basic_values_to_workflow(
    record: dict[str, Any],
    basic_values: dict[str, Any],
    advanced_values: dict[str, Any],
    num_images: int = 1,
    disabled_subgraphs: list[Any] | None = None,
) -> dict[str, Any]:
    workflow = deepcopy(record.get("workflow", {}))
    workflow.pop("config", None)
    basic_values = _normalize_basic_values_aliases(basic_values)
    basic_values, advanced_values = _apply_prompt_params(record, basic_values, advanced_values)
    _validate_clip_last_layer_advanced_values(
        workflow, advanced_values if isinstance(advanced_values, dict) else {}
    )
    _apply_clip_last_layer_bypass(
        workflow, advanced_values if isinstance(advanced_values, dict) else {}
    )
    analysis = record.get("analysis", {})
    detected = analysis.get("detected", {})

    def _coerce_int(value: Any, fallback: int = 0) -> int:
        if isinstance(value, bool):
            return fallback
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return fallback
            if re.fullmatch(r"[+-]?\d+", text):
                try:
                    return int(text)
                except Exception:
                    return fallback
            try:
                return int(float(text))
            except Exception:
                return fallback
        return fallback

    def _set_numeric_input(node_id: str, input_key: str, value: int) -> None:
        if node_id not in workflow:
            return
        node_inputs = workflow[node_id].setdefault("inputs", {})
        current = node_inputs.get(input_key)
        if _is_link(current):
            target_node_id = str(current[0])
            target_node = workflow.get(target_node_id, {})
            if isinstance(target_node, dict):
                target_inputs = target_node.setdefault("inputs", {})
                for key in ("value", input_key):
                    if key in target_inputs and isinstance(
                        target_inputs.get(key), (int, float)
                    ):
                        target_inputs[key] = int(value)
                        return
            # The input is a dynamic link (e.g. GetImageSize output) — do not
            # overwrite it with a scalar; the link provides the correct value.
            return
        node_inputs[input_key] = int(value)

    sampler_id = detected.get("samplerNodeId")
    guider_id = detected.get("guiderNodeId")
    noise_id = detected.get("noiseNodeId")
    latent_id = detected.get("latentNodeId")
    positive_node_id = detected.get("positiveNodeId")
    negative_node_id = detected.get("negativeNodeId")

    # Runtime fallback for legacy imports and heterogeneous workflow graphs where
    # analysis may miss prompt ids (e.g. empty text nodes or custom guider chains).
    def _infer_prompt_node_ids() -> tuple[str | None, str | None]:
        inferred_positive = str(positive_node_id) if positive_node_id else None
        inferred_negative = str(negative_node_id) if negative_node_id else None

        def _scan_anchor(node_id: str) -> None:
            nonlocal inferred_positive, inferred_negative
            node = workflow.get(str(node_id), {}) if isinstance(workflow, dict) else {}
            inputs = (
                node.get("inputs", {})
                if isinstance(node, dict) and isinstance(node.get("inputs", {}), dict)
                else {}
            )
            if not inferred_positive:
                for key in ("positive", "conditioning", "prompt", "text"):
                    value = inputs.get(key)
                    if _is_link(value):
                        inferred_positive = str(value[0])
                        break
            if not inferred_negative:
                for key in (
                    "negative",
                    "negative_prompt",
                    "negative_conditioning",
                    "uncond",
                ):
                    value = inputs.get(key)
                    if _is_link(value):
                        inferred_negative = str(value[0])
                        break

        for anchor in (sampler_id, guider_id):
            if (
                anchor
                and str(anchor) in workflow
                and (not inferred_positive or not inferred_negative)
            ):
                _scan_anchor(str(anchor))

        if not inferred_positive or not inferred_negative:
            for node in workflow.values():
                if not isinstance(node, dict):
                    continue
                inputs = (
                    node.get("inputs", {})
                    if isinstance(node.get("inputs", {}), dict)
                    else {}
                )
                if not inferred_positive:
                    for key in ("positive", "conditioning", "prompt"):
                        value = inputs.get(key)
                        if _is_link(value):
                            inferred_positive = str(value[0])
                            break
                if not inferred_negative:
                    for key in (
                        "negative",
                        "negative_prompt",
                        "negative_conditioning",
                        "uncond",
                    ):
                        value = inputs.get(key)
                        if _is_link(value):
                            inferred_negative = str(value[0])
                            break
                if inferred_positive and inferred_negative:
                    break

        if not inferred_positive or not inferred_negative:
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                class_type = str(node.get("class_type", ""))
                if "TextEncode" not in class_type:
                    continue
                meta = (
                    node.get("_meta", {})
                    if isinstance(node.get("_meta", {}), dict)
                    else {}
                )
                title = str(meta.get("title", "")).strip().lower()
                if not inferred_positive and "positive" in title:
                    inferred_positive = str(node_id)
                if not inferred_negative and "negative" in title:
                    inferred_negative = str(node_id)
                if inferred_positive and inferred_negative:
                    break

        return inferred_positive, inferred_negative

    positive_node_id, negative_node_id = _infer_prompt_node_ids()

    # Backward compatibility for imports saved before custom-sampler detection was added.
    if not noise_id:
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            if str(node.get("class_type", "")) != "SamplerCustomAdvanced":
                continue
            inputs = (
                node.get("inputs", {})
                if isinstance(node.get("inputs", {}), dict)
                else {}
            )
            noise_link = inputs.get("noise")
            if _is_link(noise_link):
                noise_id = str(noise_link[0])
                break

    if not noise_id:
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            if str(node.get("class_type", "")) == "RandomNoise":
                noise_id = str(node_id)
                break

    if sampler_id and sampler_id in workflow and not noise_id:
        if "seed" in basic_values:
            sampler_inputs = workflow[str(sampler_id)].setdefault("inputs", {})
            if isinstance(sampler_inputs, dict):
                seed_key = "seed"
                if "seed" not in sampler_inputs and "noise_seed" in sampler_inputs:
                    seed_key = "noise_seed"
                elif "seed" not in sampler_inputs and "random_seed" in sampler_inputs:
                    seed_key = "random_seed"
                _set_numeric_input(
                    str(sampler_id), seed_key, _coerce_int(basic_values.get("seed"), 0)
                )

    if noise_id and noise_id in workflow and "seed" in basic_values:
        noise_inputs = workflow[noise_id].setdefault("inputs", {})
        if "noise_seed" in noise_inputs:
            _set_numeric_input(
                str(noise_id), "noise_seed", _coerce_int(basic_values.get("seed"), 0)
            )
        elif "seed" in noise_inputs:
            _set_numeric_input(
                str(noise_id), "seed", _coerce_int(basic_values.get("seed"), 0)
            )
        else:
            noise_inputs["noise_seed"] = _coerce_int(basic_values.get("seed"), 0)

    if latent_id and latent_id in workflow:
        if "width" in basic_values:
            _set_numeric_input(
                str(latent_id), "width", _coerce_int(basic_values.get("width"), 512)
            )
        if "height" in basic_values:
            _set_numeric_input(
                str(latent_id), "height", _coerce_int(basic_values.get("height"), 512)
            )
        latent_inputs = workflow[latent_id].setdefault("inputs", {})
        if "batch_size" in latent_inputs:
            latent_inputs["batch_size"] = int(max(1, min(num_images, 8)))

    # Ideogram4Scheduler carries its own width/height, independent from the
    # latent node's — it drives the MRoPE positional grounding that bbox
    # layout ("compositional_deconstruction.elements[].bbox") is anchored to.
    # If it's left at its imported default (usually 1024x1024) while the
    # actual canvas is a different aspect ratio, the model grounds bbox
    # coordinates against the wrong (square) reference frame and lettering/
    # element placement drifts — squeezed toward one corner with the
    # remainder of the canvas improvised. Keep it in lockstep with whatever
    # width/height end up on the latent node, for every Ideogram4 workflow,
    # not just ones that happen to alias this node as "sigmas".
    if "width" in basic_values or "height" in basic_values:
        target_w = _coerce_int(basic_values.get("width"), 512)
        target_h = _coerce_int(basic_values.get("height"), 512)
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            if node.get("class_type") != "Ideogram4Scheduler":
                continue
            node_inputs = node.get("inputs", {})
            if not isinstance(node_inputs, dict):
                continue
            if "width" in node_inputs:
                _set_numeric_input(str(node_id), "width", target_w)
            if "height" in node_inputs:
                _set_numeric_input(str(node_id), "height", target_h)

    if sampler_id and sampler_id in workflow and not latent_id:
        sampler_inputs = workflow[str(sampler_id)].setdefault("inputs", {})
        if isinstance(sampler_inputs, dict):
            if "width" in basic_values and "width" in sampler_inputs:
                _set_numeric_input(
                    str(sampler_id),
                    "width",
                    _coerce_int(basic_values.get("width"), 512),
                )
            if "height" in basic_values and "height" in sampler_inputs:
                _set_numeric_input(
                    str(sampler_id),
                    "height",
                    _coerce_int(basic_values.get("height"), 512),
                )

    _applied_positive_node_id: str | None = None
    _applied_positive_text_key: str | None = None
    _applied_negative_node_id: str | None = None
    _applied_negative_text_key: str | None = None

    if positive_node_id:
        node_id, text_key = _find_text_target_node(
            workflow, str(positive_node_id), target="positive"
        )
        if node_id and text_key and node_id in workflow and "positive" in basic_values:
            workflow[node_id].setdefault("inputs", {})[text_key] = (
                _prefix_lora_trigger_words(
                    record,
                    workflow,
                    advanced_values if isinstance(advanced_values, dict) else {},
                    basic_values.get("loraKeywordsOff"),
                    str(basic_values["positive"]),
                )
            )
            _applied_positive_node_id = node_id
            _applied_positive_text_key = text_key

    if negative_node_id and str(basic_values.get("negative", "")).strip():
        node_id, text_key = _find_text_target_node(
            workflow, str(negative_node_id), target="negative"
        )
        if node_id and text_key and node_id in workflow:
            workflow[node_id].setdefault("inputs", {})[text_key] = str(
                basic_values["negative"]
            )
            _applied_negative_node_id = node_id
            _applied_negative_text_key = text_key

    # Nodes and input keys that are already controlled by basicValues — advanced overrides
    # must not clobber them, otherwise the last write wins against the explicit seed logic.
    _seed_controlled: set[tuple[str, str]] = set()
    # Protect injected prompt fields from being overwritten by stored advancedValues.
    if _applied_positive_node_id and _applied_positive_text_key:
        _seed_controlled.add((_applied_positive_node_id, _applied_positive_text_key))
    if _applied_negative_node_id and _applied_negative_text_key:
        _seed_controlled.add((_applied_negative_node_id, _applied_negative_text_key))
    if noise_id:
        _seed_controlled.add((str(noise_id), "noise_seed"))
        _seed_controlled.add((str(noise_id), "seed"))
    if sampler_id:
        _seed_controlled.add((str(sampler_id), "seed"))
        _seed_controlled.add((str(sampler_id), "noise_seed"))
        _seed_controlled.add((str(sampler_id), "random_seed"))
        _seed_controlled.add((str(sampler_id), "width"))
        _seed_controlled.add((str(sampler_id), "height"))
    if latent_id:
        _seed_controlled.add((str(latent_id), "width"))
        _seed_controlled.add((str(latent_id), "height"))

    _ensure_lora_loader_node(
        workflow, advanced_values if isinstance(advanced_values, dict) else {}
    )
    _apply_lora_chain_to_workflow(
        workflow,
        advanced_values if isinstance(advanced_values, dict) else {},
        max_items=4,
    )

    for composite_key, value in advanced_values.items():
        if "." not in composite_key:
            continue
        node_id, input_key = composite_key.split(".", 1)
        if input_key.startswith("__"):
            continue
        if (node_id, input_key) in _seed_controlled:
            continue
        if node_id in workflow:
            node_inputs = workflow[node_id].setdefault("inputs", {})
            current_value = node_inputs.get(input_key)

            # LoRA bypass: when lora_name is set to the sentinel value, rewire
            # every consumer of this node's outputs directly to whatever fed
            # this node's own model/clip inputs, then drop the node entirely.
            # A zero-strength LoRA node still loads its file and runs — this
            # is a real ComfyUI-graph bypass instead (issue #5).
            if input_key == "lora_name" and str(value) == "__bypass__":
                for out_idx, source_key in enumerate(("model", "clip")):
                    source = node_inputs.get(source_key)
                    if _is_link(source):
                        _replace_links_from_node_output(
                            workflow, node_id, out_idx, list(source)
                        )
                workflow.pop(node_id, None)
                continue

            # Never replace graph links with serialized text placeholders like "[25, 0]".
            if _is_link(current_value) and isinstance(value, str):
                text = value.strip()
                if re.fullmatch(r"\[\s*\d+\s*,\s*\d+\s*\]", text):
                    continue

            node_inputs[input_key] = value

    # Fallback: if workflow has generic batch_size inputs outside latent node.
    bounded_num_images = int(max(1, min(num_images, 8)))
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        if "batch_size" in inputs and isinstance(inputs.get("batch_size"), int):
            inputs["batch_size"] = bounded_num_images

    if disabled_subgraphs:
        workflow = apply_disabled_subgraphs(
            workflow, analysis.get("optionalSubgraphs", []), [str(x) for x in disabled_subgraphs]
        )

    return workflow


# ---------------------------------------------------------------------------
# Output image selection
# ---------------------------------------------------------------------------


def _select_output_images(
    history_payload: dict[str, Any], prompt_id: str, preferred_node_ids: list[str]
) -> tuple[str | None, list[dict[str, Any]]]:
    run = history_payload.get(prompt_id, {})
    outputs = run.get("outputs", {}) if isinstance(run.get("outputs", {}), dict) else {}

    for node_id in preferred_node_ids:
        node_output = outputs.get(node_id, {})
        images = node_output.get("images", []) if isinstance(node_output, dict) else []
        if images:
            return node_id, images

    for node_id, node_output in outputs.items():
        if not isinstance(node_output, dict):
            continue
        images = node_output.get("images", [])
        if images:
            return str(node_id), images

    return None, []



# ---------------------------------------------------------------------------
# Applied seed extraction / ComfyUI poll timeouts
# ---------------------------------------------------------------------------


def _extract_applied_seeds(
    record: dict[str, Any], prepared_workflow: dict[str, Any]
) -> tuple[str, Any, Any]:
    """Return (applied_noise_node_id, applied_noise_seed, applied_sampler_seed)."""
    applied_noise_node_id = str(
        record.get("analysis", {}).get("detected", {}).get("noiseNodeId") or ""
    ).strip()
    if not applied_noise_node_id:
        for node_id, node in prepared_workflow.items():
            if (
                isinstance(node, dict)
                and str(node.get("class_type", "")) == "RandomNoise"
            ):
                applied_noise_node_id = str(node_id)
                break

    applied_noise_seed = None
    if applied_noise_node_id and applied_noise_node_id in prepared_workflow:
        node_inputs = prepared_workflow.get(applied_noise_node_id, {}).get("inputs", {})
        if isinstance(node_inputs, dict):
            applied_noise_seed = node_inputs.get("noise_seed", node_inputs.get("seed"))

    applied_sampler_seed = None
    applied_sampler_id = str(
        record.get("analysis", {}).get("detected", {}).get("samplerNodeId") or ""
    ).strip()
    if applied_sampler_id and applied_sampler_id in prepared_workflow:
        node_inputs = prepared_workflow.get(applied_sampler_id, {}).get("inputs", {})
        if isinstance(node_inputs, dict) and "seed" in node_inputs:
            applied_sampler_seed = node_inputs.get("seed")

    return applied_noise_node_id, applied_noise_seed, applied_sampler_seed


def _compute_comfy_poll_timeouts(
    width: int, height: int, num_images: int
) -> tuple[int, int]:
    """Return (history_timeout_secs, view_timeout_secs) tuned by output size/count."""
    safe_w = max(64, int(width or 512))
    safe_h = max(64, int(height or 512))
    safe_n = max(1, min(int(num_images or 1), 8))
    mega_pixels = (safe_w * safe_h) / 1_000_000.0

    history_timeout = int(
        max(15, min(180, 20 + (mega_pixels * 8) + ((safe_n - 1) * 6)))
    )
    view_timeout = int(max(30, min(240, 40 + (mega_pixels * 10) + ((safe_n - 1) * 8))))
    return history_timeout, view_timeout
