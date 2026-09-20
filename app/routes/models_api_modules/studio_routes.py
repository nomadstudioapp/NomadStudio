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
from app.services import flow_engine
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
    _apply_think_trick,
    _auto_context_size,
    _clip_text,
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
    _strip_think_trick_preamble,
    logger,
    models_api_bp,
)

from app.routes.models_api_modules.chat_routes import (
    IDEOGRAM_COMPOSE_SCHEMA,
    _extract_json_payload_from_text,
    _extract_lmstudio_message_text,
    _extract_lmstudio_v1_message_text,
    _inject_no_think,
    _build_chat_payload,
    _call_lmstudio_v1_chat,
    _call_studio_llm,
    _call_studio_llm_json,
    _reasoning_level_from_request,
    _resolve_prompt_model,
    _resolve_vision_model,
    _resolve_explicit_vision_model,
)


# The flair dial used to be purely rhetorical: it wrote "Creativity / artistic
# flair intensity: 45/100" into the prompt and changed no sampling parameter,
# so with the configured temperature at 0.1 the model returned near-identical
# text no matter where the user put it. Measured on studio-enhance, same idea,
# three runs each (pairwise Jaccard distance between runs, 1.0 = nothing
# shared):
#
#     temperature 0.1 -> 0.05   (and erratic: a second batch gave 0.58)
#     temperature 0.3 -> 0.70
#     temperature 0.5 -> 0.70
#     temperature 0.8 -> 0.77
#     temperature 1.0 -> 0.82   but the subject starts drifting
#
# The ceiling is 0.9 rather than 1.0 because at 1.0 one run in three dropped
# the subject entirely — "a lighthouse keeper" came back as "a solitary figure
# ... in a weathered coastal cottage" — and the system prompt's first rule is
# to preserve the original subject.
_CREATIVITY_TEMPERATURE_FLOOR = 0.1
_CREATIVITY_TEMPERATURE_CEILING = 0.9


def _creativity_temperature(payload: dict[str, Any], fallback: float) -> float:
    """Sampling temperature for a creative step, from its flair value.

    Returns `fallback` — the globally configured temperature — when the caller
    sends no flair at all, so nothing changes for callers that never adopted
    the dial.
    """
    raw = payload.get("flair")
    if raw is None:
        return fallback
    try:
        flair = max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        return fallback
    span = _CREATIVITY_TEMPERATURE_CEILING - _CREATIVITY_TEMPERATURE_FLOOR
    return round(_CREATIVITY_TEMPERATURE_FLOOR + (flair / 100.0) * span, 2)


def _genre_hint_block(genre_id: str) -> str:
    """
    Build the system-prompt block for a selected story genre (thriller, adventure, ...).

    Looks up instructions/genres/<id>.json via flow_engine and returns its
    context_hint wrapped as a labeled block, or "" if no genre was selected /
    the id doesn't match any known genre.
    """
    genre_id = str(genre_id or "").strip()
    if not genre_id:
        return ""
    genre = flow_engine.get_genre_by_id(genre_id)
    if not genre or not genre.get("context_hint"):
        return ""
    return (
        f"\n\nGENRE — {genre.get('label', genre_id)}: "
        + str(genre["context_hint"])
    )



def _context_texts(payload: dict[str, Any]) -> list[str]:
    """Every string in a studio request that will travel to the model.

    Feeds _auto_context_size, which replaced the stored "Context" number the
    user used to set by hand. Reading the payload rather than naming fields per
    route means the accumulated previousVariations of a continuous-chat step
    are counted too, and that a route gaining a field does not silently start
    under-sizing its window.

    Data URLs are skipped: no studio route sends one, and a base64 image would
    swamp the estimate with bytes the text budget never sees.
    """
    texts: list[str] = []
    for value in payload.values():
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, list):
            texts.extend(v for v in value if isinstance(v, str))
    return [t for t in texts if not t.startswith("data:")]

@models_api_bp.post("/models/chat/studio-scenes")
def studio_scenes_prompt():
    """Generate N distinct scene prompts from a single idea via LM Studio.

    Request body:
        idea        (str)  – rough idea or concept
        n           (int)  – number of scenes to generate (1-100, default 6)
        level       (str)  – enhancement level: quick | style | scene | master
        flair       (int)  – 0-100 creativity intensity
        genre       (str)  – genre id from /api/flows/genres (optional, adds a tone hint)
        aspectRatio (str)  – e.g. "16:9" (optional, affects composition hints)
        aspectMode  (str)  – portrait | square | landscape (optional)

    Returns:
        { scenes: ["prompt1", ...], model, level, genre }
    """
    payload = request.get_json(silent=True) or {}
    idea = str(payload.get("idea", "")).strip()
    if not idea:
        return jsonify({"error": "idea is required"}), 400

    n = 6
    try:
        n = max(1, min(100, int(payload.get("n", 6))))
    except (TypeError, ValueError):
        n = 6

    level = str(payload.get("level", "scene")).strip()
    genre = str(payload.get("genre", "")).strip()
    payload_system_prompt_scenes = str(payload.get("systemPrompt", "")).strip()
    payload_user_prompt_scenes = str(payload.get("userPrompt", "")).strip()
    flair = 0
    try:
        flair = max(0, min(100, int(payload.get("flair", 0))))
    except (TypeError, ValueError):
        flair = 0

    _raw_aspect_ratio = str(payload.get("aspectRatio") or "").strip()
    import re as _re_local

    aspect_ratio = (
        _raw_aspect_ratio
        if _re_local.fullmatch(r"[0-9]{1,4}:[0-9]{1,4}", _raw_aspect_ratio)
        else ""
    )
    _raw_aspect_mode = str(payload.get("aspectMode") or "").strip().lower()
    aspect_mode = (
        _raw_aspect_mode
        if _raw_aspect_mode in ("portrait", "landscape", "square")
        else ""
    )

    _level_map = {
        "quick": "studioQuick",
        "style": "studioStyle",
        "scene": "studioScene",
        "master": "studioMaster",
    }
    level_key = _level_map.get(level, "studioScene")

    data = _ensure_registry()
    settings = data.setdefault("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    lmstudio_model = _resolve_prompt_model(settings)
    auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))
    base_context_size = _auto_context_size(*_context_texts(payload))
    lmstudio_temperature = _coerce_lmstudio_temperature(
        settings.get("lmStudioTemperature", DEFAULT_LMSTUDIO_TEMPERATURE)
    )
    # The creativity dial owns the temperature for this call when the
    # caller sets one; the global setting still governs every other step.
    lmstudio_temperature = _creativity_temperature(payload, lmstudio_temperature)

    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400
    if not lmstudio_model:
        return jsonify({"error": "LM Studio model is not selected"}), 400

    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Batch in chunks instead of asking for all N scenes in one shot — a
    # single call for N=100 produces a huge, single-turn output that tends to
    # truncate, drift off-instruction, and repeat itself toward the end.
    # Chunking keeps each call's output bounded and lets us feed forward a
    # summary of what's already been covered.
    CHUNK_SIZE = 12
    chunk_sizes: list[int] = []
    remaining = n
    while remaining > 0:
        take = min(CHUNK_SIZE, remaining)
        chunk_sizes.append(take)
        remaining -= take

    # Scale context: scenes need more room than single-prompt enhance
    _level_ctx_mult = {
        "studioQuick": 2.0,
        "studioStyle": 4.0,
        "studioScene": 6.0,
        "studioMaster": 8.0,
    }
    level_mult = _level_ctx_mult.get(level_key, 4.0)
    # Extra context for a bigger chunk (each scene adds ~300 tokens output)
    scene_extra = max(0, (chunk_sizes[0] - 4)) * 512
    raw_ctx = int(base_context_size * level_mult) + scene_extra
    context_size = max(LMSTUDIO_CONTEXT_SIZE_MIN, min(raw_ctx, 131072))

    idea_clipped = _clip_text(idea, max(400, min(4000, int(context_size * 0.3))))
    max_output_tokens = LMSTUDIO_MAX_OUTPUT_TOKENS

    # Build aspect hint for system prompt
    aspect_hint = ""
    if aspect_ratio and aspect_mode:
        aspect_hint = (
            f"\n\nEach scene prompt should be composed for {aspect_mode} orientation ({aspect_ratio} aspect ratio). "
            "Describe composition, framing, and depth of field accordingly."
        )

    # Flair hint
    flair_hint = ""
    if flair > 0:
        intensity_word = (
            "minimal"
            if flair <= 15
            else "moderate"
            if flair <= 35
            else "strong"
            if flair <= 60
            else "intense"
            if flair <= 85
            else "maximum"
        )
        flair_hint = (
            f"\n\nCreativity / artistic flair intensity: {flair}/100 ({intensity_word}). "
            "Let this influence how unexpected, stylized, or imaginative each scene description is."
        )

    genre_hint = _genre_hint_block(genre)

    # Every scene prompt opens with the exact same "anchor" clause (subject
    # appearance + art style) so the same character/style carries across the
    # whole set — without this, each scene was independently self-contained
    # and nothing tied them together visually.
    def _default_sys(count: int, anchor_pin: str | None, covered: list[str]) -> str:
        if not anchor_pin:
            body = (
                "You are a cinematic storyboard director and AI image prompt specialist. "
                "You will generate a series of distinct, visually rich image-generation prompts — one per scene — "
                "from a single central idea, all depicting the SAME subject and the SAME overall visual style so the "
                "whole set is visually consistent.\n\n"
                "Step 1 — decide on a fixed CHARACTER/STYLE ANCHOR: one dense clause covering the subject's "
                "apparent age (e.g. \"in their late 20s\", \"a child around 8\", \"elderly, 70s\"), build, hair, "
                "distinguishing features, outfit, and the overall art style/rendering. "
                "This exact clause will open EVERY scene prompt, unchanged.\n\n"
                f"Step 2 — write {count} scene prompts. Each one MUST:\n"
                "- Start with the anchor clause, verbatim, word for word identical every time.\n"
                "- Continue with scene-specific setting, action, lighting, mood, and composition — this is what "
                "varies between scenes.\n"
                "- Be fully self-contained and detailed enough to generate the image on its own.\n"
                "- Explore a different moment or angle of the idea — never repeat the same beat.\n"
                "- Be written in the comma-separated descriptive style used by Stable Diffusion and Flux image models.\n"
                "- Not be numbered in the prompt text itself.\n\n"
                "Output ONLY a valid JSON object, no explanation, no markdown:\n"
                '{"anchor": "<the exact anchor clause>", '
                '"scenes": ["<anchor clause>, <scene 1 details>", "<anchor clause>, <scene 2 details>", ...]}'
            )
        else:
            covered_block = (
                "\n\nBeats already covered — do not repeat them:\n- " + "\n- ".join(covered)
                if covered else ""
            )
            anchor_escaped = anchor_pin.replace('"', '\\"')
            body = (
                "You are continuing the same storyboard job. "
                "You MUST use exactly this character/style anchor clause, verbatim and unchanged, at the start of "
                f'every scene prompt: "{anchor_pin}"\n'
                "Do not modify, paraphrase, shorten, or drop any part of it.\n\n"
                f"Write {count} MORE scene prompts continuing the same central idea, each exploring a different, "
                "unused moment or angle." + covered_block + "\n\n"
                "Same rules as before: fully self-contained, comma-separated descriptive style, no numbering.\n"
                "Output ONLY a valid JSON object, no explanation, no markdown:\n"
                '{"anchor": "' + anchor_escaped + '", "scenes": ["<anchor clause>, <scene details>", ...]}'
            )
        return body + aspect_hint + flair_hint + genre_hint

    def _default_usr(count: int, anchor_pin: str | None) -> str:
        if not anchor_pin:
            return (
                f"Central idea:\n{idea_clipped}\n\n"
                f"Generate the character/style anchor and {count} distinct scene prompts as described."
            )
        return f"Central idea (for reference):\n{idea_clipped}\n\nGenerate {count} more scene prompts."

    # A caller-supplied systemPrompt/userPrompt (e.g. a flow JSON step's own
    # template) is honored as-is, per chunk, with just {{n}} swapped to the
    # chunk size — we don't rewrite custom prompts, only feed them in batches.
    def _build_messages(count: int, anchor_pin: str | None, covered: list[str]) -> list[dict[str, str]]:
        if payload_system_prompt_scenes or payload_user_prompt_scenes:
            sys_p = (payload_system_prompt_scenes or _default_sys(count, anchor_pin, covered)) \
                + aspect_hint + flair_hint + genre_hint
            usr_p = payload_user_prompt_scenes.replace("{{idea}}", idea_clipped).replace("{{n}}", str(count)) \
                if payload_user_prompt_scenes else _default_usr(count, anchor_pin)
        else:
            sys_p = _default_sys(count, anchor_pin, covered)
            usr_p = _default_usr(count, anchor_pin)
        return [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}]

    auto_disconnect_loaded = False
    unload_instance_id = ""
    auto_disconnect_applied = False
    all_scenes: list[str] = []
    anchor_pin: str | None = None
    covered_summaries: list[str] = []
    raw_outputs: list[str] = []

    # Schema-first attempt for one chunk, short timeout, falling back to the
    # native endpoint's own call unchanged on any failure (NomadStudio#3) —
    # same "try fast, fall back to what already worked" shape as
    # _call_studio_llm_json, just wired to this loop's own chunked/anchored
    # shape instead of a single call. Only used with the DEFAULT prompts: a
    # caller-supplied systemPrompt/userPrompt (a flow JSON's own template)
    # may ask for a different shape entirely (a bare array — see the
    # isinstance(parsed, list) handling below), and forcing this schema on
    # it would silently break those flows instead of the ones this fixes.
    def _scenes_chunk_raw_output(count: int, msgs: list[dict[str, str]]) -> str:
        if not (payload_system_prompt_scenes or payload_user_prompt_scenes):
            chunk_schema = {
                "type": "object",
                "properties": {
                    "anchor": {"type": "string"},
                    "scenes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": count,
                        "maxItems": count,
                    },
                },
                "required": ["anchor", "scenes"],
            }
            try:
                schema_payload = _build_chat_payload(
                    lmstudio_model, msgs, lmstudio_temperature, max_output_tokens
                )
                schema_payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "studio_scenes_chunk", "strict": True, "schema": chunk_schema},
                }
                response = http_json(
                    url=_lmstudio_chat_endpoint(lmstudio_url), gpu_category="lmstudio",
                    method="POST", payload=schema_payload, timeout=90,
                )
                answer, _source = _extract_lmstudio_message_text(response)
                if answer.strip():
                    return answer
                logger.warning(
                    "studio-scenes: schema-constrained chunk call returned nothing; "
                    "falling back to the native endpoint."
                )
            except Exception as exc:
                logger.warning(
                    "studio-scenes: schema-constrained chunk call failed (%s); "
                    "falling back to the native endpoint.", exc,
                )
        v1_response, _used_reasoning_level = _call_lmstudio_v1_chat(
            lmstudio_url,
            lmstudio_model,
            msgs[0]["content"],
            msgs[1]["content"],
            lmstudio_temperature,
            max_output_tokens,
            reasoning=reasoning_level,
            timeout=600,
        )
        return _extract_lmstudio_v1_message_text(v1_response)

    try:
        if auto_disconnect:
            auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                lmstudio_url, lmstudio_model, context_size
            )

        reasoning_level = _reasoning_level_from_request(payload)
        for chunk_count in chunk_sizes:
            messages = _build_messages(chunk_count, anchor_pin, covered_summaries)
            raw_output = _scenes_chunk_raw_output(chunk_count, messages)
            if not raw_output:
                break
            raw_outputs.append(raw_output)

            parsed = _extract_json_payload_from_text(raw_output)
            chunk_anchor = ""
            chunk_items: list[Any] = []
            if isinstance(parsed, dict):
                chunk_anchor = str(parsed.get("anchor", "")).strip()
                chunk_items = parsed.get("scenes") if isinstance(parsed.get("scenes"), list) else []
            elif isinstance(parsed, list):
                chunk_items = parsed  # caller-supplied prompt might still ask for a bare array

            if not chunk_items:
                from app.routes.models_api_shared import _extract_json_array_from_text as _extract_arr
                chunk_items = _extract_arr(raw_output)
                if len(chunk_items) == 1 and isinstance(chunk_items[0], dict):
                    _d = chunk_items[0]
                    _vals = [str(v).strip() for v in _d.values() if isinstance(v, str) and str(v).strip()]
                    if len(_vals) > 1:
                        chunk_items = _vals

            if not anchor_pin and chunk_anchor:
                anchor_pin = chunk_anchor

            for item in chunk_items:
                if isinstance(item, str):
                    text = _sanitize_lmstudio_edited_prompt(item)
                elif isinstance(item, dict):
                    text = ""
                    for key in ("prompt", "new_prompt", "scene", "text", "content"):
                        val = str(item.get(key, "")).strip()
                        if val:
                            text = _sanitize_lmstudio_edited_prompt(val)
                            break
                else:
                    text = ""
                if not text:
                    continue
                # Defensive: if the model dropped the anchor on this one entry,
                # prepend it so consistency holds even when the model slips.
                if anchor_pin and not text.lower().startswith(anchor_pin.lower()[:24]):
                    text = anchor_pin.rstrip(", ") + ", " + text
                all_scenes.append(_clip_text(text, 1800))
                covered_summaries.append(" ".join(text.split()[-14:]))

            if len(all_scenes) >= n:
                break

        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            auto_disconnect_applied = _lmstudio_unload_model(
                lmstudio_url, unload_instance_id
            )
    except Exception as exc:
        from app.routes.models_api_shared import logger as _logger

        _logger.exception(
            "LM Studio studio-scenes request failed for model '%s'", lmstudio_model
        )
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            _lmstudio_unload_model(lmstudio_url, unload_instance_id)
        return jsonify({"error": f"LM Studio request failed: {exc}"}), 502

    scenes = all_scenes[:n]
    if not scenes:
        return jsonify({"error": "LM Studio returned no valid scene prompts"}), 502

    from datetime import datetime as _dt, timezone as _tz

    _append_lmstudio_output_log(
        data,
        settings,
        {
            "at": _dt.now(_tz.utc).isoformat(),
            "model": lmstudio_model,
            "instruction": f"studio-scenes:n={n}:level={level_key}:genre={genre or 'none'}:chunks={len(chunk_sizes)}:reasoning={reasoning_level}",
            "editedPrompt": f"{len(scenes)} scenes generated (anchor: {bool(anchor_pin)})",
            "rawOutput": _clip_text("\n---\n".join(raw_outputs), 1400),
            "ok": bool(scenes),
        },
    )

    return jsonify(
        {
            "scenes": scenes,
            "model": lmstudio_model,
            "level": level_key,
            "n": n,
            "flair": flair,
            "genre": genre or None,
            "aspectRatio": aspect_ratio or None,
            "aspectMode": aspect_mode or None,
            "anchor": anchor_pin or None,
            "autoDisconnectApplied": auto_disconnect_applied,
        }
    )


# ---------------------------------------------------------------------------
# Studio Variations — fill [bracketed placeholders] in a template N times
# ---------------------------------------------------------------------------


@models_api_bp.post("/models/chat/studio-variations")
def studio_variations_prompt():
    """Generate N filled-in variations of a prompt template with [bracketed placeholders].

    Request body:
        template    (str)  – prompt with [bracket] placeholders
        n           (int)  – number of variations (1-20, default 4)
        level       (str)  – quick | style | scene | master
        flair       (int)  – 0-100 creativity
        systemPrompt (str) – optional system prompt override from flow JSON
        userPrompt  (str)  – optional user prompt template override from flow JSON

    Returns:
        { variations: ["prompt1", ...], model, level }
    """
    payload = request.get_json(silent=True) or {}
    template = str(payload.get("template", "")).strip()
    if not template:
        return jsonify({"error": "template is required"}), 400

    level = str(payload.get("level", "scene")).strip()
    n = 1
    payload_system_prompt = str(payload.get("systemPrompt", "")).strip()
    payload_user_prompt = str(payload.get("userPrompt", "")).strip()
    continuous_chat = bool(payload.get("continuousChat", False))
    previous_variations: list[str] = [
        str(v) for v in (payload.get("previousVariations") or []) if v
    ]
    continue_message = str(payload.get("continueMessage", "")).strip()
    flair = 0
    try:
        flair = max(0, min(100, int(payload.get("flair", 0))))
    except (TypeError, ValueError):
        flair = 0

    _level_map = {
        "quick": "studioQuick",
        "style": "studioStyle",
        "scene": "studioScene",
        "master": "studioMaster",
    }
    level_key = _level_map.get(level, "studioScene")

    data = _ensure_registry()
    settings = data.setdefault("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    lmstudio_model = _resolve_prompt_model(settings)
    auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))
    base_context_size = _auto_context_size(*_context_texts(payload))
    lmstudio_temperature = _coerce_lmstudio_temperature(
        settings.get("lmStudioTemperature", DEFAULT_LMSTUDIO_TEMPERATURE)
    )
    # The creativity dial owns the temperature for this call when the
    # caller sets one; the global setting still governs every other step.
    lmstudio_temperature = _creativity_temperature(payload, lmstudio_temperature)

    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400
    if not lmstudio_model:
        return jsonify({"error": "LM Studio model is not selected"}), 400

    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    _level_ctx_mult = {
        "studioQuick": 2.0,
        "studioStyle": 4.0,
        "studioScene": 6.0,
        "studioMaster": 8.0,
    }
    level_mult = _level_ctx_mult.get(level_key, 4.0)
    variation_extra = max(0, (n - 4)) * 512
    if continuous_chat:
        variation_extra += len(previous_variations) * 512
    raw_ctx = int(base_context_size * level_mult) + variation_extra
    context_size = max(LMSTUDIO_CONTEXT_SIZE_MIN, min(raw_ctx, 131072))

    template_clipped = _clip_text(template, max(400, min(4000, int(context_size * 0.4))))
    max_output_tokens = LMSTUDIO_MAX_OUTPUT_TOKENS

    flair_hint = ""
    if flair > 0:
        intensity_word = (
            "minimal" if flair <= 15
            else "moderate" if flair <= 35
            else "strong" if flair <= 60
            else "intense" if flair <= 85
            else "maximum"
        )
        flair_hint = (
            f"\n\nCreativity / artistic flair intensity: {flair}/100 ({intensity_word}). "
            "Let this shape how unexpected and imaginative the filled-in values are."
        )

    _variations_default_sys = (
        f"You are a creative AI image prompt specialist. "
        f"The user provides a prompt template with [bracketed placeholders]. "
        f"Your task is to generate {n} complete, distinct, and visually specific image-generation prompts "
        f"by filling in each [bracket] with different creative values.\n\n"
        "Rules:\n"
        "- Preserve the entire template structure and all text outside the brackets exactly as given.\n"
        "- Replace EVERY [bracketed placeholder] in each variation with a specific, vivid, and distinct value.\n"
        "- Each variation should feel visually different while sharing the overall style and mood of the template.\n"
        "- Write in the comma-separated descriptive style used by Stable Diffusion and Flux image generation models.\n"
        "- Do NOT include any explanation, markdown, or wrapper text.\n"
        f"Output ONLY a valid JSON array of exactly {n} strings. Each string is one complete filled-in prompt."
    )
    system_prompt = (
        payload_system_prompt.replace("{{n}}", str(n)) if payload_system_prompt else _variations_default_sys
    ) + flair_hint

    _variations_default_usr = (
        f"Template:\n{template_clipped}\n\n"
        f"Generate exactly {n} variations by filling in all [bracket] placeholders "
        f"with different creative values for each variation. Output as a JSON array of strings:\n"
        '["variation 1", "variation 2", ...]'
    )
    user_prompt = (
        payload_user_prompt
        .replace("{{template}}", template_clipped)
        .replace("{{n}}", str(n))
        if payload_user_prompt else _variations_default_usr
    )

    _default_continue = "Generate another variation. Use completely different values for every bracket."
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    if continuous_chat and previous_variations:
        _continue_msg = continue_message or _default_continue
        for prev_var in previous_variations:
            messages.append({"role": "assistant", "content": prev_var})
            messages.append({"role": "user", "content": _continue_msg})

    auto_disconnect_loaded = False
    unload_instance_id = ""
    auto_disconnect_applied = False

    try:
        if auto_disconnect:
            auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                lmstudio_url, lmstudio_model, context_size
            )

        raw_output, raw_source = _call_studio_llm(
            lmstudio_url,
            lmstudio_model,
            messages,
            lmstudio_temperature,
            max_output_tokens,
            reasoning=_reasoning_level_from_request(payload),
            timeout=600,
            label="studio-variations",
        )
    except Exception as exc:
        logger.exception(
            "LM Studio studio-variations request failed for model '%s'", lmstudio_model
        )
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            _lmstudio_unload_model(lmstudio_url, unload_instance_id)
        return jsonify({"error": f"LM Studio request failed: {exc}"}), 502

    if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
        auto_disconnect_applied = _lmstudio_unload_model(lmstudio_url, unload_instance_id)

    variation = raw_output.strip()

    if not variation:
        return jsonify(
            _reasoning_only_error(
                raw_source, max_output_tokens,
                "LM Studio did not return a variation",
            )
        ), 502

    _append_lmstudio_output_log(
        data,
        settings,
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "model": lmstudio_model,
            "instruction": f"studio-variations:level={level_key}",
            "editedPrompt": variation,
            "rawOutput": _clip_text(raw_output, 1400),
            "ok": True,
        },
    )

    return jsonify(
        {
            "variation": variation,
            "model": lmstudio_model,
            "level": level_key,
            "autoDisconnectApplied": auto_disconnect_applied,
        }
    )


# ---------------------------------------------------------------------------
# Studio Variations JSON — fill JSON variables N times into a prompt string
# ---------------------------------------------------------------------------


@models_api_bp.post("/models/chat/studio-variations-json")
def studio_variations_json_prompt():
    """Generate one filled-in prompt string from a JSON variables template.

    The LLM receives a JSON object where each key is a variable (e.g. subject,
    style, mood) and returns ONE creative image-generation prompt string that
    incorporates those variables. Called N times by the JS engine to get N
    distinct prompt variations.

    Request body:
        template         (dict) – JSON object of variable_name -> current_value
        systemPrompt     (str)  – optional override
        userPrompt       (str)  – optional override
        continuousChat   (bool) – pass previous variations as chat history
        previousVariations (list[str]) – previous prompt strings for diversity
        continueMessage  (str)  – message between continuous calls

    Returns:
        { variation: "...", model }
    """
    payload = request.get_json(silent=True) or {}
    template = payload.get("template", {})
    if not isinstance(template, dict) or not template:
        return jsonify({"error": "template must be a non-empty JSON object"}), 400

    payload_system_prompt = str(payload.get("systemPrompt", "")).strip()
    payload_user_prompt = str(payload.get("userPrompt", "")).strip()
    continuous_chat = bool(payload.get("continuousChat", False))
    previous_variations: list[str] = [
        str(v) for v in (payload.get("previousVariations") or []) if v
    ]
    continue_message = str(payload.get("continueMessage", "")).strip()

    data = _ensure_registry()
    settings = data.setdefault("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    lmstudio_model = _resolve_prompt_model(settings)
    auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))
    base_context_size = _auto_context_size(*_context_texts(payload))
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

    variation_extra = len(previous_variations) * 512 if continuous_chat else 0
    context_size = max(
        LMSTUDIO_CONTEXT_SIZE_MIN,
        min(int(base_context_size * 4.0) + variation_extra, 131072),
    )
    max_output_tokens = LMSTUDIO_MAX_OUTPUT_TOKENS

    import json as _json
    template_str = _json.dumps(template, indent=2, ensure_ascii=False)

    keys_listed = ", ".join(f'"{k}"' for k in template.keys())

    default_system = (
        "You are a creative AI image prompt specialist. "
        "The user provides a JSON object where each key is a visual variable "
        f"({keys_listed}). "
        "Your task is to generate ONE complete, vivid image-generation prompt string "
        "by choosing creative values for each variable and weaving them into a coherent scene.\n\n"
        "Rules:\n"
        "- Keep what every variable is ABOUT. If the subject is a climber, every "
        "variation is that climber: vary the framing, the moment, the angle and the "
        "supporting detail, not the subject itself.\n"
        "- NEVER just list the variables back. Restating them in order is not a "
        "prompt. Build a scene: add the camera position, what the subject is doing "
        "at this instant, textures, background depth, colour and atmosphere until "
        "it reads like a photograph someone took.\n"
        "- Aim for 50-80 words.\n"
        "- Return ONLY the final prompt string. No JSON, no labels, no explanations.\n"
        "- Write in the comma-separated descriptive style used by Stable Diffusion / Flux."
    )
    system_prompt = payload_system_prompt or default_system

    default_user = (
        f"Variables:\n{template_str}\n\n"
        "Generate one vivid image-generation prompt using these variables creatively. "
        "Return only the prompt string:"
    )
    user_prompt = (
        payload_user_prompt
        .replace("{{template}}", template_str)
        if payload_user_prompt else default_user
    )

    # "Use completely different values for every variable" is what this used to
    # say, and the model obeyed it exactly. Given a template about a woman
    # bouldering under a railway overpass, the second variation came back as a
    # man surfing an underwater coral reef among bioluminescent jellyfish, and
    # the third repeated that one word for word. Nothing of the user's template
    # survived, which is the opposite of what the flow's own card promises
    # ("the AI varies the fields directly").
    #
    # A variation set is only useful if the entries belong together, so the
    # instruction now bounds the range: same subject, same kind of place, same
    # style and mood — vary how it is seen and told. Measured over four
    # variations that took template retention from 1/3 to 4/4, with no exact
    # duplicates.
    #
    # Note this bound is NOT needed by the bracket-based sibling above: there
    # the system prompt already pins everything outside the [brackets], so the
    # range is defined by the template itself.
    _default_continue = (
        "Generate another variation of the SAME scene. Keep what every variable is "
        "about: the same subject, the same kind of place, the same style and mood. "
        "Change the framing, the angle, the moment and the supporting details, and "
        "do not repeat any previous wording."
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    if continuous_chat and previous_variations:
        _continue_msg = continue_message or _default_continue
        for prev_var in previous_variations:
            messages.append({"role": "assistant", "content": prev_var})
            messages.append({"role": "user", "content": _continue_msg})

    auto_disconnect_loaded = False
    unload_instance_id = ""
    auto_disconnect_applied = False

    try:
        if auto_disconnect:
            auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                lmstudio_url, lmstudio_model, context_size
            )
        raw_output, raw_source = _call_studio_llm(
            lmstudio_url,
            lmstudio_model,
            messages,
            lmstudio_temperature,
            max_output_tokens,
            reasoning=_reasoning_level_from_request(payload),
            timeout=600,
            label="studio-variations-json",
        )
    except Exception as exc:
        logger.exception(
            "LM Studio studio-variations-json request failed for model '%s'", lmstudio_model
        )
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            _lmstudio_unload_model(lmstudio_url, unload_instance_id)
        return jsonify({"error": f"LM Studio request failed: {exc}"}), 502

    if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
        auto_disconnect_applied = _lmstudio_unload_model(lmstudio_url, unload_instance_id)

    variation = raw_output.strip()
    if not variation:
        return jsonify(
            _reasoning_only_error(
                raw_source, max_output_tokens,
                "LM Studio did not return a variation",
            )
        ), 502

    _append_lmstudio_output_log(
        data,
        settings,
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "model": lmstudio_model,
            "instruction": "studio-variations-json",
            "editedPrompt": variation,
            "rawOutput": _clip_text(raw_output, 1400),
            "ok": True,
        },
    )

    return jsonify(
        {
            "variation": variation,
            "model": lmstudio_model,
            "autoDisconnectApplied": auto_disconnect_applied,
        }
    )


# ---------------------------------------------------------------------------
# Studio Templateize — Convert a finished prompt into a bracketed template
# ---------------------------------------------------------------------------


@models_api_bp.post("/models/chat/studio-templateize")
def studio_templateize_prompt():
    """Convert a finished image-generation prompt into a reusable [bracketed] template.

    Request body:
        prompt       (str) – complete finished prompt to templateize
        systemPrompt (str) – optional system prompt override from flow JSON
        userPrompt   (str) – optional user prompt template override from flow JSON

    Returns:
        { template: "...", model }
    """
    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    payload_system_prompt = str(payload.get("systemPrompt", "")).strip()
    payload_user_prompt = str(payload.get("userPrompt", "")).strip()

    data = _ensure_registry()
    settings = data.setdefault("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    lmstudio_model = _resolve_prompt_model(settings)
    auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))
    base_context_size = _auto_context_size(*_context_texts(payload))
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

    context_size = max(LMSTUDIO_CONTEXT_SIZE_MIN, min(int(base_context_size * 3.0), 131072))
    prompt_clipped = _clip_text(prompt, max(400, min(4000, int(context_size * 0.4))))

    # This prompt used to be rules only — a KEEP list and a REPLACE list — and it
    # under-bracketed badly. On a 9-sentence cyberpunk illustration prompt it
    # returned two brackets and copied the rest verbatim, and the clothing it
    # skipped was named in the REPLACE list, so it was not a coverage gap in the
    # rules. It under-brackets photographic prompts the same way (two brackets on
    # a lighthouse-keeper prompt, missing the storm and the jetty).
    #
    # The cause is the shape of the task. Asking for the template asks the model
    # to re-emit the whole paragraph with edits, and verbatim copying is the
    # cheapest path through that — it takes it after the first bracket or two.
    #
    # Writing more rules makes it worse, not better. A version with the categories
    # widened and "COVERAGE IS MANDATORY" spelled out returned *one* bracket.
    # Having the model list the variable spans as JSON and substituting them in
    # Python failed the other way: it marked whole sentences and ate the fixed
    # text. One worked example fixed it, measured on the same prompt at the
    # configured temperature of 0.1:
    #
    #   rules only    qwythos-9b  2, 2 brackets   qwen3.8-4b  6, 6
    #   with example  qwythos-9b  9, 10, 10       qwen3.8-4b  10, 8, 9
    #
    # The example is photographic while the failing prompt was a flat graphic
    # illustration, so it is not teaching one register. The regression that
    # matters is the opposite one — over-bracketing the fixed technical tail —
    # and it holds: on the lighthouse prompt this version brackets the subject,
    # garment, event and location while leaving "shot on 35mm with a raking cold
    # sidelight, heavy film grain, desaturated teal colour grade" untouched.
    #
    # The style rule below was added after recording the Variations tutorial with
    # the version above. On a comma-separated tag prompt ("…cinematic editorial
    # photography, shallow depth of field, photorealistic") the model bracketed
    # the style clauses too — [photography style], [camera technique], [quality
    # descriptor] — leaving a template with no fixed content at all. The three
    # variations that came back were a Greek marble statue, a cyberpunk samurai
    # and a 1950s diner waitress: unrelated images rather than variations, under
    # a caption promising "same structure".
    #
    # Prose prompts never showed it, which is why the earlier tests missed it,
    # and it is intermittent even on tag prompts, which is why one run is not
    # evidence. Counting whether the style words survive OUTSIDE the brackets,
    # six runs per prompt across three prompt shapes: 2 of 18 lost the style
    # before the rule, 0 of 18 after, on both models, with bracket coverage
    # unchanged (7-8 on the prompt that first exposed the under-bracketing).
    _default_sys = (
        "You are a prompt template designer for AI image generation.\n"
        "The user provides a complete, finished image-generation prompt.\n"
        "Your task is to convert it into a reusable template by replacing every "
        "variable content element with a [descriptive bracket label].\n\n"
        "The principle: WHAT is depicted is variable. HOW it is rendered is fixed.\n\n"
        "Rules:\n"
        "- REPLACE with [brackets] every concrete thing the image contains: the "
        "subject and their identity, physical features, hair, garments, "
        "accessories and props, the colour of any named object, the background "
        "or setting, expression, pose, action, and any distinct graphic element.\n"
        "- KEEP fixed the rendering technique only: medium and art style, camera "
        "angle, shot type, lens, lighting setup, film format, overall colour "
        "grade, mood, rendering quality, film grain. Note the difference — the "
        "colour grade of the whole image is fixed, but the colour of a jacket, "
        "of hair or of a backdrop is variable.\n"
        "- Bracket labels must be descriptive hints that guide future variations, "
        "not generic tags. Write [hair style / defining feature] not [hair]. "
        "Write [structured elegant clothing in a rich color] not [clothes]. "
        "Never append the rule category to the label.\n"
        "- NEVER put the style itself inside brackets. The words naming the "
        "medium, the camera work or the finish — \"cinematic editorial "
        "photography\", \"shallow depth of field\", \"photorealistic\", \"oil "
        "painting\", \"shot on 35mm\" — must survive as the literal words the "
        "user wrote. A label like [photography style], [camera technique] or "
        "[quality descriptor] is always wrong. That fixed tail is what makes "
        "every variation look like it belongs to the same set; bracket it and "
        "you get unrelated images instead of variations.\n"
        "- Preserve all punctuation, sentence structure, and fixed text exactly.\n\n"
        "Example.\n"
        "Input: A moody oil painting of an old fisherman mending a green net on a "
        "stone pier, wearing a patched wool sweater, a battered pipe in his "
        "teeth, with a red lighthouse behind him, painted in thick impasto "
        "strokes.\n"
        "Output: A moody oil painting of [subject / who they are] [action they "
        "are performing] on [surface or location they occupy], wearing [garment, "
        "material and colour], [held prop or accessory] in his teeth, with "
        "[background landmark and its colour] behind him, painted in thick "
        "impasto strokes.\n\n"
        "Note how every concrete element became a bracket and only the medium "
        "and the brushwork stayed fixed. Do the same for the user's prompt, "
        "however long it is. A long prompt yields many brackets — do not stop "
        "after the first two and copy the rest.\n\n"
        "Output ONLY the template string. No explanations, no quotes, no labels."
    )
    system_prompt = payload_system_prompt if payload_system_prompt else _default_sys

    _default_usr = (
        f"Convert this prompt into a reusable template with [bracketed placeholders] "
        f"for the variable elements:\n\n{prompt_clipped}"
    )
    user_prompt = (
        payload_user_prompt.replace("{{prompt}}", prompt_clipped)
        if payload_user_prompt else _default_usr
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

        raw_output, raw_source = _call_studio_llm(
            lmstudio_url,
            lmstudio_model,
            messages,
            lmstudio_temperature,
            LMSTUDIO_MAX_OUTPUT_TOKENS,
            reasoning=_reasoning_level_from_request(payload),
            timeout=120,
            label="studio-templateize",
        )
    except Exception as exc:
        logger.exception(
            "LM Studio studio-templateize request failed for model '%s'", lmstudio_model
        )
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            _lmstudio_unload_model(lmstudio_url, unload_instance_id)
        return jsonify({"error": f"LM Studio request failed: {exc}"}), 502

    if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
        auto_disconnect_applied = _lmstudio_unload_model(lmstudio_url, unload_instance_id)

    if not raw_output:
        # Say which kind of nothing this is. A reasoning-only response is a
        # token-budget problem the user can act on; the old flat message left
        # Generate dead with no explanation (OPENHIKER#99).
        return jsonify(
            _reasoning_only_error(
                raw_source, LMSTUDIO_MAX_OUTPUT_TOKENS,
                "LM Studio did not return a template",
            )
        ), 502

    _append_lmstudio_output_log(
        data,
        settings,
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "model": lmstudio_model,
            "instruction": "studio-templateize",
            "editedPrompt": raw_output,
            "rawOutput": _clip_text(raw_output, 1400),
            "ok": True,
        },
    )

    return jsonify(
        {
            "template": raw_output,
            "model": lmstudio_model,
            "autoDisconnectApplied": auto_disconnect_applied,
        }
    )


# ---------------------------------------------------------------------------
# Studio Enhance — New modal prompt enhancement levels
# ---------------------------------------------------------------------------

_VALID_STUDIO_LEVELS = {"studioQuick", "studioStyle", "studioScene", "studioMaster"}


@models_api_bp.post("/models/chat/studio-enhance")
def studio_enhance_prompt():
    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt", "")).strip()
    level = str(payload.get("level", "")).strip()
    flair = 0
    try:
        flair = max(0, min(100, int(payload.get("flair", 0))))
    except (TypeError, ValueError):
        flair = 0

    # Aspect ratio: sanitize to safe characters only (digits and colon, e.g. "2:3")
    _raw_aspect_ratio = str(payload.get("aspectRatio") or "").strip()
    aspect_ratio = (
        _raw_aspect_ratio
        if re.fullmatch(r"[0-9]{1,4}:[0-9]{1,4}", _raw_aspect_ratio)
        else ""
    )
    _raw_aspect_mode = str(payload.get("aspectMode") or "").strip().lower()
    aspect_mode = (
        _raw_aspect_mode
        if _raw_aspect_mode in ("portrait", "landscape", "square")
        else ""
    )

    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    # Map short level keys ("quick", "style", "scene", "master") to full keys
    _level_map = {
        "quick": "studioQuick",
        "style": "studioStyle",
        "scene": "studioScene",
        "master": "studioMaster",
    }
    level_key = _level_map.get(level, level)
    if level_key not in _VALID_STUDIO_LEVELS:
        return jsonify(
            {
                "error": f"Invalid level '{level}'. Must be one of: quick, style, scene, master"
            }
        ), 400

    data = _ensure_registry()
    settings = data.setdefault("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    lmstudio_model = _resolve_prompt_model(settings)
    auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))
    base_context_size = _auto_context_size(*_context_texts(payload))
    lmstudio_temperature = _coerce_lmstudio_temperature(
        settings.get("lmStudioTemperature", DEFAULT_LMSTUDIO_TEMPERATURE)
    )
    # The creativity dial owns the temperature for this call when the
    # caller sets one; the global setting still governs every other step.
    lmstudio_temperature = _creativity_temperature(payload, lmstudio_temperature)

    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400
    if not lmstudio_model:
        return jsonify({"error": "LM Studio model is not selected"}), 400

    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Scale context dynamically: longer prompts + deeper levels need more room.
    # Level multipliers: quick=x2, style=x4, scene=x6, master=x8
    # Master uses a higher ceiling (128 K) so very long compositions fit without clipping.
    _level_ctx_mult = {
        "studioQuick": 2.0,
        "studioStyle": 4.0,
        "studioScene": 6.0,
        "studioMaster": 8.0,
    }
    _level_ctx_ceil = {
        "studioQuick": 65535,
        "studioStyle": 65535,
        "studioScene": 65535,
        "studioMaster": 131072,
    }
    _level_prompt_max = {
        "studioQuick": 2000,
        "studioStyle": 4000,
        "studioScene": 6000,
        "studioMaster": 30000,
    }
    level_mult = _level_ctx_mult.get(level_key, 1.0)
    prompt_len = len(prompt)
    # Add extra context for long prompts: ~512 tokens per 400 chars beyond 200 chars baseline
    prompt_extra = max(0, (prompt_len - 200) // 400) * 512
    raw_ctx = int(base_context_size * level_mult) + prompt_extra
    ctx_ceil = _level_ctx_ceil.get(level_key, 65535)
    context_size = max(LMSTUDIO_CONTEXT_SIZE_MIN, min(raw_ctx, ctx_ceil))
    prompt_max_chars_ceil = _level_prompt_max.get(level_key, 6000)
    prompt_max_chars = max(400, min(prompt_max_chars_ceil, int(context_size * 0.6)))
    max_output_tokens = _apply_max_tokens_override(payload, LMSTUDIO_MAX_OUTPUT_TOKENS)
    prompt = _clip_text(prompt, prompt_max_chars)

    payload_system_prompt_enhance = str(payload.get("systemPrompt", "")).strip()
    if payload_system_prompt_enhance:
        # Caller supplied an explicit system prompt — use it directly, skip saved/variant logic
        system_prompt = payload_system_prompt_enhance
    else:
        studio_saved = settings.get("studioPrompts", {})
        saved_text = str(studio_saved.get(level_key, "")).strip()
        system_prompt = saved_text or DEFAULT_STUDIO_PROMPTS[level_key]

        variants_map = studio_saved.get("promptVariants", {})
        active_map = studio_saved.get("promptActiveVariants", {})
        active_id = str(active_map.get(level_key, "")).strip()
        if active_id and isinstance(variants_map.get(level_key), list):
            for variant in variants_map[level_key]:
                if isinstance(variant, dict) and str(variant.get("id", "")).strip() == active_id:
                    variant_text = str(variant.get("text", "")).strip()
                    if variant_text:
                        system_prompt = variant_text
                    break

    if flair > 0:
        system_prompt = (
            system_prompt + "\n\n" + _STUDIO_FLAIR_INSTRUCTION.format(flair_value=flair)
        )

    if aspect_ratio and aspect_mode:
        system_prompt = (
            system_prompt
            + "\n\n"
            + _STUDIO_ASPECT_INSTRUCTION.format(aspect_ratio=aspect_ratio, aspect_mode=aspect_mode)
        )

    reference_prompt = _clip_text(str(payload.get("referencePrompt", "")).strip(), 2000)
    if reference_prompt:
        system_prompt = (
            system_prompt
            + "\n\n"
            + _STUDIO_REFERENCE_INSTRUCTION.format(reference_prompt=reference_prompt)
        )

    think_mode = bool(payload.get("thinkMode", False))
    system_prompt = _apply_think_trick(system_prompt, think_mode)

    messages = [{"role": "user", "content": prompt}]
    auto_disconnect_loaded = False
    unload_instance_id = ""
    auto_disconnect_applied = False
    try:
        if auto_disconnect:
            auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                lmstudio_url, lmstudio_model, context_size
            )
        raw_output, raw_source = _call_studio_llm(
            lmstudio_url,
            lmstudio_model,
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            lmstudio_temperature,
            max_output_tokens,
            reasoning=_reasoning_level_from_request(payload),
            timeout=600,
            label="studio-enhance",
        )
    except Exception as exc:
        logger.exception(
            "LM Studio studio-enhance request failed for model '%s'", lmstudio_model
        )
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            _lmstudio_unload_model(lmstudio_url, unload_instance_id)
        return jsonify({"error": f"LM Studio request failed: {exc}"}), 502

    raw_output = _strip_think_trick_preamble(raw_output)
    enhanced_prompt = _sanitize_lmstudio_edited_prompt(raw_output)

    if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
        auto_disconnect_applied = _lmstudio_unload_model(lmstudio_url, unload_instance_id)

    if not enhanced_prompt:
        return jsonify(
            _reasoning_only_error(raw_source, max_output_tokens, "LM Studio returned an empty enhanced prompt")
        ), 502

    return jsonify(
        {
            "enhancedPrompt": enhanced_prompt,
            "model": lmstudio_model,
            "level": level_key,
            "flair": flair,
            "aspectRatio": aspect_ratio or None,
            "aspectMode": aspect_mode or None,
        }
    )


@models_api_bp.post("/models/chat/studio-story")
def studio_story_continue():
    """Generate the next scene prompt for a visual story via LM Studio.

    Request body:
        worldContext   (str)       – initial world / opening scene description
        storyHistory   (list[str]) – prompts of scenes already generated
        instruction    (str)       – "what happens next" (empty = first scene)
        level          (str)       – quick | style | scene | master
        flair          (int)       – 0-100 creativity
        genre          (str)       – genre id from /api/flows/genres (optional, adds a tone hint)

    Returns:
        { scene: "...", model, level, genre }
    """
    payload = request.get_json(silent=True) or {}
    world_context = str(payload.get("worldContext", "")).strip()
    if not world_context:
        return jsonify({"error": "worldContext is required"}), 400

    story_history: list[str] = []
    raw_history = payload.get("storyHistory")
    if isinstance(raw_history, list):
        story_history = [str(s) for s in raw_history if str(s).strip()]

    instruction = str(payload.get("instruction", "")).strip()
    level = str(payload.get("level", "scene")).strip()
    genre = str(payload.get("genre", "")).strip()
    payload_system_prompt = str(payload.get("systemPrompt", "")).strip()
    character_anchor = str(payload.get("characterAnchor", "")).strip()
    style_reference = _clip_text(str(payload.get("styleReference", "")).strip(), 1500)
    vision_context = _clip_text(str(payload.get("visionContext", "")).strip(), 1800)
    # Bounded narrative-continuity window (last 1-3 plot-summary sentences
    # from the story project JSON's narrative_thread — see
    # story_project_service.py / GET /api/stories/<id>/context) — separate
    # from story_history above, which is the last few raw image PROMPTS
    # (visual detail). This is plot language, not comma-separated visual
    # tags, and intentionally stays a small fixed window rather than growing
    # with the story.
    narrative_context = _clip_text(str(payload.get("narrativeContext", "")).strip(), 600)
    flair = 0
    try:
        flair = max(0, min(100, int(payload.get("flair", 0))))
    except (TypeError, ValueError):
        flair = 0

    scene_count = 1
    try:
        scene_count = int(payload.get("sceneCount", 1))
    except (TypeError, ValueError):
        scene_count = 1
    scene_count = max(1, min(20, scene_count))

    _level_map = {
        "quick": "studioQuick",
        "style": "studioStyle",
        "scene": "studioScene",
        "master": "studioMaster",
    }
    level_key = _level_map.get(level, "studioScene")

    data = _ensure_registry()
    settings = data.setdefault("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    lmstudio_model = _resolve_prompt_model(settings)
    auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))
    base_context_size = _auto_context_size(*_context_texts(payload))
    lmstudio_temperature = _coerce_lmstudio_temperature(
        settings.get("lmStudioTemperature", DEFAULT_LMSTUDIO_TEMPERATURE)
    )
    # The creativity dial owns the temperature for this call when the
    # caller sets one; the global setting still governs every other step.
    lmstudio_temperature = _creativity_temperature(payload, lmstudio_temperature)

    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400
    if not lmstudio_model:
        return jsonify({"error": "LM Studio model is not selected"}), 400

    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    _level_ctx_mult = {
        "studioQuick": 2.0,
        "studioStyle": 4.0,
        "studioScene": 6.0,
        "studioMaster": 8.0,
    }
    raw_ctx = int(base_context_size * _level_ctx_mult.get(level_key, 4.0))
    context_size = max(LMSTUDIO_CONTEXT_SIZE_MIN, min(raw_ctx, 131072))
    max_output_tokens = LMSTUDIO_MAX_OUTPUT_TOKENS

    world_clipped = _clip_text(world_context, max(200, min(1200, int(context_size * 0.25))))
    instruction_clipped = _clip_text(instruction, max(100, min(800, int(context_size * 0.15))))
    history_cap = max(1, min(len(story_history), 6))
    history_clipped = story_history[-history_cap:]

    flair_hint = ""
    if flair > 0:
        intensity_word = (
            "minimal" if flair <= 15
            else "moderate" if flair <= 35
            else "strong" if flair <= 60
            else "intense" if flair <= 85
            else "maximum"
        )
        flair_hint = (
            f"\n\nCreativity / artistic flair intensity: {flair}/100 ({intensity_word}). "
            "Let this shape how unexpected, stylized, or imaginative the scene is."
        )

    if scene_count > 1:
        _story_default_prompt = (
            "You are a cinematic story director for AI image generation. "
            "You receive the world context of an ongoing visual story and must write a sequence of "
            "consecutive scene prompts that continue it. "
            "Rules:\n"
            "- Scene 1 continues directly from the world context / previous scenes / narrative direction.\n"
            "- Each subsequent scene evolves naturally from the one before it — they are connected frames of the same story.\n"
            "- Maintain visual consistency across all scenes: preserve the same characters (including exact hairstyle, hair color, "
            "and hair length), art style, color palette, and setting elements.\n"
            "- Only evolve what the narrative direction says should change; keep everything else — especially hair and facial "
            "features — stable.\n"
            "- If the narrative direction describes movement, travel, or physical action (walking, running, turning, fighting, "
            "reacting, going from one place to another), depict the character actively performing that action — mid-stride, "
            "mid-turn, dynamic body language — never standing still or posing for the camera.\n"
            "- Avoid defaulting to generic passive framing like 'standing on/in/at a place'. Even when the direction gives no "
            "explicit action, ground the character in something specific they are doing in that moment — gripping a hilt, "
            "shielding their eyes, reaching toward something, mid-step, glancing over a shoulder — instead of a neutral pose. "
            "Only describe a still, deliberately composed stance if the story genuinely calls for a quiet or contemplative beat.\n"
            "- Each prompt must be fully self-contained and detailed enough to generate the image on its own.\n"
            "- Write in the comma-separated descriptive style used by Stable Diffusion and Flux image models.\n"
            "Output ONLY a valid JSON array with no markdown fences or extra commentary."
        )
    else:
        _story_default_prompt = (
            "You are a cinematic story director for AI image generation. "
            "You receive the world context of an ongoing visual story and must write the next single scene prompt. "
            "Rules:\n"
            "- The scene prompt must be fully self-contained and detailed enough to generate the image on its own.\n"
            "- Maintain visual consistency: preserve the same characters (including exact hairstyle, hair color, and hair "
            "length), art style, color palette, and setting elements.\n"
            "- Only evolve what the narrative direction says should change; keep everything else — especially hair and facial "
            "features — stable.\n"
            "- This applies just as strongly to the ENVIRONMENT as to the character: time of day, weather, light color/"
            "direction, and the general location must stay the same as the previous scene unless the narrative direction (or "
            "the plot summary of recent scenes) explicitly moves the story to a new place or a later moment. A character "
            "swimming away from a wreck, wading through water, or walking toward a landmark is still the SAME shot of the "
            "SAME moment continuing — do not silently jump from night to bright midday to golden sunset, or swap the "
            "background landmarks/vegetation/architecture, across consecutive scenes just because the character's pose or "
            "distance changed.\n"
            "- If the narrative direction describes movement, travel, or physical action (walking, running, turning, fighting, "
            "reacting, going from one place to another), depict the character actively performing that action — mid-stride, "
            "mid-turn, dynamic body language — never standing still or posing for the camera.\n"
            "- Avoid defaulting to generic passive framing like 'standing on/in/at a place'. Even when the direction gives no "
            "explicit action, ground the character in something specific they are doing in that moment — gripping a hilt, "
            "shielding their eyes, reaching toward something, mid-step, glancing over a shoulder — instead of a neutral pose. "
            "Only describe a still, deliberately composed stance if the story genuinely calls for a quiet or contemplative beat.\n"
            "- Write in the comma-separated descriptive style used by Stable Diffusion and Flux image models.\n"
            "- Also write a short narrative summary of this scene — one plain-language sentence describing what happens in "
            "story terms (plot/action), NOT the image-prompt style. E.g. \"Nomad reaches the clearing and finds the ruins\" "
            "— not comma-separated visual tags.\n"
            "Output ONLY a valid JSON object, no explanation, no markdown fences:\n"
            '{"narrative_summary": "<one-sentence plot summary>", "scene": "<the full image-generation prompt>"}'
        )
    system_prompt = (payload_system_prompt or _story_default_prompt) + flair_hint + _genre_hint_block(genre)

    # Character/style anchor: same mechanism as Scenes (studio-scenes) — a
    # fixed clause repeated verbatim in every scene so the same character
    # carries across the whole story, instead of relying on the model to
    # freely reconstruct consistency from history each turn.
    deriving_anchor = False
    if character_anchor:
        system_prompt = (
            system_prompt
            + '\n\nCHARACTER/STYLE ANCHOR — you MUST use this exact clause, verbatim and unchanged, to open every '
            'scene prompt: "' + character_anchor.replace('"', '\\"') + '"\n'
            "Do not modify, paraphrase, shorten, or drop any part of it. Everything else in the scene may evolve "
            "per the narrative direction."
        )
    elif scene_count == 1:
        deriving_anchor = True
        system_prompt = (
            system_prompt
            + "\n\nFor this turn only, ignore the earlier output-format instruction. First decide on a fixed "
            "CHARACTER/STYLE ANCHOR: one dense clause covering the subject's apparent age, build, hair, "
            "distinguishing features, outfit, and the overall art style/rendering. This exact clause will open this "
            "scene and every scene that follows in this story, unchanged.\n"
            "Output ONLY a valid JSON object, no explanation, no markdown:\n"
            '{"anchor": "<the exact anchor clause>", "narrative_summary": "<one-sentence plot summary of this scene>", '
            '"scene": "<anchor clause>, <rest of the scene prompt>"}'
        )

    if style_reference:
        system_prompt = (
            system_prompt
            + "\n\nSTYLE ANCHOR (extracted from a CivitAI generation — keep this as the constant visual foundation):\n"
            + style_reference
            + "\n\nAlways preserve the artistic style, quality tags, rendering keywords, and lighting language from the style anchor. "
            "Only the subject and composition should evolve per scene."
        )

    if vision_context:
        system_prompt = (
            system_prompt
            + "\n\nCHARACTER & ENVIRONMENT ANCHOR (vision analysis of the most recent generated image — keep these characters, "
            "their appearance, and this setting consistent unless the narrative direction explicitly changes them). "
            "Pay special attention to hair — hairstyle, hair color, and hair length must match this description exactly "
            "in every following scene unless the narrative direction explicitly says the character's hair changes "
            "(cut, dyed, wet, windblown is fine as a momentary state, but the base style/color/length must not drift):\n"
            + vision_context
        )

    if narrative_context:
        system_prompt = (
            system_prompt
            + "\n\nRECENT STORY BEATS (plot summary of the last few scenes, for narrative continuity — "
            "use this to know what just happened and where the story is headed, not for visual detail):\n"
            + narrative_context
        )

    # The character-anchor / style-reference / vision-anchor / narrative-beats
    # blocks above are all appended AFTER the base prompt's "Output ONLY a
    # valid JSON object" instruction — so on any turn where one or more of
    # them fire (i.e. every continuation turn, scene 2 onward), the JSON
    # format instruction is no longer the last thing the model reads. Local
    # models lean heavily on recency, so they'd drop the JSON wrapper and
    # just answer in plain prose — meaning narrative_summary (and anchor, on
    # the deriving turn) silently came back empty every time, even though
    # the scene text itself still looked fine (that part survives via the
    # raw-text fallback). Restate the exact required shape as the last thing
    # in the system prompt so it isn't buried under those extra blocks.
    if scene_count == 1:
        if deriving_anchor:
            _json_shape = '{"anchor": "<the exact anchor clause>", "narrative_summary": "<one-sentence plot summary of this scene>", "scene": "<anchor clause>, <rest of the scene prompt>"}'
        else:
            _json_shape = '{"narrative_summary": "<one-sentence plot summary>", "scene": "<the full image-generation prompt>"}'
        system_prompt = (
            system_prompt
            + "\n\nReminder — regardless of anything above, output ONLY a single valid JSON object, "
            "no explanation, no markdown fences, in exactly this shape:\n"
            + _json_shape
        )

    history_block = ""
    if history_clipped:
        history_block = "\n\nPrevious scenes (most recent last):\n" + "\n".join(
            f"Scene {i + 1}: {p}" for i, p in enumerate(history_clipped)
        )

    if scene_count > 1:
        _next_word = "next" if instruction_clipped else "opening"
        user_prompt = (
            f"World context:\n{world_clipped}"
            f"{history_block}\n\n"
            + (f"Narrative direction:\n{instruction_clipped}\n\n" if instruction_clipped else "")
            + f"Write exactly {scene_count} sequential {_next_word} scenes as a JSON array:\n"
            "[\n"
            "  {\n"
            '    "change_description": "what changed from the previous scene",\n'
            '    "new_prompt": "full self-contained prompt for this scene"\n'
            "  }\n"
            "]"
        )
    elif instruction_clipped:
        user_prompt = (
            f"World context:\n{world_clipped}"
            f"{history_block}\n\n"
            f"What happens next:\n{instruction_clipped}\n\n"
            "Write the next scene prompt:"
        )
    elif history_clipped or narrative_context:
        # Continuing an existing story with no fresh direction typed this
        # turn (multi-scene batch past its first scene, or the user just hit
        # send again) — was previously "Write the first scene prompt for
        # this world", which literally told the model to restart the story,
        # ignoring everything that already happened. That's what kept
        # stories stuck describing the same beat over and over instead of
        # moving past it: told to write "the first scene" while also being
        # shown history of a ship crash, the model kept re-describing the
        # crash rather than progressing beyond it.
        user_prompt = (
            f"World context:\n{world_clipped}"
            f"{history_block}\n\n"
            "No new direction was given this turn — continue the story on your own: "
            "move the plot forward from where the previous scene left off (do not just "
            "re-describe or embellish the same moment again). Write the next scene prompt:"
        )
    else:
        user_prompt = (
            f"World context:\n{world_clipped}"
            f"{history_block}\n\n"
            "Write the first scene prompt for this world:"
        )

    auto_disconnect_loaded = False
    unload_instance_id = None

    if auto_disconnect:
        auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(lmstudio_url, lmstudio_model)

    def _looks_like_unloaded_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "model is unloaded" in msg or "is unloaded" in msg

    raw_content = ""
    retried_after_forced_reload = False
    reasoning_level = _reasoning_level_from_request(payload)
    while True:
        try:
            v1_response, reasoning_level = _call_lmstudio_v1_chat(
                lmstudio_url,
                lmstudio_model,
                system_prompt,
                user_prompt,
                lmstudio_temperature,
                max_output_tokens,
                reasoning=reasoning_level,
                timeout=300,
            )
            raw_content = _extract_lmstudio_v1_message_text(v1_response).strip()
            # Some LM Studio / llama.cpp setups inline the reasoning as <think>...</think>
            # inside `content` instead of a separate `reasoning_content` field. Strip it —
            # otherwise stray "[" / "]" characters in the reasoning can corrupt JSON-array
            # parsing for multi-scene requests (sceneCount > 1).
            raw_content = re.sub(
                r"<think>[\s\S]*?</think>", "", raw_content, flags=re.IGNORECASE
            ).strip()
            # Unterminated <think> (truncated mid-reasoning, no closing tag) — drop
            # everything from that point on rather than feed reasoning text as if
            # it were the answer.
            if re.search(r"<think>", raw_content, flags=re.IGNORECASE):
                raw_content = re.split(r"<think>", raw_content, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            break
        except Exception as exc:
            # LM Studio can report a model as "loaded" (checked above) but have
            # actually evicted it in between — e.g. loading a vision model for
            # the Consistency toggle pushed it out of VRAM. Self-heal once by
            # forcing a real reload and retrying, instead of surfacing the
            # error to the user.
            if not retried_after_forced_reload and _looks_like_unloaded_error(exc):
                retried_after_forced_reload = True
                logger.warning(
                    "LM Studio reported '%s' unloaded mid-request — forcing reload and retrying once",
                    lmstudio_model,
                )
                loaded_now, forced_instance_id = _lmstudio_load_model(
                    lmstudio_url, lmstudio_model, force=True
                )
                if loaded_now and forced_instance_id:
                    auto_disconnect_loaded = True
                    unload_instance_id = forced_instance_id
                continue
            logger.exception(
                "LM Studio studio-story request failed for model '%s'", lmstudio_model
            )
            if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
                _lmstudio_unload_model(lmstudio_url, unload_instance_id)
            return jsonify({"error": f"LM Studio request failed: {exc}"}), 502

    if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
        _lmstudio_unload_model(lmstudio_url, unload_instance_id)

    if not raw_content:
        return jsonify({"error": "LM Studio returned an empty scene prompt"}), 502

    if scene_count > 1:
        items = _extract_json_array_from_text(raw_content)
        scenes: list[str] = []
        for item in items:
            if isinstance(item, dict):
                nxt = str(item.get("new_prompt", "") or "").strip()
            else:
                nxt = str(item or "").strip()
            if nxt:
                scenes.append(nxt)

        _append_lmstudio_output_log(
            data,
            settings,
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "model": lmstudio_model,
                "instruction": f"studio-story:sceneCount={scene_count}:level={level_key}:genre={genre or 'none'}:reasoning={reasoning_level}",
                "editedPrompt": f"{len(scenes)}/{scene_count} scenes parsed",
                "rawOutput": _clip_text(raw_content, 4000),
                "ok": bool(scenes),
            },
        )

        if not scenes:
            return jsonify({"error": "LM Studio returned no valid scenes"}), 502
        return jsonify(
            {
                "scenes": scenes,
                "scene": scenes[0],
                "requestedSceneCount": scene_count,
                "model": lmstudio_model,
                "level": level_key,
                "genre": genre or None,
            }
        )

    scene_text = raw_content
    resolved_anchor = character_anchor
    narrative_summary = ""
    # Every single-scene turn now asks for {"narrative_summary", "scene"}
    # (plus "anchor" on the turn that derives it) instead of plain text —
    # parse it the same way regardless of which of the two system prompts
    # was used above. If the model ignores the JSON instruction, scene_text
    # falls back to the raw text, narrative_summary stays empty (still
    # persisted as "" — see append_scene in story_project_service) and, on
    # the anchor-deriving turn, resolved_anchor also stays empty — no anchor
    # to pin on the *next* turn, but this turn's image still generates.
    parsed = _extract_json_payload_from_text(raw_content)
    if isinstance(parsed, dict):
        scene_from_json = str(parsed.get("scene", "")).strip()
        if scene_from_json:
            scene_text = scene_from_json
        narrative_summary = str(parsed.get("narrative_summary", "")).strip()
        if deriving_anchor:
            resolved_anchor = str(parsed.get("anchor", "")).strip()

    # Defensive: if the model dropped the anchor from this specific scene,
    # prepend it so consistency holds even when it slips.
    if resolved_anchor and not scene_text.lower().startswith(resolved_anchor.lower()[:24]):
        scene_text = resolved_anchor.rstrip(", ") + ", " + scene_text

    _append_lmstudio_output_log(
        data,
        settings,
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "model": lmstudio_model,
            "instruction": f"studio-story:single:level={level_key}:genre={genre or 'none'}:reasoning={reasoning_level}",
            "editedPrompt": _clip_text(scene_text, 400),
            "rawOutput": _clip_text(raw_content, 4000),
            "ok": True,
        },
    )

    return jsonify(
        {
            "scene": scene_text,
            "narrativeSummary": narrative_summary or None,
            "anchor": resolved_anchor or None,
            "model": lmstudio_model,
            "level": level_key,
            "genre": genre or None,
        }
    )


@models_api_bp.post("/models/chat/studio-ideogram")
def studio_ideogram_compose():
    """Compose an Ideogram JSON layout from text fragments using LM Studio."""
    payload = request.get_json(silent=True) or {}
    fragments = [str(f).strip() for f in payload.get("fragments", []) if str(f).strip()]
    level = str(payload.get("level", "scene")).strip()
    if level not in ("quick", "style", "scene", "master"):
        level = "scene"
    system_prompt = str(payload.get("systemPrompt", "")).strip()
    canvas_width = int(payload.get("canvasWidth", 1000))
    canvas_height = int(payload.get("canvasHeight", 1000))
    aspect_ratio = str(payload.get("aspectRatio", "1:1")).strip()
    reference_image_data_url = str(payload.get("referenceImageDataUrl", "")).strip()
    reference_type = str(payload.get("referenceType", "character")).strip()
    if reference_type not in ("character", "background", "style", "scene"):
        reference_type = "character"
    lettering_elements = payload.get("letteringElements")
    if not isinstance(lettering_elements, list):
        lettering_elements = []
    # Two-phase charref support:
    # visionOnly=true  → run vision pass only, return characterDescription (no compose)
    # characterDescription provided → skip vision pass, inject description directly
    vision_only = bool(payload.get("visionOnly", False))
    character_description_provided = str(payload.get("characterDescription", "")).strip()

    if not fragments and not vision_only:
        return jsonify({"error": "fragments is required"}), 400
    if not system_prompt and not vision_only:
        return jsonify({"error": "systemPrompt is required"}), 400

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

    # Analyze reference image using the vision model if provided.
    # If characterDescription is pre-supplied (two-phase charref flow), skip vision pass.
    reference_description = character_description_provided
    vision_model = _resolve_explicit_vision_model(settings)
    if not reference_description and reference_image_data_url and vision_model:
        ref_sys = _IDG_REF_SYSTEM_PROMPTS.get(reference_type, _IDG_REF_SYSTEM_PROMPTS["character"])
        try:
            image_mime, image_bytes = _parse_image_data_url(reference_image_data_url)
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
            image_url_value = normalized_data_url
            vision_messages: list[dict[str, Any]] = [
                {"role": "system", "content": ref_sys},
                {"role": "user", "content": [
                    {"type": "text", "text": "Describe this reference image as instructed."},
                    {"type": "image_url", "image_url": {"url": image_url_value}},
                ]},
            ]
            ref_raw, _ = _call_studio_llm(
                lmstudio_url,
                vision_model,
                vision_messages,
                lmstudio_temperature,
                max(600, min(2000, int(context_size * 0.45))),
                reasoning="off",
                timeout=120,
                label="studio-ideogram:reference",
            )
            reference_description = ref_raw.strip()
        except Exception:
            logger.exception("studio-ideogram: reference image analysis failed")

    # visionOnly mode: return character description without running the compose pass
    if vision_only:
        return jsonify({
            "characterDescription": reference_description,
            "referenceAnalyzed": bool(reference_description),
        })

    fragments_text = "; ".join(fragments)
    user_prompt = (
        f"Canvas: {canvas_width}×{canvas_height} (aspect ratio {aspect_ratio})\n\n"
        f"Composition fragments:\n{fragments_text}"
    )
    if reference_description:
        user_prompt += f"\n\n{reference_type.upper()} REFERENCE ANALYSIS:\n{reference_description}"
    if lettering_elements:
        user_prompt += (
            "\n\nLETTERING ELEMENTS (each has its own fixed 'text' and 'desc' — "
            "keep them separate in your output: 'text' is the literal word/phrase, "
            "copied verbatim into the output element's own 'text' field; 'desc' is "
            "ONLY the typographic/style description and must never repeat the word "
            "itself):\n"
            f"{json.dumps(lettering_elements, ensure_ascii=False)}"
        )

    max_output_tokens = _apply_max_tokens_override(payload, LMSTUDIO_MAX_OUTPUT_TOKENS)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    auto_disconnect_loaded = False
    unload_instance_id = ""
    auto_disconnect_applied = False
    response: dict[str, Any] = {}

    try:
        if auto_disconnect:
            auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                lmstudio_url, lmstudio_model, context_size
            )
        ideogram_json, raw_source, used_schema = _call_studio_llm_json(
            lmstudio_url,
            lmstudio_model,
            messages,
            lmstudio_temperature,
            max_output_tokens,
            IDEOGRAM_COMPOSE_SCHEMA,
            "ideogram_compose",
            reasoning=_reasoning_level_from_request(payload),
            timeout=300,
            label="studio-ideogram",
        )
    except Exception as exc:
        logger.exception("LM Studio studio-ideogram request failed for model '%s'", lmstudio_model)
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            _lmstudio_unload_model(lmstudio_url, unload_instance_id)
        return jsonify({"error": f"LM Studio request failed: {exc}"}), 502

    if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
        auto_disconnect_applied = _lmstudio_unload_model(lmstudio_url, unload_instance_id)

    if not isinstance(ideogram_json, dict):
        return jsonify(
            _reasoning_only_error(raw_source, max_output_tokens, "LM Studio returned invalid or empty Ideogram JSON")
        ), 502

    return jsonify({
        "ideogramJson": ideogram_json,
        "model": lmstudio_model,
        "level": level,
        "autoDisconnectApplied": auto_disconnect_applied,
        "referenceDescription": reference_description,
        "referenceAnalyzed": bool(reference_description),
        "usedSchema": used_schema,
    })


@models_api_bp.post("/models/chat/studio-ideogram-refine")
def studio_ideogram_refine():
    """Apply a natural-language change request to an existing Ideogram composition JSON."""
    payload = request.get_json(silent=True) or {}
    current_json = payload.get("currentJson")
    change_request = str(payload.get("changeRequest", "")).strip()
    system_prompt = str(payload.get("systemPrompt", "")).strip()

    if not current_json or not isinstance(current_json, dict):
        return jsonify({"error": "currentJson is required and must be an object"}), 400
    if not change_request:
        return jsonify({"error": "changeRequest is required"}), 400
    if not system_prompt:
        return jsonify({"error": "systemPrompt is required"}), 400

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

    current_json_text = json.dumps(current_json, ensure_ascii=False, indent=2)
    user_message = (
        f"Current composition JSON:\n{current_json_text}\n\n"
        f"Change request: {change_request}\n\n"
        f"Output the complete modified JSON with the requested change applied."
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    max_output_tokens = _apply_max_tokens_override(payload, LMSTUDIO_MAX_OUTPUT_TOKENS)

    auto_disconnect_loaded = False
    unload_instance_id = ""
    auto_disconnect_applied = False
    response: dict[str, Any] = {}

    try:
        if auto_disconnect:
            auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                lmstudio_url, lmstudio_model, context_size
            )
        ideogram_json, raw_source, used_schema = _call_studio_llm_json(
            lmstudio_url,
            lmstudio_model,
            messages,
            lmstudio_temperature,
            max_output_tokens,
            IDEOGRAM_COMPOSE_SCHEMA,
            "ideogram_compose",
            reasoning=_reasoning_level_from_request(payload),
            timeout=300,
            label="studio-ideogram-refine",
        )
    except Exception as exc:
        logger.exception("LM Studio studio-ideogram-refine request failed for model '%s'", lmstudio_model)
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            _lmstudio_unload_model(lmstudio_url, unload_instance_id)
        return jsonify({"error": f"LM Studio request failed: {exc}"}), 502

    if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
        auto_disconnect_applied = _lmstudio_unload_model(lmstudio_url, unload_instance_id)

    if not isinstance(ideogram_json, dict):
        return jsonify(
            _reasoning_only_error(
                raw_source, max_output_tokens, "LM Studio returned invalid or empty Ideogram JSON"
            )
        ), 502

    return jsonify({
        "ideogramJson": ideogram_json,
        "autoDisconnectApplied": auto_disconnect_applied,
        "usedSchema": used_schema,
    })


@models_api_bp.post("/models/chat/studio-ideogram-storyboard")
def studio_ideogram_storyboard():
    """Generate an Ideogram storyboard contact-sheet JSON from a subject and grid config."""
    payload = request.get_json(silent=True) or {}
    subject = str(payload.get("subject", "")).strip()
    grid_size = str(payload.get("gridSize", "2×3")).strip()
    system_prompt = str(payload.get("systemPrompt", "")).strip()

    if not subject:
        return jsonify({"error": "subject is required"}), 400
    if not system_prompt:
        return jsonify({"error": "systemPrompt is required"}), 400

    # Parse grid_size → COLS, ROWS  (accept × or x separator)
    _gs = grid_size.replace("×", "x").replace("X", "x").lower()
    _grid_parts = _gs.split("x")
    try:
        # "2×3" = matrix notation: 2 ROWS × 3 COLS (landscape contact sheet)
        _rows = int(_grid_parts[0].strip())
        _cols = int(_grid_parts[1].strip())
    except (IndexError, ValueError):
        _rows, _cols = 2, 3  # safe default

    _cols = max(1, min(4, _cols))
    _rows = max(1, min(4, _rows))
    _n_panels = _cols * _rows
    grid_label = f"{_cols}×{_rows}"

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

    # Build user message — subject + injected grid context at the end
    user_message = (
        f"Subject / story:\n{subject}\n\n"
        f"--- GRID CONFIGURATION (injected at runtime) ---\n"
        f"GRID_SIZE: {grid_label}\n"
        f"COLS: {_cols}\n"
        f"ROWS: {_rows}\n"
        f"PANELS: {_n_panels}\n"
        f"Generate exactly {_n_panels} panel elements — one per cell — covering all cells in reading order."
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    max_output_tokens = _apply_max_tokens_override(payload, LMSTUDIO_MAX_OUTPUT_TOKENS)

    auto_disconnect_loaded = False
    unload_instance_id = ""
    auto_disconnect_applied = False
    response: dict[str, Any] = {}

    try:
        if auto_disconnect:
            auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                lmstudio_url, lmstudio_model, context_size
            )
        ideogram_json, raw_source, used_schema = _call_studio_llm_json(
            lmstudio_url,
            lmstudio_model,
            messages,
            lmstudio_temperature,
            max_output_tokens,
            IDEOGRAM_COMPOSE_SCHEMA,
            "ideogram_compose",
            reasoning=_reasoning_level_from_request(payload),
            timeout=300,
            label="studio-ideogram-storyboard",
        )
    except Exception as exc:
        logger.exception(
            "LM Studio studio-ideogram-storyboard request failed for model '%s'", lmstudio_model
        )
        if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
            _lmstudio_unload_model(lmstudio_url, unload_instance_id)
        return jsonify({"error": f"LM Studio request failed: {exc}"}), 502

    if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
        auto_disconnect_applied = _lmstudio_unload_model(lmstudio_url, unload_instance_id)

    if not isinstance(ideogram_json, dict):
        return jsonify(
            _reasoning_only_error(
                raw_source, max_output_tokens, "LM Studio returned invalid or empty Ideogram JSON"
            )
        ), 502

    return jsonify({
        "ideogramJson": ideogram_json,
        "model": lmstudio_model,
        "gridSize": grid_label,
        "cols": _cols,
        "rows": _rows,
        "panels": _n_panels,
        "autoDisconnectApplied": auto_disconnect_applied,
        "usedSchema": used_schema,
    })


_IDG_REF_SYSTEM_PROMPTS: dict[str, str] = {
    "character": (
        "You are a character design analyst for AI image generation. "
        "Analyze this character reference image and produce an exhaustive, ready-to-use visual description.\n\n"
        "Describe in exact detail:\n"
        "1. BODY: build, height impression, proportions, posture, muscle definition\n"
        "2. FACE & COMPLEXION: face shape, skin tone and complexion quality (e.g. fair porcelain, warm olive, deep ebony, tanned), "
        "eyes (exact iris color, shape, lash length/thickness, expression), brows (shape, thickness, color), "
        "nose shape, lips (shape, fullness, natural color), jaw and chin, any marks, scars, or distinctive features\n"
        "3. MAKEUP: foundation/base coverage, eye makeup (eyeshadow color and technique, eyeliner style, mascara), "
        "brow grooming, lip color and finish (matte, gloss, nude, bold), blush/contour/highlight if visible — "
        "or state 'no visible makeup / natural look' if none\n"
        "4. HAIR: length, cut/style, texture, exact color with highlights, how it falls or is tied\n"
        "5. CLOTHING: every garment — name each piece, exact material (weathered leather, ripstop nylon…), "
        "exact color and tone (e.g. washed-out pale blue denim, deep burgundy velvet), fit, cut, visible wear, damage, stitching details\n"
        "6. FOOTWEAR: style, material, exact color, condition\n"
        "7. ACCESSORIES & EQUIPMENT: belts, holsters, bags, gloves, goggles, jewelry — every detail; "
        "weapons (type, material, color, condition, how carried or holstered)\n"
        "8. OVERALL RENDERING STYLE: photorealistic, stylized, painted, anime — note quality and finish\n\n"
        "Write as dense, comma-separated phrases in a single paragraph. "
        "Use precise, specific language — not 'brown pants' but 'loose-fit olive-brown cargo pants with reinforced knee patches and multiple side pockets'. "
        "Output ONLY the description text. No headers. No bullets. No JSON. No explanation."
    ),
    "background": (
        "You are a scene analysis expert for AI image generation. "
        "Analyze this background/environment reference image and describe it for scene composition.\n\n"
        "Include: setting type and location, architectural elements or natural features, ground surface and texture, "
        "sky or ceiling treatment, lighting conditions (direction, quality, color temperature), "
        "atmosphere and mood, color palette (dominant and accent colors), depth layers (foreground/mid/background), "
        "any distinctive objects or recurring visual motifs, weather or environmental effects.\n\n"
        "Write as a dense, evocative description in 3–5 sentences. "
        "Output ONLY the description. No headers. No bullets. No JSON."
    ),
    "scene": (
        "You are a scene analyst for AI image generation. "
        "Analyze this full scene image and produce an exhaustive, ready-to-use description of EVERY element in it.\n\n"
        "Describe in exact detail:\n"
        "1. SETTING & ENVIRONMENT: location type, architecture or natural features, ground surface and texture, "
        "sky or ceiling, horizon, depth layers (foreground/mid/background), any props or scene dressing\n"
        "2. CHARACTERS — describe EACH person or creature individually and exhaustively:\n"
        "   - Body: build, height impression, proportions, posture\n"
        "   - Face & complexion: face shape, skin tone (exact shade), eyes (color, shape), brows, nose, lips, jaw, "
        "any distinctive features, makeup if visible\n"
        "   - Hair: length, style, texture, exact color with highlights\n"
        "   - Clothing: every garment with exact material, exact color and tone, fit, cut, visible wear\n"
        "   - Footwear and accessories: style, material, exact color\n"
        "   - Pose, action, and position in frame\n"
        "   If there are multiple characters, give each one its own full treatment in sequence.\n"
        "3. OBJECTS & PROPS: every significant object — type, material, exact color, condition, position\n"
        "4. LIGHTING: sources (natural/artificial, position, quality), shadows, highlights, color temperature, contrast\n"
        "5. ATMOSPHERE & MOOD: time of day, weather, environmental effects (fog, rain, dust, smoke), overall feeling\n"
        "6. COLOR PALETTE: dominant colors, accent colors, tonal range\n"
        "7. COMPOSITION: framing, camera angle, depth of field, spatial relationships between subjects\n"
        "8. VISUAL STYLE: dominant art style or medium (photorealistic, concept art, anime, oil painting, cinematic…), "
        "rendering technique and level of detail, color treatment (palette, saturation, contrast, grading), "
        "lighting approach (hard/soft, dramatic/ambient, color temperature, accent colors), "
        "texture treatment (clean/painterly/grainy/cel-shaded), post-processing or filter style, "
        "any specific artistic movement, cultural reference, or cinematic influence\n\n"
        "Write as dense, comma-separated phrases organized by subject. "
        "Be exhaustive — do not skip any visible character, object, or environmental detail. "
        "Use precise, specific language — not 'blue jacket' but 'fitted royal-blue bomber jacket with silver zip and worn collar'. "
        "description text. No headers. No bullets. No JSON. No explanation."
    ),
}
