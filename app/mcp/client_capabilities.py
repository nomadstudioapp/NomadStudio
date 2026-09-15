"""Rastrea si el cliente MCP conectado soporta elicitation.

No todos los hosts MCP implementan `elicitation/create` (algunas ventanas
de Claude Desktop devuelven JSON-RPC -32601 "Method not found"). Una vez
detectado que no esta soportada, se deja de intentar en el resto del
proceso — evita un round-trip fallido en cada llamada."""

from __future__ import annotations

elicitation_supported = True


async def try_elicit(ctx, message: str, schema):
    """Intenta elicit(); devuelve None si no esta soportado o falla."""
    global elicitation_supported

    if not elicitation_supported:
        return None

    try:
        return await ctx.elicit(message=message, schema=schema)
    except Exception:
        elicitation_supported = False
        return None
