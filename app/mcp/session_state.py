"""Cache de "ultima imagen generada" para esta sesion/proceso MCP.

Mismo patron que los globals de modulo en preferences.py (un proceso MCP =
una conversacion). Permite que nomad_studio_refine_image se refiera a "la
imagen que acabamos de generar" sin que el modelo tenga que repetir el
filename en cada llamada."""

from __future__ import annotations

_last_image_filename: str | None = None


def get_last_image() -> str | None:
    return _last_image_filename


def set_last_image(filename: str) -> None:
    global _last_image_filename
    _last_image_filename = filename
