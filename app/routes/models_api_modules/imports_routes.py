from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timezone

from flask import Response, jsonify, make_response, request

from app.config import DEFAULT_COMFY_URL, MAX_IMPORT_NAME_LENGTH
from app import paths
from app.services.http_client import http_json
from app.routes.models_api_shared import (
    _analyze_workflow,
    _ensure_registry,
    _extract_checkpoint_loader_keys,
    _extract_checkpoint_options_from_object_info,
    _extract_clip_last_layer_keys,
    _extract_lora_loader_keys,
    _extract_lora_options_from_object_info,
    _normalize_record_negative,
    _parse_workflow_config_node,
    _parse_workflow_payload,
    _resolve_text_from_node,
    _safe_comfy_url,
    _save_registry,
    _validate_clip_last_layer_advanced_values,
    logger,
    models_api_bp,
)


WORKFLOW_LOGOS_DIR = paths.user_images("workflow_logos")
WORKFLOW_LOGOS_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


from app.routes.models_api_modules.imports_civitai import (
    _extract_civitai_identifiers,
    _extract_civitai_details,
    _extract_civitai_preview_image,
)
from app.routes.models_api_modules.imports_lora_catalog import (
    _parse_lora_catalog_line,
    _is_lora_catalog_candidate_line,
    _extract_lora_catalog,
    _extract_verified_loras,
    _extract_model_files,
    _MODEL_FILE_EXTENSIONS,
)

def _ensure_workflow_logos_dir() -> Path:
    WORKFLOW_LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    return WORKFLOW_LOGOS_DIR


def _sanitize_workflow_logo_name(filename: str) -> str:
    base = Path(str(filename or "")).name.strip()
    if not base:
        return ""
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    stem = Path(base).stem.strip("._")
    suffix = Path(base).suffix.lower()
    if not stem or suffix not in WORKFLOW_LOGOS_ALLOWED_EXTENSIONS:
        return ""
    return f"{stem}{suffix}"


def _normalize_image_filename(value: object) -> str:
    raw_value = str(value or "")
    # Some workflow nodes store values as "filename\n\n"; keep first non-empty line.
    for line in raw_value.replace("\r", "\n").split("\n"):
        candidate = os.path.basename(str(line).strip())
        if candidate:
            return candidate
    return ""


def _workflow_logo_url(filename: str) -> str:
    return f"/api/models/workflow-logos/{filename}"


@models_api_bp.get("/models/workflow-logos")
def list_workflow_logos():
    root = _ensure_workflow_logos_dir()
    files: list[dict[str, str]] = []
    for path in sorted(root.glob("*"), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in WORKFLOW_LOGOS_ALLOWED_EXTENSIONS:
            continue
        files.append(
            {
                "name": path.name,
                "url": _workflow_logo_url(path.name),
            }
        )
    return jsonify({"images": files})


@models_api_bp.post("/models/workflow-logos")
def upload_workflow_logo():
    root = _ensure_workflow_logos_dir()
    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify({"error": "file is required"}), 400

    safe_name = _sanitize_workflow_logo_name(uploaded.filename or "")
    if not safe_name:
        return jsonify({"error": "invalid filename or extension"}), 400

    target = root / safe_name
    try:
        uploaded.save(str(target))
    except Exception as exc:
        return jsonify({"error": f"failed saving file: {exc}"}), 500

    return jsonify(
        {
            "ok": True,
            "image": {
                "name": safe_name,
                "url": _workflow_logo_url(safe_name),
            },
        }
    )


@models_api_bp.get("/models/workflow-logos/<path:filename>")
def serve_workflow_logo(filename: str):
    root = _ensure_workflow_logos_dir()
    safe_name = _sanitize_workflow_logo_name(filename)
    if not safe_name:
        return jsonify({"error": "Invalid path"}), 400

    target = (root / safe_name).resolve()
    try:
        target.relative_to(root.resolve())
    except (ValueError, Exception):
        return jsonify({"error": "Invalid path"}), 400

    if not target.is_file():
        return jsonify({"error": "Image not found"}), 404

    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    content_type = mime_map.get(target.suffix.lower(), "application/octet-stream")

    try:
        data = target.read_bytes()
    except Exception:
        return jsonify({"error": "Image not found"}), 404

    resp = make_response(data)
    resp.headers["Content-Type"] = content_type
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


def _is_image_import_record(record: dict) -> bool:
    category = str(record.get("category", "image")).strip().lower()
    return category == "image"


def _image_import_records(data: dict) -> list[dict]:
    imports = (
        data.get("imports", []) if isinstance(data.get("imports", []), list) else []
    )
    return [
        item
        for item in imports
        if isinstance(item, dict) and _is_image_import_record(item)
    ]


def _extract_downloads_from_workflow(workflow: dict) -> list[dict[str, str]]:
    if not isinstance(workflow, dict):
        return []
    downloads: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    # Config node format (new DEFINED workflows): downloads string embedded in JSON.
    config_data = _parse_workflow_config_node(workflow)
    raw_value = str(config_data.get("downloads", "") or "").strip() if config_data else ""

    if not raw_value:
        # Fallback: legacy Downloads node (PrimitiveStringMultiline, title="Downloads").
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            if str(node.get("class_type", "")).strip() != "PrimitiveStringMultiline":
                continue
            meta = node.get("_meta", {}) if isinstance(node.get("_meta", {}), dict) else {}
            if str(meta.get("title", "")).strip().lower() != "downloads":
                continue
            inputs = (
                node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
            )
            raw_value = str(inputs.get("value", "") or "")
            break

    for raw_line in raw_value.splitlines():
        line = raw_line.strip()
        if not line or ";uri:" not in line:
            continue
        left, right = line.split(";uri:", 1)
        if ":" not in left:
            continue
        subfolder, filename = left.split(":", 1)
        entry = {
            "subfolder": str(subfolder or "").strip(),
            "filename": str(os.path.basename(filename or "")).strip(),
            "url": str(right or "").strip(),
        }
        key = (entry["subfolder"].lower(), entry["filename"].lower(), entry["url"])
        if not entry["filename"] or key in seen:
            continue
        seen.add(key)
        downloads.append(entry)
    return downloads


def _find_primitive_multiline_node_by_title(workflow: dict, title: str) -> dict | None:
    if not isinstance(workflow, dict):
        return None
    wanted = str(title or "").strip().lower()
    if not wanted:
        return None
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type", "")).strip() != "PrimitiveStringMultiline":
            continue
        meta = node.get("_meta", {}) if isinstance(node.get("_meta", {}), dict) else {}
        node_title = str(meta.get("title", "")).strip().lower()
        if node_title == wanted:
            return node
    return None


def _extract_image_from_workflow(workflow: dict) -> str:
    node = _find_primitive_multiline_node_by_title(workflow, "Image")
    if not isinstance(node, dict):
        return ""
    inputs = node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
    return _normalize_image_filename(inputs.get("value", ""))


def _sync_image_to_workflow(record: dict) -> None:
    if not isinstance(record, dict):
        return
    workflow = (
        record.get("workflow", {})
        if isinstance(record.get("workflow", {}), dict)
        else {}
    )
    node = _find_primitive_multiline_node_by_title(workflow, "Image")
    if not isinstance(node, dict):
        return
    annotation = (
        record.get("annotation", {})
        if isinstance(record.get("annotation", {}), dict)
        else {}
    )
    image_name = _normalize_image_filename(annotation.get("placeholderImage", ""))
    node_inputs = (
        node.setdefault("inputs", {})
        if isinstance(node.get("inputs", {}), dict)
        else {}
    )
    if not isinstance(node_inputs, dict):
        return
    node_inputs["value"] = f"{image_name}\n\n" if image_name else ""


def _normalize_annotation_downloads(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        subfolder = str(item.get("subfolder", "")).strip()
        filename = str(os.path.basename(str(item.get("filename", "") or ""))).strip()
        url = str(item.get("url", "")).strip()
        if not filename:
            continue
        key = (subfolder.lower(), filename.lower(), url)
        if key in seen:
            continue
        seen.add(key)
        result.append({"subfolder": subfolder, "filename": filename, "url": url})
    return result


def _normalize_annotation_loras(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        file_name = str(os.path.basename(str(item.get("fileName", "") or ""))).strip()
        if not file_name:
            continue
        key = file_name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "fileName": file_name,
                "name": str(item.get("name", "")).strip(),
                "triggerWords": str(item.get("triggerWords", "")).strip(),
                "uri": str(item.get("uri", "")).strip(),
                "classification": str(item.get("classification", "")).strip(),
                "notes": str(item.get("notes", "")).strip(),
            }
        )
    return result


def _normalize_annotation_optional_subgraphs(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        sg_id = str(item.get("id", "")).strip()
        if not sg_id or sg_id in seen:
            continue
        seen.add(sg_id)
        result.append(
            {
                "id": sg_id,
                # No display name survives the API-format import (that lives
                # only in the graph/UI format's subgraph node title) — default
                # to a comma list of what it actually contains, so the user
                # can tell what they're toggling before renaming it themselves.
                "label": str(item.get("label", "")).strip() or f"Optional part {sg_id}",
                "contains": str(item.get("contains", "")).strip(),
                "defaultEnabled": bool(item.get("defaultEnabled", True)),
            }
        )
    return result


def _default_optional_subgraphs_from_analysis(analysis: dict) -> list[dict[str, object]]:
    detected = analysis.get("optionalSubgraphs", [])
    if not isinstance(detected, list):
        return []
    result: list[dict[str, object]] = []
    for sg in detected:
        if not isinstance(sg, dict) or not sg.get("auto"):
            continue  # non-auto subgraphs need a manual bypass mapping first
        sg_id = str(sg.get("id", "")).strip()
        if not sg_id:
            continue
        labels = [str(l).strip() for l in sg.get("memberLabels", []) if str(l).strip()]
        result.append(
            {
                "id": sg_id,
                "label": f"Optional part {sg_id}",
                "contains": ", ".join(labels),
                "defaultEnabled": True,
            }
        )
    return result


def _build_default_annotation(record: dict) -> dict[str, object]:
    workflow = (
        record.get("workflow", {})
        if isinstance(record.get("workflow", {}), dict)
        else {}
    )
    analysis = (
        record.get("analysis", {})
        if isinstance(record.get("analysis", {}), dict)
        else {}
    )
    downloads = _normalize_annotation_downloads(analysis.get("downloads", []))
    if not downloads:
        downloads = _extract_downloads_from_workflow(workflow)
    loras = _normalize_annotation_loras(_extract_lora_catalog(workflow))
    image_name = _extract_image_from_workflow(workflow)
    optional_subgraphs = _default_optional_subgraphs_from_analysis(analysis)
    return {
        "downloads": downloads,
        "loras": loras,
        "placeholderImage": image_name,
        "optionalSubgraphs": optional_subgraphs,
        "updatedAt": "",
    }


def _normalize_annotation_payload(
    payload: object, current: dict[str, object] | None = None
) -> dict[str, object]:
    current = current if isinstance(current, dict) else {}
    output = {
        "downloads": _normalize_annotation_downloads(current.get("downloads", [])),
        "loras": _normalize_annotation_loras(current.get("loras", [])),
        "placeholderImage": _normalize_image_filename(
            current.get("placeholderImage", "")
        ),
        "optionalSubgraphs": _normalize_annotation_optional_subgraphs(
            current.get("optionalSubgraphs", [])
        ),
        "updatedAt": str(current.get("updatedAt", "") or "").strip(),
    }
    if not isinstance(payload, dict):
        return output

    if "downloads" in payload:
        output["downloads"] = _normalize_annotation_downloads(payload.get("downloads"))
    if "loras" in payload:
        output["loras"] = _normalize_annotation_loras(payload.get("loras"))
    if "placeholderImage" in payload:
        output["placeholderImage"] = _normalize_image_filename(
            payload.get("placeholderImage", "")
        )
    if "optionalSubgraphs" in payload:
        output["optionalSubgraphs"] = _normalize_annotation_optional_subgraphs(
            payload.get("optionalSubgraphs")
        )
    output["updatedAt"] = datetime.now(timezone.utc).isoformat()
    return output


@models_api_bp.get("/models/imports")
def list_imports():
    data = _ensure_registry()
    image_imports = _image_import_records(data)
    image_ids = {str(item.get("id", "")).strip() for item in image_imports}
    active_import_id = str(data.get("activeImportId", "")).strip()
    if active_import_id not in image_ids:
        active_import_id = (
            str(image_imports[0].get("id", "")).strip() if image_imports else ""
        )
    # Normalise activeImportIds: keep only valid image import ids, preserve order
    raw_active_ids = data.get("activeImportIds", [])
    if not isinstance(raw_active_ids, list):
        raw_active_ids = []
    active_import_ids = [i for i in raw_active_ids if i in image_ids]
    default_comfy = (
        str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip()
        or DEFAULT_COMFY_URL
    )
    queue_free = bool(
        data.get("settings", {}).get("queueFreeMemoryBetweenModels", False)
    )
    return jsonify(
        {
            "activeImportId": active_import_id or None,
            "activeImportIds": active_import_ids,
            "queueFreeMemoryBetweenModels": queue_free,
            "imports": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "createdAt": item.get("createdAt"),
                    "saveImageCount": item.get("analysis", {})
                    .get("detected", {})
                    .get("saveImageCount", 0),
                    "comfyApiUrl": str(item.get("comfyApiUrl", "")).strip()
                    or default_comfy,
                    "analysis": {
                        "detected": {
                            "hasImageInput": bool(
                                item.get("analysis", {})
                                .get("detected", {})
                                .get("hasImageInput", False)
                            ),
                            "loadImageNodeIds": item.get("analysis", {})
                            .get("detected", {})
                            .get("loadImageNodeIds", []),
                        }
                    },
                }
                for item in image_imports
            ],
        }
    )


@models_api_bp.get("/models/imports/<import_id>/workflow")
def export_import_workflow(import_id: str):
    data = _ensure_registry()
    record = next(
        (i for i in data.get("imports", []) if str(i.get("id", "")).strip() == import_id),
        None,
    )
    if record is None:
        return jsonify({"error": "Import not found"}), 404
    workflow = record.get("workflow")
    if not workflow:
        return jsonify({"error": "No workflow data for this import"}), 404
    import json
    name = re.sub(r'[^\w\-.]', '_', str(record.get("name", import_id)))
    payload = json.dumps(workflow, indent=2)
    resp = make_response(payload)
    resp.headers["Content-Type"] = "application/json"
    resp.headers["Content-Disposition"] = f'attachment; filename="{name}.json"'
    return resp


@models_api_bp.get("/models/imports/active")
def get_active_import():
    data = _ensure_registry()
    image_imports = _image_import_records(data)
    image_ids = {str(item.get("id", "")).strip() for item in image_imports}
    active_id = str(data.get("activeImportId", "")).strip()
    if active_id not in image_ids:
        active_id = str(image_imports[0].get("id", "")).strip() if image_imports else ""
    if not active_id:
        return jsonify({"active": None, "activeImportIds": []})
    record = next((item for item in image_imports if item.get("id") == active_id), None)
    if record is not None and _normalize_record_negative(record):
        _save_registry(data)
    active_ids = data.get("activeImportIds", [])
    if not isinstance(active_ids, list):
        active_ids = []
    active_records = [
        next((item for item in image_imports if item.get("id") == aid), None)
        for aid in active_ids
    ]
    active_records = [r for r in active_records if r is not None]
    # Backward-compat: if activeImportIds was never populated, always include
    # the primary active record so the frontend always gets at least one entry.
    if record is not None and not any(r.get("id") == active_id for r in active_records):
        active_records = [record] + active_records
    return jsonify(
        {
            "active": record,
            "activeImportIds": active_ids,
            "activeImports": active_records,
        }
    )


@models_api_bp.post("/models/imports/analyze")
def analyze_import():
    payload = request.get_json(silent=True) or {}
    try:
        workflow = _parse_workflow_payload(payload)
        analysis = _analyze_workflow(workflow)
    except Exception as exc:
        return jsonify({"error": f"invalid workflow: {exc}"}), 400
    # Surfaced so the import screen can ask for each LoRA's trigger words
    # while the user still has the workflow in front of them (#102). The same
    # catalog is what _build_annotation persists on save.
    analysis["loras"] = _normalize_annotation_loras(_extract_lora_catalog(workflow))
    return jsonify({"analysis": analysis})


@models_api_bp.post("/models/imports")
def save_import():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid JSON payload"}), 400

    name = str(payload.get("name", "")).strip()

    data = _ensure_registry()

    try:
        workflow = _parse_workflow_payload(payload)
        analysis = _analyze_workflow(workflow)
    except Exception as exc:
        return jsonify({"error": f"invalid workflow: {exc}"}), 400

    if not name:
        name = str(analysis.get("configNode", {}).get("name", "")).strip() or "Imported Workflow"
    if len(name) > MAX_IMPORT_NAME_LENGTH:
        return jsonify(
            {"error": f"name exceeds max length ({MAX_IMPORT_NAME_LENGTH})"}
        ), 400

    record_id = f"imp-{uuid.uuid4().hex[:8]}"
    category = str(payload.get("category", "image")).strip().lower() or "image"
    if category not in {"image", "upscale", "compose"}:
        category = "image"
    settings_default_comfy = (
        str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip()
        or DEFAULT_COMFY_URL
    )
    requested_comfy = (
        str(payload.get("comfyApiUrl", "")).strip() or settings_default_comfy
    )
    try:
        import_comfy_api_url = _safe_comfy_url(requested_comfy)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    record = {
        "id": record_id,
        "category": category,
        "name": name,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "comfyApiUrl": import_comfy_api_url,
        "workflow": workflow,
        "analysis": analysis,
        "basicValues": analysis.get("basicValues", {}),
        "advancedValues": {
            item["key"]: item["value"]
            for item in analysis.get("advancedParameters", [])
            if not bool(item.get("isLinked"))
        },
    }
    record["annotation"] = _build_default_annotation(record)

    data.setdefault("imports", []).append(record)
    if category == "image":
        # Add to active queue on first save as well
        active_ids = data.get("activeImportIds", [])
        if not isinstance(active_ids, list):
            active_ids = []
        if record_id not in active_ids:
            active_ids.append(record_id)
        data["activeImportIds"] = active_ids
        data["activeImportId"] = active_ids[0]
    _save_registry(data)

    return jsonify(
        {"import": record, "activeImportId": data.get("activeImportId")}
    ), 201


@models_api_bp.post("/models/imports/<import_id>/activate")
def activate_import(import_id: str):
    data = _ensure_registry()
    image_imports = _image_import_records(data)
    record = next((item for item in image_imports if item.get("id") == import_id), None)
    if record is None:
        return jsonify({"error": "image import not found"}), 404

    # Add to activeImportIds list (no duplicates, preserve order)
    active_ids = data.get("activeImportIds", [])
    if not isinstance(active_ids, list):
        active_ids = []
    if import_id not in active_ids:
        active_ids.append(import_id)
    data["activeImportIds"] = active_ids
    # Keep singular field = first of the list for backward compatibility
    data["activeImportId"] = active_ids[0] if active_ids else import_id
    _save_registry(data)
    return jsonify(
        {
            "active": record,
            "activeImportId": data["activeImportId"],
            "activeImportIds": active_ids,
        }
    )


@models_api_bp.delete("/models/imports/<import_id>/activate")
def deactivate_import(import_id: str):
    data = _ensure_registry()
    active_ids = data.get("activeImportIds", [])
    if not isinstance(active_ids, list):
        active_ids = []
    active_ids = [i for i in active_ids if i != import_id]
    data["activeImportIds"] = active_ids
    data["activeImportId"] = active_ids[0] if active_ids else None
    _save_registry(data)
    return jsonify(
        {"activeImportId": data["activeImportId"], "activeImportIds": active_ids}
    )


@models_api_bp.get("/models/imports/<import_id>")
def get_import(import_id: str):
    data = _ensure_registry()
    record = next(
        (item for item in data.get("imports", []) if item.get("id") == import_id), None
    )
    if record is None:
        return jsonify({"error": "import not found"}), 404
    if not isinstance(record.get("annotation"), dict):
        record["annotation"] = _build_default_annotation(record)
        _save_registry(data)
    return jsonify({"import": record})


@models_api_bp.put("/models/imports/<import_id>")
def update_import(import_id: str):
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid JSON payload"}), 400

    name = str(payload.get("name", "")).strip() or "Imported Workflow"
    if len(name) > MAX_IMPORT_NAME_LENGTH:
        return jsonify(
            {"error": f"name exceeds max length ({MAX_IMPORT_NAME_LENGTH})"}
        ), 400

    data = _ensure_registry()
    record = next(
        (item for item in data.get("imports", []) if item.get("id") == import_id), None
    )
    if record is None:
        return jsonify({"error": "import not found"}), 404

    try:
        workflow = _parse_workflow_payload(payload)
        analysis = _analyze_workflow(workflow)
    except Exception as exc:
        return jsonify({"error": f"invalid workflow: {exc}"}), 400

    settings_default_comfy = (
        str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip()
        or DEFAULT_COMFY_URL
    )
    requested_comfy = (
        str(payload.get("comfyApiUrl", "")).strip() or settings_default_comfy
    )
    try:
        import_comfy_api_url = _safe_comfy_url(requested_comfy)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    record["name"] = name
    record["comfyApiUrl"] = import_comfy_api_url
    record["workflow"] = workflow
    record["analysis"] = analysis
    record["basicValues"] = analysis.get("basicValues", {})
    record["advancedValues"] = {
        item["key"]: item["value"]
        for item in analysis.get("advancedParameters", [])
        if not bool(item.get("isLinked"))
    }
    if not isinstance(record.get("annotation"), dict):
        record["annotation"] = _build_default_annotation(record)
    _save_registry(data)
    return jsonify({"import": record})


@models_api_bp.get("/models/imports/<import_id>/annotations")
def get_import_annotations(import_id: str):
    data = _ensure_registry()
    record = next(
        (item for item in data.get("imports", []) if item.get("id") == import_id), None
    )
    if record is None:
        return jsonify({"error": "import not found"}), 404

    annotation = record.get("annotation")
    if not isinstance(annotation, dict):
        annotation = _build_default_annotation(record)
        record["annotation"] = annotation
        _save_registry(data)
    else:
        annotation = _normalize_annotation_payload({}, annotation)

    settings = (
        data.get("settings", {}) if isinstance(data.get("settings", {}), dict) else {}
    )
    fields = (
        settings.get("workflowAnnotateFields")
        if isinstance(settings.get("workflowAnnotateFields"), dict)
        else {}
    )

    return jsonify(
        {
            "importId": import_id,
            "annotation": annotation,
            "fields": {
                "downloads": fields.get("downloads", ["subfolder", "filename", "url"]),
                "loras": fields.get(
                    "loras", ["fileName", "name", "triggerWords", "uri", "notes"]
                ),
            },
        }
    )


@models_api_bp.patch("/models/imports/<import_id>/annotations")
def update_import_annotations(import_id: str):
    payload = request.get_json(silent=True) or {}
    data = _ensure_registry()
    record = next(
        (item for item in data.get("imports", []) if item.get("id") == import_id), None
    )
    if record is None:
        return jsonify({"error": "import not found"}), 404

    current = (
        record.get("annotation")
        if isinstance(record.get("annotation"), dict)
        else _build_default_annotation(record)
    )
    record["annotation"] = _normalize_annotation_payload(payload, current)
    _sync_image_to_workflow(record)
    _save_registry(data)
    return jsonify({"importId": import_id, "annotation": record["annotation"]})


@models_api_bp.delete("/models/imports/<import_id>")
def delete_import(import_id: str):
    data = _ensure_registry()
    imports = data.get("imports", [])
    kept = [item for item in imports if item.get("id") != import_id]
    if len(kept) == len(imports):
        return jsonify({"error": "import not found"}), 404

    data["imports"] = kept
    # Remove from active lists
    active_ids = data.get("activeImportIds", [])
    if isinstance(active_ids, list):
        data["activeImportIds"] = [i for i in active_ids if i != import_id]
    if data.get("activeImportId") == import_id:
        image_kept = _image_import_records(data)
        remaining = data.get("activeImportIds", [])
        data["activeImportId"] = (
            remaining[0]
            if remaining
            else (image_kept[0].get("id") if image_kept else None)
        )

    _save_registry(data, deleted_import_ids={import_id})
    return jsonify(
        {
            "ok": True,
            "activeImportId": data.get("activeImportId"),
            "activeImportIds": data.get("activeImportIds", []),
            "imports": data.get("imports", []),
        }
    )


@models_api_bp.patch("/models/imports/<import_id>/values")
def update_import_values(import_id: str):
    payload = request.get_json(silent=True) or {}
    basic_values = payload.get("basicValues", {})
    advanced_values = payload.get("advancedValues", {})
    comfy_api_url = payload.get("comfyApiUrl")
    new_name = payload.get("name")

    data = _ensure_registry()
    record = next(
        (item for item in data.get("imports", []) if item.get("id") == import_id), None
    )
    if record is None:
        return jsonify({"error": "import not found"}), 404

    if isinstance(basic_values, dict):
        record.setdefault("basicValues", {}).update(basic_values)
    if isinstance(advanced_values, dict):
        filtered_advanced_values = {
            str(key): value
            for key, value in advanced_values.items()
            if isinstance(key, str)
            and "." in key
            and not (
                isinstance(value, str)
                and value.strip().startswith("[")
                and value.strip().endswith("]")
            )
        }
        lora_request_values = {
            str(key): value
            for key, value in filtered_advanced_values.items()
            if "lora_name" in str(key)
            or "strength_model" in str(key)
            or "strength_clip" in str(key)
            or "__lora_chain" in str(key)
        }
        if lora_request_values:
            logger.info(
                "[LoRA][PATCH /values] request import=%s values=%s",
                import_id,
                lora_request_values,
            )
        workflow = (
            record.get("workflow", {})
            if isinstance(record.get("workflow", {}), dict)
            else {}
        )
        try:
            _validate_clip_last_layer_advanced_values(
                workflow, filtered_advanced_values
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        record.setdefault("advancedValues", {}).update(filtered_advanced_values)
        saved_advanced = (
            record.get("advancedValues", {})
            if isinstance(record.get("advancedValues", {}), dict)
            else {}
        )
        lora_saved_values = {
            str(key): saved_advanced.get(str(key)) for key in lora_request_values.keys()
        }
        if lora_saved_values:
            logger.info(
                "[LoRA][PATCH /values] saved import=%s values=%s",
                import_id,
                lora_saved_values,
            )

    if new_name is not None:
        name_str = str(new_name).strip()
        if not name_str:
            return jsonify({"error": "name cannot be empty"}), 400
        if len(name_str) > MAX_IMPORT_NAME_LENGTH:
            return jsonify(
                {"error": f"name exceeds max length ({MAX_IMPORT_NAME_LENGTH})"}
            ), 400
        record["name"] = name_str

    if comfy_api_url is not None:
        try:
            record["comfyApiUrl"] = _safe_comfy_url(str(comfy_api_url))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    _save_registry(data)
    return jsonify({"import": record})


@models_api_bp.get("/models/imports/<import_id>/requirements")
def get_import_requirements(import_id: str):
    data = _ensure_registry()
    record = next(
        (item for item in data.get("imports", []) if item.get("id") == import_id), None
    )
    if record is None:
        return jsonify({"error": "import not found"}), 404
    workflow = (
        record.get("workflow", {})
        if isinstance(record.get("workflow", {}), dict)
        else {}
    )
    files = _extract_model_files(workflow)
    return jsonify({"files": files})


@models_api_bp.get("/models/imports/<import_id>/param-options")
def get_import_param_options(import_id: str):
    """Return string-enum options for every advancedParameter in a workflow.

    Makes a single call to ComfyUI /object_info and extracts the valid values
    for each string-type parameter (sampler_name, scheduler, ckpt_name, etc.).

    Response:
        { "options": { "<nodeId>.<inputKey>": ["opt1", "opt2", ...], ... } }
    """
    data = _ensure_registry()
    record = next(
        (item for item in data.get("imports", []) if item.get("id") == import_id), None
    )
    if record is None:
        return jsonify({"error": "import not found"}), 404

    analysis = (
        record.get("analysis", {})
        if isinstance(record.get("analysis", {}), dict)
        else {}
    )
    advanced_params = analysis.get("advancedParameters", [])
    if not isinstance(advanced_params, list):
        advanced_params = []

    # Only process params whose default value is a string (these may have enum options)
    string_params = [p for p in advanced_params if isinstance(p.get("value"), str)]
    if not string_params:
        return jsonify({"options": {}})

    comfy_api_url = (
        str(record.get("comfyApiUrl", "")).strip()
        or str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip()
    )
    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
        object_info = http_json(f"{comfy_api_url}/object_info", timeout=20)
    except Exception:
        logger.exception(
            "Failed to load object_info for param-options import '%s'", import_id
        )
        return jsonify({"options": {}})

    result: dict[str, list[str]] = {}
    advanced_values = (
        record.get("advancedValues", {})
        if isinstance(record.get("advancedValues", {}), dict)
        else {}
    )
    workflow = (
        record.get("workflow", {})
        if isinstance(record.get("workflow", {}), dict)
        else {}
    )

    for param in string_params:
        key = str(param.get("key", "")).strip()
        node_class = str(param.get("nodeClass", "")).strip()
        input_key = str(param.get("inputKey", "")).strip()
        if not key or not node_class or not input_key:
            continue

        node_info = (
            object_info.get(node_class, {}) if isinstance(object_info, dict) else {}
        )
        if not isinstance(node_info, dict):
            continue
        input_spec = node_info.get("input", {})
        if not isinstance(input_spec, dict):
            continue

        options: list[str] | None = None
        for spec_section in ("required", "optional"):
            section = input_spec.get(spec_section, {})
            if not isinstance(section, dict):
                continue
            input_def = section.get(input_key)
            # ComfyUI format: [["opt1", "opt2", ...], {metadata}]
            if (
                isinstance(input_def, list)
                and len(input_def) > 0
                and isinstance(input_def[0], list)
            ):
                options = [str(o) for o in input_def[0] if isinstance(o, str)]
                break

        if not options:
            continue

        # Determine the currently selected value (advancedValues → workflow node → param default)
        current = str(advanced_values.get(key, "")).strip()
        if not current and "." in key:
            node_id, inp_key = key.split(".", 1)
            node_inputs = (
                workflow.get(node_id, {}).get("inputs", {})
                if isinstance(workflow.get(node_id, {}), dict)
                else {}
            )
            current = str(node_inputs.get(inp_key, "")).strip()
        if not current:
            current = str(param.get("value", "")).strip()

        # Ensure current value appears first in the list
        if current and current not in options:
            options = [current, *options]

        # Allow bypassing the LoRA node (sets strengths to 0)
        if input_key == "lora_name":
            options = ["__bypass__", *[o for o in options if o != "__bypass__"]]

        result[key] = options

    return jsonify({"options": result})


@models_api_bp.get("/models/imports/<import_id>/checkpoints")
def list_import_checkpoints(import_id: str):
    data = _ensure_registry()
    record = next(
        (item for item in data.get("imports", []) if item.get("id") == import_id), None
    )
    if record is None:
        return jsonify({"error": "import not found"}), 404

    workflow = (
        record.get("workflow", {})
        if isinstance(record.get("workflow", {}), dict)
        else {}
    )
    checkpoint_keys = _extract_checkpoint_loader_keys(workflow)
    clip_skip_keys = _extract_clip_last_layer_keys(workflow)
    if not checkpoint_keys:
        return jsonify({"checkpoints": [], "selected": "", "advancedKeys": [], "clipSkipAdvancedKeys": clip_skip_keys})

    comfy_api_url = (
        str(record.get("comfyApiUrl", "")).strip()
        or str(data.get("settings", {}).get("comfyApiUrl", "")).strip()
    )
    if not comfy_api_url:
        return jsonify(
            {"checkpoints": [], "selected": "", "advancedKeys": checkpoint_keys,
             "clipSkipAdvancedKeys": clip_skip_keys}
        )

    try:
        comfy_api_url = _safe_comfy_url(comfy_api_url)
    except ValueError:
        return jsonify(
            {"checkpoints": [], "selected": "", "advancedKeys": checkpoint_keys,
             "clipSkipAdvancedKeys": clip_skip_keys}
        )

    options: list[str] = []
    try:
        object_info = http_json(f"{comfy_api_url}/object_info", timeout=20)
        options = _extract_checkpoint_options_from_object_info(object_info)
    except Exception:
        logger.exception("Failed to load checkpoint options for import '%s'", import_id)
        options = []

    advanced_values = (
        record.get("advancedValues", {})
        if isinstance(record.get("advancedValues", {}), dict)
        else {}
    )
    selected = ""
    for key in checkpoint_keys:
        candidate = str(advanced_values.get(key, "")).strip()
        if candidate:
            selected = candidate
            break

    if not selected:
        for composite_key in checkpoint_keys:
            if "." not in composite_key:
                continue
            node_id, input_key = composite_key.split(".", 1)
            inputs = (
                workflow.get(node_id, {}).get("inputs", {})
                if isinstance(workflow.get(node_id, {}), dict)
                else {}
            )
            candidate = str(inputs.get(input_key, "")).strip()
            if candidate:
                selected = candidate
                break

    if selected and selected not in options:
        options = [selected, *options]

    return jsonify(
        {"checkpoints": options, "selected": selected,
         "advancedKeys": checkpoint_keys, "clipSkipAdvancedKeys": clip_skip_keys}
    )


@models_api_bp.get("/models/imports/<import_id>/loras")
def list_import_loras(import_id: str):
    data = _ensure_registry()
    record = next(
        (item for item in data.get("imports", []) if item.get("id") == import_id), None
    )
    if record is None:
        return jsonify({"error": "import not found"}), 404

    workflow = (
        record.get("workflow", {})
        if isinstance(record.get("workflow", {}), dict)
        else {}
    )
    lora_keys = _extract_lora_loader_keys(workflow)
    lora_catalog = _extract_lora_catalog(workflow)
    verified_loras = [
        str(item.get("fileName", "")).strip()
        for item in lora_catalog
        if str(item.get("fileName", "")).strip()
    ]

    advanced_values = (
        record.get("advancedValues", {})
        if isinstance(record.get("advancedValues", {}), dict)
        else {}
    )
    selected: dict[str, str] = {}
    for key in lora_keys:
        candidate = str(advanced_values.get(key, "")).strip()
        if not candidate and "." in key:
            node_id, input_key = key.split(".", 1)
            inputs = (
                workflow.get(node_id, {}).get("inputs", {})
                if isinstance(workflow.get(node_id, {}), dict)
                else {}
            )
            raw_candidate = inputs.get(input_key, "")
            if (
                isinstance(raw_candidate, list)
                and raw_candidate
                and isinstance(raw_candidate[0], str)
            ):
                candidate = str(
                    _resolve_text_from_node(workflow, str(raw_candidate[0]))
                ).strip()
            else:
                candidate = str(raw_candidate).strip()
        selected[key] = candidate

    logger.info(
        "[LoRA][GET /loras] import=%s keys=%s selected=%s",
        import_id,
        lora_keys,
        selected,
    )

    options: list[str] = []
    comfy_api_url = (
        str(record.get("comfyApiUrl", "")).strip()
        or str(data.get("settings", {}).get("comfyApiUrl", "")).strip()
    )
    if comfy_api_url:
        try:
            comfy_api_url = _safe_comfy_url(comfy_api_url)
            object_info = http_json(f"{comfy_api_url}/object_info", timeout=20)
            options = _extract_lora_options_from_object_info(object_info)
        except Exception:
            logger.exception("Failed to load LoRA options for import '%s'", import_id)
            options = []

    for current in selected.values():
        if current and current not in options:
            options = [current, *options]

    # Keep curated workflow LoRAs as a dedicated priority group in the UI.
    options_lower = {str(item).strip().lower() for item in options if str(item).strip()}
    for current in selected.values():
        candidate = str(current).strip()
        if (
            candidate
            and candidate.lower() not in options_lower
            and candidate.lower() not in {x.lower() for x in verified_loras}
        ):
            verified_loras.append(candidate)

    catalog_by_file: dict[str, dict[str, str]] = {}
    for entry in lora_catalog:
        file_name = os.path.basename(str(entry.get("fileName", "")).strip())
        if not file_name:
            continue
        catalog_by_file[file_name.lower()] = {
            "fileName": file_name,
            "name": str(entry.get("name", "")).strip(),
            "triggerWords": str(entry.get("triggerWords", "")).strip(),
            "uri": str(entry.get("uri", "")).strip(),
            "classification": str(entry.get("classification", "")).strip(),
            "imageUrl": "",
        }

    ordered_catalog: list[dict[str, str]] = []
    for file_name in verified_loras:
        key = str(file_name or "").strip().lower()
        if key in catalog_by_file:
            ordered_catalog.append(catalog_by_file[key])

    for option_name in options:
        full_path = str(option_name or "").strip()
        if not full_path:
            continue
        base_name = os.path.basename(full_path)
        key = base_name.lower() if base_name else full_path.lower()
        # De-duplicate using basename key so path-prefixed and bare names don't collide.
        if any(
            str(item.get("fileName", "")).strip().lower() == key
            for item in ordered_catalog
        ):
            continue
        ordered_catalog.append(
            catalog_by_file.get(
                key,
                {
                    "fileName": base_name or full_path,
                    "name": "",
                    "triggerWords": "",
                    "uri": "",
                    "classification": "",
                    "imageUrl": "",
                },
            )
        )

    # Prioritize currently selected LoRAs so their preview/info is always enriched first.
    selected_priority: set[str] = set()
    for current in selected.values():
        base = os.path.basename(str(current or "").strip())
        if base:
            selected_priority.add(base.lower())

    if selected_priority:
        ordered_catalog.sort(
            key=lambda item: (
                0
                if str(item.get("fileName", "")).strip().lower() in selected_priority
                else 1
            )
        )

    if not options and verified_loras:
        options = list(verified_loras)

    # Normalize all option paths to basename so the frontend select values
    # match the catalog keys (which are always basenames).
    options_normalized: list[str] = []
    options_norm_seen: set[str] = set()
    for opt in options:
        base = os.path.basename(str(opt or "").strip())
        if not base:
            continue
        key = base.lower()
        if key in options_norm_seen:
            continue
        options_norm_seen.add(key)
        options_normalized.append(base)
    options = options_normalized

    return jsonify(
        {
            "loras": options,
            "verifiedLoras": verified_loras,
            "loraCatalog": ordered_catalog,
            "selected": selected,
            "advancedKeys": lora_keys,
        }
    )


@models_api_bp.get("/models/imports/<import_id>/loras/details")
def get_import_lora_details(import_id: str):
    data = _ensure_registry()
    record = next(
        (item for item in data.get("imports", []) if item.get("id") == import_id), None
    )
    if record is None:
        return jsonify({"error": "import not found"}), 404

    lora_name_raw = str(request.args.get("lora", "")).strip()
    lora_name = os.path.basename(lora_name_raw)
    if not lora_name:
        return jsonify({"error": "lora query parameter is required"}), 400

    workflow = (
        record.get("workflow", {})
        if isinstance(record.get("workflow", {}), dict)
        else {}
    )
    lora_catalog = _extract_lora_catalog(workflow)

    entry = None
    lora_key = lora_name.lower()
    for item in lora_catalog:
        candidate = os.path.basename(str(item.get("fileName", "")).strip())
        if candidate and candidate.lower() == lora_key:
            entry = {
                "fileName": candidate,
                "name": str(item.get("name", "")).strip(),
                "triggerWords": str(item.get("triggerWords", "")).strip(),
                "uri": str(item.get("uri", "")).strip(),
                "classification": str(item.get("classification", "")).strip(),
                "imageUrl": "",
            }
            break

    if entry is None:
        entry = {
            "fileName": lora_name,
            "name": "",
            "triggerWords": "",
            "uri": "",
            "classification": "",
            "imageUrl": "",
        }

    uri = str(entry.get("uri", "")).strip()
    if uri and "civitai.com" in uri.lower():
        details = _extract_civitai_details(uri, {})
        if not str(entry.get("imageUrl", "")).strip():
            entry["imageUrl"] = str(details.get("imageUrl", "")).strip()
        if not str(entry.get("name", "")).strip():
            entry["name"] = str(details.get("name", "")).strip()
        if not str(entry.get("triggerWords", "")).strip():
            entry["triggerWords"] = str(details.get("triggerWords", "")).strip()
        if not str(entry.get("classification", "")).strip():
            entry["classification"] = str(details.get("classification", "")).strip()

    logger.warning(
        "[LoRA][GET /loras/details] import=%s lora=%s response=%s",
        import_id,
        lora_name,
        entry,
    )

    return jsonify({"lora": entry})


def _resolve_comfy_models_folder() -> str:
    data = _ensure_registry()
    return str(data.get("settings", {}).get("comfyModelsFolder", "")).strip()


def _resolve_download_target_path(subfolder: str, filename: str) -> "Path | None":
    base = _resolve_comfy_models_folder()
    filename = str(filename or "").strip()
    if not base or not filename:
        return None
    base = base.replace("\\", "/")
    parts = [p for p in re.split(r"[\\/]+", str(subfolder or "").strip()) if p]
    return Path(base).joinpath(*parts, filename)


# Resolved lookups, keyed by file hash. The hash itself is cheap (218 MiB in
# ~0.2s) but the CivitAI round-trip isn't, and the same LoRA gets asked about
# every time an import screen opens.
_CIVITAI_HASH_CACHE: dict[str, dict[str, Any]] = {}


def _find_lora_file(filename: str) -> "Path | None":
    """Locate a LoRA anywhere under the models folder's `loras` tree."""
    base = _resolve_comfy_models_folder()
    filename = str(filename or "").strip()
    if not base or not filename:
        return None
    root = Path(base.replace("\\", "/")) / "loras"
    if not root.is_dir():
        return None
    direct = root / filename
    if direct.is_file():
        return direct
    needle = filename.lower()
    for candidate in root.rglob("*"):
        if candidate.is_file() and candidate.name.lower() == needle:
            return candidate
    return None


def _sha256_file(path: Path) -> str:
    """SHA-256 of a file's contents, uppercase.

    This is what makes the lookup work at all: SHA-256 is a public standard,
    so the digest computed here is byte-for-byte the one CivitAI stored when
    the file was uploaded. It identifies a model by *content*, which means a
    renamed or manually-placed file is still recognised — exactly the case
    that has no other trace to go on.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


@models_api_bp.post("/models/imports/loras/civitai-lookup")
def lookup_loras_on_civitai():
    """Identify local LoRA files on CivitAI by hash and return their metadata.

    A LoRA that arrived as a loose file carries no provenance: no download
    URI, and — more importantly — no trigger words, without which it quietly
    underperforms (#102). Looking it up by content recovers both, and works
    even when the file was renamed.

    Body: {"loras": ["krea2/some_lora.safetensors", ...]} — the same
    `lora_name` values the workflow uses, subfolder included.
    """
    payload = request.get_json(silent=True) or {}
    names = payload.get("loras", [])
    if not isinstance(names, list):
        return jsonify({"error": "loras must be a list"}), 400

    results: dict[str, dict[str, Any]] = {}
    for raw_name in names[:32]:
        name = str(raw_name or "").strip()
        if not name:
            continue
        parts = [p for p in re.split(r"[\\/]+", name) if p]
        filename = parts[-1]
        subfolder = "/".join(["loras", *parts[:-1]])
        target = _resolve_download_target_path(subfolder, filename)
        if not target or not target.is_file():
            # Callers don't agree on whether the subfolder travels with the
            # name: the workflow says "krea2/foo.safetensors" but the stored
            # annotation keeps the base name only. Search the LoRA tree for
            # the file rather than making the caller get the path right.
            target = _find_lora_file(filename)
        if not target:
            results[name] = {
                "found": False,
                "error": "file not found in the models folder",
            }
            continue
        try:
            file_hash = _sha256_file(target)
        except Exception as exc:
            results[name] = {"found": False, "error": f"could not hash: {exc}"}
            continue

        if file_hash in _CIVITAI_HASH_CACHE:
            results[name] = _CIVITAI_HASH_CACHE[file_hash]
            continue

        try:
            data = http_json(
                f"https://civitai.com/api/v1/model-versions/by-hash/{file_hash}",
                timeout=25,
            )
        except Exception as exc:
            # Not on CivitAI, or unreachable. Either way the user can still
            # type the words by hand — this is a shortcut, not a gate.
            results[name] = {"found": False, "hash": file_hash, "error": str(exc)[:160]}
            continue

        words = data.get("trainedWords")
        model = data.get("model") if isinstance(data.get("model"), dict) else {}
        download_url = ""
        for entry in data.get("files") or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("name", "")).lower() == filename.lower():
                download_url = str(entry.get("downloadUrl", "") or "")
                break
        model_id = data.get("modelId")
        resolved = {
            "found": True,
            "hash": file_hash,
            # An empty list is a real answer — this LoRA genuinely has no
            # trigger words — and must not read as "lookup failed".
            "triggerWords": ", ".join(
                str(w).strip() for w in words if str(w).strip()
            ) if isinstance(words, list) else "",
            "modelName": str(model.get("name", "") or ""),
            "versionName": str(data.get("name", "") or ""),
            "modelPage": f"https://civitai.com/models/{model_id}" if model_id else "",
            "downloadUrl": download_url,
        }
        _CIVITAI_HASH_CACHE[file_hash] = resolved
        results[name] = resolved

    return jsonify({"results": results})


@models_api_bp.post("/models/imports/check-files")
def check_files_exist():
    """Check which files in a list already exist in the models folder."""
    payload = request.get_json(silent=True) or {}
    files = payload.get("files", [])
    if not isinstance(files, list):
        return jsonify({"error": "files must be a list"}), 400

    exists: dict[str, bool] = {}
    base = _resolve_comfy_models_folder()
    if base:
        for item in files:
            if not isinstance(item, dict):
                continue
            subfolder = str(item.get("subfolder", "")).strip()
            filename = str(item.get("filename", "")).strip()
            if not filename:
                continue
            key = f"{subfolder}/{filename}"
            target = _resolve_download_target_path(subfolder, filename)
            exists[key] = bool(target and target.is_file())

    return jsonify({"exists": exists})


def _is_civitai(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return host == "civitai.com" or host.endswith(".civitai.com")


@models_api_bp.post("/models/imports/download-file")
def download_import_file():
    """Existence check (non-force) or streaming download (force) of a single model file
    into the configured ComfyUI models folder.
    """
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()
    subfolder = str(payload.get("subfolder", "")).strip()
    filename = str(payload.get("filename", "")).strip()
    force = bool(payload.get("force"))

    if not url or not filename:
        return jsonify({"error": "url and filename are required"}), 400

    base = _resolve_comfy_models_folder()
    if not base:
        return jsonify({"error": "ComfyUI Models Folder is not configured. Set it in Settings → ComfyUI."}), 400

    target = _resolve_download_target_path(subfolder, filename)
    if target is None:
        return jsonify({"error": "Could not resolve destination path."}), 400

    if not force:
        return jsonify({"exists": target.is_file(), "path": str(target)})

    settings = _ensure_registry().get("settings", {})

    def generate():
        import json as _json
        from urllib.error import HTTPError, URLError
        from urllib.request import Request, urlopen

        tmp_path = target.with_name(target.name + ".part")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            # CivitAI answers 401 to anyone without a key, and several LoRAs
            # are published nowhere else. The key is the user's own (Settings).
            if _is_civitai(url):
                key = str(settings.get("civitaiApiKey", "") or "").strip()
                if not key:
                    yield _json.dumps({"error": "CivitAI needs an API key to download this file. "
                                                "Add yours in Settings (CivitAI account)."}) + "\n"
                    return
                headers["Authorization"] = f"Bearer {key}"
            req = Request(url=url, headers=headers, method="GET")
            with urlopen(req, timeout=60) as resp:
                kind = str(resp.headers.get("Content-Type") or "").lower()
                # A login page or an error document instead of the model: say
                # so, rather than writing HTML into a .safetensors.
                if kind.startswith("text/") or "json" in kind:
                    detail = resp.read(400).decode("utf-8", "replace").strip()
                    yield _json.dumps({"error": ("The server sent a page instead of the file"
                                                 + (" — check your CivitAI API key." if _is_civitai(url) else ".")
                                                 + " " + detail[:200])}) + "\n"
                    return
                total_header = resp.headers.get("Content-Length")
                total = int(total_header) if total_header and total_header.isdigit() else 0
                downloaded = 0
                last_pct = -1
                with open(tmp_path, "wb") as fh:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = int(downloaded * 100 / total)
                            if pct != last_pct:
                                last_pct = pct
                                yield _json.dumps({"progress": pct}) + "\n"
            tmp_path.replace(target)
            yield _json.dumps({"ok": True, "path": str(target), "progress": 100}) + "\n"
        except (URLError, HTTPError, OSError) as exc:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            yield _json.dumps({"error": str(exc)}) + "\n"
        except Exception as exc:  # pragma: no cover - safety net
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            yield _json.dumps({"error": str(exc)}) + "\n"

    return Response(generate(), mimetype="application/x-ndjson")