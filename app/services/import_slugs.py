"""Workflow identifiers (slugs) for engines — what "--v monaco" names
(NomadStudio#27).

Every import record gets a short, unique ``slug`` (lowercase letters, digits
and dashes). Engine packages bring their own (the engine JSON's ``slug``);
anything else gets one made from its name, flagged ``slugAuto`` so a package
update may still replace it — a slug the user typed is never touched.

find() is the one lookup for "--v <ref>" in the app, the graph builder and
the MCP: exact slug, then exact name, then a piece of the name (reporting
every candidate so an ambiguous one can be pointed out).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

SLUG_MAX = 32
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:SLUG_MAX].strip("-") or "engine"


def is_valid(slug: str) -> bool:
    return bool(slug) and len(slug) <= SLUG_MAX and bool(_SLUG_RE.match(slug))


def _taken(imports: list[dict[str, Any]], exclude_id: str | None = None) -> set[str]:
    return {str(r.get("slug")) for r in imports
            if isinstance(r, dict) and r.get("slug") and str(r.get("id")) != str(exclude_id)}


def unique(base: str, imports: list[dict[str, Any]], exclude_id: str | None = None) -> str:
    taken = _taken(imports, exclude_id)
    base = slugify(base)
    if base not in taken:
        return base
    n = 2
    while f"{base[:SLUG_MAX - 4]}-{n}" in taken:
        n += 1
    return f"{base[:SLUG_MAX - 4]}-{n}"


def validation_error(slug: str, imports: list[dict[str, Any]], record_id: str | None) -> str | None:
    """English message for an unusable slug, or None."""
    if not is_valid(slug):
        return f"Use lowercase letters, numbers and dashes (up to {SLUG_MAX})."
    owner = next((r for r in imports if isinstance(r, dict) and r.get("slug") == slug
                  and str(r.get("id")) != str(record_id)), None)
    if owner:
        return f"Already used by {owner.get('name') or owner.get('id')}."
    return None


def assign(record: dict[str, Any], imports: list[dict[str, Any]], wanted: str | None = None) -> None:
    """Give ``record`` a slug: ``wanted`` (a package's) if free, else keep a
    user-typed one, else one made from its name."""
    current = str(record.get("slug") or "")
    user_set = current and not record.get("slugAuto")
    if user_set:
        return
    rid = record.get("id")
    if wanted and is_valid(wanted) and wanted not in _taken(imports, rid):
        record["slug"], record["slugAuto"] = wanted, True
        return
    if current and current not in _taken(imports, rid):
        return
    record["slug"], record["slugAuto"] = unique(record.get("name") or rid or "engine", imports, rid), True


def ensure(imports: list[dict[str, Any]]) -> bool:
    """Fill in missing slugs (records from before slugs existed). True if any changed."""
    changed = False
    for record in imports:
        if isinstance(record, dict) and not record.get("slug"):
            assign(record, imports)
            changed = True
    return changed


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().replace("-", " ").replace("_", " ").split())


def find(imports: list[dict[str, Any]], ref: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """(match, candidates) for "--v <ref>": exact slug, then exact name, then
    a piece of the name — the first of several candidates wins, and all of
    them are returned so the caller can say it was ambiguous."""
    records = [r for r in imports if isinstance(r, dict)]
    ref_slug = str(ref or "").strip().lower()
    if not ref_slug:
        return None, []
    for r in records:
        if str(r.get("slug") or "") == ref_slug:
            return r, [r]
    needle = _norm(ref)
    exact = [r for r in records if _norm(r.get("name")) == needle]
    if exact:
        return exact[0], exact
    partial = [r for r in records if needle in _norm(r.get("name")) or needle.replace(" ", "") in _norm(r.get("name")).replace(" ", "")]
    return (partial[0] if partial else None), partial
