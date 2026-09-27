"""Preferencias de sesion (formato/velocidad) para nomad_studio_create_image.

Orden de resolucion:
1. Valor explicito pasado por el modelo (ej. "una vertical" -> portrait ya lo
   resuelve el propio modelo via la descripcion de la tool). Se cachea como
   preferencia de sesion.
2. Preferencia ya cacheada en esta sesion (un proceso = una conversacion).
3. Elicitation (quick-replies nativas), en hosts que la soporten.
4. ``None`` — el host no soporta elicitation (Claude Desktop responde -32601
   en sus ventanas de chat) o el usuario declino. El caller (server.py) debe
   devolver entonces un mensaje pidiendo al modelo que pregunte al usuario en
   el chat y reintente; NUNCA asumir un valor por defecto en silencio.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from app.mcp.client_capabilities import try_elicit
from app.mcp.config import ASPECT_RATIO_ALIASES, ASPECT_RATIO_DIMENSIONS, SPEED_TO_QUANTIZATIONS
from app.services import import_slugs

if TYPE_CHECKING:
    from app.mcp.nomad_client import NomadClient

_session_aspect_ratio: str | None = None
_session_speed: str | None = None
_session_model_id: str | None = None

# Nota: la elicitation de MCP solo admite campos primitivos (str/int/float/bool
# u Optional de estos) — nada de Literal/enum, así que las opciones se listan
# en la descripción en vez de forzarse por tipo.


class _AspectRatioChoice(BaseModel):
    aspect_ratio: str = Field(
        description="Formato de la imagen. Escribe exactamente: landscape (apaisado 3:2), portrait (retrato 2:3), "
        "square (cuadrado), wide (panoramico 16:9) o tall (vertical 9:16)."
    )


class _SpeedChoice(BaseModel):
    speed: str = Field(
        description="Velocidad/calidad. Escribe exactamente: fast (superrapida), balanced (rapida) o max (normal/maxima calidad)."
    )


async def resolve_aspect_ratio(aspect_ratio: str | None, ctx) -> str | None:
    global _session_aspect_ratio

    if aspect_ratio:
        normalized = aspect_ratio.strip().lower()
        normalized = ASPECT_RATIO_ALIASES.get(normalized, normalized)
        if normalized in ASPECT_RATIO_DIMENSIONS:
            _session_aspect_ratio = normalized
            return normalized
        # Valor no reconocido (ej. "panorama"): tratar como ausente para que se
        # pregunte en vez de generar con algo que el usuario no pidio.
    if _session_aspect_ratio:
        return _session_aspect_ratio

    result = await try_elicit(
        ctx,
        message="¿Que formato quieres para la imagen? (landscape / portrait / square / wide 16:9 / tall 9:16)",
        schema=_AspectRatioChoice,
    )
    if result is None or result.action != "accept" or not result.data:
        return None

    answer = result.data.aspect_ratio.strip().lower()
    answer = ASPECT_RATIO_ALIASES.get(answer, answer)
    if answer in ASPECT_RATIO_DIMENSIONS:
        _session_aspect_ratio = answer
        return answer
    return None


class _ModelChoice(BaseModel):
    model: str = Field(description="Nombre exacto (o parte reconocible) del modelo a usar, tal y como aparece listado.")


async def resolve_model(model: str | None, client: "NomadClient", ctx) -> dict[str, Any] | None:
    """Resuelve que import (modelo/checkpoint) usar para esta generacion.

    Orden: valor explicito (busca por substring case-insensitive contra el
    nombre) -> preferencia cacheada de esta sesion -> si solo hay 1 import
    disponible, se autoselecciona sin preguntar -> si hay 2+, elicitation o
    (sin soporte) None para que el caller pida al usuario que elija en el
    chat, listando los nombres reales.

    Devuelve el import record completo (via client.get_import), o None si
    hay que preguntar."""
    global _session_model_id

    imports = await client.list_imports()
    by_id = {str(imp.get("id", "")): imp for imp in imports if isinstance(imp, dict)}

    if model:
        # Identificador exacto ("monaco"), nombre exacto o trozo del nombre
        # (guiones = espacios): la misma busqueda que la app, import_slugs.find.
        match, _candidates = import_slugs.find(imports, model)
        if match:
            _session_model_id = str(match.get("id", ""))
            return await client.get_import(_session_model_id)
        # Nombre no reconocido: tratar como ausente, que se pregunte con la
        # lista real en vez de generar con un modelo que el usuario no pidio.

    if _session_model_id and _session_model_id in by_id:
        return await client.get_import(_session_model_id)

    if len(imports) <= 1:
        if not imports:
            return None
        chosen_id = str(imports[0].get("id", ""))
        _session_model_id = chosen_id
        return await client.get_import(chosen_id)

    names = [str(imp.get("name", "") or imp.get("id", "")) for imp in imports]
    result = await try_elicit(
        ctx,
        message="¿Que modelo quieres usar? Opciones disponibles: " + ", ".join(names),
        schema=_ModelChoice,
    )
    if result is None or result.action != "accept" or not result.data:
        return None

    match, _candidates = import_slugs.find(imports, result.data.model)
    if match is None:
        return None
    _session_model_id = str(match.get("id", ""))
    return await client.get_import(_session_model_id)


async def resolve_speed(speed: str | None, ctx) -> str | None:
    global _session_speed

    if speed:
        normalized = speed.strip().lower()
        if normalized in SPEED_TO_QUANTIZATIONS:
            _session_speed = normalized
            return normalized
    if _session_speed:
        return _session_speed

    result = await try_elicit(
        ctx,
        message="¿Que velocidad/calidad prefieres? (fast / balanced / max)",
        schema=_SpeedChoice,
    )
    if result is None or result.action != "accept" or not result.data:
        return None

    answer = result.data.speed.strip().lower()
    if answer in SPEED_TO_QUANTIZATIONS:
        _session_speed = answer
        return answer
    return None
