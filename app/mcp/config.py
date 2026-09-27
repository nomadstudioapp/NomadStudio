"""Configuracion del servidor MCP de Nomad Studio."""

from __future__ import annotations

import os

NOMAD_BASE_URL = os.environ.get("NOMAD_STUDIO_BASE_URL", "http://127.0.0.1:5123").rstrip("/")

REQUEST_TIMEOUT_SECONDS = 300.0

# Cuantizaciones en orden de preferencia dentro de cada preset de velocidad.
# Se casan contra los ids del bloque `quantization` de la metadata del
# workflow activo (nodo config: w4a8/int4/int8/fp8/bf16...); ver
# app.mcp.quantization.pick_quantization.
SPEED_TO_QUANTIZATIONS: dict[str, list[str]] = {
    "fast": ["w4a8", "int4", "int8"],
    "balanced": ["int8", "w4a8", "fp8", "bf16"],
    "max": ["bf16", "fp8", "int8"],
}

# Dimensiones por defecto (multiplos de 64, buckets habituales SDXL/Flux).
ASPECT_RATIO_DIMENSIONS: dict[str, tuple[int, int]] = {
    "square": (1024, 1024),
    "landscape": (1216, 832),
    "portrait": (832, 1216),
    # 16:9 / 9:16 (~1 MP, the size these engines are trained around).
    "wide": (1344, 768),
    "tall": (768, 1344),
}

# What people actually type for the two 16:9 formats.
ASPECT_RATIO_ALIASES: dict[str, str] = {"16:9": "wide", "widescreen": "wide", "9:16": "tall", "vertical": "tall"}

DEFAULT_ASPECT_RATIO = "square"
DEFAULT_SPEED = "fast"

# 1024px: Claude Desktop acepta hasta 2000px (multiples imagenes) / 8000px
# (una sola); su guia recomienda >=1000px para buena calidad visual.
THUMBNAIL_WIDTH = 1024
