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
import sys
from typing import Any

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
from app.mcp import refine_actions
from app.mcp import session_state
from app.mcp.regions import MarkedRegion, annotate_data_url

mcp = FastMCP("nomad-studio")
_client = NomadClient()


@mcp.tool(
    name="nomad_studio_create_image",
    description=(
        "Genera una imagen 100% local con Nomad Studio (ComfyUI en tu propio PC, sin API "
        "keys ni cuenta). Usa esto cuando el usuario pida crear, generar o dibujar una imagen, "
        "ilustracion o foto. El prompt debe describirse en ingles cuando sea posible."
    ),
    # Sin structured_output=False, FastMCP genera un outputSchema a partir de la
    # anotacion de retorno y adjunta structuredContent (el base64 duplicado como
    # JSON); Claude Desktop entonces prioriza ese JSON y no renderiza el bloque
    # de imagen. La tool debe ser "unstructured" para que la imagen se muestre.
    structured_output=False,
)
async def nomad_studio_create_image(
    prompt: str,
    ctx: Context,
    aspect_ratio: str | None = None,
    speed: str | None = None,
    model: str | None = None,
    quantization: str | None = None,
    steps: int | None = None,
    width: int | None = None,
    height: int | None = None,
) -> list[TextContent | ImageContent]:
    """
    Args:
        prompt: Descripcion de la imagen a generar, en ingles preferiblemente.
        aspect_ratio: 'landscape' (apaisado/horizontal), 'portrait' (retrato/vertical)
            o 'square' (cuadrado). Si el usuario ya lo indico (aunque sea con otras palabras),
            traducelo a uno de esos tres valores. Si no lo indico, deja el campo vacio: se
            reutilizara su eleccion anterior de esta conversacion, o la tool te pedira que
            se lo preguntes en el chat antes de generar. Ignorado si se pasan 'width'/'height'
            explicitos.
        speed: 'fast' (superrapida), 'balanced' (rapida) o 'max' (normal/maxima calidad).
            Si el usuario ya lo indico, traducelo a uno de esos tres valores. Si no lo indico,
            deja el campo vacio: se reutilizara su eleccion anterior de esta conversacion, o
            la tool te pedira que se lo preguntes en el chat antes de generar.
        model: Nombre (o parte reconocible del nombre) del modelo/checkpoint a usar, tal y
            como lo tenga importado el usuario en Nomad Studio (ej. "Krea 2", "Ideogram 4",
            "Flux Klein"). Si el usuario no especifico ninguno y hay mas de un modelo
            disponible, deja el campo vacio: se reutilizara su eleccion anterior de esta
            conversacion, o la tool te pedira que preguntes al usuario en el chat, listando
            los modelos reales disponibles. Si solo hay un modelo importado, se usa sin preguntar.
        quantization: Id exacto de una cuantizacion concreta del modelo elegido (ej. "fp8",
            "int8", "bf16", "w4a8") — SOLO si el usuario pide explicitamente una cuantizacion
            concreta o pregunta que opciones hay. A diferencia de aspect_ratio/speed/model,
            esto NUNCA bloquea la generacion: si se deja vacio, se sigue eligiendo automaticamente
            segun 'speed' como hasta ahora. Cada modelo tiene sus propias opciones (no todas
            existen en todos los modelos) — si pides un id que no existe para el modelo elegido,
            la tool te devolvera la lista real de opciones de ese modelo con una explicacion de
            calidad/velocidad de cada una, sin generar nada, para que se lo reenvies al usuario.
        steps: Numero de pasos de sampler, SOLO si el usuario lo pide explicitamente (ej. "usa
            8 steps"). Si se deja vacio, se usa el valor por defecto del propio workflow/modelo
            (normal — la mayoria de usuarios nunca necesita tocar esto).
        width: Ancho exacto en pixeles — SOLO si el usuario pide una resolucion concreta (ej.
            "1024x768"), no una de las tres orientaciones estandar. Tiene que darse junto con
            'height' (los dos o ninguno) — si solo se da uno de los dos, se ignoran ambos y se
            usa 'aspect_ratio' en su lugar. Se redondea al multiplo de 64 mas cercano.
        height: Alto exacto en pixeles — ver 'width'.
    """
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
        }
    }

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
            missing.append("aspect_ratio — landscape (apaisado), portrait (vertical) o square (cuadrado)")
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
                        "pasando su eleccion en esos parametros."
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

        request_payload = {
            "import_id": import_id,
            "basicValues": {"positive": prompt, "width": width, "height": height},
            "advancedValues": advanced_values,
            "numImages": 1,
        }
        debug["request"] = request_payload
        _log(f"REQUEST: {json.dumps(request_payload, ensure_ascii=False)}")

        result = await _client.generate(
            import_id=import_id,
            basic_values={"positive": prompt, "width": width, "height": height},
            advanced_values=advanced_values,
            num_images=1,
        )
        debug["response"] = result
        _log(f"RESPONSE: {json.dumps(result, ensure_ascii=False)}")

        images = result.get("images") or []
        if not images:
            debug["error"] = "Nomad Studio no devolvio ninguna imagen."
            return [_debug_text(agent_name, agent_slug, debug)]

        filename = images[0].get("savedFilename") or images[0].get("filename")
        debug["filename"] = filename
        if not filename:
            debug["error"] = "No se pudo determinar el nombre de fichero de la imagen generada."
            return [_debug_text(agent_name, agent_slug, debug)]
        session_state.set_last_image(filename)

        output_dir = await _client.get_output_dir()
        thumb_bytes, thumb_mime = read_thumbnail(output_dir, agent_slug, filename, THUMBNAIL_WIDTH)
        thumb_b64 = base64.b64encode(thumb_bytes).decode("ascii")
        debug["thumbnail_bytes"] = len(thumb_bytes)
        debug["thumbnail_mime"] = thumb_mime
        debug["thumbnail_source"] = "local_disk"
        public_url = _client.image_url(filename, viewer_id=agent_slug)
        debug["image_url_with_cookie_bypass"] = public_url
        _log(f"THUMBNAIL (disco local): {len(thumb_bytes)} bytes, url={public_url}")

        quant_note = ""
        if quant_options:
            how_chosen = "pedida explicitamente" if quantization else f"auto, segun speed='{speed}'"
            quant_note = (
                f"\nCuantizacion usada: {chosen_id or 'por defecto del workflow'} ({how_chosen})."
                f"\nOtras opciones disponibles en este modelo:\n{describe_quantization_options(quant_options)}\n"
            )

        return [
            ImageContent(type="image", data=thumb_b64, mimeType=thumb_mime),
            TextContent(
                type="text",
                text=(
                    f"Generado con Nomad Studio — modelo: {record.get('name', 'desconocido')}, "
                    f"cuantizacion: {chosen_id or 'por defecto del workflow'} "
                    f"(velocidad pedida: {speed}).\n"
                    f"Enlace directo a la imagen (sin login, no requiere sesion): {public_url}\n"
                    f"Si tienes un navegador o visor integrado en este entorno, abrelo ahi para "
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

    lines = ["Modelos disponibles en Nomad Studio:\n"]
    for imp in imports:
        name = str(imp.get("name", "") or imp.get("id", ""))
        try:
            record = await _client.get_import(str(imp.get("id", "")))
        except NomadClientError:
            record = {}
        quant_block = (record.get("analysis") or {}).get("quantization")
        options = (quant_block or {}).get("options") or []
        lines.append(f"## {name}")
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


_OUTPAINT_POSITIONS = {
    "center", "top", "bottom", "left", "right",
    "top-left", "top-right", "bottom-left", "bottom-right",
}


async def _nomad_studio_refine_image_impl(
    action: str,
    ctx: Context,
    filename: str | None = None,
    instruction: str | None = None,
    position: str | None = None,
    scale: int | None = None,
    expand_percent: int | None = None,
    regions: list[MarkedRegion] | None = None,
) -> list[TextContent | ImageContent]:
    """
    Args:
        action: Que tipo de retoque aplicar — el id exacto de un flow de Refine de Nomad
            Studio (ej. "refine.pf_relight", "refine.remove_bg_simple", "refine.outpaint").
            Si no sabes que ids hay disponibles para esta conversacion, llama primero a
            nomad_studio_list_refine_actions: devuelve la lista completa con una descripcion
            de cada uno, agrupada por categoria. Si pasas un id invalido, esta misma tool
            devuelve esa lista igualmente en el mensaje de error.
        filename: Nombre del fichero de la imagen a editar, tal y como aparecio en una
            respuesta anterior de esta conversacion (nomad_studio_create_image o esta misma
            tool). Si el usuario se refiere a "la imagen"/"esta foto" sin mas, deja el campo
            vacio: se usara automaticamente la ultima imagen generada en esta conversacion.
        instruction: Detalle adicional en ingles sobre COMO aplicar la accion (ej. para
            'relight': "backlit rim light"; para 'remove_object': el objeto a quitar, ej.
            "the red car"). Si el usuario no da detalle, deja el campo vacio: se usara un
            valor por defecto razonable para esa accion.
        position: SOLO para action='outpaint'. Donde queda la imagen ORIGINAL dentro del
            lienzo nuevo, mas grande — uno de: center, top, bottom, left, right, top-left,
            top-right, bottom-left, bottom-right. Traduce la frase del usuario: "bajala un
            poco"/"muevela abajo" -> "bottom" (el hueco nuevo se rellena arriba); "muevela a
            la izquierda" -> "left" (el hueco nuevo se rellena a la derecha); etc. Si no lo
            menciona, deja vacio (default "center", expande por todos los lados por igual).
        scale: SOLO para action='outpaint'. 10-100, que porcentaje del lienzo nuevo ocupa la
            imagen original (100 = a tamano completo, sin encoger). Si el usuario pide
            "reducela"/"hazla mas pequena" antes de expandir el lienzo, baja este valor (ej.
            70-80) para dejar mas borde alrededor a rellenar. Si no lo menciona, deja vacio
            (default 100).
        expand_percent: SOLO para action='outpaint'. Cuanto crece el lienzo respecto al
            tamano original de la imagen, en porcentaje (ej. 40 = el lienzo nuevo es un 40%
            mas grande). Si el usuario pide una extension grande, sube este valor; si no dice
            nada, deja vacio (default 40).
        regions: SOLO para las acciones marcadas [NEEDS 'regions'] en
            nomad_studio_list_refine_actions (Local Edit, Text Editor...): esas acciones editan
            zonas concretas que se marcan sobre la imagen con un contorno de color, y son
            obligatorias. Una entrada por zona, en porcentaje del lienzo: left/top/right/bottom
            de 0 a 100 (ej. la mitad superior entera = left 0, top 0, right 100, bottom 50), y
            un color distinto por zona (red, green, blue, yellow, purple, orange). La
            'instruction' tiene que nombrar cada zona por su color, en ingles: "Replace the text
            inside the red rectangle with \"SALE\"", "Remove the object in the blue circle".
            Si no sabes donde esta algo en la imagen, preguntaselo al usuario antes de llamar.
    """
    agent_name = "unknown"
    agent_slug = "unknown"
    debug: dict[str, Any] = {
        "input": {
            "action": action,
            "filename": filename,
            "instruction": instruction,
            "position": position,
            "scale": scale,
            "expand_percent": expand_percent,
            "regions": [r.model_dump() for r in regions] if regions else None,
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

        advanced_values: dict[str, Any] = dict(refine_action.extra_advanced_values)
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

            source_path = f"{output_dir}/{agent_slug}/{resolved_filename}"
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
                    f"Refinado con Nomad Studio — accion: {action} ({refine_action.flow_id}).\n"
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
