"""Depot CRUD — a named, private set of backgrounds/characters/images/flows
tied to one story/idea (see library.js's CATEGORIES 'depot' entry and
services/depot_service.py). Always scoped to the active viewer; there is no
shared/global depot."""

from __future__ import annotations

from flask import jsonify, request, session

from app.routes.models_api_shared import _active_viewer_id, models_api_bp
from app.services import depot_service

# Which depot "Send to Depot" (on a generation result card) targets — a
# separate session key from _active_viewer_id's, since switching depots
# shouldn't require re-logging in as a viewer. Cleared whenever the viewer
# switches (viewers_routes.py) would be nice but isn't required for
# correctness: _active_depot_id() below re-validates ownership on every
# read, so a stale id from a previous viewer just resolves to None.
_ACTIVE_DEPOT_SESSION_KEY = "active_depot_id"


def _active_depot_id() -> str | None:
    viewer_id = _active_viewer_id()
    depot_id = session.get(_ACTIVE_DEPOT_SESSION_KEY)
    if not depot_id or not viewer_id:
        return None
    if depot_service.get_depot(depot_id, viewer_id) is None:
        return None
    return depot_id


@models_api_bp.get("/depots")
def list_depots():
    viewer_id = _active_viewer_id()
    return jsonify({"depots": depot_service.list_depots(viewer_id)})


@models_api_bp.post("/depots")
def create_depot():
    viewer_id = _active_viewer_id()
    body = request.get_json(silent=True) or {}
    try:
        depot = depot_service.create_depot(body, viewer_id)
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400
    return jsonify({"ok": True, "depot": depot})


@models_api_bp.get("/depots/active")
def get_active_depot():
    viewer_id = _active_viewer_id()
    depot_id = _active_depot_id()
    depot = depot_service.get_depot(depot_id, viewer_id) if depot_id else None
    return jsonify({"depot": depot})


@models_api_bp.post("/depots/active/items")
def add_active_depot_item():
    """'Send to Depot' from a generation result card — attaches the image to
    whichever depot is currently active, classified as the category the
    user picked (character/background/asset)."""
    viewer_id = _active_viewer_id()
    depot_id = _active_depot_id()
    if not depot_id:
        return jsonify({"ok": False, "error": "No active Depot"}), 400
    body = request.get_json(silent=True) or {}
    category = str(body.get("category") or "").strip().lower()
    url = str(body.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "url is required"}), 400
    item = depot_service.add_item(
        depot_id,
        viewer_id,
        category,
        url,
        body.get("caption") or "",
        body.get("sourceUrl") or "",
    )
    if item is None:
        return jsonify({"ok": False, "error": "Invalid category or depot"}), 400
    return jsonify({"ok": True, "item": item})


@models_api_bp.post("/depots/<depot_id>/activate")
def activate_depot(depot_id: str):
    viewer_id = _active_viewer_id()
    if depot_service.get_depot(depot_id, viewer_id) is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    session[_ACTIVE_DEPOT_SESSION_KEY] = depot_id
    return jsonify({"ok": True, "activeDepotId": depot_id})


@models_api_bp.post("/depots/deactivate")
def deactivate_depot():
    session.pop(_ACTIVE_DEPOT_SESSION_KEY, None)
    return jsonify({"ok": True})


@models_api_bp.get("/depots/<depot_id>")
def get_depot(depot_id: str):
    viewer_id = _active_viewer_id()
    depot = depot_service.get_depot(depot_id, viewer_id)
    if depot is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "depot": depot})


@models_api_bp.patch("/depots/<depot_id>")
def update_depot(depot_id: str):
    viewer_id = _active_viewer_id()
    patch = request.get_json(silent=True) or {}
    depot = depot_service.update_depot(depot_id, patch, viewer_id)
    if depot is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "depot": depot})


@models_api_bp.delete("/depots/<depot_id>")
def delete_depot(depot_id: str):
    viewer_id = _active_viewer_id()
    ok = depot_service.delete_depot(depot_id, viewer_id)
    return jsonify({"ok": ok}), (200 if ok else 404)
