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
    _registry_transaction,
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

@models_api_bp.post("/models/chat/describe-image")
def describe_image_with_lmstudio():
    payload = request.get_json(silent=True) or {}
    image_data_url = str(payload.get("imageDataUrl", "")).strip()
    describe_type = str(payload.get("describeType", "prompt")).strip().lower()
    describe_scope = str(payload.get("describeScope", "full")).strip().lower()
    describe_format = str(payload.get("describeFormat", "paragraph")).strip().lower()
    force_refresh = bool(payload.get("forceRefresh", False))
    custom_system_prompt = str(payload.get("systemPrompt", "")).strip()
    include_pose = bool(payload.get("includePose", True))
    if describe_type not in {"prompt", "style", "typography", "character"}:
        describe_type = "prompt"
    if describe_scope not in {"full", "scene"}:
        describe_scope = "full"
    if describe_format not in {"paragraph", "json"}:
        describe_format = "paragraph"

    cache_describe_key = (
        f"{describe_type}:{describe_scope}:{describe_format}"
        if describe_type == "prompt"
        else f"{describe_type}:{describe_format}"
        + ("" if describe_type != "character" else (":pose" if include_pose else ":nopose"))
    )

    if not image_data_url:
        return jsonify({"error": "imageDataUrl is required"}), 400

    try:
        image_mime, image_bytes = _parse_image_data_url(image_data_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    image_hash = hashlib.sha256(image_bytes).hexdigest()

    data = _ensure_registry()
    settings = data.setdefault("settings", {})

    if not force_refresh:
        cached_entry = _describe_cache_get(settings, image_hash, cache_describe_key)
        if cached_entry:
            cached_description = str(cached_entry.get("description", "")).strip()
            if cached_description:
                return jsonify(
                    {
                        "description": cached_description,
                        "describeType": describe_type,
                        "describeScope": describe_scope,
                        "describeFormat": describe_format,
                        "imageHash": image_hash,
                        "cached": True,
                        "model": _resolve_vision_model(
                            settings, _resolve_prompt_model(settings)
                        ),
                        "lmStudioApiUrl": str(
                            settings.get("lmStudioApiUrl", "")
                        ).strip(),
                        "autoDisconnectEnabled": bool(
                            settings.get("lmStudioAutoDisconnect", False)
                        ),
                        "autoDisconnectLoaded": False,
                        "autoDisconnectApplied": False,
                        "contextLimits": {
                            "contextSize": _auto_context_size(
                                *_context_texts(payload)
                            ),
                            "maxOutputTokens": 0,
                        },
                    }
                )
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    lmstudio_model = _resolve_explicit_vision_model(settings)
    configured_vision_models = [
        str(item or "").strip()
        for item in settings.get("lmStudioVisionModels", [])
        if str(item or "").strip()
    ]
    if configured_vision_models and lmstudio_model not in configured_vision_models:
        lmstudio_model = configured_vision_models[0]
        settings["lmStudioVisionModel"] = lmstudio_model
        # Small, quick correction — done before the slow vision call below, so
        # the registry lock is only held for this write, not for the request.
        with _registry_transaction() as tx_data:
            tx_data.setdefault("settings", {})["lmStudioVisionModel"] = lmstudio_model
    auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))
    context_size = _auto_context_size(*_context_texts(payload))
    lmstudio_temperature = _coerce_lmstudio_temperature(
        settings.get("lmStudioTemperature", DEFAULT_LMSTUDIO_TEMPERATURE)
    )
    # Generous cap: reasoning models spend many tokens on CoT before producing output.
    max_output_tokens = _apply_max_tokens_override(
        payload, max(800, min(3000, int(context_size * 0.65)))
    )

    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400
    if not lmstudio_model:
        return jsonify({"error": "LM Studio vision model is not selected"}), 400

    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if describe_type == "typography":
        system_prompt = (
            "You are a typography and lettering style analyst for AI image generation. "
            "Analyze the text, lettering, or title treatment visible in this image and produce a concise, "
            "ready-to-use style description for an Ideogram text element.\n\n"
            "Identify and describe:\n"
            "1. LETTERFORM TYPE: serif / sans-serif / script / display / blackletter / slab / decorative / hand-lettered\n"
            "2. WEIGHT & WIDTH: thin / light / regular / bold / black / condensed / expanded\n"
            "3. SURFACE TREATMENT: flat / embossed / debossed / engraved / 3D extruded / outlined / inline / shadowed\n"
            "4. MATERIAL OR TEXTURE: metallic gold / chrome / stone carving / wood grain / neon glow / glass / liquid / fire / organic / worn ink / etc.\n"
            "5. COLOR TREATMENT: solid / gradient / metallic sheen / iridescent / duotone / multi-color / monochrome\n"
            "6. SPECIAL EFFECTS: glow / drop shadow / inner glow / distress / aged / cracked / eroded / paint splatter / etc.\n"
            "7. ERA OR AESTHETIC: art nouveau / art deco / gothic / medieval / futuristic / retro 80s / grunge / Victorian / modern minimalist / etc.\n"
            "8. DECORATIVE ELEMENTS: ornate serifs / swashes / ligatures / flourishes / inline details / decorative frames\n\n"
            "Output 4–6 comma-separated descriptive phrases that can be pasted directly as an Ideogram lettering style instruction. "
            "Be specific and visual — not 'fancy font' but 'hand-lettered script, thick ink brush strokes, aged parchment texture, warm sepia tones, Victorian flourishes'. "
            "Output ONLY the phrase list. No headers. No bullets. No explanation."
        )
        user_instruction = "Describe the lettering style now."
    elif describe_type == "style":
        if describe_format == "json":
            system_prompt = (
                "Act as a Visual Style Analyst for text-to-image workflows. "
                "Return only valid minified JSON with this exact schema: "
                '{"style_family":"","style_family_secondary":"","medium":"","movement":"","rendering":"","palette":"","contrast":"","lighting_tone":"","lighting_colors":[],"composition_language":"","texture_treatment":"","depth_feel":"","post_processing":"","notes":""}. '
                "Use empty strings or empty arrays when unknown. "
                "Describe only visible visual style characteristics and avoid camera metadata."
            )
        else:
            system_prompt = (
                "Act as a Visual Style Analyst for text-to-image workflows. "
                "Start by explicitly identifying the dominant style family in plain words (for example: anime, photorealistic, comic, cartoon, 3D render, watercolor, oil painting, sketch, cinematic). "
                "If the style is hybrid, name the two closest style families. "
                "Describe only the visual style characteristics visible in the image: medium, artistic movement, rendering approach, "
                "color palette, contrast, lighting mood, lighting tone, lighting color accents, composition language, texture treatment, lens/depth feeling, and post-processing cues. "
                "Avoid describing identity-specific subject details unless they are necessary to explain the style. "
                "Write one single continuous paragraph with no headers or bullets. "
                "Target 350-650 characters. "
                "If uncertainty exists, briefly mark it instead of inventing. "
                "Do not include markdown, labels, or camera metadata."
            )
        user_instruction = "Generate the final style description now."
    elif describe_type == "character":
        if include_pose:
            pose_instruction = (
                "Never use the words 'surface', 'ground', 'floor', 'bed', 'chair', 'wall', 'table', 'seat', or any "
                "other noun naming what the person is sitting/standing/leaning/lying on — not even generically. "
                "Describe pose purely as body geometry relative to the person's own body (e.g. 'cross-legged, hands "
                "resting near her hips' or 'standing with weight on one leg, arms crossed'), never by naming what "
                "supports them. "
            )
            pose_paragraph_clause = "pose and gesture described purely as body geometry, "
            pose_schema_key = '"pose":"",'
        else:
            pose_instruction = (
                "Do not mention the person's pose, gesture, body position, or how any part of their body is "
                "arranged (standing, sitting, cross-legged, hand placement, etc.) at all — skip pose entirely. "
            )
            pose_paragraph_clause = ""
            pose_schema_key = ""
        if describe_format == "json":
            system_prompt = (
                "Act as a Character Analyst for text-to-image prompting. "
                "Describe ONLY the person/character in this image — do not describe the background, "
                "scene, environment, or any other subject visible behind or around them. "
                + pose_instruction
                + "The only physical objects allowed in the description are ones the person is "
                "wearing or holding as an accessory (clothing, jewelry, a bag, etc.). "
                "Return only valid minified JSON with this exact schema: "
                '{"facial_features":"","ethnicity_or_ancestry":"","expression":"","gaze":"","hair":"",'
                '"makeup":"",' + pose_schema_key + '"clothing":"","accessories":"","rendering_style":"","uncertainties":""}. '
                "\"rendering_style\" covers medium/artistic style (photographic, illustrated, painterly, anime, 3D render, etc.) — "
                "this is the one style-related field to include, everything else must stay about the person only. "
                "Use empty strings when unknown. No markdown, no extra keys, no prose outside JSON."
            )
        else:
            system_prompt = (
                "Act as a Character Analyst for text-to-image prompting. "
                "Describe ONLY the person/character in this image — do not describe the background, scene, "
                "environment, or any other subject visible behind or around them. "
                + pose_instruction
                + "The only physical objects allowed in the description are ones the person is "
                "wearing or holding as an accessory (clothing, jewelry, a bag, etc.). "
                "Include facial features, likely ethnicity or ancestry when inferable from visible traits, "
                "expression, gaze direction, hair, makeup if visible, "
                + pose_paragraph_clause
                + "clothing fabric/color/fit, and accessories. "
                "Also include the rendering/artistic style the character is depicted in (photographic, illustrated, "
                "painterly, anime, 3D render, etc.) — this is the one exception to the 'person only' rule. "
                "Write one single continuous paragraph with no headers or bullets. "
                "If a detail is not clearly visible, briefly acknowledge uncertainty instead of inventing. "
                "Do not include markdown, labels, camera metadata, or any description of the background/environment, "
                "surfaces, or furniture."
            )
        user_instruction = "Generate the final character description now."
    else:
        if describe_scope == "scene":
            if describe_format == "json":
                system_prompt = (
                    "Act as a Visual Scene Analyst for text-to-image prompting. "
                    "Return only valid minified JSON with this exact schema: "
                    '{"scene":"","subjects":[],"actions":"","composition":"","environment":"","spatial_relationships":"","lighting_tone":"","lighting_colors":[],"human_details":[{"facial_features":"","ethnicity_or_ancestry":"","certainty":""}],"readable_text":[],"uncertainties":""}. '
                    "If humans are present, include facial features and likely ethnicity or ancestry when inferable from visible cues; otherwise leave as uncertain. "
                    "Use empty arrays/strings when data is unavailable. "
                    "No markdown, no extra keys, no prose outside JSON."
                )
            else:
                system_prompt = (
                    "Act as a Visual Scene Analyst for text-to-image prompting. "
                    "Describe the scene, subjects, actions, composition, environment, and spatial relationships in detail. "
                    "Include lighting tone and specific visible lighting colors. "
                    "When humans appear, include their facial features and likely ethnicity or ancestry only when inferable from visible/contextual cues; if uncertain, explicitly say so. "
                    "Keep visual content rich but avoid style-family labels and avoid focusing on artistic medium terms unless unavoidable. "
                    "Write one single continuous paragraph with no headers or bullets. "
                    "Target 600-900 characters. "
                    "Quote any readable text exactly in double quotes. "
                    "If a detail is not clearly visible, briefly acknowledge uncertainty instead of inventing. "
                    "Do not include markdown, labels, or camera metadata."
                )
            user_instruction = "Generate the final scene-focused caption now."
        else:
            if describe_format == "json":
                system_prompt = (
                    "Act as a Visual Prompt Engineer specialized in descriptive captions for text-to-image prompting. "
                    "Return only valid minified JSON with this exact schema: "
                    '{"summary":"","scene_content":"","style_cues":"","main_subject":"","human_details":[{"facial_features":"","ethnicity_or_ancestry":"","expression":"","gaze":"","hair":"","makeup":"","pose":"","interaction":"","clothing":"","accessories":"","certainty":""}],"foreground":"","background":"","depth":"","lighting_tone":"","lighting_colors":[],"readable_text":[],"uncertainties":""}. '
                    "If humans are present, include facial features and likely ethnicity or ancestry when inferable from visible/contextual cues; otherwise mark uncertainty. "
                    "Use empty arrays/strings when unknown. "
                    "No markdown, no extra keys, no prose outside JSON."
                )
            else:
                system_prompt = (
                    "Act as a Visual Prompt Engineer specialized in long descriptive captions for text-to-image prompting."
                    "Describe exactly what is visible in the image with high detail and natural narrative flow."
                    "Include both scene content and visible stylistic/rendering cues from this image."
                    "If there is one main person, include expression, gaze direction, hair, facial features, likely ethnicity or ancestry when inferable from visible traits such as skin tone, eye shape, hair texture, and facial structure, makeup if visible, pose, hand or object interaction, clothing fabric/color/fit, and accessories."
                    "If there is no clear main person, describe the primary subject(s), composition, and interactions accordingly."
                    "Cover foreground elements, background setting, depth cues including bokeh when present, lighting quality, lighting tone, visible lighting colors, and color/texture specifics."
                    "Write one single continuous paragraph with no headers or bullets."
                    "Quote any readable text exactly in double quotes."
                    "If a detail is not clearly visible, briefly acknowledge uncertainty instead of inventing."
                    "Do not include markdown, labels, or camera metadata."
                )
            user_instruction = "Generate the final full caption now."

    # Qwen (and some other vision models) reject WebP — convert to JPEG.
    if image_mime == "image/webp":
        try:
            import io as _io
            from PIL import Image as _PILImage  # type: ignore

            with _PILImage.open(_io.BytesIO(image_bytes)) as _im:
                _buf = _io.BytesIO()
                _im.convert("RGB").save(_buf, format="JPEG", quality=95)
                image_bytes = _buf.getvalue()
                image_mime = "image/jpeg"
        except Exception:
            pass

    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    normalized_data_url = f"data:{image_mime};base64,{image_base64}"

    # Apply custom prompt override from settings if configured.
    _custom_p = settings.get("customPrompts", {})
    if describe_format == "json":
        if describe_type == "style":
            system_prompt = _custom_p.get("describeStyleJson") or system_prompt
        elif describe_type == "character":
            system_prompt = _custom_p.get("describeCharacterJson") or system_prompt
        elif describe_scope == "scene":
            system_prompt = _custom_p.get("describeSceneJson") or system_prompt
        else:
            system_prompt = _custom_p.get("describeFullJson") or system_prompt
    else:
        if describe_type == "style":
            system_prompt = _custom_p.get("describeStyle") or system_prompt
        elif describe_type == "character":
            system_prompt = _custom_p.get("describeCharacter") or system_prompt
        elif describe_scope == "scene":
            system_prompt = _custom_p.get("describeScene") or system_prompt
        else:
            _active_id = str(_custom_p.get("describeFullActiveId", "")).strip()
            if _active_id:
                _variants = _custom_p.get("describeFullVariants", [])
                _found = next(
                    (
                        v
                        for v in _variants
                        if isinstance(v, dict)
                        and str(v.get("id", "")) == _active_id
                        and v.get("text")
                    ),
                    None,
                )
                system_prompt = (
                    _found["text"]
                    if _found
                    else (_custom_p.get("describeFull") or system_prompt)
                )
            else:
                system_prompt = _custom_p.get("describeFull") or system_prompt

    # If the caller supplied an explicit systemPrompt, it takes precedence over
    # every built-in / custom-settings prompt constructed above.
    if custom_system_prompt:
        system_prompt = custom_system_prompt

    prefers_raw_base64 = "qwen" in lmstudio_model.lower()
    image_url_candidates = (
        [image_base64, normalized_data_url]
        if prefers_raw_base64
        else [normalized_data_url, image_base64]
    )
    message_variants: list[list[dict[str, Any]]] = []
    for image_url_value in image_url_candidates:
        message_variants.append(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_instruction},
                        {"type": "image_url", "image_url": {"url": image_url_value}},
                    ],
                },
            ]
        )

    auto_disconnect_loaded = False
    unload_instance_id = ""
    auto_disconnect_applied = False
    response: dict[str, Any] = {}
    used_variant_idx = -1
    last_error: Exception | None = None

    try:
        if auto_disconnect:
            auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                lmstudio_url, lmstudio_model, context_size
            )

        for idx, messages in enumerate(message_variants):
            try:
                _llm_text, _llm_source = _call_studio_llm(
                    lmstudio_url,
                    lmstudio_model,
                    messages,
                    lmstudio_temperature,
                    max_output_tokens,
                    reasoning="off",
                    timeout=300,
                    label="describe-image",
                )
                used_variant_idx = idx
                last_error = None
                break
            except Exception as exc:
                # Keep the FIRST failure, not the last. The variants are
                # ordered best-guess-first for this model, so variant 0's error
                # is the real diagnosis and the later one is the long shot
                # failing as expected. Reporting the last one hid a "Reasoning
                # setting 'off' is not supported by model ..." behind a
                # baffling "Invalid base64-encoded data URI" that had nothing
                # to do with the actual problem.
                if last_error is None:
                    last_error = exc

        if last_error is not None:
            raise last_error
    except Exception as exc:
        logger.exception(
            "LM Studio image describe request failed for model '%s'", lmstudio_model
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
                "instruction": f"describe-image:{describe_type}:variant-{used_variant_idx}",
                "editedPrompt": "",
                "rawOutput": f"ERROR: {exc}",
                "ok": False,
            },
        )
        return jsonify(
            {
                "error": (
                    f"LM Studio request failed: {exc}. "
                    "Tried image_url.url as data URL and as raw base64."
                )
            }
        ), 502

    raw_output, raw_source = _llm_text, _llm_source

    description = _sanitize_lmstudio_edited_prompt(raw_output)

    if description:
        _describe_cache_set(
            data,
            settings,
            image_hash,
            cache_describe_key,
            {
                "description": description,
                "mime": image_mime,
                "at": datetime.now(timezone.utc).isoformat(),
            },
        )

    _append_lmstudio_output_log(
        data,
        settings,
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "model": lmstudio_model,
            "instruction": f"describe-image:{describe_type}:variant-{used_variant_idx}",
            "editedPrompt": description,
            "rawOutput": f"[{raw_source or 'unknown'}] {raw_output}",
            "ok": bool(description),
        },
    )

    if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
        auto_disconnect_applied = _lmstudio_unload_model(
            lmstudio_url, unload_instance_id
        )

    if not description:
        return jsonify(
            _reasoning_only_error(raw_source, max_output_tokens, "LM Studio returned empty image description")
        ), 502

    return jsonify(
        {
            "description": description,
            "describeType": describe_type,
            "describeScope": describe_scope,
            "describeFormat": describe_format,
            "imageHash": image_hash,
            "cached": False,
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


@models_api_bp.post("/models/chat/edit-description")
def edit_description_with_lmstudio():
    """Edit an existing description using an instruction via LM Studio."""
    payload = request.get_json(silent=True) or {}
    current_description = str(payload.get("current_description", "")).strip()
    instruction = str(payload.get("instruction", "")).strip()

    if not current_description:
        return jsonify({"error": "current_description is required"}), 400
    if not instruction:
        return jsonify({"error": "instruction is required"}), 400

    data = _ensure_registry()
    settings = data.get("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    lmstudio_model = _resolve_prompt_model(settings)
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

    system_prompt = (
        "You are an expert visual description editor. "
        "You will receive an existing image description and an editing instruction. "
        "Apply the instruction precisely while keeping the description natural, detailed and well-structured. "
        "Preserve the original structure and level of detail unless the instruction explicitly asks to change it. "
        "Return ONLY the edited description text. Do not add explanations, markdown, or extra commentary."
    )
    user_prompt = f"Current description:\n{current_description}\n\nInstruction: {instruction}\n\nEdited description:"
    max_output_tokens = _apply_max_tokens_override(payload, LMSTUDIO_MAX_OUTPUT_TOKENS)

    try:
        raw_output, raw_source = _call_studio_llm(
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
            label="edit-description",
        )
        edited = raw_output.strip() if raw_output else ""
        if not edited:
            return jsonify(
                _reasoning_only_error(raw_source, max_output_tokens, "LM Studio returned empty response")
            ), 502

        return jsonify({"edited_description": edited})
    except Exception as exc:
        logger.exception("LM Studio edit-description request failed")
        return jsonify({"error": f"Edit failed: {str(exc)}"}), 502


@models_api_bp.post("/styles/generate-from-image")
def generate_style_from_image():
    """Call the Vision Model to analyse an image and return a structured style object."""
    payload = request.get_json(silent=True) or {}
    image_data_url = str(payload.get("imageDataUrl", "")).strip()

    if not image_data_url:
        return jsonify({"error": "imageDataUrl is required"}), 400

    try:
        image_mime, image_bytes = _parse_image_data_url(image_data_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    data = _ensure_registry()
    settings = data.setdefault("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    lmstudio_model = _resolve_explicit_vision_model(settings)
    auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))
    context_size = _auto_context_size(*_context_texts(payload))
    lmstudio_temperature = _coerce_lmstudio_temperature(
        settings.get("lmStudioTemperature", DEFAULT_LMSTUDIO_TEMPERATURE)
    )
    max_output_tokens = LMSTUDIO_MAX_OUTPUT_TOKENS
    # Allow caller to override max_tokens (e.g. retry after reasoning-only response).
    requested_max_tokens = payload.get("maxTokens")
    if (
        isinstance(requested_max_tokens, int)
        and requested_max_tokens > max_output_tokens
    ):
        max_output_tokens = requested_max_tokens

    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400
    if not lmstudio_model:
        return jsonify({"error": "No vision model is configured"}), 400

    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Qwen (and some other vision models) reject WebP — convert to JPEG.
    if image_mime == "image/webp":
        try:
            import io as _io
            from PIL import Image as _PILImage  # type: ignore

            with _PILImage.open(_io.BytesIO(image_bytes)) as _im:
                _buf = _io.BytesIO()
                _im.convert("RGB").save(_buf, format="JPEG", quality=95)
                image_bytes = _buf.getvalue()
                image_mime = "image/jpeg"
        except Exception:
            pass

    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    normalized_data_url = f"data:{image_mime};base64,{image_base64}"

    system_prompt = (
        "Act as a Visual Style Analyst for text-to-image generation workflows. "
        "Analyze the visual rendering style, artistic technique, and aesthetic qualities of this image. "
        "Explicitly analyze dominant color tonalities, palette harmony, and background tone. "
        "If the image is an illustration, explicitly analyze stroke style, line weight, and stroke color behavior. "
        "Return only valid minified JSON with this exact schema: "
        '{"title":"","category":"","prompt":"","prefix":"","suffix":""}. '
        "- title: a memorable 2-4 word name for this visual style. "
        "- category: one word from: photorealistic, anime, illustration, painting, 3d-render, sketch, cinematic, fantasy, abstract, other. "
        "- prompt: a rich 100-200 word description of the visual content and style suitable as a text-to-image prompt. "
        "  Describe subjects, scene, composition, lighting, color tonalities, palette structure, and stylistic rendering. "
        "  For illustration categories, include stroke style and stroke color details in the prompt text. "
        "- prefix: 15-20 words explanining the style plus one word from: photorealistic, anime, illustration, painting, 3d-render, sketch, cinematic, fantasy, abstract, other. "
        "- suffix: Give me 15-20 exact words that describe the style, palette, lighting, and visual rendering of this image. Use specific terms: for example, ochre,teal water,bold ink lines,cinematic sunlit highlights, etc. Don't use phrases like fantasy landscape or comic style—only words that accurately define the visuals."
        "Return only the JSON object with no markdown, no code fences, no extra keys, no prose."
    )
    custom_prompts = (
        settings.get("customPrompts", {})
        if isinstance(settings.get("customPrompts", {}), dict)
        else {}
    )
    system_prompt = (
        str(custom_prompts.get("referencePrompt") or "").strip() or system_prompt
    )
    user_instruction = "Analyze this image and return the style JSON now."

    prefers_raw_base64 = "qwen" in lmstudio_model.lower()
    image_url_candidates = (
        [image_base64, normalized_data_url]
        if prefers_raw_base64
        else [normalized_data_url, image_base64]
    )
    message_variants: list[list[dict[str, Any]]] = []
    for image_url_value in image_url_candidates:
        message_variants.append(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_instruction},
                        {"type": "image_url", "image_url": {"url": image_url_value}},
                    ],
                },
            ]
        )

    auto_disconnect_loaded = False
    unload_instance_id = ""
    auto_disconnect_applied = False
    response: dict[str, Any] = {}
    used_variant_idx = -1
    last_error: Exception | None = None

    try:
        if auto_disconnect:
            auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                lmstudio_url, lmstudio_model, context_size
            )

        for idx, messages in enumerate(message_variants):
            try:
                _llm_text, _llm_source = _call_studio_llm(
                    lmstudio_url,
                    lmstudio_model,
                    messages,
                    lmstudio_temperature,
                    max_output_tokens,
                    reasoning="off",
                    timeout=300,
                    label="style-from-image",
                )
                used_variant_idx = idx
                last_error = None
                break
            except Exception as exc:
                # Keep the FIRST failure, not the last. The variants are
                # ordered best-guess-first for this model, so variant 0's error
                # is the real diagnosis and the later one is the long shot
                # failing as expected. Reporting the last one hid a "Reasoning
                # setting 'off' is not supported by model ..." behind a
                # baffling "Invalid base64-encoded data URI" that had nothing
                # to do with the actual problem.
                if last_error is None:
                    last_error = exc

        if last_error is not None:
            raise last_error
    except Exception as exc:
        logger.exception(
            "LM Studio generate-style-from-image failed for model '%s'", lmstudio_model
        )
        return jsonify({"error": f"LM Studio request failed: {exc}"}), 502
    finally:
        # Recipes flow: always attempt to unload the vision model after analysis.
        unload_target = unload_instance_id
        if not unload_target:
            unload_target = (
                lmstudio_service.find_loaded_instance_id(lmstudio_url, lmstudio_model)
                or lmstudio_model
            )
        if unload_target:
            auto_disconnect_applied = _lmstudio_unload_model(
                lmstudio_url, unload_target
            )

    raw_output, raw_source = _llm_text, _llm_source
    raw_output = _sanitize_lmstudio_edited_prompt(raw_output)

    if not raw_output:
        if raw_source == "reasoning_only":
            return jsonify(
                {
                    "error": "Vision model returned only reasoning content — max_tokens may be too low.",
                    "emptyWithReasoning": True,
                    "currentMaxTokens": max_output_tokens,
                }
            ), 502
        return jsonify({"error": "Vision model returned empty output"}), 502

    json_payload = _extract_json_payload_from_text(raw_output)
    if not isinstance(json_payload, dict):
        # Fallback: use the raw output as the prompt and derive a minimal style.
        json_payload = {
            "title": "Generated Style",
            "category": "other",
            "prompt": raw_output,
            "prefix": "",
            "suffix": "",
        }

    metadata = (
        json_payload.get("metadata", {}) if isinstance(json_payload, dict) else {}
    )
    if not isinstance(metadata, dict):
        metadata = {}

    style_dna = str(json_payload.get("style_dna", "") or "").strip()
    style_description = str(json_payload.get("style_description", "") or "").strip()
    legacy_prompt = str(json_payload.get("prompt", "") or "").strip()

    style = {
        "title": str(json_payload.get("title", "") or "").strip() or "Generated Style",
        "category": str(json_payload.get("category", "") or "").strip() or "other",
        "prompt": style_dna or style_description or legacy_prompt,
        "prefix": str(
            metadata.get("prefix", "") or json_payload.get("prefix", "") or ""
        ).strip(),
        "suffix": str(
            metadata.get("suffix", "") or json_payload.get("suffix", "") or ""
        ).strip(),
    }

    _append_lmstudio_output_log(
        data,
        settings,
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "model": lmstudio_model,
            "instruction": f"generate-style-from-image:variant-{used_variant_idx}",
            "editedPrompt": style.get("title", ""),
            "rawOutput": raw_output,
            "ok": True,
        },
    )

    return jsonify(
        {
            "ok": True,
            "style": style,
            "model": lmstudio_model,
            "autoDisconnectApplied": auto_disconnect_applied,
        }
    )


