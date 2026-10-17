"""Catalogo dinamico de flows de Mix (varias imagenes -> una) para el MCP
(NomadStudio#25), leido de GET /api/flows?category=mix como el de Refine.

Todo sale del paso ``action`` del flow (calls = generation.submit_mix): su
``input_map`` dice que image_picker va a que nodo LoadImage, en que clave va
el prompt y de que paso sale el workflow. De cada flow se expone:

- sus huecos de imagen (id del image_picker, etiqueta = su papel, si es
  opcional) en el orden del flow;
- el prompt (su valor por defecto, si lo trae);
- si tiene formato de salida (campo aspect_ratio) — para el argumento
  aspect_ratio de la tool.

Quedan fuera los flows que necesitan interaccion que el MCP no tiene (zonas
dibujadas, plantillas de composicion, un LLM que reescribe la idea): hay una
variante "Quick" sin eso para la composicion multi-referencia."""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from app.mcp import variations

if TYPE_CHECKING:
    from app.mcp.nomad_client import NomadClient

# Pasos que el MCP no puede rellenar: si el flow los tiene, no entra.
_INTERACTIVE_STEPS = {"region_annotate", "compose_template_picker", "zone_prompt_builder", "llm_transform"}
# Campos de ayuda visual o que ya cubre otro campo (el selector de papeles solo
# rellena el prompt).
_SKIP_FIELDS = {"compose", "compose_preview", "canvas_preview", "engine_select"}
_DEFAULT_FIELDS = {"number", "slider", "checkbox", "select", "scale_slider"}


@dataclass(frozen=True)
class MixSlot:
    slot: str
    label: str
    node_id: str
    optional: bool


@dataclass(frozen=True)
class MixAction:
    flow_id: str
    label: str
    description: str
    group: str
    workflow_file: str
    slots: tuple[MixSlot, ...]
    prompt_key: str | None
    default_prompt: str
    defaults: dict[str, Any] = field(default_factory=dict)
    seed_keys: tuple[str, ...] = ()
    width_key: str | None = None
    height_key: str | None = None
    default_aspect: tuple[int, int] = (1, 1)
    # Variaciones del workflow ('normal', 'turbo'...), de su analysis.
    variations: tuple[str, ...] = ()

    @property
    def required_slots(self) -> list[MixSlot]:
        return [s for s in self.slots if not s.optional]


def _ref_step(ref: Any) -> str | None:
    """'steps.<id>.output.<x>' -> '<id>'."""
    parts = str(ref or "").split(".")
    return parts[1] if len(parts) >= 3 and parts[0] == "steps" else None


def _aspect_from_key(key: str) -> tuple[int, int]:
    # "r16x9" -> (16, 9); cualquier otra cosa, cuadrado.
    try:
        w, h = str(key).lstrip("r").split("x", 1)
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 1, 1


def _classify_flow(flow_entry: dict[str, Any]) -> MixAction | None:
    flow_def: dict[str, Any] = flow_entry.get("definition") or flow_entry
    if flow_def.get("category") != "mix" or not flow_def.get("comfyui_required", True):
        return None
    steps = flow_def.get("steps") or []
    if any(s.get("type") in _INTERACTIVE_STEPS for s in steps):
        return None
    by_id = {s.get("id"): s for s in steps}
    action = next((s for s in steps if s.get("type") == "action"
                   and s.get("calls") == "generation.submit_mix"), None)
    if action is None:
        return None
    input_map = action.get("input_map") or {}

    slots: list[MixSlot] = []
    for entry in input_map.get("images") or []:
        picker = by_id.get(_ref_step(entry.get("dataUrl")))
        if not picker or picker.get("type") != "image_picker" or not entry.get("nodeId"):
            return None
        optional = bool(entry.get("optional")) or picker.get("required") is False
        slots.append(MixSlot(str(picker["id"]), str(picker.get("label") or picker["id"]),
                             str(entry["nodeId"]), optional))
    if not slots:
        return None

    # Workflow: literal, o el del paso workflow_params al que apunta (su motor
    # por defecto si tiene selector).
    wf_ref = input_map.get("workflowFile")
    wf_step = by_id.get(_ref_step(wf_ref))
    workflow_file = None
    if wf_step is not None:
        workflow_file = wf_step.get("workflow_file")
        for f in wf_step.get("fields") or []:
            if f.get("type") == "engine_select":
                engine = next((e for e in f.get("engines") or [] if e.get("id") == f.get("default")), None)
                workflow_file = (engine or {}).get("workflow_file") or workflow_file
    elif isinstance(wf_ref, str) and wf_ref.endswith(".json"):
        workflow_file = wf_ref
    if not workflow_file:
        return None

    defaults: dict[str, Any] = {}
    seed_keys: list[str] = []
    width_key = height_key = None
    default_aspect = (1, 1)
    params_step = by_id.get(_ref_step(input_map.get("advancedValues")))
    for f in (params_step or {}).get("fields") or []:
        ftype = f.get("type")
        if ftype in _SKIP_FIELDS:
            continue
        if ftype == "seed":
            if f.get("adv_key"):
                seed_keys.append(f["adv_key"])
            continue
        if ftype == "aspect_ratio":
            keys = f.get("adv_keys") or {}
            width_key, height_key = keys.get("width"), keys.get("height")
            if not width_key or not height_key:
                return None
            default_aspect = _aspect_from_key(f.get("default") or "r1x1")
            continue
        if ftype in _DEFAULT_FIELDS:
            if f.get("adv_key") and f.get("default") is not None:
                defaults[f["adv_key"]] = f["default"]
            continue
        return None  # campo que no se sabe rellenar solo

    prompt_step = by_id.get(_ref_step(input_map.get("promptValue")))
    prompt_key = str(input_map.get("promptKey") or "") or None
    default_prompt = str((prompt_step or {}).get("default") or "")

    return MixAction(
        flow_id=flow_def["id"],
        label=flow_def.get("label", flow_def["id"]),
        description=flow_def.get("description") or flow_def.get("card_desc") or flow_def.get("label", ""),
        group=flow_def.get("group") or "compose",
        workflow_file=workflow_file,
        slots=tuple(slots),
        prompt_key=prompt_key,
        default_prompt=default_prompt,
        defaults=defaults,
        seed_keys=tuple(seed_keys),
        width_key=width_key,
        height_key=height_key,
        default_aspect=default_aspect,
    )


_catalog_cache: dict[str, MixAction] | None = None


async def get_catalog(client: "NomadClient") -> dict[str, MixAction]:
    """Catalogo {flow_id: MixAction}, construido una vez por proceso MCP."""
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache
    flows = await client.list_flows(category="mix", available=True, full=True)
    catalog: dict[str, MixAction] = {}
    for flow_def in flows:
        try:
            action = _classify_flow(flow_def)
        except Exception:
            action = None
        if action is not None:
            catalog[action.flow_id] = action
    by_file: dict[str, tuple[str, ...]] = {}
    for flow_id, action in list(catalog.items()):
        if action.workflow_file not in by_file:
            try:
                by_file[action.workflow_file] = await variations.available(client, action.workflow_file)
            except Exception:
                by_file[action.workflow_file] = ()
        if by_file[action.workflow_file]:
            catalog[flow_id] = replace(action, variations=by_file[action.workflow_file])
    _catalog_cache = catalog
    return catalog


def advanced_values(action: MixAction, instruction: str | None, size: tuple[int, int] | None,
                    seed: int | None) -> dict[str, Any]:
    values = dict(action.defaults)
    for key in action.seed_keys:
        values[key] = seed if seed is not None else random.randint(1, 2**31 - 1)
    if action.width_key and action.height_key and size:
        values[action.width_key], values[action.height_key] = size
    prompt = (instruction or "").strip() or action.default_prompt
    if action.prompt_key and prompt:
        values[action.prompt_key] = prompt
    return values


def describe_actions(catalog: dict[str, MixAction]) -> str:
    if not catalog:
        return "(no hay flows de Mix disponibles ahora mismo — instala un pack de Mix o revisa la conexion)"
    lines: list[str] = []
    by_group: dict[str, list[MixAction]] = {}
    for action in catalog.values():
        by_group.setdefault(action.group, []).append(action)
    for group in sorted(by_group):
        lines.append(f"## {group}")
        for action in sorted(by_group[group], key=lambda a: a.flow_id):
            lines.append(f"- {action.flow_id}: {action.description}")
            for slot in action.slots:
                lines.append(f"    slot '{slot.slot}': {slot.label}{' (optional)' if slot.optional else ''}")
            if action.default_prompt:
                lines.append(f"    default instruction: {action.default_prompt[:220]}"
                             + ("..." if len(action.default_prompt) > 220 else ""))
            elif action.prompt_key:
                lines.append("    instruction: optional")
            if action.width_key:
                lines.append("    accepts aspect_ratio")
            if action.variations:
                lines.append(f"    accepts variation: {', '.join(action.variations)}")
    return "\n".join(lines)
