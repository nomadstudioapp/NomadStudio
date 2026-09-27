"""Midjourney-style parameters at the end of a prompt (NomadStudio#27).

    a weathered shop sign that says OPEN SOURCE --ar 16:9 --no people, text --seed 1234

parse() splits the prompt into the text to draw and the settings asked for
with ``--``. Only what Nomad Studio can honour is returned as a setting;
Midjourney-only knobs (--stylize, --chaos, --weird…) are listed in
``ignored`` so the caller can say they don't apply, and anything unknown or
with an unusable value lands in ``invalid`` — nothing is silently guessed.

The same parser serves the MCP (app/mcp/server.py) and Create's generation
endpoints, so a prompt means the same thing wherever it is typed.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# " --name" starts a parameter: a space (or the start) before it, a letter
# after, so "well--known" or an em dash in the prompt are left alone.
_PARAM_START = re.compile(r"(?:^|\s)--(?=[A-Za-z])")

_ALIASES = {
    "ar": "ar", "aspect": "ar",
    "no": "no",
    "seed": "seed", "sameseed": "seed",
    "v": "model", "version": "model", "model": "model", "engine": "model", "m": "model",
    "niji": "niji",
    "q": "speed", "quality": "speed", "speed": "speed",
    "draft": "draft", "fast": "draft", "turbo": "draft",
    "steps": "steps",
    "quant": "quantization", "quantization": "quantization",
    "r": "repeat", "repeat": "repeat",
}
# Midjourney parameters with no Nomad Studio equivalent (yet).
_MIDJOURNEY_ONLY = {
    "s", "stylize", "c", "chaos", "w", "weird", "style", "tile", "iw", "stop", "p", "personalize",
    "sref", "sw", "sv", "cref", "cw", "oref", "ow", "exp", "raw", "hd", "uplight", "upbeta", "video",
    "relax", "public", "stealth",
}
SPEEDS = ("fast", "balanced", "max")
_SPEED_WORDS = {"fast": "fast", "draft": "fast", "low": "fast", "balanced": "balanced", "normal": "balanced",
                "medium": "balanced", "max": "max", "high": "max", "best": "max"}
MAX_REPEAT = 4


@dataclass
class PromptParams:
    prompt: str                                  # the prompt without its parameters
    aspect: tuple[int, int] | None = None        # (width ratio, height ratio), e.g. (16, 9)
    no: str | None = None                        # things to keep out: added to the negative
    seed: int | None = None
    model: str | None = None                     # engine name to look up among the installed ones
    speed: str | None = None                     # fast | balanced | max
    quantization: str | None = None              # int8, fp8, bf16…
    steps: int | None = None
    repeat: int | None = None                    # how many images
    ignored: list[str] = field(default_factory=list)            # Midjourney-only, no equivalent
    invalid: dict[str, str] = field(default_factory=dict)       # name → why it wasn't used

    @property
    def found(self) -> bool:
        return any(v is not None for v in (self.aspect, self.no, self.seed, self.model, self.speed,
                                           self.quantization, self.steps, self.repeat)) \
            or bool(self.ignored or self.invalid)

    def as_dict(self) -> dict:
        out = {k: v for k, v in {
            "aspect": f"{self.aspect[0]}:{self.aspect[1]}" if self.aspect else None,
            "no": self.no, "seed": self.seed, "model": self.model, "speed": self.speed,
            "quantization": self.quantization, "steps": self.steps, "repeat": self.repeat,
        }.items() if v is not None}
        if self.ignored:
            out["ignored"] = list(self.ignored)
        if self.invalid:
            out["invalid"] = dict(self.invalid)
        return out


def _int(value: str, low: int, high: int) -> int | None:
    try:
        n = int(float(value.strip().replace(",", "")))
    except ValueError:
        return None
    return n if low <= n <= high else None


def _aspect(value: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[:x×/]\s*(\d+(?:\.\d+)?)\s*", value)
    if not m:
        return None
    w, h = float(m.group(1)), float(m.group(2))
    if w <= 0 or h <= 0 or not (1 / 4 <= w / h <= 4):
        return None
    # Keep what was typed ("16:9", "2.39:1" → 239:100) as whole numbers.
    scale = 1
    while (w * scale) % 1 or (h * scale) % 1:
        scale *= 10
    wi, hi = int(w * scale), int(h * scale)
    g = math.gcd(wi, hi)
    return wi // g, hi // g


def _speed(value: str) -> str | None:
    v = value.strip().lower()
    if v in _SPEED_WORDS:
        return _SPEED_WORDS[v]
    try:  # Midjourney's --q .25/.5/1/2/4
        q = float(v)
    except ValueError:
        return None
    return "fast" if q < 1 else "balanced" if q < 2 else "max"


def parse(text: str) -> PromptParams:
    text = text or ""
    first = _PARAM_START.search(text)
    if not first:
        return PromptParams(prompt=text.strip())
    result = PromptParams(prompt=text[:first.start()].strip())
    chunks = _PARAM_START.split(text[first.start():])
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        name, _, value = chunk.partition(" ")
        raw_name = name.lower()
        value = value.strip()
        key = _ALIASES.get(raw_name)
        if key is None:
            if raw_name in _MIDJOURNEY_ONLY:
                result.ignored.append(raw_name)
            else:
                result.invalid[raw_name] = "unknown parameter"
            continue
        if key == "ar":
            aspect = _aspect(value)
            if aspect:
                result.aspect = aspect
            else:
                result.invalid[raw_name] = f"'{value}' is not a ratio like 16:9 (between 1:4 and 4:1)"
        elif key == "no":
            parts = [p.strip() for p in value.split(",") if p.strip()]
            if parts:
                result.no = ", ".join(([result.no] if result.no else []) + parts)
            else:
                result.invalid[raw_name] = "nothing after --no"
        elif key == "seed":
            seed = _int(value, 0, 2**53)
            if seed is None:
                result.invalid[raw_name] = f"'{value}' is not a whole number"
            else:
                result.seed = seed
        elif key == "model":
            if value:
                result.model = value
            else:
                result.invalid[raw_name] = "no engine name after it"
        elif key == "niji":
            result.model = "anime"
        elif key == "speed":
            speed = _speed(value)
            if speed:
                result.speed = speed
            else:
                result.invalid[raw_name] = f"'{value}' — use fast, balanced or max"
        elif key == "draft":
            result.speed = "fast"
        elif key == "steps":
            steps = _int(value, 1, 150)
            if steps is None:
                result.invalid[raw_name] = f"'{value}' — a number from 1 to 150"
            else:
                result.steps = steps
        elif key == "quantization":
            if re.fullmatch(r"[a-z0-9_]+", value.lower()):
                result.quantization = value.lower()
            else:
                result.invalid[raw_name] = f"'{value}' — e.g. int8, fp8, bf16"
        elif key == "repeat":
            repeat = _int(value, 1, MAX_REPEAT)
            if repeat is None:
                result.invalid[raw_name] = f"'{value}' — a number from 1 to {MAX_REPEAT}"
            else:
                result.repeat = repeat
    return result


def size_for_aspect(aspect: tuple[int, int], area: int = 1024 * 1024, multiple: int = 64) -> tuple[int, int]:
    """Width and height for this ratio with about ``area`` pixels (the
    megapixels of the size it replaces), both multiples of ``multiple``."""
    rw, rh = aspect
    width = math.sqrt(area * rw / rh)
    height = width * rh / rw
    return (max(multiple, round(width / multiple) * multiple),
            max(multiple, round(height / multiple) * multiple))
