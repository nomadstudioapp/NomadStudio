"""Viewer profiles ("Who's watching?") — Netflix-style picker for the app.

Named "viewer" (not "profile") deliberately: "profile" already means the
per-style preview image slots used across styles_routes.py /
workflow_style_utils.py. Keeping distinct vocabulary avoids collisions in
search and shared context between the two features.

Storage follows the same convention as import_registry.json: a single JSON
file, read/written via services.registry_service (atomic write + .json.bak
backup), not raw open()/json.load calls.
"""

from __future__ import annotations

import hashlib
import random
import re
import secrets
import uuid
from pathlib import Path
from typing import Any

from . import registry_service

VIEWERS_PATH = Path(__file__).resolve().parents[1] / "data" / "viewers.json"


def _default_viewers() -> dict[str, Any]:
    return {"viewers": []}


def _ensure_viewers() -> dict[str, Any]:
    return registry_service.ensure_registry(VIEWERS_PATH, _default_viewers())


def _save_viewers(data: dict[str, Any]) -> None:
    registry_service.save_registry(VIEWERS_PATH, data)


def _hash_pin(pin: str, salt: str) -> str:
    return hashlib.sha256((salt + pin).encode("utf-8")).hexdigest()


_AVATAR_EXTENSIONS = (".webp", ".png", ".jpg", ".jpeg")

# Fallback when the bionic set is missing — an avatar that ships with the app.
AGENT_AVATAR = "bionic/bio_01_salute.webp"

_BIONIC_AVATARS_DIR = Path(__file__).resolve().parents[1] / "static" / "images" / "avatars" / "bionic"


def _random_agent_avatar() -> str:
    """Pick one of the bionic-raccoon avatars at random for a new agent
    (see app/images/originals/avatars_bionic/ for how the set was generated).
    Falls back to AGENT_AVATAR if the bionic set is missing for some reason
    (e.g. a dev checkout without the generated images)."""
    try:
        files = sorted(
            f.name for f in _BIONIC_AVATARS_DIR.iterdir()
            if f.suffix.lower() in _AVATAR_EXTENSIONS
        )
    except FileNotFoundError:
        files = []
    if not files:
        return AGENT_AVATAR
    return "bionic/" + random.choice(files)


def slugify_name(text: str) -> str:
    """Same slug a viewer's name maps to for its output folder — see
    _resolve_viewer_output_dir() in models_api_shared.py, which this must
    stay consistent with (kept here as the single source of truth)."""
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:50] or "viewer"


def list_viewers() -> list[dict[str, Any]]:
    """Public view of human viewers — never includes pin_hash/pin_salt."""
    data = _ensure_viewers()
    return [
        {
            "id": v["id"],
            "name": v["name"],
            "avatar": v["avatar"],
            "is_owner": v.get("is_owner", False),
            "has_pin": bool(v.get("pin_hash")),
        }
        for v in data["viewers"]
        if not v.get("is_agent", False) and not v.get("is_vanish", False)
    ]


def list_agent_viewers() -> list[dict[str, Any]]:
    """Public view of agent viewers (MCP connections) — no pins, no security.
    Includes ``slug`` (their Album folder name and the ``?viewer=`` value
    that lets a plain link show their images without a session) and
    ``avatar`` (one of the bionic-raccoon set, picked at random when the
    agent was created — see _random_agent_avatar())."""
    data = _ensure_viewers()
    return [
        {
            "id": v["id"],
            "name": v["name"],
            "slug": slugify_name(v["name"]),
            "avatar": v.get("avatar") or AGENT_AVATAR,
        }
        for v in data["viewers"]
        if v.get("is_agent", False)
    ]


VANISH_AVATAR = "vanish.webp"
VANISH_NAME = "Vanish Session"


def get_or_create_vanish_viewer() -> dict[str, Any]:
    """The singleton ephemeral profile — one fixed record, never duplicated,
    always the same id. Its generations are never written to disk (see
    _active_viewer_is_vanish() in models_api_shared.py) — this entry only
    exists so the rest of the codebase (Tray/album lookups that expect a
    real viewer to resolve a folder) degrades the same way it already does
    for "no active viewer", instead of hitting a viewer_id that resolves to
    nothing at all."""
    data = _ensure_viewers()
    existing = next((v for v in data["viewers"] if v.get("is_vanish", False)), None)
    if existing:
        return existing

    viewer: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": VANISH_NAME,
        "avatar": VANISH_AVATAR,
        "is_owner": False,
        "is_agent": False,
        "is_vanish": True,
        "pin_hash": None,
        "pin_salt": None,
    }
    data["viewers"].append(viewer)
    _save_viewers(data)
    return viewer


def create_agent_viewer(name: str) -> dict[str, Any]:
    """Create a new agent viewer for an MCP connection. No pin, no security —
    agents are trusted local processes, not human accounts. Gets a random
    bionic-raccoon avatar (distinct from the plain avatars humans pick)."""
    return create_viewer(name, _random_agent_avatar(), pin=None, is_agent=True)


def get_viewer(viewer_id: str) -> dict[str, Any] | None:
    data = _ensure_viewers()
    return next((v for v in data["viewers"] if v["id"] == viewer_id), None)


def get_agent_viewer_by_slug(slug: str) -> dict[str, Any] | None:
    """Resolve an agent viewer by its slug (e.g. "claude-desktop-test") —
    shorter and more readable than the raw uuid for links shown in chat."""
    data = _ensure_viewers()
    return next(
        (v for v in data["viewers"] if v.get("is_agent", False) and slugify_name(v["name"]) == slug),
        None,
    )


def create_viewer(name: str, avatar: str, pin: str | None, is_agent: bool = False) -> dict[str, Any]:
    data = _ensure_viewers()
    human_viewers = [v for v in data["viewers"] if not v.get("is_agent", False)]

    viewer: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": name,
        "avatar": avatar,
        "is_owner": (not is_agent) and len(human_viewers) == 0,
        "is_agent": is_agent,
        "pin_hash": None,
        "pin_salt": None,
    }

    if pin:
        salt = secrets.token_hex(8)
        viewer["pin_salt"] = salt
        viewer["pin_hash"] = _hash_pin(pin, salt)

    data["viewers"].append(viewer)
    _save_viewers(data)
    return viewer


def verify_pin(viewer_id: str, pin: str) -> bool:
    viewer = get_viewer(viewer_id)
    if not viewer or not viewer.get("pin_hash"):
        return False
    return _hash_pin(pin, viewer["pin_salt"]) == viewer["pin_hash"]


def list_available_avatars(avatars_dir: Path) -> list[str]:
    if not avatars_dir.is_dir():
        return []
    return sorted(
        f.name for f in avatars_dir.iterdir()
        if f.suffix.lower() in _AVATAR_EXTENSIONS and f.stem != "vanish"  # reserved for Vanish Session
    )
