"""Server-side persistence for Depots — a named set of backgrounds,
characters, images and flows tied to one story/idea (see library.js's
CATEGORIES 'depot' entry). Always private to the viewer who created it: no
"shared" scope like Sessions have, since a Depot is explicitly personal.

Storage follows the same convention as sessions.json / viewers.json: a
single JSON file, read/written via services.registry_service (atomic write
+ .json.bak backup).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .. import paths
from . import registry_service

DEPOTS_PATH = paths.data_file("depots.json")

# What a generated image gets classified as when it's added to the active
# depot. "character"/"background"/"asset" come from the manual "Send to
# Depot" picker on a result card; "flow" is written automatically for every
# generation while a depot is active (see flow-gallery.js's addToFeed) — no
# manual picking involved. "style" comes from Build › Styles' save-to-Depot
# button and carries a ``ref`` to the style ({styleId, name, category...}).
ITEM_CATEGORIES = ("character", "background", "asset", "flow", "style")


def _default_depots() -> dict[str, Any]:
    return {"depots": []}


def _ensure_depots() -> dict[str, Any]:
    return registry_service.ensure_registry(DEPOTS_PATH, _default_depots())


def _save_depots(data: dict[str, Any]) -> None:
    registry_service.save_registry(DEPOTS_PATH, data)


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    return s[:60] or "depot"


# "active" is a reserved path segment (GET/POST /api/depots/active[/items]
# in depots_routes.py) — a depot slugged exactly "active" would be
# unreachable by id, so it's treated as already-taken here.
_RESERVED_IDS = {"active"}


def _unique_slug(base: str, existing_ids: set[str]) -> str:
    if base not in existing_ids and base not in _RESERVED_IDS:
        return base
    n = 2
    while f"{base}-{n}" in existing_ids or f"{base}-{n}" in _RESERVED_IDS:
        n += 1
    return f"{base}-{n}"


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def visible_to(depot: dict[str, Any], viewer_id: str | None) -> bool:
    """A depot is only ever visible to the viewer who owns it — unlike
    Sessions there's no shared/global scope."""
    owner = depot.get("ownerViewerId")
    return bool(owner) and bool(viewer_id) and owner == viewer_id


def list_depots(viewer_id: str | None) -> list[dict[str, Any]]:
    data = _ensure_depots()
    return [d for d in data["depots"] if visible_to(d, viewer_id)]


def get_depot(depot_id: str, viewer_id: str | None) -> dict[str, Any] | None:
    data = _ensure_depots()
    d = next((x for x in data["depots"] if x.get("id") == depot_id), None)
    if d is None or not visible_to(d, viewer_id):
        return None
    return d


def create_depot(payload: dict[str, Any], viewer_id: str | None) -> dict[str, Any]:
    """Create a new depot. Requires a logged-in viewer — a depot with no
    owner would be visible to nobody, which is never useful."""
    if not viewer_id:
        raise ValueError("A viewer must be logged in to create a Depot")

    data = _ensure_depots()
    name = str(payload.get("name") or "").strip() or "Untitled Depot"
    description = str(payload.get("description") or "").strip()
    existing_ids = {d.get("id") for d in data["depots"]}
    slug = _unique_slug(_slugify(name), existing_ids)

    depot = {
        "id": slug,
        "name": name,
        "description": description,
        "createdAt": _now_iso(),
        "ownerViewerId": viewer_id,
    }
    data["depots"].append(depot)
    _save_depots(data)
    return depot


def update_depot(
    depot_id: str, patch: dict[str, Any], viewer_id: str | None
) -> dict[str, Any] | None:
    data = _ensure_depots()
    idx = next(
        (i for i, x in enumerate(data["depots"]) if x.get("id") == depot_id), None
    )
    if idx is None or not visible_to(data["depots"][idx], viewer_id):
        return None
    d = data["depots"][idx]
    if "name" in patch:
        d["name"] = str(patch["name"] or "").strip() or d["name"]
    if "description" in patch:
        d["description"] = str(patch["description"] or "").strip()
    data["depots"][idx] = d
    _save_depots(data)
    return d


def add_item(
    depot_id: str,
    viewer_id: str | None,
    category: str,
    url: str,
    caption: str = "",
    source_url: str = "",
    ref: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Attach a generated image to a depot under one of ITEM_CATEGORIES —
    the "Send to Depot" action on a generation result card. Returns the new
    item, or None if the depot doesn't exist / isn't owned by this viewer /
    the category is invalid.

    source_url is the page (flow or Session) the item was sent from —
    window.location.href at send time, see flow-gallery.js — so the Depot
    detail view's "Open flow" button (issue #57) has somewhere to go back
    to. Items sent before this field existed just won't have one."""
    if category not in ITEM_CATEGORIES:
        return None
    data = _ensure_depots()
    idx = next(
        (i for i, x in enumerate(data["depots"]) if x.get("id") == depot_id), None
    )
    if idx is None or not visible_to(data["depots"][idx], viewer_id):
        return None
    d = data["depots"][idx]
    d.setdefault("items", [])
    item = {
        "id": f"{depot_id}-item-{len(d['items']) + 1}-{int(_now_ms())}",
        "category": category,
        "url": str(url or ""),
        "caption": str(caption or "").strip(),
        "sourceUrl": str(source_url or "").strip(),
        "addedAt": _now_iso(),
    }
    if ref:
        item["ref"] = ref
    d["items"].append(item)
    data["depots"][idx] = d
    _save_depots(data)
    return item


# Which field of ``ref`` identifies the Build entity an item points at.
# Styles by numeric id; Characters/Backgrounds by keyword — the same keyword
# flows use, so a Depot character is a real Build character, not a snapshot.
REF_KEYS = {"style": "styleId", "character": "keyword", "background": "keyword"}


def find_item_by_ref(
    depot_id: str, viewer_id: str | None, category: str, ref_id: str
) -> dict[str, Any] | None:
    """The item of ``category`` whose ``ref`` points at ``ref_id`` (e.g. a
    style already saved in this depot), or None."""
    ref_key = REF_KEYS.get(category)
    if not ref_key:
        return None
    depot = get_depot(depot_id, viewer_id)
    for item in (depot or {}).get("items") or []:
        if item.get("category") == category and str((item.get("ref") or {}).get(ref_key)) == str(ref_id):
            return item
    return None


def set_item_ref(
    depot_id: str, viewer_id: str | None, item_id: str, ref: dict[str, Any], url: str = ""
) -> dict[str, Any] | None:
    """Link an existing item to a Build entity — an image-only Character or
    Background sent before items carried a ``ref`` becomes the real one it
    was just made into. Returns the updated item, or None if not found."""
    data = _ensure_depots()
    d = next((x for x in data["depots"] if x.get("id") == depot_id), None)
    if d is None or not visible_to(d, viewer_id):
        return None
    item = next((it for it in d.get("items") or [] if it.get("id") == item_id), None)
    if item is None:
        return None
    item["ref"] = ref
    if url:
        item["url"] = url
    _save_depots(data)
    return item


def rename_ref_keyword(category: str, old: str, new: str) -> int:
    """A Build Character/Background was renamed (its keyword is also its
    image's file name): repoint every depot item that referenced it, in every
    viewer's depots. Returns how many items changed."""
    data = _ensure_depots()
    changed = 0
    for d in data["depots"]:
        for item in d.get("items") or []:
            ref = item.get("ref") or {}
            if item.get("category") == category and ref.get("keyword") == old:
                ref["keyword"] = new
                item["url"] = f"/static/images/{category}s/{new}.png"
                changed += 1
    if changed:
        _save_depots(data)
    return changed


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


def delete_depot(depot_id: str, viewer_id: str | None) -> bool:
    data = _ensure_depots()
    d = next((x for x in data["depots"] if x.get("id") == depot_id), None)
    if d is None or not visible_to(d, viewer_id):
        return False
    data["depots"] = [x for x in data["depots"] if x.get("id") != depot_id]
    _save_depots(data)
    return True
