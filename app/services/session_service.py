"""Server-side persistence for Sessions (formerly called "Bundles").

Historically Sessions lived only in browser localStorage (see
static/js/services/session-store.js), which meant a session created in one
browser was invisible in another. This module gives them a real home on the
server so they can be scoped either to a single viewer ("user") or shared
with everyone ("all"), and therefore show up for that viewer regardless of
which browser/device they're using.

Storage follows the same convention as viewers.json / import_registry.json:
a single JSON file, read/written via services.registry_service (atomic
write + .json.bak backup).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from .. import paths
from . import registry_service

SESSIONS_PATH = paths.data_file("sessions.json")

SCOPE_ALL = "all"
SCOPE_USER = "user"

# Serializes each read-modify-write of sessions.json. The browser and the MCP
# server (NomadStudio#24) both write it; without the lock two near-simultaneous
# writes each start from their own copy and the second one drops the first.
_lock = threading.RLock()


def now_ms() -> int:
    """Server clock, in ms. Stamped on appended steps (``addedAt``) and handed
    to clients as ``serverTime`` so they can say how fresh their copy is."""
    return int(time.time() * 1000)


def _default_sessions() -> dict[str, Any]:
    return {"sessions": []}


def _ensure_sessions() -> dict[str, Any]:
    return registry_service.ensure_registry(SESSIONS_PATH, _default_sessions())


def _save_sessions(data: dict[str, Any]) -> None:
    registry_service.save_registry(SESSIONS_PATH, data)


def _slugify(name: str) -> str:
    import re

    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
    return (s[:40] or "session")


def visible_to(session: dict[str, Any], viewer_id: str | None) -> bool:
    """A session is visible when it's shared with everyone, or owned by the
    current viewer. Sessions owned by someone else stay hidden."""
    owner = session.get("ownerViewerId")
    if not owner:
        return True  # scope=all
    return bool(viewer_id) and owner == viewer_id


def list_sessions(viewer_id: str | None) -> list[dict[str, Any]]:
    data = _ensure_sessions()
    return [b for b in data["sessions"] if visible_to(b, viewer_id)]


def get_session(session_id: str, viewer_id: str | None) -> dict[str, Any] | None:
    data = _ensure_sessions()
    b = next((x for x in data["sessions"] if x.get("id") == session_id), None)
    if b is None or not visible_to(b, viewer_id):
        return None
    return b


def _new_id() -> str:
    return "session-" + str(int(time.time() * 1000))


def create_session(
    payload: dict[str, Any], scope: str, viewer_id: str | None
) -> dict[str, Any]:
    """Create a new session. scope='user' requires a logged-in viewer — falls
    back to 'all' if nobody is logged in, so the feature degrades gracefully."""
    name = str(payload.get("name") or "Untitled Session")
    owner = viewer_id if (scope == SCOPE_USER and viewer_id) else None

    session = {
        "id": payload.get("id") or _new_id(),
        "name": name,
        "folder": payload.get("folder") or (_slugify(name) + "-" + str(int(time.time()))),
        "createdAt": payload.get("createdAt") or _now_iso(),
        "steps": payload.get("steps") or [],
        "ownerViewerId": owner,
    }
    with _lock:
        data = _ensure_sessions()
        data["sessions"].append(session)
        _save_sessions(data)
    return session


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def upsert_session(
    session_id: str, patch: dict[str, Any], viewer_id: str | None
) -> dict[str, Any] | None:
    """Update an existing (visible) session's mutable fields (name/steps/folder).
    Ownership/scope is never changed here — use duplicate_session for that.

    The browser sends the whole ``steps`` list from its own cache. With
    ``syncedAt`` (the ``serverTime`` of its last read) a step appended here
    after that moment — by the MCP, while the session was open — is one the
    client never saw, not one it deleted, so it is kept."""
    with _lock:
        data = _ensure_sessions()
        idx = next(
            (i for i, x in enumerate(data["sessions"]) if x.get("id") == session_id), None
        )
        if idx is None or not visible_to(data["sessions"][idx], viewer_id):
            return None
        b = data["sessions"][idx]
        if isinstance(patch.get("steps"), list):
            patch = dict(patch)
            patch["steps"] = _keep_unseen_steps(b.get("steps") or [], patch["steps"], patch.get("syncedAt"))
        for field in ("name", "steps", "folder"):
            if field in patch:
                b[field] = patch[field]
        data["sessions"][idx] = b
        _save_sessions(data)
    return b


def _keep_unseen_steps(current: list[Any], incoming: list[Any], synced_at: Any) -> list[Any]:
    try:
        synced = int(synced_at)
    except (TypeError, ValueError):
        return incoming  # older client: whole-list replace, as before
    incoming_ids = {s.get("id") for s in incoming if isinstance(s, dict)}
    unseen = [
        s for s in current
        if isinstance(s, dict) and s.get("id") not in incoming_ids
        and int(s.get("addedAt") or 0) > synced
    ]
    return incoming + unseen


def append_step(
    session_id: str, step: dict[str, Any], viewer_id: str | None
) -> dict[str, Any] | None:
    """Add one step to a visible session without touching the others (the MCP
    path: it never holds the whole list). The new step becomes the selected
    one, as when a flow captures its images in the app."""
    with _lock:
        data = _ensure_sessions()
        b = next((x for x in data["sessions"] if x.get("id") == session_id), None)
        if b is None or not visible_to(b, viewer_id):
            return None
        steps = b.setdefault("steps", [])
        for s in steps:
            if isinstance(s, dict):
                s["selected"] = False
        step["selected"] = True
        step["addedAt"] = now_ms()
        steps.append(step)
        _save_sessions(data)
    return b


def delete_session(session_id: str, viewer_id: str | None) -> bool:
    with _lock:
        data = _ensure_sessions()
        b = next((x for x in data["sessions"] if x.get("id") == session_id), None)
        if b is None or not visible_to(b, viewer_id):
            return False
        data["sessions"] = [x for x in data["sessions"] if x.get("id") != session_id]
        _save_sessions(data)
    return True


def duplicate_session(
    session_id: str, viewer_id: str | None
) -> dict[str, Any] | None:
    """Duplicating is always private to the current viewer — never asks,
    never shared — per product decision (a copy is always "yours")."""
    with _lock:
        data = _ensure_sessions()
        src = next((x for x in data["sessions"] if x.get("id") == session_id), None)
        if src is None or not visible_to(src, viewer_id):
            return None

        copy = {
            "id": _new_id(),
            "name": str(src.get("name") or "Untitled Session") + " (copy)",
            "folder": _slugify(src.get("name")) + "-" + str(int(time.time())),
            "createdAt": _now_iso(),
            "steps": [dict(s) for s in (src.get("steps") or [])],
            "ownerViewerId": viewer_id,  # always current viewer, regardless of source scope
        }
        data["sessions"].append(copy)
        _save_sessions(data)
    return copy


def import_session(
    payload: dict[str, Any], scope: str, viewer_id: str | None
) -> dict[str, Any]:
    """Import a session previously exported (client JSON/zip contents already
    parsed by the caller). Always gets a fresh id to avoid collisions."""
    owner = viewer_id if (scope == SCOPE_USER and viewer_id) else None
    name = str(payload.get("name") or "Imported Session")
    session = {
        "id": _new_id(),
        "name": name,
        "folder": payload.get("folder") or (_slugify(name) + "-" + str(int(time.time()))),
        "createdAt": payload.get("createdAt") or _now_iso(),
        "steps": payload.get("steps") or [],
        "ownerViewerId": owner,
    }
    with _lock:
        data = _ensure_sessions()
        data["sessions"].append(session)
        _save_sessions(data)
    return session
