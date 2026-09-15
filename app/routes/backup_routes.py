"""Backups in Settings — API over app/services/backup_service.py.

The backup folder is chosen by the user (``settings.backupDir``); by default
it is ``backups/`` next to ``app/``. Folder picker and "open folder" act on
the server machine, like the other folder pickers in Settings (local use).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from flask import Blueprint, jsonify, request

from ..services import app_info, backup_service
from ..services.local_access import local_only, request_is_local
from .models_api_shared import _ensure_registry, _registry_transaction

backup_bp = Blueprint("backup", __name__)

APP_DIR = Path(__file__).resolve().parents[1]  # app/ — tests point this at a copy

_browse_lock = threading.Lock()


def _backup_dir() -> Path:
    return backup_service.resolve_backup_dir(APP_DIR, _ensure_registry().get("settings", {}))


def _version() -> str | None:
    try:
        return app_info.health().get("version")
    except Exception:  # noqa: BLE001
        return None


@backup_bp.get("/api/backup")
def backup_overview():
    backup_dir = _backup_dir()
    settings = _ensure_registry().get("settings", {})
    return jsonify({
        "backupDir": str(backup_dir),
        "isDefaultDir": not str(settings.get("backupDir", "") or "").strip(),
        "dirExists": backup_dir.is_dir(),
        "backups": backup_service.list_backups(backup_dir),
        "estimate": backup_service.estimate(APP_DIR),
        "busy": backup_service.is_busy(),
        # Restore, delete, folder changes and pickers only from the machine
        # Nomad Studio runs on (app/services/local_access.py).
        "local": request_is_local(),
    })


@backup_bp.patch("/api/backup/settings")
@local_only
def update_backup_settings():
    payload = request.get_json(silent=True) or {}
    raw = str(payload.get("backupDir", "") or "").strip()
    if raw:
        if not os.path.isabs(raw):
            return jsonify({"ok": False, "error": "The backup folder must be an absolute path"}), 400
        try:
            os.makedirs(raw, exist_ok=True)
        except OSError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        if not os.access(raw, os.W_OK):
            return jsonify({"ok": False, "error": "Nomad Studio cannot write to this folder"}), 400
    with _registry_transaction() as data:
        data.setdefault("settings", {})["backupDir"] = raw
    return jsonify({"ok": True, "backupDir": str(_backup_dir())})


@backup_bp.post("/api/backup/browse")
@local_only
def browse_backup_dir():
    if not _browse_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Another folder picker is already open"}), 409
    initial = str((request.get_json(silent=True) or {}).get("current", "")).strip()
    chosen: list[str] = []
    error: list[str] = []

    def _pick():
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(
                parent=root,
                title="Nomad Studio backups",
                initialdir=initial if os.path.isdir(initial) else "/",
            )
            root.destroy()
            if path:
                chosen.append(path)
        except Exception as exc:  # noqa: BLE001
            error.append(str(exc))
        finally:
            _browse_lock.release()

    t = threading.Thread(target=_pick, daemon=True)
    t.start()
    t.join(timeout=120)
    if error:
        return jsonify({"ok": False, "error": error[0]}), 500
    if not chosen:
        return jsonify({"ok": False, "cancelled": True})
    return jsonify({"ok": True, "backupDir": chosen[0]})


@backup_bp.post("/api/backup/open-folder")
@local_only
def open_backup_folder():
    backup_dir = _backup_dir()
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(str(backup_dir))  # noqa: S606 — local desktop app
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(backup_dir)])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", str(backup_dir)])  # noqa: S603,S607
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True})


@backup_bp.post("/api/backup/create")
def create_backup():
    payload = request.get_json(silent=True) or {}
    job = backup_service.start_create(APP_DIR, _backup_dir(), bool(payload.get("includeImages")), "manual", _version())
    if job is None:
        return jsonify({"ok": False, "error": "A backup or restore is already running"}), 409
    return jsonify({"ok": True, "job": job})


@backup_bp.post("/api/backup/restore")
@local_only
def restore_backup():
    payload = request.get_json(silent=True) or {}
    backup_dir = _backup_dir()
    path = backup_service.safe_backup_path(backup_dir, str(payload.get("name", "")))
    if path is None:
        return jsonify({"ok": False, "error": "Backup not found"}), 404
    if backup_service.read_manifest(path) is None:
        return jsonify({"ok": False, "error": "This file is not a valid Nomad Studio backup"}), 400
    job = backup_service.start_restore(APP_DIR, backup_dir, path, _version())
    if job is None:
        return jsonify({"ok": False, "error": "A backup or restore is already running"}), 409
    return jsonify({"ok": True, "job": job})


@backup_bp.delete("/api/backup/<name>")
@local_only
def delete_backup(name: str):
    if backup_service.is_busy():
        return jsonify({"ok": False, "error": "A backup or restore is already running"}), 409
    path = backup_service.safe_backup_path(_backup_dir(), name)
    if path is None:
        return jsonify({"ok": False, "error": "Backup not found"}), 404
    path.unlink()
    return jsonify({"ok": True})


@backup_bp.get("/api/backup/jobs/<job_id>")
def backup_job(job_id: str):
    job = backup_service.get_job(job_id)
    if job is None:
        return jsonify({"ok": False, "error": "Job not found"}), 404
    return jsonify({"ok": True, "job": job})
