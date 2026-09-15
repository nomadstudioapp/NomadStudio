import time

from flask import Flask, jsonify

from .config import DEFAULT_SECRET_KEY
from .routes.main import main_bp
from .routes.models_api import models_api_bp
from .routes.templates_api import templates_api_bp
from .routes.flows_api import flows_api_bp
from .routes.viewers_routes import viewers_bp
from .routes.setup_routes import setup_bp
from .routes.backup_routes import backup_bp
from .routes.reset_routes import reset_bp
from .routes.packages_routes import packages_bp
from .routes.user_images_routes import user_images_bp
from .routes.updates_routes import updates_bp
from . import paths
from .services.addon_loader import load_addons, get_registry
from .services import app_info
from .services.local_access import request_is_local


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = DEFAULT_SECRET_KEY

    app.register_blueprint(main_bp)
    app.register_blueprint(models_api_bp, url_prefix="/api")
    app.register_blueprint(templates_api_bp, url_prefix="/api")
    app.register_blueprint(flows_api_bp, url_prefix="/api")
    app.register_blueprint(viewers_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(reset_bp)
    app.register_blueprint(packages_bp)
    app.register_blueprint(user_images_bp)
    app.register_blueprint(updates_bp)

    # User data lives outside the program folder (app/paths.py): create it,
    # move data left inside app/ by older versions, and point installed packs
    # at the current packages folder.
    try:
        paths.prepare_data_dir()
        from .routes.models_api_shared import REGISTRY_PATH, _registry_transaction
        from .services import registry_service

        if paths.fix_pack_dirs(registry_service._read_json_safe(REGISTRY_PATH) or {}):
            with _registry_transaction() as data:
                paths.fix_pack_dirs(data)
    except Exception:  # noqa: BLE001 — the app still starts; the log says why
        app.logger.exception("preparing the data folder failed (%s)", paths.DATA_DIR)

    # Free engines and base flows shipped with the app (bundled-packages/):
    # installed on the first start, updated when the app brings newer ones,
    # never reinstalled after the user removes them.
    try:
        from .routes.packages_routes import install_bundled_packages

        install_bundled_packages()
    except Exception:  # noqa: BLE001 — never block startup on a package
        app.logger.exception("installing bundled packages failed")

    # Discover and register addons from addons/ directory
    load_addons(app)

    # Was bumped once per process start — but this app gets its CSS/JS
    # hand-edited live while the dev server keeps running (no restart in
    # between), so a fixed per-process value bit us repeatedly: edits to
    # nomad_studio.css/.js "looked like they weren't applied" because the
    # browser kept serving the cache from the FIRST page load of the
    # session under the same ?v=... URL (confirmed during the card-zoom
    # work — an old, already-stale 372px value kept showing up no matter
    # what the CSS said). Recomputed on every request instead, so every
    # reload is guaranteed to fetch current file contents.
    @app.context_processor
    def inject_asset_version():
        return {"asset_v": str(int(time.time()))}

    @app.context_processor
    def inject_storage_scope():
        # Browser storage per profile (layout/base.html → storage_scope.js).
        from .routes.viewers_routes import storage_scope

        return {"nomad_storage_scope": storage_scope}

    @app.context_processor
    def inject_local_request():
        # Pages disable machine-only actions (reset, restore, folder pickers)
        # for browsers on other computers — see services/local_access.py.
        return {"is_local_request": request_is_local}

    @app.get("/api/health")
    def health():
        """Nomad Studio itself is up. Used by the release build's smoke test
        and by the launcher's post-update check (docs/APP_UPDATES.md §7.5).
        Deliberately never touches ComfyUI or LM Studio — that is what the
        service LEDs in nav_status.js are for."""
        response = jsonify(app_info.health())
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/addons")
    def list_addons():
        """List all loaded addons with their metadata."""
        return jsonify(list(get_registry().values()))

    return app
