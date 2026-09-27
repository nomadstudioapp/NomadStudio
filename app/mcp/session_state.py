"""Cache de "ultima imagen generada" para esta sesion/proceso MCP.

Mismo patron que los globals de modulo en preferences.py (un proceso MCP =
una conversacion). Permite que nomad_studio_refine_image se refiera a "la
imagen que acabamos de generar" sin que el modelo tenga que repetir el
filename en cada llamada, y que nomad_studio_get_last_generation cuente que
se hizo (prompt, seed, tamano, imagenes)."""

from __future__ import annotations

from typing import Any

_last_image_filename: str | None = None
_last_generation: dict[str, Any] | None = None


def get_last_image() -> str | None:
    return _last_image_filename


def set_last_image(filename: str) -> None:
    global _last_image_filename
    _last_image_filename = filename


def get_last_generation() -> dict[str, Any] | None:
    return _last_generation


def set_last_generation(generation: dict[str, Any]) -> None:
    global _last_generation
    _last_generation = generation


# ── Sessions de Nomad Studio (NomadStudio#24) ──────────────────────────────
# La session a la que esta conversacion va anadiendo sus imagenes (si el
# usuario lo pidio) y en que paso quedo cada imagen: al retocar una imagen que
# ya esta en la session, el paso nuevo cuelga del suyo.

_follow_session_id: str | None = None
_image_steps: dict[str, tuple[str, str]] = {}  # filename -> (session id, step id)


def get_follow_session() -> str | None:
    return _follow_session_id


def set_follow_session(session_id: str | None) -> None:
    global _follow_session_id
    _follow_session_id = session_id


def remember_image_step(filename: str, session_id: str, step_id: str) -> None:
    _image_steps[filename] = (session_id, step_id)


def step_for_image(filename: str | None, session_id: str) -> str | None:
    found = _image_steps.get(filename or "")
    return found[1] if found and found[0] == session_id else None
