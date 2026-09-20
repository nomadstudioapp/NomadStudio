"""Where Nomad Studio keeps the user's data — outside the program folder.

The program folder (the portable ``NomadStudio/`` a user unzips) can be
deleted or replaced by an update at any time, so nothing the user creates
lives inside it (docs/APP_UPDATES.md §8):

- portable build (``portable.json`` next to app.py): ``~/Nomad Studio/data``,
  next to the default image output folder ``~/Nomad Studio``
- source checkout: ``<repo>/data`` (git-ignored), so a development copy never
  mixes its data with an installed Nomad Studio on the same machine
- ``NOMAD_DATA_DIR`` overrides both (tests, several installs side by side)

Layout of the data folder::

    import_registry.json       settings, engines, installed packs
    viewers.json, sessions.json, depots.json, styles.json, …  (app stores)
    packages/                  installed packages + index.json
    stories/, story_benchmarks/, vision_benchmarks/
    images/styles|characters|backgrounds|template_packs|workflow_logos|originals
    updates/                   update staging and results
    version.json               data_schema of this folder

Before this module the same files lived inside the app package
(``app/data``, ``app/workflows/import_registry.json``, ``app/images/…``,
``app/static/images/…``). ``migrate_legacy_data`` moves them here once.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent  # the ``app`` Python package (shipped code and assets)
REPO_DIR = APP_DIR.parent  # app.py, portable.json, bundled-packages/
IS_PORTABLE = (REPO_DIR / "portable.json").is_file()

DATA_SCHEMA = 1

# Files shipped in app/data that the app reads as defaults (versioned in git).
SEED_FILES = ("sfw_characters.json", "sfw_backgrounds.json")


def _resolve_data_dir() -> Path:
    override = os.getenv("NOMAD_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if IS_PORTABLE:
        return Path.home() / "Nomad Studio" / "data"
    return REPO_DIR / "data"


DATA_DIR = _resolve_data_dir()
REGISTRY_PATH = DATA_DIR / "import_registry.json"
PACKAGES_DIR = DATA_DIR / "packages"
IMAGES_DIR = DATA_DIR / "images"
UPDATES_DIR = DATA_DIR / "updates"
# Release builds place the package ZIPs next to the portable app. In a source
# checkout those ZIPs are generated under dist/packages instead; using that
# directory as a development fallback keeps the same startup/install path as a
# release without committing generated binaries to git.
_RELEASE_BUNDLED_PACKAGES_DIR = REPO_DIR / "bundled-packages"
_DEV_BUNDLED_PACKAGES_DIR = REPO_DIR / "dist" / "packages"
BUNDLED_PACKAGES_DIR = (
    _RELEASE_BUNDLED_PACKAGES_DIR
    if _RELEASE_BUNDLED_PACKAGES_DIR.is_dir()
    else _DEV_BUNDLED_PACKAGES_DIR
)


def data_file(name: str) -> Path:
    return DATA_DIR / name


def user_images(kind: str) -> Path:
    """images/styles, images/characters, images/backgrounds, …"""
    return IMAGES_DIR / kind


def default_backup_dir() -> Path:
    """Next to the data folder (``~/Nomad Studio/backups``), never inside
    the program folder."""
    return DATA_DIR.parent / "backups"


# Legacy location (relative to the app package) → location in the data folder.
LEGACY_LOCATIONS: tuple[tuple[str, str], ...] = (
    ("workflows/import_registry.json", "import_registry.json"),
    ("workflows/import_registry.json.bak", "import_registry.json.bak"),
    ("images/styles", "images/styles"),
    ("images/originals", "images/originals"),
    ("static/images/characters", "images/characters"),
    ("static/images/backgrounds", "images/backgrounds"),
    ("static/images/template_packs", "images/template_packs"),
)


def legacy_to_data(rel: str) -> str | None:
    """Map a path relative to the old app package (as stored in backups made
    before the data folder existed) to its place in the data folder."""
    rel = rel.replace("\\", "/").lstrip("/")
    for old, new in LEGACY_LOCATIONS:
        if rel == old or rel.startswith(old + "/"):
            return new + rel[len(old):]
    if rel == "images/workflow_logos" or rel.startswith("images/workflow_logos/"):
        return rel
    if rel.startswith("data/"):
        return rel[len("data/"):]
    return None


def _legacy_has_user_data(app_dir: Path) -> bool:
    if (app_dir / "workflows" / "import_registry.json").is_file():
        return True
    data = app_dir / "data"
    return data.is_dir() and any(p.name not in SEED_FILES for p in data.iterdir())


def _move(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir() and dest.is_dir():
        for child in list(src.iterdir()):
            if not (dest / child.name).exists() or child.is_dir():
                _move(child, dest / child.name)
        try:
            src.rmdir()
        except OSError:
            pass
        return
    if dest.exists():
        logger.warning("data migration: %s already exists, left %s in place", dest, src)
        return
    shutil.move(str(src), str(dest))


def migrate_legacy_data(app_dir: Path = APP_DIR, data_dir: Path | None = None) -> dict[str, Any]:
    """Move data from inside the app package to the data folder. Runs once:
    only when the old location has user data and the data folder has no
    registry yet. Never overwrites anything in the data folder."""
    data_dir = data_dir or DATA_DIR
    result: dict[str, Any] = {"migrated": False, "moved": []}
    if (data_dir / "import_registry.json").exists() or not _legacy_has_user_data(app_dir):
        return result
    data_dir.mkdir(parents=True, exist_ok=True)
    for old, new in LEGACY_LOCATIONS:
        src = app_dir / old
        if src.exists():
            _move(src, data_dir / new)
            result["moved"].append(old)
    legacy_data = app_dir / "data"
    if legacy_data.is_dir():
        for child in list(legacy_data.iterdir()):
            if child.name in SEED_FILES:
                # Versioned defaults stay with the program; the user's copy goes along.
                if not (data_dir / child.name).exists():
                    shutil.copy2(child, data_dir / child.name)
                continue
            _move(child, data_dir / child.name)
            result["moved"].append(f"data/{child.name}")
    logos = app_dir / "images" / "workflow_logos"
    if logos.is_dir():
        for logo in logos.iterdir():
            target = data_dir / "images" / "workflow_logos" / logo.name
            if logo.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(logo, target)
    result["migrated"] = True
    result["from"] = str(app_dir)
    logger.info("data migration: moved %s from %s to %s", ", ".join(result["moved"]) or "nothing", app_dir, data_dir)
    return result


def fix_pack_dirs(registry: dict[str, Any], packages_dir: Path | None = None) -> bool:
    """installedPacks store an absolute packDir; point them at the current
    packages folder (after a migration, or if the data folder moved)."""
    packages_dir = packages_dir or PACKAGES_DIR
    changed = False
    for pack in registry.get("installedPacks") or []:
        if not isinstance(pack, dict):
            continue
        pack_id = str(pack.get("packId") or "")
        current = packages_dir / pack_id
        if pack_id and current.is_dir() and pack.get("packDir") != str(current):
            pack["packDir"] = str(current)
            changed = True
    return changed


def prepare_data_dir(app_dir: Path = APP_DIR, data_dir: Path | None = None) -> dict[str, Any]:
    """Startup: create the data folder, migrate old data, add missing seeds
    and shipped workflow logos, record the data schema."""
    data_dir = data_dir or DATA_DIR
    result = migrate_legacy_data(app_dir, data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in SEED_FILES:
        seed = app_dir / "data" / name
        if seed.is_file() and not (data_dir / name).exists():
            shutil.copy2(seed, data_dir / name)
    shipped_logos = app_dir / "images" / "workflow_logos"
    if shipped_logos.is_dir():
        for logo in shipped_logos.iterdir():
            target = data_dir / "images" / "workflow_logos" / logo.name
            if logo.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(logo, target)
    version_file = data_dir / "version.json"
    info: dict[str, Any] = {}
    if version_file.is_file():
        try:
            info = json.loads(version_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
    if info.get("data_schema") != DATA_SCHEMA or result["migrated"]:
        info["data_schema"] = DATA_SCHEMA
        if result["migrated"]:
            info["migrated_from"] = result["from"]
        version_file.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return result
