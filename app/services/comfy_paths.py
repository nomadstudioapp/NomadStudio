"""Model file names in a workflow, with the path separator of the ComfyUI
that runs it.

ComfyUI lists models in subfolders with its own system's separator
("krea2\\file.safetensors" on Windows, "krea2/file.safetensors" on Linux and
macOS) and rejects any other spelling ("Value not in list"). The workflows in
the packages were made on Windows, so on a Linux ComfyUI every engine with
its model in a subfolder failed (found on Ubuntu with Krea 2 Turbo). Every
place that queues a prompt passes the graph through for_comfy() first.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from app.services.http_client import http_json

_MODEL_EXTENSIONS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".sft", ".onnx")
_CACHE_SECONDS = 300
_cache: dict[str, tuple[float, bool]] = {}
_lock = threading.Lock()


def comfy_is_windows(comfy_url: str) -> bool | None:
    """Whether that ComfyUI runs on Windows (its /system_stats "os"), or None
    when it does not say. Cached a few minutes per address."""
    base = str(comfy_url or "").rstrip("/")
    now = time.monotonic()
    with _lock:
        hit = _cache.get(base)
        if hit and now - hit[0] < _CACHE_SECONDS:
            return hit[1]
    try:
        system = str((http_json(f"{base}/system_stats", timeout=5).get("system") or {}).get("os", "")).lower()
    except Exception:  # noqa: BLE001 — not reachable now: leave the graph as it is
        return None
    if not system:
        return None
    windows = system in ("nt", "windows", "win32")
    with _lock:
        _cache[base] = (now, windows)
    return windows


def for_comfy(prompt: Any, comfy_url: str) -> Any:
    """*prompt* (an API-format graph) with the separators of its model file
    names turned into the ones that ComfyUI uses. Changed in place and
    returned; anything that is not a graph is returned untouched."""
    if not isinstance(prompt, dict):
        return prompt
    windows = comfy_is_windows(comfy_url)
    if windows is None:
        return prompt
    wrong, right = ("/", "\\") if windows else ("\\", "/")
    for node in prompt.values():
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict):
            continue
        for key, value in inputs.items():
            if isinstance(value, str) and wrong in value and value.lower().endswith(_MODEL_EXTENSIONS):
                inputs[key] = value.replace(wrong, right)
    return prompt
