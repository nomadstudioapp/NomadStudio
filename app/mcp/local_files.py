"""Lectura directa de disco para las imagenes generadas.

El MCP server corre en la misma maquina que Nomad Studio/ComfyUI, asi que
lee el fichero ya guardado en el Album directamente con Python en vez de
hacer una llamada HTTP a Flask (que requeriria cookie/sesion de viewer en
el camino critico de "generar y mostrar la imagen"). El sistema de viewers
sigue existiendo para el Album normal de la app; el MCP simplemente no
depende de el para esto.
"""

from __future__ import annotations

import io
from pathlib import Path


class LocalImageNotFoundError(RuntimeError):
    """La imagen no se encontro en disco en la ruta esperada."""


def read_thumbnail(output_dir: str, viewer_slug: str, filename: str, max_size: int) -> tuple[bytes, str]:
    """Devuelve (bytes, "image/jpeg"). A diferencia de
    image_service.serve_image_thumb() (que devuelve el PNG original intacto
    si ya cabe en max_size — 716KB para un PNG de 1024px), aqui SIEMPRE se
    re-encodea a JPEG: el resultado viaja en base64 dentro de la respuesta
    MCP y cuenta como tokens de vision, asi que el tamano importa."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise LocalImageNotFoundError(f"Nombre de fichero invalido: '{filename}'")
    path = Path(output_dir) / viewer_slug / filename
    if not path.is_file():
        raise LocalImageNotFoundError(f"No se encontro '{filename}' en '{path.parent}'.")
    try:
        from PIL import Image

        with Image.open(path) as im:
            im.thumbnail((max_size, max_size), Image.LANCZOS)
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG", quality=85, optimize=True)
            return buf.getvalue(), "image/jpeg"
    except LocalImageNotFoundError:
        raise
    except Exception as exc:
        raise LocalImageNotFoundError(f"Pillow fallo al procesar '{filename}': {exc}") from exc


_EXT_TO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def read_full_image_as_data_url(output_dir: str, viewer_slug: str, filename: str) -> str:
    """Devuelve la imagen a resolucion completa (sin redimensionar, a
    diferencia de read_thumbnail) como "data:image/<mime>;base64,...", listo
    para el parametro imageDataUrl que espera POST /api/models/refine/generate.
    Necesario para editar (relight, remove background...) sin perder detalle
    respecto a la miniatura pensada solo para mostrarse en el chat."""
    import base64

    if "/" in filename or "\\" in filename or ".." in filename:
        raise LocalImageNotFoundError(f"Nombre de fichero invalido: '{filename}'")
    path = Path(output_dir) / viewer_slug / filename
    if not path.is_file():
        raise LocalImageNotFoundError(f"No se encontro '{filename}' en '{path.parent}'.")
    mime = _EXT_TO_MIME.get(path.suffix.lower(), "image/png")
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"
