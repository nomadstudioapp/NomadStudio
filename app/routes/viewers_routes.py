"""Routes for the "Who's watching?" viewer picker (pre-shell gate screen)."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from ..services import agent_setup, viewer_service
from ..services.local_access import local_only

viewers_bp = Blueprint("viewers", __name__)

_AVATARS_DIR = Path(__file__).resolve().parents[1] / "static" / "images" / "avatars"

SESSION_KEY = "active_viewer_id"
VANISH_TOKEN_KEY = "vanish_storage_token"


def storage_scope() -> dict:
    """What the browser needs to keep its storage per profile
    (static/js/services/storage_scope.js): the active viewer id, whether it is
    the Vanish Session, and Vanish's per-entry token. Never the pin or name."""
    viewer_id = session.get(SESSION_KEY)
    viewer = viewer_service.get_viewer(viewer_id) if viewer_id else None
    if not viewer:
        return {"id": None, "vanish": False, "token": None}
    is_vanish = bool(viewer.get("is_vanish"))
    if is_vanish and not session.get(VANISH_TOKEN_KEY):
        session[VANISH_TOKEN_KEY] = secrets.token_hex(8)
    return {"id": viewer["id"], "vanish": is_vanish, "token": session.get(VANISH_TOKEN_KEY) if is_vanish else None}


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


@viewers_bp.post("/api/viewers/me/create-unlocked")
def unlock_create():
    """First image with Simple (or "Show all flows"): Create shows its whole
    catalogue from now on for this profile. Idempotent."""
    viewer_id = session.get(SESSION_KEY)
    if not viewer_id:
        return jsonify({"ok": False, "error": "no active viewer"}), 400
    return jsonify({"ok": viewer_service.unlock_create(viewer_id)})


@viewers_bp.post("/api/viewers/me/essentials")
def set_essential():
    """Right-click on a hub card: add it to / remove it from this profile's
    Essentials. `default` is the card's package value (data-essential-default),
    so only the profile's differences from it get stored."""
    viewer_id = session.get(SESSION_KEY)
    body = request.get_json(silent=True) or {}
    flow_id = str(body.get("flow_id") or "").strip()
    if not flow_id:
        return jsonify({"ok": False, "error": "flow_id required"}), 400
    on = bool(body.get("essential"))
    if not viewer_id:
        return jsonify({"ok": False, "essential": on})
    ok = viewer_service.set_essential(viewer_id, flow_id, on, bool(body.get("default")))
    return jsonify({"ok": ok, "essential": on})


@viewers_bp.post("/api/viewers/me/essentials-mode")
def set_essentials_mode():
    """The pin next to the filter toggle: show only Essentials, or everything."""
    viewer_id = session.get(SESSION_KEY)
    on = bool((request.get_json(silent=True) or {}).get("on"))
    if not viewer_id:
        return jsonify({"ok": False, "on": on})
    return jsonify({"ok": viewer_service.set_essentials_only(viewer_id, on), "on": on})


@viewers_bp.post("/api/viewers/vanish")
def select_vanish_viewer():
    """Enter (or re-enter) the singleton "Vanish Session" profile — no name,
    no pin, no signup. Always resolves to the same fixed viewer record so
    the rest of the app has something real to point at, but its Create
    generations are never written to disk (see _active_viewer_is_vanish())."""
    viewer = viewer_service.get_or_create_vanish_viewer()
    session[SESSION_KEY] = viewer["id"]
    # New every time Vanish is entered: browser storage is keyed on it
    # (static/js/services/storage_scope.js), so a Vanish Session never sees
    # what an earlier one left in the tab.
    session[VANISH_TOKEN_KEY] = secrets.token_hex(8)
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


@viewers_bp.get("/api/agents/setup")
@local_only
def agents_setup():
    """Settings › Agents: this installation's MCP launch values (Python,
    PYTHONPATH, port) and whether Claude Desktop / ChatGPT / Bionic already
    point here (app/services/agent_setup.py). Local only: it shows paths on
    this computer."""
    return jsonify(agent_setup.setup_info(_request_port()))


def _request_port() -> int:
    try:
        return int(request.host.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return int(os.environ.get("PORT") or agent_setup.DEFAULT_MCP_PORT)


@viewers_bp.post("/api/agents/setup/<client>/connect")
@local_only
def agents_setup_connect(client: str):
    """Settings › Agents › Connect / Fix: write this installation's MCP entry
    into Claude Desktop's, ChatGPT's (Codex) or Bionic's config file — a dated
    copy first, only Nomad Studio's entry changes (agent_setup.connect)."""
    from ..paths import DATA_DIR

    try:
        result = agent_setup.connect(client, _request_port(), DATA_DIR / "backups" / "agents")
    except agent_setup.ConnectError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"ok": False, "error": f"Could not write the file: {exc}"}), 500
    return jsonify({"ok": True, **result})


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
