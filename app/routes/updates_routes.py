"""Settings › Updates — API over app/services/update_service.py.

    GET  /api/updates                  installed version, prepared update, last result
    POST /api/updates/inspect          multipart "file" (release ZIP) → summary + token
    POST /api/updates/discard-upload   {"token"}
    POST /api/updates/prepare          {"token"} → background job (extract + data backup)
    GET  /api/updates/job              the prepare job
    POST /api/updates/discard          forget the prepared update
    POST /api/updates/apply            restart into the prepared update
    POST /api/updates/dismiss-result   hide the last result notice

Everything that changes the install is only allowed from the computer Nomad
Studio runs on (local_access).
"""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, request

from .. import paths
from ..services import backup_service, update_service
from ..services.local_access import local_only, request_is_local
from ..services.update_service import UpdateError
from .models_api_shared import _ensure_registry

updates_bp = Blueprint("updates", __name__)


def _backup_dir():
    return backup_service.resolve_backup_dir(paths.DATA_DIR, _ensure_registry().get("settings", {}))


@updates_bp.get("/api/updates")
def updates_overview():
    return jsonify({
        "ok": True,
        "installed": update_service.current(),
        "unsupported": update_service.unsupported_reason(),
        "pending": update_service.pending(),
        "lastResult": update_service.last_result(),
        "job": update_service.get_job(),
        "dataDir": str(paths.DATA_DIR),
        "local": request_is_local(),
    })


@updates_bp.post("/api/updates/inspect")
@local_only
def inspect_update():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"ok": False, "error": "Choose the release ZIP"}), 400
    try:
        token, path = update_service.save_upload(upload.stream)
    except UpdateError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    try:
        summary = update_service.inspect_zip(path)
    except UpdateError as exc:
        update_service.discard_upload(token)
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "token": token, "update": summary})


@updates_bp.post("/api/updates/discard-upload")
@local_only
def discard_upload():
    update_service.discard_upload(str((request.get_json(silent=True) or {}).get("token", "")))
    return jsonify({"ok": True})


@updates_bp.post("/api/updates/prepare")
@local_only
def prepare_update():
    token = str((request.get_json(silent=True) or {}).get("token", ""))
    try:
        job = update_service.start_prepare(token, _backup_dir())
    except UpdateError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "job": job})


@updates_bp.get("/api/updates/job")
def update_job():
    return jsonify({"ok": True, "job": update_service.get_job()})


@updates_bp.post("/api/updates/discard")
@local_only
def discard_prepared():
    job = update_service.get_job()
    if job and job.get("state") == "running":
        return jsonify({"ok": False, "error": "The update is still being prepared"}), 409
    update_service.discard_prepared()
    return jsonify({"ok": True})


@updates_bp.post("/api/updates/apply")
@local_only
def apply_update():
    try:
        info = update_service.apply(int(os.getenv("PORT", "5123")))
    except UpdateError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "to": info.get("to")})


@updates_bp.post("/api/updates/dismiss-result")
def dismiss_result():
    update_service.dismiss_result()
    return jsonify({"ok": True})
