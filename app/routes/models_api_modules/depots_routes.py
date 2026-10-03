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
    body = request.get_json(silent=True) or {}
    category = str(body.get("category") or "").strip().lower()
    if not depot_id:
        # "flow" is the automatic save after every generation
        # (flow-gallery.js addToFeed): no Depot active just means there is
        # nowhere to file it, not an error.
        if category == "flow":
            return jsonify({"ok": True, "skipped": "no active depot"})
        return jsonify({"ok": False, "error": "No active Depot"}), 400
    url = str(body.get("url") or "").strip()
    ref = None
    if category == "style":
        # Build › Styles: the item points at the style itself. Saving the
        # same style twice returns the one already there.
        raw_ref = body.get("ref") if isinstance(body.get("ref"), dict) else {}
        style_id = str(raw_ref.get("styleId") or "").strip()
        if not style_id:
            return jsonify({"ok": False, "error": "ref.styleId is required"}), 400
        existing = depot_service.find_item_by_ref(depot_id, viewer_id, "style", style_id)
        if existing is not None:
            return jsonify({"ok": True, "item": existing, "duplicate": True})
        ref = {"styleId": style_id}
        for key in ("name", "category", "prompt"):
            if raw_ref.get(key):
                ref[key] = str(raw_ref[key])[:2000]
    elif category in ("character", "background") and isinstance(body.get("ref"), dict):
        # A real Build Character/Background (flow-gallery.js creates or picks
        # it first): the item points at its keyword. Same one twice → the
        # one already there.
        keyword = str(body["ref"].get("keyword") or "").strip()
        if not keyword:
            return jsonify({"ok": False, "error": "ref.keyword is required"}), 400
        existing = depot_service.find_item_by_ref(depot_id, viewer_id, category, keyword)
        if existing is not None:
            return jsonify({"ok": True, "item": existing, "duplicate": True})
        ref = {"keyword": keyword}
        url = url or f"/static/images/{category}s/{keyword}.png"
    elif not url:
        return jsonify({"ok": False, "error": "url is required"}), 400
    item = depot_service.add_item(
        depot_id,
        viewer_id,
        category,
        url,
        body.get("caption") or "",
        body.get("sourceUrl") or "",
        ref,
    )
    if item is None:
        return jsonify({"ok": False, "error": "Invalid category or depot"}), 400
    return jsonify({"ok": True, "item": item})


@models_api_bp.patch("/depots/<depot_id>/items/<item_id>/ref")
def link_depot_item(depot_id: str, item_id: str):
    """Point an image-only Character/Background item at the real Build one
    it was just made into (library.js "Make it a character")."""
    viewer_id = _active_viewer_id()
    body = request.get_json(silent=True) or {}
    keyword = str(body.get("keyword") or "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "keyword is required"}), 400
    depot = depot_service.get_depot(depot_id, viewer_id)
    item = next((it for it in (depot or {}).get("items") or [] if it.get("id") == item_id), None)
    if item is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    if item.get("category") not in ("character", "background"):
        return jsonify({"ok": False, "error": "Only Characters and Backgrounds link to Build"}), 400
    url = f"/static/images/{item['category']}s/{keyword}.png"
    item = depot_service.set_item_ref(depot_id, viewer_id, item_id, {"keyword": keyword}, url)
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
