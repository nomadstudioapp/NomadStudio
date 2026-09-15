from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from flask import jsonify, request

from app.config import (
    DEFAULT_LMSTUDIO_CONTEXT_SIZE,
    DEFAULT_LMSTUDIO_TEMPERATURE,
    DEFAULT_LMSTUDIO_URL,
    LMSTUDIO_CONTEXT_SIZE_MIN,
    LMSTUDIO_MAX_OUTPUT_TOKENS,
)
from app.services import lmstudio_service
from app.services.http_client import http_json
from app.routes.models_api_modules.settings_routes import (
    DEFAULT_CUSTOM_PROMPTS,
    DEFAULT_STUDIO_PROMPTS,
    _STUDIO_FLAIR_INSTRUCTION,
    _STUDIO_ASPECT_INSTRUCTION,
    _STUDIO_REFERENCE_INSTRUCTION,
)
from app.routes.models_api_shared import (
    _append_lmstudio_output_log,
    _apply_max_tokens_override,
    _auto_context_size,
    _clip_text,
    _coerce_context_size,
    _coerce_lmstudio_temperature,
    _describe_cache_get,
    _describe_cache_set,
    _ensure_registry,
    _extract_json_array_from_text,
    _lmstudio_chat_endpoint,
    _lmstudio_load_model,
    _lmstudio_unload_model,
    _normalize_lmstudio_conversation_messages,
    _parse_image_data_url,
    _reasoning_only_error,
    _safe_http_url,
    _save_registry,
    _sanitize_lmstudio_edited_prompt,
    logger,
    models_api_bp,
)

from app.routes.models_api_modules.chat_routes import (
    _extract_json_payload_from_text,
    _extract_lmstudio_message_text,
    _inject_no_think,
    _build_chat_payload,
    _call_studio_llm,
    _resolve_prompt_model,
    _resolve_vision_model,
    _resolve_explicit_vision_model,
)


def _context_texts(payload: dict[str, Any]) -> list[str]:
    """Every string in the request that will travel to the model.

    Feeds _auto_context_size, which replaced the stored "Context" number the
    user used to set by hand — it advertised a speed difference that could not
    be measured across a 32x range and quietly capped how much of the user's
    own text was sent. Reading the payload rather than naming fields per route
    means a route gaining a field cannot silently start under-sizing its window.

    Data URLs are skipped: an inlined image would swamp an estimate meant for
    the text budget.
    """
    texts: list[str] = []
    for value in payload.values():
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, list):
            texts.extend(v for v in value if isinstance(v, str))
    return [t for t in texts if not t.startswith("data:")]

@models_api_bp.post("/models/chat/edit-prompt")
def edit_prompt_with_lmstudio():
    payload = request.get_json(silent=True) or {}
    mode = str(payload.get("mode", "")).strip().lower()
    skip_system_prompt = bool(payload.get("skipSystemPrompt", False))
    story_mode = bool(payload.get("storyMode", False))
    instruction = str(payload.get("instruction", "")).strip()
    current_prompt = str(payload.get("currentPrompt", "")).strip()
    original_prompt = str(payload.get("originalPrompt", "")).strip() or current_prompt
    thinking = bool(payload.get("thinking", True))

    variant_count = 1
    try:
        variant_count = int(payload.get("variantCount", 1))
    except Exception:
        variant_count = 1
    variant_count = max(1, min(20, variant_count))

    data = _ensure_registry()
    settings = data.setdefault("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    lmstudio_model = _resolve_prompt_model(settings)
    auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))
    context_size = _auto_context_size(*_context_texts(payload))
    lmstudio_temperature = _coerce_lmstudio_temperature(
        settings.get("lmStudioTemperature", DEFAULT_LMSTUDIO_TEMPERATURE)
    )
    effective_context_size = context_size * (
        variant_count if mode == "brainvariants" else 1
    )

    instruction_max_chars = max(120, min(1800, int(effective_context_size * 0.4)))
    current_prompt_max_chars = effective_context_size
    original_prompt_max_chars = max(160, min(3200, int(effective_context_size * 0.55)))
    # Higher cap so reasoning models still have enough budget for real output
    # after spending tokens on internal CoT (even when thinking:false is ignored).
    max_output_tokens = _apply_max_tokens_override(payload, LMSTUDIO_MAX_OUTPUT_TOKENS)

    conversation_messages = _normalize_lmstudio_conversation_messages(
        payload.get("conversationMessages"), effective_context_size
    )

    if not conversation_messages:
        if not instruction:
            return jsonify({"error": "instruction is required"}), 400
        if not current_prompt:
            return jsonify({"error": "currentPrompt is required"}), 400

    instruction = _clip_text(instruction, instruction_max_chars)
    current_prompt = _clip_text(current_prompt, current_prompt_max_chars)
    original_prompt = _clip_text(original_prompt, original_prompt_max_chars)

    if mode == "brainvariants" and original_prompt:
        current_prompt = original_prompt

    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400
    if not lmstudio_model:
        return jsonify({"error": "LM Studio model is not selected"}), 400

    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if mode == "brainvariants":
        max_output_tokens = _apply_max_tokens_override(payload, LMSTUDIO_MAX_OUTPUT_TOKENS)
        if story_mode:
            # Story mode: sequential narrative where each scene builds on the previous
            system_prompt = (
                "You are a cinematic story director for AI image generation. "
                "Given an opening scene and a narrative direction, write a sequence of image generation prompts "
                "that tell a cohesive visual story. "
                "Rules:\n"
                "- Scene 1 starts directly from the opening scene.\n"
                "- Each subsequent scene evolves naturally from the previous one — they are connected frames of the same story.\n"
                "- Maintain visual consistency across all scenes: preserve the same characters, art style, color palette, and setting elements.\n"
                "- Only evolve what the narrative direction says should change; keep everything else stable.\n"
                "- Each prompt must be fully self-contained and detailed enough to generate the image on its own.\n"
                "Output ONLY a valid JSON array with no markdown fences or extra commentary."
            )
            user_prompt = (
                f"Opening scene:\n{original_prompt}\n\n"
                f"Narrative direction:\n{instruction}\n\n"
                f"Write exactly {variant_count} sequential scenes as a JSON array:\n"
                "[\n"
                "  {\n"
                '    "change_description": "what changed from the previous scene",\n'
                '    "new_prompt": "full self-contained prompt for this scene"\n'
                "  }\n"
                "]"
            )
        else:
            # Variations mode: independent variants of the original prompt (original behaviour)
            system_prompt = (
                "You are a prompt editor for image generation. "
                "Given an original prompt and an edit instruction, output ONLY a valid JSON array. "
                "Each item must contain keys 'change_description' and 'new_prompt'. "
                "Each new_prompt must be a distinct variation of the ORIGINAL prompt that follows the instruction. "
                "Do not output markdown fences or extra commentary."
            )
            user_prompt = (
                f"Original prompt:\n{original_prompt}\n\n"
                f"Edit instruction:\n{instruction}\n\n"
                f"Return exactly {variant_count} JSON items using this schema:\n"
                "[\n"
                "  {\n"
                '    "change_description": "what changed",\n'
                '    "new_prompt": "full edited prompt text"\n'
                "  }\n"
                "]"
            )
    else:
        system_prompt = (
            "You are an image prompt generator for AI image generation. You receive a base prompt and an instruction to change the current scene.\n"
            "Rules:\n"
            "- The prompt must be fully self-contained and detailed enough to generate the image on its own.\n"
            "- Apply the user's instruction to the base prompt. Preserve characters, setting, and style unless the instruction says otherwise. Only change what is asked.\n"
            "- Write in the comma-separated descriptive style used by Stable Diffusion and Flux image models.\n"
            "- Output ONLY the image prompt text. No JSON, no labels, no explanation."
        )
        user_prompt = (
            f"Base prompt:\n{current_prompt}\n\n"
            f"Instruction / What to change:\n{instruction}\n\n"
            "Return only the new image prompt text:"
        )

    # Apply custom prompt override from settings if configured.
    # Note: an active Brain Mode variant overrides the storyMode flag entirely.
    _custom_p = settings.get("customPrompts", {})
    if mode == "brainvariants":
        system_prompt = _custom_p.get("editVariants") or system_prompt
        # Also override user_prompt schema comment to match story vs variations
        # (the system_prompt drives everything; user_prompt is already set above)
    else:
        custom_single = str(_custom_p.get("editSingle", "") or "").strip()

    if mode == "brainvariants":
        messages: list[dict[str, str]] = []
        if not skip_system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if conversation_messages:
            messages.extend(conversation_messages)
            if messages[-1].get("role") != "user" and instruction and current_prompt:
                messages.append({"role": "user", "content": user_prompt})
        else:
            messages.append({"role": "user", "content": user_prompt})
    else:
        sys_msg = custom_single if custom_single else system_prompt
        if not skip_system_prompt:
            messages = [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_prompt},
            ]
        else:
            messages = [{"role": "user", "content": user_prompt}]

    auto_disconnect_loaded = False
    unload_instance_id = ""
    auto_disconnect_applied = False
    response: dict[str, Any] = {}

    try:
        if auto_disconnect:
            auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                lmstudio_url, lmstudio_model, context_size
            )

        _llm_text, _llm_source = _call_studio_llm(
            lmstudio_url,
            lmstudio_model,
            messages,
            lmstudio_temperature,
            max_output_tokens,
            reasoning=("on" if thinking else "off"),
            timeout=300,
            label="edit-prompt",
        )
    except Exception as exc:
        logger.exception("LM Studio chat request failed for model '%s'", lmstudio_model)
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            auto_disconnect_applied = _lmstudio_unload_model(
                lmstudio_url, unload_instance_id
            )
        _append_lmstudio_output_log(
            data,
            settings,
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "model": lmstudio_model,
                "instruction": _clip_text(instruction, 240),
                "editedPrompt": "",
                "rawOutput": f"ERROR: {exc}",
                "ok": False,
            },
        )
        return jsonify(
            {
                "error": (
                    f"LM Studio request failed: {exc}. "
                    "Check that the selected LM Studio model supports vision/image inputs."
                )
            }
        ), 502

    raw_output = ""
    raw_source = ""
    variants: list[dict[str, str]] = []
    try:
        raw_output, raw_source = _llm_text, _llm_source
        if mode == "brainvariants":
            parsed_items = _extract_json_array_from_text(raw_output)
            for item in parsed_items:
                if not isinstance(item, dict):
                    continue
                description = _clip_text(
                    str(item.get("change_description", "")).strip(), 240
                )
                next_prompt = _sanitize_lmstudio_edited_prompt(
                    str(item.get("new_prompt", "")).strip()
                )
                if not next_prompt:
                    continue
                variants.append(
                    {
                        "change_description": description or "Variation",
                        "new_prompt": _clip_text(next_prompt, 1800),
                    }
                )
            if len(variants) > variant_count:
                variants = variants[:variant_count]
            edited_prompt = variants[0]["new_prompt"] if variants else ""
        else:
            edited_prompt = _sanitize_lmstudio_edited_prompt(raw_output)
    except Exception:
        logger.exception(
            "Failed to parse LM Studio output for model '%s'", lmstudio_model
        )
        edited_prompt = ""

    _append_lmstudio_output_log(
        data,
        settings,
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "model": lmstudio_model,
            "instruction": _clip_text(instruction, 240),
            "editedPrompt": _clip_text(edited_prompt, 1400),
            "rawOutput": _clip_text(raw_output, 1400),
            "ok": bool(edited_prompt),
        },
    )

    if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
        auto_disconnect_applied = _lmstudio_unload_model(
            lmstudio_url, unload_instance_id
        )

    if mode == "brainvariants":
        if not variants:
            return jsonify(
                _reasoning_only_error(
                    raw_source, max_output_tokens, "LM Studio returned invalid or empty variants JSON"
                )
            ), 502
        return jsonify(
            {
                "editedPrompt": variants[0]["new_prompt"],
                "variants": variants,
                "model": lmstudio_model,
                "lmStudioApiUrl": lmstudio_url,
                "autoDisconnectEnabled": auto_disconnect,
                "autoDisconnectLoaded": auto_disconnect_loaded
                if auto_disconnect
                else False,
                "autoDisconnectApplied": auto_disconnect_applied,
                "contextLimits": {
                    "contextSize": context_size,
                    "effectiveContextSize": effective_context_size,
                    "brainEntries": variant_count,
                    "instructionMaxChars": instruction_max_chars,
                    "currentPromptMaxChars": current_prompt_max_chars,
                    "originalPromptMaxChars": original_prompt_max_chars,
                    "maxOutputTokens": max_output_tokens,
                },
            }
        )

    if not edited_prompt:
        return jsonify(
            _reasoning_only_error(raw_source, max_output_tokens, "LM Studio returned empty edited prompt")
        ), 502

    return jsonify(
        {
            "editedPrompt": edited_prompt,
            "model": lmstudio_model,
            "lmStudioApiUrl": lmstudio_url,
            "autoDisconnectEnabled": auto_disconnect,
            "autoDisconnectLoaded": auto_disconnect_loaded
            if auto_disconnect
            else False,
            "autoDisconnectApplied": auto_disconnect_applied,
            "contextLimits": {
                "contextSize": context_size,
                "effectiveContextSize": effective_context_size,
                "brainEntries": 1,
                "instructionMaxChars": instruction_max_chars,
                "currentPromptMaxChars": current_prompt_max_chars,
                "originalPromptMaxChars": original_prompt_max_chars,
                "maxOutputTokens": max_output_tokens,
            },
        }
    )


@models_api_bp.post("/models/chat/convert-to-json")
def convert_prompt_to_json_with_lmstudio():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    enhance = bool(payload.get("enhance", False))
    thinking = bool(payload.get("thinking", False))

    if not text:
        return jsonify({"error": "text is required"}), 400

    data = _ensure_registry()
    settings = data.setdefault("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    lmstudio_model = _resolve_prompt_model(settings)
    auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))
    context_size = _auto_context_size(*_context_texts(payload))
    lmstudio_temperature = _coerce_lmstudio_temperature(
        settings.get("lmStudioTemperature", DEFAULT_LMSTUDIO_TEMPERATURE)
    )

    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400
    if not lmstudio_model:
        return jsonify({"error": "LM Studio model is not selected"}), 400

    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    prompt_max_chars = max(
        700, min(6000, int(context_size * (1.3 if enhance else 1.0)))
    )
    text = _clip_text(text, prompt_max_chars)
    max_output_tokens = _apply_max_tokens_override(
        payload, max(180, min(1800, int(context_size * (0.7 if enhance else 0.5))))
    )

    if enhance:
        # Single definition, shared with the Settings editor. These used to be
        # duplicated inline here, so editing the defaults in settings_routes.py
        # changed what Settings showed while the running prompt stayed the same.
        system_prompt = DEFAULT_CUSTOM_PROMPTS["convertToJsonEnhanced"]
    else:
        system_prompt = DEFAULT_CUSTOM_PROMPTS["convertToJson"]

    user_prompt = (
        "Turn this image idea into the JSON shape described above. Keep the "
        "subject and intent, and fill in the specifics it implies.\n\n"
        f"{text}\n\n"
        "Return only valid JSON."
    )

    # Apply custom prompt override from settings if configured.
    _custom_p = settings.get("customPrompts", {})
    if enhance:
        system_prompt = _custom_p.get("convertToJsonEnhanced") or system_prompt
    else:
        system_prompt = _custom_p.get("convertToJson") or system_prompt

    auto_disconnect_loaded = False
    unload_instance_id = ""
    auto_disconnect_applied = False
    response: dict[str, Any] = {}

    try:
        if auto_disconnect:
            auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                lmstudio_url, lmstudio_model, context_size
            )

        _llm_text, _llm_source = _call_studio_llm(
            lmstudio_url,
            lmstudio_model,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            lmstudio_temperature,
            max_output_tokens,
            reasoning=("on" if thinking else "off"),
            timeout=300,
            label="convert-to-json",
        )
    except Exception as exc:
        logger.exception(
            "LM Studio convert-to-json request failed for model '%s'", lmstudio_model
        )
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            auto_disconnect_applied = _lmstudio_unload_model(
                lmstudio_url, unload_instance_id
            )
        _append_lmstudio_output_log(
            data,
            settings,
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "model": lmstudio_model,
                "instruction": "convert-to-json",
                "editedPrompt": "",
                "rawOutput": f"ERROR: {exc}",
                "ok": False,
            },
        )
        return jsonify({"error": f"LM Studio request failed: {exc}"}), 502

    raw_output, raw_source = _llm_text, _llm_source

    json_payload = _extract_json_payload_from_text(raw_output)
    if json_payload is None:
        _append_lmstudio_output_log(
            data,
            settings,
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "model": lmstudio_model,
                "instruction": "convert-to-json",
                "editedPrompt": "",
                "rawOutput": _clip_text(raw_output, 1800),
                "ok": False,
            },
        )
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            auto_disconnect_applied = _lmstudio_unload_model(
                lmstudio_url, unload_instance_id
            )
        return jsonify(
            _reasoning_only_error(raw_source, max_output_tokens, "LM Studio returned invalid JSON output")
        ), 502

    pretty_json = _clip_text(json.dumps(json_payload, ensure_ascii=False), 1400)
    _append_lmstudio_output_log(
        data,
        settings,
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "model": lmstudio_model,
            "instruction": "convert-to-json-enhance" if enhance else "convert-to-json",
            "editedPrompt": pretty_json,
            "rawOutput": _clip_text(raw_output, 1400),
            "ok": True,
        },
    )

    if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
        auto_disconnect_applied = _lmstudio_unload_model(
            lmstudio_url, unload_instance_id
        )

    return jsonify(
        {
            "json": json_payload,
            "enhanced": enhance,
            "model": lmstudio_model,
            "lmStudioApiUrl": lmstudio_url,
            "autoDisconnectEnabled": auto_disconnect,
            "autoDisconnectLoaded": auto_disconnect_loaded
            if auto_disconnect
            else False,
            "autoDisconnectApplied": auto_disconnect_applied,
            "contextLimits": {
                "contextSize": context_size,
                "promptMaxChars": prompt_max_chars,
                "maxOutputTokens": max_output_tokens,
            },
        }
    )


@models_api_bp.post("/models/chat/regenerate-json-field")
def regenerate_json_field_with_lmstudio():
    payload = request.get_json(silent=True) or {}
    field_path = str(payload.get("path", "")).strip()
    field_type = str(payload.get("fieldType", "string")).strip().lower()
    current_value = payload.get("currentValue")
    current_json = payload.get("currentJson")

    if not field_path:
        return jsonify({"error": "path is required"}), 400
    if not isinstance(current_json, (dict, list)):
        return jsonify({"error": "currentJson must be an object or array"}), 400

    data = _ensure_registry()
    settings = data.setdefault("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    lmstudio_model = _resolve_prompt_model(settings)
    auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))
    context_size = _auto_context_size(*_context_texts(payload))
    lmstudio_temperature = _coerce_lmstudio_temperature(
        settings.get("lmStudioTemperature", DEFAULT_LMSTUDIO_TEMPERATURE)
    )

    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400
    if not lmstudio_model:
        return jsonify({"error": "LM Studio model is not selected"}), 400

    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    json_context_text = _clip_text(
        json.dumps(current_json, ensure_ascii=False),
        max(1200, min(10000, int(context_size * 3))),
    )
    current_value_text = _clip_text(
        json.dumps(current_value, ensure_ascii=False),
        max(120, min(2400, int(context_size * 0.8))),
    )
    max_output_tokens = _apply_max_tokens_override(
        payload, max(120, min(1200, int(context_size * 0.35)))
    )

    system_prompt = (
        "You are helping edit a JSON field for image-generation prompts. "
        "Return ONLY one valid JSON value for the requested field path. "
        "Do not return an object wrapper, markdown, or explanations."
    )

    user_prompt = (
        f"Target field path: {field_path}\n"
        f"Expected field type: {field_type}\n"
        f"Current field value (JSON): {current_value_text}\n\n"
        "Generate a fresh alternative value for this field while staying coherent with the prompt context JSON below. "
        "If possible, keep the same data type as expected.\n\n"
        f"Context JSON:\n{json_context_text}\n\n"
        "Return only the new JSON value."
    )

    auto_disconnect_loaded = False
    unload_instance_id = ""
    auto_disconnect_applied = False
    response: dict[str, Any] = {}

    try:
        if auto_disconnect:
            auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                lmstudio_url, lmstudio_model, context_size
            )

        _llm_text, _llm_source = _call_studio_llm(
            lmstudio_url,
            lmstudio_model,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            lmstudio_temperature,
            max_output_tokens,
            reasoning="off",
            timeout=300,
            label="regenerate-json-field",
        )
    except Exception as exc:
        logger.exception(
            "LM Studio regenerate-json-field request failed for model '%s'",
            lmstudio_model,
        )
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            auto_disconnect_applied = _lmstudio_unload_model(
                lmstudio_url, unload_instance_id
            )
        _append_lmstudio_output_log(
            data,
            settings,
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "model": lmstudio_model,
                "instruction": "regenerate-json-field",
                "editedPrompt": "",
                "rawOutput": f"ERROR: {exc}",
                "ok": False,
            },
        )
        return jsonify({"error": f"LM Studio request failed: {exc}"}), 502

    raw_output, raw_source = _llm_text, _llm_source

    parsed_value: Any = None
    value_ok = False

    if raw_output:
        try:
            parsed_value = json.loads(raw_output)
            value_ok = True
        except Exception:
            payload_from_text = _extract_json_payload_from_text(raw_output)
            if payload_from_text is not None:
                parsed_value = payload_from_text
                value_ok = True

    if not value_ok and field_type == "string":
        fallback = str(raw_output or "").strip()
        if fallback:
            parsed_value = fallback
            value_ok = True

    if not value_ok:
        _append_lmstudio_output_log(
            data,
            settings,
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "model": lmstudio_model,
                "instruction": "regenerate-json-field",
                "editedPrompt": "",
                "rawOutput": _clip_text(raw_output, 1800),
                "ok": False,
            },
        )
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            auto_disconnect_applied = _lmstudio_unload_model(
                lmstudio_url, unload_instance_id
            )
        return jsonify(
            _reasoning_only_error(raw_source, max_output_tokens, "LM Studio returned invalid JSON field value")
        ), 502

    _append_lmstudio_output_log(
        data,
        settings,
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "model": lmstudio_model,
            "instruction": "regenerate-json-field",
            "editedPrompt": _clip_text(
                json.dumps(parsed_value, ensure_ascii=False), 1200
            ),
            "rawOutput": _clip_text(raw_output, 1400),
            "ok": True,
        },
    )

    if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
        auto_disconnect_applied = _lmstudio_unload_model(
            lmstudio_url, unload_instance_id
        )

    return jsonify(
        {
            "value": parsed_value,
            "path": field_path,
            "fieldType": field_type,
            "model": lmstudio_model,
            "lmStudioApiUrl": lmstudio_url,
            "autoDisconnectEnabled": auto_disconnect,
            "autoDisconnectLoaded": auto_disconnect_loaded
            if auto_disconnect
            else False,
            "autoDisconnectApplied": auto_disconnect_applied,
            "contextLimits": {
                "contextSize": context_size,
                "maxOutputTokens": max_output_tokens,
            },
        }
    )


@models_api_bp.post("/models/chat/blend-prompts")
def blend_prompts_with_lmstudio():
    payload = request.get_json(silent=True) or {}
    scene_prompt = str(payload.get("scenePrompt", "")).strip()
    style_prompt = str(payload.get("stylePrompt", "")).strip()

    if not scene_prompt:
        return jsonify({"error": "scenePrompt is required"}), 400
    if not style_prompt:
        return jsonify({"error": "stylePrompt is required"}), 400

    data = _ensure_registry()
    settings = data.setdefault("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    lmstudio_model = _resolve_prompt_model(settings)
    auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))
    context_size = _auto_context_size(*_context_texts(payload))
    lmstudio_temperature = _coerce_lmstudio_temperature(
        settings.get("lmStudioTemperature", DEFAULT_LMSTUDIO_TEMPERATURE)
    )

    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400
    if not lmstudio_model:
        return jsonify({"error": "LM Studio model is not selected"}), 400

    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    scene_prompt = _clip_text(scene_prompt, max(800, context_size * 2))
    style_prompt = _clip_text(style_prompt, max(800, context_size * 2))
    max_output_tokens = _apply_max_tokens_override(payload, LMSTUDIO_MAX_OUTPUT_TOKENS)

    system_prompt = (
        "You are an expert prompt blender for image generation. "
        "Blend two prompts into one cohesive prompt. "
        "Preserve scene structure, subjects, actions, and composition from the scene prompt. "
        "Apply artistic style, lighting mood, texture, palette, and rendering characteristics from the style prompt. "
        "Return only the final blended prompt text with no markdown, labels, or explanations."
    )
    user_prompt = (
        f"Scene and character prompt:\n{scene_prompt}\n\n"
        f"Style prompt:\n{style_prompt}\n\n"
        "Output one final blended prompt."
    )

    # Apply custom prompt override from settings if configured.
    system_prompt = (
        settings.get("customPrompts", {}).get("blendPrompts") or system_prompt
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    auto_disconnect_loaded = False
    unload_instance_id = ""
    auto_disconnect_applied = False

    try:
        if auto_disconnect:
            auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                lmstudio_url, lmstudio_model, context_size
            )

        _llm_text, _llm_source = _call_studio_llm(
            lmstudio_url,
            lmstudio_model,
            messages,
            lmstudio_temperature,
            max_output_tokens,
            reasoning="off",
            timeout=300,
            label="blend-prompts",
        )
    except Exception as exc:
        logger.exception(
            "LM Studio blend prompt request failed for model '%s'", lmstudio_model
        )
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            auto_disconnect_applied = _lmstudio_unload_model(
                lmstudio_url, unload_instance_id
            )
        _append_lmstudio_output_log(
            data,
            settings,
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "model": lmstudio_model,
                "instruction": "blend-prompts",
                "editedPrompt": "",
                "rawOutput": f"ERROR: {exc}",
                "ok": False,
            },
        )
        return jsonify({"error": f"LM Studio request failed: {exc}"}), 502

    raw_output, raw_source = _llm_text, _llm_source
    blended_prompt = _sanitize_lmstudio_edited_prompt(raw_output)

    _append_lmstudio_output_log(
        data,
        settings,
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "model": lmstudio_model,
            "instruction": "blend-prompts",
            "editedPrompt": blended_prompt,
            "rawOutput": raw_output,
            "ok": bool(blended_prompt),
        },
    )

    if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
        auto_disconnect_applied = _lmstudio_unload_model(
            lmstudio_url, unload_instance_id
        )

    if not blended_prompt:
        return jsonify(
            _reasoning_only_error(raw_source, max_output_tokens, "LM Studio returned empty blended prompt")
        ), 502

    return jsonify(
        {
            "blendedPrompt": blended_prompt,
            "model": lmstudio_model,
            "lmStudioApiUrl": lmstudio_url,
            "autoDisconnectEnabled": auto_disconnect,
            "autoDisconnectLoaded": auto_disconnect_loaded
            if auto_disconnect
            else False,
            "autoDisconnectApplied": auto_disconnect_applied,
            "contextLimits": {
                "contextSize": context_size,
                "maxOutputTokens": max_output_tokens,
            },
        }
    )


# ---------------------------------------------------------------------------
# Studio Enhance — New modal prompt enhancement levels
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Studio Scenes — generate N scene prompts from an idea
# ---------------------------------------------------------------------------


