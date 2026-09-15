"""Routes for the "Who's watching?" viewer picker (pre-shell gate screen)."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from ..services import viewer_service

viewers_bp = Blueprint("viewers", __name__)

_AVATARS_DIR = Path(__file__).resolve().parents[1] / "static" / "images" / "avatars"

SESSION_KEY = "active_viewer_id"


@viewers_bp.get("/who")
def who_screen():
    return render_template(
        "pages/who.html",
        viewers=viewer_service.list_viewers(),
        agent_viewers=viewer_service.list_agent_viewers(),
        available_avatars=viewer_service.list_available_avatars(_AVATARS_DIR),
        vanish_avatar=viewer_service.get_or_create_vanish_viewer()["avatar"],
    )


@viewers_bp.post("/api/viewers/verify-pin")
def verify_pin():
    body = request.get_json(force=True) or {}
    viewer_id = body.get("viewer_id")
    pin = str(body.get("pin", ""))

    viewer = viewer_service.get_viewer(viewer_id)
    if viewer is None:
        return jsonify({"ok": False, "error": "viewer not found"}), 404

    ok = viewer_service.verify_pin(viewer_id, pin)
    if ok:
        session[SESSION_KEY] = viewer_id
    return jsonify({"ok": ok})


@viewers_bp.post("/api/viewers/select")
def select_viewer():
    """Select a viewer that has no PIN — no verification needed."""
    body = request.get_json(force=True) or {}
    viewer_id = body.get("viewer_id")
    viewer = viewer_service.get_viewer(viewer_id)
    if viewer is None:
        return jsonify({"ok": False, "error": "viewer not found"}), 404
    if viewer.get("pin_hash"):
        return jsonify({"ok": False, "error": "this viewer requires a pin"}), 403

    session[SESSION_KEY] = viewer_id
    return jsonify({"ok": True})


@viewers_bp.post("/api/viewers")
def create_viewer():
    body = request.get_json(force=True) or {}
    name = str(body.get("name", "")).strip()
    avatar = body.get("avatar")
    pin = body.get("pin")

    if not name or not avatar:
        return jsonify({"ok": False, "error": "name and avatar are required"}), 400

    if pin and (not str(pin).isdigit() or len(str(pin)) != 4):
        return jsonify({"ok": False, "error": "pin must be 4 digits"}), 400

    viewer = viewer_service.create_viewer(name, avatar, pin)
    return jsonify({"ok": True, "viewer": {
        "id": viewer["id"],
        "name": viewer["name"],
        "avatar": viewer["avatar"],
        "is_owner": viewer["is_owner"],
        "has_pin": bool(viewer.get("pin_hash")),
    }})


@viewers_bp.post("/api/viewers/vanish")
def select_vanish_viewer():
    """Enter (or re-enter) the singleton "Vanish Session" profile — no name,
    no pin, no signup. Always resolves to the same fixed viewer record so
    the rest of the app has something real to point at, but its Create
    generations are never written to disk (see _active_viewer_is_vanish())."""
    viewer = viewer_service.get_or_create_vanish_viewer()
    session[SESSION_KEY] = viewer["id"]
    return jsonify({"ok": True, "viewer": {"id": viewer["id"], "name": viewer["name"], "avatar": viewer["avatar"]}})


@viewers_bp.get("/switch-viewer")
def switch_viewer():
    """Sign out of the current viewer and go back to the picker."""
    session.pop(SESSION_KEY, None)
    return redirect(url_for("viewers.who_screen"))


# ── Agent viewers (MCP connections) ──────────────────────────────────────
# Same session mechanism as human viewers, but no PIN/security: agents are
# trusted local processes (Claude Desktop, LM Studio), not human accounts.

@viewers_bp.get("/api/agents")
def list_agents():
    return jsonify({"agents": viewer_service.list_agent_viewers()})


@viewers_bp.post("/api/agents")
def create_agent():
    body = request.get_json(force=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400

    viewer = viewer_service.create_agent_viewer(name)
    session[SESSION_KEY] = viewer["id"]
    slug = viewer_service.slugify_name(viewer["name"])
    return jsonify({"ok": True, "agent": {"id": viewer["id"], "name": viewer["name"], "slug": slug}})


@viewers_bp.post("/api/agents/<agent_id>/select")
def select_agent(agent_id: str):
    viewer = viewer_service.get_viewer(agent_id)
    if viewer is None or not viewer.get("is_agent", False):
        return jsonify({"ok": False, "error": "agent not found"}), 404

    session[SESSION_KEY] = agent_id
    slug = viewer_service.slugify_name(viewer["name"])
    return jsonify({"ok": True, "agent": {"id": viewer["id"], "name": viewer["name"], "slug": slug}})
