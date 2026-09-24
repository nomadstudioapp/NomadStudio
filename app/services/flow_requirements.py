"""What a flow's ComfyUI graphs need that ComfyUI does not have yet.

A flow installed from a package ships its graphs, not the model files or the
custom nodes they use. Before this, a missing file only surfaced as ComfyUI
rejecting the job ("Queue rejected"). This compares each graph against
ComfyUI's own ``/object_info``:

* a node class ComfyUI does not know → a custom-node pack to install, named
  from app/static/data/custom_node_packs.json (tools/packages/gen_node_packs.py);
* a model file that is not among the choices ComfyUI offers for that loader
  input → a file to download, with the address from the graph's ``downloads``
  list when it has one (the same list the Setup wizard installs engines from).

Files that are one of the graph's quantization variants (``config`` node) are
reported per variant: the flow runs as long as ONE variant is complete.

Nothing here writes anything; downloads go through the existing
/api/models/imports/download-file.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .http_client import http_json

MODEL_EXTENSIONS = (".safetensors", ".gguf", ".pth", ".pt", ".bin", ".ckpt", ".sft", ".onnx")

# Loader class → ComfyUI models folder a missing file is downloaded into.
_CLASS_FOLDERS = {
    "UNETLoader": "diffusion_models",
    "UnetLoaderGGUF": "diffusion_models",
    "CLIPLoader": "text_encoders",
    "DualCLIPLoader": "text_encoders",
    "TripleCLIPLoader": "text_encoders",
    "CLIPLoaderGGUF": "text_encoders",
    "VAELoader": "vae",
    "LoraLoader": "loras",
    "LoraLoaderModelOnly": "loras",
    "CheckpointLoaderSimple": "checkpoints",
    "ImageOnlyCheckpointLoader": "checkpoints",
    "CLIPVisionLoader": "clip_vision",
    "UpscaleModelLoader": "upscale_models",
    "ModelPatchLoader": "model_patches",
    "StyleModelLoader": "style_models",
    "ControlNetLoader": "controlnet",
}
# Fallback by input name, for loaders not listed above.
_INPUT_FOLDERS = {
    "unet_name": "diffusion_models",
    "unet_unconditional_name": "diffusion_models",
    "clip_name": "text_encoders",
    "clip_name1": "text_encoders",
    "clip_name2": "text_encoders",
    "vae_name": "vae",
    "lora_name": "loras",
    "ckpt_name": "checkpoints",
    "model_name": "upscale_models",
}

_NODE_PACKS_FILE = Path(__file__).resolve().parents[1] / "static" / "data" / "custom_node_packs.json"

_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}
_OBJECT_INFO_TTL = 15.0


def _norm(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _basename(value: str) -> str:
    return re.split(r"[\\/]", str(value or "").strip())[-1]


def _dirname(value: str) -> str:
    parts = [p for p in re.split(r"[\\/]", str(value or "").strip()) if p]
    return "/".join(parts[:-1])


def object_info(comfy_url: str, force: bool = False) -> dict[str, Any]:
    """ComfyUI's /object_info, cached briefly: every flow opened asks for it,
    and a "Check again" after a download must see the new file (force)."""
    key = comfy_url.rstrip("/")
    with _cache_lock:
        hit = _cache.get(key)
        if hit and not force and time.monotonic() - hit[0] < _OBJECT_INFO_TTL:
            return hit[1]
    data = http_json(f"{key}/object_info", timeout=30)
    if not isinstance(data, dict):
        raise ValueError("ComfyUI returned no node list")
    with _cache_lock:
        _cache[key] = (time.monotonic(), data)
    return data


def node_packs() -> dict[str, Any]:
    try:
        return json.loads(_NODE_PACKS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"packs": {}, "classes": {}}


def _choices(info: dict[str, Any], class_type: str, input_name: str) -> set[str] | None:
    """The file names ComfyUI accepts for this loader input, or None when the
    input is not a list of files (then presence cannot be judged)."""
    node = info.get(class_type)
    if not isinstance(node, dict):
        return None
    inputs = node.get("input") or {}
    for group in ("required", "optional"):
        spec = (inputs.get(group) or {}).get(input_name)
        if not isinstance(spec, list) or not spec:
            continue
        options = spec[0]
        # Newer ComfyUI: ["COMBO", {"options": [...]}]
        if options == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
            options = spec[1].get("options")
        if isinstance(options, list):
            return {_norm(o) for o in options if isinstance(o, str)}
    return None


def _quant_files(config: dict[str, Any]) -> list[dict[str, Any]]:
    quant = config.get("quantization") if isinstance(config, dict) else None
    if not isinstance(quant, dict):
        return []
    options = []
    for key, raw in quant.items():
        values: list[tuple[str, str]] = []  # (input name, file)
        label = str(key).upper()
        if isinstance(raw, str):
            values.append(("unet_name", raw))
        elif isinstance(raw, dict):
            label = str(raw.get("label") or label)
            for field in ("unet_name", "unet_unconditional_name", "clip_name"):
                if isinstance(raw.get(field), str) and raw[field].strip():
                    values.append((field, raw[field]))
        if values:
            options.append({"key": str(key), "label": label, "values": values})
    return options


def check(
    workflows: list[dict[str, Any]],
    info: dict[str, Any],
    parse_config: Callable[[dict], dict | None],
    extract_downloads: Callable[[dict], list[dict[str, str]]],
    available_folders: list[str] | None = None,
    declared: dict[str, dict[str, Any]] | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``declared``: the packages' requires.models by file name (lower) — the
    file's identity (folder, size, sha256, fallback url). ``catalog``: the
    models catalog (models_catalog.load()) — where files are downloaded.
    Address order (PACKAGE_FORMAT.md §8.2.3): catalog by sha256 → catalog by
    name → the package's url → the graph's own downloads list."""
    from . import models_catalog

    available = set(available_folders or [])
    declared = declared or {}
    catalog = catalog or {"models": []}
    packs = node_packs()
    models: dict[str, dict[str, Any]] = {}      # basename (lower) → entry
    quant_groups: list[dict[str, Any]] = []
    missing_classes: set[str] = set()

    for workflow in workflows:
        downloads: dict[str, dict[str, str]] = {}
        for d in extract_downloads(workflow) or []:
            fname = _basename(d.get("filename", ""))
            if fname and d.get("url"):
                downloads.setdefault(fname.lower(), {"subfolder": str(d.get("subfolder", "")), "url": d["url"]})

        # Which loader (class, input) each file sits on — the quantization
        # variants name files only, their loader is the one holding the
        # graph's default for that input.
        loader_for_input: dict[str, str] = {}
        refs: list[tuple[str, str, str]] = []   # (class, input, value)
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type") or "")
            if not class_type:
                continue
            if class_type not in info:
                missing_classes.add(class_type)
                continue
            for input_name, value in (node.get("inputs") or {}).items():
                # Only a loader's file dropdown counts — a text node that
                # happens to end in ".safetensors" (the graph's own
                # "Downloads" list) is not a file the graph loads.
                if (isinstance(value, str) and value.lower().endswith(MODEL_EXTENSIONS)
                        and _choices(info, class_type, input_name) is not None):
                    refs.append((class_type, input_name, value))
                    loader_for_input.setdefault(input_name, class_type)

        def describe(class_type: str, input_name: str, value: str) -> dict[str, Any]:
            choices = _choices(info, class_type, input_name)
            fname = _basename(value)
            folder = _CLASS_FOLDERS.get(class_type) or _INPUT_FOLDERS.get(input_name, "")
            dl = downloads.get(fname.lower())
            if dl:
                sub = dl["subfolder"].replace("\\", "/").strip("/")
                first = sub.split("/")[0] if sub else ""
                # A declared subfolder that is not itself a models folder
                # (e.g. "flux2_klein") is relative to the loader's folder.
                subfolder = sub if (first in available or first == folder) else "/".join(p for p in (folder, sub) if p)
            else:
                subfolder = "/".join(p for p in (folder, _dirname(value)) if p)

            decl = declared.get(fname.lower()) or {}
            sha = decl.get("sha256") or None
            size = decl.get("size") if isinstance(decl.get("size"), int) else None
            entry = models_catalog.lookup(catalog, fname, sha, size)
            sources: list[dict[str, Any]] = []
            for src in (entry or {}).get("sources") or []:
                sources.append({k: src.get(k) for k in ("url", "host", "gated", "license_url") if src.get(k) is not None})
            for url in (decl.get("url"), dl["url"] if dl else None):
                if url and url not in {x["url"] for x in sources}:
                    sources.append({"url": url})
            if decl.get("folder"):
                subfolder = str(decl["folder"]).replace("\\", "/").strip("/")
            elif entry and entry.get("folder"):
                subfolder = str(entry["folder"]).strip("/")
            first = sources[0] if sources else {}
            return {
                "filename": fname,
                "value": value.replace("\\", "/"),
                "subfolder": subfolder,
                "url": first.get("url"),
                "sources": sources,
                "gated": bool(first.get("gated")),
                "licenseUrl": first.get("license_url"),
                # What the download is checked against: the catalog's current
                # revision when it knows the file (the publisher may have
                # replaced the one the package was built with), else the
                # package's own declaration (PACKAGE_FORMAT.md §8.2.4).
                "sha256": (entry or {}).get("sha256") or sha,
                "size": (entry or {}).get("size") or size,
                "present": True if choices is None else _norm(value) in choices,
            }

        config = parse_config(workflow) or {}
        options = _quant_files(config)
        option_names = {_basename(v).lower() for o in options for _, v in o["values"]}
        for class_type, input_name, value in refs:
            if _basename(value).lower() in option_names:
                continue
            entry = describe(class_type, input_name, value)
            prev = models.get(entry["filename"].lower())
            if not prev or (not prev["url"] and entry["url"]):
                models[entry["filename"].lower()] = entry

        if options:
            group = []
            for opt in options:
                files = [describe(loader_for_input.get(inp, "UNETLoader"), inp, v) for inp, v in opt["values"]]
                group.append({"key": opt["key"], "label": opt["label"], "files": files,
                              "installed": all(f["present"] for f in files)})
            quant_groups.append({"options": group, "installed": any(o["installed"] for o in group)})

    by_pack: dict[str, dict[str, Any]] = {}
    unknown: list[str] = []
    for class_type in sorted(missing_classes):
        pack_id = (packs.get("classes") or {}).get(class_type)
        if not pack_id:
            unknown.append(class_type)
            continue
        pack = (packs.get("packs") or {}).get(pack_id) or {}
        entry = by_pack.setdefault(pack_id, {"id": pack_id, "name": pack.get("name") or pack_id,
                                             "repo": pack.get("repo") or "",
                                             "registryId": pack.get("registry_id") or "", "classes": []})
        entry["classes"].append(class_type)

    model_list = sorted(models.values(), key=lambda m: (m["present"], m["filename"].lower()))
    missing_models = [m for m in model_list if not m["present"]]
    quant_missing = [g for g in quant_groups if not g["installed"]]
    return {
        "ok": not missing_models and not quant_missing and not by_pack and not unknown,
        "models": model_list,
        "missingModels": len(missing_models),
        "quantization": quant_groups,
        "quantizationMissing": len(quant_missing),
        "nodePacks": list(by_pack.values()),
        "unknownNodes": unknown,
    }
