"""workflow_clip — CLIPSetLastLayer advanced input helpers."""
from __future__ import annotations

from typing import Any

from app.services.workflow_utils import (
    CLIP_LAST_LAYER_ALLOWED_VALUES,
    CLIP_LAST_LAYER_INPUT_KEYS,
    _coerce_int_scalar,
    _is_link,
)

# ---------------------------------------------------------------------------
# Advanced input metadata / CLIP Last Layer
# ---------------------------------------------------------------------------


def _advanced_input_metadata(class_type: str, input_key: str) -> dict[str, Any]:
    class_name = str(class_type or "").strip()
    key = str(input_key or "").strip().lower()

    if class_name in {"LoraLoader", "LoraLoaderModelOnly"} or (
        key == "lora_name" and "lora" in class_name.lower()
    ):
        if key == "lora_name":
            return {
                "controlType": "select",
                "valueType": "string",
                "optionsSource": "lora",
            }
        if key in {"strength_model", "strength_clip"}:
            return {
                "controlType": "number",
                "valueType": "float",
            }

    if class_name == "CLIPSetLastLayer" and key in CLIP_LAST_LAYER_INPUT_KEYS:
        return {
            "controlType": "number",
            "valueType": "integer",
            "allowedValues": sorted(CLIP_LAST_LAYER_ALLOWED_VALUES),
            "blockedValues": [],
            "disabledValue": 0,
            "validationMessage": "Allowed values: 0 (bypass), -2, -3.",
        }

    return {}


def _extract_clip_last_layer_keys(workflow: dict[str, Any]) -> list[str]:
    if not isinstance(workflow, dict):
        return []

    keys: list[str] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type", "")) != "CLIPSetLastLayer":
            continue
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        for input_key in CLIP_LAST_LAYER_INPUT_KEYS:
            if input_key in inputs:
                keys.append(f"{node_id}.{input_key}")
    return keys


def _validate_clip_last_layer_advanced_values(
    workflow: dict[str, Any], advanced_values: dict[str, Any]
) -> None:
    if not isinstance(advanced_values, dict):
        return

    clip_keys = set(_extract_clip_last_layer_keys(workflow))
    if not clip_keys:
        return

    for key, raw_value in advanced_values.items():
        if key not in clip_keys:
            continue
        value = _coerce_int_scalar(raw_value)
        if value is None:
            raise ValueError(f"{key}: CLIP Last Layer must be an integer")
        if value not in CLIP_LAST_LAYER_ALLOWED_VALUES:
            raise ValueError(f"{key}: allowed values are 0, -2, -3")


def _normalize_clip_last_layer_advanced_values(
    workflow: dict[str, Any], advanced_values: dict[str, Any]
) -> dict[str, Any]:
    """Normalize legacy CLIPSetLastLayer values (-1 -> 0 for bypass)."""
    if not isinstance(advanced_values, dict):
        return {}

    normalized = dict(advanced_values)
    clip_keys = set(_extract_clip_last_layer_keys(workflow))
    if not clip_keys:
        return normalized

    for key in clip_keys:
        if key not in normalized:
            continue
        value = _coerce_int_scalar(normalized.get(key))
        if value == -1:
            normalized[key] = 0

    return normalized


def _prune_stale_clip_last_layer_overrides(
    workflow: dict[str, Any],
    merged_advanced_values: dict[str, Any],
    input_advanced_values: dict[str, Any],
) -> dict[str, Any]:
    """Keep CLIPSetLastLayer overrides only when explicitly sent by current payload."""
    if not isinstance(merged_advanced_values, dict):
        return {}
    if not isinstance(input_advanced_values, dict):
        input_advanced_values = {}

    clip_keys = set(_extract_clip_last_layer_keys(workflow))
    if not clip_keys:
        return dict(merged_advanced_values)

    explicit_input_keys = {
        str(key) for key in input_advanced_values.keys() if isinstance(key, str)
    }
    pruned = dict(merged_advanced_values)
    for key in clip_keys:
        if key in pruned and key not in explicit_input_keys:
            pruned.pop(key, None)
    return pruned


def _apply_clip_last_layer_bypass(
    workflow: dict[str, Any], advanced_values: dict[str, Any]
) -> None:
    """Rewire CLIPSetLastLayer outputs to upstream clip source when value is 0."""
    if not isinstance(workflow, dict) or not isinstance(advanced_values, dict):
        return

    bypass_node_ids: set[str] = set()
    for composite_key, raw_value in advanced_values.items():
        if not isinstance(composite_key, str) or "." not in composite_key:
            continue
        node_id, input_key = composite_key.split(".", 1)
        if input_key not in CLIP_LAST_LAYER_INPUT_KEYS:
            continue
        node = (
            workflow.get(node_id, {}) if isinstance(workflow.get(node_id), dict) else {}
        )
        if str(node.get("class_type", "")) != "CLIPSetLastLayer":
            continue
        parsed = _coerce_int_scalar(raw_value)
        if parsed == 0:
            bypass_node_ids.add(str(node_id))

    if not bypass_node_ids:
        return

    for bypass_node_id in bypass_node_ids:
        bypass_node = (
            workflow.get(bypass_node_id, {})
            if isinstance(workflow.get(bypass_node_id), dict)
            else {}
        )
        bypass_inputs = (
            bypass_node.get("inputs", {})
            if isinstance(bypass_node.get("inputs", {}), dict)
            else {}
        )
        upstream_clip = bypass_inputs.get("clip")
        if not _is_link(upstream_clip):
            continue

        upstream_link = [
            str(upstream_clip[0]),
            int(upstream_clip[1]) if len(upstream_clip) > 1 else 0,
        ]

        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            node_inputs = (
                node.get("inputs", {})
                if isinstance(node.get("inputs", {}), dict)
                else {}
            )
            for input_key, input_value in list(node_inputs.items()):
                if _is_link(input_value) and str(input_value[0]) == bypass_node_id:
                    node_inputs[input_key] = [upstream_link[0], upstream_link[1]]
