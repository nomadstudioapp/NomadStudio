from __future__ import annotations

import base64
import hashlib
import re
import time
from typing import Any

from app.config import (
    DEFAULT_LMSTUDIO_CONTEXT_SIZE,
    DEFAULT_LMSTUDIO_TEMPERATURE,
    LMSTUDIO_MAX_OUTPUT_TOKENS,
)
from app.services import lmstudio_service
from app.services.http_client import http_json


def _parse_image_data_url(data_url: str) -> tuple[str, bytes]:
    text = str(data_url or "").strip()
    match = re.match(
        r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise ValueError("imageDataUrl must be a valid base64 data URL")
    mime = match.group(1).lower()
    raw_b64 = re.sub(r"\s+", "", match.group(2))
    try:
        raw_bytes = base64.b64decode(raw_b64, validate=True)
    except Exception as exc:
        raise ValueError(f"Invalid base64 image data: {exc}") from exc
    return mime, raw_bytes


def _coerce_mode(value: Any) -> str:
    mode = str(value or "full").strip().lower()
    if mode in {"full", "scene", "style"}:
        return mode
    return "full"


def _coerce_format(value: Any) -> str:
    output_format = str(value or "text").strip().lower()
    if output_format in {"text", "json"}:
        return output_format
    return "text"


def _coerce_context_size(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        return DEFAULT_LMSTUDIO_CONTEXT_SIZE
    return max(1024, min(262144, parsed))


def _coerce_temperature(value: Any) -> float:
    try:
        parsed = float(value)
    except Exception:
        return DEFAULT_LMSTUDIO_TEMPERATURE
    return max(0.0, min(2.0, parsed))


def _extract_lmstudio_message_text(response: dict[str, Any]) -> tuple[str, str]:
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

    reasoning_text = _collect_text(message.get("reasoning_content", ""))
    if reasoning_text:
        return "", "reasoning_only"

    return "", ""


def _build_chat_payload(
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": False,
        "enable_thinking": False,
    }


def _resolve_prompt_selection(
    mode: str, output_format: str, custom_prompts: dict[str, Any]
) -> tuple[str, str, dict[str, Any]]:
    prompt_meta: dict[str, Any] = {
        "mode": mode,
        "outputFormat": output_format,
        "source": "default",
        "key": "",
        "activeVariantId": "",
    }

    if mode == "style":
        if output_format == "json":
            return (
                "Analyze visual style only. Return minified JSON only with keys: "
                "style_family, medium, palette, lighting_tone, composition_language, texture_treatment, notes.",
                "Describe the visual style as JSON.",
                prompt_meta,
            )
        custom_style = str(custom_prompts.get("describeStyle", "")).strip()
        if custom_style:
            prompt_meta.update({"source": "settings", "key": "describeStyle"})
            return (
                custom_style,
                "Describe the visual style in plain text.",
                prompt_meta,
            )
        return (
            "Analyze visual style only. Write a compact single paragraph without bullets.",
            "Describe the visual style in plain text.",
            prompt_meta,
        )

    if mode == "scene":
        if output_format == "json":
            return (
                "Analyze scene content. Return minified JSON only with keys: "
                "scene, subjects, actions, environment, composition, lighting_tone, readable_text, uncertainties.",
                "Describe the scene as JSON.",
                prompt_meta,
            )
        custom_scene = str(custom_prompts.get("describeScene", "")).strip()
        if custom_scene:
            prompt_meta.update({"source": "settings", "key": "describeScene"})
            return (custom_scene, "Describe the scene in plain text.", prompt_meta)
        return (
            "Analyze scene content and visible details. Write a compact single paragraph without bullets.",
            "Describe the scene in plain text.",
            prompt_meta,
        )

    if output_format == "json":
        return (
            "Analyze the full image for prompting purposes. Return minified JSON only with keys: "
            "summary, subjects, scene, style, composition, lighting, colors, readable_text, uncertainties.",
            "Describe the image fully as JSON.",
            prompt_meta,
        )

    active_id = str(custom_prompts.get("describeFullActiveId", "")).strip()
    if active_id:
        variants = custom_prompts.get("describeFullVariants", [])
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                variant_id = str(variant.get("id", "")).strip()
                variant_text = str(variant.get("text", "")).strip()
                if variant_id == active_id and variant_text:
                    prompt_meta.update(
                        {
                            "source": "settings",
                            "key": "describeFullVariants",
                            "activeVariantId": active_id,
                        }
                    )
                    return (
                        variant_text,
                        "Describe the image fully in plain text.",
                        prompt_meta,
                    )

    custom_full = str(custom_prompts.get("describeFull", "")).strip()
    if custom_full:
        prompt_meta.update({"source": "settings", "key": "describeFull"})
        return (custom_full, "Describe the image fully in plain text.", prompt_meta)

    return (
        "Analyze the full image for prompting purposes and include both scene and style cues. "
        "Write a compact single paragraph without bullets.",
        "Describe the image fully in plain text.",
        prompt_meta,
    )


def _list_vision_models_sdk_first(base_url: str) -> list[dict[str, str]]:
    models = lmstudio_service.list_models(base_url)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in models:
        if not isinstance(entry, dict):
            continue

        model_id = str(
            entry.get("id", "") or entry.get("model", "") or entry.get("name", "")
        ).strip()
        if not model_id or model_id in seen:
            continue

        explicit_vision = entry.get("vision")
        if isinstance(explicit_vision, bool):
            is_vision = explicit_vision
            source = "sdk"
        else:
            is_vision = lmstudio_service.model_supports_vision(entry)
            source = "normalized"

        if not is_vision:
            continue

        reasoning_options = lmstudio_service.model_reasoning_options(entry)

        seen.add(model_id)
        selected.append(
            {
                "id": model_id,
                "source": source,
                "reasoning": bool(reasoning_options),
                "reasoningOptions": reasoning_options,
            }
        )

    selected.sort(key=lambda item: item["id"].lower())
    return selected


def list_vision_models_for_benchmark(base_url: str) -> list[dict[str, Any]]:
    return _list_vision_models_sdk_first(base_url)


def run_vision_describe_benchmark(
    *,
    image_data_url: str,
    describe_mode: str,
    output_format: str,
    lmstudio_url: str,
    context_size: Any,
    temperature: Any,
    auto_disconnect: bool,
    custom_prompts: Any = None,
    on_model_start: Any = None,
    on_model_finished: Any = None,
    should_stop: Any = None,
    per_model_timeout_sec: int = 90,
) -> dict[str, Any]:
    mode = _coerce_mode(describe_mode)
    fmt = _coerce_format(output_format)
    parsed_context_size = _coerce_context_size(context_size)
    parsed_temperature = _coerce_temperature(temperature)

    image_mime, image_bytes = _parse_image_data_url(image_data_url)

    # Some vision backends reject WebP in image_url payloads; convert to JPEG best-effort.
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
    image_hash = hashlib.sha256(image_bytes).hexdigest()

    vision_models = _list_vision_models_sdk_first(lmstudio_url)
    if not vision_models:
        return {
            "mode": mode,
            "outputFormat": fmt,
            "imageHash": image_hash,
            "imageMime": image_mime,
            "results": [],
            "summary": {
                "total": 0,
                "ok": 0,
                "failed": 0,
            },
        }

    max_tokens = max(
        800, min(LMSTUDIO_MAX_OUTPUT_TOKENS, int(parsed_context_size * 0.65))
    )
    prompt_settings = custom_prompts if isinstance(custom_prompts, dict) else {}
    system_prompt, user_instruction, prompt_meta = _resolve_prompt_selection(
        mode, fmt, prompt_settings
    )

    results: list[dict[str, Any]] = []
    stopped_early = False
    for model_entry in vision_models:
        if callable(should_stop) and bool(should_stop()):
            stopped_early = True
            break

        model_id = model_entry["id"]
        if callable(on_model_start):
            try:
                on_model_start(model_id)
            except Exception:
                pass
        start = time.perf_counter()
        result: dict[str, Any] = {
            "model": model_id,
            "visionSource": model_entry.get("source", "unknown"),
            "ok": False,
            "description": "",
            "error": "",
            "durationMs": 0,
            "loadedByBenchmark": False,
        }

        loaded_instance_id = ""
        loaded_before = bool(
            lmstudio_service.find_loaded_instance_id(lmstudio_url, model_id)
        )
        try:
            if not loaded_before:
                loaded_here, loaded_instance_id = lmstudio_service.load_model(
                    lmstudio_url,
                    model_id,
                    parsed_context_size,
                )
                result["loadedByBenchmark"] = bool(loaded_here)
                loaded_now = bool(
                    lmstudio_service.find_loaded_instance_id(lmstudio_url, model_id)
                )
                if not loaded_here and not loaded_now:
                    raise RuntimeError("Failed to load model in LM Studio")

            # Native /api/v1/chat first, with reasoning off (NomadStudio#12): the
            # same call the app's describe uses, so the benchmark measures what
            # users get, a reasoning vision model no longer spends its budget
            # thinking and returns nothing, and a dead engine is waited for. The
            # chat-completions attempts stay as the fallback for models the native
            # endpoint rejects.
            description = ""
            try:
                native_response, _level = lmstudio_service.native_chat(
                    lmstudio_url, model_id, system_prompt,
                    [{"type": "text", "content": user_instruction},
                     {"type": "image", "data_url": normalized_data_url}],
                    parsed_temperature, max_tokens,
                    reasoning="off", timeout=max(10, int(per_model_timeout_sec)),
                )
                description = lmstudio_service.native_message_text(native_response)
            except Exception:
                description = ""

            if not description:
                model_l = model_id.lower()
                prefers_raw_base64 = ("qwen" in model_l) or ("gemma" in model_l)
                image_url_candidates = (
                    [image_base64, normalized_data_url]
                    if prefers_raw_base64
                    else [normalized_data_url, image_base64]
                )

                response: dict[str, Any] = {}
                last_error: Exception | None = None
                for image_url_value in image_url_candidates:
                    try:
                        payload = _build_chat_payload(
                            model=model_id,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": user_instruction},
                                        {
                                            "type": "image_url",
                                            "image_url": {"url": image_url_value},
                                        },
                                    ],
                                },
                            ],
                            temperature=parsed_temperature,
                            max_tokens=max_tokens,
                        )

                        response = http_json(
                            lmstudio_service.chat_endpoint(lmstudio_url),
                            gpu_category="lmstudio",
                            method="POST",
                            payload=payload,
                            timeout=max(10, int(per_model_timeout_sec)),
                        )
                        if isinstance(response, dict):
                            error_text = str(
                                response.get("error") or response.get("message") or ""
                            ).strip()
                            if error_text:
                                raise RuntimeError(error_text)
                        last_error = None
                        break
                    except Exception as exc:
                        last_error = exc

                if last_error is not None:
                    raise last_error

                description, source = _extract_lmstudio_message_text(
                    response if isinstance(response, dict) else {}
                )
                if not description:
                    if source == "reasoning_only":
                        raise RuntimeError(
                            "Model returned reasoning only and no final content"
                        )
                    raise RuntimeError("LM Studio returned empty content")

            result["ok"] = True
            result["description"] = description
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            if auto_disconnect and result.get("loadedByBenchmark"):
                unload_target = loaded_instance_id or model_id
                lmstudio_service.unload_model(lmstudio_url, unload_target)

            duration_ms = int((time.perf_counter() - start) * 1000)
            result["durationMs"] = max(0, duration_ms)
            results.append(result)
            if callable(on_model_finished):
                try:
                    on_model_finished(result)
                except Exception:
                    pass

    ok_count = sum(1 for item in results if item.get("ok"))
    failed_count = len(results) - ok_count

    return {
        "mode": mode,
        "outputFormat": fmt,
        "promptSelection": prompt_meta,
        "imageHash": image_hash,
        "imageMime": image_mime,
        "results": results,
        "stopped": stopped_early,
        "summary": {
            "total": len(results),
            "ok": ok_count,
            "failed": failed_count,
        },
    }
