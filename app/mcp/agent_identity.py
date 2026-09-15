"""Resuelve que "agent viewer" de Nomad Studio usa esta conexion MCP.

Cada host MCP (Claude Desktop, Bionic, LM Studio...) envia su propio nombre
de producto en el handshake `initialize` (`clientInfo.name`). Se usa ESE
nombre como identidad por defecto — un host nuevo crea su propio agente
automaticamente, sin preguntar y sin colisionar con los demas. Sin el, dos
hosts distintos conectados a la vez acababan compartiendo el mismo agente
(y por tanto el mismo Album) en cuanto solo habia uno registrado, porque el
codigo antiguo asumia "si solo hay uno, es este".

Sin usuarios agentes definidos y sin nombre de host disponible -> se pide un
nombre (elicitation) y se crea uno.
Con usuarios agentes ya definidos y sin nombre de host disponible -> se
pregunta cual usar, mostrando la lista (comportamiento legado, hosts viejos).
Sin seguridad: los agentes no llevan PIN, son procesos locales de confianza.

La seleccion se cachea en memoria durante la vida del proceso del servidor
MCP (una sesion de Claude Desktop / LM Studio = un proceso = una eleccion).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.mcp.client_capabilities import try_elicit
from app.mcp.nomad_client import NomadClient

DEFAULT_AGENT_NAME = "MCP Client"

_selected_agent: dict[str, str] | None = None


class _NewAgentName(BaseModel):
    name: str = Field(description="Nombre para identificar este agente en Nomad Studio, ej. 'Claude Desktop'")


class _ExistingAgentChoice(BaseModel):
    agent_name: str = Field(description="Nombre exacto del agente a usar, de la lista mostrada")


def _host_client_name(ctx) -> str | None:
    """Nombre de producto que el host MCP declaro en `initialize`
    (`clientInfo.name`), o None si no esta disponible (SDK/host viejo)."""
    try:
        params = ctx.session.client_params
        name = params.clientInfo.name if params else None
        return str(name).strip() or None
    except Exception:
        return None


async def ensure_agent_session(client: NomadClient, ctx) -> dict[str, str]:
    """Garantiza que `client` tiene una sesion de agente activa. Devuelve
    {"id", "name", "slug"} del agente en uso — slug es la carpeta real del
    Album (<output_dir>/<slug>/), util para verificar donde escribe. `ctx`
    es el Context de FastMCP (para elicit)."""
    global _selected_agent

    if _selected_agent is not None:
        return _selected_agent

    agents = await client.list_agents()
    host_name = _host_client_name(ctx)

    if host_name:
        # Ya existe un agente con este nombre de host exacto (misma app
        # reconectando) -> reusarlo sin preguntar ni crear duplicados.
        existing = next((a for a in agents if a.get("name") == host_name), None)
        if existing is not None:
            await client.select_agent(existing["id"])
            _selected_agent = existing
            return existing
        # Host nunca visto -> crear su propio agente automaticamente. Nada
        # de elicitation aqui: el nombre del host ya es identidad suficiente,
        # y preguntar en cada primera conexion de cada app seria friccion
        # innecesaria (a diferencia del caso legado de abajo, sin nombre).
        agent = await client.create_agent(host_name)
        _selected_agent = agent
        return agent

    # ── Legado: host que no manda clientInfo.name utilizable ───────────
    if not agents:
        result = await try_elicit(
            ctx,
            message=(
                "Nomad Studio no tiene ningun agente registrado todavia. "
                "¿Como quieres llamar a esta conexion (ej. 'Claude Desktop')?"
            ),
            schema=_NewAgentName,
        )
        # Sin elicitation soportada (o declinada): crea uno con nombre por
        # defecto en vez de bloquear la generacion de imagen.
        name = result.data.name.strip() if result and result.action == "accept" and result.data else ""
        agent = await client.create_agent(name or DEFAULT_AGENT_NAME)
        _selected_agent = agent
        return agent

    if len(agents) == 1:
        agent = agents[0]
        await client.select_agent(agent["id"])
        _selected_agent = agent
        return agent

    names = [a["name"] for a in agents]
    result = await try_elicit(
        ctx,
        message=f"¿Que agente se va a conectar? Opciones: {', '.join(names)}",
        schema=_ExistingAgentChoice,
    )
    if result is None or result.action != "accept" or not result.data:
        # Sin elicitation soportada: usa el primero en vez de bloquear.
        chosen = agents[0]
        await client.select_agent(chosen["id"])
        _selected_agent = chosen
        return chosen

    chosen = next((a for a in agents if a["name"] == result.data.agent_name.strip()), None)
    if chosen is None:
        # El usuario escribio un nombre nuevo que no estaba en la lista: lo creamos.
        chosen = await client.create_agent(result.data.agent_name.strip())
    else:
        await client.select_agent(chosen["id"])

    _selected_agent = chosen
    return chosen
