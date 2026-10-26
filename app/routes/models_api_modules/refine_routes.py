from __future__ import annotations

import io
import json
import logging
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, quote

from flask import jsonify, request
from PIL import Image

from app.services.comfy_paths import for_comfy
from app.config import DEFAULT_COMFY_URL
from app.paths import PACKAGES_DIR
from app.services.http_client import http_json, http_bytes, http_multipart_upload_image
from app.services import gpu_coordinator
from app.services.workflow_service import _extract_lora_options_from_object_info, _analyze_workflow
from app.routes.models_api_shared import (
    _apply_comfy_output_policy,
    _ensure_registry,
    _inject_uploaded_image_into_workflow,
    _parse_image_data_url,
    _safe_comfy_url,
    _select_output_images,
    _try_save_image_to_output_dir,
    models_api_bp,
)

_APP_DIR = Path(__file__).parent.parent.parent  # app/
logger = logging.getLogger(__name__)

# Extensions ComfyUI happily lists (it just enumerates the folder) but that
# spandrel — the loader ComfyUI's upscale/model nodes use — can never load,
# since these aren't PyTorch model formats at all (NCNN/ONNX exports some
# users keep alongside real .pth/.safetensors files in the same folder for
# their own testing). Filtering them out of combo-list responses avoids
# offering a choice that's guaranteed to fail with spandrel.UnsupportedModelError
# the moment it's actually used.
_UNLOADABLE_MODEL_EXTENSIONS = (".bin", ".onnx", ".param")


def _drop_unloadable_model_files(options: list[str]) -> list[str]:
    return [o for o in options if not str(o).lower().endswith(_UNLOADABLE_MODEL_EXTENSIONS)]


# Graphs a package renamed (old basename -> new): sessions and older installs
# still store the old path, so a miss retries with the new name.
_RENAMED_WORKFLOW_FILES = {
    "refine_qwen_2511_edit.json": "refine_qwen_edit.json",
}


def _load_workflow_file(relative_path: str) -> dict:
    try:
        return _load_workflow_file_exact(relative_path)
    except ValueError:
        path = Path(relative_path)
        renamed = _RENAMED_WORKFLOW_FILES.get(path.name)
        if not renamed:
            raise
        return _load_workflow_file_exact((path.parent / renamed).as_posix())


def _load_workflow_file_exact(relative_path: str) -> dict:
    """Resolves a refine flow's `workflow_file` against the two places it can
    live: `app/workflows/` for anything still shipped in the app's own code
    tree (legacy/addons), and `<data>/packages/` for a flow that came from an
    installed package — those declare their workflow_file already prefixed
    with their own package id (e.g. "nomad.core-refine/workflows/x.json"),
    written that way by tools/packages/build_packages.py at build time.
    Tries app dir first so no existing flow changes behavior."""
    safe = Path(relative_path).as_posix()
    if ".." in safe or safe.startswith("/"):
        raise ValueError("Invalid workflow_file path")
    for base in (_APP_DIR, PACKAGES_DIR):
        full = (base / safe).resolve()
        try:
            full.relative_to(base.resolve())
        except ValueError:
            continue  # escaped base, e.g. via a symlink — skip this base
        if full.is_file():
            raw = json.loads(full.read_text(encoding="utf-8"))
            return {k: v for k, v in raw.items() if not str(k).startswith("_")}
    raise ValueError(f"workflow_file not found: {relative_path}")


def _extract_combo_options(input_def) -> list[str]:
    """Pull a combo's list of string choices out of a ComfyUI object_info
    input definition, across the schema variants seen in the wild:

      Classic:      [["opt1", "opt2", ...], {metadata}]
      Newer/v3-ish: ["COMBO", {"options": ["opt1", "opt2", ...], ...}]
                    ["COMBO", {"choices": [...]}]
      Dict-first:   [{"options": [...]}, ...]  (options/choices nested in a
                    dict that is itself the first element instead of the type
                    name string)

    Returns [] if none of these shapes match — callers can then log the raw
    shape for further diagnosis.
    """
    if not isinstance(input_def, list) or not input_def:
        return []

    first = input_def[0]

    # Classic: first element IS the list of choices.
    if isinstance(first, list):
        return [str(v) for v in first if str(v).strip()]

    # Newer variants: choices live in a dict, either as the second element
    # (type-name string + metadata dict) or as the first element itself.
    meta_candidates = []
    if isinstance(first, dict):
        meta_candidates.append(first)
    if len(input_def) > 1 and isinstance(input_def[1], dict):
        meta_candidates.append(input_def[1])

    for meta in meta_candidates:
        for key in ("options", "choices", "values", "enum"):
            candidates = meta.get(key)
            if isinstance(candidates, list) and candidates:
                return [str(v) for v in candidates if str(v).strip()]

    return []


@models_api_bp.get("/models/workflow-file/analysis")
def get_workflow_file_analysis():
    """Analysis (quantization/quality/downloads/etc.) for a plain `workflow_file`
    flow (Refine's Qwen 2511 Edit, Flux Klein Edit, ...) — the workflow_file
    counterpart to an import record's `analysis`, so the frontend can reuse the
    same Advanced/Quantization panel that Create's imports already use, even
    though these flows never go through the Imports registry.

    Query params: file (workflow_file relative path).

    Response: { "analysis": {...} } — same shape as `import.analysis`
    (detected/basicParameters/advancedParameters/quantization/configNode/...).
    Returns { "analysis": null } (not an error) on any failure, so callers can
    just hide the Advanced panel when there's nothing to show.
    """
    workflow_file = str(request.args.get("file", "")).strip()
    if not workflow_file:
        return jsonify({"analysis": None})

    try:
        workflow = _load_workflow_file(workflow_file)
    except (ValueError, FileNotFoundError) as exc:
        logger.warning("workflow-file/analysis: could not load workflow_file=%r (%s)", workflow_file, exc)
        return jsonify({"analysis": None})

    try:
        analysis = _analyze_workflow(workflow)
    except Exception as exc:
        logger.warning("workflow-file/analysis: analysis failed for workflow_file=%r (%s)", workflow_file, exc)
        return jsonify({"analysis": None})

    return jsonify({"analysis": analysis})


@models_api_bp.get("/models/workflow-file/param-options")
def get_workflow_file_param_options():
    """Live enum options for a single node input of a plain `workflow_file`
    flow (Remove Background, Lettering, etc.) — the lightweight counterpart to
    /models/imports/<id>/param-options for flows that don't go through the
    Imports registry and so have no cached `analysis.advancedParameters`.

    Query params: file (workflow_file relative path), node (node id in that
    workflow), key (input name on that node, e.g. "model").

    Response: { "options": ["opt1", "opt2", ...] } — empty list (not an error)
    on any failure, so callers can just fall back to their static list.
    """
    workflow_file = str(request.args.get("file", "")).strip()
    node_id = str(request.args.get("node", "")).strip()
    input_key = str(request.args.get("key", "")).strip()
    if not workflow_file or not node_id or not input_key:
        logger.warning("param-options: missing query params file=%r node=%r key=%r", workflow_file, node_id, input_key)
        return jsonify({"options": []})

    try:
        workflow = _load_workflow_file(workflow_file)
    except (ValueError, FileNotFoundError) as exc:
        logger.warning("param-options: could not load workflow_file=%r (%s)", workflow_file, exc)
        return jsonify({"options": []})

    node = workflow.get(node_id)
    class_type = str(node.get("class_type", "")).strip() if isinstance(node, dict) else ""
    if not class_type:
        logger.warning("param-options: node id=%r not found (or has no class_type) in %r — keys present: %s", node_id, workflow_file, list(workflow.keys()))
        return jsonify({"options": []})

    data = _ensure_registry()
    comfy_api_url = str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip() or DEFAULT_COMFY_URL
    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
        object_info = http_json(f"{comfy_api_url}/object_info/{class_type}", timeout=20)
    except Exception as exc:
        logger.warning("param-options: /object_info/%s request to %s failed: %s", class_type, comfy_api_url, exc)
        return jsonify({"options": []})

    node_info = object_info.get(class_type, {}) if isinstance(object_info, dict) else {}
    if not node_info:
        logger.warning(
            "param-options: ComfyUI's /object_info/%s response has no entry for class_type %r — returned keys: %s",
            class_type, class_type, list(object_info.keys()) if isinstance(object_info, dict) else type(object_info),
        )
    input_spec = node_info.get("input", {}) if isinstance(node_info, dict) else {}
    options: list[str] = []
    raw_input_def = None
    for section_name in ("required", "optional"):
        section = input_spec.get(section_name, {}) if isinstance(input_spec, dict) else {}
        input_def = section.get(input_key) if isinstance(section, dict) else None
        if input_def is not None:
            raw_input_def = input_def
        options = _extract_combo_options(input_def)
        if options:
            break

    if not options and node_info:
        logger.warning(
            "param-options: found node_info for %s but no combo list at input_key=%r — input keys available: required=%s optional=%s — raw shape: %r",
            class_type, input_key,
            list((input_spec.get("required") or {}).keys()) if isinstance(input_spec, dict) else None,
            list((input_spec.get("optional") or {}).keys()) if isinstance(input_spec, dict) else None,
            raw_input_def,
        )

    options = _drop_unloadable_model_files(options)
    return jsonify({"options": options})


def _get_flow_preprocess(workflow: dict) -> dict | None:
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        if str(node.get("_meta", {}).get("title", "")) != "flow_data":
            continue
        raw = str(node.get("inputs", {}).get("value", "")).strip()
        if not raw:
            continue
        try:
            meta = json.loads(raw)
            p = meta.get("preprocess")
            return p if isinstance(p, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _pad_canvas(
    raw_bytes: bytes,
    target_w: int,
    target_h: int,
    background: str = "white",
    position: str = "center",
    scale_pct: float = 100.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> bytes:
    from PIL import ImageFilter
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
    orig_w, orig_h = img.size
    # Scale relative to the canvas: 100% = image fitted to fill the canvas
    # (keeping aspect ratio); lower values shrink it inside the canvas,
    # leaving more area to outpaint. Resolution-independent.
    try:
        factor = float(scale_pct) / 100.0
    except (TypeError, ValueError):
        factor = 1.0
    if factor <= 0:
        factor = 1.0
    fit = min(target_w / orig_w, target_h / orig_h)
    eff = fit * min(factor, 1.0)
    img = img.resize(
        (max(1, round(orig_w * eff)), max(1, round(orig_h * eff))),
        Image.LANCZOS,
    )
    orig_w, orig_h = img.size
    if "left" in position:
        x = 0
    elif "right" in position:
        x = target_w - orig_w
    else:
        x = (target_w - orig_w) // 2
    if "top" in position:
        y = 0
    elif "bottom" in position:
        y = target_h - orig_h
    else:
        y = (target_h - orig_h) // 2
    # Fine offset (px) on top of the grid anchor, clamped back onto the
    # canvas the same way the client-side preview does — a large offset just
    # pins the image against whichever edge it was heading towards, instead
    # of pushing it (or the canvas math) out of range.
    try:
        x += round(float(offset_x))
        y += round(float(offset_y))
    except (TypeError, ValueError):
        pass
    x = max(0, min(x, max(0, target_w - orig_w)))
    y = max(0, min(y, max(0, target_h - orig_h)))
    if background in ("transparent", "alpha", "none"):
        # Pad with real transparency and keep the alpha channel (RGBA PNG).
        canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
        canvas.paste(img, (x, y), img)
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return buf.getvalue()
    if background == "edge_blur":
        bg = img.convert("RGB").resize((target_w, target_h), Image.LANCZOS)
        blur_r = max(target_w, target_h) // 8
        bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_r)).convert("RGBA")
        bg.paste(img, (x, y))
        canvas = bg
    else:
        # Solid fill. Accept "r,g,b" / "r,g,b,a" strings (e.g. "0,255,0" green)
        # as well as PIL colour names, since PIL doesn't parse comma strings.
        fill = background
        bg_str = str(background).strip()
        if "," in bg_str:
            try:
                comps = [int(float(c)) for c in bg_str.split(",")]
                if len(comps) == 3:
                    fill = (comps[0], comps[1], comps[2], 255)
                elif len(comps) == 4:
                    fill = (comps[0], comps[1], comps[2], comps[3])
            except ValueError:
                fill = background
        canvas = Image.new("RGBA", (target_w, target_h), fill)
        canvas.paste(img, (x, y), img)
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def _apply_output_aspect(raw_bytes: bytes, merged_advanced: dict) -> None:
    """Output aspect ratio picked in Refine's Resolution panel ("_output.aspect",
    e.g. "16:9" or "2.39:1"; absent or "original" = keep the source's shape).
    Same pixel count as the image actually sent (after any downscale), in the
    new shape, snapped to /16 — written into the latent's width/height keys
    the flow names in "_output.width_key"/"_output.height_key"."""
    aspect = str(merged_advanced.get("_output.aspect") or "").strip().lower()
    width_key = str(merged_advanced.get("_output.width_key") or "").strip()
    height_key = str(merged_advanced.get("_output.height_key") or "").strip()
    if not aspect or aspect == "original" or not width_key or not height_key:
        return
    try:
        num, den = (float(p) for p in aspect.split(":", 1))
        ratio = num / den
        with Image.open(io.BytesIO(raw_bytes)) as img:
            src_w, src_h = img.size
    except Exception:
        return
    if ratio <= 0 or src_w <= 0 or src_h <= 0:
        return
    pixels = src_w * src_h
    merged_advanced[width_key] = max(16, round((pixels * ratio) ** 0.5 / 16) * 16)
    merged_advanced[height_key] = max(16, round((pixels / ratio) ** 0.5 / 16) * 16)


def _apply_preprocess(
    raw_bytes: bytes,
    mime: str,
    raw_workflow: dict,
    merged_advanced: dict,
) -> tuple[bytes, str]:
    _apply_output_aspect(raw_bytes, merged_advanced)
    preprocess = _get_flow_preprocess(raw_workflow)
    if not preprocess:
        return raw_bytes, mime
    if str(preprocess.get("type", "")) != "pad_canvas":
        return raw_bytes, mime
    width_key = str(preprocess.get("width_key", "")).strip()
    height_key = str(preprocess.get("height_key", "")).strip()
    target_w = int(merged_advanced.get(width_key, 0))
    target_h = int(merged_advanced.get(height_key, 0))
    if target_w <= 0 or target_h <= 0:
        return raw_bytes, mime
    background = str(merged_advanced.get("_preprocess.background") or preprocess.get("background", "white"))
    position = str(merged_advanced.get("_preprocess.position") or preprocess.get("position", "center"))
    try:
        scale_pct = float(merged_advanced.get("_preprocess.scale", 100) or 100)
    except (TypeError, ValueError):
        scale_pct = 100.0
    try:
        offset_x = float(merged_advanced.get("_preprocess.offset_x", 0) or 0)
    except (TypeError, ValueError):
        offset_x = 0.0
    try:
        offset_y = float(merged_advanced.get("_preprocess.offset_y", 0) or 0)
    except (TypeError, ValueError):
        offset_y = 0.0
    padded = _pad_canvas(raw_bytes, target_w, target_h, background, position, scale_pct, offset_x, offset_y)
    return padded, "image/png"


def _apply_advanced_values(workflow: dict, advanced_values: dict) -> None:
    for dot_key, value in advanced_values.items():
        parts = str(dot_key).split(".", 1)
        if len(parts) != 2:
            continue
        node_id, input_key = parts
        node = workflow.get(node_id)
        if not isinstance(node, dict):
            continue
        if input_key == "_mode":
            try:
                node["mode"] = int(value)
            except (ValueError, TypeError):
                pass
        elif isinstance(node.get("inputs"), dict):
            node["inputs"][input_key] = value


@models_api_bp.get("/models/comfy/loras")
def list_comfy_loras():
    """Returns LoRA filenames available in ComfyUI."""
    data = _ensure_registry()
    comfy_api_url = (
        str(request.args.get("comfyApiUrl", "")).strip()
        or str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip()
        or DEFAULT_COMFY_URL
    )
    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        object_info = http_json(f"{comfy_api_url}/object_info", timeout=15)
    except Exception as exc:
        return jsonify({"error": f"ComfyUI unreachable: {exc}"}), 502

    loras = _extract_lora_options_from_object_info(object_info)
    prefix = str(request.args.get("prefix", "")).strip()
    if prefix:
        loras = [l for l in loras if l.startswith(prefix)]
    return jsonify({"loras": loras})


_PLACEHOLDER_PNG_CACHE: bytes | None = None


def _neutral_placeholder_png() -> bytes:
    """Flat mid-gray 768x768 PNG, cached — stand-in for an optional mix image
    slot the user left empty (see prepare_mix_workflow). Size doesn't matter
    much: every mix workflow re-scales its LoadImage output with its own
    ImageScaleToTotalPixels node before it reaches the model."""
    global _PLACEHOLDER_PNG_CACHE
    if _PLACEHOLDER_PNG_CACHE is None:
        buf = io.BytesIO()
        Image.new("RGB", (768, 768), (128, 128, 128)).save(buf, format="PNG")
        _PLACEHOLDER_PNG_CACHE = buf.getvalue()
    return _PLACEHOLDER_PNG_CACHE


@models_api_bp.post("/models/quantization/presence")
def quantization_presence():
    """Which precision options (analysis.quantization.options) ComfyUI has the
    files for, so the Advanced panel can disable the rest instead of letting a
    pick fail at queue time. Body: {options: [...]}. Response: {present:
    {id: bool}}, or {present: null} when ComfyUI can't be asked — then every
    option stays enabled, as before."""
    from app.services import flow_requirements as reqs

    payload = request.get_json(silent=True) or {}
    options = [o for o in (payload.get("options") or []) if isinstance(o, dict)]
    if not options:
        return jsonify({"present": {}})
    data = _ensure_registry()
    comfy_api_url = str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip() or DEFAULT_COMFY_URL
    try:
        info = reqs.object_info(_safe_comfy_url(comfy_api_url), force=bool(payload.get("refresh")))
    except Exception:  # noqa: BLE001 — ComfyUI down: don't judge
        return jsonify({"present": None})
    return jsonify({"present": reqs.quantization_presence(options, info)})


@models_api_bp.post("/models/flows/requirements")
def flow_requirements():
    """Model files and custom nodes a flow's graphs need that ComfyUI does not
    have (app/services/flow_requirements.py). Body: {workflowFiles: [...],
    refresh: bool} — refresh skips the short object_info cache ("Check
    again" after a download)."""
    from app.services import flow_requirements as reqs
    from app.services.setup_service import is_local_url
    from .imports_routes import (
        _extract_downloads_from_workflow,
        _parse_workflow_config_node,
        _resolve_comfy_models_folder,
    )

    payload = request.get_json(silent=True) or {}
    files = [str(f).strip() for f in (payload.get("workflowFiles") or []) if str(f or "").strip()]
    workflows = []
    for rel in dict.fromkeys(files):
        try:
            workflows.append(_load_workflow_file(rel))
        except (ValueError, OSError, json.JSONDecodeError):
            continue  # a flow pointing at a graph that is gone is a different problem
    # Graphs the app runs after the flow's own (the Upscale output pill), with
    # the values it will set: {"file": ..., "values": {"<node>.<input>": v}}.
    for extra in payload.get("extraWorkflows") or []:
        if not isinstance(extra, dict) or not str(extra.get("file") or "").strip():
            continue
        rel = str(extra["file"]).strip()
        try:
            graph = _load_workflow_file(rel)
        except (ValueError, OSError, json.JSONDecodeError):
            continue
        for key, value in (extra.get("values") or {}).items():
            node_id, _, input_name = str(key).partition(".")
            node = graph.get(node_id)
            if input_name and "." not in input_name and isinstance(node, dict) and isinstance(value, (str, int, float)):
                node.setdefault("inputs", {})[input_name] = value
        workflows.append(graph)
        files.append(rel)
    if not workflows:
        return jsonify({"ok": True, "checked": 0})

    data = _ensure_registry()
    comfy_api_url = str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip() or DEFAULT_COMFY_URL
    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
        info = reqs.object_info(comfy_api_url, force=bool(payload.get("refresh")))
    except Exception as exc:  # noqa: BLE001 — ComfyUI down is its own notice
        return jsonify({"ok": False, "comfyUnreachable": True, "error": str(exc)[:200]})
    try:
        folders = http_json(f"{comfy_api_url}/models", timeout=8)
    except Exception:  # noqa: BLE001
        folders = []
    # What the packages behind these graphs declare about each model file
    # (requires.models: identity + fallback address) — the graph path starts
    # with the package id ("nomad.refine-styling/workflows/…").
    declared: dict = {}
    for rel in dict.fromkeys(files):
        pkg_id = Path(rel).as_posix().split("/", 1)[0]
        manifest_path = PACKAGES_DIR / pkg_id / "manifest.json"
        if ".." in pkg_id or not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for m in ((manifest.get("requires") or {}).get("models") or []):
            if isinstance(m, dict) and str(m.get("file", "")).strip():
                declared.setdefault(str(m["file"]).strip().lower(), m)
    from app.services import models_catalog
    catalog = models_catalog.load(str(data.get("settings", {}).get("modelsCatalogUrl", "") or "").strip(),
                                  force=bool(payload.get("refresh")))

    result = reqs.check(workflows, info, _parse_workflow_config_node, _extract_downloads_from_workflow,
                        [f for f in folders if isinstance(f, str)] if isinstance(folders, list) else [],
                        declared=declared, catalog=catalog)
    result.update({
        "catalogSource": models_catalog.source(),
        "checked": len(workflows),
        "modelsFolderSet": bool(_resolve_comfy_models_folder()),
        "comfyIsLocal": is_local_url(comfy_api_url),
    })
    return jsonify(result)


@models_api_bp.post("/models/mix/prepare")
def prepare_mix_workflow():
    """Prepare a mix workflow (2+ image inputs) for direct JS submission to ComfyUI.

    Accepts:
      workflowFile  – relative path to the workflow JSON
      images        – list of {dataUrl, nodeId} dicts, one per LoadImage node
      advancedValues – dot-notation overrides (e.g. {"135.text": "...", "125.noise_seed": 42})

    Returns {workflow, clientId, comfyApiUrl} — same contract as refine/prepare.
    """
    payload = request.get_json(silent=True) or {}
    prepared = _prepare_mix(payload)
    if not isinstance(prepared, tuple):
        return prepared
    prepared_workflow, comfy_api_url, _data, _merged = prepared
    gpu_coordinator.wait_external("comfy")  # browser submits directly (superqueue)
    client_id = uuid.uuid4().hex
    return jsonify({
        "workflow": prepared_workflow,
        "clientId": client_id,
        "comfyApiUrl": comfy_api_url,
    })


@models_api_bp.post("/models/mix/generate")
def generate_mix_image():
    """Run a mix workflow end to end on the server and save the result — the
    mix counterpart of /models/refine/generate, for callers with no browser
    (the MCP, NomadStudio#25). Same body as /models/mix/prepare; returns
    {ok, workflowFile, promptId, savedFilename}."""
    payload = request.get_json(silent=True) or {}
    prepared = _prepare_mix(payload)
    if not isinstance(prepared, tuple):
        return prepared
    prepared_workflow, comfy_api_url, data, merged_advanced = prepared
    workflow_file = str(payload.get("workflowFile", "")).strip()
    return _run_and_save(data, comfy_api_url, prepared_workflow, workflow_file, merged_advanced, "mix")


def _prepare_mix(payload: dict):
    """Load a mix workflow, apply advancedValues and upload each image into its
    LoadImage node. Returns (workflow, comfyApiUrl, registry, advancedValues),
    or an error response."""
    workflow_file = str(payload.get("workflowFile", "")).strip()
    images = payload.get("images", [])
    advanced_values = payload.get("advancedValues", {})

    if not workflow_file:
        return jsonify({"error": "workflowFile is required"}), 400
    if not isinstance(images, list) or len(images) < 1:
        return jsonify({"error": "images must be a non-empty list"}), 400

    try:
        raw_workflow = _load_workflow_file(workflow_file)
    except (ValueError, FileNotFoundError) as exc:
        return jsonify({"error": f"Workflow file error: {exc}"}), 400

    data = _ensure_registry()
    comfy_api_url = (
        str(payload.get("comfyApiUrl", "")).strip()
        or str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip()
        or DEFAULT_COMFY_URL
    )
    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    merged_advanced: dict = {}
    if isinstance(advanced_values, dict):
        for key, value in advanced_values.items():
            key_text = str(key or "").strip()
            if key_text and isinstance(value, (str, int, float, bool)):
                merged_advanced[key_text] = value

    prepared_workflow = deepcopy(raw_workflow)
    _apply_advanced_values(prepared_workflow, merged_advanced)

    # Upload each image and inject into its node
    for img_entry in images:
        if not isinstance(img_entry, dict):
            continue
        data_url = str(img_entry.get("dataUrl", "")).strip()
        node_id = str(img_entry.get("nodeId", "")).strip() or None
        if not data_url:
            if not node_id:
                continue
            # Optional image slot left empty (e.g. Clothes Mix run text-only,
            # no reference photo) — the node still needs SOME uploaded image
            # to keep the graph valid, and leaving the workflow file's own
            # baked-in LoadImage filename in place would reference whatever
            # test image the flow's author had on their own ComfyUI input
            # folder, which won't exist on the user's server. A flat neutral
            # placeholder stands in for it instead; the prompt (already
            # required for this case by updateGenerateBtn client-side) is
            # what actually drives the result.
            mime, raw_bytes = "image/png", _neutral_placeholder_png()
        else:
            try:
                mime, raw_bytes = _parse_image_data_url(data_url)
            except ValueError as exc:
                return jsonify({"error": f"Invalid image dataUrl: {exc}"}), 400

        image_ext = "png" if mime == "image/png" else ("jpg" if mime == "image/jpeg" else "webp")
        upload_filename = f"oj-mix-{uuid.uuid4().hex}.{image_ext}"
        try:
            upload_result = http_multipart_upload_image(
                f"{comfy_api_url}/upload/image",
                upload_filename,
                raw_bytes,
                mime,
            )
            comfy_filename = str(upload_result.get("name", "")).strip() or upload_filename
        except Exception as exc:
            return jsonify({"error": f"ComfyUI image upload failed: {exc}"}), 502

        if node_id and node_id in prepared_workflow:
            node = prepared_workflow[node_id]
            if isinstance(node, dict) and isinstance(node.get("inputs"), dict):
                node["inputs"]["image"] = comfy_filename
        else:
            # Fallback: inject into first available LoadImage node not yet overridden
            if not _inject_uploaded_image_into_workflow(prepared_workflow, comfy_filename, node_id=node_id):
                return jsonify({"error": f"No LoadImage node found for nodeId={node_id}"}), 400

    _apply_comfy_output_policy(data, prepared_workflow)
    return prepared_workflow, comfy_api_url, data, merged_advanced


@models_api_bp.post("/models/refine/preprocess-preview")
def preprocess_preview():
    """Return the preprocessed image as a base64 data URL (no ComfyUI involved)."""
    import base64
    payload        = request.get_json(silent=True) or {}
    image_data_url = str(payload.get("imageDataUrl", "")).strip()
    workflow_file  = str(payload.get("workflowFile", "")).strip()
    advanced_values = payload.get("advancedValues", {})

    if not image_data_url:
        return jsonify({"error": "imageDataUrl required"}), 400

    try:
        mime, raw_bytes = _parse_image_data_url(image_data_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    merged_advanced: dict = {}
    if isinstance(advanced_values, dict):
        for k, v in advanced_values.items():
            k = str(k or "").strip()
            if k and isinstance(v, (str, int, float, bool)):
                merged_advanced[k] = v

    if workflow_file:
        try:
            raw_workflow = _load_workflow_file(workflow_file)
            raw_bytes, mime = _apply_preprocess(raw_bytes, mime, raw_workflow, merged_advanced)
        except Exception:
            pass

    data_url = "data:" + mime + ";base64," + base64.b64encode(raw_bytes).decode()
    return jsonify({"dataUrl": data_url})


@models_api_bp.post("/models/refine/prepare")
def prepare_refine_workflow():
    """Prepare refine workflow for direct JS submission to ComfyUI.

    Loads the workflow file, uploads the source image to ComfyUI, applies
    advanced values, and returns {workflow, clientId, comfyApiUrl} — same
    contract as /models/imports/prepare-queue.
    """
    payload = request.get_json(silent=True) or {}
    workflow_file = str(payload.get("workflowFile", "")).strip()
    image_data_url = str(payload.get("imageDataUrl", "")).strip()
    advanced_values = payload.get("advancedValues", {})
    image_node_id = str(payload.get("imageNodeId", "")).strip() or None

    if not workflow_file:
        return jsonify({"error": "workflowFile is required"}), 400
    if not image_data_url:
        return jsonify({"error": "imageDataUrl is required"}), 400

    try:
        raw_workflow = _load_workflow_file(workflow_file)
    except (ValueError, FileNotFoundError) as exc:
        return jsonify({"error": f"Workflow file error: {exc}"}), 400

    data = _ensure_registry()
    comfy_api_url = (
        str(payload.get("comfyApiUrl", "")).strip()
        or str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip()
        or DEFAULT_COMFY_URL
    )

    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        mime, raw_bytes = _parse_image_data_url(image_data_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    merged_advanced: dict = {}
    if isinstance(advanced_values, dict):
        for key, value in advanced_values.items():
            key_text = str(key or "").strip()
            if key_text and isinstance(value, (str, int, float, bool)):
                merged_advanced[key_text] = value

    raw_bytes, mime = _apply_preprocess(raw_bytes, mime, raw_workflow, merged_advanced)

    image_ext = "png" if mime == "image/png" else ("jpg" if mime == "image/jpeg" else "webp")
    upload_filename = f"oj-refine-{uuid.uuid4().hex}.{image_ext}"
    try:
        upload_result = http_multipart_upload_image(
            f"{comfy_api_url}/upload/image",
            upload_filename,
            raw_bytes,
            mime,
        )
        comfy_filename = str(upload_result.get("name", "")).strip() or upload_filename
    except Exception as exc:
        return jsonify({"error": f"ComfyUI image upload failed: {exc}"}), 502

    prepared_workflow = deepcopy(raw_workflow)
    _apply_advanced_values(prepared_workflow, merged_advanced)

    if not _inject_uploaded_image_into_workflow(
        prepared_workflow, comfy_filename, node_id=image_node_id
    ):
        return jsonify({"error": "Workflow has no LoadImage node for input image"}), 400

    _apply_comfy_output_policy(data, prepared_workflow)
    gpu_coordinator.wait_external("comfy")  # browser submits directly (superqueue)
    client_id = uuid.uuid4().hex

    input_image_url = (
        f"{comfy_api_url}/view?filename={quote(comfy_filename)}&type=input"
    )

    return jsonify({
        "workflow":      prepared_workflow,
        "clientId":      client_id,
        "comfyApiUrl":   comfy_api_url,
        "inputImageUrl": input_image_url,
    })


@models_api_bp.post("/models/refine/generate")
def generate_refine_image():
    payload = request.get_json(silent=True) or {}
    workflow_file = str(payload.get("workflowFile", "")).strip()
    image_data_url = str(payload.get("imageDataUrl", "")).strip()
    advanced_values = payload.get("advancedValues", {})
    image_node_id = str(payload.get("imageNodeId", "")).strip() or None

    if not workflow_file:
        return jsonify({"error": "workflowFile is required"}), 400
    if not image_data_url:
        return jsonify({"error": "imageDataUrl is required"}), 400

    try:
        raw_workflow = _load_workflow_file(workflow_file)
    except (ValueError, FileNotFoundError) as exc:
        return jsonify({"error": f"Workflow file error: {exc}"}), 400

    data = _ensure_registry()
    comfy_api_url = (
        str(payload.get("comfyApiUrl", "")).strip()
        or str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip()
        or DEFAULT_COMFY_URL
    )

    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        mime, raw_bytes = _parse_image_data_url(image_data_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    merged_advanced: dict = {}
    if isinstance(advanced_values, dict):
        for key, value in advanced_values.items():
            key_text = str(key or "").strip()
            if key_text and isinstance(value, (str, int, float, bool)):
                merged_advanced[key_text] = value

    raw_bytes, mime = _apply_preprocess(raw_bytes, mime, raw_workflow, merged_advanced)

    image_ext = "png" if mime == "image/png" else ("jpg" if mime == "image/jpeg" else "webp")
    upload_filename = f"oj-refine-{uuid.uuid4().hex}.{image_ext}"

    try:
        upload_result = http_multipart_upload_image(
            f"{comfy_api_url}/upload/image",
            upload_filename,
            raw_bytes,
            mime,
        )
        comfy_filename = str(upload_result.get("name", "")).strip() or upload_filename
    except Exception as exc:
        return jsonify({"error": f"ComfyUI image upload failed: {exc}"}), 502

    prepared_workflow = deepcopy(raw_workflow)
    _apply_advanced_values(prepared_workflow, merged_advanced)

    if not _inject_uploaded_image_into_workflow(
        prepared_workflow, comfy_filename, node_id=image_node_id
    ):
        return jsonify(
            {"error": "Workflow has no LoadImage node for input image"}
        ), 400

    _apply_comfy_output_policy(data, prepared_workflow)
    return _run_and_save(data, comfy_api_url, prepared_workflow, workflow_file, merged_advanced, "refine")


# ── Multimask (NomadStudio#40) ───────────────────────────────────────────────
# Smart Selection with a comma list ("crow, pig, girl"): SAM3 merges every
# term into one selection, so each term gets its own run here, and the results
# come back as one mask + one cutout per term plus a composite to review them.
_SMART_SELECTION_WF = "nomad.refine-extract/workflows/refine/refine_smart_selection.json"
_MULTIMASK_COLORS = [(255, 0, 200), (0, 210, 255), (90, 255, 60), (255, 170, 0),
                     (160, 90, 255), (255, 60, 60), (0, 255, 170), (255, 255, 0)]
_MULTIMASK_MAX_TERMS = 8


def _split_mask_terms(text: str) -> list[str]:
    """'crow, pig , girl' -> ['crow', 'pig', 'girl'] (empties and repeats dropped).
    A SAM3 count cap like 'eye:2' stays with its term."""
    seen: list[str] = []
    for part in str(text or "").split(","):
        term = part.strip()
        if term and term.lower() not in (s.lower() for s in seen):
            seen.append(term)
    return seen


def _queue_and_fetch(comfy_api_url: str, prepared_workflow: dict) -> bytes:
    """Run a prepared workflow on ComfyUI and return its saved output image."""
    with gpu_coordinator.held("comfy"):
        prompt_response = http_json(
            f"{comfy_api_url}/prompt", method="POST",
            payload={"prompt": for_comfy(prepared_workflow, comfy_api_url), "client_id": uuid.uuid4().hex},
            timeout=30,
        )
        prompt_id = str(prompt_response.get("prompt_id", "")).strip()
        if not prompt_id:
            raise RuntimeError(f"ComfyUI rejected prompt: {prompt_response}")
        history_payload: dict = {}
        for _ in range(720):
            time.sleep(0.5)
            history_payload = http_json(f"{comfy_api_url}/history/{prompt_id}", timeout=120)
            if isinstance(history_payload, dict) and history_payload.get(prompt_id, {}).get("outputs"):
                break
    _node, entries = _select_output_images(history_payload, prompt_id, [])
    if not entries:
        raise RuntimeError("No output image found in ComfyUI history")
    first = entries[0]
    query = urlencode({"filename": first.get("filename", ""), "subfolder": first.get("subfolder", ""),
                       "type": first.get("type", "output")})
    return http_bytes(f"{comfy_api_url}/view?{query}", timeout=180)


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _multimask_composite(source: Image.Image, results: list[dict]) -> Image.Image:
    """The source with each found term tinted in its colour, outlined, and a
    legend (colour swatch + term) in the top-left corner."""
    from PIL import ImageDraw, ImageFilter, ImageFont

    out = source.convert("RGBA")
    for r in results:
        mask = r.get("_mask")
        if mask is None:
            continue
        color = tuple(r["color"])
        tint = Image.new("RGBA", out.size, color + (0,))
        tint.putalpha(mask.point(lambda v: int(v * 0.5)))
        out.alpha_composite(tint)
        edge = mask.point(lambda v: 255 if v > 127 else 0).filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(5))
        line = Image.new("RGBA", out.size, color + (0,))
        line.putalpha(edge)
        out.alpha_composite(line)

    size = max(16, out.width // 70)
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:
        font = ImageFont.load_default()
    rows = [(r["term"] + ("" if r["found"] else "  (not found)"), tuple(r["color"])) for r in results]
    pad, sw = size // 2, size
    widths = [ImageDraw.Draw(out).textlength(t, font=font) for t, _ in rows]
    box_w = int(pad * 3 + sw + max(widths or [0]))
    box_h = int(pad + len(rows) * (size + pad))
    legend = Image.new("RGBA", out.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(legend)
    d.rounded_rectangle((pad, pad, pad + box_w, pad + box_h), radius=pad, fill=(0, 0, 0, 170))
    y = pad * 2
    for (text, color), _w in zip(rows, widths):
        d.rectangle((pad * 2, y, pad * 2 + sw, y + sw), fill=color + (255,))
        d.text((pad * 3 + sw, y - size // 8), text, font=font, fill=(255, 255, 255, 255))
        y += size + pad
    out.alpha_composite(legend)
    return out.convert("RGB")


def _sam_masks(data, comfy_api_url, raw_workflow, comfy_filename, source, terms, payload) -> list[dict]:
    """One Smart Selection (SAM3) run per term on an already-uploaded image.
    Each result: {term, found, color, bbox, _mask (L, source size) or None}."""
    base_values = {
        "4.threshold": payload.get("threshold", 0.5),
        "4.refine_iterations": payload.get("refineIterations", 2),
        "4.individual_masks": False,
    }
    results: list[dict] = []
    for i, term in enumerate(terms):
        workflow = deepcopy(raw_workflow)
        _apply_advanced_values(workflow, {**base_values, "3.text": term})
        if not _inject_uploaded_image_into_workflow(workflow, comfy_filename):
            raise RuntimeError("Workflow has no LoadImage node for input image")
        _apply_comfy_output_policy(data, workflow)
        holed = Image.open(io.BytesIO(_queue_and_fetch(comfy_api_url, workflow))).convert("RGBA")
        mask = holed.getchannel("A").point(lambda v: 255 - v)
        if mask.size != source.size:
            mask = mask.resize(source.size, Image.LANCZOS)
        bbox = mask.point(lambda v: 255 if v > 127 else 0).getbbox()
        coverage = sum(mask.point(lambda v: 1 if v > 127 else 0).getdata()) / (source.width * source.height)
        found = bool(bbox) and coverage > 0.0005
        results.append({"term": term, "found": found, "color": _MULTIMASK_COLORS[i % len(_MULTIMASK_COLORS)],
                        "bbox": list(bbox) if found else None, "_mask": mask if found else None})
    return results


def _natural_list(terms: list[str]) -> str:
    """['crow', 'chef pig', 'girl'] -> 'the crow, the chef pig and the girl'."""
    items = [t if t.lower().startswith(("the ", "a ", "an ")) else f"the {t}" for t in terms]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


_SMART_FILL_WF = "nomad.refine-extract/workflows/refine/selection/refine_smart_selection_fill.json"


@models_api_bp.post("/models/refine/multiremove")
def generate_refine_multiremove():
    """Smart Object Removal for several objects ("crow, chef pig, girl"): one
    SAM3 run per term, the masks joined, and ONE Qwen fill inside that joined
    mask (the fill workflow's own SAM3 node is bypassed by a LoadImageMask).
    Body: {imageDataUrl, text, fillPrompt?, padding?, threshold?}. Returns
    {ok, savedFilename, removed: [...], notFound: [...]}. NomadStudio#40."""
    payload = request.get_json(silent=True) or {}
    image_data_url = str(payload.get("imageDataUrl", "")).strip()
    terms = _split_mask_terms(payload.get("text", ""))
    if not image_data_url or not terms:
        return jsonify({"error": "imageDataUrl and text are required"}), 400
    if len(terms) > _MULTIMASK_MAX_TERMS:
        return jsonify({"error": f"At most {_MULTIMASK_MAX_TERMS} terms per run"}), 400
    try:
        sam_workflow = _load_workflow_file(_SMART_SELECTION_WF)
        fill_workflow = _load_workflow_file(_SMART_FILL_WF)
    except (ValueError, FileNotFoundError) as exc:
        return jsonify({"error": f"Workflow file error: {exc}"}), 400
    data = _ensure_registry()
    try:
        comfy_api_url = _safe_comfy_url(
            str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip() or DEFAULT_COMFY_URL)
        mime, raw_bytes = _parse_image_data_url(image_data_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    source = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    ext = "png" if mime == "image/png" else ("jpg" if mime == "image/jpeg" else "webp")
    try:
        up = http_multipart_upload_image(f"{comfy_api_url}/upload/image",
                                         f"oj-multiremove-{uuid.uuid4().hex}.{ext}", raw_bytes, mime)
        comfy_filename = str(up.get("name", "")).strip()
        results = _sam_masks(data, comfy_api_url, sam_workflow, comfy_filename, source, terms, payload)
    except Exception as exc:
        return jsonify({"error": f"Smart Selection failed: {exc}"}), 502

    found = [r for r in results if r["found"]]
    not_found = [r["term"] for r in results if not r["found"]]
    if not found:
        return jsonify({"error": "None of the objects was found: " + ", ".join(not_found)}), 422
    # One fill per object, chained: each run removes ONE object (its own mask,
    # "Remove the girl") from the previous result. A single fill of the joined
    # mask makes Qwen redraw what it can still see in its reference image, and
    # Qwen 2511 keeps white holes white, so the chained single removals (which
    # work every time) are the reliable way. Masks come from the original.
    current = raw_bytes
    current_mime = mime
    # The flow's default "what was behind it" lets Qwen put a new character or
    # prop in the hole; removing several objects needs a stricter one.
    fill_prompt = str(payload.get("fillPrompt") or "").strip()
    if not fill_prompt or fill_prompt.lower().startswith("fill that area with what was behind it"):
        fill_prompt = ("Fill that area only with the empty background that was behind it: the ground, walls, "
                       "buildings and sky, continuing the surrounding scene with the same lighting, perspective "
                       "and style. Do not add any new character, animal, person or object.")
    import random
    try:
        for r in found:
            ext_now = "png" if current_mime == "image/png" else ("jpg" if current_mime == "image/jpeg" else "webp")
            img_up = http_multipart_upload_image(f"{comfy_api_url}/upload/image",
                                                 f"oj-multiremove-{uuid.uuid4().hex}.{ext_now}", current, current_mime)
            mask_up = http_multipart_upload_image(f"{comfy_api_url}/upload/image",
                                                  f"oj-multiremove-mask-{uuid.uuid4().hex}.png",
                                                  _png_bytes(r["_mask"].convert("RGB")), "image/png")
            workflow = deepcopy(fill_workflow)
            # A fresh seed per fill (the workflow's saved one repeats every result).
            values = {"240.value": r["term"], "241.value": fill_prompt, "15.seed": random.randint(1, 2**48)}
            # The flow's model choices (Variation Normal/Turbo, Quantization, steps).
            for key, val in (payload.get("advancedValues") or {}).items():
                if str(key).startswith(("6.", "3.", "15.steps", "15.cfg")) and isinstance(val, (str, int, float)):
                    values[str(key)] = val
            # At least 30 px: these illustrations have a light paper halo around
            # each character; 15 px left it as outlines Qwen then continued.
            try:
                padding = int(payload.get("padding") or 0)
            except (TypeError, ValueError):
                padding = 0
            values["114.expand"] = max(padding, 30)
            _apply_advanced_values(workflow, values)
            # This object's mask replaces the workflow's own SAM3 selection.
            workflow["900"] = {"class_type": "LoadImageMask",
                               "inputs": {"image": str(mask_up.get("name", "")).strip(), "channel": "red"},
                               "_meta": {"title": "Object mask"}}
            for node in workflow.values():
                inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
                for key, val in list(inputs.items()):
                    if isinstance(val, list) and val and str(val[0]) == "99:75":
                        inputs[key] = ["900", 0]
            if not _inject_uploaded_image_into_workflow(workflow, str(img_up.get("name", "")).strip()):
                return jsonify({"error": "Workflow has no LoadImage node for input image"}), 400
            _apply_comfy_output_policy(data, workflow)
            out = Image.open(io.BytesIO(_queue_and_fetch(comfy_api_url, workflow))).convert("RGB")
            if out.size != source.size:
                out = out.resize(source.size, Image.LANCZOS)
            current, current_mime = _png_bytes(out), "image/png"
    except Exception as exc:
        return jsonify({"error": f"Smart Object Removal failed: {exc}"}), 502

    meta = {"source": "refine", "workflow_file": _SMART_FILL_WF,
            "advanced_values": json.dumps({"terms": ", ".join(terms)}, ensure_ascii=False),
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    saved = _try_save_image_to_output_dir(data, current, meta, "refine", 0)
    return jsonify({"ok": True, "workflowFile": _SMART_FILL_WF, "savedFilename": saved,
                    "removed": [r["term"] for r in found], "notFound": not_found})

@models_api_bp.post("/models/refine/multimask")
def generate_refine_multimask():
    """Body: {imageDataUrl, text: "crow, pig, girl", threshold?, refineIterations?}.
    Returns {ok, savedFilename (composite), masks: [{term, found, mask, cutout,
    bbox, color}]} — mask/cutout are saved filenames like any generation."""
    payload = request.get_json(silent=True) or {}
    image_data_url = str(payload.get("imageDataUrl", "")).strip()
    terms = _split_mask_terms(payload.get("text", ""))
    if not image_data_url:
        return jsonify({"error": "imageDataUrl is required"}), 400
    if not terms:
        return jsonify({"error": "text is required (one or more terms, separated by commas)"}), 400
    if len(terms) > _MULTIMASK_MAX_TERMS:
        return jsonify({"error": f"At most {_MULTIMASK_MAX_TERMS} terms per run"}), 400

    try:
        raw_workflow = _load_workflow_file(_SMART_SELECTION_WF)
    except (ValueError, FileNotFoundError) as exc:
        return jsonify({"error": f"Workflow file error: {exc}"}), 400
    data = _ensure_registry()
    try:
        comfy_api_url = _safe_comfy_url(
            str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip() or DEFAULT_COMFY_URL)
        mime, raw_bytes = _parse_image_data_url(image_data_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    source = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    image_ext = "png" if mime == "image/png" else ("jpg" if mime == "image/jpeg" else "webp")
    try:
        upload = http_multipart_upload_image(f"{comfy_api_url}/upload/image",
                                             f"oj-multimask-{uuid.uuid4().hex}.{image_ext}", raw_bytes, mime)
        comfy_filename = str(upload.get("name", "")).strip()
    except Exception as exc:
        return jsonify({"error": f"ComfyUI image upload failed: {exc}"}), 502

    try:
        results = _sam_masks(data, comfy_api_url, raw_workflow, comfy_filename, source, terms, payload)
    except Exception as exc:
        return jsonify({"error": f"Smart Selection failed: {exc}"}), 502

    meta_base = {"source": "refine-multimask", "workflow_file": _SMART_SELECTION_WF,
                 "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    composite = _multimask_composite(source, results)
    saved = _try_save_image_to_output_dir(
        data, _png_bytes(composite), {**meta_base, "terms": ", ".join(terms)}, "multimask", 0)
    masks_out = []
    for r in results:
        entry = {"term": r["term"], "found": r["found"], "bbox": r["bbox"], "color": r["color"],
                 "mask": None, "cutout": None}
        if r["found"]:
            mask = r["_mask"]
            meta = {**meta_base, "term": r["term"]}
            entry["mask"] = _try_save_image_to_output_dir(data, _png_bytes(mask), meta, "mask", 0)
            cut = source.convert("RGBA")
            cut.putalpha(mask)
            entry["cutout"] = _try_save_image_to_output_dir(
                data, _png_bytes(cut.crop(tuple(r["bbox"]))), meta, "cutout", 0)
        masks_out.append(entry)
    return jsonify({"ok": True, "workflowFile": _SMART_SELECTION_WF, "savedFilename": saved, "masks": masks_out})


def _run_and_save(data, comfy_api_url, prepared_workflow, workflow_file, merged_advanced, source):
    """Queue a prepared workflow on ComfyUI, wait for it and save its first
    image to the active viewer's output folder (refine/generate, mix/generate)."""
    try:
        with gpu_coordinator.held("comfy"):
            prompt_response = http_json(
                f"{comfy_api_url}/prompt",
                method="POST",
                payload={"prompt": for_comfy(prepared_workflow, comfy_api_url), "client_id": uuid.uuid4().hex},
                timeout=30,
            )
            prompt_id = str(prompt_response.get("prompt_id", "")).strip()
            if not prompt_id:
                return jsonify({"error": f"ComfyUI rejected prompt: {prompt_response}"}), 502

            history_payload: dict = {}
            for _ in range(720):
                time.sleep(0.5)
                history_payload = http_json(
                    f"{comfy_api_url}/history/{prompt_id}", timeout=120
                )
                if isinstance(history_payload, dict) and prompt_id in history_payload:
                    outputs = history_payload.get(prompt_id, {}).get("outputs", {})
                    if outputs:
                        break

        _output_node_id, image_entries = _select_output_images(
            history_payload, prompt_id, []
        )
        if not image_entries:
            return jsonify({"error": "No output image found in ComfyUI history"}), 502

        first = image_entries[0]
        query = urlencode(
            {
                "filename": first.get("filename", ""),
                "subfolder": first.get("subfolder", ""),
                "type": first.get("type", "output"),
            }
        )
        image_bytes = http_bytes(f"{comfy_api_url}/view?{query}", timeout=180)

        meta: dict[str, str] = {
            "source": source,
            "session": prompt_id,
            "workflow_file": workflow_file,
            "advanced_values": json.dumps(merged_advanced, ensure_ascii=False),
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        saved_filename = _try_save_image_to_output_dir(
            data, image_bytes, meta, source, 0
        )
    except Exception as exc:
        return jsonify({"error": f"ComfyUI {source} workflow failed: {exc}"}), 502

    return jsonify(
        {
            "ok": True,
            "workflowFile": workflow_file,
            "promptId": prompt_id,
            "savedFilename": saved_filename,
        }
    )
