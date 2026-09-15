from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from flask import jsonify, request

from app import paths
from app.routes.models_api_shared import models_api_bp

logger = logging.getLogger(__name__)

_LIBRARY_FLOWS_PATH = paths.data_file("library_flows.json")
_library_flows_cache: list[dict] | None = None


def _load_library_flows() -> list[dict]:
    global _library_flows_cache
    if _library_flows_cache is not None:
        return _library_flows_cache
    try:
        data = json.loads(_LIBRARY_FLOWS_PATH.read_text(encoding="utf-8"))
        _library_flows_cache = data if isinstance(data, list) else []
    except Exception:
        _library_flows_cache = []
    return _library_flows_cache


def _save_library_flows(items: list[dict]) -> None:
    global _library_flows_cache
    _LIBRARY_FLOWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_LIBRARY_FLOWS_PATH, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)
    _library_flows_cache = items


@models_api_bp.get("/library/flows")
def get_library_flows():
    return jsonify({"flows": _load_library_flows()})


@models_api_bp.post("/library/flows")
def create_library_flow():
    payload = request.get_json(silent=True) or {}
    flow_type = str(payload.get("type", "") or "").strip()
    if not flow_type:
        return jsonify({"error": "type is required"}), 400

    entry = {
        "id": uuid.uuid4().hex,
        "type": flow_type,
        "label": str(payload.get("label", "") or flow_type).strip(),
        "prompt": str(payload.get("prompt", "") or "").strip(),
        "data": payload.get("data") if isinstance(payload.get("data"), dict) else {},
        "savedAt": int(time.time() * 1000),
    }

    items = _load_library_flows()
    items.insert(0, entry)
    _save_library_flows(items)
    return jsonify({"ok": True, "flow": entry}), 201


@models_api_bp.delete("/library/flows/<flow_id>")
def delete_library_flow(flow_id: str):
    items = _load_library_flows()
    filtered = [it for it in items if str(it.get("id")) != flow_id]
    if len(filtered) == len(items):
        return jsonify({"error": "Flow not found"}), 404
    _save_library_flows(filtered)
    return jsonify({"ok": True})
