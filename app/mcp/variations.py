"""Variaciones de un workflow (Normal / Turbo...) para las tools de refine y mix.

Mismo dato que el bloque Variation del panel Advanced de la app
(analysis.quantization.variations, ver app/services/workflow_quality.py): otro
checkpoint del mismo grafo con su propio numero de pasos. Elegir una aqui
escribe lo mismo que la UI: el UNET (y su text encoder) de la primera precision
que ComfyUI tenga instalada, y los pasos de la variacion en el sampler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.mcp.nomad_client import NomadClient


class VariationError(ValueError):
    """La variacion pedida no existe en ese flow o no esta instalada."""


async def available(client: "NomadClient", workflow_file: str) -> tuple[str, ...]:
    """Ids de variacion del workflow ('normal', 'turbo'...); vacio si no tiene."""
    analysis = await client.workflow_analysis(workflow_file)
    quant = analysis.get("quantization") or {}
    return tuple(str(v.get("id")) for v in quant.get("variations") or [] if v.get("id"))


async def advanced_values(client: "NomadClient", workflow_file: str, variation: str | None) -> dict[str, Any]:
    """advancedValues que aplican la variacion; {} para vacio o 'normal' (el
    grafo ya es la normal). VariationError si no se puede usar."""
    wanted = (variation or "").strip().lower()
    if not wanted or wanted == "normal":
        return {}
    analysis = await client.workflow_analysis(workflow_file)
    quant = analysis.get("quantization") or {}
    variations = quant.get("variations") or []
    chosen = next((v for v in variations if str(v.get("id", "")).lower() == wanted), None)
    if chosen is None:
        ids = ", ".join(str(v.get("id")) for v in variations) or "ninguna"
        raise VariationError(f"este flow no tiene la variacion '{variation}' (tiene: {ids})")

    options = chosen.get("options") or []
    present = await client.quantization_presence(options)
    option = next((o for o in options if present.get(o.get("id")) is not False), None)
    if option is None:
        raise VariationError(f"la variacion '{variation}' no esta instalada en ComfyUI")

    values: dict[str, Any] = {quant["targetKey"]: option["unet_name"]}
    if quant.get("clipTargetKey") and option.get("clip_name"):
        values[quant["clipTargetKey"]] = option["clip_name"]
    if quant.get("unconditionalTargetKey") and option.get("unet_unconditional_name"):
        values[quant["unconditionalTargetKey"]] = option["unet_unconditional_name"]
    if quant.get("stepsTargetKey") and chosen.get("steps"):
        values[quant["stepsTargetKey"]] = int(chosen["steps"])
    return values
