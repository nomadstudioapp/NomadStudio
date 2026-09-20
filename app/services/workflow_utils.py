"""workflow_utils — primitive helpers shared across all workflow modules.

Importing from here instead of workflow_service avoids circular deps.
workflow_service re-exports everything for backward compatibility.
"""
from __future__ import annotations

import re
from typing import Any, TypeGuard

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLIP_LAST_LAYER_ALLOWED_VALUES = {0, -2, -3}
CLIP_LAST_LAYER_INPUT_KEYS = {"stop_at_clip_layer", "layer"}

# ---------------------------------------------------------------------------
# Basic link / scalar helpers
# ---------------------------------------------------------------------------


def _is_link(value: Any) -> TypeGuard[list[Any]]:
    return isinstance(value, list) and len(value) >= 1 and isinstance(value[0], str)


def _as_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)):
        return value
    return None


def _is_prompt_like_key(input_key: str) -> bool:
    key = str(input_key or "").strip().lower()
    if not key:
        return False
    return key in {"prompt", "positive", "text", "string", "value"} or "prompt" in key


def _is_negative_like_key(input_key: str) -> bool:
    key = str(input_key or "").strip().lower()
    if not key:
        return False
    return (
        key
        in {
            "negative",
            "negative_prompt",
            "neg_prompt",
            "uncond",
            "negative_conditioning",
        }
        or "negative" in key
    )


def _is_sampler_like_node(class_type: str, inputs: dict[str, Any]) -> bool:
    class_name = str(class_type or "").strip().lower()
    if class_name == "ksampler":
        return True

    if not isinstance(inputs, dict):
        return False

    keys = {str(key).strip().lower() for key in inputs.keys()}
    has_seed = any(key in keys for key in {"seed", "noise_seed", "random_seed"})
    has_steps = "steps" in keys
    has_guidance = any(key in keys for key in {"cfg", "guidance", "guidance_scale"})
    has_dims = "width" in keys and "height" in keys
    has_conditioning = any(
        key in keys
        for key in {"positive", "negative", "conditioning", "prompt", "text"}
    )

    if has_seed and has_steps and (has_guidance or has_dims):
        return True

    if "sampler" in class_name and (has_seed or has_steps or has_dims):
        return True

    return has_seed and has_dims and has_conditioning


def _extract_seed_from_inputs(inputs: dict[str, Any]) -> int | None:
    if not isinstance(inputs, dict):
        return None
    for key in ("seed", "noise_seed", "random_seed"):
        seed = _coerce_int_scalar(inputs.get(key))
        if isinstance(seed, int):
            return seed
    return None


def _coerce_int_scalar(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if re.fullmatch(r"[+-]?\d+", text):
            try:
                return int(text)
            except Exception:
                return None
        try:
            return int(float(text))
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Node inspection helpers (pure — no analysis deps)
# ---------------------------------------------------------------------------


def _workflow_load_image_nodes(workflow: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if not isinstance(workflow, dict):
        return out
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        if class_type not in {"LoadImage", "LoadImageMask"}:
            continue
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        if "image" in inputs:
            out.append(str(node_id))
    return out


def _extract_checkpoint_loader_keys(workflow: dict[str, Any]) -> list[str]:
    if not isinstance(workflow, dict):
        return []

    supported_classes = {"CheckpointLoaderSimple", "CheckpointLoader"}
    keys: list[str] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        if class_type not in supported_classes:
            continue
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        if "ckpt_name" in inputs:
            keys.append(f"{node_id}.ckpt_name")
    return keys


def _extract_unet_loader_keys(workflow: dict[str, Any]) -> list[str]:
    if not isinstance(workflow, dict):
        return []

    keys: list[str] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type", "")) != "UNETLoader":
            continue
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        if "unet_name" in inputs:
            keys.append(f"{node_id}.unet_name")
    return keys


def _extract_clip_loader_keys(workflow: dict[str, Any]) -> list[str]:
    if not isinstance(workflow, dict):
        return []

    keys: list[str] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type", "")) != "CLIPLoader":
            continue
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        if "clip_name" in inputs:
            keys.append(f"{node_id}.clip_name")
    return keys


def _extract_lora_loader_keys(workflow: dict[str, Any]) -> list[str]:
    if not isinstance(workflow, dict):
        return []

    supported_classes = {"LoraLoader", "LoraLoaderModelOnly"}

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

    keys: list[str] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        if not _is_lora_loader_node(node):
            continue
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        if "lora_name" in inputs:
            keys.append(f"{node_id}.lora_name")
    return keys


def _extract_checkpoint_options_from_object_info(
    object_info: dict[str, Any],
) -> list[str]:
    if not isinstance(object_info, dict):
        return []

    supported_classes = ("CheckpointLoaderSimple", "CheckpointLoader")
    options: list[str] = []
    for class_name in supported_classes:
        class_info = object_info.get(class_name, {})
        if not isinstance(class_info, dict):
            continue
        input_info = (
            class_info.get("input", {})
            if isinstance(class_info.get("input", {}), dict)
            else {}
        )
        required = (
            input_info.get("required", {})
            if isinstance(input_info.get("required", {}), dict)
            else {}
        )
        ckpt_spec = required.get("ckpt_name")
        if not isinstance(ckpt_spec, list) or not ckpt_spec:
            continue
        candidates = ckpt_spec[0]
        if not isinstance(candidates, list):
            continue
        for item in candidates:
            name = str(item).strip()
            if name:
                options.append(name)

    seen: set[str] = set()
    deduped: list[str] = []
    for name in options:
        if name in seen:
            continue
        seen.add(name)
        deduped.append(name)
    return deduped


def _extract_unet_options_from_object_info(
    object_info: dict[str, Any],
) -> list[str]:
    if not isinstance(object_info, dict):
        return []

    class_info = object_info.get("UNETLoader", {})
    if not isinstance(class_info, dict):
        return []
    input_info = (
        class_info.get("input", {})
        if isinstance(class_info.get("input", {}), dict)
        else {}
    )
    required = (
        input_info.get("required", {})
        if isinstance(input_info.get("required", {}), dict)
        else {}
    )
    unet_spec = required.get("unet_name")
    if not isinstance(unet_spec, list) or not unet_spec:
        return []
    candidates = unet_spec[0]
    if not isinstance(candidates, list):
        return []

    seen: set[str] = set()
    options: list[str] = []
    for item in candidates:
        name = str(item).strip()
        if name and name not in seen:
            seen.add(name)
            options.append(name)
    return options


def _extract_lora_options_from_object_info(object_info: dict[str, Any]) -> list[str]:
    if not isinstance(object_info, dict):
        return []

    options: list[str] = []
    seen: set[str] = set()

    for class_name in ("LoraLoader", "LoraLoaderModelOnly"):
        class_info = object_info.get(class_name, {})
        if not isinstance(class_info, dict):
            continue
        input_info = (
            class_info.get("input", {})
            if isinstance(class_info.get("input", {}), dict)
            else {}
        )
        required = (
            input_info.get("required", {})
            if isinstance(input_info.get("required", {}), dict)
            else {}
        )
        lora_spec = required.get("lora_name")
        if not isinstance(lora_spec, list) or not lora_spec:
            continue
        candidates = lora_spec[0]
        if not isinstance(candidates, list):
            continue

        for item in candidates:
            name = str(item).strip()
            if not name or name in seen:
                continue
            options.append(name)
            seen.add(name)

    if not options:
        for class_info in object_info.values():
            if not isinstance(class_info, dict):
                continue
            input_info = (
                class_info.get("input", {})
                if isinstance(class_info.get("input", {}), dict)
                else {}
            )
            required = (
                input_info.get("required", {})
                if isinstance(input_info.get("required", {}), dict)
                else {}
            )
            lora_spec = required.get("lora_name")
            if not isinstance(lora_spec, list) or not lora_spec:
                continue
            candidates = lora_spec[0]
            if not isinstance(candidates, list):
                continue
            for item in candidates:
                name = str(item).strip()
                if not name or name in seen:
                    continue
                options.append(name)
                seen.add(name)

    return options
