from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
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
    _clip_text,
    _coerce_context_size,
    _coerce_lmstudio_temperature,
    _describe_cache_get,
    _describe_cache_set,
    _ensure_registry,
    _extract_json_array_from_text,
    _lmstudio_chat_endpoint,
    _lmstudio_load_model,
    _lmstudio_rest_chat_endpoint,
    _lmstudio_unload_model,
    _normalize_lmstudio_conversation_messages,
    _parse_image_data_url,
    _safe_http_url,
    _save_registry,
    _sanitize_lmstudio_edited_prompt,
    logger,
    models_api_bp,
)


def _close_unbalanced_json(text: str) -> tuple[str, int] | None:
    """Close a JSON document whose final brackets are missing.

    Models emitting long nested JSON drop closing brackets — not from hitting
    the token ceiling (the responses come back with finish_reason "stop"), but
    from simply losing count. Measured on studio-ideogram: two of three
    answers ended in `}]}` where a valid one ends `}]}}`. Every byte before
    that was correct, and the whole answer was being discarded over one
    character.

    Only appends what is missing — never rewrites content. Returns the
    repaired text and how many brackets it took, or None when the text has no
    opening bracket or is already balanced, so callers can tell "nothing to
    repair" from "repaired".
    """
    stack: list[str] = []
    in_string = False
    escaped = False
    closer = {"{": "}", "[": "]"}

    for ch in text:
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in closer:
            stack.append(ch)
        elif ch in ("}", "]") and stack and closer[stack[-1]] == ch:
            stack.pop()

    if not stack:
        return None

    repaired = text
    if in_string:
        repaired += '"'
    # A truncated document often stops right after a comma, which is invalid
    # once the bracket lands behind it.
    repaired = repaired.rstrip()
    if repaired.endswith(","):
        repaired = repaired[:-1]
    return repaired + "".join(closer[ch] for ch in reversed(stack)), len(stack)


def _extract_json_payload_from_text(raw_text: str) -> dict[str, Any] | list[Any] | None:
    """Recover the JSON document a model meant to send.

    Scans every opening bracket and keeps the candidate that accounts for the
    most text, rather than the first one that happens to parse. That ordering
    matters: when a document is missing its final bracket the root fails to
    parse while an object nested inside it succeeds, so "first that parses"
    returns a fragment. On studio-ideogram that fragment was `style_description`
    — a perfectly valid dict with none of the keys the caller needed, which is
    what OPENHIKER#98 saw as "the model omitted compositional_deconstruction".

    Unbalanced documents are closed as a last resort and logged, since a model
    that keeps needing that is worth replacing and should stay visible.
    """
    text = str(raw_text or "").strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            return parsed
    except Exception:
        pass

    decoder = json.JSONDecoder()
    best: tuple[int, Any] | None = None      # (characters accounted for, value)
    best_repair: tuple[int, Any, int] | None = None  # (chars, value, added)

    for match in re.finditer(r"[\{\[]", text):
        chunk = text[match.start() :]
        try:
            parsed, consumed = decoder.raw_decode(chunk)
        except Exception:
            parsed, consumed = None, 0
        if isinstance(parsed, (dict, list)) and (best is None or consumed > best[0]):
            best = (consumed, parsed)

        if best_repair is not None and best_repair[0] >= len(chunk):
            continue
        attempt = _close_unbalanced_json(chunk)
        if attempt is None:
            continue
        repaired, brackets = attempt
        try:
            parsed = json.loads(repaired)
        except Exception:
            continue
        if isinstance(parsed, (dict, list)):
            best_repair = (len(chunk), parsed, brackets)

    # An intact parse is always preferred over a repaired one, unless the
    # repair recovers materially more of the answer — which is exactly the
    # missing-final-bracket case.
    if best is not None and (best_repair is None or best[0] >= best_repair[0]):
        return best[1]
    if best_repair is not None:
        logger.warning(
            "Recovered a JSON payload by closing %d missing bracket(s); "
            "the model returned an unbalanced document.",
            best_repair[2],
        )
        return best_repair[1]
    return None


def _extract_lmstudio_message_text(response: dict[str, Any]) -> tuple[str, str]:
    """Extract text from LM Studio/OpenAI-like chat responses.

    Returns a tuple of (text, source) where source is "content" or "".
    reasoning_content is intentionally ignored — it is internal chain-of-thought,
    not the final answer.  Models that only produce reasoning and no content have
    been asked to disable thinking via thinking:false in the request payload.
    """

    def _collect_text(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            text_chunks: list[str] = []
            for part in value:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type", "")).strip().lower()
                if part_type and part_type != "text":
                    continue
                text_part = str(part.get("text", "")).strip()
                if text_part:
                    text_chunks.append(text_part)
            return "\n".join(text_chunks).strip()
        return ""

    message = response.get("choices", [{}])[0].get("message", {})
    if not isinstance(message, dict):
        return "", ""

    content_text = _collect_text(message.get("content", ""))
    if content_text:
        return content_text, "content"

    # Detect reasoning-only response: model spent all tokens on chain-of-thought.
    reasoning_text = _collect_text(message.get("reasoning_content", ""))
    if reasoning_text:
        return "", "reasoning_only"

    return "", ""


_THINKING_BUDGET_TOKENS = 5000


def _inject_no_think(model: str, messages: list[dict[str, Any]], thinking: bool = False) -> list[dict[str, Any]]:
    """Prepend the /think or /no_think directive to the first user message for Qwen models.

    Qwen3 requires this directive in the user turn, not the system prompt, to actually
    toggle reasoning — the API-level thinking/enable_thinking payload fields alone are
    not enough for Qwen's chat template to engage chain-of-thought. This used to always
    inject /no_think regardless of `thinking`, which silently disabled reasoning even
    when the caller explicitly asked for it.
    If no user message exists, appends a standalone user message with just the directive.
    """
    if "qwen" not in model.lower():
        return messages
    directive = "/think" if thinking else "/no_think"
    result: list[dict[str, Any]] = []
    injected = False
    for msg in messages:
        if not injected and msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                new_content: Any = directive + "\r\n" + content
            elif isinstance(content, list):
                # Multipart content (e.g. vision) — prepend as a text part
                new_content = [{"type": "text", "text": directive}] + list(content)
            else:
                new_content = directive + "\r\n" + str(content)
            result.append({**msg, "content": new_content})
            injected = True
        else:
            result.append(msg)
    if not injected:
        result.append({"role": "user", "content": directive})
    return result


def _build_chat_payload(
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    thinking: bool = False,
) -> dict[str, Any]:
    """Build a chat-completions payload.

    ``thinking`` controls whether extended reasoning is enabled.
    Both ``thinking`` (LM Studio / Qwen3 legacy) and ``enable_thinking``
    (newer LM Studio format used by some reasoning models) are sent so that
    all model variants disable or enable chain-of-thought correctly.
    When enabled, a budget_tokens cap is applied to limit chain-of-thought length.
    Qwen models also receive /think or /no_think prepended to the first user
    message, matching `thinking` — the API-level fields alone don't reliably
    toggle Qwen3's chat template without this.
    """
    final_messages = _inject_no_think(model, messages, thinking=thinking)
    if "qwen" in model.lower():
        logger.warning(
            "[no_think debug] model=%s thinking=%s messages=%s",
            model,
            thinking,
            json.dumps(final_messages, ensure_ascii=False, default=str)[:2000],
        )
    payload: dict[str, Any] = {
        "model": model,
        "messages": final_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # Only send thinking/enable_thinking when actually requesting extended
    # reasoning. Some model/backend combos (e.g. certain Gemma GGUF quants
    # with flash attention) choke on these fields even when explicitly set
    # to false/False — presumably because their presence alone triggers a
    # different load/template codepath in LM Studio. Disabling thinking for
    # non-reasoning models is already handled via _inject_no_think() above
    # (Qwen's /no_think directive), so omitting the fields when off is safe.
    if thinking:
        payload["thinking"] = {"type": "enabled", "budget_tokens": _THINKING_BUDGET_TOKENS}
        payload["enable_thinking"] = True
        if "qwen" in model.lower():
            payload["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": True}
            }
    return payload


def _reasoning_level_from_request(payload: dict[str, Any]) -> str:
    """Resolve the reasoning level for LM Studio's native /api/v1/chat endpoint.

    Accepts an explicit ``reasoningLevel`` (off|low|medium|high|on) and falls back
    to the legacy boolean ``thinking`` flag (True -> "on", False -> "off") for
    callers that haven't adopted the graduated selector yet.
    """
    level = str(payload.get("reasoningLevel", "")).strip().lower()
    if level in ("off", "low", "medium", "high", "on"):
        return level
    return "on" if bool(payload.get("thinking", False)) else "off"


# Graduated levels aren't supported by every loaded model — LM Studio reports
# this via an explicit "not supported by model" error. Fall back one step
# toward "on" rather than failing the request outright.
#
# "off" belongs here too, and its absence used to fail hard: a model that can
# only reason answers the request with
#   "Reasoning setting 'off' is not supported by model '…'. Supported
#    settings: 'on'."
# and with no entry to fall back to, the call raised and the route returned
# 502. Measured on mistralai/ministral-3-14b-reasoning: 12 of 12 calls dead.
# The gap predates routing every studio call through this endpoint, but only
# showed up once "off" started being asked for everywhere.
#
# Falling back to "on" means those models reason whether we want it or not —
# that is their nature, and a slow answer beats no answer.
_REASONING_FALLBACK = {"off": "on", "low": "on", "medium": "on", "high": "on"}


def _extract_lmstudio_v1_message_text(response: dict[str, Any]) -> str:
    """Extract the final answer text from a native /api/v1/chat response.

    Skips 'reasoning' output items (chain-of-thought) and returns the first
    'message' item's content.
    """
    output = response.get("output")
    if not isinstance(output, list):
        return ""
    for item in output:
        if not isinstance(item, dict):
            continue
        if str(item.get("type", "")).strip().lower() == "message":
            content = item.get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def _call_lmstudio_v1_chat(
    lmstudio_url: str,
    model: str,
    system_prompt: str,
    user_input: str,
    temperature: float,
    max_tokens: int,
    reasoning: str = "off",
    timeout: int = 300,
) -> tuple[dict[str, Any], str]:
    """Call LM Studio's native /api/v1/chat endpoint with a reasoning level.

    Returns (response, level_actually_used) — the level can differ from the
    requested one when a graduated level got rejected and we fell back to "on".
    """

    def _payload(level: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "system_prompt": system_prompt,
            "input": user_input,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if level is not None:
            payload["reasoning"] = level
        return payload

    level: str | None = reasoning
    url = _lmstudio_rest_chat_endpoint(lmstudio_url)
    try:
        response = http_json(url=url, method="POST", payload=_payload(level), timeout=timeout, gpu_category="lmstudio")
    except RuntimeError as exc:
        exc_text = str(exc).lower()
        fallback = _REASONING_FALLBACK.get(level)
        if fallback and "not supported by model" in exc_text:
            level = fallback
            response = http_json(url=url, method="POST", payload=_payload(level), timeout=timeout, gpu_category="lmstudio")
        elif "does not expose reasoning configuration" in exc_text:
            # Plain non-reasoning models reject the "reasoning" field outright,
            # even at "off" — omit it entirely rather than fail the request.
            level = None
            response = http_json(url=url, method="POST", payload=_payload(level), timeout=timeout, gpu_category="lmstudio")
        else:
            raise
    return response, (level or "off")


# Older LM Studio builds have no /api/v1/chat at all. That was the only reason
# this fallback existed at first, and the list below was the whole test.
#
# It turned out to be too narrow. Some models simply cannot be driven through
# the native endpoint, and they fail in ways that look nothing like "endpoint
# missing". Measured on `mistralai/ministral-3-14b-reasoning` with an image:
#
#   reasoning="off"  -> 400 "Reasoning setting 'off' is not supported by model
#                       ... Supported settings: 'on'."   (handled: we retry "on")
#   reasoning="on"   -> 500 Jinja Exception: "After the optional system message,
#                       conversation roles must alternate user and assistant"
#
# Neither matches a marker, so the call died — even though the very same image
# and prompt work perfectly through /v1/chat/completions. A good vision model
# was unusable because of how we ask, not what it can do.
#
# So the rule is now the honest one: the native endpoint is an optimisation
# (real reasoning control, #103), not a requirement. If it fails for ANY
# reason, try the legacy path before giving up. The markers stay only to keep
# the log message accurate about which case we are in.
_NO_NATIVE_CHAT_MARKERS = ("404", "not found", "no such endpoint", "cannot post")


def _native_input_from_messages(messages: list[dict[str, Any]]) -> Any:
    """Translate OpenAI-style messages into the native endpoint's `input`.

    The native endpoint takes images too — it just spells the parts
    differently, and the shape isn't documented anywhere we had. Probing it
    until the validator stopped complaining gives:

        {"type": "text",  "content":  "..."}
        {"type": "image", "data_url": "data:image/png;base64,..."}

    against chat-completions' `{"type": "image_url", "image_url": {"url": …}}`.
    Verified end to end: a 128x128 red PNG sent this way came back described as
    "Red." So there is no reason to keep vision on a second endpoint.

    Returns a plain string when nothing but text is present, which is what the
    endpoint expects in the common case and keeps payloads readable in logs.
    """
    parts: list[dict[str, Any]] = []
    texts: list[str] = []
    has_image = False

    for message in messages:
        if str(message.get("role", "")).lower() == "system":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            if content.strip():
                parts.append({"type": "text", "content": content})
                texts.append(content)
            continue
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict):
                continue
            kind = str(part.get("type", "")).lower()
            if kind == "image_url":
                url = part.get("image_url")
                url = url.get("url", "") if isinstance(url, dict) else str(url or "")
                if url:
                    parts.append({"type": "image", "data_url": url})
                    has_image = True
            elif kind in ("text", "input_text"):
                text = str(part.get("text", "") or part.get("content", ""))
                if text.strip():
                    parts.append({"type": "text", "content": text})
                    texts.append(text)

    if not has_image:
        return " ".join(texts).strip()
    return parts


def _call_studio_llm(
    lmstudio_url: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    reasoning: str = "off",
    timeout: int = 120,
    label: str = "studio",
) -> tuple[str, str]:
    """Get one text answer from LM Studio with reasoning genuinely disabled.

    Returns (text, source) matching _extract_lmstudio_message_text, so callers
    keep their existing reasoning-only reporting.

    Prefers the native /api/v1/chat endpoint, whose ``reasoning`` parameter
    actually works. The legacy /v1/chat/completions path tries to suppress
    chain-of-thought by prepending Qwen's ``/no_think`` directive, and measuring
    it showed that does nothing: across 37 legacy calls spanning four models,
    not one came back with zero reasoning tokens (minimum 148, maximum 4662),
    while native calls at reasoning "off" reported exactly 0. Reasoning-distilled
    models ignore the directive entirely, and models whose name lacks "qwen"
    — gemma among them — never even receive it.

    That mattered beyond latency: when a model spends its whole answer on
    chain-of-thought, ``content`` comes back empty and the caller reports
    "LM Studio did not return …" with nothing to act on (OPENHIKER#99).

    Falls back to the legacy endpoint only when the native one is absent, so
    installs on older LM Studio keep working.
    """
    system_prompt = " ".join(
        str(m.get("content", "")) for m in messages
        if str(m.get("role", "")).lower() == "system"
        and isinstance(m.get("content"), str)
    ).strip()
    user_input = _native_input_from_messages(messages)

    try:
        response, _level = _call_lmstudio_v1_chat(
            lmstudio_url, model, system_prompt, user_input,
            temperature, max_tokens, reasoning=reasoning, timeout=timeout,
        )
        text = _extract_lmstudio_v1_message_text(response).strip()
        return text, ("content" if text else "")
    except Exception as exc:
        native_error = exc
        if any(marker in str(exc).lower() for marker in _NO_NATIVE_CHAT_MARKERS):
            logger.warning(
                "%s: native /api/v1/chat unavailable (%s); falling back to "
                "chat-completions, where reasoning cannot be reliably disabled.",
                label, exc,
            )
        else:
            logger.warning(
                "%s: model %r rejected the native /api/v1/chat call (%s); "
                "falling back to chat-completions, where reasoning cannot be "
                "reliably disabled.",
                label, model, exc,
            )

    try:
        response = http_json(
            url=_lmstudio_chat_endpoint(lmstudio_url), gpu_category="lmstudio",
            method="POST",
            payload=_build_chat_payload(model, messages, temperature, max_tokens),
            timeout=timeout,
        )
    except Exception as legacy_error:
        # Both paths failed. The native error is almost always the informative
        # one — it says *why* the model refused — so lead with it.
        raise RuntimeError(
            f"{native_error} (chat-completions also failed: {legacy_error})"
        ) from native_error

    answer, source = _extract_lmstudio_message_text(response)
    return answer.strip(), source


def _sanitize_lmstudio_favorite_models(
    values: Any, available_models: list[str] | None = None
) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    allowed = {
        str(item).strip() for item in (available_models or []) if str(item).strip()
    }
    for value in values if isinstance(values, list) else []:
        name = str(value).strip()
        if not name:
            continue
        if allowed and name not in allowed:
            continue
        if name in seen:
            continue
        seen.add(name)
        cleaned.append(name)
        if len(cleaned) >= 200:
            break
    return cleaned


def _resolve_prompt_model(settings: dict[str, Any]) -> str:
    prompt_model = str(settings.get("lmStudioPromptModel", "")).strip()
    legacy_model = str(settings.get("lmStudioModel", "")).strip()
    return prompt_model or legacy_model


def _resolve_vision_model(settings: dict[str, Any], prompt_model: str) -> str:
    vision_model = str(settings.get("lmStudioVisionModel", "")).strip()
    return vision_model or prompt_model


def _resolve_explicit_vision_model(settings: dict[str, Any]) -> str:
    vision_model = str(settings.get("lmStudioVisionModel", "")).strip()
    if vision_model:
        return vision_model

    vision_models = settings.get("lmStudioVisionModels", [])
    if isinstance(vision_models, list):
        for item in vision_models:
            name = str(item or "").strip()
            if name:
                return name
    return ""


def _chat_settings_response(settings: dict[str, Any]) -> dict[str, Any]:
    models = settings.get("lmStudioModels", [])
    vision_models = settings.get("lmStudioVisionModels", [])
    prompt_favorites = _sanitize_lmstudio_favorite_models(
        settings.get("lmStudioFavoriteModels", []), models
    )
    vision_favorites = _sanitize_lmstudio_favorite_models(
        settings.get("lmStudioVisionFavoriteModels", []), models
    )
    prompt_model = _resolve_prompt_model(settings)
    vision_model = _resolve_vision_model(settings, prompt_model)

    settings["lmStudioFavoriteModels"] = prompt_favorites
    settings["lmStudioVisionFavoriteModels"] = vision_favorites
    settings["lmStudioPromptModel"] = prompt_model
    settings["lmStudioVisionModel"] = vision_model
    settings["lmStudioModel"] = prompt_model

    return {
        "lmStudioApiUrl": settings.get("lmStudioApiUrl", DEFAULT_LMSTUDIO_URL),
        "lmStudioModel": prompt_model,
        "lmStudioPromptModel": prompt_model,
        "lmStudioVisionModel": vision_model,
        "lmStudioModels": models,
        "lmStudioVisionModels": vision_models,
        "lmStudioFavoriteModels": prompt_favorites,
        "lmStudioVisionFavoriteModels": vision_favorites,
        "lmStudioShowFavoritesOnly": bool(
            settings.get("lmStudioShowFavoritesOnly", False)
        ),
        "lmStudioVisionShowFavoritesOnly": bool(
            settings.get("lmStudioVisionShowFavoritesOnly", False)
        ),
        "lmStudioAutoDisconnect": bool(settings.get("lmStudioAutoDisconnect", False)),
        "lmStudioContextSize": _coerce_context_size(
            settings.get("lmStudioContextSize", DEFAULT_LMSTUDIO_CONTEXT_SIZE)
        ),
        "lmStudioTemperature": _coerce_lmstudio_temperature(
            settings.get("lmStudioTemperature", DEFAULT_LMSTUDIO_TEMPERATURE)
        ),
        "lmStudioOutputLog": settings.get("lmStudioOutputLog", []),
        "lmStudioThinkCompat": settings.get("lmStudioThinkCompat", {}),
    }


# In-process cache for the reachability ping. Every hard page navigation in
# this app re-runs nav_status.js from scratch (most in-app links use
# window.location.href, not the SPA router), so a naive ping fires a fresh
# GET /v1/models at LM Studio on every single page load. LM Studio's model
# list doesn't change second-to-second, so we coalesce ping calls behind a
# longer TTL, keyed by URL so switching LM Studio endpoints doesn't serve a
# stale result. Pass ?force=1 to bypass the cache (used for manual LED
# re-checks so a click always reflects LM Studio's current state).
_PING_CACHE: dict[str, dict[str, Any]] = {}
_PING_CACHE_TTL_SECONDS = 60.0


@models_api_bp.get("/models/chat/ping")
def ping_chat_service():
    """Lightweight reachability check — does NOT write to registry.

    Used by the nav LED so polling every 30 s does not trigger a full model
    list reload (which would be noisy and persist unwanted state). Results
    are cached in-process for a few seconds so bursts of callers (multiple
    LEDs, tabs, or SPA back/forward navigations) don't each fire a fresh
    GET /v1/models at LM Studio.
    """
    source = str(request.args.get("source", "unknown")).strip() or "unknown"
    referer = request.headers.get("Referer", "-")
    force = str(request.args.get("force", "")).strip() in {"1", "true", "yes"}

    data = _ensure_registry()
    settings = data.get("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    if not lmstudio_url:
        return jsonify({"ok": False, "error": "LM Studio URI is not configured"}), 200
    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200

    now = time.monotonic()
    cached = None if force else _PING_CACHE.get(lmstudio_url)
    if cached and (now - cached["ts"]) < _PING_CACHE_TTL_SECONDS:
        age = now - cached["ts"]
        logger.info(
            "lmstudio ping [CACHE HIT] source=%s referer=%s age=%.1fs",
            source, referer, age,
        )
        return jsonify(cached["response"])

    try:
        http_json(lmstudio_service.models_endpoint(lmstudio_url), timeout=5)
        response = {"ok": True, "lmStudioApiUrl": lmstudio_url}
    except Exception:
        response = {"ok": False, "error": "LM Studio unreachable"}

    logger.info(
        "lmstudio ping [NETWORK CALL] source=%s referer=%s ok=%s",
        source, referer, response.get("ok"),
    )

    _PING_CACHE[lmstudio_url] = {"ts": now, "response": response}
    return jsonify(response), 200


@models_api_bp.get("/models/chat/settings")
def get_models_chat_settings():
    data = _ensure_registry()
    settings = data.get("settings", {})
    return jsonify({"settings": _chat_settings_response(settings)})


@models_api_bp.patch("/models/chat/settings")
def update_models_chat_settings():
    payload = request.get_json(silent=True) or {}
    data = _ensure_registry()
    settings = data.setdefault("settings", {})

    if "lmStudioApiUrl" in payload:
        try:
            settings["lmStudioApiUrl"] = _safe_http_url(
                str(payload.get("lmStudioApiUrl", "")), "LM Studio"
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    if "lmStudioModel" in payload:
        settings["lmStudioPromptModel"] = str(payload.get("lmStudioModel", "")).strip()
    if "lmStudioPromptModel" in payload:
        settings["lmStudioPromptModel"] = str(
            payload.get("lmStudioPromptModel", "")
        ).strip()
    if "lmStudioVisionModel" in payload:
        settings["lmStudioVisionModel"] = str(
            payload.get("lmStudioVisionModel", "")
        ).strip()
    if "lmStudioFavoriteModels" in payload:
        settings["lmStudioFavoriteModels"] = _sanitize_lmstudio_favorite_models(
            payload.get("lmStudioFavoriteModels", []),
            settings.get("lmStudioModels", []),
        )
    if "lmStudioVisionFavoriteModels" in payload:
        settings["lmStudioVisionFavoriteModels"] = _sanitize_lmstudio_favorite_models(
            payload.get("lmStudioVisionFavoriteModels", []),
            settings.get("lmStudioModels", []),
        )
    if "lmStudioShowFavoritesOnly" in payload:
        settings["lmStudioShowFavoritesOnly"] = bool(
            payload.get("lmStudioShowFavoritesOnly")
        )
    if "lmStudioVisionShowFavoritesOnly" in payload:
        settings["lmStudioVisionShowFavoritesOnly"] = bool(
            payload.get("lmStudioVisionShowFavoritesOnly")
        )
    if "lmStudioAutoDisconnect" in payload:
        settings["lmStudioAutoDisconnect"] = bool(payload.get("lmStudioAutoDisconnect"))
    if "lmStudioContextSize" in payload:
        settings["lmStudioContextSize"] = _coerce_context_size(
            payload.get("lmStudioContextSize")
        )
    if "lmStudioTemperature" in payload:
        settings["lmStudioTemperature"] = _coerce_lmstudio_temperature(
            payload.get("lmStudioTemperature")
        )
    if "clearLmStudioOutputLog" in payload and bool(
        payload.get("clearLmStudioOutputLog")
    ):
        settings["lmStudioOutputLog"] = []

    prompt_model = _resolve_prompt_model(settings)
    settings["lmStudioPromptModel"] = prompt_model
    settings["lmStudioVisionModel"] = _resolve_vision_model(settings, prompt_model)
    settings["lmStudioModel"] = prompt_model

    _save_registry(data)
    return jsonify({"settings": _chat_settings_response(settings)})


def _response_has_reasoning(response: dict[str, Any]) -> bool:
    """True if the response's message carries any reasoning_content text.

    Unlike _extract_lmstudio_message_text (which only reports reasoning when
    content is otherwise empty — it's built to find the "reasoning ate the
    whole budget" failure), this checks unconditionally, used to tell "this
    model never reasons at all" apart from "this model reasoned here but
    still left room for a real answer".
    """
    message = response.get("choices", [{}])[0].get("message", {})
    if not isinstance(message, dict):
        return False
    value = message.get("reasoning_content", "")
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(
            isinstance(part, dict) and str(part.get("text", "")).strip()
            for part in value
        )
    return False


@models_api_bp.post("/models/chat/check-think-compatibility")
def check_think_compatibility():
    """Test how a model handles "don't think" (see issue #1: Qwen 3.6 35B
    ignores /no_think and enable_thinking:false, and can burn its whole token
    budget on reasoning_content without ever producing content) — and, if it
    passes that, whether it can reason at all.

    Two real requests against the model:
    1. thinking off + a moderately demanding task (same shape as the manual
       test that first found the bug) — if the model spends the whole budget
       reasoning and returns no content, it's "unsupported" (ignores the
       off-switch, the dangerous case) and step 2 is skipped.
    2. thinking on, trivial prompt — if reasoning_content never shows up even
       when explicitly asked to think, the model has no reasoning capability
       at all ("no_thinking" — not dangerous, just nothing to toggle). If it
       does show up, the model both reasons and respected the off-switch in
       step 1, so it's fully "supported".

    Result persisted per model (keyed by model id) in settings.lmStudioThinkCompat
    so the frontend doesn't have to re-run this on every render, and so newly
    added models start out unchecked instead of inheriting another model's
    verdict.
    """
    payload = request.get_json(silent=True) or {}
    data = _ensure_registry()
    settings = data.setdefault("settings", {})
    model = str(payload.get("model", "")).strip() or _resolve_prompt_model(settings)
    if not model:
        return jsonify({"error": "No model selected to check"}), 400

    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400
    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        off_response = http_json(
            _lmstudio_chat_endpoint(lmstudio_url), gpu_category="lmstudio",
            method="POST",
            payload=_build_chat_payload(
                model,
                [{"role": "user", "content": "Write a two paragraph story about a cat exploring a garden."}],
                0.7,
                500,
                thinking=False,
            ),
            timeout=120,
        )
    except Exception as exc:
        return jsonify({"error": f"LM Studio request failed: {exc}"}), 502

    raw_output, _raw_source = _extract_lmstudio_message_text(off_response)
    checked_at = datetime.now(timezone.utc).isoformat()

    if not raw_output:
        state = "unsupported"
    else:
        try:
            on_response = http_json(
                _lmstudio_chat_endpoint(lmstudio_url), gpu_category="lmstudio",
                method="POST",
                payload=_build_chat_payload(
                    model,
                    [{"role": "user", "content": "Say hello in one short sentence."}],
                    0.7,
                    300,
                    thinking=True,
                ),
                timeout=120,
            )
            state = "supported" if _response_has_reasoning(on_response) else "no_thinking"
        except Exception:
            # thinking-off already succeeded — treat the follow-up probe
            # failing as inconclusive rather than throwing the whole check
            # away; "supported" is the safer default (don't disable toggles
            # over a network hiccup on the second call).
            state = "supported"

    compat = settings.setdefault("lmStudioThinkCompat", {})
    compat[model] = {"state": state, "checkedAt": checked_at}
    _save_registry(data)

    return jsonify({"model": model, "state": state, "checkedAt": checked_at})


# ── Story-model benchmark (see issue #76 follow-up: "otro boton para que se
# ejecuten los benchmarks a modelos nuevos") ─────────────────────────────────
# Ports app/scripts/benchmark_story_models.py's mechanical test (same prompt,
# same 3-scene request) into a real endpoint, one model per call — same
# per-model, cancellable pattern as check-think-compatibility/Check All
# Pending, so a long benchmark run over many models doesn't turn into an
# unstoppable multi-hour blocking call. Unlike the standalone script (which
# only writes a Markdown report and leaves quality/consistency/instruction-
# following for a human to read and score by hand), this also runs an
# LLM-judge pass using the app's own configured Prompt LLM, so the whole
# thing writes straight into model_scores.json with no manual step.

_MODEL_SCORES_PATH = (
    Path(__file__).resolve().parents[2] / "static" / "data" / "model_scores.json"
)

_BENCH_WORLD_CONTEXT = (
    "a woman detective who looks like a young Angelina Jolie, 1990s style, "
    "standing at the edge of a lake in a London park at golden hour"
)
_BENCH_INSTRUCTION = "she starts walking along the lake, then exits the park"
_BENCH_SCENE_COUNT = 3


def _load_model_scores() -> dict[str, Any]:
    try:
        return json.loads(_MODEL_SCORES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"source": "", "note": "", "fastestDurationSec": None, "models": {}}


def _save_model_scores(data: dict[str, Any]) -> None:
    _MODEL_SCORES_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _benchmark_story_messages() -> list[dict[str, str]]:
    system_prompt = (
        "You are a cinematic story director for AI image generation. "
        "You receive the world context of an ongoing visual story and must write a sequence of "
        "consecutive scene prompts that continue it. "
        "Rules:\n"
        "- Scene 1 continues directly from the world context / previous scenes / narrative direction.\n"
        "- Each subsequent scene evolves naturally from the one before it — they are connected frames of the same story.\n"
        "- Maintain visual consistency across all scenes: preserve the same characters, art style, color palette, and setting elements.\n"
        "- Only evolve what the narrative direction says should change; keep everything else stable.\n"
        "- Each prompt must be fully self-contained and detailed enough to generate the image on its own.\n"
        "- Write in the comma-separated descriptive style used by Stable Diffusion and Flux image models.\n"
        "Output ONLY a valid JSON array with no markdown fences or extra commentary."
    )
    user_prompt = (
        f"World context:\n{_BENCH_WORLD_CONTEXT}\n\n"
        f"Narrative direction:\n{_BENCH_INSTRUCTION}\n\n"
        f"Write exactly {_BENCH_SCENE_COUNT} sequential next scenes as a JSON array:\n"
        "[\n"
        "  {\n"
        '    "change_description": "what changed from the previous scene",\n'
        '    "new_prompt": "full self-contained prompt for this scene"\n'
        "  }\n"
        "]"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _strip_think_tags(text: str) -> str:
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    if re.search(r"<think>", text, flags=re.IGNORECASE):
        text = re.split(r"<think>", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    return text


def _parse_benchmark_scenes(raw_content: str) -> list[str]:
    items = _extract_json_array_from_text(_strip_think_tags(raw_content))
    scenes: list[str] = []
    for item in items:
        nxt = str(item.get("new_prompt", "") if isinstance(item, dict) else item or "").strip()
        if nxt:
            scenes.append(nxt)
    return scenes


_JUDGE_RUBRIC = """You are scoring a text model's output from an automated benchmark, on a 1-10 scale for each metric below. Be a strict, consistent grader — most models should land in the 4-8 range; reserve 9-10 for genuinely excellent output and 1-3 for broken/off-task output.

Task the model was given: continue a visual story with {scene_count} sequential scene prompts, given a world context and a narrative direction, as a JSON array of {{change_description, new_prompt}} objects.

World context: {world_context}
Narrative direction: {instruction}

Model's raw output:
---
{raw_output}
---

It returned {scenes_returned}/{scenes_requested} valid scenes in {duration:.1f}s (fastest model so far: {fastest:.1f}s, slowest so far: {slowest:.1f}s).

Score these 5 metrics (integers 1-10):
- reliability: did it return well-formed JSON with the requested scene count, no garbage/errors?
- speed: how fast, relative to the fastest ({fastest:.1f}s) and slowest ({slowest:.1f}s) models seen so far — faster is a higher score.
- quality: how well-written and visually specific are the prompts (concrete detail, image-generation-ready phrasing)?
- consistency: do characters/style/setting stay consistent across the scenes?
- instructionFollowing: does it actually follow the narrative direction without ignoring it or wandering off-task?

Output ONLY a JSON object, no markdown fences, no commentary:
{{"reliability": N, "speed": N, "quality": N, "consistency": N, "instructionFollowing": N}}"""


@models_api_bp.get("/models/chat/benchmark-pending")
def list_benchmark_pending_models():
    """Models LM Studio currently has that aren't in model_scores.json yet —
    what the "Benchmark New Models" button has left to do. Embedding models
    are filtered out heuristically (id contains "embed") since the story
    benchmark prompt is meaningless for them."""
    data = _ensure_registry()
    settings = data.get("settings", {})
    lm_models = settings.get("lmStudioModels", [])
    scores = _load_model_scores()
    scored = set(scores.get("models", {}).keys())
    pending = [
        m for m in lm_models
        if m not in scored and "embed" not in m.lower()
    ]
    return jsonify({"pending": pending, "totalModels": len(lm_models), "scoredModels": len(scored)})


@models_api_bp.post("/models/chat/benchmark-model")
def benchmark_model():
    """Run the story benchmark against one model and, if it produced usable
    output, judge it with the app's own Prompt LLM and write the result into
    model_scores.json. One model per call — see the module comment above."""
    payload = request.get_json(silent=True) or {}
    model = str(payload.get("model", "")).strip()
    if not model:
        return jsonify({"error": "model is required"}), 400

    data = _ensure_registry()
    settings = data.get("settings", {})
    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400
    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    start = time.monotonic()
    try:
        response = http_json(
            _lmstudio_chat_endpoint(lmstudio_url), gpu_category="lmstudio",
            method="POST",
            payload=_build_chat_payload(model, _benchmark_story_messages(), 0.7, 1600, thinking=False),
            timeout=180,
        )
    except Exception as exc:
        return jsonify({"model": model, "ok": False, "error": f"LM Studio request failed: {exc}"}), 200
    duration = round(time.monotonic() - start, 2)

    raw_output, _raw_source = _extract_lmstudio_message_text(response)
    scenes = _parse_benchmark_scenes(raw_output) if raw_output else []
    if not scenes:
        return jsonify({
            "model": model, "ok": False, "durationSec": duration,
            "error": "No valid scenes returned", "rawOutput": _clip_text(raw_output, 800),
        }), 200

    scores = _load_model_scores()
    existing = [v.get("durationSec") for v in scores.get("models", {}).values() if v.get("durationSec")]
    fastest = min([duration] + existing) if existing else duration
    slowest = max([duration] + existing) if existing else duration

    judge_prompt = _JUDGE_RUBRIC.format(
        scene_count=_BENCH_SCENE_COUNT,
        world_context=_BENCH_WORLD_CONTEXT,
        instruction=_BENCH_INSTRUCTION,
        raw_output=_clip_text(raw_output, 3000),
        scenes_returned=len(scenes),
        scenes_requested=_BENCH_SCENE_COUNT,
        duration=duration,
        fastest=fastest,
        slowest=slowest,
    )
    judge_model = _resolve_prompt_model(settings)
    if not judge_model:
        return jsonify({
            "model": model, "ok": False, "durationSec": duration,
            "error": "No Prompt LLM configured to judge the output",
        }), 200
    try:
        judge_response = http_json(
            _lmstudio_chat_endpoint(lmstudio_url), gpu_category="lmstudio",
            method="POST",
            # Generous budget: the judge model is whatever the app's Prompt
            # LLM happens to be, which can itself be a reasoning model that
            # ignores thinking:false (see issue #1) — found live scoring
            # qwythos-9b-claude-mythos-5-1m with its own 300-token judge
            # budget, which mostly went to the judge's own hidden reasoning,
            # leaving it too little room to write real JSON scores and
            # producing garbage/unfairly-low results.
            payload=_build_chat_payload(
                judge_model, [{"role": "user", "content": judge_prompt}], 0.2, 900, thinking=False
            ),
            timeout=120,
        )
    except Exception as exc:
        return jsonify({
            "model": model, "ok": False, "durationSec": duration,
            "error": f"Judge model request failed: {exc}",
        }), 200

    judge_raw, judge_source = _extract_lmstudio_message_text(judge_response)
    judge_json = _extract_json_payload_from_text(judge_raw) if judge_raw else None
    if not isinstance(judge_json, dict):
        error_msg = (
            f"Judge model ({judge_model}) spent its whole budget on reasoning and never wrote scores."
            if judge_source == "reasoning_only"
            else "Judge model returned invalid JSON"
        )
        return jsonify({
            "model": model, "ok": False, "durationSec": duration,
            "error": error_msg, "rawOutput": _clip_text(judge_raw, 400),
        }), 200

    def _clamp_score(value: Any) -> float:
        try:
            return max(1.0, min(10.0, float(value)))
        except (TypeError, ValueError):
            return 1.0

    metrics = {
        key: _clamp_score(judge_json.get(key))
        for key in ("reliability", "speed", "quality", "consistency", "instructionFollowing")
    }
    average = round(sum(metrics.values()) / len(metrics), 2)

    entry = {"average": average, "durationSec": duration, **metrics}
    scores.setdefault("models", {})[model] = entry
    if not scores.get("fastestDurationSec") or duration < scores["fastestDurationSec"]:
        scores["fastestDurationSec"] = duration
    _save_model_scores(scores)

    return jsonify({"model": model, "ok": True, "entry": entry})


@models_api_bp.post("/models/chat/models/load")
def load_models_chat_models():
    payload = request.get_json(silent=True) or {}
    data = _ensure_registry()
    settings = data.setdefault("settings", {})

    input_url = (
        str(payload.get("lmStudioApiUrl", "")).strip()
        or str(settings.get("lmStudioApiUrl", "")).strip()
    )
    if not input_url:
        return jsonify({"error": "LM Studio URI is required"}), 400

    try:
        lmstudio_url = _safe_http_url(input_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        models = lmstudio_service.list_models(lmstudio_url)
    except Exception as exc:
        logger.exception("Failed loading models from LM Studio URL '%s'", lmstudio_url)
        return jsonify({"error": f"Failed loading models from LM Studio: {exc}"}), 502

    model_ids = sorted(
        {
            str(item.get("id", "")).strip()
            for item in models
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        }
    )
    vision_model_ids = sorted(
        {
            str(item.get("id", "")).strip()
            for item in models
            if isinstance(item, dict)
            and str(item.get("id", "")).strip()
            and lmstudio_service.model_supports_vision(item)
        }
    )

    settings["lmStudioApiUrl"] = lmstudio_url
    settings["lmStudioModels"] = model_ids
    settings["lmStudioVisionModels"] = vision_model_ids
    settings["lmStudioFavoriteModels"] = _sanitize_lmstudio_favorite_models(
        settings.get("lmStudioFavoriteModels", []),
        model_ids,
    )
    settings["lmStudioVisionFavoriteModels"] = _sanitize_lmstudio_favorite_models(
        settings.get("lmStudioVisionFavoriteModels", []),
        model_ids,
    )
    current_prompt_model = _resolve_prompt_model(settings)
    if model_ids and current_prompt_model not in model_ids:
        settings["lmStudioPromptModel"] = model_ids[0]

    current_prompt_model = _resolve_prompt_model(settings)
    current_vision_model = str(settings.get("lmStudioVisionModel", "")).strip()
    if model_ids and current_vision_model not in model_ids:
        if vision_model_ids:
            settings["lmStudioVisionModel"] = vision_model_ids[0]
        else:
            settings["lmStudioVisionModel"] = current_prompt_model

    settings["lmStudioModel"] = _resolve_prompt_model(settings)

    _save_registry(data)
    return jsonify(
        {
            "models": model_ids,
            "visionModels": vision_model_ids,
            "settings": _chat_settings_response(settings),
        }
    )


