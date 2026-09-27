"""Sessions de Nomad Studio desde el MCP (NomadStudio#24).

Convierte lo ultimo generado/retocado en esta conversacion (session_state.
get_last_generation) en un paso de session con la misma forma que los que
guarda la app: flowCategory/flowAction para poder reabrirlo, params con el
prompt y los valores usados, e ``inputs`` con la imagen de entrada de un
Refine. Las imagenes estan en el album del agente; el servidor las copia a la
carpeta de la session (POST /api/sessions/<id>/steps)."""

from __future__ import annotations

from typing import Any

from app.mcp import session_state
from app.mcp.nomad_client import NomadClient


def _generation_files(generation: dict[str, Any]) -> list[str]:
    return [str(img.get("id")) for img in generation.get("images") or [] if img.get("id")]


def build_step(generation: dict[str, Any], agent_slug: str) -> dict[str, Any]:
    source = f"mcp:{agent_slug}"
    kind = generation.get("kind")
    if kind in ("refine", "mix"):
        flow_id = str(generation.get("action") or "")
        return {
            "flowLabel": generation.get("flow_label") or flow_id,
            "flowCategory": kind,
            "flowAction": flow_id.split(".", 1)[1] if flow_id.startswith(kind + ".") else flow_id or None,
            "params": {
                "mode": "basic",
                "kind": kind,
                "flowId": flow_id,
                "prompt": generation.get("instruction") or "",
                "advancedValues": generation.get("advanced_values") or {},
                "workflowFile": generation.get("workflow_file"),
            },
            "source": source,
        }
    return {
        "flowLabel": f"Create · {generation.get('model') or 'Nomad Studio'}",
        "flowCategory": "create",
        "flowAction": "simple",
        "params": {
            "mode": "basic",
            "kind": "create",
            "prompt": generation.get("prompt") or "",
            "negative": generation.get("negative_prompt") or "",
            "seed": generation.get("seed"),
            "width": generation.get("width"),
            "height": generation.get("height"),
            "model": generation.get("model_id"),
        },
        "source": source,
    }


async def add_generation(
    client: NomadClient,
    session_id: str,
    generation: dict[str, Any],
    agent_slug: str,
    files: list[str] | None = None,
    parent_step_id: str | None = None,
) -> dict[str, Any]:
    """Anade ``generation`` (o solo ``files`` de ella) como un paso. Sin
    ``parent_step_id``, un Refine cuelga del paso donde ya estaba su imagen de
    origen en esta session, si lo hay. Devuelve el paso creado."""
    files = files or _generation_files(generation)
    step = build_step(generation, agent_slug)
    # {id del image_picker: imagen}: al reabrir el paso en la app vuelve a
    # cargar sus imagenes de entrada ("image" en Refine; image, image_2... en Mix).
    inputs: dict[str, str] | None = dict(generation.get("inputs") or {}) or None
    if inputs is None and generation.get("kind") == "refine" and generation.get("source_image"):
        inputs = {"image": str(generation["source_image"])}
    for source_image in (inputs or {}).values():
        if parent_step_id:
            break
        parent_step_id = session_state.step_for_image(source_image, session_id)
        if not parent_step_id and source_image.startswith("session/"):
            # Imagen de un paso de la session (get_session).
            session = await client.get_session(session_id) or {}
            url = "/api/images/" + source_image
            parent_step_id = next(
                (s.get("id") for s in reversed(session.get("steps") or [])
                 if url in (s.get("images") or []) or s.get("imageUrl") == url),
                None,
            )
    step["parentId"] = parent_step_id
    created = await client.add_session_step(session_id, step, files, inputs)
    for name in files:
        session_state.remember_image_step(name, session_id, str(created.get("id") or ""))
    return created


async def auto_add(client: NomadClient, agent_slug: str) -> str:
    """Si la conversacion sigue una session, anade ahi la ultima generacion.
    Devuelve una linea para la respuesta de la tool ("" si no sigue ninguna).
    Un fallo aqui no estropea la imagen ya generada: solo se cuenta."""
    session_id = session_state.get_follow_session()
    generation = session_state.get_last_generation()
    if not session_id or not generation:
        return ""
    try:
        step = await add_generation(client, session_id, generation, agent_slug)
    except Exception as exc:  # noqa: BLE001 — la imagen ya esta hecha
        return f"\nNo se pudo anadir a la session {session_id}: {exc}"
    return (f"\nAnadida a la session {session_id} como paso {step.get('id')} "
            f"(esta conversacion va guardando ahi sus imagenes).")
