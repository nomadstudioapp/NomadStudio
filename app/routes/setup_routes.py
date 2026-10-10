"""First-run setup wizard — page and API (docs/SETUP_WIZARD.md).

The wizard reuses existing endpoints wherever they already do the job:
folder pickers (/api/models/settings/*/browse), output folder test
(/api/models/settings/output-dir/test), profile creation (/api/viewers) and
model downloads (/api/models/imports/download-file). What lives here is only
what had no endpoint yet: service checks against a URL the user has not
saved, engine detection, and the wizard's own state.

``?preview=1`` opens the wizard without saving anything — used from
Settings to review it on an already configured install.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, jsonify, render_template, request, url_for

from .. import paths
from ..services import lmstudio_service, local_apps, setup_service, viewer_service
from ..services.local_access import local_only, request_is_local
from ..services.workflow_service import _safe_http_url
from .models_api_shared import _ensure_registry, _registry_transaction, _safe_comfy_url

setup_bp = Blueprint("setup", __name__)

_AVATARS_DIR = Path(__file__).resolve().parents[1] / "static" / "images" / "avatars"
_DATA_DIR = paths.DATA_DIR

_IMAGE_FORMATS = {"webp", "png"}
_WIZARD_STEPS = 10


def setup_completed() -> bool:
    """True once the wizard finished — or for installs that were already set up
    before the wizard existed (they have an output folder), so an update never
    forces the wizard on someone mid-work."""
    settings = _ensure_registry().get("settings", {})
    if "setupCompleted" in settings:
        return bool(settings.get("setupCompleted"))
    return bool(str(settings.get("outputDir", "")).strip())


def _settings_payload() -> dict:
    s = _ensure_registry().get("settings", {})
    return {
        "comfyApiUrl": s.get("comfyApiUrl", ""),
        "lmStudioApiUrl": s.get("lmStudioApiUrl", ""),
        "lmStudioPromptModel": s.get("lmStudioPromptModel") or s.get("lmStudioModel", ""),
        "lmStudioVisionModel": s.get("lmStudioVisionModel", ""),
        "outputDir": s.get("outputDir", ""),
        "comfyModelsFolder": s.get("comfyModelsFolder", ""),
        "imageFormat": s.get("imageFormat", "png"),
        "skipComfyOutputCopy": s.get("skipComfyOutputCopy") is True,  # off by default (docs/SETUP_WIZARD.md)
        "autoStartApps": s.get("autoStartApps") is not False,  # on by default (local_apps.py)
        "wizardStep": int(s.get("wizardStep", 1) or 1),
    }


# ── Page ────────────────────────────────────────────────────────────────────


@setup_bp.get("/setup")
def setup_page():
    preview = str(request.args.get("preview", "")).strip() in {"1", "true", "yes"}
    return render_template(
        "pages/setup.html",
        preview=preview,
        available_avatars=viewer_service.list_available_avatars(_AVATARS_DIR),
        next_url=url_for("viewers.who_screen"),
        settings_url=url_for("main.settings_page"),
    )


# ── State ───────────────────────────────────────────────────────────────────


@setup_bp.get("/api/setup/state")
def get_state():
    data_writable = os.access(_DATA_DIR, os.W_OK) if _DATA_DIR.exists() else False
    return jsonify({
        "setupCompleted": setup_completed(),
        "settings": _settings_payload(),
        "viewers": len(viewer_service.list_viewers()),
        "dataDir": {"path": str(_DATA_DIR), "writable": data_writable, "portable": paths.IS_PORTABLE},
        "canCreateShortcuts": local_apps.can_create_shortcuts(),
        # Proposed image folder: short, always writable, not a synced or
        # antivirus-protected folder (Documents/Pictures), and no second drive
        # needed (laptops often have only C:).
        "suggestedOutputDir": str(Path.home() / "Nomad Studio"),
        "steps": _WIZARD_STEPS,
    })


@setup_bp.patch("/api/setup/state")
def patch_state():
    payload = request.get_json(silent=True) or {}
    with _registry_transaction() as data:
        s = data.setdefault("settings", {})
        try:
            if "comfyApiUrl" in payload:
                s["comfyApiUrl"] = _safe_comfy_url(str(payload["comfyApiUrl"]))
            if "lmStudioApiUrl" in payload:
                raw = str(payload["lmStudioApiUrl"]).strip()
                s["lmStudioApiUrl"] = _safe_http_url(raw, "LM Studio") if raw else ""
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        if "outputDir" in payload:
            raw_dir = str(payload["outputDir"]).strip()
            if raw_dir:
                try:
                    os.makedirs(raw_dir, exist_ok=True)
                except OSError as exc:
                    return jsonify({"ok": False, "error": str(exc)}), 400
            s["outputDir"] = raw_dir
        if "comfyModelsFolder" in payload:
            raw_folder = str(payload["comfyModelsFolder"]).strip()
            if raw_folder and not os.path.isabs(raw_folder):
                return jsonify({"ok": False, "error": "comfyModelsFolder must be an absolute path"}), 400
            s["comfyModelsFolder"] = raw_folder
        if "imageFormat" in payload:
            fmt = str(payload["imageFormat"]).strip().lower()
            if fmt not in _IMAGE_FORMATS:
                return jsonify({"ok": False, "error": "imageFormat must be webp or png"}), 400
            s["imageFormat"] = fmt
        if "lmStudioPromptModel" in payload:
            # Same pair chat_routes keeps in sync (lmStudioModel is the legacy name).
            s["lmStudioPromptModel"] = s["lmStudioModel"] = str(payload["lmStudioPromptModel"] or "").strip()[:200]
        if "lmStudioVisionModel" in payload:
            s["lmStudioVisionModel"] = str(payload["lmStudioVisionModel"] or "").strip()[:200]
        if "skipComfyOutputCopy" in payload:
            s["skipComfyOutputCopy"] = bool(payload["skipComfyOutputCopy"])
        if "autoStartApps" in payload:
            s["autoStartApps"] = bool(payload["autoStartApps"])
        if "wizardStep" in payload:
            try:
                s["wizardStep"] = max(1, min(_WIZARD_STEPS, int(payload["wizardStep"])))
            except (TypeError, ValueError):
                pass
        if "setupCompleted" in payload:
            s["setupCompleted"] = bool(payload["setupCompleted"])
    return jsonify({"ok": True, "settings": _settings_payload(), "setupCompleted": setup_completed()})


# ── Checks (never save) ─────────────────────────────────────────────────────


def _comfy_url_from(payload: dict) -> str:
    raw = str(payload.get("comfyApiUrl") or _ensure_registry().get("settings", {}).get("comfyApiUrl", "")).strip()
    return _safe_comfy_url(raw)


@setup_bp.get("/api/setup/local-apps")
def local_apps_state():
    """What this computer already has: graphics card, and ComfyUI or LM Studio
    installed but not running. Lets the wizard help a user who has neither
    (app/services/local_apps.py)."""
    return jsonify({"ok": True, "local": request_is_local(), **local_apps.state()})


@setup_bp.post("/api/setup/local-apps/start")
@local_only
def local_apps_start():
    payload = request.get_json(silent=True) or {}
    app_id = str(payload.get("app", ""))
    if app_id == "comfy":
        return jsonify(local_apps.start_comfyui(listen=bool(payload.get("listen"))))
    if app_id == "lmstudio":
        return jsonify(local_apps.start_lmstudio())
    return jsonify({"ok": False, "error": "Unknown app"}), 400


@setup_bp.get("/api/setup/autostart")
def autostart_status():
    """Whether Nomad Studio is starting ComfyUI / LM Studio (local_apps.py).
    Read by the launcher's start screen, a file:// page: hence the CORS header.
    Only states, no paths."""
    resp = jsonify({"ok": True, **local_apps.autostart_state()})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@setup_bp.post("/api/setup/autostart/start")
@local_only
def autostart_start():
    """Start ComfyUI or LM Studio from the settings panel's Start button."""
    app_id = str((request.get_json(silent=True) or {}).get("app", ""))
    if app_id not in {"comfy", "lmstudio"}:
        return jsonify({"ok": False, "error": "Unknown app"}), 400
    settings = dict(_ensure_registry().get("settings", {}))
    threading.Thread(target=local_apps.start_and_wait, args=(app_id, settings), daemon=True).start()
    return jsonify({"ok": True})


@setup_bp.post("/api/setup/shortcuts")
@local_only
def make_shortcuts():
    """Desktop / Start menu shortcuts to this copy of Nomad Studio (local_apps.py)."""
    payload = request.get_json(silent=True) or {}
    res = local_apps.create_shortcuts(desktop=payload.get("desktop", True) is not False,
                                      start_menu=payload.get("startMenu", True) is not False)
    return jsonify(res), (200 if res.get("ok") else 400)


@setup_bp.post("/api/setup/install/<app_id>")
@local_only
def install_local_app(app_id: str):
    """Get ComfyUI or LM Studio for a user who has neither: ComfyUI is
    unpacked into the chosen folder, LM Studio's own installer is downloaded
    and opened (app/services/local_apps.py). "vcredist" is the Visual C++
    runtime ComfyUI needs on a fresh Windows; it takes no folder."""
    if app_id == "vcredist":
        try:
            return jsonify({"ok": True, "job": local_apps.start_install_vcredist()})
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
    payload = request.get_json(silent=True) or {}
    raw = str(payload.get("dir", "") or "").strip()
    if not raw or not os.path.isabs(raw):
        return jsonify({"ok": False, "error": "Choose a folder to install it in"}), 400
    starters = {"comfyui": local_apps.start_install_comfyui, "lmstudio": local_apps.start_install_lmstudio}
    if app_id not in starters:
        return jsonify({"ok": False, "error": "Unknown app"}), 400
    try:
        job = starters[app_id](Path(raw))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "job": job})


@setup_bp.get("/api/setup/install/job")
def install_local_app_job():
    return jsonify({"ok": True, "job": local_apps.get_job()})


@setup_bp.post("/api/setup/check/comfy")
def check_comfy():
    payload = request.get_json(silent=True) or {}
    try:
        url = _comfy_url_from(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    return jsonify({**setup_service.check_comfy(url), "comfyApiUrl": url, "isLocal": setup_service.is_local_url(url)})


_discover_lock = threading.Lock()


@setup_bp.post("/api/setup/discover")
def discover_services():
    """Find ComfyUI and LM Studio on this machine and the local network
    (setup_service.discover_services). One scan at a time."""
    if not _discover_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "A network search is already running"}), 409
    try:
        return jsonify({"ok": True, **setup_service.discover_services()})
    finally:
        _discover_lock.release()


@setup_bp.post("/api/setup/check/lmstudio")
def check_lmstudio():
    payload = request.get_json(silent=True) or {}
    raw = str(payload.get("lmStudioApiUrl") or _ensure_registry().get("settings", {}).get("lmStudioApiUrl", "")).strip()
    try:
        url = _safe_http_url(raw, "LM Studio")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    return jsonify({**setup_service.check_lmstudio(lmstudio_service.models_endpoint(url)), "lmStudioApiUrl": url})


def _lms_rest_models_url(payload: dict) -> str:
    raw = str(payload.get("lmStudioApiUrl") or _ensure_registry().get("settings", {}).get("lmStudioApiUrl", "")).strip()
    return lmstudio_service.rest_models_endpoint(_safe_http_url(raw, "LM Studio"))


@setup_bp.post("/api/setup/llm-models")
def llm_models():
    payload = request.get_json(silent=True) or {}
    try:
        url = _lms_rest_models_url(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    status = setup_service.llm_models_status(url)
    # Not in preview: also fill the Prompts and Vision model lists, so those
    # pages are not "No models loaded" after the wizard already read LM Studio.
    # The chosen models are left to the wizard (pick_defaults=False).
    if status.get("ok") and payload.get("save"):
        from .models_api_modules.chat_routes import refresh_lmstudio_model_lists

        raw = str(payload.get("lmStudioApiUrl") or _ensure_registry().get("settings", {}).get("lmStudioApiUrl", "")).strip()
        try:
            with _registry_transaction() as data:
                refresh_lmstudio_model_lists(data.setdefault("settings", {}), _safe_http_url(raw, "LM Studio"), pick_defaults=False)
            status["listsSaved"] = True
        except Exception as exc:  # noqa: BLE001 — the step still works without the lists
            status["listsError"] = str(exc)
    return jsonify(status)


@setup_bp.post("/api/setup/llm-models/download")
def llm_model_download():
    payload = request.get_json(silent=True) or {}
    try:
        url = _lms_rest_models_url(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    return jsonify(setup_service.llm_download_start(url, str(payload.get("id", ""))))


@setup_bp.get("/api/setup/llm-models/download/<job_id>")
def llm_model_download_status(job_id: str):
    try:
        url = _lms_rest_models_url({})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    return jsonify(setup_service.llm_download_status(url, job_id))


@setup_bp.post("/api/setup/check/output-dir")
def check_output_dir():
    """Existence/writability is tested by /api/models/settings/output-dir/test;
    this only adds the sync/protected-folder warning."""
    payload = request.get_json(silent=True) or {}
    return jsonify({"warning": setup_service.sync_folder_warning(str(payload.get("outputDir", "")))})


# ── Engines ─────────────────────────────────────────────────────────────────


@setup_bp.post("/api/setup/engines")
def detect_engines():
    from .models_api_modules import imports_routes

    payload = request.get_json(silent=True) or {}
    try:
        url = _comfy_url_from(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    comfy = setup_service.check_comfy(url)
    if not comfy.get("ok"):
        return jsonify({"ok": False, "error": comfy.get("error", "ComfyUI unreachable")})
    try:
        result = setup_service.detect_engines(
            _ensure_registry().get("imports", []),
            url,
            comfy.get("gpus", []),
            imports_routes._parse_workflow_config_node,
            imports_routes._extract_downloads_from_workflow,
        )
    except Exception as exc:  # noqa: BLE001 — shown to the user, wizard keeps going
        return jsonify({"ok": False, "error": str(exc)})
    return jsonify({
        "ok": True,
        "gpus": comfy.get("gpus", []),
        "isLocal": setup_service.is_local_url(url),
        "comfyHost": urlparse(url).hostname or "",
        **result,
    })


@setup_bp.post("/api/setup/models-folder/validate")
def validate_models_folder():
    payload = request.get_json(silent=True) or {}
    path = str(payload.get("path", "")).strip()
    if not path or not os.path.isabs(path):
        return jsonify({"ok": False, "reason": "not_absolute"})
    try:
        index, _ = setup_service.comfy_model_index(_comfy_url_from(payload))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "reason": "comfy_unreachable", "error": str(exc)})
    return jsonify({**setup_service.validate_models_folder(path, index), "freeBytes": setup_service.free_space(path)})


@setup_bp.post("/api/setup/downloads/sizes")
def download_sizes():
    payload = request.get_json(silent=True) or {}
    urls = payload.get("urls") if isinstance(payload.get("urls"), list) else []
    folder = str(_ensure_registry().get("settings", {}).get("comfyModelsFolder", "")).strip()
    return jsonify({
        "sizes": setup_service.remote_sizes(urls),
        "freeBytes": setup_service.free_space(folder) if folder else None,
    })
