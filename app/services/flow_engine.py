"""
flow_engine.py
==============
Carga y valida los flujos de Nomad Studio desde archivos JSON.

Flujos built-in:  app/instructions/index.json  +  app/instructions/flows/**/*.json
Packs de usuario: directorios registrados en registry['installedPacks']

El motor NO renderiza UI — solo devuelve datos estructurados.
El renderizado es responsabilidad del cliente (flow_renderer.js).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Rutas base ────────────────────────────────────────────────────────────────

_INSTRUCTIONS_DIR = Path(__file__).parent.parent / "instructions"
_INDEX_FILE = _INSTRUCTIONS_DIR / "index.json"
_STEP_TYPES_FILE = _INSTRUCTIONS_DIR / "types" / "step_types.json"
_WORKFLOWS_DIR = Path(__file__).parent.parent / "workflows"
_APP_DIR = Path(__file__).parent.parent


# ── Helpers de I/O ────────────────────────────────────────────────────────────


def _read_json(path: Path) -> Any:
    """Lee y parsea un JSON. Devuelve None si el fichero no existe o falla."""
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw)
    except FileNotFoundError:
        return None
    except Exception:
        logger.warning("flow_engine: failed to parse JSON at %s", path)
        return None


# ── Step types ────────────────────────────────────────────────────────────────


def load_step_types() -> dict[str, Any]:
    """Devuelve el mapa de tipos de step { type_id → definition }."""
    data = _read_json(_STEP_TYPES_FILE)
    if isinstance(data, dict):
        return data.get("step_types", {})
    return {}


# ── Index ─────────────────────────────────────────────────────────────────────


def _load_index_entries() -> list[dict[str, Any]]:
    """Lee index.json y devuelve la lista de entradas de flujo."""
    data = _read_json(_INDEX_FILE)
    if isinstance(data, dict):
        return [f for f in data.get("flows", []) if isinstance(f, dict)]
    return []


# ── Definición de un flujo ────────────────────────────────────────────────────


def load_flow_file(relative_file: str) -> dict[str, Any] | None:
    """Carga el JSON de definición de un flujo por su path relativo al dir instructions/."""
    path = _INSTRUCTIONS_DIR / relative_file
    data = _read_json(path)
    return data if isinstance(data, dict) else None


# ── Generador de flows desde _oj_refine_meta ─────────────────────────────────


def _build_mix_flow_definition(
    meta: dict[str, Any],
    workflow_rel_path: str,
) -> dict[str, Any]:
    """Generates a complete flow definition for mix flows (2+ image inputs)."""
    flow_id = str(meta.get("id", "")).strip()
    image_node = str(meta.get("image_node", "")).strip()
    image_node_2 = str(meta.get("image_node_2", "")).strip()
    vision_assist = meta.get("vision_assist")
    # Opt-in per-flow (e.g. Clothes Mix): let the user skip the reference
    # photo entirely and drive it off the manual description field alone
    # ("What is the clothing?" / subject_input on image_2_step, below).
    # Face Swap/Photo Session don't set this — their 2nd image is the actual
    # subject being composited, a text description can't stand in for it.
    image_2_optional = bool(meta.get("image_2_optional", False))

    # Split params: prompt-type text param goes to prompt_input step; rest go to workflow_params
    all_params = [p for p in meta.get("params", []) if isinstance(p, dict)]
    prompt_param = next((p for p in all_params if p.get("type") == "text"), None)
    other_params = [p for p in all_params if p.get("type") != "text"]

    # Build workflow_params fields (non-text params, e.g. seed)
    fields: list[dict[str, Any]] = []
    for p in other_params:
        field = {k: v for k, v in p.items() if k != "key"}
        field["adv_key"] = str(p.get("key", ""))
        fields.append(field)

    # An engine_select field (choosing between e.g. Klein 9B/4B, or a
    # Normal/Turbo LoRA variant) gets pulled out into its own "Choose engine"
    # step at the very top of the wizard — mirrors Create's "Choose a
    # workflow" step (workflow_picker) instead of being buried inside the
    # Parameters block.
    engine_field = next((f for f in fields if f.get("type") == "engine_select"), None)
    if engine_field is not None:
        fields = [f for f in fields if f is not engine_field]

    # Prompt adv_key for the action input_map
    prompt_adv_key = str(prompt_param.get("key", "")) if prompt_param else ""

    image_2_step: dict[str, Any] = {
        "id": "image_2",
        "type": "image_picker",
        "label": str(meta.get("image_2_label", "Clothing reference")),
        "required": not image_2_optional,
        "has_vision_analysis": False,
    }
    if image_2_optional:
        # Client-side hint (flow-generate-btn.js / _snapshotMix): this image
        # slot may stay empty at Generate time as long as its own manual
        # description field (subject_input, just below) has text instead.
        image_2_step["optional"] = True
        image_2_step["hint"] = "Optional — leave empty and describe it below instead."
    # Optional manual description field for the second (reference) image —
    # same "Who is the subject?" input pattern as the primary image, just
    # aimed at whatever the reference picture shows (e.g. Clothes Mix: the
    # user can type "red bikini" themselves). Purely additive: whatever's
    # typed here gets combined with "Describe reference"'s AI output at
    # prompt-assembly time (see flow-step-prompt-input.js's {{clothing}}
    # handling), it doesn't replace it. Only enabled when vision_assist
    # actually targets image_2 and declares manual_label — flows with no
    # vision_assist (Face Swap, Photo Session) don't get this field.
    if (
        vision_assist
        and isinstance(vision_assist, dict)
        and str(vision_assist.get("image_ref", "")) == "image_2"
        and vision_assist.get("manual_label")
    ):
        image_2_step["subject_input"] = True
        image_2_step["subject_label"] = str(vision_assist.get("manual_label", ""))
        image_2_step["subject_placeholder"] = str(vision_assist.get("manual_placeholder", ""))

    image_step: dict[str, Any] = {
        "id": "image",
        "type": "image_picker",
        "label": str(meta.get("image_label", "Subject")),
        "required": True,
        "has_vision_analysis": False,
    }
    # "Who is the subject?" only makes sense for face/subject-compositing mixes
    # (Face Swap, Clothes Mix, Photo Session). Flows that just combine two
    # images without a subject concept (e.g. a style-transfer image + a photo
    # to edit) opt out with "no_subject_input": true in the workflow's meta.
    if not bool(meta.get("no_subject_input", False)):
        image_step["subject_input"] = True
        image_step["subject_label"] = "Who is the subject?"
        image_step["subject_placeholder"] = "e.g. woman, man, person, child…"
        image_step["subject_default"] = "person"
    # Opt-in per flow: reuses the same "Styles" catalog button as the
    # single-image refine flows (flow-step-image-picker.js) — for mixes where
    # this first image slot IS a style reference (e.g. Untwisting RoPE style
    # transfer), not a subject/content photo.
    if bool(meta.get("style_image_input", False)):
        image_step["style_image_input"] = True
    # Optional "detect via vision" pair of round icon buttons next to
    # "Who is the subject?" — eye button runs a quick vision describe on
    # image 1 and fills the subject field with the result; the second
    # button (makeVisionModelBtn, flow-model-picker.js) picks which vision
    # model handles it, same picker used everywhere else. Opt-in via a
    # subject_vision_assist block in the workflow's meta (e.g. Photo
    # Session) — flows that don't declare one (Clothes Mix, Face Swap) keep
    # the plain text-only field.
    subject_vision_assist = meta.get("subject_vision_assist")
    if isinstance(subject_vision_assist, dict) and subject_vision_assist.get("system_prompt"):
        image_step["subject_vision_assist"] = {
            "system_prompt": str(subject_vision_assist.get("system_prompt", "")),
        }

    steps: list[dict[str, Any]] = [
        image_step,
        image_2_step,
    ]

    if engine_field is not None:
        steps.insert(0, {
            "id": "engine",
            "type": "workflow_params",
            "label": "Choose engine",
            # workflow_params steps skip their own label by default (it's
            # meant for the "Parameters" block, which reads fine headerless)
            # — this one-field step needs it shown, like Create's "Choose
            # engine" workflow_picker (flow-render-all.js's skipLabel check).
            "show_label": True,
            "workflow_file": workflow_rel_path,
            "image_node": image_node,
            "fields": [engine_field],
            # This step's own "Advanced" (Quantization for workflow_file)
            # would just duplicate the real "params" step below — same file
            # on load, and its adv_values are never read (input_map always
            # points at steps.params.output.adv_values, never
            # steps.engine.output.adv_values) — see
            # flow-step-workflow-params.js's skip_quantization check.
            "skip_quantization": True,
        })

    if vision_assist and isinstance(vision_assist, dict) and prompt_param:
        steps.append({
            "id": "vision_assist",
            "type": "vision_describe",
            "label": "Describe reference",
            "image_from": "steps." + str(vision_assist.get("image_ref", "image_2")) + ".output.image_data_url",
            "system_prompt": str(vision_assist.get("system_prompt", "")),
            "output_to": str(vision_assist.get("output_to_param", "prompt")),
            "subject_from": "steps.image.output.subject",
        })

    if prompt_param:
        step: dict[str, Any] = {
            "id": "prompt",
            "type": "prompt_input",
            "label": prompt_param.get("label", "Prompt"),
            # Common to every style flow: adds the "Edit prompt" (P/Idea/S +
            # Refine-with-LLM) button next to the history icon
            # (flow-step-prompt-input.js) whenever the sibling image step is
            # itself a style reference.
            "style_prompt_edit": bool(meta.get("style_image_input", False)),
            "required": False,
            "placeholder": str(prompt_param.get("placeholder", "")),
            "rows": 3,
        }
        if prompt_param.get("default"):
            # Static default text — pre-fills the textarea with editable text
            # on load, unlike "placeholder" which only shows greyed hint text
            # and is never submitted. Set even when vision_assist is present:
            # "Describe reference" is an optional shortcut that overwrites
            # this text with an AI-generated one, not a requirement to fill
            # the field in the first place.
            step["default"] = str(prompt_param.get("default", ""))
        if vision_assist:
            step["prefill_from"] = "steps.vision_assist.output.description"
        # Base-prompt presets (e.g. Mix's Clothes flow: Simple / Detailed /
        # Preserve everything). Each item is {label, text, system_prompt?} —
        # "text" fills the textarea, and if "system_prompt" is present the
        # matching vision_assist step's instruction switches to it too, so
        # "Describe reference" generates in the same style as the picked
        # preset (see flow-step-prompt-input.js's preset click handler).
        prompt_presets = meta.get("prompt_presets")
        if isinstance(prompt_presets, list) and prompt_presets:
            step["presets"] = prompt_presets
        steps.append(step)

    if fields:
        steps.append({
            "id": "params",
            "type": "workflow_params",
            "label": "Parameters",
            "workflow_file": workflow_rel_path,
            "image_node": image_node,
            "fields": fields,
        })

    image_2_entry: dict[str, Any] = {"dataUrl": "steps.image_2.output.image_data_url", "nodeId": image_node_2}
    if image_2_optional:
        # Read by flow-generate-btn.js/_snapshotMix: this slot doesn't block
        # Generate on its own — either the image or this text ref must resolve.
        image_2_entry["optional"] = True
        image_2_entry["textFallback"] = "steps.image_2.output.subject"

    input_map: dict[str, Any] = {
        # Dynamic (not the literal path) whenever an "engine" or "params" step
        # exists: an engine_select field can swap stepDef.workflow_file at
        # runtime (flow-step-workflow-params.js's esApplyEngine), and that
        # step always seeds 'workflow_file' with workflow_rel_path on first
        # render regardless, so this stays equivalent for flows with no
        # engine_select.
        "workflowFile": (
            "steps.engine.output.workflow_file" if engine_field is not None
            else ("steps.params.output.workflow_file" if fields else workflow_rel_path)
        ),
        "images": [
            {"dataUrl": "steps.image.output.image_data_url", "nodeId": image_node},
            image_2_entry,
        ],
        "advancedValues": "steps.params.output.adv_values" if fields else {},
        "cardPrompt": "steps.prompt.output.prompt_text" if prompt_param else "",
    }
    if prompt_adv_key:
        input_map["promptKey"] = prompt_adv_key
        input_map["promptValue"] = "steps.prompt.output.prompt_text"

    steps.append({
        "id": "generate",
        "type": "action",
        "label": "Generate",
        "calls": "generation.submit_mix",
        "input_map": input_map,
    })
    steps.append({
        # No "actions" key: the flow engine has never rendered one. Every flow
        # carried a list here and showResultActions() (flow-gallery.js) returns
        # before reading it for plain create/refine/mix flows, so the lists were
        # inert config that read like a promise. They described buttons that do
        # not exist — Save, Upscale, Regenerate, Re-enhance — while what the
        # result really offers is "Apply params" on the card and the refine
        # catalogue above the grid. Removed from all 126 flow files; writing new
        # ones here would put them straight back.
        "id": "result",
        "type": "result_view",
        "label": "Result",
    })

    return {
        "id": flow_id,
        "label": str(meta.get("label", flow_id)),
        "category": "mix",
        "group": str(meta.get("group", "core")),
        "description": str(meta.get("description", "")),
        "card_desc": str(meta.get("card_desc", "")),
        "card_tags": list(meta.get("card_tags", [])),
        "card_css_modifier": str(meta.get("card_css_modifier", "")),
        "llm_required": bool(meta.get("llm_required", False)),
        "comfyui_required": True,
        "steps": steps,
    }


def _build_refine_flow_definition(
    meta: dict[str, Any],
    workflow_rel_path: str,
) -> dict[str, Any]:
    """Generates a complete flow definition from a workflow's _oj_refine_meta block."""
    flow_id = str(meta.get("id", "")).strip()
    image_node = str(meta.get("image_node", "")).strip()

    fields: list[dict[str, Any]] = []
    for p in meta.get("params", []):
        if not isinstance(p, dict):
            continue
        field = {k: v for k, v in p.items() if k != "key"}
        field["adv_key"] = str(p.get("key", ""))
        fields.append(field)

    # Common to every style flow: the prompt_history field gets the "Edit
    # prompt" (P/Idea/S + Refine-with-LLM) button next to its history icon
    # (flow-step-workflow-params.js) whenever the image step is itself a
    # style reference — same rule as the mix-flow prompt_input step below.
    if bool(meta.get("style_image_input", False)):
        for f in fields:
            if f.get("type") == "prompt_history":
                f["style_prompt_edit"] = True

    # Rule for ALL outpaints: every pad_canvas flow gets a dynamic "Fill" combo
    # (transparent / edge blur / green / magenta) that drives both the preview
    # and the preprocess fill colour. Injected here so it never has to be
    # hardcoded per workflow. Skipped if the flow already defines its own.
    preprocess = meta.get("preprocess")
    if isinstance(preprocess, dict) and str(preprocess.get("type", "")) == "pad_canvas":
        has_bg = any(str(f.get("adv_key", "")) == "_preprocess.background" for f in fields)
        if not has_bg:
            authored_bg = str(preprocess.get("background", "transparent")).strip() or "transparent"
            options = [
                {"value": "transparent", "label": "Transparent"},
                {"value": "edge_blur", "label": "Edge blur"},
                {"value": "0,0,0", "label": "Black"},
                {"value": "255,255,255", "label": "White"},
                {"value": "0,255,0", "label": "Green"},
                {"value": "255,0,255", "label": "Magenta"},
            ]
            if authored_bg not in [o["value"] for o in options]:
                options.insert(0, {"value": authored_bg, "label": authored_bg})
            bg_field = {
                "id": "bg",
                "type": "select",
                "label": "Fill",
                "adv_key": "_preprocess.background",
                "default": authored_bg,
                "options": options,
            }
            idx = next(
                (i for i, f in enumerate(fields) if f.get("type") == "canvas_preview"),
                len(fields),
            )
            fields.insert(idx, bg_field)

    return {
        "id": flow_id,
        "label": str(meta.get("label", flow_id)),
        "category": "refine",
        "group": str(meta.get("group", "core")),
        "description": str(meta.get("description", "")),
        "card_desc": str(meta.get("card_desc", "")),
        "card_tags": list(meta.get("card_tags", [])),
        "card_css_modifier": str(meta.get("card_css_modifier", "")),
        "llm_required": bool(meta.get("llm_required", False)),
        "comfyui_required": True,
        "steps": [
            {
                "id": "image",
                "type": "image_picker",
                "label": "Source image",
                "required": True,
                # Vision model selector is opt-in per flow: set "vision_input": true
                # in the workflow's flow_data node for flows that analyse the input
                # image (e.g. describe-then-edit). Upscale/refine don't need it.
                "has_vision_analysis": bool(meta.get("vision_input", False)),
                # Single-image refine flows accept multiple images: the frontend runs
                # the same flow once per selected image (sequential queue).
                "multiple": True,
                # Opt-in per flow: set "style_image_input": true in the workflow's
                # flow_data node for flows where the source image IS a style
                # reference (e.g. RF Inversion style transfer) — adds a "Styles"
                # button below Downscale that loads a saved style's own image
                # straight into this picker instead of just injecting its prompt.
                "style_image_input": bool(meta.get("style_image_input", False)),
            },
            {
                "id": "params",
                "type": "workflow_params",
                "label": "Parameters",
                "workflow_file": workflow_rel_path,
                "image_node": image_node,
                "fields": fields,
            },
            {
                "id": "generate",
                "type": "action",
                "label": "Refine",
                "calls": "generation.submit_refine",
                "input_map": {
                    "workflowFile":   "steps.params.output.workflow_file",
                    "imageDataUrl":   "steps.image.output.image_data_url",
                    "advancedValues": "steps.params.output.adv_values",
                    "cardPrompt":     "steps.params.output.field_prompt",
                },
            },
            {
                # See the note on the other result step above: no "actions".
                "id": "result",
                "type": "result_view",
                "label": "Result",
            },
        ],
    }


def _extract_flow_data_node(workflow: dict[str, Any]) -> dict[str, Any] | None:
    """Returns the parsed metadata from a node titled 'flow_data', or None if absent."""
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        if str(node.get("_meta", {}).get("title", "")) != "flow_data":
            continue
        raw_text = str(node.get("inputs", {}).get("value", "")).strip()
        if not raw_text:
            continue
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            logger.warning("flow_engine: invalid JSON in flow_data node")
    return None


def _load_refine_flows_from_workflows(
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    """Scans app/workflows/ for JSON files containing a 'flow_data' node and generates flow entries."""
    results: list[dict[str, Any]] = []

    if not _WORKFLOWS_DIR.is_dir():
        logger.warning("flow_engine: workflows dir not found: %s", _WORKFLOWS_DIR)
        return results

    for wf_path in sorted(_WORKFLOWS_DIR.glob("**/*.json")):
        data = _read_json(wf_path)
        if not isinstance(data, dict):
            continue

        meta = _extract_flow_data_node(data)
        if meta is None:
            continue

        flow_id = str(meta.get("id", "")).strip()
        if not flow_id:
            logger.warning("flow_engine: flow_data node missing 'id' in %s", wf_path)
            continue

        try:
            workflow_rel_path = wf_path.relative_to(_APP_DIR).as_posix()
        except ValueError:
            logger.warning("flow_engine: workflow not under app dir: %s", wf_path)
            continue

        is_mix = str(meta.get("category", "")).strip() == "mix" or flow_id.startswith("mix.")
        if is_mix:
            definition = _build_mix_flow_definition(meta, workflow_rel_path)
            category = "mix"
        else:
            definition = _build_refine_flow_definition(meta, workflow_rel_path)
            category = "refine"
        entry = {
            "id": flow_id,
            "label": str(meta.get("label", flow_id)),
            "category": category,
            "llm_required": bool(meta.get("llm_required", False)),
            "comfyui_required": True,
            "status": "active",
            "pack": "builtin",
        }
        results.append(_enrich_entry(entry, definition, settings))

    return results


# ── Disponibilidad ────────────────────────────────────────────────────────────


def check_availability(
    flow_meta: dict[str, Any],
    settings: dict[str, Any],
) -> tuple[bool, str]:
    """
    Comprueba si un flujo puede ejecutarse con la configuración actual.

    Devuelve (available: bool, reason: str).
    reason es "" cuando available es True.
    """
    # LLM requerido → LM Studio debe estar configurado con modelo seleccionado
    if flow_meta.get("llm_required"):
        lms_url = str(settings.get("lmStudioApiUrl", "") or "").strip()
        lms_model = str(
            settings.get("lmStudioPromptModel", "")
            or settings.get("lmStudioModel", "")
            or ""
        ).strip()
        if not lms_url:
            return False, "LM Studio URL not configured"
        if not lms_model:
            return False, "LM Studio model not selected"

    # ComfyUI requerido → siempre true por ahora (la app lo necesita siempre)
    # Podría validarse contra settings.comfyApiUrl si lo necesitamos en el futuro

    return True, ""


# ── Carga completa de flujos ──────────────────────────────────────────────────


def _mark_multi_image_input(definition: dict[str, Any] | None) -> None:
    """
    For single-image refine flows (exactly one image_picker step), flag that
    step as "multiple": True so the frontend lets the user select several
    images and runs the flow once per image (sequential queue).

    Flows with more than one image_picker (mix/compose-style, two distinct
    reference images) are left untouched — multi-select there would be
    ambiguous about which picker the extra images belong to.
    """
    if not isinstance(definition, dict):
        return
    if str(definition.get("category", "")).strip() != "refine":
        return
    steps = definition.get("steps")
    if not isinstance(steps, list):
        return
    pickers = [s for s in steps if isinstance(s, dict) and s.get("type") == "image_picker"]
    if len(pickers) != 1:
        return
    pickers[0]["multiple"] = True


def _enrich_entry(
    entry: dict[str, Any],
    definition: dict[str, Any] | None,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """
    Fusiona la entrada del index con la definición completa del flujo
    y añade el campo `available` calculado en tiempo de carga.
    """
    _mark_multi_image_input(definition)
    flow_id = str(entry.get("id", "")).strip()

    # llm_required: el index es la fuente de verdad; la definición es un fallback
    llm_required = bool(
        entry.get(
            "llm_required",
            definition.get("llm_required", False) if definition else False,
        )
    )
    comfyui_required = bool(
        entry.get(
            "comfyui_required",
            definition.get("comfyui_required", True) if definition else True,
        )
    )

    available, unavail_reason = check_availability(
        {"llm_required": llm_required, "comfyui_required": comfyui_required},
        settings,
    )

    description = ""
    card_tags: list[str] = []
    card_desc = ""
    card_css_modifier = ""
    entry_category = ""
    complexity = None
    if definition:
        description = str(definition.get("description", "")).strip()
        card_tags = [str(t) for t in definition.get("card_tags", []) if str(t).strip()]
        card_desc = str(definition.get("card_desc", "")).strip()
        card_css_modifier = str(definition.get("card_css_modifier", "")).strip()
        entry_category = str(definition.get("entry_category", "")).strip()
        complexity = definition.get("complexity")

    return {
        "id": flow_id,
        "action": flow_id.split(".", 1)[1] if "." in flow_id else flow_id,
        "label": str(entry.get("label", flow_id)),
        "category": str(entry.get("category", "create")),
        "description": description,
        "card_tags": card_tags,
        "card_desc": card_desc,
        "card_css_modifier": card_css_modifier,
        "entry_category": entry_category,
        "complexity": complexity,
        "llm_required": llm_required,
        "comfyui_required": comfyui_required,
        "status": str(entry.get("status", "planned")),
        "pack": str(entry.get("pack", "builtin")),  # "builtin" | pack_id
        # Display grouping (Refine's expansion packs) — distinct from "pack"
        # above: "pack" is install provenance (builtin/pack_id/addon:x),
        # "group" is what section a flow's card renders under. Definition
        # (flow.json / embedded flow_data) is the source of truth; falls
        # back to the index entry, then "core".
        "group": str(
            (definition.get("group") if definition else None)
            or entry.get("group")
            or "core"
        ),
        "available": available,
        "unavail_reason": unavail_reason,
        "definition": definition,  # None si el .json no existe aún
    }


def _set_by_path(definition: dict[str, Any], path: str, value: str) -> None:
    """Write one translated text into the flow, by its i18n path
    (PACKAGE_FORMAT.md §7.2): "description",
    "steps.<id>[.fields.<key>].<prop>", "steps.<id>.fields.<key>.options.<value>"."""
    parts = path.split(".")
    if parts == ["description"]:
        definition["description"] = value
        return
    if len(parts) < 3 or parts[0] != "steps":
        return
    step = next((s for s in definition.get("steps") or [] if isinstance(s, dict) and str(s.get("id")) == parts[1]), None)
    if step is None:
        return
    if len(parts) == 3:
        step[parts[2]] = value
        return
    if parts[2] != "fields":
        return
    field = next((f for f in step.get("fields") or []
                  if isinstance(f, dict) and str(f.get("key") or f.get("id")) == parts[3]), None)
    if field is None:
        return
    if len(parts) == 5 and parts[4] != "options":
        field[parts[4]] = value
    elif len(parts) == 6 and parts[4] == "options":
        option = next((o for o in field.get("options") or []
                       if isinstance(o, dict) and str(o.get("value")) == parts[5]), None)
        if option is not None:
            option["label"] = value


def translate_flow(definition: dict[str, Any], pack_dir: Path, lang: str) -> dict[str, Any]:
    """A package carries its own text (PACKAGE_FORMAT.md §7). The flow is
    translated here, as it is served, so the flow page shows it in the user's
    language without every step renderer having to translate on its own.

    Anything the package does not translate stays in its own language."""
    flow_id = str(definition.get("id", ""))
    card = definition.get("card") if isinstance(definition.get("card"), dict) else {}
    for key, target in (("label", "label"), ("desc", "card_desc")):
        texts = card.get(key)
        if isinstance(texts, dict) and texts.get(lang):
            definition[target] = str(texts[lang])
    try:
        table = json.loads((pack_dir / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return definition
    by_path = table.get(flow_id) if isinstance(table, dict) else None
    if not isinstance(by_path, dict):
        return definition
    for key, value in by_path.items():
        if isinstance(value, str) and value.strip():
            _set_by_path(definition, key, value)
    return definition


def load_all_flows(
    settings: dict[str, Any],
    installed_packs: list[dict[str, Any]] | None = None,
    lang: str | None = None,
) -> list[dict[str, Any]]:
    """
    Carga todos los flujos disponibles:
      1. Flujos built-in desde index.json
      2. Flujos de packs instalados (Phase 4 — de momento vacío)

    Devuelve lista ordenada: primero activos, luego planned.
    Cada elemento incluye la key `definition` con el JSON completo del flujo
    (o None si el archivo de definición todavía no existe).
    """
    results: list[dict[str, Any]] = []

    # ── 1. Built-in flows ─────────────────────────────────────────────────────
    for entry in _load_index_entries():
        flow_id = str(entry.get("id", "")).strip()
        file_path = str(entry.get("file", "")).strip()
        if not flow_id:
            continue

        definition = load_flow_file(file_path) if file_path else None
        results.append(_enrich_entry(entry, definition, settings))

    # ── 2. Refine/mix flows from flow_data node in workflow files ─────────────
    refine_ids_from_index = {f["id"] for f in results if f["category"] in ("refine", "mix")}
    for flow in _load_refine_flows_from_workflows(settings):
        if flow["id"] not in refine_ids_from_index:
            results.append(flow)

    # ── 3. User-installed packs ───────────────────────────────────────────────
    # Phase 4: iterar installed_packs, cargar flows desde pack_dir/flows/**/*.json
    for pack in installed_packs or []:
        pack_id = str(pack.get("packId", "")).strip()
        pack_dir = str(pack.get("packDir", "")).strip()
        if not pack_id or not pack_dir:
            continue
        pack_path = Path(pack_dir)
        if not pack_path.is_dir():
            logger.warning("flow_engine: pack dir not found: %s", pack_dir)
            continue
        for flow_file in sorted(pack_path.glob("flows/**/*.json")):
            definition = _read_json(flow_file)
            if isinstance(definition, dict) and lang and lang != "en":
                definition = translate_flow(definition, pack_path, lang)
            if not isinstance(definition, dict):
                continue
            flow_id = str(definition.get("id", "")).strip()
            if not flow_id:
                continue
            entry = {
                "id": flow_id,
                "label": definition.get("label", flow_id),
                "category": definition.get("category", "create"),
                "file": str(flow_file),
                "llm_required": definition.get("llm_required", False),
                "comfyui_required": definition.get("comfyui_required", True),
                "status": definition.get("status", "active"),
                "pack": pack_id,
            }
            results.append(_enrich_entry(entry, definition, settings))

    # ── 4. Addon flows ────────────────────────────────────────────────────────
    try:
        from app.services.addon_loader import get_addon_flows
        existing_ids = {f["id"] for f in results}
        for addon_flow in get_addon_flows():
            definition = addon_flow["definition"]
            flow_id = str(definition.get("id", "")).strip()
            if flow_id in existing_ids:
                continue  # core/pack takes precedence
            # An addon shipped in a package (data/packages/<pkg>/addon/) is
            # translated from that package's i18n/, like its other flows.
            addon_dir = addon_flow.get("dir")
            if lang and lang != "en" and addon_dir is not None and addon_dir.name == "addon":
                definition = translate_flow(definition, addon_dir.parent, lang)
            entry = {
                "id": flow_id,
                "label": definition.get("label", flow_id),
                "category": definition.get("category", "refine"),
                "llm_required": definition.get("llm_required", False),
                "comfyui_required": definition.get("comfyui_required", False),
                "status": definition.get("status", "active"),
                "pack": f"addon:{addon_flow['addon_id']}",
            }
            results.append(_enrich_entry(entry, definition, settings))
            existing_ids.add(flow_id)
    except Exception:
        logger.exception("flow_engine: failed to load addon flows")

    # Orden: active primero, luego planned; dentro de cada grupo por id
    results.sort(key=lambda f: (0 if f["status"] == "active" else 1, f["id"]))
    return results


def get_flow_by_id(
    flow_id: str,
    settings: dict[str, Any],
    installed_packs: list[dict[str, Any]] | None = None,
    lang: str | None = None,
) -> dict[str, Any] | None:
    """Devuelve un flujo concreto por su id, o None si no existe."""
    target = str(flow_id or "").strip()
    if not target:
        return None
    for flow in load_all_flows(settings, installed_packs=installed_packs, lang=lang):
        if flow["id"] == target:
            return flow
    return None


# ── Géneros narrativos (create.story / create.scenes) ────────────────────────

_GENRES_DIR = _INSTRUCTIONS_DIR / "genres"


def load_genres() -> list[dict[str, Any]]:
    """
    Escanea instructions/genres/*.json y devuelve la lista de géneros disponibles.

    Cada archivo define: id, label, icon, flair (0-100), level (quick|style|scene|master,
    opcional), context_hint (texto inyectado en el system prompt del LLM).
    Añadir un nuevo género = soltar un .json nuevo en la carpeta, no requiere código.
    """
    if not _GENRES_DIR.is_dir():
        return []
    genres: list[dict[str, Any]] = []
    for genre_file in sorted(_GENRES_DIR.glob("*.json")):
        data = _read_json(genre_file)
        if not isinstance(data, dict):
            continue
        genre_id = str(data.get("id", "")).strip()
        if not genre_id:
            continue
        genres.append(
            {
                "id": genre_id,
                "label": str(data.get("label", genre_id)),
                "icon": str(data.get("icon", "")),
                "flair": data.get("flair"),
                "level": data.get("level"),
                "context_hint": str(data.get("context_hint", "")),
            }
        )
    return genres


def get_genre_by_id(genre_id: str) -> dict[str, Any] | None:
    """Devuelve un género concreto por su id, o None si no existe."""
    target = str(genre_id or "").strip()
    if not target:
        return None
    for genre in load_genres():
        if genre["id"] == target:
            return genre
    return None


# ── Validación estructural ────────────────────────────────────────────────────


def validate_flow_definition(definition: dict[str, Any]) -> list[str]:
    """
    Valida la estructura de un JSON de flujo.
    Devuelve lista de errores (vacía = válido).
    """
    errors: list[str] = []
    known_step_types = set(load_step_types().keys())

    if not isinstance(definition.get("id"), str) or not definition["id"].strip():
        errors.append("Missing or empty 'id'")
    if not isinstance(definition.get("steps"), list):
        errors.append("Missing 'steps' array")
        return errors  # No podemos seguir sin steps

    step_ids: set[str] = set()
    for i, step in enumerate(definition["steps"]):
        if not isinstance(step, dict):
            errors.append(f"Step [{i}] is not an object")
            continue
        sid = str(step.get("id", "")).strip()
        stype = str(step.get("type", "")).strip()
        if not sid:
            errors.append(f"Step [{i}] missing 'id'")
        elif sid in step_ids:
            errors.append(f"Duplicate step id '{sid}'")
        else:
            step_ids.add(sid)
        if not stype:
            errors.append(f"Step '{sid or i}' missing 'type'")
        elif known_step_types and stype not in known_step_types:
            errors.append(f"Step '{sid}' uses unknown type '{stype}'")

    return errors
