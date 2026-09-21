"""Addon loader — discovers and registers NomadStudio addons.

Addons live in the ``addons/`` directory at the project root.  Each addon is a
Python package (a folder with ``__init__.py``) that declares at minimum:

    ADDON_INFO = {
        "name": "My Addon",
        "version": (1, 0, 0),
        "description": "...",
        "author": "...",
    }

    def register(app: Flask) -> None:
        app.register_blueprint(my_bp, url_prefix="/api")

Optionally an addon may expose:

    def unregister() -> None: ...
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import types
from pathlib import Path
from typing import Any

from flask import Flask

logger = logging.getLogger(__name__)

# Registry: addon_id -> {"info": ADDON_INFO, "module": <module>}
_registry: dict[str, dict[str, Any]] = {}


def _addons_dir() -> Path:
    """Return the absolute path to the ``addons/`` directory."""
    return Path(__file__).resolve().parents[2] / "addons"


def load_addons(app: Flask) -> None:
    """Discover and register all addons found in ``addons/`` (source-tree,
    built-in ones) and in each installed package's own ``addon/`` folder
    (``contributes.addon`` — PACKAGE_FORMAT.md §9, minimal slice: still a
    plain ``from app…``-importing Flask blueprint, same contract as a
    source-tree addon, just delivered inside a package zip instead of
    checked into git. Installing one requires an app restart to activate —
    this function only ever runs once, at create_app() time)."""
    addons_path = _addons_dir()
    if addons_path.is_dir():
        # Ensure the parent 'addons' package exists in sys.modules so that
        # relative imports inside addon submodules resolve correctly.
        if "addons" not in sys.modules:
            addons_pkg = types.ModuleType("addons")
            addons_pkg.__path__ = [str(addons_path)]  # type: ignore[attr-defined]
            addons_pkg.__package__ = "addons"
            sys.modules["addons"] = addons_pkg

        for entry in sorted(addons_path.iterdir()):
            if not entry.is_dir():
                continue
            if not (entry / "__init__.py").exists():
                continue
            _load_addon(app, entry.name, entry)
    else:
        logger.debug("No addons/ directory found at %s — skipping.", addons_path)

    _load_package_addons(app)


def _load_package_addons(app: Flask) -> None:
    """Same as the source-tree scan above, but for packages installed via
    the normal /api/packages/install pipeline that carry a
    ``contributes.addon`` (package_service.py already extracts their
    ``addon/`` folder onto disk unconditionally — this is the only part
    that still needs to notice it's there and import it)."""
    from app.paths import PACKAGES_DIR

    if not PACKAGES_DIR.is_dir():
        return
    for pkg_dir in sorted(PACKAGES_DIR.iterdir()):
        if not pkg_dir.is_dir() or pkg_dir.name.startswith("."):
            continue
        addon_path = pkg_dir / "addon"
        if not (addon_path / "__init__.py").exists():
            continue
        # Sanitized, not the raw dotted/hyphenated package id: kept out of
        # Python's import machinery entirely as anything but an opaque
        # sys.modules string key, but no reason to risk relying on that.
        addon_id = "pkg_" + "".join(c if c.isalnum() else "_" for c in pkg_dir.name)
        _load_addon(app, addon_id, addon_path)


def _load_addon(app: Flask, addon_id: str, path: Path) -> None:
    """Import a single addon package and call its register() function."""
    module_name = f"addons.{addon_id}"
    try:
        spec = importlib.util.spec_from_file_location(
            module_name, path / "__init__.py",
            submodule_search_locations=[str(path)],
        )
        if spec is None or spec.loader is None:
            logger.warning("Addon '%s': could not create module spec.", addon_id)
            return

        module = importlib.util.module_from_spec(spec)
        # Register in sys.modules BEFORE exec_module so that relative imports
        # inside the package (e.g. ``from . import service``) resolve correctly.
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        addon_info: dict[str, Any] = getattr(module, "ADDON_INFO", {})
        if not addon_info:
            logger.warning("Addon '%s': ADDON_INFO missing — skipping.", addon_id)
            return

        register_fn = getattr(module, "register", None)
        if register_fn is None:
            logger.warning("Addon '%s': register() missing — skipping.", addon_id)
            return

        register_fn(app)
        _registry[addon_id] = {"info": addon_info, "module": module}
        logger.info(
            "Addon loaded: %s v%s",
            addon_info.get("name", addon_id),
            _fmt_version(addon_info.get("version", ())),
        )

    except Exception:
        logger.exception("Failed to load addon '%s'.", addon_id)
        sys.modules.pop(module_name, None)  # clean up partial registration


def get_registry() -> dict[str, dict[str, Any]]:
    """Return a copy of the addon registry (safe for serialisation)."""
    return {
        addon_id: {
            "id": addon_id,
            "name": entry["info"].get("name", addon_id),
            "version": _fmt_version(entry["info"].get("version", ())),
            "description": entry["info"].get("description", ""),
            "author": entry["info"].get("author", ""),
        }
        for addon_id, entry in _registry.items()
    }


def get_addon_flows() -> list[dict[str, Any]]:
    """Return flow definitions from all loaded addons.

    Each addon may ship a ``flow.json`` alongside its ``__init__.py``.
    This function collects them all and returns a list of flow dicts ready
    to be merged into the core flow catalogue.
    """
    import json

    flows: list[dict[str, Any]] = []
    for addon_id, entry in _registry.items():
        module = entry["module"]
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        flow_path = Path(module_file).parent / "flow.json"
        if not flow_path.exists():
            continue
        try:
            definition: dict[str, Any] = json.loads(flow_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Addon '%s': could not parse flow.json — skipping.", addon_id)
            continue
        if not isinstance(definition, dict) or not definition.get("id"):
            logger.warning("Addon '%s': flow.json missing 'id' field — skipping.", addon_id)
            continue
        flows.append({"addon_id": addon_id, "definition": definition})
    return flows


def _fmt_version(version: Any) -> str:
    if isinstance(version, (list, tuple)):
        return ".".join(str(v) for v in version)
    return str(version)
