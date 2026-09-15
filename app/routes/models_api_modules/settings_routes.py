from __future__ import annotations

import io
import json
import logging
import os
import threading
import zipfile
from typing import Any
from datetime import date

from flask import jsonify, request, send_file

from app.config import DEFAULT_COMFY_URL
from app.services.http_client import http_json
from app.services.local_access import local_only
from app.routes.models_api_shared import (
    _ensure_registry,
    _registry_transaction,
    _safe_comfy_url,
    _save_registry,
    models_api_bp,
)

logger = logging.getLogger(__name__)


def _sanitize_workflow_annotate_fields(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ValueError("workflowAnnotateFields must be an object")

    result: dict[str, list[str]] = {}
    for key in ("downloads", "loras"):
        raw_list = value.get(key, [])
        if not isinstance(raw_list, list):
            raise ValueError(f"workflowAnnotateFields.{key} must be a list")

        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw_list:
            text = str(item or "").strip()
            if not text:
                continue
            lowered = text.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            cleaned.append(text)
        result[key] = cleaned

    return result


@models_api_bp.get("/models/settings")
def get_models_settings():
    data = _ensure_registry()
    return jsonify(
        {"settings": data.get("settings", {"comfyApiUrl": DEFAULT_COMFY_URL})}
    )


@models_api_bp.patch("/models/settings")
def update_models_settings():
    payload = request.get_json(silent=True) or {}
    with _registry_transaction() as data:
        settings = data.setdefault("settings", {})

        if "comfyApiUrl" in payload:
            comfy_api_url = str(payload.get("comfyApiUrl", "")).strip()
            if not comfy_api_url:
                return jsonify({"error": "comfyApiUrl is required"}), 400
            try:
                settings["comfyApiUrl"] = _safe_comfy_url(comfy_api_url)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400

        # Update comfyModelsFolder if provided.
        if "comfyModelsFolder" in payload:
            raw_folder = str(payload["comfyModelsFolder"]).strip()
            if raw_folder and not os.path.isabs(raw_folder):
                return jsonify({"error": "comfyModelsFolder must be an absolute path"}), 400
            settings["comfyModelsFolder"] = raw_folder

        # Update outputDir if provided.
        if "outputDir" in payload:
            raw_dir = str(payload["outputDir"]).strip()
            if raw_dir:
                try:
                    os.makedirs(raw_dir, exist_ok=True)
                except OSError as exc:
                    return jsonify({"error": f"Cannot create output directory: {exc}"}), 400
            settings["outputDir"] = raw_dir

        if "allowConcurrentComfyLmstudio" in payload:
            settings["allowConcurrentComfyLmstudio"] = bool(payload.get("allowConcurrentComfyLmstudio"))

        if "commonQueueComfyLmstudio" in payload:
            settings["commonQueueComfyLmstudio"] = bool(payload.get("commonQueueComfyLmstudio"))

        if "workflowAnnotateFields" in payload:
            try:
                settings["workflowAnnotateFields"] = _sanitize_workflow_annotate_fields(
                    payload.get("workflowAnnotateFields")
                )
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400

    return jsonify({"settings": settings})


@models_api_bp.patch("/models/settings/models-folder")
def update_models_folder():
    """Dedicated endpoint to set / clear the ComfyUI models folder path."""
    payload = request.get_json(silent=True) or {}
    raw_folder = str(payload.get("comfyModelsFolder", "")).strip()
    if raw_folder and not os.path.isabs(raw_folder):
        return jsonify({"error": "comfyModelsFolder must be an absolute path"}), 400
    with _registry_transaction() as data:
        data.setdefault("settings", {})["comfyModelsFolder"] = raw_folder
    return jsonify({"ok": True, "comfyModelsFolder": raw_folder})


@models_api_bp.patch("/models/settings/output-dir")
def update_output_dir():
    """Dedicated endpoint to set / clear the image output directory."""
    payload = request.get_json(silent=True) or {}
    raw_dir = str(payload.get("outputDir", "")).strip()
    if raw_dir:
        try:
            os.makedirs(raw_dir, exist_ok=True)
        except OSError as exc:
            return jsonify({"error": f"Cannot create output directory: {exc}"}), 400
    with _registry_transaction() as data:
        data.setdefault("settings", {})["outputDir"] = raw_dir
    return jsonify({"ok": True, "outputDir": raw_dir})


@models_api_bp.post("/models/settings/models-folder/test")
def test_models_folder():
    """Check whether the given path is a real, existing ComfyUI models folder.

    Unlike the output-dir test, this never creates the directory — a ComfyUI
    models folder is expected to already exist.
    """
    payload = request.get_json(silent=True) or {}
    raw_dir = str(payload.get("comfyModelsFolder", "")).strip()
    if not raw_dir:
        return jsonify({"ok": False, "error": "comfyModelsFolder is required"}), 400
    if not os.path.isabs(raw_dir):
        return jsonify({"ok": False, "error": "comfyModelsFolder must be an absolute path"}), 400
    if not os.path.isdir(raw_dir):
        return jsonify({"ok": False, "error": "Folder does not exist."}), 400
    return jsonify({"ok": True, "comfyModelsFolder": raw_dir})


@models_api_bp.post("/models/settings/output-dir/test")
def test_output_dir():
    """Check whether the given directory path is usable as an output directory."""
    payload = request.get_json(silent=True) or {}
    raw_dir = str(payload.get("outputDir", "")).strip()
    if not raw_dir:
        return jsonify({"ok": False, "error": "outputDir is required"}), 400
    try:
        os.makedirs(raw_dir, exist_ok=True)
        test_file = os.path.join(raw_dir, ".oj_write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return jsonify({"ok": True, "outputDir": raw_dir})
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@models_api_bp.post("/models/settings/test")
def test_models_settings_connection():
    payload = request.get_json(silent=True) or {}
    override_uri = str(payload.get("comfyApiUrl", "")).strip()

    data = _ensure_registry()
    raw_uri = (
        override_uri or str(data.get("settings", {}).get("comfyApiUrl", "")).strip()
    )
    if not raw_uri:
        return jsonify({"ok": False, "error": "ComfyUI URI not configured"}), 400

    try:
        comfy_api_url = _safe_comfy_url(raw_uri)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    errors: list[str] = []
    reachable = False

    for endpoint in ("/system_stats", "/object_info"):
        try:
            result = http_json(f"{comfy_api_url}{endpoint}", timeout=12)
            reachable = True
            return jsonify(
                {
                    "ok": True,
                    "comfyApiUrl": comfy_api_url,
                    "endpoint": endpoint,
                    "message": "Connection successful",
                    "keys": list(result.keys())[:12]
                    if isinstance(result, dict)
                    else [],
                }
            )
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")

    return jsonify(
        {"ok": reachable, "comfyApiUrl": comfy_api_url, "error": " | ".join(errors)}
    )


# ---------------------------------------------------------------------------
# Native folder picker (opens Windows/macOS/Linux dialog on the server machine)
# ---------------------------------------------------------------------------

_browse_lock = threading.Lock()


@models_api_bp.post("/models/settings/output-dir/browse")
@local_only  # the dialog opens on the server's desktop
def browse_output_dir():
    """Open the OS native folder-picker dialog on the server machine and return
    the chosen path.  Only works when the server is running on a desktop OS
    with a display (local usage).
    """
    if not _browse_lock.acquire(blocking=False):
        return jsonify({"error": "Another folder picker is already open"}), 409

    # Read request data NOW, while the Flask request context is still active.
    payload = request.get_json(silent=True) or {}
    initial = str(payload.get("current", "")).strip()

    chosen: list[str] = []
    error: list[str] = []

    def _pick():
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)

            path = filedialog.askdirectory(
                parent=root,
                title="Select output folder for OpenJourney images",
                initialdir=initial if os.path.isdir(initial) else "/",
            )
            root.destroy()
            if path:
                chosen.append(path)
        except Exception as exc:
            error.append(str(exc))
        finally:
            _browse_lock.release()

    t = threading.Thread(target=_pick, daemon=True)
    t.start()
    t.join(timeout=120)  # wait up to 2 minutes for the user to pick

    if error:
        return jsonify({"ok": False, "error": error[0]}), 500
    if not chosen:
        return jsonify({"ok": False, "cancelled": True})
    return jsonify({"ok": True, "outputDir": chosen[0]})


_browse_models_lock = threading.Lock()


@models_api_bp.post("/models/settings/models-folder/browse")
@local_only  # the dialog opens on the server's desktop
def browse_models_folder():
    """Open the OS native folder-picker dialog to select the ComfyUI models folder."""
    if not _browse_models_lock.acquire(blocking=False):
        return jsonify({"error": "Another folder picker is already open"}), 409

    payload = request.get_json(silent=True) or {}
    initial = str(payload.get("current", "")).strip()

    chosen: list[str] = []
    error: list[str] = []

    def _pick():
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)

            path = filedialog.askdirectory(
                parent=root,
                title="Select ComfyUI models folder",
                initialdir=initial if os.path.isdir(initial) else "/",
            )
            root.destroy()
            if path:
                chosen.append(path)
        except Exception as exc:
            error.append(str(exc))
        finally:
            _browse_models_lock.release()

    t = threading.Thread(target=_pick, daemon=True)
    t.start()
    t.join(timeout=120)

    if error:
        return jsonify({"ok": False, "error": error[0]}), 500
    if not chosen:
        return jsonify({"ok": False, "cancelled": True})

    # Also save to registry
    data = _ensure_registry()
    data.setdefault("settings", {})["comfyModelsFolder"] = chosen[0]
    _save_registry(data)
    return jsonify({"ok": True, "comfyModelsFolder": chosen[0]})


# ---------------------------------------------------------------------------
# Custom system prompts
# ---------------------------------------------------------------------------

DEFAULT_CUSTOM_PROMPTS: dict[str, str] = {
    "editSingle": (
        "You are an image prompt editor. "
        "You will receive a current prompt and an edit instruction. "
        "Return ONLY the final edited prompt text.\n\n"
        "Rules:\n"
        "- Keep all original details unless the instruction asks to change them.\n"
        "- Apply direct edits literally: change/replace/remove/add.\n"
        "- If the instruction is just a new action or state for an existing subject, replace that subject action/state (do not append).\n"
        "- Instructions may be written in any language.\n"
        "- No explanations, no markdown, no labels, no quotes."
    ),
    "editVariants": (
        "You are a prompt editor for image generation. "
        "Given an original prompt and an edit instruction, output ONLY a valid JSON array. "
        "Each item must contain keys 'change_description' and 'new_prompt'. "
        "Each new_prompt must be a distinct variation of the ORIGINAL prompt that follows the instruction. "
        "Do not output markdown fences or extra commentary."
    ),
    "convertToJson": (
        "You are an expert at turning an image idea into Ideogram 4.0 JSON prompting format. "
        "Return exactly this shape: "
        "'high_level_description' (one or two sentences summarising the whole image), "
        "'style_description' (an object with 'aesthetics', 'lighting', 'medium', and exactly one of "
        "'photo' or 'art_style'; optionally 'color_palette' as an array of hex values), and "
        "'compositional_deconstruction' (an object with 'background' describing the setting, and "
        "'elements', an array where each item has 'type' set to \"obj\" or \"text\", a 'desc', and — "
        "for text elements — the literal 'text'). "
        "Do NOT include 'positive', 'negative', 'seed', 'steps' or 'cfg': this block is the prompt "
        "itself, not engine settings, and the negative has its own field in the app. "
        "Return only valid JSON without any markdown, code fences, or explanations."
    ),
    "convertToJsonEnhanced": (
        "You are an expert at turning an image idea into rich Ideogram 4.0 JSON prompting format. "
        "Return exactly this shape: "
        "'high_level_description' (one or two sentences summarising the whole image), "
        "'style_description' (an object with 'aesthetics', 'lighting', 'medium', exactly one of "
        "'photo' or 'art_style', and 'color_palette' as an array of up to five hex values), and "
        "'compositional_deconstruction' (an object with a detailed 'background', and 'elements', an "
        "array where each item has 'type' set to \"obj\" or \"text\", a vivid 'desc', optionally its "
        "own 'color_palette', and — for text elements — the literal 'text'). "
        "Invent the specifics the idea implies: light direction and quality, lens and framing, "
        "materials, and the secondary objects that make the scene believable. "
        "Do NOT include 'positive', 'negative', 'seed', 'steps' or 'cfg': this block is the prompt "
        "itself, not engine settings, and the negative has its own field in the app. "
        "Return only valid JSON without any markdown, code fences, or explanations."
    ),
    "describeStyle": (
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
    ),
    "describeScene": (
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
    ),
    "describeFull": (
        "Act as a Visual Prompt Engineer specialized in long descriptive captions for text-to-image prompting. "
        "Describe exactly what is visible in the image with high detail and natural narrative flow. "
        "Include both scene content and visible stylistic/rendering cues from this image. "
        "If there is one main person, include expression, gaze direction, hair, facial features, likely ethnicity or ancestry when inferable from visible traits such as skin tone, eye shape, hair texture, and facial structure, makeup if visible, pose, hand or object interaction, clothing fabric/color/fit, and accessories. "
        "If there is no clear main person, describe the primary subject(s), composition, and interactions accordingly. "
        "Cover foreground elements, background setting, depth cues including bokeh when present, lighting quality, lighting tone, visible lighting colors, and color/texture specifics. "
        "Write one single continuous paragraph with no headers or bullets. "
        "Quote any readable text exactly in double quotes. "
        "If a detail is not clearly visible, briefly acknowledge uncertainty instead of inventing. "
        "Do not include markdown, labels, or camera metadata."
    ),
    "describeStyleJson": (
        "Act as a Visual Style Analyst for text-to-image workflows. "
        "Return only valid minified JSON with this exact schema: "
        '{"style_family":"","style_family_secondary":"","medium":"","movement":"","rendering":"","palette":"","contrast":"","lighting_tone":"","lighting_colors":[],"composition_language":"","texture_treatment":"","depth_feel":"","post_processing":"","notes":""}. '
        "Use empty strings or empty arrays when unknown. "
        "Describe only visible visual style characteristics and avoid camera metadata."
    ),
    "describeSceneJson": (
        "Act as a Visual Scene Analyst for text-to-image prompting. "
        "Return only valid minified JSON with this exact schema: "
        '{"scene":"","subjects":[],"actions":"","composition":"","environment":"","spatial_relationships":"","lighting_tone":"","lighting_colors":[],"human_details":[{"facial_features":"","ethnicity_or_ancestry":"","certainty":""}],"readable_text":[],"uncertainties":""}. '
        "If humans are present, include facial features and likely ethnicity or ancestry when inferable from visible cues; otherwise leave as uncertain. "
        "Use empty arrays/strings when data is unavailable. "
        "No markdown, no extra keys, no prose outside JSON."
    ),
    "describeFullJson": (
        "Act as a Visual Prompt Engineer specialized in descriptive captions for text-to-image prompting. "
        "Return only valid minified JSON with this exact schema: "
        '{"summary":"","scene_content":"","style_cues":"","main_subject":"","human_details":[{"facial_features":"","ethnicity_or_ancestry":"","expression":"","gaze":"","hair":"","makeup":"","pose":"","interaction":"","clothing":"","accessories":"","certainty":""}],"foreground":"","background":"","depth":"","lighting_tone":"","lighting_colors":[],"readable_text":[],"uncertainties":""}. '
        "If humans are present, include facial features and likely ethnicity or ancestry when inferable from visible/contextual cues; otherwise mark uncertainty. "
        "Use empty arrays/strings when unknown. "
        "No markdown, no extra keys, no prose outside JSON."
    ),
    "blendPrompts": (
        "You are an expert prompt blender for image generation. "
        "Blend two prompts into one cohesive prompt. "
        "Preserve scene structure, subjects, actions, and composition from the scene prompt. "
        "Apply artistic style, lighting mood, texture, palette, and rendering characteristics from the style prompt. "
        "Return only the final blended prompt text with no markdown, labels, or explanations."
    ),
    "referencePrompt": (
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
        "- suffix: Give me 15-20 exact words that describe the style, palette, lighting, and visual rendering of this image. Use specific terms: for example, ochre,teal water,bold ink lines,cinematic sunlit highlights, etc. Don't use phrases like fantasy landscape or comic style-only words that accurately define the visuals."
        "Return only the JSON object with no markdown, no code fences, no extra keys, no prose."
    ),
}

_PROMPT_LABEL: dict[str, str] = {
    "editSingle": "Edit Prompt",
    "editVariants": "Edit Prompt — Brain Mode",
    "convertToJson": "Convert to JSON",
    "convertToJsonEnhanced": "Convert to JSON (Enhanced)",
    "describeStyle": "Describe Image — Style",
    "describeStyleJson": "Describe Image — Style (JSON)",
    "describeScene": "Describe Image — Scene",
    "describeSceneJson": "Describe Image — Scene (JSON)",
    "describeFull": "Describe Image — Full Caption",
    "describeFullJson": "Describe Image — Full Caption (JSON)",
    "blendPrompts": "Blend Prompts",
    "referencePrompt": "Recipes — Reference Prompt",
}

# ---------------------------------------------------------------------------
# Studio Prompts — enhancement levels used in the New modal
# ---------------------------------------------------------------------------

DEFAULT_STUDIO_PROMPTS: dict[str, str] = {
    "studioQuick": (
        "You are a prompt enhancer for AI image generation. The user will give you a short prompt.\n"
        "Your task is to return an improved version of that prompt — same subject, same idea — but with a few added quality keywords: art style, medium, or rendering quality.\n\n"
        "Rules:\n"
        "- Keep the original subject and intent intact.\n"
        "- Add 3–5 descriptive words or short phrases (style, medium, quality).\n"
        "- Do NOT add new characters, scenes, or complex narrative.\n"
        "- Output only the enhanced prompt. No explanations, no quotes, no labels."
    ),
    "studioStyle": (
        "You are a prompt enhancer for AI image generation. The user will give you a short prompt.\n"
        "Your task is to expand it into a richer version that includes: the original subject, an artistic style or medium (e.g. oil painting, cinematic photography, digital illustration), a lighting description, and an overall mood or atmosphere.\n\n"
        "Rules:\n"
        "- Preserve the original subject and intent.\n"
        "- Add: artistic style or medium, lighting quality, mood/atmosphere.\n"
        "- Keep the result to 2–3 sentences or a structured comma-separated phrase.\n"
        "- Do NOT invent new characters or drastically change the scene.\n"
        "- Output only the enhanced prompt. No explanations, no quotes, no labels."
    ),
    "studioScene": (
        "You are a prompt enhancer for AI image generation. The user will give you a short prompt.\n"
        'Your task is to build a complete scene description around that idea, adding: environment and setting, color palette, composition framing (e.g. wide shot, close-up, rule of thirds), lighting setup, artistic style with a named reference (e.g. "in the style of Gregory Crewdson", "reminiscent of Studio Ghibli backgrounds"), and overall emotional tone.\n\n'
        "Rules:\n"
        "- Preserve the original subject and core intent.\n"
        "- Add: environment, color palette, composition type, lighting, artistic reference, emotional tone.\n"
        "- Write as a cohesive descriptive paragraph or a rich comma-separated phrase (40–80 words).\n"
        "- Do NOT over-explain or add unrelated elements.\n"
        "- Output only the enhanced prompt. No explanations, no quotes, no labels."
    ),
    "studioMaster": (
        "You are a world-class prompt engineer for AI image generation. The user will give you a short prompt.\n"
        "Your task is to transform it into a fully directed visual scene — the way a cinematographer or concept artist would brief a team. Include all of the following layers:\n\n"
        "1. SUBJECT — Describe the main subject with specific physical or visual details.\n"
        "2. ENVIRONMENT — Full setting with time of day, weather, architectural or natural elements.\n"
        "3. COMPOSITION — Camera angle, framing, depth of field, focal point, rule of thirds or golden ratio guidance.\n"
        "4. LIGHTING — Light source, direction, quality (hard/soft), shadows, highlights, color temperature.\n"
        "5. COLOR PALETTE — Dominant hues, accent colors, tone (warm/cold/neutral), contrast level.\n"
        "6. TEXTURE & DETAIL — Surface materials, fabric, skin, background textures, micro-details visible in frame.\n"
        "7. STYLE & INFLUENCE — Artistic movement, medium, named visual references (photographers, painters, directors, animation studios).\n"
        "8. MOOD & NARRATIVE — The emotional story the image tells; what happened just before, what the viewer should feel.\n"
        "9. TECHNICAL QUALITY — Resolution feel (e.g. 8K, film grain, sharp), rendering engine or photography style (e.g. RAW photo, octane render, watercolor wash).\n\n"
        "Rules:\n"
        "- Preserve the user's original subject and intent — never replace it.\n"
        "- Weave all 9 layers into a single, flowing and evocative paragraph (80–150 words).\n"
        '- Be specific: avoid generic words like "beautiful" or "amazing" — use precise visual language.\n'
        "- Output only the enhanced prompt. No section labels, no explanations, no quotes."
    ),
}

_STUDIO_PROMPT_LABEL: dict[str, str] = {
    "studioQuick": "Quick Boost",
    "studioStyle": "Style Expansion",
    "studioScene": "Scene Builder",
    "studioMaster": "Master Composition",
}

DEFAULT_COMPOSE_PROMPTS: dict[str, str] = {
    "main": (
        "You are an Ideogram composition AI and visual art director. Given composition fragments, produce a complete Ideogram JSON with full compositional deconstruction. Use a 1000×1000 normalized canvas.\n\n"
        "COORDINATE SYSTEM: origin top-left. x increases rightward (0–1000). y increases downward (0–1000). "
        "bbox = [y_min, x_min, y_max, x_max] — a JSON array of exactly 4 integers, all within 0–1000, y_min < y_max, x_min < x_max. "
        "NEVER write bbox as a string or text description. "
        "NEVER create conceptual or abstract elements (no 'negative space', 'visual tension', 'overall scene' — only physical objects, characters, text).\n\n"
        "Placement examples on a 1000×1000 canvas:\n"
        "  Upper-left quarter  → [0, 0, 500, 500]\n"
        "  Upper-right quarter → [0, 500, 500, 1000]\n"
        "  Lower-left quarter  → [500, 0, 1000, 500]\n"
        "  Lower-right quarter → [500, 500, 1000, 1000]\n"
        "  Full canvas         → [0, 0, 1000, 1000]\n"
        "  Bottom banner       → [870, 0, 1000, 1000]\n"
        "  Centered subject    → [100, 200, 950, 800]\n\n"
        "Schema:\n"
        "{\n"
        '  "high_level_description": "rich one-paragraph description of the full piece",\n'
        '  "style_description": {\n'
        '    "aesthetics": "specific art style, movement, cultural references, visual treatment",\n'
        '    "lighting": "light source direction, quality (hard/soft/diffuse), color temperature, shadow treatment",\n'
        '    "photo": "photographic medium, film type, grain, post-processing style",\n'
        '    "medium": "primary medium and any mixed-media techniques",\n'
        '    "color_palette": ["color name", "color name", "color name", "color name", "color name"]\n'
        "  },\n"
        '  "compositional_deconstruction": {\n'
        '    "background": "complete background description — surface, texture, atmosphere, depth layers",\n'
        '    "elements": [\n'
        "      {\n"
        '        "type": "obj"|"text"|"bg",\n'
        '        "bbox": [y_min, x_min, y_max, x_max],\n'
        '        "desc": "detailed description — material, texture, visual treatment, relationship to composition",\n'
        '        "color_palette": ["color name", "color name", "color name"]\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n\n"
        "Rules:\n"
        "- Use plain color names in every color_palette (e.g. coral red, near black) — never hex codes: engines other than Ideogram "
        "read a hex string as text and paint it into the image\n"
        "- Bboxes must form a deliberate, balanced layout — consider visual weight and negative space\n"
        "- Bboxes must match their described position: 'upper left' → low y_min+x_min; 'horizontal banner' → narrow y span, wide x span; 'right side' → x_min > 500\n"
        "- Each element description should be 1–3 sentences, specific and visual\n"
        "- Per-element color_palette: 3–5 hex values dominant in that element\n"
        "- Global color_palette: 5 hex values that define the mood of the whole piece\n"
        "- Infer complementary elements from context if needed (backgrounds, textures, secondary objects)\n"
        "- Output ONLY valid JSON. No text before or after. No markdown. No code blocks."
    ),
}

_COMPOSE_PROMPT_LABEL: dict[str, str] = {
    "main": "Compose Prompt",
}


def _sanitize_compose_variants_map(value: Any) -> dict[str, list[dict[str, str]]]:
    if not isinstance(value, dict):
        raise ValueError("promptVariants must be an object")
    out: dict[str, list[dict[str, str]]] = {}
    for key in DEFAULT_COMPOSE_PROMPTS:
        raw_list = value.get(key, [])
        if not isinstance(raw_list, list):
            continue
        cleaned_list: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            vid = str(item.get("id", "")).strip()
            vlabel = str(item.get("label", "")).strip()
            vtext = str(item.get("text", "")).strip()
            if not vid or not vlabel or vid in seen_ids:
                continue
            seen_ids.add(vid)
            cleaned_list.append({"id": vid, "label": vlabel, "text": vtext})
        out[key] = cleaned_list
    return out


def _sanitize_compose_active_variants_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("promptActiveVariants must be an object")
    out: dict[str, str] = {}
    for key in DEFAULT_COMPOSE_PROMPTS:
        out[key] = str(value.get(key, "")).strip()
    return out


_STUDIO_FLAIR_INSTRUCTION = (
    "Also apply an artistic flair of {flair_value}/100 to the enhancement.\n"
    "At 0: stay completely literal — no artistic interpretation beyond what was explicitly requested.\n"
    "At 50: introduce moderate aesthetic choices — cinematic lighting, balanced composition, slightly idealized forms.\n"
    "At 100: maximum flair — dramatic cinematic staging, bold aesthetic vision, and where human figures are present, "
    "heightened and idealized proportions with a strong sense of stylized sensuality.\n"
    "Interpolate naturally and proportionally between these anchors based on the given value."
)

_STUDIO_ASPECT_INSTRUCTION = (
    "The target image will be generated at {aspect_ratio} aspect ratio ({aspect_mode} orientation).\n"
    "Ensure your composition guidance — framing, subject placement, camera angle, and any depth-of-field "
    "or cropping decisions — is specifically tailored for this {aspect_mode} format."
)

_STUDIO_REFERENCE_INSTRUCTION = (
    "STYLE REFERENCE (extracted from a CivitAI generation):\n"
    "{reference_prompt}\n\n"
    "Use the above as your visual and stylistic foundation: extract the artistic style, quality tags, "
    "rendering keywords, LoRA trigger words, and lighting language it implies. "
    "Do NOT copy the reference's subject, characters, or scene — the user's idea below is what you enhance. "
    "Treat the reference purely as a style and quality guide."
)


_BRAIN_DEFAULT_VARIANTS = [
    {
        "id": "builtin-variations",
        "label": "Variations",
        "text": (
            "You are a prompt editor for image generation. "
            "Given an original prompt and an edit instruction, output ONLY a valid JSON array. "
            "Each item must contain keys 'change_description' and 'new_prompt'. "
            "Each new_prompt must be a distinct variation of the ORIGINAL prompt that follows the instruction. "
            "Do not output markdown fences or extra commentary."
        ),
    },
    {
        "id": "builtin-story",
        "label": "Story",
        "text": (
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
        ),
    },
]


def _sanitize_prompt_variants_map(value: Any) -> dict[str, list[dict[str, str]]]:
    if not isinstance(value, dict):
        raise ValueError("promptVariants must be an object")

    out: dict[str, list[dict[str, str]]] = {}
    for key in DEFAULT_CUSTOM_PROMPTS:
        raw_list = value.get(key, [])
        if not isinstance(raw_list, list):
            continue
        cleaned_list: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            vid = str(item.get("id", "")).strip()
            vlabel = str(item.get("label", "")).strip()
            vtext = str(item.get("text", "")).strip()
            if not vid or not vlabel or vid in seen_ids:
                continue
            seen_ids.add(vid)
            cleaned_list.append({"id": vid, "label": vlabel, "text": vtext})
        out[key] = cleaned_list
    return out


def _sanitize_prompt_active_variants_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("promptActiveVariants must be an object")

    out: dict[str, str] = {}
    for key in DEFAULT_CUSTOM_PROMPTS:
        out[key] = str(value.get(key, "")).strip()
    return out


@models_api_bp.get("/models/settings/prompts")
def get_custom_prompts():
    data = _ensure_registry()
    saved: dict = data.get("settings", {}).get("customPrompts", {})
    merged = {
        k: saved.get(k) or DEFAULT_CUSTOM_PROMPTS[k] for k in DEFAULT_CUSTOM_PROMPTS
    }

    prompt_variants_raw = saved.get("promptVariants", {})
    if not isinstance(prompt_variants_raw, dict):
        prompt_variants_raw = {}
    prompt_active_raw = saved.get("promptActiveVariants", {})
    if not isinstance(prompt_active_raw, dict):
        prompt_active_raw = {}

    prompt_variants: dict[str, list[dict[str, str]]] = {
        k: [] for k in DEFAULT_CUSTOM_PROMPTS
    }
    for key in DEFAULT_CUSTOM_PROMPTS:
        raw_list = prompt_variants_raw.get(key, [])
        if isinstance(raw_list, list):
            cleaned: list[dict[str, str]] = []
            seen_ids: set[str] = set()
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                vid = str(item.get("id", "")).strip()
                vlabel = str(item.get("label", "")).strip()
                vtext = str(item.get("text", "")).strip()
                if not vid or not vlabel or vid in seen_ids:
                    continue
                seen_ids.add(vid)
                cleaned.append({"id": vid, "label": vlabel, "text": vtext})
            prompt_variants[key] = cleaned

    prompt_active_variants: dict[str, str] = {
        key: str(prompt_active_raw.get(key, "")).strip()
        for key in DEFAULT_CUSTOM_PROMPTS
    }

    # Legacy migration: keep old keys working and expose them through the generic maps.
    if not prompt_variants.get("describeFull"):
        legacy_variants = saved.get("describeFullVariants", [])
        if isinstance(legacy_variants, list):
            migrated: list[dict[str, str]] = []
            for item in legacy_variants:
                if not isinstance(item, dict):
                    continue
                vid = str(item.get("id", "")).strip()
                vlabel = str(item.get("label", "")).strip()
                vtext = str(item.get("text", "")).strip()
                if vid and vlabel:
                    migrated.append({"id": vid, "label": vlabel, "text": vtext})
            prompt_variants["describeFull"] = migrated
    if not prompt_active_variants.get("describeFull"):
        prompt_active_variants["describeFull"] = str(
            saved.get("describeFullActiveId", "")
        ).strip()

    if not prompt_variants.get("editVariants"):
        legacy_brain_variants = saved.get("editVariantsVariants", None)
        if isinstance(legacy_brain_variants, list):
            migrated_brain: list[dict[str, str]] = []
            for item in legacy_brain_variants:
                if not isinstance(item, dict):
                    continue
                vid = str(item.get("id", "")).strip()
                vlabel = str(item.get("label", "")).strip()
                vtext = str(item.get("text", "")).strip()
                if vid and vlabel:
                    migrated_brain.append({"id": vid, "label": vlabel, "text": vtext})
            prompt_variants["editVariants"] = migrated_brain
        else:
            prompt_variants["editVariants"] = _BRAIN_DEFAULT_VARIANTS
    if not prompt_active_variants.get("editVariants"):
        prompt_active_variants["editVariants"] = str(
            saved.get("editVariantsActiveId", "")
        ).strip()

    return jsonify(
        {
            "prompts": merged,
            "defaults": DEFAULT_CUSTOM_PROMPTS,
            "labels": _PROMPT_LABEL,
            "promptVariants": prompt_variants,
            "promptActiveVariants": prompt_active_variants,
            # Legacy fields returned for backward compatibility with older frontends.
            "describeFullVariants": prompt_variants.get("describeFull", []),
            "describeFullActiveId": prompt_active_variants.get("describeFull", ""),
            "editVariantsVariants": prompt_variants.get("editVariants", []),
            "editVariantsActiveId": prompt_active_variants.get("editVariants", ""),
        }
    )


@models_api_bp.patch("/models/settings/queue-free-memory")
def update_queue_free_memory_setting():
    payload = request.get_json(silent=True) or {}
    if "queueFreeMemoryBetweenModels" not in payload:
        return jsonify({"error": "queueFreeMemoryBetweenModels is required"}), 400
    value = bool(payload["queueFreeMemoryBetweenModels"])
    data = _ensure_registry()
    data.setdefault("settings", {})["queueFreeMemoryBetweenModels"] = value
    _save_registry(data)
    return jsonify({"queueFreeMemoryBetweenModels": value})


# ---------------------------------------------------------------------------
# Export configuration as ZIP
# ---------------------------------------------------------------------------


@models_api_bp.get("/models/settings/export")
def export_config():
    """Export the full registry (workflows, settings, prompts) as a ZIP file."""
    data = _ensure_registry()

    json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("openhiker_config.json", json_bytes)
    buf.seek(0)

    filename = f"openhiker-config-{date.today().isoformat()}.zip"
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )


@models_api_bp.patch("/models/settings/prompts")
def update_custom_prompts():
    payload = request.get_json(silent=True) or {}

    data = _ensure_registry()
    existing_custom: dict = dict(data.get("settings", {}).get("customPrompts", {}))
    cleaned: dict = dict(existing_custom)

    # Update prompt texts when provided.
    if "prompts" in payload:
        incoming = payload["prompts"]
        if not isinstance(incoming, dict):
            return jsonify({"error": "prompts must be an object"}), 400
        for k in DEFAULT_CUSTOM_PROMPTS:
            v = str(incoming.get(k, "")).strip()
            cleaned[k] = v  # empty string = use default at runtime

    # Update variants when provided.
    if "promptVariants" in payload:
        try:
            cleaned["promptVariants"] = _sanitize_prompt_variants_map(
                payload["promptVariants"]
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    if "promptActiveVariants" in payload:
        try:
            cleaned["promptActiveVariants"] = _sanitize_prompt_active_variants_map(
                payload["promptActiveVariants"]
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    data["settings"]["customPrompts"] = cleaned
    _save_registry(data)
    return jsonify({"ok": True})


@models_api_bp.get("/models/settings/studio-prompts")
def get_studio_prompts():
    data = _ensure_registry()
    saved: dict = data.get("settings", {}).get("studioPrompts", {})

    prompts = {k: str(saved.get(k, "") or "").strip() or v for k, v in DEFAULT_STUDIO_PROMPTS.items()}

    variants_raw = saved.get("promptVariants", {})
    if not isinstance(variants_raw, dict):
        variants_raw = {}
    active_raw = saved.get("promptActiveVariants", {})
    if not isinstance(active_raw, dict):
        active_raw = {}

    prompt_variants: dict[str, list] = {}
    for key in DEFAULT_STUDIO_PROMPTS:
        raw_list = variants_raw.get(key, [])
        cleaned_list: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        if isinstance(raw_list, list):
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                vid = str(item.get("id", "")).strip()
                vlabel = str(item.get("label", "")).strip()
                vtext = str(item.get("text", "")).strip()
                if not vid or not vlabel or vid in seen_ids:
                    continue
                seen_ids.add(vid)
                cleaned_list.append({"id": vid, "label": vlabel, "text": vtext})
        prompt_variants[key] = cleaned_list

    prompt_active_variants = {
        key: str(active_raw.get(key, "")).strip()
        for key in DEFAULT_STUDIO_PROMPTS
    }

    return jsonify({
        "defaults": DEFAULT_STUDIO_PROMPTS,
        "labels": _STUDIO_PROMPT_LABEL,
        "prompts": prompts,
        "promptVariants": prompt_variants,
        "promptActiveVariants": prompt_active_variants,
    })


@models_api_bp.patch("/models/settings/studio-prompts")
def update_studio_prompts():
    payload = request.get_json(silent=True) or {}

    data = _ensure_registry()
    existing: dict = dict(data.get("settings", {}).get("studioPrompts", {}))
    cleaned: dict = dict(existing)

    if "prompts" in payload:
        incoming = payload["prompts"]
        if not isinstance(incoming, dict):
            return jsonify({"error": "prompts must be an object"}), 400
        for k in DEFAULT_STUDIO_PROMPTS:
            cleaned[k] = str(incoming.get(k, "")).strip()

    if "promptVariants" in payload:
        try:
            cleaned["promptVariants"] = _sanitize_prompt_variants_map(payload["promptVariants"])
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    if "promptActiveVariants" in payload:
        try:
            cleaned["promptActiveVariants"] = _sanitize_prompt_active_variants_map(
                payload["promptActiveVariants"]
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    data["settings"]["studioPrompts"] = cleaned
    _save_registry(data)
    return jsonify({"ok": True})


@models_api_bp.get("/models/settings/compose-prompts")
def get_compose_prompts():
    data = _ensure_registry()
    saved: dict = data.get("settings", {}).get("composePrompts", {})

    prompts = {k: str(saved.get(k, "") or "").strip() or v for k, v in DEFAULT_COMPOSE_PROMPTS.items()}

    variants_raw = saved.get("promptVariants", {})
    if not isinstance(variants_raw, dict):
        variants_raw = {}
    active_raw = saved.get("promptActiveVariants", {})
    if not isinstance(active_raw, dict):
        active_raw = {}

    prompt_variants: dict[str, list] = {}
    for key in DEFAULT_COMPOSE_PROMPTS:
        raw_list = variants_raw.get(key, [])
        cleaned_list: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        if isinstance(raw_list, list):
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                vid = str(item.get("id", "")).strip()
                vlabel = str(item.get("label", "")).strip()
                vtext = str(item.get("text", "")).strip()
                if not vid or not vlabel or vid in seen_ids:
                    continue
                seen_ids.add(vid)
                cleaned_list.append({"id": vid, "label": vlabel, "text": vtext})
        prompt_variants[key] = cleaned_list

    prompt_active_variants = {
        key: str(active_raw.get(key, "")).strip()
        for key in DEFAULT_COMPOSE_PROMPTS
    }

    return jsonify({
        "defaults": DEFAULT_COMPOSE_PROMPTS,
        "labels": _COMPOSE_PROMPT_LABEL,
        "prompts": prompts,
        "promptVariants": prompt_variants,
        "promptActiveVariants": prompt_active_variants,
    })


@models_api_bp.patch("/models/settings/compose-prompts")
def update_compose_prompts():
    payload = request.get_json(silent=True) or {}

    data = _ensure_registry()
    existing: dict = dict(data.get("settings", {}).get("composePrompts", {}))
    cleaned: dict = dict(existing)

    if "prompts" in payload:
        incoming = payload["prompts"]
        if not isinstance(incoming, dict):
            return jsonify({"error": "prompts must be an object"}), 400
        for k in DEFAULT_COMPOSE_PROMPTS:
            cleaned[k] = str(incoming.get(k, "")).strip()

    if "promptVariants" in payload:
        try:
            cleaned["promptVariants"] = _sanitize_compose_variants_map(payload["promptVariants"])
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    if "promptActiveVariants" in payload:
        try:
            cleaned["promptActiveVariants"] = _sanitize_compose_active_variants_map(
                payload["promptActiveVariants"]
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    data["settings"]["composePrompts"] = cleaned
    _save_registry(data)
    return jsonify({"ok": True})
