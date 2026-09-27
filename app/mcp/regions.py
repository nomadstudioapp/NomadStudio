"""Marcas de color para los flows de Refine con paso region_annotate.

En la app, Local Edit y Text Editor piden marcar zonas sobre la imagen
(flow-step-region-annotate.js) y lo que se manda al grafo es la imagen con
esas marcas pintadas encima: el prompt las nombra por color ("replace the
text inside the red rectangle"). Por MCP no hay lienzo, asi que el agente
describe cada zona en porcentajes del lienzo y aqui se pinta igual que la
app: mismos colores, contorno sin relleno, trazo equivalente a 14 px sobre
una imagen de 1536 px.
"""

from __future__ import annotations

import base64
import io
from typing import Literal

from pydantic import BaseModel, Field

# Mismos colores que COLORS en flow-step-region-annotate.js.
REGION_COLORS = {
    "red": (0xEF, 0x44, 0x44),
    "green": (0x22, 0xC5, 0x5E),
    "blue": (0x3B, 0x82, 0xF6),
    "yellow": (0xEA, 0xB3, 0x08),
    "purple": (0xA8, 0x55, 0xF7),
    "orange": (0xF9, 0x73, 0x16),
}
_APP_STROKE = 14      # DEFAULT_WIDTH en la app…
_APP_CANVAS = 1536    # …sobre un lienzo de como mucho MAX_DIM px


class MarkedRegion(BaseModel):
    """Una zona marcada sobre la imagen, en porcentaje del lienzo (0 = borde
    izquierdo/superior, 100 = borde derecho/inferior)."""

    color: Literal["red", "green", "blue", "yellow", "purple", "orange"] = Field(
        "red", description="Color de la marca; la instruction la nombra asi ('the red rectangle').")
    left: float = Field(..., ge=0, le=100, description="Borde izquierdo de la zona, % del ancho.")
    top: float = Field(..., ge=0, le=100, description="Borde superior de la zona, % del alto.")
    right: float = Field(..., ge=0, le=100, description="Borde derecho de la zona, % del ancho.")
    bottom: float = Field(..., ge=0, le=100, description="Borde inferior de la zona, % del alto.")


def annotate_data_url(data_url: str, regions: list[MarkedRegion], shape: str) -> str:
    """La imagen (data URL) con cada zona pintada como contorno de su color —
    rectangulo o elipse segun el flow — devuelta como data URL PNG."""
    from PIL import Image, ImageDraw

    header, b64 = data_url.split(",", 1)
    with Image.open(io.BytesIO(base64.b64decode(b64))) as src:
        im = src.convert("RGB")
    w, h = im.size
    stroke = max(2, round(_APP_STROKE * max(w, h) / _APP_CANVAS))
    draw = ImageDraw.Draw(im)
    for r in regions:
        x0, x1 = sorted((r.left * w / 100, r.right * w / 100))
        y0, y1 = sorted((r.top * h / 100, r.bottom * h / 100))
        box = [round(x0), round(y0), round(x1), round(y1)]
        color = REGION_COLORS[r.color]
        if shape == "rect":
            draw.rectangle(box, outline=color, width=stroke)
        else:
            draw.ellipse(box, outline=color, width=stroke)
    out = io.BytesIO()
    im.save(out, "PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")
