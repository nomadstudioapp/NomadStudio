"""Total reset (Settings › Advanced › Danger zone) — SIMULATION ONLY.

``POST /api/reset/plan`` returns what a reset would do. There is no
endpoint that executes it yet: that is added once the simulated plan has
been reviewed (see app/services/reset_service.py).
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..services import reset_service
from ..services.local_access import local_only
from . import backup_routes
from .models_api_shared import _ensure_registry

reset_bp = Blueprint("reset", __name__)

# The whole reset — plan included — is only available on the machine Nomad
# Studio is installed on: from a browser on another computer it would wipe
# this machine's data (app/services/local_access.py).


@reset_bp.post("/api/reset/plan")
@local_only
def reset_plan():
    payload = request.get_json(silent=True) or {}
    registry = _ensure_registry()
    plan = reset_service.build_plan(
        backup_routes.APP_DIR,
        registry.get("settings", {}),
        len(registry.get("imports", []) or []),
        include_build=bool(payload.get("includeBuild")),
        include_generated=bool(payload.get("includeGenerated")),
    )
    return jsonify({"ok": True, "plan": plan})
