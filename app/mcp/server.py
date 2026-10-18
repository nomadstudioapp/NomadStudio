"""Entrypoint del servidor MCP de Nomad Studio (transporte stdio).

Uso:
    python -m app.mcp.server

Pensado para ser lanzado como proceso hijo por un host MCP (Claude Desktop).
Requiere que el backend Flask de Nomad Studio (app.py) este corriendo en
NOMAD_STUDIO_BASE_URL (por defecto http://127.0.0.1:5123).
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import sys
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ImageContent, TextContent

from app.mcp.agent_identity import ensure_agent_session
from app.mcp.config import (
    ASPECT_RATIO_DIMENSIONS,
    DEFAULT_ASPECT_RATIO,
    THUMBNAIL_WIDTH,
)
from app.mcp.local_files import (
    LocalImageNotFoundError,
    image_path,
    read_full_image_as_data_url,
    read_thumbnail,
)
from app.mcp.nomad_client import NomadClient, NomadClientError
from app.mcp.preferences import resolve_aspect_ratio, resolve_model, resolve_speed
from app.mcp.quantization import (
    NoMatchingImportError,
    describe_quantization_options,
    pick_quantization,
    quantization_file_refs,
)
from app.mcp import mix_actions
from app.mcp import refine_actions
from app.mcp import session_state
from app.mcp import sessions as mcp_sessions
from app.mcp import variations
from app.mcp.regions import MarkedRegion, annotate_data_url
from app.services.prompt_params import MAX_REPEAT as MAX_IMAGES_PER_CALL
from app.services.prompt_params import parse as parse_prompt_params, size_for_aspect
from mcp.types import ToolAnnotations

mcp = FastMCP("nomad-studio")

# Codex asks before running tools that write (default_tools_approval_mode =
# "writes"); consultations are marked read-only so they run straight away.
_READ_TOOL = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
_WRITE_TOOL = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
_client = NomadClient()


@mcp.tool(
    name="nomad_studio_create_image",
    description=(
        "Genera una imagen 100% local con Nomad Studio (ComfyUI en tu propio PC, sin API "
        "keys ni cuenta). Usa esto cuando el usuario pida crear, generar o dibujar una imagen, "
        "ilustracion o foto. El prompt debe describirse en ingles cuando sea posible. Si el "
        "usuario escribe parametros estilo Midjourney (--ar 16:9, --v monaco, --q max, --no text, "
        "--seed 1...), copialos LITERALMENTE al final de 'prompt' y no rellenes con ellos los "
        "demas argumentos: la tool los interpreta."
    ),
    # Sin structured_output=False, FastMCP genera un outputSchema a partir de la
    # anotacion de retorno y adjunta structuredContent (el base64 duplicado como
    # JSON); Claude Desktop entonces prioriza ese JSON y no renderiza el bloque
    # de imagen. La tool debe ser "unstructured" para que la imagen se muestre.
    structured_output=False,
    annotations=_WRITE_TOOL,
)
# Cada argumento lleva su descripcion en Field(description=...): es lo unico
# que llega al cliente. Con description= en @mcp.tool, un bloque "Args:" en el
# docstring NO se publica — ningun modelo lo veia.
async def nomad_studio_create_image(
    prompt: Annotated[str, Field(description=(
        "Descripcion de la imagen a generar, en ingles preferiblemente. Puede terminar con "
        "parametros estilo Midjourney, que se interpretan aqui y mandan sobre los demas "
        "argumentos: --ar 16:9 (cualquier proporcion), --no people, text (se suma al negativo por "
        "defecto), --seed 1234, --v <modelo> (ej. --v krea), --anime (el modelo de anime "
        "instalado), --q fast|balanced|max (o --draft), --steps 20, --quant int8, --r 2 (varias "
        "imagenes, hasta 4). IMPORTANTE: si el usuario escribe parametros con --, copialos "
        "LITERALMENTE al final de este 'prompt', exactamente como los escribio — no los quites, no "
        "los traduzcas y no los pases a otros argumentos (aspect_ratio, model, speed, steps...): se "
        "interpretan aqui. Los de Midjourney sin equivalente (--stylize, --chaos...) se quitan "
        "solos: no hace falta mencionarlos."))],
    ctx: Context,
    aspect_ratio: Annotated[str | None, Field(description=(
        "'landscape' (apaisado 3:2), 'portrait' (retrato 2:3), 'square' (cuadrado), 'wide' "
        "(panoramico 16:9, tipo pantalla/YouTube/cabecera) o 'tall' (vertical 9:16, tipo "
        "movil/stories/reels). Si el usuario ya lo indico con palabras (ej. 'para el movil'), "
        "traducelo a uno de esos valores. Si no lo indico, dejalo vacio: se reutilizara su "
        "eleccion anterior de esta conversacion, o la tool te pedira que se lo preguntes. "
        "Ignorado si se pasan 'width'/'height'."))] = None,
    speed: Annotated[str | None, Field(description=(
        "'fast' (superrapida), 'balanced' (rapida) o 'max' (maxima calidad). Si el usuario ya lo "
        "indico, traducelo a uno de esos tres valores. Si no, dejalo vacio: se reutilizara su "
        "eleccion anterior de esta conversacion, o la tool te pedira que se lo preguntes."))] = None,
    model: Annotated[str | None, Field(description=(
        "Identificador del modelo (el de '--v', ej. 'monaco', 'qwen', 'ideogram': lo lista "
        "nomad_studio_list_models) o su nombre / parte reconocible del nombre, tal y como lo tenga el "
        "usuario en Nomad Studio. Si el usuario no dijo ninguno, dejalo "
        "vacio: se reutilizara su eleccion anterior de esta conversacion, o la tool te pedira que "
        "le preguntes listando los modelos reales. Con un solo modelo instalado se usa sin "
        "preguntar."))] = None,
    quantization: Annotated[str | None, Field(description=(
        "Id exacto de una cuantizacion del modelo elegido (ej. 'fp8', 'int8', 'bf16', 'w4a8') — "
        "SOLO si el usuario pide una concreta o pregunta que opciones hay. Vacio = se elige sola "
        "segun 'speed'. Si el id no existe para ese modelo, la tool devuelve sus opciones reales "
        "sin generar nada, para que se las ensenes al usuario."))] = None,
    steps: Annotated[int | None, Field(description=(
        "Pasos del sampler, SOLO si el usuario da un numero explicito (ej. 'usa 8 steps'). Nunca "
        "lo inventes para subir la calidad: para eso esta 'speed'. Vacio = el valor del propio "
        "modelo (lo normal)."))] = None,
    width: Annotated[int | None, Field(description=(
        "Ancho exacto en pixeles — SOLO si el usuario pide una resolucion concreta (ej. "
        "'1024x768'). Va junto con 'height' (los dos o ninguno). Se redondea al multiplo de 64."))] = None,
    height: Annotated[int | None, Field(description="Alto exacto en pixeles — ver 'width'.")] = None,
    negative: Annotated[str | None, Field(description=(
        "Lo que NO debe aparecer, en ingles (ej. 'text, watermark, people') — SOLO si el usuario "
        "lo pide ('sin gente', 'que no salga texto'). Vacio = el negativo por defecto del modelo. "
        "Si lo pasas, sustituye a ese por defecto."))] = None,
    seed: Annotated[int | None, Field(description=(
        "Semilla exacta, SOLO para repetir o variar una imagen anterior (cada respuesta dice la "
        "semilla usada). Mismo prompt + semilla + modelo + tamano = la misma imagen. Vacio = "
        "aleatoria (lo normal)."))] = None,
    count: Annotated[int | None, Field(description=(
        "Cuantas imagenes generar de una vez, 1-4 (lo mismo que '--r' en el prompt, que manda si "
        "estan los dos). Vacio = 1."))] = None,
) -> list[TextContent | ImageContent]:
    agent_name = "unknown"
    agent_slug = "unknown"
    agent_id = "unknown"
    debug: dict[str, Any] = {
        "input": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "speed": speed,
            "model": model,
            "quantization": quantization,
            "steps": steps,
            "width": width,
            "height": height,
            "negative": negative,
            "seed": seed,
            "count": count,
        }
    }

    if count is not None and not 1 <= int(count) <= MAX_IMAGES_PER_CALL:
        return [TextContent(type="text", text=(
            f"NO SE HA GENERADO NADA TODAVIA. 'count' tiene que ser de 1 a {MAX_IMAGES_PER_CALL} "
            f"(se ha pedido {count})."))]

    # Midjourney-style "--ar 16:9 --no text --seed 1" at the end of the prompt
    # (NomadStudio#27): they win over the separate arguments.
    prompt_params = parse_prompt_params(prompt)
    if prompt_params.found:
        debug["prompt_params"] = prompt_params.as_dict()
        if prompt_params.invalid:
            problems = "\n".join(f"- --{name}: {why}" for name, why in prompt_params.invalid.items())
            return [TextContent(type="text", text=(
                "NO SE HA GENERADO NADA TODAVIA. Estos parametros del prompt no se pueden usar:\n"
                f"{problems}\nCorrigelos (o quitalos) y vuelve a llamar a la tool."))]
        prompt = prompt_params.prompt
        if prompt_params.aspect:
            width, height = size_for_aspect(prompt_params.aspect)
        seed = prompt_params.seed if prompt_params.seed is not None else seed
        model = prompt_params.model or model
        speed = prompt_params.speed or speed
        quantization = prompt_params.quantization or quantization
        steps = prompt_params.steps or steps
    if not prompt.strip():
        return [TextContent(type="text", text=(
            "NO SE HA GENERADO NADA TODAVIA. El prompt esta vacio: describe la imagen que quieres "
            "(los parametros con -- van despues de la descripcion)."))]
    num_images = prompt_params.repeat or (int(count) if count else 1)

    try:
        agent = await ensure_agent_session(_client, ctx)
        agent_name = agent.get("name", "unknown")
        agent_slug = agent.get("slug", "unknown")
        agent_id = agent.get("id", "unknown")
        debug["agent"] = agent
        _log(f"AGENT: {agent_name} (user: {agent_slug}) — generating image")

        # width+height explicitos ganan a aspect_ratio (ver docstring) — ni
        # se resuelve ni se exige en ese caso, para no preguntar por algo que
        # ya no hace falta.
        has_explicit_dims = width is not None and height is not None
        debug["input"]["has_explicit_dims"] = has_explicit_dims

        # Las tres preferencias se resuelven ANTES de decidir si falta algo —
        # asi, si faltan varias, se preguntan TODAS JUNTAS en una sola vuelta
        # (antes el chequeo de aspect_ratio/speed devolvia en cuanto faltaba
        # uno de esos dos, sin llegar siquiera a intentar resolver el modelo;
        # con 2+ modelos disponibles eso obligaba a una segunda ronda de
        # preguntas por separado, y si esa segunda ronda tampoco se relayaba
        # bien, el modelo nunca llegaba a preguntarse).
        aspect_ratio = aspect_ratio if has_explicit_dims else await resolve_aspect_ratio(aspect_ratio, ctx)
        speed = await resolve_speed(speed, ctx)
        record = await resolve_model(model, _client, ctx)
        debug["resolved_preferences"] = {"aspect_ratio": aspect_ratio, "speed": speed, "model": record.get("name") if record else None}

        imports_for_error: list[dict[str, Any]] = []
        if record is None:
            imports_for_error = await _client.list_imports()
            if not imports_for_error:
                raise NoMatchingImportError(
                    "No hay ningun workflow importado en Nomad Studio. Importa uno desde la seccion Imports."
                )

        # Sin preferencia explicita, sin cache de sesion y sin elicitation
        # (Claude Desktop responde -32601 en sus ventanas de chat): pedir al
        # modelo que pregunte al usuario en el chat, en vez de generar en
        # silencio con un formato/calidad/modelo que nadie eligio.
        missing: list[str] = []
        if aspect_ratio is None and not has_explicit_dims:
            missing.append("aspect_ratio — landscape (apaisado 3:2), portrait (vertical 2:3), square (cuadrado), "
                           "wide (panoramico 16:9) o tall (vertical 9:16)")
        if speed is None:
            missing.append("speed — fast (superrapida), balanced (equilibrada) o max (maxima calidad)")
        if record is None:
            names = [str(imp.get("name", "") or imp.get("id", "")) for imp in imports_for_error]
            missing.append("model — uno de estos: " + ", ".join(names))
        if missing:
            _log(f"PREFERENCIAS PENDIENTES: {missing}")
            return [
                TextContent(
                    type="text",
                    text=(
                        "NO SE HA GENERADO NADA TODAVIA. Antes de volver a llamar a esta tool, "
                        "pregunta al usuario en el chat que opcion prefiere para:\n- "
                        + "\n- ".join(missing)
                        + "\nCuando responda, llama de nuevo a nomad_studio_create_image "
                        "pasando su eleccion en esos parametros.\n"
                        "EXCEPCION: si en su mensaje el usuario ya escribio parametros con -- (ej. "
                        "--v monaco, --q max, --ar 16:9), NO le preguntes: vuelve a llamar ahora "
                        "con el prompt terminado en esos parametros, copiados literalmente."
                    ),
                )
            ]
        if has_explicit_dims:
            width = max(64, round(width / 64) * 64)
            height = max(64, round(height / 64) * 64)
        else:
            width, height = ASPECT_RATIO_DIMENSIONS.get(aspect_ratio, ASPECT_RATIO_DIMENSIONS[DEFAULT_ASPECT_RATIO])

        import_id = str(record.get("id", "") or "").strip()
        if not import_id:
            raise NoMatchingImportError("El modelo elegido no tiene id.")

        quant_block = (record.get("analysis") or {}).get("quantization")
        quant_options = (quant_block or {}).get("options") or []

        if quantization:
            requested = quantization.strip().lower()
            match = next(
                (o for o in quant_options if isinstance(o, dict) and str(o.get("id", "")).lower() == requested),
                None,
            )
            if match is None:
                debug["error"] = f"Cuantizacion '{quantization}' no existe para el modelo '{record.get('name', '')}'."
                _log(f"CUANTIZACION INVALIDA: {quantization}")
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"NO SE HA GENERADO NADA TODAVIA. '{quantization}' no es una cuantizacion valida "
                            f"para el modelo '{record.get('name', '')}'. Opciones disponibles:\n"
                            + describe_quantization_options(quant_options)
                            + "\nPregunta al usuario cual prefiere y vuelve a llamar a la tool con ese id "
                            "en el parametro 'quantization' (o dejalo vacio para que se elija segun 'speed')."
                        ),
                    )
                ]
            advanced_values = {str(quant_block.get("targetKey", "")): str(match["unet_name"])}
            clip_name = str(match.get("clip_name", "") or "").strip()
            clip_target = str(quant_block.get("clipTargetKey", "") or "").strip()
            if clip_name and clip_target:
                advanced_values[clip_target] = clip_name
            uncond_name = str(match.get("unet_unconditional_name", "") or "").strip()
            uncond_target = str(quant_block.get("unconditionalTargetKey", "") or "").strip()
            if uncond_name and uncond_target:
                advanced_values[uncond_target] = uncond_name
            chosen_id = str(match.get("id", ""))
        else:
            exists = await _client.check_files(quantization_file_refs(quant_block))
            chosen = pick_quantization(speed, quant_block, exists)
            advanced_values = chosen["advancedValues"] if chosen else {}
            chosen_id = chosen["id"] if chosen else None

        if steps is not None:
            sampler_node_id = str(record.get("analysis", {}).get("detected", {}).get("samplerNodeId") or "").strip()
            if sampler_node_id:
                advanced_values[f"{sampler_node_id}.steps"] = max(1, int(steps))
            debug["steps_override"] = {"requested": steps, "samplerNodeId": sampler_node_id or None}

        debug["quantization"] = {
            "model": record.get("name"),
            "requested_speed": speed,
            "requested_quantization": quantization,
            "chosen": chosen_id or "workflow default",
            "advancedValues": advanced_values,
            "available_options": describe_quantization_options(quant_options) if quant_options else None,
        }

        basic_values: dict[str, Any] = {"positive": prompt, "width": width, "height": height}
        negative = (negative or "").strip()
        if prompt_params.no:
            # --no adds to the negative — the given one, else the engine's own
            # default (it already keeps watermarks, bad anatomy… out).
            base = negative or str((record.get("basicValues") or {}).get("negative") or "").strip()
            negative = ", ".join(p for p in (base.rstrip(", "), prompt_params.no) if p)
        if negative:
            # Both aliases: an engine record can carry its own default under
            # each, and the one left behind would win.
            basic_values["negative"] = basic_values["negative_prompt"] = negative
        # The app never draws a seed itself (Create sends a fresh one each
        # time); without one the engine's last saved seed was reused, so the
        # same prompt gave the same image every time.
        basic_values["seed"] = max(0, int(seed)) if seed is not None else secrets.randbelow(2**48)
        request_payload = {
            "import_id": import_id,
            "basicValues": basic_values,
            "advancedValues": advanced_values,
            "numImages": num_images,
        }
        debug["request"] = request_payload
        _log(f"REQUEST: {json.dumps(request_payload, ensure_ascii=False)}")

        result = await _client.generate(
            import_id=import_id,
            basic_values=basic_values,
            advanced_values=advanced_values,
            num_images=num_images,
        )
        debug["response"] = result
        _log(f"RESPONSE: {json.dumps(result, ensure_ascii=False)}")

        images = result.get("images") or []
        if not images:
            debug["error"] = "Nomad Studio no devolvio ninguna imagen."
            return [_debug_text(agent_name, agent_slug, debug)]

        filenames = [str(img.get("savedFilename") or img.get("filename") or "") for img in images]
        filenames = [f for f in filenames if f]
        debug["filename"] = filenames[0] if filenames else None
        if not filenames:
            debug["error"] = "No se pudo determinar el nombre de fichero de la imagen generada."
            return [_debug_text(agent_name, agent_slug, debug)]
        filename = filenames[-1]
        session_state.set_last_image(filename)
        session_state.set_last_generation({
            "kind": "create",
            "model": record.get("name"),
            "model_id": record.get("slug") or record.get("id"),
            "prompt": prompt,
            "negative_prompt": basic_values.get("negative") or None,
            "seed": result.get("appliedSeed"),
            "width": width,
            "height": height,
            "count": len(filenames),
            "speed": speed,
            "quantization": chosen_id or None,
            "images": [{"id": name, "url": _client.image_url(name, viewer_id=agent_slug)} for name in filenames],
        })
        session_note = await mcp_sessions.auto_add(_client, agent_slug)

        output_dir = await _client.get_output_dir()
        image_blocks: list[ImageContent] = []
        for name in filenames:
            thumb_bytes, thumb_mime = read_thumbnail(output_dir, agent_slug, name, THUMBNAIL_WIDTH)
            image_blocks.append(ImageContent(type="image", data=base64.b64encode(thumb_bytes).decode("ascii"),
                                             mimeType=thumb_mime))
        debug["thumbnail_source"] = "local_disk"
        public_url = _client.image_url(filename, viewer_id=agent_slug)
        debug["image_url_with_cookie_bypass"] = public_url
        _log(f"THUMBNAILS (disco local): {len(image_blocks)}, url={public_url}")

        links = "\n".join(f"- {name}: {_client.image_url(name, viewer_id=agent_slug)}" for name in filenames)
        # Midjourney-only parameters (--stylize...) are dropped silently, as in the app.
        params_note = ""
        if len(filenames) > 1:
            params_note += (f"\nSe han generado {len(filenames)} imagenes; 'la imagen' en lo siguiente "
                            f"es la ultima, {filename}, salvo que el usuario elija otra por su nombre.")

        quant_note = ""
        if quant_options:
            how_chosen = "pedida explicitamente" if quantization else f"auto, segun speed='{speed}'"
            quant_note = (
                f"\nCuantizacion usada: {chosen_id or 'por defecto del workflow'} ({how_chosen})."
                f"\nOtras opciones disponibles en este modelo:\n{describe_quantization_options(quant_options)}\n"
            )

        return [
            *image_blocks,
            TextContent(
                type="text",
                text=(
                    f"Generado con Nomad Studio — modelo: {record.get('name', 'desconocido')}, "
                    f"cuantizacion: {chosen_id or 'por defecto del workflow'} "
                    f"(velocidad pedida: {speed}).\n"
                    f"Tamano: {width}x{height}. Semilla usada: {result.get('appliedSeed')} (pasala en 'seed' "
                    f"para repetir esta imagen o variarla solo con cambios en el prompt).{params_note}{session_note}\n"
                    f"Enlace directo a la imagen (sin login, no requiere sesion): {public_url}\n"
                    + (f"Todas las imagenes de esta tanda:\n{links}\n" if len(filenames) > 1 else "")
                    + "Si tienes un navegador o visor integrado en este entorno, abrelo ahi para "
                    f"ensenarsela al usuario directamente en el chat, sin que tenga que pedirlo."
                    f"{quant_note}\n"
                    f"AGENT: {agent_name}\nUSER: {agent_slug}\n\n"
                    f"```json\n{json.dumps(debug, indent=2, ensure_ascii=False)}\n```"
                ),
            ),
        ]

    except NoMatchingImportError as exc:
        debug["error"] = str(exc)
        _log(f"ERROR: {exc}")
        return [_debug_text(agent_name, agent_slug, debug)]
    except LocalImageNotFoundError as exc:
        debug["error"] = str(exc)
        _log(f"ERROR: {exc}")
        return [_debug_text(agent_name, agent_slug, debug)]
    except NomadClientError as exc:
        debug["error"] = f"No se pudo conectar con Nomad Studio: {exc}. ¿Esta la app abierta y corriendo?"
        _log(f"ERROR: {exc}")
        return [_debug_text(agent_name, agent_slug, debug)]


@mcp.tool(
    name="nomad_studio_list_models",
    description=(
        "Lista los modelos/checkpoints que el usuario tiene importados en Nomad Studio, con las "
        "opciones de cuantizacion de cada uno y una explicacion de su calidad/velocidad. Usa esto "
        "cuando el usuario pregunte que modelos o cuantizaciones tiene disponibles (ej. '¿cuales "
        "tengo?', 'que modelos hay') — en vez de intentar responder sin datos o buscar en el "
        "sistema de ficheros. No genera ni modifica nada."
    ),
    structured_output=False,
    annotations=_READ_TOOL,
)
async def nomad_studio_list_models(ctx: Context) -> list[TextContent]:
    """Sin argumentos. Devuelve la lista de modelos que el usuario tiene importados en Nomad
    Studio, y para cada uno sus opciones de cuantizacion disponibles con una frase de
    calidad/velocidad de cada una — para poder responder preguntas del usuario y para saber
    que pasarle luego a nomad_studio_create_image en 'model'/'quantization'."""
    try:
        imports = await _client.list_imports()
    except NomadClientError as exc:
        return [
            TextContent(
                type="text",
                text=f"No se pudo conectar con Nomad Studio: {exc}. ¿Esta la app abierta y corriendo?",
            )
        ]

    if not imports:
        return [
            TextContent(
                type="text",
                text="No hay ningun modelo importado en Nomad Studio todavia. Importa uno desde la seccion Imports.",
            )
        ]

    lines = ["Modelos disponibles en Nomad Studio (entre parentesis, su identificador para '--v' en el "
             "prompt o para el argumento 'model'):\n"]
    for imp in imports:
        name = str(imp.get("name", "") or imp.get("id", ""))
        try:
            record = await _client.get_import(str(imp.get("id", "")))
        except NomadClientError:
            record = {}
        quant_block = (record.get("analysis") or {}).get("quantization")
        options = (quant_block or {}).get("options") or []
        slug = str(imp.get("slug") or "")
        lines.append(f"## {name}" + (f"  (--v {slug})" if slug else ""))
        lines.append(describe_quantization_options(options))
        lines.append("")

    return [TextContent(type="text", text="\n".join(lines))]


@mcp.tool(
    name="nomad_studio_list_refine_actions",
    description=(
        "Lista las acciones de Refine disponibles ahora mismo en Nomad Studio (built-in + "
        "packs instalados por el usuario) para usar con nomad_studio_refine_image — su id "
        "exacto y una descripcion de que hace cada una. Usa esto cuando no sepas que 'action' "
        "pasar, o cuando el usuario pregunte que retoques/ediciones estan disponibles."
    ),
    structured_output=False,
    annotations=_READ_TOOL,
)
async def nomad_studio_list_refine_actions(ctx: Context) -> list[TextContent]:
    """Sin argumentos. Devuelve el catalogo completo de acciones de Refine (id + descripcion,
    agrupadas por categoria) que se puede pasar en el parametro 'action' de
    nomad_studio_refine_image."""
    try:
        catalog = await refine_actions.get_catalog(_client)
    except NomadClientError as exc:
        return [
            TextContent(
                type="text",
                text=f"No se pudo conectar con Nomad Studio: {exc}. ¿Esta la app abierta y corriendo?",
            )
        ]
    return [TextContent(type="text", text=refine_actions.describe_actions(catalog))]


@mcp.tool(
    name="nomad_studio_get_last_generation",
    description=(
        "Devuelve lo ultimo que se ha generado o retocado con Nomad Studio en esta conversacion: "
        "prompt, negativo, semilla, tamano, modelo, numero de imagenes y enlace a cada una (o la "
        "accion de Refine y la imagen de origen). Usa esto para recordar o repetir una imagen, o "
        "para contestar que parametros se usaron. No genera ni modifica nada."
    ),
    structured_output=False,
    annotations=_READ_TOOL,
)
async def nomad_studio_get_last_generation(ctx: Context) -> list[TextContent]:
    generation = session_state.get_last_generation()
    if not generation:
        return [TextContent(type="text", text=(
            "Todavia no se ha generado ni retocado ninguna imagen en esta conversacion."))]
    return [TextContent(type="text", text=(
        "Ultima generacion de esta conversacion:\n"
        f"```json\n{json.dumps(generation, indent=2, ensure_ascii=False)}\n```"))]


class MixImage(BaseModel):
    """Una imagen de entrada de un Mix y el hueco (papel) que ocupa."""

    filename: str = Field(..., description=(
        "Fichero de la imagen, tal y como aparecio en una respuesta anterior (create_image, "
        "refine_image, mix_images) o 'session/<carpeta>/<fichero>' de nomad_studio_get_session."))
    slot: str | None = Field(None, description=(
        "Hueco que ocupa, el id que da nomad_studio_list_mix_actions ('image', 'image_2'...: "
        "cada uno tiene un papel, ej. fondo, sujeto, referencia de estilo). Vacio = el siguiente "
        "hueco libre, en el orden del flow."))


def _resolve_aspect(value: str | None) -> tuple[int, int] | None:
    """'wide'/'landscape'... o 'W:H' -> tamano en pixeles (~1 MP); None si vacio."""
    text = (value or "").strip().lower()
    if not text:
        return None
    if text in ASPECT_RATIO_DIMENSIONS:
        return ASPECT_RATIO_DIMENSIONS[text]
    w, sep, h = text.partition(":")
    if not sep or not (w.isdigit() and h.isdigit()) or not int(w) or not int(h):
        raise ValueError(f"'{value}' no es un formato valido (usa 16:9, 3:2, square, wide...)")
    return size_for_aspect((int(w), int(h)))


@mcp.tool(
    name="nomad_studio_list_mix_actions",
    description=(
        "Lista los flows de Mix de Nomad Studio (combinar varias imagenes en una: componer un "
        "sujeto sobre un fondo, pasar el estilo de una imagen a otra...) para usar con "
        "nomad_studio_mix_images: su id, que hace, y los huecos de imagen de cada uno con su "
        "papel. Usa esto antes de mezclar imagenes si no sabes que 'action' o que huecos usar."
    ),
    structured_output=False,
    annotations=_READ_TOOL,
)
async def nomad_studio_list_mix_actions(ctx: Context) -> list[TextContent]:
    try:
        catalog = await mix_actions.get_catalog(_client)
    except NomadClientError as exc:
        return [TextContent(type="text", text=(
            f"No se pudo conectar con Nomad Studio: {exc}. ¿Esta la app abierta y corriendo?"))]
    return [TextContent(type="text", text=(
        "Flows de Mix (en la instruction, <image1> es el primer hueco, <image2> el segundo...):\n"
        + mix_actions.describe_actions(catalog)))]


@mcp.tool(
    name="nomad_studio_mix_images",
    description=(
        "Combina 100% en local varias imagenes en una nueva con un flow de Mix de Nomad Studio: "
        "poner un sujeto sobre un fondo, juntar varias referencias en una escena, o aplicar el "
        "estilo de una imagen a otra. Cada imagen va en un hueco con su papel (fondo, sujeto, "
        "referencia de estilo...): los ids de flow y de hueco los da nomad_studio_list_mix_actions. "
        "Para editar UNA sola imagen usa nomad_studio_refine_image; para crear desde cero, "
        "nomad_studio_create_image."
    ),
    structured_output=False,
    annotations=_WRITE_TOOL,
)
async def nomad_studio_mix_images(
    action: Annotated[str, Field(description=(
        "Id exacto del flow de Mix (ej. 'mix.multi_reference_compose_quick', "
        "'mix.style_transfer_qwen_2511'), de nomad_studio_list_mix_actions."))],
    images: Annotated[list[MixImage], Field(description=(
        "Las imagenes de entrada, cada una con su hueco. Hay que llenar todos los huecos no "
        "opcionales del flow. Si el usuario no dice que papel tiene cada una y no es obvio, "
        "preguntaselo."))],
    ctx: Context,
    instruction: Annotated[str | None, Field(description=(
        "Que hacer, en ingles, nombrando cada imagen por su hueco: <image1> = el primer hueco "
        "del flow, <image2> el segundo... (ej. 'Place the person from <image2> into the "
        "background <image1>, sitting on the bench.'). Vacio = la instruccion por defecto del "
        "flow, si la tiene."))] = None,
    aspect_ratio: Annotated[str | None, Field(description=(
        "Formato de la imagen final, SOLO en los flows marcados 'accepts aspect_ratio': "
        "'16:9', '3:2', 'square', 'wide', 'tall', 'landscape', 'portrait'... Vacio = el del "
        "flow."))] = None,
    seed: Annotated[int | None, Field(description=(
        "Semilla exacta, SOLO para repetir un resultado anterior. Vacio = aleatoria."))] = None,
    variation: Annotated[str | None, Field(description=(
        "SOLO en los flows marcados 'accepts variation' en nomad_studio_list_mix_actions. "
        "'turbo' = checkpoint destilado, unas 2 veces mas rapido (8 pasos) con calidad parecida; "
        "'normal' o vacio = el modelo base. Usa 'turbo' si el usuario pide rapidez o lo nombra."))] = None,
) -> list[TextContent | ImageContent]:
    agent_name = agent_slug = "unknown"
    debug: dict[str, Any] = {"input": {
        "action": action, "images": [i.model_dump() for i in images], "instruction": instruction,
        "aspect_ratio": aspect_ratio, "seed": seed, "variation": variation}}
    try:
        agent = await ensure_agent_session(_client, ctx)
        agent_name, agent_slug = agent.get("name", "unknown"), agent.get("slug", "unknown")
        catalog = await mix_actions.get_catalog(_client)
        mix = catalog.get(action.strip())
        if mix is None:
            return [TextContent(type="text", text=(
                f"NO SE HA HECHO NADA TODAVIA. '{action}' no es un flow de Mix valido. Elige uno de "
                f"estos:\n{mix_actions.describe_actions(catalog)}"))]

        # Cada imagen a su hueco: los que se nombran, y el resto al siguiente
        # libre en el orden del flow.
        by_slot = {s.slot: s for s in mix.slots}
        assigned: dict[str, str] = {}
        problems: list[str] = []
        for img in images:
            if img.slot:
                if img.slot not in by_slot:
                    problems.append(f"'{img.slot}' no es un hueco de {mix.flow_id}")
                elif img.slot in assigned:
                    problems.append(f"el hueco '{img.slot}' tiene dos imagenes")
                else:
                    assigned[img.slot] = img.filename
        for img in images:
            if not img.slot:
                free = next((s.slot for s in mix.slots if s.slot not in assigned), None)
                if free is None:
                    problems.append(f"sobra la imagen '{img.filename}': no quedan huecos")
                else:
                    assigned[free] = img.filename
        missing = [s for s in mix.required_slots if s.slot not in assigned]
        if missing:
            problems.append("faltan imagenes para: " + ", ".join(f"'{s.slot}' ({s.label})" for s in missing))
        if problems:
            slots = "\n".join(f"- '{s.slot}': {s.label}{' (opcional)' if s.optional else ''}" for s in mix.slots)
            return [TextContent(type="text", text=(
                "NO SE HA HECHO NADA TODAVIA: " + "; ".join(problems)
                + f".\nHuecos de {mix.flow_id}, en orden (<image1>, <image2>...):\n{slots}"))]

        try:
            size = _resolve_aspect(aspect_ratio) if mix.width_key else None
        except ValueError as exc:
            return [TextContent(type="text", text=f"NO SE HA HECHO NADA TODAVIA: {exc}.")]
        if mix.width_key and size is None:
            size = size_for_aspect(mix.default_aspect)
        advanced = mix_actions.advanced_values(mix, instruction, size, seed)
        try:
            advanced.update(await variations.advanced_values(_client, mix.workflow_file, variation))
        except variations.VariationError as exc:
            return [TextContent(type="text", text=f"NO SE HA HECHO NADA TODAVIA: {exc}.")]

        output_dir = await _client.get_output_dir()
        payload_images = [
            {"dataUrl": read_full_image_as_data_url(output_dir, agent_slug, assigned[s.slot]) if s.slot in assigned else "",
             "nodeId": s.node_id}
            for s in mix.slots
        ]
        debug["slots"] = assigned
        debug["request"] = {"workflowFile": mix.workflow_file, "advancedValues": advanced}
        _log(f"MIX REQUEST: {json.dumps(debug['request'], ensure_ascii=False)}")
        result = await _client.submit_mix(mix.workflow_file, payload_images, advanced)
        debug["response"] = result
        saved = result.get("savedFilename")
        if not saved:
            debug["error"] = "Nomad Studio no devolvio el nombre del fichero."
            return [_debug_text(agent_name, agent_slug, debug)]

        prompt_used = advanced.get(mix.prompt_key) if mix.prompt_key else None
        session_state.set_last_image(saved)
        session_state.set_last_generation({
            "kind": "mix",
            "action": mix.flow_id,
            "flow_label": mix.label,
            "inputs": assigned,
            "instruction": prompt_used,
            "workflow_file": mix.workflow_file,
            "advanced_values": advanced,
            "images": [{"id": saved, "url": _client.image_url(saved, viewer_id=agent_slug)}],
        })
        session_note = await mcp_sessions.auto_add(_client, agent_slug)

        thumb, mime = read_thumbnail(output_dir, agent_slug, saved, THUMBNAIL_WIDTH)
        public_url = _client.image_url(saved, viewer_id=agent_slug)
        used = ", ".join(f"{slot} = {name}" for slot, name in assigned.items())
        return [
            ImageContent(type="image", data=base64.b64encode(thumb).decode("ascii"), mimeType=mime),
            TextContent(type="text", text=(
                f"Mezclado con Nomad Studio — flow: {mix.label} ({mix.flow_id}). Imagenes: {used}."
                f"{session_note}\n"
                f"Enlace directo a la imagen (sin login, no requiere sesion): {public_url}\n"
                f"Si tienes un navegador o visor integrado en este entorno, abrelo ahi para "
                f"ensenarsela al usuario directamente en el chat, sin que tenga que pedirlo.\n\n"
                f"AGENT: {agent_name}\nUSER: {agent_slug}\n\n"
                f"```json\n{json.dumps(debug, indent=2, ensure_ascii=False)}\n```"
            )),
        ]
    except LocalImageNotFoundError as exc:
        debug["error"] = str(exc)
        return [_debug_text(agent_name, agent_slug, debug)]
    except NomadClientError as exc:
        debug["error"] = f"No se pudo conectar con Nomad Studio: {exc}. ¿Esta la app abierta y corriendo?"
        return [_debug_text(agent_name, agent_slug, debug)]


def _session_image_ref(url: str) -> str:
    """"/api/images/session/<carpeta>/<fichero>" -> "session/<carpeta>/<fichero>",
    lo que aceptan 'filename' de refine_image y add_to_session."""
    return url[len("/api/images/"):] if url.startswith("/api/images/") else url


def _step_prompt(step: dict[str, Any]) -> str:
    params = step.get("params") if isinstance(step.get("params"), dict) else {}
    prompt = str(params.get("prompt") or "").strip()
    return prompt if len(prompt) <= 300 else prompt[:297] + "..."


@mcp.tool(
    name="nomad_studio_list_sessions",
    description=(
        "Lista las sessions de Nomad Studio que se pueden ver desde aqui (las compartidas con "
        "todos): id, nombre, numero de pasos y fecha. Una session es un proyecto de la app que "
        "guarda, paso a paso, las imagenes creadas y retocadas y como se hizo cada una. Usa "
        "esto cuando el usuario hable de sus sessions o quiera guardar/continuar algo en una. "
        "No genera ni modifica nada."
    ),
    structured_output=False,
    annotations=_READ_TOOL,
)
async def nomad_studio_list_sessions(ctx: Context) -> list[TextContent]:
    try:
        await ensure_agent_session(_client, ctx)
        sessions = await _client.list_sessions()
    except NomadClientError as exc:
        return [TextContent(type="text", text=(
            f"No se pudo conectar con Nomad Studio: {exc}. ¿Esta la app abierta y corriendo?"))]
    if not sessions:
        return [TextContent(type="text", text=(
            "No hay ninguna session visible. Se puede crear una con nomad_studio_add_to_session "
            "(argumento 'new_session_name')."))]
    sessions = sorted(sessions, key=lambda s: str(s.get("createdAt") or ""), reverse=True)
    following = session_state.get_follow_session()
    lines = ["Sessions de Nomad Studio (las mas recientes primero):\n"]
    for sess in sessions[:40]:
        steps = sess.get("steps") or []
        mark = "  <- esta conversacion guarda aqui sus imagenes" if sess.get("id") == following else ""
        lines.append(f"- {sess.get('name') or 'Sin nombre'} — id: {sess.get('id')}, {len(steps)} pasos, "
                     f"creada {str(sess.get('createdAt') or '')[:10]}{mark}")
    if len(sessions) > 40:
        lines.append(f"... y {len(sessions) - 40} mas.")
    return [TextContent(type="text", text="\n".join(lines))]


@mcp.tool(
    name="nomad_studio_get_session",
    description=(
        "Lee una session de Nomad Studio: sus pasos en orden, con el flow usado, de que paso "
        "sale cada uno, el prompt y sus imagenes, mas una miniatura de la ultima. Usa esto para "
        "contar que hay en una session o antes de retocar la imagen de uno de sus pasos (pasa "
        "su 'session/...' en 'filename' de nomad_studio_refine_image). No genera ni modifica nada."
    ),
    structured_output=False,
    annotations=_READ_TOOL,
)
async def nomad_studio_get_session(
    session_id: Annotated[str, Field(description=(
        "Id de la session ('session-...'), tal y como lo da nomad_studio_list_sessions."))],
    ctx: Context,
) -> list[TextContent | ImageContent]:
    try:
        await ensure_agent_session(_client, ctx)
        sess = await _client.get_session(session_id.strip())
        output_dir = await _client.get_output_dir()
    except NomadClientError as exc:
        return [TextContent(type="text", text=(
            f"No se pudo conectar con Nomad Studio: {exc}. ¿Esta la app abierta y corriendo?"))]
    if sess is None:
        return [TextContent(type="text", text=(
            f"No hay ninguna session visible con id '{session_id}'. Mira los ids reales con "
            "nomad_studio_list_sessions."))]

    steps = [s for s in sess.get("steps") or [] if isinstance(s, dict)]
    index = {s.get("id"): n for n, s in enumerate(steps, 1)}
    lines = [f"Session '{sess.get('name')}' (id: {sess.get('id')}), {len(steps)} pasos:\n"]
    for n, step in enumerate(steps, 1):
        parent = index.get(step.get("parentId"))
        head = f"{n}. {step.get('flowLabel') or 'Paso'} [{step.get('flowCategory')}"
        head += f": {step.get('flowAction')}]" if step.get("flowAction") else "]"
        if parent:
            head += f" — sale del paso {parent}"
        if step.get("selected"):
            head += " — SELECCIONADO"
        if str(step.get("source") or "").startswith("mcp:"):
            head += " — anadido por un agente"
        lines.append(head + f"  (id: {step.get('id')})")
        prompt = _step_prompt(step)
        if prompt:
            lines.append(f"   prompt: {prompt}")
        images = step.get("images") or ([step["imageUrl"]] if step.get("imageUrl") else [])
        for url in images:
            lines.append(f"   imagen: {_session_image_ref(url)} — {_client.absolute_url(url)}")
    blocks: list[TextContent | ImageContent] = []
    last = next((s for s in reversed(steps) if s.get("imageUrl")), None)
    if last:
        try:
            thumb, mime = read_thumbnail(output_dir, "", _session_image_ref(last["imageUrl"]), THUMBNAIL_WIDTH)
            blocks.append(ImageContent(type="image", data=base64.b64encode(thumb).decode("ascii"), mimeType=mime))
        except LocalImageNotFoundError:
            pass
    return [*blocks, TextContent(type="text", text="\n".join(lines))]


@mcp.tool(
    name="nomad_studio_add_to_session",
    description=(
        "Guarda en una session de Nomad Studio lo ultimo que se ha generado o retocado en esta "
        "conversacion, como un paso nuevo (con su prompt y ajustes, y colgando del paso de su "
        "imagen de origen si se retoco una imagen de la session). La session puede ser una que "
        "ya exista o una nueva. Por defecto, a partir de ahi cada imagen que se genere o retoque "
        "en esta conversacion se anade sola a esa misma session. Usa esto cuando el usuario pida "
        "guardar, apuntar o llevar sus imagenes a una session o proyecto."
    ),
    structured_output=False,
    annotations=_WRITE_TOOL,
)
async def nomad_studio_add_to_session(
    ctx: Context,
    session_id: Annotated[str | None, Field(description=(
        "Id de una session existente ('session-...', de nomad_studio_list_sessions). Vacio = la "
        "session donde esta conversacion ya viene guardando, o una nueva si se da "
        "'new_session_name'."))] = None,
    new_session_name: Annotated[str | None, Field(description=(
        "Nombre para crear una session nueva (visible para todos en la app), SOLO si el usuario "
        "no quiere usar una existente. Se ignora si se pasa 'session_id'."))] = None,
    filename: Annotated[str | None, Field(description=(
        "Solo una de las imagenes de la ultima tanda (su fichero, como aparecio en la respuesta). "
        "Vacio = todas las imagenes de lo ultimo generado o retocado."))] = None,
    parent_step_id: Annotated[str | None, Field(description=(
        "Id del paso del que sale este ('step-...', de nomad_studio_get_session), SOLO si el "
        "usuario lo indica. Vacio = se deduce solo (el paso de la imagen retocada) o ninguno."))] = None,
    keep_adding: Annotated[bool, Field(description=(
        "True (lo normal) = a partir de ahora cada imagen nueva de esta conversacion se anade "
        "sola a esta session. False = anadir solo esta vez."))] = True,
) -> list[TextContent]:
    generation = session_state.get_last_generation()
    if not generation:
        return [TextContent(type="text", text=(
            "NO SE HA HECHO NADA TODAVIA. En esta conversacion aun no se ha generado ni retocado "
            "ninguna imagen: genera una primero con nomad_studio_create_image."))]
    files = [str(img.get("id")) for img in generation.get("images") or [] if img.get("id")]
    if filename:
        if filename not in files:
            return [TextContent(type="text", text=(
                f"NO SE HA HECHO NADA TODAVIA. '{filename}' no es de la ultima tanda; sus imagenes "
                f"son: {', '.join(files)}."))]
        files = [filename]
    try:
        agent = await ensure_agent_session(_client, ctx)
        agent_slug = agent.get("slug", "unknown")
        target = (session_id or "").strip() or None
        created_name = None
        if target is None and not (new_session_name or "").strip():
            target = session_state.get_follow_session()
        if target is None:
            name = (new_session_name or "").strip()
            if not name:
                return [TextContent(type="text", text=(
                    "NO SE HA HECHO NADA TODAVIA. Falta a que session anadirla: pregunta al usuario "
                    "si quiere una existente (llama a nomad_studio_list_sessions para ensenarle "
                    "cuales hay) o una nueva, y con que nombre."))]
            created = await _client.create_session(name)
            target, created_name = created.get("id"), name
        elif await _client.get_session(target) is None:
            return [TextContent(type="text", text=(
                f"NO SE HA HECHO NADA TODAVIA. No hay ninguna session visible con id '{target}'. "
                "Mira los ids reales con nomad_studio_list_sessions."))]
        already = {session_state.step_for_image(name, target) for name in files}
        if None not in already:
            # Ya entro sola (keep_adding de una llamada anterior).
            session_state.set_follow_session(target if keep_adding else session_state.get_follow_session())
            return [TextContent(type="text", text=(
                f"Ya estaba en la session {target} (paso {', '.join(sorted(already))}): no se ha "
                "anadido otra vez."))]
        step = await mcp_sessions.add_generation(
            _client, target, generation, agent_slug, files=files,
            parent_step_id=(parent_step_id or "").strip() or None)
    except NomadClientError as exc:
        return [TextContent(type="text", text=f"No se pudo anadir a la session: {exc}")]
    session_state.set_follow_session(target if keep_adding else session_state.get_follow_session())
    text = (f"Anadido a la session {'nueva ' + repr(created_name) + ' ' if created_name else ''}"
            f"(id: {target}) como paso {step.get('id')}"
            + (f", colgando del paso {step.get('parentId')}" if step.get("parentId") else "")
            + f", con {len(files)} imagen(es). El usuario lo ve en Nomad Studio > Session "
            f"({_client.absolute_url('/nomad-studio/session/' + str(target))}).")
    if keep_adding:
        text += " Desde ahora, cada imagen que se genere o retoque en esta conversacion se anade sola ahi."
    return [TextContent(type="text", text=text)]


_REFINE_SEED_RE = re.compile(r"\s*--(?:same)?seed[\s=]+(\d+)\b", re.IGNORECASE)

_OUTPAINT_POSITIONS = {
    "center", "top", "bottom", "left", "right",
    "top-left", "top-right", "bottom-left", "bottom-right",
}


async def _nomad_studio_refine_image_impl(
    action: Annotated[str, Field(description=(
        "Que retoque aplicar: el id exacto de un flow de Refine de Nomad Studio (ej. "
        "'refine.pf_relight', 'refine.remove_bg_simple', 'refine.outpaint'). Si no sabes que ids "
        "hay, llama primero a nomad_studio_list_refine_actions (lista completa, con descripcion y "
        "categoria). Con un id invalido, esta tool devuelve esa lista en el error."))],
    ctx: Context,
    filename: Annotated[str | None, Field(description=(
        "Fichero de la imagen a editar, tal y como aparecio en una respuesta anterior de esta "
        "conversacion (create_image o esta tool), o la de un paso de una session tal y como la da "
        "nomad_studio_get_session ('session/<carpeta>/<fichero>'). Si el usuario dice 'la "
        "imagen'/'esta foto' sin mas, dejalo vacio: se usa la ultima imagen generada en esta "
        "conversacion."))] = None,
    instruction: Annotated[str | None, Field(description=(
        "Detalle en ingles sobre COMO aplicar la accion (ej. relight: 'backlit rim light'; quitar "
        "un objeto: 'the red car'). Sin detalle del usuario, dejalo vacio: se usa un valor por "
        "defecto razonable. En las acciones con 'regions' es obligatorio y nombra cada zona por su "
        "color ('the red rectangle')."))] = None,
    position: Annotated[str | None, Field(description=(
        "SOLO para action='refine.outpaint'. Donde queda la imagen ORIGINAL en el lienzo nuevo: "
        "center, top, bottom, left, right, top-left, top-right, bottom-left o bottom-right. "
        "'bajala un poco' -> bottom (se rellena arriba); 'muevela a la izquierda' -> left (se "
        "rellena a la derecha). Vacio = center."))] = None,
    scale: Annotated[int | None, Field(description=(
        "SOLO para outpaint. 10-100: que porcentaje del lienzo nuevo ocupa la imagen original "
        "(100 = sin encoger). 'Reducela antes de expandir' -> 70-80. Vacio = 100."))] = None,
    expand_percent: Annotated[int | None, Field(description=(
        "SOLO para outpaint. Cuanto crece el lienzo, en % (40 = un 40% mas grande). Vacio = 40."))] = None,
    regions: Annotated[list[MarkedRegion] | None, Field(description=(
        "SOLO para las acciones marcadas [NEEDS 'regions'] en nomad_studio_list_refine_actions "
        "(Local Edit, Text Editor...), y ahi es obligatorio: las zonas a editar, que se marcan "
        "sobre la imagen con un contorno de color. Una entrada por zona, en % del lienzo "
        "(left/top/right/bottom de 0 a 100; la mitad superior = 0, 0, 100, 50) y un color distinto "
        "por zona (red, green, blue, yellow, purple, orange). La 'instruction' las nombra por su "
        "color: 'Replace the text inside the red rectangle with \"SALE\"'. Si no sabes donde "
        "esta algo, preguntaselo al usuario."))] = None,
    variation: Annotated[str | None, Field(description=(
        "SOLO en las acciones marcadas 'accepts variation' en nomad_studio_list_refine_actions. "
        "'turbo' = checkpoint destilado, unas 2 veces mas rapido (8 pasos) con calidad parecida; "
        "'normal' o vacio = el modelo base. Usa 'turbo' si el usuario pide rapidez o lo nombra."))] = None,
    aspect_ratio: Annotated[str | None, Field(description=(
        "SOLO en las acciones marcadas 'accepts aspect_ratio': forma de la imagen de SALIDA, "
        "distinta de la de entrada (ej. una vertical 9:16 recompuesta en 16:9). '16:9', '3:2', "
        "'square', 'wide', 'tall', 'original'... Mantiene los pixeles de la entrada. Vacio = la "
        "misma forma que la entrada. Ignorado si se pasan 'width'/'height'."))] = None,
    width: Annotated[int | None, Field(description=(
        "SOLO en las acciones marcadas 'accepts aspect_ratio': ancho exacto de la salida en "
        "pixeles, solo si el usuario da un tamano concreto (ej. '1280x720'). Va junto con 'height' "
        "(los dos o ninguno). Se redondea al multiplo de 16."))] = None,
    height: Annotated[int | None, Field(description="Alto exacto de la salida — ver 'width'.")] = None,
    seed: Annotated[int | None, Field(description=(
        "Semilla exacta, SOLO para repetir o variar un retoque anterior (cada respuesta dice la "
        "semilla usada). Misma imagen + accion + instruccion + semilla = el mismo resultado. "
        "Tambien vale '--seed 1234' al final de 'instruction'. Vacio = aleatoria (lo normal)."))] = None,
) -> list[TextContent | ImageContent]:
    agent_name = "unknown"
    agent_slug = "unknown"
    debug: dict[str, Any] = {
        "input": {
            "seed": seed,
            "action": action,
            "filename": filename,
            "instruction": instruction,
            "position": position,
            "scale": scale,
            "expand_percent": expand_percent,
            "regions": [r.model_dump() for r in regions] if regions else None,
            "variation": variation,
            "aspect_ratio": aspect_ratio,
            "width": width,
            "height": height,
        }
    }

    try:
        agent = await ensure_agent_session(_client, ctx)
        agent_name = agent.get("name", "unknown")
        agent_slug = agent.get("slug", "unknown")
        debug["agent"] = agent
        _log(f"AGENT: {agent_name} (user: {agent_slug}) — refinando imagen, action={action}")

        resolved_filename = filename or session_state.get_last_image()
        if not resolved_filename:
            return [
                TextContent(
                    type="text",
                    text=(
                        "NO SE HA HECHO NADA TODAVIA. No hay ninguna imagen generada en esta conversacion "
                        "todavia. Genera una primero con nomad_studio_create_image, o pasa el parametro "
                        "'filename' con el nombre exacto de una imagen ya generada."
                    ),
                )
            ]

        catalog = await refine_actions.get_catalog(_client)
        refine_action = catalog.get(action.strip())
        if refine_action is None:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"NO SE HA HECHO NADA TODAVIA. '{action}' no es una accion valida. Elige una de estas "
                        f"y vuelve a llamar a la tool:\n{refine_actions.describe_actions(catalog)}"
                    ),
                )
            ]
        debug["flow_id"] = refine_action.flow_id

        if refine_action.needs_region:
            shape_word = "rectangle" if refine_action.region_shape == "rect" else "circle"
            problem = None
            if not regions:
                problem = "esta accion edita zonas marcadas y no se ha pasado ninguna en 'regions'"
            elif any(r.right == r.left or r.bottom == r.top for r in regions):
                problem = "alguna zona de 'regions' no tiene ancho o alto (left == right o top == bottom)"
            elif not (instruction or "").strip():
                problem = "falta 'instruction': tiene que decir que hacer en cada zona, nombrandola por su color"
            if problem:
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"NO SE HA HECHO NADA TODAVIA: {problem}. Pasa 'regions' (una por zona, en % del "
                            f"lienzo, cada una con su color) y una 'instruction' en ingles que las nombre, ej. "
                            f"\"... inside the red {shape_word} ...\". Si no sabes donde esta lo que hay que "
                            f"editar, preguntaselo al usuario."
                        ),
                    )
                ]
        elif regions:
            debug["regions_ignored"] = "esta accion no usa zonas marcadas"

        # "--seed 1234" at the end of the instruction, as in create_image; it
        # wins over the 'seed' argument.
        seed_match = _REFINE_SEED_RE.search(instruction or "")
        if seed_match:
            seed = int(seed_match.group(1))
            instruction = (instruction[:seed_match.start()] + instruction[seed_match.end():]).strip() or None
        applied_seed = None
        if refine_action.seed_keys:
            applied_seed = max(0, int(seed)) if seed is not None else secrets.randbelow(2**48)
        elif seed is not None:
            debug["seed_ignored"] = "esta accion no usa semilla (no genera con difusion)"
        advanced_values: dict[str, Any] = dict(refine_action.extra_advanced_values)
        for seed_key in refine_action.seed_keys:
            advanced_values[seed_key] = applied_seed
        if refine_action.prompt_adv_key:
            advanced_values[refine_action.prompt_adv_key] = instruction or refine_action.default_prompt
            if refine_action.needs_region and regions:
                # Tested: without this the colored outline stays painted in the
                # result (same fix the pack-cover scripts use).
                shape_word = "rectangle" if refine_action.region_shape == "rect" else "circle"
                marks = " and the ".join(dict.fromkeys(f"{r.color} {shape_word}" for r in regions))
                advanced_values[refine_action.prompt_adv_key] = (
                    advanced_values[refine_action.prompt_adv_key].rstrip() + f" Remove the {marks}.")

        output_dir = await _client.get_output_dir()

        if refine_action.is_outpaint_shaped:
            if position is not None and position.strip().lower() not in _OUTPAINT_POSITIONS:
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"NO SE HA HECHO NADA TODAVIA. '{position}' no es una posicion valida. Usa una de "
                            + ", ".join(sorted(_OUTPAINT_POSITIONS))
                            + "."
                        ),
                    )
                ]
            scale_pct = max(10, min(100, scale if scale is not None else 100))
            expand_pct = max(0, expand_percent if expand_percent is not None else 40)

            from PIL import Image as _PILImage

            source_path = image_path(output_dir, agent_slug, resolved_filename)
            with _PILImage.open(source_path) as _im:
                orig_w, orig_h = _im.size
            factor = 1.0 + (expand_pct / 100.0)
            target_w = max(64, round(orig_w * factor / 64) * 64)
            target_h = max(64, round(orig_h * factor / 64) * 64)

            advanced_values[refine_action.width_adv_key] = target_w
            advanced_values[refine_action.height_adv_key] = target_h
            advanced_values[refine_action.position_adv_key] = (position or "center").strip().lower()
            advanced_values[refine_action.scale_adv_key] = scale_pct
            debug["outpaint_geometry"] = {
                "original_size": [orig_w, orig_h],
                "target_size": [target_w, target_h],
                "position": advanced_values[refine_action.position_adv_key],
                "scale": scale_pct,
                "expand_percent": expand_pct,
            }

        try:
            advanced_values.update(
                await variations.advanced_values(_client, refine_action.workflow_file, variation))
        except variations.VariationError as exc:
            return [TextContent(type="text", text=f"NO SE HA HECHO NADA TODAVIA: {exc}.")]

        if aspect_ratio or width or height:
            if not refine_action.accepts_output_size:
                debug["output_size_ignored"] = "esta accion no cambia la forma de salida"
            elif width or height:
                if not (width and height) or width <= 0 or height <= 0:
                    return [TextContent(type="text", text=(
                        "NO SE HA HECHO NADA TODAVIA: 'width' y 'height' van juntos (los dos o ninguno)."))]
                advanced_values[refine_action.output_width_key] = max(64, round(width / 16) * 16)
                advanced_values[refine_action.output_height_key] = max(64, round(height / 16) * 16)
            elif aspect_ratio.strip().lower() not in ("original", "same", "input"):
                try:
                    ratio_w, ratio_h = _resolve_aspect(aspect_ratio)
                except ValueError as exc:
                    return [TextContent(type="text", text=f"NO SE HA HECHO NADA TODAVIA: {exc}.")]
                # The app keeps the source's pixel count in the new shape
                # (refine_routes._apply_output_aspect) — the ratio is all it needs.
                advanced_values["_output.aspect"] = f"{ratio_w}:{ratio_h}"
                advanced_values["_output.width_key"] = refine_action.output_width_key
                advanced_values["_output.height_key"] = refine_action.output_height_key

        debug["advancedValues"] = advanced_values

        image_data_url = read_full_image_as_data_url(output_dir, agent_slug, resolved_filename)
        if refine_action.needs_region and regions:
            image_data_url = annotate_data_url(image_data_url, regions, refine_action.region_shape)
            debug["regions_drawn"] = f"{len(regions)} x {refine_action.region_shape}"

        request_payload = {"workflowFile": refine_action.workflow_file, "advancedValues": advanced_values}
        debug["request"] = request_payload
        _log(f"REQUEST: {json.dumps(request_payload, ensure_ascii=False)}")

        result = await _client.submit_refine(
            workflow_file=refine_action.workflow_file,
            image_data_url=image_data_url,
            advanced_values=advanced_values,
        )
        debug["response"] = result
        _log(f"RESPONSE: {json.dumps(result, ensure_ascii=False)}")

        saved_filename = result.get("savedFilename")
        if not saved_filename:
            debug["error"] = "Nomad Studio no devolvio el nombre del fichero refinado."
            return [_debug_text(agent_name, agent_slug, debug)]
        session_state.set_last_image(saved_filename)
        session_state.set_last_generation({
            "kind": "refine",
            "seed": applied_seed,
            "action": refine_action.flow_id,
            "source_image": resolved_filename,
            "flow_label": refine_action.label,
            "instruction": advanced_values.get(refine_action.prompt_adv_key) if refine_action.prompt_adv_key else None,
            "workflow_file": refine_action.workflow_file,
            "advanced_values": advanced_values,
            "images": [{"id": saved_filename, "url": _client.image_url(saved_filename, viewer_id=agent_slug)}],
        })
        session_note = await mcp_sessions.auto_add(_client, agent_slug)

        thumb_bytes, thumb_mime = read_thumbnail(output_dir, agent_slug, saved_filename, THUMBNAIL_WIDTH)
        thumb_b64 = base64.b64encode(thumb_bytes).decode("ascii")
        debug["thumbnail_bytes"] = len(thumb_bytes)
        public_url = _client.image_url(saved_filename, viewer_id=agent_slug)
        debug["image_url_with_cookie_bypass"] = public_url
        _log(f"THUMBNAIL (disco local): {len(thumb_bytes)} bytes, url={public_url}")

        return [
            ImageContent(type="image", data=thumb_b64, mimeType=thumb_mime),
            TextContent(
                type="text",
                text=(
                    f"Refinado con Nomad Studio — accion: {action} ({refine_action.flow_id}).{session_note}\n"
                    + (f"Semilla usada: {applied_seed} (pasala en 'seed' para repetir este retoque "
                       f"exacto).\n" if applied_seed is not None else "") +
                    f"Enlace directo a la imagen (sin login, no requiere sesion): {public_url}\n"
                    f"Si tienes un navegador o visor integrado en este entorno, abrelo ahi para "
                    f"ensenarsela al usuario directamente en el chat, sin que tenga que pedirlo.\n\n"
                    f"AGENT: {agent_name}\nUSER: {agent_slug}\n\n"
                    f"```json\n{json.dumps(debug, indent=2, ensure_ascii=False)}\n```"
                ),
            ),
        ]

    except LocalImageNotFoundError as exc:
        debug["error"] = str(exc)
        _log(f"ERROR: {exc}")
        return [_debug_text(agent_name, agent_slug, debug)]
    except NomadClientError as exc:
        debug["error"] = f"No se pudo conectar con Nomad Studio: {exc}. ¿Esta la app abierta y corriendo?"
        _log(f"ERROR: {exc}")
        return [_debug_text(agent_name, agent_slug, debug)]


nomad_studio_refine_image = mcp.tool(
    name="nomad_studio_refine_image",
    description=(
        "Edita/retoca 100% en local una imagen ya generada en esta conversacion con Nomad Studio "
        "(ComfyUI en tu propio PC). Usa esto cuando el usuario pida modificar una imagen que ya "
        "existe en el chat: cambiar la luz, quitar el fondo, restaurar, quitar una marca de agua "
        "o un objeto, retocar la piel, mejorar resolucion o cambiar el color — nunca para crear "
        "una imagen nueva desde cero (para eso usa nomad_studio_create_image)."
    ),
    structured_output=False,
    annotations=_WRITE_TOOL,
)(_nomad_studio_refine_image_impl)


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _debug_text(agent_name: str, agent_slug: str, debug: dict[str, Any]) -> TextContent:
    return TextContent(
        type="text",
        text=(
            f"AGENT: {agent_name}\nUSER: {agent_slug}\n\n"
            f"```json\n{json.dumps(debug, indent=2, ensure_ascii=False)}\n```"
        ),
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
