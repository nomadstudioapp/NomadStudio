"""workflow_quality — quality preset extraction from PrimitiveStringMultiline nodes."""
from __future__ import annotations

import re
from typing import Any

from app.services.workflow_utils import (
    _as_scalar,
    _extract_clip_loader_keys,
    _extract_unet_loader_keys,
)

# ---------------------------------------------------------------------------
# Quality helpers
# ---------------------------------------------------------------------------

_QUANTIZATION_LABELS = {"int4": "INT4", "int8": "INT8", "fp8": "FP8"}
_QUANTIZATION_ORDER = ["int4", "int8", "fp8"]


def _quantization_entry_to_option(level_key: str, label: str, raw: Any) -> dict[str, str] | None:
    """Normalize one ``quantization`` map entry into an option dict.

    Accepts either the legacy plain-string form (``"fp8": "file.safetensors"``,
    unet-only) or the paired form (``"fp8": {"unet_name": ..., "clip_name": ...,
    "unet_unconditional_name": ...}``) that lets a quantization level swap its
    diffusion model *and* its matching text encoder together (one text encoder
    per precision level, e.g. a 4B model using a 4B encoder vs a 9B model using
    an 8B encoder), *and/or* a second diffusion model — some workflows (e.g.
    Ideogram 4's dual-branch CFG) load a normal and an "unconditional" UNETLoader
    that both need to move to the same precision at once."""
    if isinstance(raw, dict):
        unet_name = str(raw.get("unet_name", "") or "").strip()
        if not unet_name:
            return None
        custom_label = str(raw.get("label", "") or "").strip()
        option = {"id": level_key, "label": custom_label or label, "unet_name": unet_name}
        clip_name = str(raw.get("clip_name", "") or "").strip()
        if clip_name:
            option["clip_name"] = clip_name
        unet_unconditional_name = str(raw.get("unet_unconditional_name", "") or "").strip()
        if unet_unconditional_name:
            option["unet_unconditional_name"] = unet_unconditional_name
        return option

    filename = str(raw or "").strip()
    if not filename:
        return None
    return {"id": level_key, "label": label, "unet_name": filename}


def _quantization_map_to_options(quant_raw: Any) -> list[dict[str, str]]:
    """Every level of one ``quantization`` map as options, standard levels
    (INT4/INT8/FP8) first."""
    if not isinstance(quant_raw, dict):
        return []
    options: list[dict[str, str]] = []
    for level in _QUANTIZATION_ORDER:
        option = _quantization_entry_to_option(level, _QUANTIZATION_LABELS[level], quant_raw.get(level))
        if option:
            options.append(option)
    # Preserve any additional, non-standard levels the config might define.
    for level, raw in quant_raw.items():
        level_key = str(level).strip().lower()
        if level_key in _QUANTIZATION_ORDER:
            continue
        option = _quantization_entry_to_option(level_key, level_key.upper(), raw)
        if option:
            options.append(option)
    return options


def _extract_quantization_options(
    workflow: dict[str, Any],
    config_data: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Read a ``quantization: {int4/int8/fp8: <unet_name>}`` block from the
    workflow's ``config`` node and pair it with the workflow's UNETLoader
    node, so the frontend can offer an INT4/INT8/FP8 diffusion-model picker.

    Each level may instead map to ``{"unet_name": ..., "clip_name": ...,
    "unet_unconditional_name": ...}`` when that precision needs its own
    matching text encoder (e.g. a 4B model using a 4B text encoder vs a 9B
    model using an 8B text encoder) and/or a second UNETLoader that must move
    to the same precision together (e.g. Ideogram 4's normal + unconditional
    dual-branch CFG) — in that case the returned dict also carries
    ``clipTargetKey`` / ``unconditionalTargetKey`` so the frontend swaps all
    the relevant loaders together.

    An optional ``variations: {id: {label, steps, quantization}}`` block adds
    alternative checkpoints of the same graph (e.g. Qwen Image 2.1 Turbo):
    the result then carries ``variations`` — an implicit "normal" one with the
    top-level options and the sampler's own steps, then each declared one with
    its own options and steps — plus ``stepsTargetKey``. The frontend shows
    them as a Variation picker that decides what Quantization lists.

    Returns ``None`` when the workflow has no quantization config or no
    UNETLoader node — existing workflows are unaffected."""
    if not isinstance(config_data, dict):
        return None
    quant_raw = config_data.get("quantization")
    if not isinstance(quant_raw, dict) or not quant_raw:
        return None

    unet_keys = _extract_unet_loader_keys(workflow)
    if not unet_keys:
        return None

    def _current_unet_name(key: str) -> str:
        node_id = key.split(".", 1)[0]
        node = workflow.get(node_id) if isinstance(workflow, dict) else None
        inputs = node.get("inputs") if isinstance(node, dict) and isinstance(node.get("inputs"), dict) else {}
        return str(inputs.get("unet_name", "") or "")

    # A second UNETLoader whose current filename reads as the "unconditional"
    # branch (Ideogram 4's dual-branch CFG) is treated as the pair to swap
    # alongside the main one, not a second independent target.
    unconditional_key = next(
        (k for k in unet_keys if "unconditional" in _current_unet_name(k).lower()), None
    )
    target_key = next((k for k in unet_keys if k != unconditional_key), unet_keys[0])

    options = _quantization_map_to_options(quant_raw)
    if not options:
        return None

    result: dict[str, Any] = {"targetKey": target_key, "options": options}
    variations = _extract_variations(workflow, config_data, options)
    every_option = options + [opt for v in variations for opt in v["options"]]
    if any("clip_name" in opt for opt in every_option):
        clip_keys = _extract_clip_loader_keys(workflow)
        if clip_keys:
            result["clipTargetKey"] = clip_keys[0]
    if unconditional_key and any("unet_unconditional_name" in opt for opt in every_option):
        result["unconditionalTargetKey"] = unconditional_key
    if variations:
        result["variations"] = variations
        steps_key = _sampler_steps_key(workflow)
        if steps_key:
            result["stepsTargetKey"] = steps_key
    return result


def _extract_variations(
    workflow: dict[str, Any],
    config_data: dict[str, Any],
    normal_options: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """``config.variations`` as a list, the implicit "normal" first. Empty
    when the config declares no usable variation."""
    raw_variations = config_data.get("variations")
    if not isinstance(raw_variations, dict):
        return []
    declared: list[dict[str, Any]] = []
    for var_id, raw in raw_variations.items():
        if not isinstance(raw, dict):
            continue
        var_options = _quantization_map_to_options(raw.get("quantization"))
        if not var_options:
            continue
        variation: dict[str, Any] = {
            "id": str(var_id).strip().lower(),
            "label": str(raw.get("label") or var_id).strip(),
            "options": var_options,
        }
        steps = _positive_int(raw.get("steps"))
        if steps:
            variation["steps"] = steps
        declared.append(variation)
    if not declared:
        return []
    normal: dict[str, Any] = {"id": "normal", "label": "Normal", "options": normal_options}
    steps_key = _sampler_steps_key(workflow)
    if steps_key:
        node = workflow.get(steps_key.split(".", 1)[0]) or {}
        steps = _positive_int((node.get("inputs") or {}).get("steps"))
        if steps:
            normal["steps"] = steps
    return [normal] + declared


def _positive_int(value: Any) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _sampler_steps_key(workflow: dict[str, Any]) -> str | None:
    """``"<node id>.steps"`` of the graph's sampler (KSampler, or the
    BasicScheduler of a SamplerCustomAdvanced chain) — where a variation's
    own step count goes."""
    if not isinstance(workflow, dict):
        return None
    for class_types in (("KSampler", "KSamplerAdvanced"), ("BasicScheduler",)):
        for node_id, node in workflow.items():
            if not isinstance(node, dict) or node.get("class_type") not in class_types:
                continue
            inputs = node.get("inputs")
            if isinstance(inputs, dict) and "steps" in inputs:
                return f"{node_id}.steps"
    return None


def _normalize_quality_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9_\-\s]+", "", text)
    text = re.sub(r"[\s\-]+", "_", text).strip("_")
    return text


def _coerce_quality_value(raw: str) -> int | float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if re.fullmatch(r"[-+]?\d+", text):
        try:
            return int(text)
        except Exception:
            return None
    try:
        value = float(text)
    except Exception:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _quality_field_aliases(field_label: str) -> set[str]:
    field_norm = _normalize_quality_token(field_label)
    aliases = {field_norm} if field_norm else set()
    if field_norm in {"cfg", "guidance"}:
        aliases.update({"cfg", "guidance", "guidance_scale"})
    if field_norm == "steps":
        aliases.update({"steps"})
    if field_norm == "denoise":
        aliases.update({"denoise"})
    if "resolution" in field_norm and ("mult" in field_norm or "scale" in field_norm):
        aliases.update({"scale", "scale_by", "resolution_multiplier", "multiplier"})
    return {item for item in aliases if item}


def _extract_quality_blocks_from_text(raw_value: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw_line in str(raw_value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        header_match = re.match(
            r"^#\s*(?:nodo|node)\s+(\d+)\s*-\s*(.+?)\s*$", line, re.IGNORECASE
        )
        if header_match:
            current = {
                "nodeId": str(header_match.group(1)).strip(),
                "field": str(header_match.group(2)).strip(),
                "values": {},
            }
            blocks.append(current)
            continue

        if line.startswith("#"):
            continue
        if current is None or "=" not in line:
            continue

        level_raw, value_raw = line.split("=", 1)
        level = _normalize_quality_token(level_raw)
        if not level:
            continue
        parsed_value = _coerce_quality_value(value_raw)
        if parsed_value is None:
            continue

        values = current.get("values", {})
        if not isinstance(values, dict):
            values = {}
            current["values"] = values
        values[level] = parsed_value

    return [
        block
        for block in blocks
        if isinstance(block.get("values"), dict) and block.get("values")
    ]


def _resolve_quality_target_key(
    workflow: dict[str, Any],
    advanced_parameters: list[dict[str, Any]],
    node_id: str,
    field_label: str,
) -> str | None:
    aliases = _quality_field_aliases(field_label)
    if not aliases:
        return None

    fallback_key: str | None = None
    for param in advanced_parameters:
        if str(param.get("nodeId", "")).strip() != node_id:
            continue
        key = str(param.get("key", "")).strip()
        if not key:
            continue
        input_norm = _normalize_quality_token(param.get("inputKey", ""))
        label_norm = _normalize_quality_token(param.get("label", ""))
        if input_norm in aliases or label_norm in aliases:
            return key
        if not fallback_key and (
            any(alias and alias in input_norm for alias in aliases)
            or any(alias and alias in label_norm for alias in aliases)
        ):
            fallback_key = key

    if fallback_key:
        return fallback_key

    node = workflow.get(node_id, {}) if isinstance(workflow, dict) else {}
    inputs = node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
    for input_key, input_value in inputs.items():
        scalar = _as_scalar(input_value)
        if scalar is None:
            continue
        normalized_input_key = _normalize_quality_token(input_key)
        if normalized_input_key in aliases:
            return f"{node_id}.{input_key}"

    return None


def _extract_quality_presets(
    workflow: dict[str, Any],
    advanced_parameters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    quality_text = ""
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type", "")).strip() != "PrimitiveStringMultiline":
            continue
        meta = node.get("_meta", {}) if isinstance(node.get("_meta", {}), dict) else {}
        if str(meta.get("title", "")).strip().lower() != "quality":
            continue
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        quality_text = str(inputs.get("value", "") or "")
        break

    blocks = _extract_quality_blocks_from_text(quality_text)
    if not blocks:
        return []

    values_by_level: dict[str, dict[str, Any]] = {}
    for block in blocks:
        node_id = str(block.get("nodeId", "")).strip()
        field_label = str(block.get("field", "")).strip()
        if not node_id or not field_label:
            continue
        resolved_key = _resolve_quality_target_key(
            workflow, advanced_parameters, node_id, field_label
        )
        if not resolved_key:
            continue

        block_values = (
            block.get("values", {}) if isinstance(block.get("values", {}), dict) else {}
        )
        for level, value in block_values.items():
            level_key = _normalize_quality_token(level)
            if not level_key:
                continue
            by_level_entry = values_by_level.setdefault(level_key, {})
            by_level_entry[resolved_key] = value

    if not values_by_level:
        return []

    ordered_levels = ["draft", "standard", "high", "ultra"]
    extra_levels = sorted(
        [level for level in values_by_level.keys() if level not in ordered_levels]
    )

    quality_presets: list[dict[str, Any]] = []
    for level in ordered_levels + extra_levels:
        level_values = values_by_level.get(level)
        if not level_values:
            continue
        quality_presets.append(
            {
                "id": level,
                "label": level.replace("_", " ").title(),
                "values": level_values,
            }
        )

    return quality_presets
