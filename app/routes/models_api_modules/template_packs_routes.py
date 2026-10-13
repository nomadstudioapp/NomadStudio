from __future__ import annotations

import base64
import json
import logging
import re
import threading
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from flask import jsonify, request

from app import paths
from app.routes.models_api_shared import models_api_bp

logger = logging.getLogger(__name__)

_TEMPLATE_PACKS_PATH = paths.data_file("template_packs.json")
_FIELD_VALUES_PATH = paths.data_file("template_pack_field_values.json")
_STATIC_IMAGES_DIR = paths.IMAGES_DIR
_TEMPLATE_PACKS_IMAGES_DIR = _STATIC_IMAGES_DIR / "template_packs"
_template_packs_cache: list[dict[str, Any]] | None = None
_field_values_cache: dict[str, dict[str, dict[str, list[str]]]] | None = None
_packages_lock = threading.Lock()
_DATA_URL_RE = re.compile(r"^data:image/(?P<ext>[a-zA-Z0-9.+-]+);base64,(?P<data>.+)$", re.DOTALL)


def _load_template_packs() -> list[dict[str, Any]]:
    global _template_packs_cache
    if _template_packs_cache is not None:
        return _template_packs_cache
    try:
        with open(_TEMPLATE_PACKS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        _template_packs_cache = data if isinstance(data, list) else []
    except FileNotFoundError:
        # No template packs installed yet (empty install): nothing to load.
        _template_packs_cache = []
    except Exception:
        logger.exception("Failed to load template packs")
        _template_packs_cache = []
    return _template_packs_cache


def _save_template_packs(items: list[dict[str, Any]]) -> None:
    global _template_packs_cache
    _TEMPLATE_PACKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_TEMPLATE_PACKS_PATH, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)
    _template_packs_cache = items


def _load_field_values() -> dict[str, dict[str, dict[str, list[str]]]]:
    global _field_values_cache
    if _field_values_cache is not None:
        return _field_values_cache
    try:
        with open(_FIELD_VALUES_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        _field_values_cache = data if isinstance(data, dict) else {}
    except FileNotFoundError:
        # A new install has none yet: written with the first value saved.
        # Not an error (its traceback showed in the terminal at first start).
        _field_values_cache = {}
    except Exception:
        logger.exception("Failed to load template pack field values")
        _field_values_cache = {}
    return _field_values_cache


def _save_field_values(data: dict[str, dict[str, dict[str, list[str]]]]) -> None:
    global _field_values_cache
    _FIELD_VALUES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_FIELD_VALUES_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    _field_values_cache = data


def _coerce_id(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _slugify_pack_name(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "pack"


def _decode_image_data_url(data_url: str) -> tuple[bytes, str] | None:
    match = _DATA_URL_RE.match(str(data_url or "").strip())
    if not match:
        return None
    ext = match.group("ext").lower()
    if ext == "jpeg":
        ext = "jpg"
    try:
        return base64.b64decode(match.group("data")), ext
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Template packs contributed by packages (PACKAGE_FORMAT.md §10.1)
# ---------------------------------------------------------------------------
# A package theme becomes one template_packs.json entry per example image
# (the picker shows one card per example), tagged `package` + `package_key`
# ("<theme key>#<n>") — that pair, never the name, is what later installs
# match on. Images are served from the package folder (`url`); the theme's
# field values go into template_pack_field_values.json under its pack/theme
# names. What the user edits is never overwritten: `package_edited` on an
# entry (text or images), `package_values_edited` on the theme's entries
# (field values). An edited entry the package no longer provides stays as
# the user's own.

def _package_image_url(pkg_id: str, rel: str, version: str) -> str:
    # ?v= busts the year-long immutable cache /packages/ files get.
    return f"/packages/{quote(pkg_id)}/{quote(rel)}" + (f"?v={quote(version)}" if version else "")


def _user_images(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Images the user added (stored under data/images) — not the package's."""
    return [img for img in entry.get("images") or [] if isinstance(img, dict) and not img.get("url")]


def _detach_template(entry: dict[str, Any]) -> None:
    for key in ("package", "package_key", "package_edited", "package_values_edited"):
        entry.pop(key, None)
    # Images served from the package folder vanish with it.
    entry["images"] = _user_images(entry)


def _package_themes(items: list[dict[str, Any]], pkg_id: str) -> set[tuple[str, str]]:
    return {(str(it.get("pack", "")), str(it.get("theme", ""))) for it in items if it.get("package") == pkg_id}


def _prune_field_values(before: set[tuple[str, str]], items: list[dict[str, Any]]) -> None:
    """Drop the field values of package themes no entry uses any more."""
    in_use = {(str(it.get("pack", "")), str(it.get("theme", ""))) for it in items}
    gone = before - in_use
    if not gone:
        return
    values = _load_field_values()
    for pack, theme in gone:
        values.get(pack, {}).pop(theme, None)
        if pack in values and not values[pack]:
            del values[pack]
    _save_field_values(values)


def sync_package_template_packs(pkg_id: str, pkg_dir: Path, manifest: dict[str, Any]) -> dict[str, int]:
    """Merge a just-installed package's template themes into
    template_packs.json and their values into template_pack_field_values.json."""
    from app.services import package_service
    from app.services.package_service import template_entry_name, text_for

    default_lang = str(manifest.get("default_lang") or "en")
    version = str(manifest.get("version") or "")
    incoming = package_service.load_package_template_packs(pkg_dir, manifest)
    # `replaces`: older packs whose themes moved into this one are adopted by
    # key — same ids, same edits — so regrouping packs never duplicates them.
    replaces = {str(p) for p in (manifest.get("replaces") or []) if str(p) and str(p) != pkg_id}
    added = updated = removed = 0
    with _packages_lock:
        items = [dict(it) for it in _load_template_packs()]
        incoming_keys = {
            f"{t.get('key')}#{i}" for t in incoming for i in range(1, len(t.get("images") or []) + 1)
        }
        for it in items:
            if it.get("package") in replaces and it.get("package_key") in incoming_keys:
                it["package"] = pkg_id
        before = _package_themes(items, pkg_id)
        by_key = {it.get("package_key"): it for it in items if it.get("package") == pkg_id}
        max_id = max((_coerce_id(it.get("id")) or 0 for it in items), default=0)
        values = _load_field_values()
        values_changed = False
        seen: set[str] = set()
        for theme in incoming:
            pack_name = text_for(theme.get("pack"), default_lang, default_lang)
            theme_name = text_for(theme.get("theme"), default_lang, default_lang)
            images = [img for img in theme.get("images") or [] if isinstance(img, dict)]
            theme_entries = []
            for i, img in enumerate(images, start=1):
                pkg_key = f"{theme.get('key')}#{i}"
                if pkg_key in seen:
                    continue
                seen.add(pkg_key)
                text = {
                    "name": template_entry_name(theme_name, i, len(images)),
                    "pack": pack_name,
                    "theme": theme_name,
                    "template": str(theme.get("template", "")).strip(),
                }
                package_image = {
                    "filename": "",
                    "url": _package_image_url(pkg_id, str(img.get("file", "")), version),
                    "prompt": str(img.get("prompt", "") or ""),
                }
                entry = by_key.get(pkg_key)
                if entry is None:
                    max_id += 1
                    entry = {"id": max_id, **text, "images": [package_image],
                             "package": pkg_id, "package_key": pkg_key}
                    items.append(entry)
                    added += 1
                else:
                    if not entry.get("package_edited"):
                        entry.update(text)
                        updated += 1
                    entry["images"] = [package_image, *_user_images(entry)]
                theme_entries.append(entry)
            if not any(e.get("package_values_edited") for e in theme_entries):
                theme_values = {k: list(v) for k, v in (theme.get("values") or {}).items()}
                if values.get(pack_name, {}).get(theme_name) != theme_values:
                    values.setdefault(pack_name, {})[theme_name] = theme_values
                    values_changed = True
        kept: list[dict[str, Any]] = []
        for it in items:
            if it.get("package") == pkg_id and it.get("package_key") not in seen:
                if it.get("package_edited") or _user_images(it):
                    _detach_template(it)
                else:
                    removed += 1
                    continue
            kept.append(it)
        if values_changed:
            _save_field_values(values)
        _save_template_packs(kept)
        _prune_field_values(before, kept)
    return {"added": added, "updated": updated, "removed": removed}


def remove_package_template_packs(pkg_id: str) -> dict[str, int]:
    """Uninstall: drop the package's templates, except those the user edited
    or added images to — those stay as the user's own."""
    removed = kept_count = 0
    with _packages_lock:
        items = [dict(it) for it in _load_template_packs()]
        before = _package_themes(items, pkg_id)
        if not before:
            return {"removed": 0, "kept": 0}
        kept: list[dict[str, Any]] = []
        for it in items:
            if it.get("package") == pkg_id:
                if it.get("package_edited") or _user_images(it):
                    _detach_template(it)
                    kept_count += 1
                else:
                    removed += 1
                    continue
            kept.append(it)
        _save_template_packs(kept)
        _prune_field_values(before, kept)
    return {"removed": removed, "kept": kept_count}


@models_api_bp.get("/template-packs")
def list_template_packs():
    return jsonify({"templatePacks": _load_template_packs()})


@models_api_bp.post("/template-packs")
def create_template_pack():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    items = _load_template_packs()
    max_id = max((_coerce_id(it.get("id")) or 0 for it in items), default=0)
    record = {
        "id": max_id + 1,
        "name": name,
        "pack": str(payload.get("pack", "") or "").strip(),
        "theme": str(payload.get("theme", "") or "").strip(),
        "template": str(payload.get("template", "") or "").strip(),
        "images": [],
    }
    items.append(record)
    _save_template_packs(items)
    return jsonify({"ok": True, "templatePack": record}), 201


@models_api_bp.patch("/template-packs/<int:pack_id>")
def update_template_pack(pack_id: int):
    payload = request.get_json(silent=True) or {}
    EDITABLE_KEYS = {"name", "pack", "theme", "template"}
    updates = {k: str(v or "").strip() for k, v in payload.items() if k in EDITABLE_KEYS}
    if not updates:
        return jsonify({"error": "No editable fields provided"}), 400

    items = _load_template_packs()
    target = next((it for it in items if _coerce_id(it.get("id")) == pack_id), None)
    if target is None:
        return jsonify({"error": f"Template {pack_id} not found"}), 404

    target.update(updates)
    if target.get("package"):
        target["package_edited"] = True
    _save_template_packs(items)
    return jsonify({"ok": True, "templatePack": target})


@models_api_bp.delete("/template-packs/<int:pack_id>")
def delete_template_pack(pack_id: int):
    items = _load_template_packs()
    target = next((it for it in items if _coerce_id(it.get("id")) == pack_id), None)
    if target is None:
        return jsonify({"error": f"Template {pack_id} not found"}), 404

    items = [it for it in items if _coerce_id(it.get("id")) != pack_id]
    _save_template_packs(items)
    return jsonify({"ok": True, "id": pack_id})


@models_api_bp.post("/template-packs/<int:pack_id>/images")
def add_template_pack_image(pack_id: int):
    payload = request.get_json(silent=True) or {}
    image_data_url = str(payload.get("imageDataUrl", "") or "").strip()
    prompt = str(payload.get("prompt", "") or "").strip()
    if not image_data_url:
        return jsonify({"error": "imageDataUrl is required"}), 400

    decoded = _decode_image_data_url(image_data_url)
    if decoded is None:
        return jsonify({"error": "Could not decode image data"}), 400
    raw_bytes, ext = decoded

    items = _load_template_packs()
    target = next((it for it in items if _coerce_id(it.get("id")) == pack_id), None)
    if target is None:
        return jsonify({"error": f"Template {pack_id} not found"}), 404

    pack_slug = _slugify_pack_name(target.get("pack", ""))
    pack_dir = _TEMPLATE_PACKS_IMAGES_DIR / pack_slug
    pack_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{pack_id}_{uuid.uuid4().hex[:8]}.{ext}"
    (pack_dir / filename).write_bytes(raw_bytes)

    images = target.get("images")
    if not isinstance(images, list):
        images = []
    images.append({"filename": f"template_packs/{pack_slug}/{filename}", "prompt": prompt})
    target["images"] = images
    _save_template_packs(items)
    return jsonify({"ok": True, "templatePack": target}), 201


@models_api_bp.delete("/template-packs/<int:pack_id>/images/<int:image_index>")
def delete_template_pack_image(pack_id: int, image_index: int):
    items = _load_template_packs()
    target = next((it for it in items if _coerce_id(it.get("id")) == pack_id), None)
    if target is None:
        return jsonify({"error": f"Template {pack_id} not found"}), 404

    images = target.get("images")
    if not isinstance(images, list) or image_index < 0 or image_index >= len(images):
        return jsonify({"error": "Image index out of range"}), 404

    removed = images.pop(image_index)
    if target.get("package"):
        target["package_edited"] = True
    filename = str(removed.get("filename", "") or "").strip()
    # A package image (`url`) lives in the package folder: only unlisted here.
    if filename and not removed.get("url"):
        try:
            file_path = (_STATIC_IMAGES_DIR / filename).resolve()
            file_path.relative_to(_STATIC_IMAGES_DIR.resolve())  # guard against path traversal
            if file_path.is_file():
                file_path.unlink()
        except Exception:
            logger.warning("Failed deleting template image file: %s", filename)

    target["images"] = images
    _save_template_packs(items)
    return jsonify({"ok": True, "templatePack": target})


@models_api_bp.get("/template-packs/field-values/<path:pack>/<path:theme>")
def get_template_pack_field_values(pack: str, theme: str):
    all_values = _load_field_values()
    pack_values = all_values.get(pack, {})
    return jsonify({"pack": pack, "theme": theme, "values": pack_values.get(theme, {})})


@models_api_bp.put("/template-packs/field-values/<path:pack>/<path:theme>")
def update_template_pack_field_values(pack: str, theme: str):
    payload = request.get_json(silent=True) or {}
    raw_values = payload.get("values")
    if not isinstance(raw_values, dict):
        return jsonify({"error": "values must be an object"}), 400

    clean: dict[str, list[str]] = {}
    for key, values in raw_values.items():
        if not isinstance(values, list):
            continue
        clean[str(key)] = [str(v).strip() for v in values if str(v).strip()]

    all_values = _load_field_values()
    all_values.setdefault(pack, {})[theme] = clean
    _save_field_values(all_values)
    # Values of a package theme the user changed are theirs from now on.
    items = _load_template_packs()
    marked = False
    for it in items:
        if it.get("package") and it.get("pack") == pack and it.get("theme") == theme:
            it["package_values_edited"] = True
            marked = True
    if marked:
        _save_template_packs(items)
    return jsonify({"ok": True, "pack": pack, "theme": theme, "values": clean})
