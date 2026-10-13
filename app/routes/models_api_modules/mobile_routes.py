"""Mobile gallery + image-edit endpoint.

POST /api/mobile/edit
  Input : { filename, editType ("person"|"background"|"pose"|"custom"), instruction }
    Flow  : read PNG metadata chunks → refine prompt via LM Studio → generate via active import → return
"""

from __future__ import annotations

import math
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from flask import jsonify, request

from app.services.comfy_paths import for_comfy
from app.config import (
    DEFAULT_LMSTUDIO_TEMPERATURE,
    DEFAULT_LMSTUDIO_URL,
)
from app.routes.models_api_shared import (
    _apply_basic_values_to_workflow,
    _apply_comfy_output_policy,
    _ensure_registry,
    _lmstudio_chat_endpoint,
    _lmstudio_load_model,
    _lmstudio_unload_model,
    _safe_comfy_url,
    _safe_http_url,
    _sanitize_lmstudio_edited_prompt,
    _select_output_images,
    _try_save_image_to_output_dir,
    _coerce_lmstudio_temperature,
    logger,
    models_api_bp,
)
from app.services import gpu_coordinator
from app.services import image_service
from pathlib import Path
from app.services.http_client import http_json, http_bytes


# ---------------------------------------------------------------------------
# System prompts for each preset edit type
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a prompt editor for AI image generation. "
    "You receive an original image generation prompt and an instruction. "
    "Apply the instruction to the prompt and return the edited prompt. "
    "Return ONLY the final prompt text — no labels, no explanations, no quotes."
)

_EDIT_INSTRUCTIONS: dict[str, str] = {
    "person": "Change the person or character to a completely different one, with different hair and demonym. If the main subject is human, keep the same gender presentation as the original. If the main subject is an animal, you may change it freely. Keep the background, scene, style, and everything else exactly the same.",
    "background": "Change the background and scene to a completely different one. Keep the person, character, pose, and style exactly the same.",
    "pose": "Change the pose and action of the person to a completely different one. Keep the person, background, scene, and style exactly the same.",
    "custom": "Apply the following edit to the prompt:",
}


def _extract_lmstudio_message_text_with_reasoning_fallback(
    response: dict[str, Any],
) -> tuple[str, str]:
    """Extract text from LM Studio chat response.

    Prefer `message.content`, but if a model returns empty content and only
    `reasoning_content`, use that as a fallback so mobile edit does not fail.
    Returns (text, source) where source is "content", "reasoning_content", or "".
    """

    def _collect_text(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            chunks: list[str] = []
            for part in value:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type", "")).strip().lower()
                if part_type and part_type != "text":
                    continue
                text_part = str(part.get("text", "")).strip()
                if text_part:
                    chunks.append(text_part)
            return "\n".join(chunks).strip()
        return ""

    choices = response.get("choices") if isinstance(response, dict) else None
    if not isinstance(choices, list) or not choices:
        return "", ""

    first = choices[0]
    if not isinstance(first, dict):
        return "", ""

    message = first.get("message", {})
    if not isinstance(message, dict):
        return "", ""

    content_text = _collect_text(message.get("content", ""))
    if content_text:
        return content_text, "content"

    reasoning_text = _collect_text(message.get("reasoning_content", ""))
    if reasoning_text:
        return reasoning_text, "reasoning_content"

    return "", ""


def _get_image_png_meta(output_dir: str, filename: str) -> dict[str, str]:
    """Read embedded metadata chunks from a PNG image (oj:* keys)."""
    try:
        image_path = Path(output_dir) / filename
        if image_path.suffix.lower() != ".png" or not image_path.is_file():
            return {}
        meta = image_service.read_png_text_chunks(image_path.read_bytes())
        return meta if isinstance(meta, dict) else {}
    except Exception:
        return {}


def _to_positive_int(value: Any) -> int | None:
    try:
        num = int(str(value or "").strip())
    except Exception:
        return None
    return num if num > 0 else None


def _round_to_multiple(value: int, step: int = 8, minimum: int = 64) -> int:
    rounded = int(round(float(value) / float(step)) * step)
    return max(minimum, rounded)


def _derive_dims_from_ratio(
    base_width: int | None,
    base_height: int | None,
    original_width: int | None,
    original_height: int | None,
) -> tuple[int, int] | None:
    """Compute target dimensions preserving original aspect ratio.

    Uses the active workflow base area as size budget and applies the original
    image ratio, then snaps both dimensions to multiples of 8.
    """
    if not original_width or not original_height:
        return None
    if original_width <= 0 or original_height <= 0:
        return None

    ratio = float(original_width) / float(original_height)
    if ratio <= 0:
        return None

    default_area = 1024 * 1024
    if base_width and base_height and base_width > 0 and base_height > 0:
        area = int(base_width) * int(base_height)
    else:
        area = default_area

    derived_width = int(math.sqrt(area * ratio))
    derived_height = int(math.sqrt(area / ratio))

    width = _round_to_multiple(max(64, derived_width), step=8, minimum=64)
    height = _round_to_multiple(max(64, derived_height), step=8, minimum=64)
    return width, height


@models_api_bp.post("/mobile/edit")
def mobile_edit_image():
    """Refine prompt via LM Studio then generate a new image via active ComfyUI import."""
    payload = request.get_json(silent=True) or {}

    filename = str(payload.get("filename", "")).strip()
    edit_type = str(payload.get("editType", "custom")).strip().lower()
    instruction = str(payload.get("instruction", "")).strip()
    seed_mode = str(payload.get("seedMode", "fixed") or "fixed").strip().lower()
    seed_only = bool(payload.get("seedOnly", False))
    preview_only = bool(payload.get("previewOnly", False))
    thinking = bool(payload.get("thinking", False))
    skip_system_prompt = bool(payload.get("skipSystemPrompt", True))
    incoming_refined_prompt = str(payload.get("refinedPrompt", "") or "").strip()

    # Use a default instruction if none was provided
    if not instruction:
        instruction = _EDIT_INSTRUCTIONS.get(edit_type, _EDIT_INSTRUCTIONS["custom"])

    if not filename:
        return jsonify({"error": "filename is required"}), 400

    # Reject path traversal attempts.
    if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
        return jsonify({"error": "invalid filename"}), 400

    data = _ensure_registry()
    settings = (
        data.get("settings", {}) if isinstance(data.get("settings"), dict) else {}
    )
    output_dir = str(settings.get("outputDir", "")).strip()

    # -----------------------------------------------------------------------
    # 1. Load original prompt from embedded PNG metadata chunks
    # -----------------------------------------------------------------------
    original_prompt = ""
    original_workflow_id = ""
    original_meta: dict[str, str] = {}
    if output_dir:
        original_meta = _get_image_png_meta(output_dir, filename)
        original_prompt = str(original_meta.get("positive", "") or "").strip()
        original_workflow_id = str(original_meta.get("workflow", "") or "").strip()

    logger.info(
        "[mobile/edit] output_dir=%r  filename=%r  original_prompt=%r  original_workflow_id=%r",
        output_dir,
        filename,
        original_prompt,
        original_workflow_id,
    )

    # -----------------------------------------------------------------------
    # 2. Refine prompt via LM Studio (unless caller already provided refinedPrompt)
    # -----------------------------------------------------------------------
    refined_prompt = incoming_refined_prompt
    if seed_only and not refined_prompt:
        refined_prompt = original_prompt

    if not refined_prompt and not seed_only:
        lmstudio_url = (
            str(settings.get("lmStudioApiUrl", "")).strip() or DEFAULT_LMSTUDIO_URL
        )
        lmstudio_model = str(settings.get("lmStudioModel", "")).strip()
        lmstudio_temperature = _coerce_lmstudio_temperature(
            settings.get("lmStudioTemperature", DEFAULT_LMSTUDIO_TEMPERATURE)
        )
        # Mobile edit input is tiny: allow up to 30000 tokens for reasoning models.
        max_output_tokens = 30000
        auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))

        logger.info(
            "[mobile/edit] lmstudio_url=%r  lmstudio_model=%r",
            lmstudio_url,
            lmstudio_model,
        )

        if not lmstudio_url:
            return jsonify({"error": "LM Studio URI is not configured"}), 400
        if not lmstudio_model:
            return jsonify({"error": "LM Studio model is not selected"}), 400

        try:
            lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        system_prompt = _SYSTEM_PROMPT
        edit_instruction = _EDIT_INSTRUCTIONS.get(
            edit_type, _EDIT_INSTRUCTIONS["custom"]
        )

        if original_prompt:
            user_prompt = (
                f"Original prompt:\n{original_prompt}\n\n"
                f"Instruction: {edit_instruction}\n\n"
                "Return only the rewritten prompt.\n"
                "Send result prompt only."
            )
        else:
            user_prompt = (
                f"Instruction: {edit_instruction}\n\n"
                "Return a prompt for image generation based on this instruction.\n"
                "Send result prompt only."
            )

        messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
        if not skip_system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        auto_disconnect_loaded = False
        unload_instance_id = ""

        try:
            if auto_disconnect:
                auto_disconnect_loaded, unload_instance_id = _lmstudio_load_model(
                    lmstudio_url, lmstudio_model
                )

            # Native /api/v1/chat with an explicit reasoning level
            # (NomadStudio#12): the chat-completions call used here before
            # could not turn reasoning off, so reasoning models spent the
            # budget thinking and returned nothing. _call_studio_llm also waits
            # for LM Studio to come back if its engine dies, and makes VRAM
            # room before a load (Qwen's /no_think prefix is no longer needed).
            from .chat_routes import _call_studio_llm

            raw_text, text_source = _call_studio_llm(
                lmstudio_url, lmstudio_model, messages,
                lmstudio_temperature, max_output_tokens,
                reasoning="on" if thinking else "off", timeout=600, label="mobile-edit",
            )
            if text_source == "reasoning_only":
                logger.warning(
                    "LM Studio returned reasoning only for the mobile edit; keeping the original prompt"
                )

            refined_prompt = (
                _sanitize_lmstudio_edited_prompt(raw_text)
                or original_prompt
                or instruction
            )

        except Exception as exc:
            logger.error("LM Studio prompt refinement failed: %s", exc, exc_info=True)
            return jsonify({"error": f"LM Studio call failed: {exc}"}), 502
        finally:
            if auto_disconnect and auto_disconnect_loaded and unload_instance_id:
                try:
                    _lmstudio_unload_model(lmstudio_url, unload_instance_id)
                except Exception:
                    pass

    if not refined_prompt and not seed_only:
        return jsonify({"error": "Could not produce a refined prompt"}), 502

    if preview_only:
        return jsonify(
            {
                "ok": True,
                "previewOnly": True,
                "refinedPrompt": refined_prompt,
                "originalPrompt": original_prompt,
            }
        )

    # -----------------------------------------------------------------------
    # 3. Pick import: prefer the image's original workflow, fallback to first active import
    # -----------------------------------------------------------------------
    imports: list[dict[str, Any]] = (
        data.get("imports", []) if isinstance(data.get("imports"), list) else []
    )
    active_ids: list[str] = (
        data.get("activeImportIds", [])
        if isinstance(data.get("activeImportIds"), list)
        else []
    )
    legacy_id = str(data.get("activeImportId", "") or "").strip()
    if legacy_id and legacy_id not in active_ids:
        active_ids = [legacy_id, *active_ids]

    record: dict[str, Any] | None = None

    if original_workflow_id:
        record = next(
            (
                item
                for item in imports
                if isinstance(item, dict)
                and str(item.get("id", "")) == original_workflow_id
            ),
            None,
        )

    if record is None:
        for aid in active_ids:
            candidate = next(
                (
                    item
                    for item in imports
                    if isinstance(item, dict) and str(item.get("id", "")) == aid
                ),
                None,
            )
            if candidate:
                record = candidate
                break

    if record is None:
        if original_workflow_id:
            return jsonify(
                {
                    "error": (
                        "Original image workflow was not found and no active import is available. "
                        "Activate a workflow in Models > Images first."
                    )
                }
            ), 400
        return jsonify(
            {
                "error": "No active import found. Activate a workflow in Models > Images first."
            }
        ), 400

    if seed_only and not refined_prompt:
        refined_prompt = str(
            record.get("basicValues", {}).get("positive", "") or ""
        ).strip()
    if not refined_prompt:
        return jsonify(
            {"error": "Could not determine a base prompt for seed-only regeneration"}
        ), 400

    comfy_api_url = (
        str(record.get("comfyApiUrl", "")).strip()
        or str(settings.get("comfyApiUrl", "")).strip()
    )
    if not comfy_api_url:
        return jsonify({"error": "ComfyUI URI not configured"}), 400

    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # -----------------------------------------------------------------------
    # 4. Prepare workflow and submit to ComfyUI
    # -----------------------------------------------------------------------
    merged_basic = {**record.get("basicValues", {}), "positive": refined_prompt}

    # Resolve the seed used for this mobile edit so it is both applied and persisted.
    applied_seed = _to_positive_int(merged_basic.get("seed"))
    if seed_mode == "random":
        applied_seed = random.randint(1, 2147483647)
        merged_basic["seed"] = applied_seed

    logger.info("[mobile/edit] seed_mode=%r applied_seed=%r", seed_mode, applied_seed)

    # Keep generation ratio aligned with the original image when dimensions are available.
    base_width = _to_positive_int(merged_basic.get("width"))
    base_height = _to_positive_int(merged_basic.get("height"))
    original_width = _to_positive_int(original_meta.get("width"))
    original_height = _to_positive_int(original_meta.get("height"))
    derived_dims = _derive_dims_from_ratio(
        base_width, base_height, original_width, original_height
    )
    if derived_dims:
        merged_basic["width"], merged_basic["height"] = derived_dims

    merged_advanced = {**record.get("advancedValues", {})}

    try:
        prepared_workflow = _apply_basic_values_to_workflow(
            record, merged_basic, merged_advanced, num_images=1
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    _apply_comfy_output_policy(data, prepared_workflow)

    try:
        client_id = uuid.uuid4().hex
        # Held for the whole submit+poll window, not just the POST — the actual
        # GPU work happens between these HTTP calls (see gpu_coordinator.py).
        with gpu_coordinator.held("comfy"):
            prompt_response = http_json(
                f"{comfy_api_url}/prompt",
                method="POST",
                payload={"prompt": for_comfy(prepared_workflow, comfy_api_url), "client_id": client_id},
                timeout=30,
            )
            prompt_id = str(prompt_response.get("prompt_id", "")).strip()
            if not prompt_id:
                return jsonify(
                    {"error": f"ComfyUI rejected the prompt: {prompt_response}"}
                ), 502

            # Poll history until output appears (max 6 min).
            history_payload: dict[str, Any] = {}
            for _ in range(720):
                time.sleep(0.5)
                history_payload = http_json(
                    f"{comfy_api_url}/history/{prompt_id}", timeout=120
                )
                if isinstance(history_payload, dict) and prompt_id in history_payload:
                    outputs = history_payload.get(prompt_id, {}).get("outputs", {})
                    if outputs:
                        break

        preferred_save_nodes = (
            record.get("analysis", {}).get("detected", {}).get("saveImageNodeIds", [])
            or []
        )
        _, image_entries = _select_output_images(
            history_payload, prompt_id, preferred_save_nodes
        )
        if not image_entries:
            return jsonify({"error": "No output image found in ComfyUI history"}), 502

        first = image_entries[0]
        query = urlencode(
            {
                "filename": first.get("filename", ""),
                "subfolder": first.get("subfolder", ""),
                "type": first.get("type", "output"),
            }
        )
        image_bytes = http_bytes(f"{comfy_api_url}/view?{query}", timeout=180)

        meta: dict[str, str] = {
            "positive": refined_prompt,
            "original_prompt": original_prompt,
            "seed": str(applied_seed or merged_basic.get("seed", "0") or "0"),
            "source": "mobile_edit",
            "edit_type": edit_type,
            "session": prompt_id,
            "workflow": str(record.get("id", "")),
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        saved_filename = _try_save_image_to_output_dir(
            data, image_bytes, meta, "mobile-edit", 0
        )
    except Exception as exc:
        logger.exception("ComfyUI mobile edit generation failed")
        return jsonify({"error": f"Generation failed: {exc}"}), 502

    return jsonify(
        {
            "ok": True,
            "savedFilename": saved_filename,
            "refinedPrompt": refined_prompt,
            "originalPrompt": original_prompt,
            "seedMode": seed_mode,
            "appliedSeed": applied_seed,
        }
    )
