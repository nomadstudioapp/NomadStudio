"""Pixel Matcher — imported colour palettes.

Parses the palette files pixel artists actually trade (Lospec, Aseprite,
GIMP, Paint Shop Pro, Photoshop, Paint.NET) into a plain list of "#rrggbb"
strings, and keeps the user's imported palettes in DATA_DIR/palettes.json.

Supported formats:
- .pal  JASC-PAL (text, Paint Shop Pro / Aseprite / Lospec) and RIFF PAL
        (binary, Microsoft) — both use the same extension.
- .gpl  GIMP palette.
- .hex  one "rrggbb" per line (Lospec).
- .txt  Paint.NET ("aarrggbb" per line, ";" comments).
- .act  Adobe Color Table (768 bytes, optional 4-byte count trailer).
"""

from __future__ import annotations

import json
import os
import re
import struct
import threading
import time
import uuid
from pathlib import Path

MAX_COLORS = 256
MAX_FILE_BYTES = 256 * 1024
SUPPORTED_EXTENSIONS = (".pal", ".gpl", ".hex", ".txt", ".act")

_HEX6 = re.compile(r"^#?([0-9a-fA-F]{6})$")
_HEX8 = re.compile(r"^#?([0-9a-fA-F]{8})$")
_lock = threading.Lock()


class PaletteError(ValueError):
    """The file is not a palette we can read."""


def _hex(r: int, g: int, b: int) -> str:
    return "#{:02x}{:02x}{:02x}".format(r & 255, g & 255, b & 255)


def _dedupe(colors: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for c in colors:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _rgb_triplets(lines: list[str]) -> list[str]:
    colors = []
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            r, g, b = (int(p) for p in parts[:3])
        except ValueError:
            continue
        if all(0 <= v <= 255 for v in (r, g, b)):
            colors.append(_hex(r, g, b))
    return colors


def _parse_riff(data: bytes) -> list[str]:
    # RIFF <size> PAL  data <size> <version:u16> <count:u16> {r g b flags}*
    idx = data.find(b"data", 12)
    if idx < 0 or len(data) < idx + 12:
        raise PaletteError("RIFF palette without a data chunk")
    count = struct.unpack_from("<H", data, idx + 10)[0]
    start = idx + 12
    colors = []
    for i in range(count):
        off = start + i * 4
        if off + 3 > len(data):
            break
        colors.append(_hex(data[off], data[off + 1], data[off + 2]))
    return colors


def _parse_act(data: bytes) -> list[str]:
    count = 256
    if len(data) >= 772:
        count = struct.unpack_from(">H", data, 768)[0] or 256
    count = min(count, 256)
    return [_hex(data[i * 3], data[i * 3 + 1], data[i * 3 + 2]) for i in range(count)]


def parse_palette(filename: str, data: bytes) -> list[str]:
    """Colours in file order, deduplicated, as "#rrggbb"."""
    if len(data) > MAX_FILE_BYTES:
        raise PaletteError("file too large for a palette")
    ext = Path(filename).suffix.lower()

    if data[:4] == b"RIFF" and data[8:12] == b"PAL ":
        colors = _parse_riff(data)
    elif ext == ".act":
        if len(data) < 768:
            raise PaletteError("ACT palette shorter than 768 bytes")
        colors = _parse_act(data)
    else:
        text = data.decode("utf-8-sig", errors="replace")
        lines = [ln.strip() for ln in text.splitlines()]
        head = lines[0].upper() if lines else ""
        if head.startswith("JASC-PAL"):
            colors = _rgb_triplets(lines[3:])
        elif head.startswith("GIMP PALETTE"):
            body = [ln for ln in lines[1:]
                    if ln and not ln.startswith("#") and ":" not in ln.split()[0]]
            colors = _rgb_triplets(body)
        else:
            # .hex / Paint.NET .txt / anything that is just hex codes.
            colors = []
            for ln in lines:
                if not ln or ln.startswith(";") or ln.startswith("//"):
                    continue
                token = ln.split()[0]
                m6 = _HEX6.match(token)
                m8 = _HEX8.match(token)
                if m6:
                    colors.append("#" + m6.group(1).lower())
                elif m8:  # Paint.NET: AARRGGBB
                    colors.append("#" + m8.group(1)[2:].lower())

    colors = _dedupe(colors)
    if len(colors) < 2:
        raise PaletteError("no colours found (need at least 2)")
    return colors[:MAX_COLORS]


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


# ── Storage ──────────────────────────────────────────────────────────────────

def _store_path() -> Path:
    from app.paths import DATA_DIR
    return DATA_DIR / "palettes.json"


def _read() -> list[dict]:
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("palettes") if isinstance(data, dict) else None
    return [p for p in items or [] if isinstance(p, dict) and p.get("id")]


def _write(items: list[dict]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"palettes": items}, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


_BUILTIN_PATH = Path(__file__).with_name("default_palettes.json")
_builtin_cache: list[dict] | None = None


def builtin_palettes() -> list[dict]:
    """Palettes shipped with the addon (default_palettes.json, taken from
    Lospec with their authors) — read-only, listed before the user's own."""
    global _builtin_cache
    if _builtin_cache is None:
        try:
            items = json.loads(_BUILTIN_PATH.read_text(encoding="utf-8")).get("palettes") or []
        except (OSError, ValueError):
            items = []
        _builtin_cache = [{**p, "builtin": True} for p in items if isinstance(p, dict) and p.get("id")]
    return _builtin_cache


def list_palettes() -> list[dict]:
    with _lock:
        return builtin_palettes() + _read()


def get_palette(palette_id: str) -> dict | None:
    with _lock:
        return next((p for p in builtin_palettes() + _read() if p["id"] == palette_id), None)


def add_palette(filename: str, data: bytes) -> dict:
    colors = parse_palette(filename, data)
    name = Path(filename).stem.replace("_", " ").replace("-", " ").strip() or "Palette"
    palette = {
        "id": uuid.uuid4().hex[:12],
        "name": name[:80],
        "colors": colors,
        "format": Path(filename).suffix.lower().lstrip("."),
        "created": int(time.time()),
    }
    with _lock:
        items = _read()
        items.append(palette)
        _write(items)
    return palette


def rename_palette(palette_id: str, name: str) -> dict | None:
    name = str(name or "").strip()[:80]
    if not name:
        return None
    with _lock:
        items = _read()
        target = next((p for p in items if p["id"] == palette_id), None)
        if target is None:
            return None
        target["name"] = name
        _write(items)
        return target


def delete_palette(palette_id: str) -> bool:
    with _lock:
        items = _read()
        kept = [p for p in items if p["id"] != palette_id]
        if len(kept) == len(items):
            return False
        _write(kept)
        return True
