"""Catalogo dinamico de acciones de Refine para nomad_studio_refine_image.

"Router de intencion" del issue #18: en vez de un clasificador de texto en Python
o una tabla curada a mano, el catalogo se construye leyendo los flows reales de
Refine de Nomad Studio (GET /api/flows?category=refine&full=true — el mismo
endpoint que usa la web UI, built-in + packs instalados). Cada flow "simple"
(un solo image_picker, y solo campos con un valor por defecto seguro aparte de
como mucho un prompt libre) se convierte automaticamente en una RefineAction;
los flows "complejos" (mas de una imagen de entrada, tipos de campo que no se
pueden rellenar solos, selectores de Styles guardados del usuario, etc.) quedan
fuera sin romper nada.

Esto resuelve tambien el "hook" de packs sin diseno nuevo: un pack instalado
que traiga flows de Refine con este mismo schema (los trae, porque es el motor
de flows nativo de la app) aparece automaticamente en /api/flows y por tanto en
este catalogo, sin tocar codigo.

El catalogo se construye una vez por proceso MCP y se cachea (mismo patron que
los globals de sesion de preferences.py/session_state.py) — para verlo
actualizado hay que reiniciar el host MCP, igual que para cualquier otro
cambio de docstring/schema de tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.mcp.nomad_client import NomadClient


@dataclass(frozen=True)
class RefineAction:
    flow_id: str
    label: str
    description: str
    group: str
    workflow_file: str
    image_node: str
    prompt_adv_key: str | None
    default_prompt: str
    extra_advanced_values: dict[str, Any] = field(default_factory=dict)
    # Solo se rellenan para flows "outpaint-shaped" (aspect_ratio + position_grid +
    # image_scale) — leidos del propio flow, no hardcodeados a un flow concreto.
    width_adv_key: str | None = None
    height_adv_key: str | None = None
    position_adv_key: str | None = None
    scale_adv_key: str | None = None

    @property
    def is_outpaint_shaped(self) -> bool:
        return bool(self.position_adv_key and self.scale_adv_key)


# Tipos de campo que no necesitan intervencion: engine_select siempre se deja en su
# motor por defecto (el workflow_file/image_node a nivel de step ya corresponde a
# ese motor por defecto — confirmado leyendo los flows reales), y canvas_preview es
# puramente visual (no tiene adv_key).
_SKIP_TYPES = {"engine_select", "canvas_preview"}

# Tipos con un valor por defecto directamente usable tal cual.
_SAFE_DEFAULT_TYPES = {"number", "seed", "slider", "scale_slider", "checkbox", "select"}

# Campos de texto libre — candidatos a ser "el" prompt expuesto como `instruction`.
_PROMPT_TYPES = {"textarea", "text", "prompt_history"}

# Forma especial de outpaint (canvas mas grande + posicion/escala de la imagen original).
_ASPECT_TYPE = "aspect_ratio"
_POSITION_TYPE = "position_grid"
_SCALE_TYPE = "image_scale"

# Convencion consistente en los flows reales: un campo de texto libre con este id es un
# prompt NEGATIVO (casi siempre con default vacio "no aplicar nada") y nunca es "el" prompt
# principal que se expone como `instruction`, aunque su default este vacio.
_NEGATIVE_PROMPT_IDS = {"negative", "negative_prompt"}


def _classify_flow(flow_entry: dict[str, Any]) -> RefineAction | None:
    # /api/flows?full=true anida la definicion completa (steps/fields) bajo "definition";
    # el resto de claves del entry son metadatos ya resumidos (id/label/category/group...).
    flow_def: dict[str, Any] = flow_entry.get("definition") or flow_entry

    if flow_def.get("category") != "refine":
        return None
    if not flow_def.get("comfyui_required", True):
        return None

    steps = flow_def.get("steps") or []
    image_pickers = [s for s in steps if s.get("type") == "image_picker"]
    if len(image_pickers) != 1:
        return None

    params_step = next((s for s in steps if s.get("type") == "workflow_params"), None)
    if params_step is None:
        return None

    workflow_file = params_step.get("workflow_file")
    image_node = params_step.get("image_node")
    if not workflow_file or not image_node:
        return None

    fields = params_step.get("fields") or []
    extra: dict[str, Any] = {}
    width_key = height_key = position_key = scale_key = None
    prompt_fields = [f for f in fields if f.get("type") in _PROMPT_TYPES]
    other_fields = [f for f in fields if f.get("type") not in _PROMPT_TYPES]

    for f in other_fields:
        ftype = f.get("type")
        if ftype in _SKIP_TYPES:
            continue
        if ftype == _ASPECT_TYPE:
            adv_keys = f.get("adv_keys") or {}
            width_key = adv_keys.get("width")
            height_key = adv_keys.get("height")
            if not width_key or not height_key:
                return None
            continue
        if ftype == _POSITION_TYPE:
            position_key = f.get("adv_key")
            if not position_key:
                return None
            continue
        if ftype == _SCALE_TYPE:
            scale_key = f.get("adv_key")
            if not scale_key:
                return None
            continue
        if ftype in _SAFE_DEFAULT_TYPES:
            adv_key = f.get("adv_key")
            default = f.get("default")
            if not adv_key:
                return None
            if ftype == "select" and not default:
                # ej. style_picker/select sin opcion por defecto real — no se puede
                # rellenar solo, el flow queda fuera del catalogo.
                return None
            if default is not None:
                extra[adv_key] = default
            continue
        # Tipo de campo no reconocido/no auto-rellenable (style_picker, compose,
        # compose_preview, layer_compositor...) -> flow demasiado complejo, se excluye.
        return None

    prompt_adv_key: str | None = None
    default_prompt = ""
    negative_fields = [f for f in prompt_fields if f.get("id") in _NEGATIVE_PROMPT_IDS]
    primary_candidates = [f for f in prompt_fields if f.get("id") not in _NEGATIVE_PROMPT_IDS]

    exposed: dict[str, Any] | None = None
    if len(primary_candidates) == 1:
        exposed = primary_candidates[0]
    elif len(primary_candidates) > 1:
        # Varios campos de texto libre "principales" (ni negativos): el que se expone como
        # `instruction` es el que no trae un valor por defecto propio (ej. "object_prompt" en
        # Smart Object Removal); los demas quedan fijos con su propio default (ej.
        # "fill_prompt"). Si no hay exactamente uno sin default, es ambiguo y se excluye.
        empty_default = [f for f in primary_candidates if not (f.get("default") or "").strip()]
        if len(empty_default) != 1:
            return None
        exposed = empty_default[0]

    if exposed is not None:
        prompt_adv_key = exposed.get("adv_key")
        if not prompt_adv_key:
            return None
        default_prompt = exposed.get("default") or ""

    for f in prompt_fields:
        if f is exposed:
            continue
        adv_key = f.get("adv_key")
        if not adv_key:
            return None
        extra[adv_key] = f.get("default") or ""

    return RefineAction(
        flow_id=flow_def["id"],
        label=flow_def.get("label", flow_def["id"]),
        description=flow_def.get("description") or flow_def.get("card_desc") or flow_def.get("label", ""),
        group=flow_def.get("group") or "core",
        workflow_file=workflow_file,
        image_node=str(image_node),
        prompt_adv_key=prompt_adv_key,
        default_prompt=default_prompt,
        extra_advanced_values=extra,
        width_adv_key=width_key,
        height_adv_key=height_key,
        position_adv_key=position_key,
        scale_adv_key=scale_key,
    )


_catalog_cache: dict[str, RefineAction] | None = None


async def get_catalog(client: "NomadClient") -> dict[str, RefineAction]:
    """Catalogo {flow_id: RefineAction}, construido una vez por proceso MCP y cacheado."""
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache
    flows = await client.list_flows(category="refine", available=True, full=True)
    catalog: dict[str, RefineAction] = {}
    for flow_def in flows:
        try:
            action = _classify_flow(flow_def)
        except Exception:
            action = None
        if action is not None:
            catalog[action.flow_id] = action
    _catalog_cache = catalog
    return catalog


def describe_actions(catalog: dict[str, RefineAction]) -> str:
    """Texto en ingles listando las acciones validas, agrupado por categoria — para el
    docstring de la tool y para el mensaje de error cuando se pide una accion desconocida."""
    if not catalog:
        return "(no hay acciones de Refine disponibles ahora mismo — revisa la conexion con Nomad Studio)"
    by_group: dict[str, list[RefineAction]] = {}
    for action in catalog.values():
        by_group.setdefault(action.group, []).append(action)
    lines: list[str] = []
    for group in sorted(by_group):
        lines.append(f"## {group}")
        for action in sorted(by_group[group], key=lambda a: a.flow_id):
            lines.append(f"- {action.flow_id}: {action.description}")
    return "\n".join(lines)
