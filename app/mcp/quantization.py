"""Resuelve un preset de velocidad (fast/balanced/max) a una cuantizacion
concreta del workflow activo.

Cada workflow declara sus cuantizaciones disponibles en la metadata de su
nodo ``config`` (``quantization: {w4a8/int4/int8/fp8: <fichero>}``); el
analisis del backend lo expone como ``analysis.quantization`` con el
``targetKey`` del UNETLoader. Aqui se elige el nivel segun el preset de
velocidad y se construyen los ``advancedValues`` que el endpoint /generate
aplica al workflow — igual que hace el panel Advanced de la app.

Ya NO se elige entre imports por substring del nombre: el import es el
activo en Nomad Studio y la cuantizacion se cambia dentro de su workflow.
"""

from __future__ import annotations

from typing import Any

from app.mcp.config import SPEED_TO_QUANTIZATIONS


class NoMatchingImportError(RuntimeError):
    """No hay ningun import de ComfyUI utilizable."""


# Explicacion de calidad/velocidad por id de cuantizacion — el backend solo
# expone un "label" corto (INT8, FP8...) en analysis.quantization.options[],
# no una descripcion; esto es lo que le falta para que un humano decida.
QUANT_QUALITY_NOTES: dict[str, str] = {
    "w4a8": "La mas rapida y la que menos VRAM usa; perdida de detalle mas perceptible en texturas finas.",
    "int4": "Muy rapida, huella minima; calidad notablemente por debajo de int8/fp8.",
    "int8": "Buen equilibrio — rapida y con muy poca perdida de calidad frente al modelo completo.",
    "fp8": "Calidad alta, algo mas lenta que int8; buen punto medio para la mayoria de casos.",
    "bf16": "Maxima calidad y fidelidad, la mas lenta y la que mas VRAM necesita.",
    "nvfp4": "Muy rapida, pero requiere GPU con soporte Blackwell/RTX 50 — en otro hardware no aporta nada frente a fp8.",
}
_DEFAULT_QUANT_NOTE = "Sin descripcion especifica — variante de cuantizacion propia de este modelo."


def describe_quantization_options(options: list[dict] | None) -> str:
    """Texto en espanol listando cada opcion de cuantizacion disponible con su
    id, su label y una frase de calidad/velocidad — para mostrar al usuario
    cuando hay que elegir o cuando pidio un id que no existe."""
    if not options:
        return "Este modelo no tiene opciones de cuantizacion configurables — usa siempre su checkpoint por defecto."
    lines = []
    for option in options:
        if not isinstance(option, dict):
            continue
        opt_id = str(option.get("id", "")).strip()
        if not opt_id:
            continue
        label = str(option.get("label", "") or opt_id.upper()).strip()
        note = QUANT_QUALITY_NOTES.get(opt_id.lower(), _DEFAULT_QUANT_NOTE)
        lines.append(f"- {opt_id} ({label}): {note}")
    return "\n".join(lines) if lines else "Este modelo no tiene opciones de cuantizacion configurables."


# Un unet_name de UNETLoader es relativo a la carpeta diffusion_models de
# ComfyUI (o unet, la legacy); un clip_name lo es a text_encoders. check-files
# en cambio resuelve subfolders contra la RAIZ de models, asi que hay que
# anteponer la categoria para mirar donde de verdad viven los ficheros.
_UNET_CATEGORIES = ("diffusion_models", "unet")
_CLIP_CATEGORIES = ("text_encoders",)


def model_file_refs(model_path: str, categories: tuple[str, ...]) -> list[dict[str, str]]:
    """``("krea2\\f.safetensors", ("diffusion_models", "unet"))`` ->
    [{"subfolder": "diffusion_models/krea2", ...}, {"subfolder": "unet/krea2", ...}],
    el formato que espera POST /api/models/imports/check-files."""
    normalized = str(model_path or "").replace("\\", "/")
    subfolder, _, filename = normalized.rpartition("/")
    refs = []
    for category in categories:
        full = f"{category}/{subfolder}" if subfolder else category
        refs.append({"subfolder": full, "filename": filename})
    return refs


def quantization_file_refs(quantization: dict[str, Any] | None) -> list[dict[str, str]]:
    """Todos los ficheros de modelo que menciona el bloque quantization (en
    todas sus ubicaciones candidatas), para comprobar de una sola llamada
    cuales estan descargados."""
    refs: list[dict[str, str]] = []
    for option in (quantization or {}).get("options", []) or []:
        if not isinstance(option, dict):
            continue
        for key, categories in (
            ("unet_name", _UNET_CATEGORIES),
            ("clip_name", _CLIP_CATEGORIES),
            ("unet_unconditional_name", _UNET_CATEGORIES),
        ):
            value = str(option.get(key, "") or "").strip()
            if value:
                refs.extend(model_file_refs(value, categories))
    return refs


def pick_quantization(
    speed: str,
    quantization: dict[str, Any] | None,
    exists: dict[str, bool] | None,
) -> dict[str, Any] | None:
    """Elige la cuantizacion para *speed* entre las opciones del workflow.

    Devuelve ``{"id": <nivel>, "advancedValues": {...}}`` o ``None`` cuando el
    workflow no define cuantizaciones (se genera con su checkpoint por
    defecto). Orden: preferencias del preset primero, luego el resto de
    opciones del workflow como ultimo recurso — siempre saltando niveles
    cuyos ficheros no esten descargados (si *exists* viene vacio, p.ej. sin
    carpeta de modelos configurada, se confia en que estan)."""
    if not isinstance(quantization, dict):
        return None
    target_key = str(quantization.get("targetKey", "") or "").strip()
    options = quantization.get("options")
    if not target_key or not isinstance(options, list):
        return None

    by_id: dict[str, dict[str, Any]] = {}
    for option in options:
        if isinstance(option, dict) and option.get("id") and option.get("unet_name"):
            by_id[str(option["id"]).lower()] = option
    if not by_id:
        return None

    order = [q for q in SPEED_TO_QUANTIZATIONS.get(speed, []) if q in by_id]
    order += [oid for oid in by_id if oid not in order]

    def _available(path: str, categories: tuple[str, ...]) -> bool:
        if not exists:
            return True
        return any(
            exists.get(f"{ref['subfolder']}/{ref['filename']}", False)
            for ref in model_file_refs(path, categories)
        )

    for option_id in order:
        option = by_id[option_id]
        unet_name = str(option["unet_name"])
        clip_name = str(option.get("clip_name", "") or "").strip()
        unet_unconditional_name = str(option.get("unet_unconditional_name", "") or "").strip()
        if not _available(unet_name, _UNET_CATEGORIES):
            continue
        if clip_name and not _available(clip_name, _CLIP_CATEGORIES):
            continue
        if unet_unconditional_name and not _available(unet_unconditional_name, _UNET_CATEGORIES):
            continue
        advanced: dict[str, Any] = {target_key: unet_name}
        clip_target = str(quantization.get("clipTargetKey", "") or "").strip()
        if clip_name and clip_target:
            advanced[clip_target] = clip_name
        unconditional_target = str(quantization.get("unconditionalTargetKey", "") or "").strip()
        if unet_unconditional_name and unconditional_target:
            advanced[unconditional_target] = unet_unconditional_name
        return {"id": option_id, "advancedValues": advanced}

    return None
