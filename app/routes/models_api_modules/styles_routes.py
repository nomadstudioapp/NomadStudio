from __future__ import annotations

import base64
import io
import json
import logging
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from flask import jsonify, make_response, request

from app.config import (
    LMSTUDIO_MAX_OUTPUT_TOKENS,
)

from app import paths  # noqa: E402

STYLES_IMAGES_DIR = paths.user_images("styles")
from app.services import image_service, registry_service
from app.services.http_client import http_bytes, http_json
from app.services.workflow_service import (
    _coerce_int_scalar,
    _coerce_profile_slot,
    _decode_data_url_image_bytes,
    _extract_filename_from_image_url,
    _get_next_page_number,
    _get_style_page_entry,
    _get_style_profile_entry,
    _style_has_image_for_page,
    _style_has_image_for_slot,
    _style_preview_filename,
    _style_preview_page_path,
)
from app.routes.models_api_shared import (
    _ensure_registry,
    _save_registry,
    _resolve_output_dir,
    _resolve_viewer_output_dir,
    _styles_lock,
    _styles_pages_lock,
    logger,
    models_api_bp,
    STYLE_PREVIEW_FALLBACK_URL,
    STYLES_PAGES_PATH,
    STYLES_PATH,
)

# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------

def _load_styles() -> list[dict[str, Any]]:
    if not STYLES_PATH.is_file():
        return []
    try:
        raw = json.loads(STYLES_PATH.read_text("utf-8"))
    except Exception:
        logger.exception("Failed reading styles file")
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _write_styles(styles: list[dict[str, Any]]) -> None:
    STYLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    registry_service._atomic_write(STYLES_PATH, styles)


# ---------------------------------------------------------------------------
# Styles contributed by packages (PACKAGE_FORMAT.md §10.3)
# ---------------------------------------------------------------------------
# A package's styles are copied into styles.json on install so Build > Styles,
# the style pickers and per-model image generation treat them exactly like the
# user's own. Each copy is tagged with `package` + `package_key`; that pair —
# never the name — is what later installs match on, so a pack never touches
# a user style that happens to share its name. Styles are text only and
# independent of any model: images stay per model in model_images and are
# never overwritten by a package.

def _pkg_text(value: Any, lang: str) -> str:
    if isinstance(value, dict):
        return str(value.get(lang) or next(iter(value.values()), "") or "").strip()
    return str(value or "").strip()


def _user_model_images(style: dict[str, Any]) -> dict[str, Any]:
    """model_images the user generated/uploaded — not the ones a package
    brought along (those carry `package`)."""
    images = style.get("model_images")
    if not isinstance(images, dict):
        return {}
    return {k: v for k, v in images.items() if isinstance(v, dict) and v and not v.get("package")}


def _style_is_kept_by_user(style: dict[str, Any]) -> bool:
    """A package style the user edited or generated images for stays when the
    package no longer provides it — it becomes one of the user's own."""
    return bool(style.get("package_edited") or _user_model_images(style))


def _detach_from_package(style: dict[str, Any]) -> None:
    for key in ("package", "package_key", "package_edited"):
        style.pop(key, None)
    # Images served from the package folder vanish with it.
    style["model_images"] = _user_model_images(style)


def _apply_package_images(style: dict[str, Any], pkg_id: str, images: Any, version: str = "") -> None:
    """Per-model previews a package ships (§10.3 `images`), served straight
    from data/packages/<pkg>/. Never replaces an image the user made for
    that model; drops package images the new version no longer carries."""
    current = style.get("model_images")
    if not isinstance(current, dict):
        current = {}
    merged = _user_model_images({"model_images": current})
    for model_id, rel in (images or {}).items():
        model_id = str(model_id)
        if model_id in merged or not isinstance(rel, str) or not rel:
            continue
        merged[model_id] = {
            "image_filename": "",
            # ?v= busts the year-long immutable cache /packages/ files get
            # when a new package version ships a different image.
            "image_url": f"/packages/{quote(pkg_id)}/{quote(rel)}" + (f"?v={quote(version)}" if version else ""),
            "package": pkg_id,
        }
    style["model_images"] = merged


def sync_package_styles(pkg_id: str, pkg_dir: Path, manifest: dict[str, Any]) -> dict[str, int]:
    """Merge a just-installed package's styles into styles.json: new keys are
    added, untouched ones get the package's current text, keys the package
    dropped are removed (or handed over to the user, see
    _style_is_kept_by_user)."""
    from app.services import package_service

    default_lang = str(manifest.get("default_lang") or "en")
    incoming = package_service.load_package_styles(pkg_dir, manifest)
    # `replaces`: older packs whose styles moved into this one. Their styles
    # are adopted by key — same id, same edits, same per-model images — so
    # regrouping packs never duplicates a style or loses its images.
    replaces = {str(p) for p in (manifest.get("replaces") or []) if str(p) and str(p) != pkg_id}
    incoming_keys = {str(item.get("key", "")) for item in incoming}
    added = updated = removed = 0
    with _styles_lock:
        styles = _load_styles()
        for style in styles:
            if style.get("package") in replaces and style.get("package_key") in incoming_keys:
                style["package"] = pkg_id
        by_key = {s.get("package_key"): s for s in styles if s.get("package") == pkg_id}
        max_id = max((_coerce_int_scalar(s.get("id")) or 0 for s in styles), default=0)
        seen: set[str] = set()
        for item in incoming:
            key = str(item.get("key", ""))
            if not key or key in seen:
                continue
            seen.add(key)
            text = {
                "name": _pkg_text(item.get("name"), default_lang),
                "category": _pkg_text(item.get("category"), default_lang),
                "prefix": str(item.get("prefix", "") or "").strip(),
                "suffix": str(item.get("suffix", "") or "").strip(),
                "prompt": str(item.get("prompt", "") or "").strip(),
            }
            existing = by_key.get(key)
            if existing is None:
                max_id += 1
                existing = {
                    **text,
                    "image_filename": "",
                    "image_url": "",
                    "profile_images": {},
                    "page_images": {},
                    "model_images": {},
                    "package": pkg_id,
                    "package_key": key,
                    "id": max_id,
                }
                styles.append(existing)
                added += 1
            elif not existing.get("package_edited"):
                existing.update(text)
                updated += 1
            _apply_package_images(existing, pkg_id, item.get("images"), str(manifest.get("version") or ""))
        kept: list[dict[str, Any]] = []
        for style in styles:
            if style.get("package") == pkg_id and style.get("package_key") not in seen:
                if _style_is_kept_by_user(style):
                    _detach_from_package(style)
                else:
                    removed += 1
                    continue
            kept.append(style)
        _write_styles(kept)
    return {"added": added, "updated": updated, "removed": removed}


def remove_package_styles(pkg_id: str) -> dict[str, int]:
    """Uninstall: drop the package's styles, except those the user edited or
    generated images for — those stay as the user's own styles."""
    removed = kept_count = 0
    with _styles_lock:
        styles = _load_styles()
        kept: list[dict[str, Any]] = []
        for style in styles:
            if style.get("package") == pkg_id:
                if _style_is_kept_by_user(style):
                    _detach_from_package(style)
                    kept_count += 1
                else:
                    removed += 1
                    continue
            kept.append(style)
        if removed or kept_count:
            _write_styles(kept)
    return {"removed": removed, "kept": kept_count}


# ---------------------------------------------------------------------------
# Pages helpers
# ---------------------------------------------------------------------------

def _load_styles_pages() -> list[dict[str, Any]]:
    try:
        if STYLES_PAGES_PATH.is_file():
            with STYLES_PAGES_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _write_styles_pages(pages: list[dict[str, Any]]) -> None:
    STYLES_PAGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    registry_service._atomic_write(STYLES_PAGES_PATH, pages)


def _build_style_image_url(image_filename: str, safe: str = "/") -> str:
    filename = str(image_filename or "").strip()
    if not filename:
        return ""
    base = f"/api/styles/image/{quote(filename, safe=safe)}"
    try:
        resolved = (STYLES_IMAGES_DIR / filename).resolve()
        resolved.relative_to(STYLES_IMAGES_DIR.resolve())
        if resolved.is_file():
            return f"{base}?v={int(resolved.stat().st_mtime_ns)}"
    except Exception:
        pass
    return base


def _resolve_style_image_url_for_page(style: dict[str, Any], page_id: str) -> str:
    entry = _get_style_page_entry(style, page_id)
    image_filename = str(entry.get("image_filename", "") or "").strip()
    if image_filename:
        return _build_style_image_url(image_filename, safe='/')
    image_url = str(entry.get("image_url", "") or "").strip()
    if image_url:
        return image_url
    return STYLE_PREVIEW_FALLBACK_URL


def _resolve_style_image_url_for_slot(style: dict[str, Any], profile_slot: int) -> str:
    entry = _get_style_profile_entry(style, profile_slot)
    image_filename = str(entry.get("image_filename", "") or "").strip()
    if image_filename:
        return _build_style_image_url(image_filename, safe='')
    image_url = str(entry.get("image_url", "") or "").strip()
    if image_url:
        return image_url
    return STYLE_PREVIEW_FALLBACK_URL


def _load_source_image_bytes_for_style(data: dict[str, Any], image_filename: str, image_url: str) -> bytes | None:
    filename = str(image_filename or "").strip()
    if not filename:
        filename = _extract_filename_from_image_url(image_url)

    if filename:
        # Current generations (openJourneyApi.saveComfyImages, used by both
        # the Styles "Generate images" button and the real Create/Refine
        # flows) are written under the active viewer's own output subfolder
        # — see images_routes.py's serve_image route, which checks the same
        # dir first for exactly this reason. Looking only in the shared
        # output dir root (as this used to) misses every current-session
        # save and always 400s with "Style image source not found", even
        # though the file exists right there under <output>/<viewer-slug>/.
        viewer_output_dir = _resolve_viewer_output_dir(data)
        if viewer_output_dir:
            image_bytes = image_service.serve_image(viewer_output_dir, filename)
            if image_bytes:
                return image_bytes
        # Legacy fallback: pre-viewer saves living directly in the shared
        # output dir's root.
        image_bytes = image_service.serve_image(_resolve_output_dir(data), filename)
        if image_bytes:
            return image_bytes

    return _decode_data_url_image_bytes(image_url)


def _delete_style_preview_file(filename: str, output_dir: str | None = None) -> bool:
    name = str(filename or "").strip()
    if not name:
        return False

    removed = False
    targets = [STYLES_IMAGES_DIR / name]
    if output_dir:
        try:
            targets.append(Path(str(output_dir)) / name)
        except Exception:
            pass

    for path in targets:
        try:
            if path.is_file():
                path.unlink()
                removed = True
        except Exception:
            logger.warning("Failed deleting style preview file: %s", path)

    return removed


# ---------------------------------------------------------------------------
# Pages routes
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Style routes
# ---------------------------------------------------------------------------

@models_api_bp.get("/styles/pages")
def list_style_pages():
    with _styles_pages_lock:
        pages = _load_styles_pages()
    return jsonify({"pages": pages})


@models_api_bp.post("/styles/pages")
def create_style_page():
    payload = request.get_json(silent=True) or {}
    model = str(payload.get("model", "") or "").strip()
    lora_names_raw = payload.get("loraNames", [])
    lora_names = [str(n) for n in lora_names_raw if isinstance(n, str) and str(n).strip()] if isinstance(lora_names_raw, list) else []

    with _styles_pages_lock:
        pages = _load_styles_pages()
        page_num = _get_next_page_number(pages)
        folder_id = f"page_{page_num}"
        # Create the folder on disk.
        page_folder = STYLES_IMAGES_DIR / folder_id
        page_folder.mkdir(parents=True, exist_ok=True)

        new_page: dict[str, Any] = {
            "id": page_num,
            "folderId": folder_id,
            "model": model,
            "loraNames": lora_names,
            "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        pages.append(new_page)
        _write_styles_pages(pages)

    return jsonify({"ok": True, "page": new_page}), 201


@models_api_bp.delete("/styles/pages")
def reset_style_pages():
    import shutil

    with _styles_pages_lock:
        pages = _load_styles_pages()
        deleted_folders = 0
        for page in pages:
            folder_id = str(page.get("folderId", "") or "").strip()
            if folder_id:
                page_folder = STYLES_IMAGES_DIR / folder_id
                try:
                    if page_folder.is_dir():
                        shutil.rmtree(str(page_folder))
                        deleted_folders += 1
                except Exception:
                    logger.warning("Failed removing page folder: %s", page_folder)
        _write_styles_pages([])

    # Clear page_images from all styles.
    with _styles_lock:
        styles = _load_styles()
        for style in styles:
            style["page_images"] = {}
        _write_styles(styles)

    return jsonify({"ok": True, "deletedFolders": deleted_folders})


@models_api_bp.delete("/styles/pages/<page_id>")
def delete_style_page(page_id: str):
    import shutil

    target = str(page_id or "").strip()
    if not target:
        return jsonify({"error": "page id is required"}), 400

    deleted_folder_id = ""
    deleted_page_number: int | None = None

    with _styles_pages_lock:
        pages = _load_styles_pages()
        if not pages:
            return jsonify({"error": "page not found"}), 404

        remaining_pages: list[dict[str, Any]] = []
        deleted_page: dict[str, Any] | None = None
        for page in pages:
            if not isinstance(page, dict):
                remaining_pages.append(page)
                continue
            folder_id = str(page.get("folderId", "") or "").strip()
            page_number = _coerce_int_scalar(page.get("id"))
            is_match = target == folder_id or (page_number is not None and target == str(page_number))
            if is_match and deleted_page is None:
                deleted_page = page
                deleted_folder_id = folder_id
                deleted_page_number = page_number
                continue
            remaining_pages.append(page)

        if deleted_page is None:
            return jsonify({"error": "page not found"}), 404

        _write_styles_pages(remaining_pages)

    if deleted_folder_id:
        page_folder = STYLES_IMAGES_DIR / deleted_folder_id
        try:
            if page_folder.is_dir():
                shutil.rmtree(str(page_folder))
        except Exception:
            logger.warning("Failed removing page folder: %s", page_folder)

    styles_updated = 0
    with _styles_lock:
        styles = _load_styles()
        for style in styles:
            if not isinstance(style, dict):
                continue
            page_images = style.get("page_images")
            if not isinstance(page_images, dict):
                continue

            changed = False
            if deleted_folder_id and deleted_folder_id in page_images:
                page_images.pop(deleted_folder_id, None)
                changed = True
            if deleted_page_number is not None and str(deleted_page_number) in page_images:
                page_images.pop(str(deleted_page_number), None)
                changed = True
            if changed:
                style["page_images"] = page_images
                styles_updated += 1

        _write_styles(styles)

    return jsonify(
        {
            "ok": True,
            "deletedPage": {
                "id": deleted_page_number,
                "folderId": deleted_folder_id,
            },
            "stylesUpdated": styles_updated,
        }
    )


@models_api_bp.get("/styles/image/<path:filename>")
def serve_style_image(filename: str):
    # `filename` may contain subdirectory components (e.g. "page_1/1.png").
    # Resolve to an absolute path and guard against path traversal.
    try:
        resolved = (STYLES_IMAGES_DIR / filename).resolve()
        resolved.relative_to(STYLES_IMAGES_DIR.resolve())  # raises if outside
    except (ValueError, Exception):
        return jsonify({"error": "Invalid path"}), 400

    img_bytes: bytes | None = None
    if resolved.is_file():
        try:
            img_bytes = resolved.read_bytes()
        except Exception:
            img_bytes = None

    if img_bytes is None:
        # Backward compatibility: flat filenames may live in the configured output dir.
        flat_name = Path(filename).name
        data = _ensure_registry()
        img_bytes = image_service.serve_image(_resolve_output_dir(data), flat_name)

    if img_bytes is None:
        return jsonify({"error": "Image not found"}), 404

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "png": "image/png"}
    content_type = mime_map.get(ext, "image/png")

    raw_w = request.args.get("w")
    if raw_w:
        max_size = min(800, max(100, int(raw_w)))
        resized = image_service.resize_image_bytes(img_bytes, max_size)
        if resized is not None:
            img_bytes, content_type = resized

    resp = make_response(img_bytes)
    resp.headers["Content-Type"] = content_type
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


def _get_style_model_entry(style: dict[str, Any], model_id: str) -> dict[str, Any]:
    model_images = style.get("model_images", {})
    if isinstance(model_images, dict):
        candidate = model_images.get(model_id)
        if isinstance(candidate, dict):
            return candidate
    return {}


def _style_has_image_for_model(style: dict[str, Any], model_id: str) -> bool:
    entry = _get_style_model_entry(style, model_id)
    return bool(
        str(entry.get("image_filename", "") or "").strip()
        or str(entry.get("image_url", "") or "").strip()
    )


@models_api_bp.get("/styles")
def list_styles():
    page_id = str(request.args.get("page", "") or "").strip()
    model_id = str(request.args.get("model", "") or "").strip()
    with _styles_lock:
        styles = _load_styles()

    payload: list[dict[str, Any]] = []
    for item in styles:
        style_record = dict(item)
        if model_id:
            model_entry = _get_style_model_entry(item, model_id)
            style_record["has_image"] = _style_has_image_for_model(item, model_id)
            style_record["image_url"] = str(model_entry.get("image_url", "") or "") or STYLE_PREVIEW_FALLBACK_URL
            style_record["image_filename"] = str(model_entry.get("image_filename", "") or "").strip()
        elif page_id:
            page_entry = _get_style_page_entry(item, page_id)
            style_record["has_image"] = _style_has_image_for_page(item, page_id)
            style_record["image_url"] = _resolve_style_image_url_for_page(item, page_id)
            style_record["image_filename"] = str(page_entry.get("image_filename", "") or "").strip()
        else:
            # No model/page filter — fall back to whichever model this style
            # happens to have an image for (if any), so callers that just
            # want "a representative thumbnail" (e.g. the Style Transfer
            # picker panel, which isn't tied to one specific model) get a
            # real image instead of always the placeholder.
            fallback_entry: dict[str, Any] = {}
            model_images = item.get("model_images")
            if isinstance(model_images, dict):
                for entry in model_images.values():
                    if isinstance(entry, dict) and (
                        str(entry.get("image_filename", "") or "").strip()
                        or str(entry.get("image_url", "") or "").strip()
                    ):
                        fallback_entry = entry
                        break
            style_record["has_image"] = bool(fallback_entry)
            style_record["image_url"] = str(fallback_entry.get("image_url", "") or "") or STYLE_PREVIEW_FALLBACK_URL
            style_record["image_filename"] = str(fallback_entry.get("image_filename", "") or "").strip()
        payload.append(style_record)

    payload.sort(key=lambda row: _coerce_int_scalar(row.get("id")) or 10**9)
    return jsonify({"styles": payload, "defaultImageUrl": STYLE_PREVIEW_FALLBACK_URL, "page": page_id, "model": model_id})


@models_api_bp.patch("/styles/<int:style_id>/image")
def update_style_image(style_id: int):
    payload = request.get_json(silent=True) or {}
    image_filename = str(payload.get("imageFilename", "") or "").strip()
    image_url = str(payload.get("imageUrl", "") or "").strip()
    page_id = str(payload.get("pageId", "") or "").strip()
    registry_data = _ensure_registry()

    if not page_id:
        return jsonify({"error": "pageId is required"}), 400

    with _styles_lock:
        styles = _load_styles()
        target = None
        for item in styles:
            if (_coerce_int_scalar(item.get("id")) or -1) == int(style_id):
                target = item
                break

        if target is None:
            return jsonify({"error": "Style not found"}), 404

        if image_filename or image_url:
            source_bytes = _load_source_image_bytes_for_style(registry_data, image_filename, image_url)
            if source_bytes is None:
                return jsonify({"error": "Style image source not found"}), 400

            style_rel_path = _style_preview_page_path(style_id, page_id)
            # Ensure the page sub-folder exists before saving.
            (STYLES_IMAGES_DIR / page_id).mkdir(parents=True, exist_ok=True)
            image_service.save_image(
                str(STYLES_IMAGES_DIR),
                style_rel_path,
                source_bytes,
                {
                    "source": "styles",
                    "style_id": str(style_id),
                    "page_id": page_id,
                    "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )

            page_images = target.get("page_images")
            if not isinstance(page_images, dict):
                page_images = {}
            page_images[page_id] = {
                "image_filename": style_rel_path,
                "image_url": _build_style_image_url(style_rel_path, safe='/'),
            }
            target["page_images"] = page_images
        else:
            page_images = target.get("page_images")
            if isinstance(page_images, dict):
                page_images[page_id] = {"image_filename": "", "image_url": ""}
                target["page_images"] = page_images

        _write_styles(styles)

    updated = dict(target)
    updated["image_url"] = _resolve_style_image_url_for_page(updated, page_id)
    updated["has_image"] = _style_has_image_for_page(updated, page_id)
    updated["pageId"] = page_id
    return jsonify({"ok": True, "style": updated})


_SUBFOLDER_PART_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")


def _to_webp(image_bytes: bytes, quality: int = 85) -> bytes | None:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as im:
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            buf = io.BytesIO()
            im.save(buf, "WEBP", quality=quality, method=6)
            return buf.getvalue()
    except Exception:
        logger.exception("WebP conversion failed")
        return None


def _safe_subfolder(value: Any) -> str | None:
    """'' when not asked for, the cleaned relative path when valid, None when
    it would escape the output folder or uses odd characters."""
    raw = str(value or "").strip().replace("\\", "/").strip("/")
    if not raw:
        return ""
    parts = [p for p in raw.split("/") if p]
    if not parts or any(p in (".", "..") or not _SUBFOLDER_PART_RE.match(p) for p in parts):
        return None
    return "/".join(parts)


def _safe_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip("-.") or "model"


def _style_file_key(style: dict[str, Any]) -> str:
    """Stable file name for a style's exported image: the package key when
    the style comes from a style pack, otherwise a slug of its name."""
    key = str(style.get("package_key") or "").strip()
    if key:
        return key
    slug = re.sub(r"[^a-z0-9]+", "-", str(style.get("name", "")).lower()).strip("-")
    return slug or f"style-{style.get('id')}"


@models_api_bp.patch("/styles/<int:style_id>/model-image")
def update_style_model_image(style_id: int):
    """Associate a generated/uploaded image with a specific imported model —
    keyed by real model id (see /api/models/imports), not the legacy
    profile_images numbered-slot scheme."""
    payload = request.get_json(silent=True) or {}
    image_filename = str(payload.get("imageFilename", "") or "").strip()
    image_url = str(payload.get("imageUrl", "") or "").strip()
    model_id = str(payload.get("modelId", "") or "").strip()
    image_format = "webp" if str(payload.get("format", "") or "").strip().lower() == "webp" else "png"
    registry_data = _ensure_registry()

    if not model_id:
        return jsonify({"error": "modelId is required"}), 400
    if not image_filename and not image_url:
        return jsonify({"error": "imageFilename or imageUrl is required"}), 400
    export_subfolder = _safe_subfolder(payload.get("exportSubfolder"))
    if export_subfolder is None:
        return jsonify({"error": "The output subfolder may only use letters, digits, '-', '_' and '/'"}), 400

    with _styles_lock:
        styles = _load_styles()
        target = next((s for s in styles if _coerce_int_scalar(s.get("id")) == style_id), None)
        if target is None:
            return jsonify({"error": "Style not found"}), 404

        source_bytes = _load_source_image_bytes_for_style(registry_data, image_filename, image_url)
        if source_bytes is None:
            return jsonify({"error": "Style image source not found"}), 400

        model_folder = f"model_{model_id}"
        (STYLES_IMAGES_DIR / model_folder).mkdir(parents=True, exist_ok=True)
        if image_format == "webp":
            webp_bytes = _to_webp(source_bytes)
            if webp_bytes is None:
                return jsonify({"error": "Could not convert the image to WebP"}), 400
            style_rel_path = f"{model_folder}/{style_id}.webp"
            (STYLES_IMAGES_DIR / style_rel_path).write_bytes(webp_bytes)
        else:
            style_rel_path = f"{model_folder}/{style_id}.png"
            image_service.save_image(
                str(STYLES_IMAGES_DIR),
                style_rel_path,
                source_bytes,
                {
                    "source": "styles",
                    "style_id": str(style_id),
                    "model_id": model_id,
                    "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )
        # Switching format leaves the other one behind — drop it.
        other = STYLES_IMAGES_DIR / f"{model_folder}/{style_id}.{'png' if image_format == 'webp' else 'webp'}"
        if other.is_file():
            try:
                other.unlink()
            except OSError:
                pass

        # Optional stable-named copy in the output folder, e.g.
        # <output>/style-previews/<model>/<style-key>.webp — what a style
        # pack's images are collected from (PACKAGE_FORMAT.md §10.3).
        export_path = ""
        if export_subfolder:
            ext = style_rel_path.rsplit(".", 1)[-1]
            export_dir = Path(_resolve_output_dir(registry_data)) / export_subfolder / _safe_segment(model_id)
            export_dir.mkdir(parents=True, exist_ok=True)
            dest = export_dir / f"{_style_file_key(target)}.{ext}"
            dest.write_bytes((STYLES_IMAGES_DIR / style_rel_path).read_bytes())
            export_path = str(dest)

        model_images = target.get("model_images")
        if not isinstance(model_images, dict):
            model_images = {}
        model_images[model_id] = {
            "image_filename": style_rel_path,
            "image_url": _build_style_image_url(style_rel_path, safe='/'),
        }
        target["model_images"] = model_images
        _write_styles(styles)

    return jsonify({
        "ok": True,
        "id": style_id,
        "modelId": model_id,
        "image_url": target["model_images"][model_id]["image_url"],
        "exportPath": export_path,
    })


@models_api_bp.post("/styles/import")
def import_styles():
    payload = request.get_json(silent=True) or {}
    incoming_raw = payload.get("styles", payload) if isinstance(payload, dict) else payload
    incoming = incoming_raw if isinstance(incoming_raw, list) else []

    if not incoming:
        return jsonify({"error": "No styles provided"}), 400

    # Strip image fields — import never overwrites images.
    IMAGE_KEYS = {"image_filename", "image_url", "profile_images", "page_images"}

    added = 0
    updated = 0

    with _styles_lock:
        styles = _load_styles()
        id_map: dict[int, dict] = {}
        name_map: dict[str, dict] = {}
        max_id = 0
        for s in styles:
            sid = _coerce_int_scalar(s.get("id"))
            if sid is not None:
                id_map[sid] = s
                if sid > max_id:
                    max_id = sid
            sname = str(s.get("name", "") or "").strip().lower()
            if sname:
                name_map[sname] = s

        for item in incoming:
            if not isinstance(item, dict):
                continue
            # Always ignore the incoming id — match by name only.
            clean = {k: v for k, v in item.items() if k not in IMAGE_KEYS and k != "id"}
            incoming_name = str(clean.get("name", "") or "").strip()

            existing = name_map.get(incoming_name.lower()) if incoming_name else None

            if existing is not None:
                for k, v in clean.items():
                    existing[k] = v
                updated += 1
            else:
                max_id += 1
                clean["id"] = max_id
                for key in IMAGE_KEYS:
                    clean.setdefault(key, {} if key in {"profile_images", "page_images"} else "")
                styles.append(clean)
                id_map[max_id] = clean
                if incoming_name:
                    name_map[incoming_name.lower()] = clean
                added += 1

        _write_styles(styles)

    return jsonify({"ok": True, "added": added, "updated": updated})


def _local_image_model_names() -> dict[str, str]:
    """id -> name for this install's own imported image-generation models
    (see /api/models/imports) — used to resolve exported model_images to
    whatever this install calls the same model, since the raw model id is
    only ever meaningful on the install that generated it."""
    data = _ensure_registry()
    imports = data.get("imports", [])
    if not isinstance(imports, list):
        return {}
    out: dict[str, str] = {}
    for item in imports:
        if not isinstance(item, dict):
            continue
        if str(item.get("category", "image") or "image").strip().lower() != "image":
            continue
        mid = item.get("id")
        name = str(item.get("name", "") or "").strip()
        if mid and name:
            out[str(mid)] = name
    return out


@models_api_bp.get("/styles/export")
def export_styles():
    """Bundles styles.json (name/category/prompt/prefix/suffix) plus their
    per-model preview images into a .zip another install can import — see
    /styles/import-zip below. Optional ?model=<id> restricts the image
    payload to one model's batch (e.g. just-generated Krea 2 previews)
    instead of every model this install has images for.

    Model ids are meaningless across installs, so the manifest carries an
    id -> model NAME map; import-zip resolves images by matching that name
    against the receiving install's own imported models."""
    model_filter = str(request.args.get("model", "") or "").strip()
    with _styles_lock:
        styles = _load_styles()
    model_names = _local_image_model_names()

    manifest_styles: list[dict[str, Any]] = []
    models_used: dict[str, str] = {}
    referenced_files: list[str] = []

    for s in styles:
        entry: dict[str, Any] = {
            "name": s.get("name", ""),
            "category": s.get("category", ""),
            "prefix": s.get("prefix", ""),
            "suffix": s.get("suffix", ""),
            "prompt": s.get("prompt", ""),
            "model_images": {},
        }
        model_images = s.get("model_images")
        if isinstance(model_images, dict):
            for mid, img in model_images.items():
                if model_filter and mid != model_filter:
                    continue
                if not isinstance(img, dict):
                    continue
                fn = str(img.get("image_filename", "") or "").strip()
                if not fn:
                    continue
                try:
                    abs_path = (STYLES_IMAGES_DIR / fn).resolve()
                    abs_path.relative_to(STYLES_IMAGES_DIR.resolve())
                except ValueError:
                    continue
                if not abs_path.is_file():
                    continue
                entry["model_images"][mid] = {"image_filename": fn}
                referenced_files.append(fn)
                models_used[mid] = model_names.get(mid, mid)

        # A single-model export only keeps styles that actually carry that
        # model's image — a full export keeps every style regardless, so
        # name/prompt/category stay in sync even for styles with no image.
        if entry["model_images"] or not model_filter:
            manifest_styles.append(entry)

    manifest = {
        "exportedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "models": models_used,
        "styles": manifest_styles,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for fn in referenced_files:
            zf.write(str(STYLES_IMAGES_DIR / fn), arcname=f"images/{fn}")
    buf.seek(0)

    resp = make_response(buf.read())
    resp.headers["Content-Type"] = "application/zip"
    fname = "styles-export" + (f"-{model_filter}" if model_filter else "") + ".zip"
    resp.headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp


@models_api_bp.post("/styles/import-zip")
def import_styles_zip():
    """Counterpart to /styles/export — matches styles by name (same rule as
    the plain-JSON /styles/import above) and, for each style's model_images,
    resolves the exported model NAME against this install's own imported
    models. An image is only ever written when the matched style+model
    doesn't already have one here — imported images never clobber local
    ones, they only fill gaps."""
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "file is required"}), 400

    try:
        zf = zipfile.ZipFile(io.BytesIO(file.read()))
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    except Exception:
        return jsonify({"error": "Invalid styles export .zip"}), 400

    if not isinstance(manifest, dict):
        return jsonify({"error": "Malformed manifest.json"}), 400
    incoming_styles = manifest.get("styles", [])
    incoming_model_names = manifest.get("models", {})
    if not isinstance(incoming_styles, list) or not isinstance(incoming_model_names, dict):
        return jsonify({"error": "Malformed manifest.json"}), 400

    local_models = _local_image_model_names()
    local_name_to_id: dict[str, str] = {}
    for mid, name in local_models.items():
        local_name_to_id.setdefault(name.strip().lower(), mid)

    # model_images is deliberately excluded too — unlike the plain-JSON
    # /styles/import above (which never carries model_images at all), this
    # zip's manifest entries DO carry a model_images subset (see
    # export_styles), and blindly merging it here would overwrite the
    # target's real, complete model_images (every model, full image_url)
    # with the export's partial one (only the exported model(s), filename
    # only, no image_url) — the per-model loop below is the only thing
    # that's allowed to touch model_images, one resolved entry at a time.
    IMAGE_KEYS = {"image_filename", "image_url", "profile_images", "page_images", "model_images"}
    added = 0
    updated = 0
    images_written = 0
    images_skipped_no_local_model = 0
    images_skipped_existing = 0

    with _styles_lock:
        styles = _load_styles()
        name_map: dict[str, dict] = {}
        max_id = 0
        for s in styles:
            sid = _coerce_int_scalar(s.get("id"))
            if sid is not None and sid > max_id:
                max_id = sid
            sname = str(s.get("name", "") or "").strip().lower()
            if sname:
                name_map[sname] = s

        for item in incoming_styles:
            if not isinstance(item, dict):
                continue
            incoming_name = str(item.get("name", "") or "").strip()
            if not incoming_name:
                continue
            clean = {k: v for k, v in item.items() if k not in IMAGE_KEYS and k != "id"}

            existing = name_map.get(incoming_name.lower())
            if existing is not None:
                for k, v in clean.items():
                    existing[k] = v
                target = existing
                updated += 1
            else:
                max_id += 1
                clean["id"] = max_id
                clean.setdefault("image_filename", "")
                clean.setdefault("image_url", "")
                clean.setdefault("profile_images", {})
                clean.setdefault("page_images", {})
                clean.setdefault("model_images", {})
                styles.append(clean)
                name_map[incoming_name.lower()] = clean
                target = clean
                added += 1

            target_style_id = _coerce_int_scalar(target.get("id"))
            incoming_model_images = item.get("model_images")
            if target_style_id is None or not isinstance(incoming_model_images, dict):
                continue

            target_model_images = target.get("model_images")
            if not isinstance(target_model_images, dict):
                target_model_images = {}
                target["model_images"] = target_model_images

            for src_model_id, img in incoming_model_images.items():
                if not isinstance(img, dict):
                    continue
                src_model_name = str(incoming_model_names.get(src_model_id, "") or "").strip().lower()
                local_model_id = local_name_to_id.get(src_model_name) if src_model_name else None
                if not local_model_id:
                    images_skipped_no_local_model += 1
                    continue
                if _style_has_image_for_model(target, local_model_id):
                    images_skipped_existing += 1
                    continue

                src_rel = str(img.get("image_filename", "") or "").strip()
                if not src_rel:
                    continue
                try:
                    image_bytes = zf.read(f"images/{src_rel}")
                except KeyError:
                    continue

                model_folder = f"model_{local_model_id}"
                style_rel_path = f"{model_folder}/{target_style_id}.png"
                (STYLES_IMAGES_DIR / model_folder).mkdir(parents=True, exist_ok=True)
                image_service.save_image(
                    str(STYLES_IMAGES_DIR),
                    style_rel_path,
                    image_bytes,
                    {
                        "source": "styles",
                        "style_id": str(target_style_id),
                        "model_id": local_model_id,
                        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "imported": "true",
                    },
                )
                target_model_images[local_model_id] = {
                    "image_filename": style_rel_path,
                    "image_url": _build_style_image_url(style_rel_path, safe='/'),
                }
                images_written += 1

        _write_styles(styles)

    return jsonify({
        "ok": True,
        "added": added,
        "updated": updated,
        "imagesWritten": images_written,
        "imagesSkippedNoLocalModel": images_skipped_no_local_model,
        "imagesSkippedExisting": images_skipped_existing,
    })


@models_api_bp.post("/styles")
def create_style():
    """Create a new style with editable fields. No image — attach one via
    the model-image endpoint afterward, once the style has an id."""
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    new_style = {
        "name": name,
        "category": str(payload.get("category", "") or "").strip(),
        "prefix": str(payload.get("prefix", "") or "").strip(),
        "suffix": str(payload.get("suffix", "") or "").strip(),
        "prompt": str(payload.get("prompt", "") or "").strip(),
        "image_filename": "",
        "image_url": "",
        "profile_images": {},
        "page_images": {},
        "model_images": {},
    }

    with _styles_lock:
        styles = _load_styles()
        max_id = max((_coerce_int_scalar(s.get("id")) or 0 for s in styles), default=0)
        new_style["id"] = max_id + 1
        styles.append(new_style)
        _write_styles(styles)

    return jsonify({"ok": True, "style": new_style})


@models_api_bp.patch("/styles/<int:style_id>")
def update_style(style_id: int):
    """Update editable fields (name, category, prompt, prefix, suffix) of a style."""
    payload = request.get_json(silent=True) or {}
    EDITABLE_KEYS = {"name", "category", "prompt", "prefix", "suffix"}
    updates = {k: v for k, v in payload.items() if k in EDITABLE_KEYS}
    if not updates:
        return jsonify({"error": "No editable fields provided"}), 400

    with _styles_lock:
        styles = _load_styles()
        target = next((s for s in styles if _coerce_int_scalar(s.get("id")) == style_id), None)
        if target is None:
            return jsonify({"error": f"Style {style_id} not found"}), 404
        for k, v in updates.items():
            target[k] = v
        # A package update must not overwrite the user's own wording.
        if target.get("package"):
            target["package_edited"] = True
        _write_styles(styles)

    return jsonify({"ok": True, "id": style_id, "updated": list(updates.keys())})


@models_api_bp.delete("/styles/<int:style_id>")
def delete_style(style_id: int):
    """Delete a style by id. Also cleans up preview image files."""
    registry_data = _ensure_registry()
    output_dir = _resolve_output_dir(registry_data)

    with _styles_lock:
        styles = _load_styles()
        target = next((s for s in styles if _coerce_int_scalar(s.get("id")) == style_id), None)
        if target is None:
            return jsonify({"error": f"Style {style_id} not found"}), 404

        # Best-effort: clean up page image files.
        page_images = target.get("page_images")
        if isinstance(page_images, dict):
            for entry in page_images.values():
                if isinstance(entry, dict):
                    fn = str(entry.get("image_filename", "") or "").strip()
                    if fn:
                        _delete_style_preview_file(fn, output_dir=output_dir)

        # Legacy single image.
        legacy_fn = str(target.get("image_filename", "") or "").strip()
        if legacy_fn:
            _delete_style_preview_file(legacy_fn, output_dir=output_dir)

        styles = [s for s in styles if _coerce_int_scalar(s.get("id")) != style_id]
        _write_styles(styles)

    return jsonify({"ok": True, "id": style_id})


@models_api_bp.post("/styles/images/reset")
def reset_style_images():
    payload = request.get_json(silent=True) or {}
    raw_slots = payload.get("profileSlots", [1, 2, 3])

    slots: set[int] = set()
    if isinstance(raw_slots, list):
        for raw_slot in raw_slots:
            slots.add(_coerce_profile_slot(raw_slot))
    else:
        slots.add(_coerce_profile_slot(raw_slots))

    if not slots:
        slots = {1, 2, 3}

    registry_data = _ensure_registry()
    output_dir = _resolve_output_dir(registry_data)
    deleted_files = 0
    styles_cleared = 0

    with _styles_lock:
        styles = _load_styles()

        for style in styles:
            style_id = _coerce_int_scalar(style.get("id"))
            profile_images = style.get("profile_images")
            if not isinstance(profile_images, dict):
                profile_images = {}

            touched = False
            for slot in sorted(slots):
                slot_key = str(slot)
                entry = profile_images.get(slot_key) if isinstance(profile_images.get(slot_key), dict) else {}
                filename = str(entry.get("image_filename", "") or "").strip()
                if not filename and style_id is not None:
                    filename = _style_preview_filename(style_id, slot)

                if filename and _delete_style_preview_file(filename, output_dir=output_dir):
                    deleted_files += 1

                if slot_key in profile_images:
                    del profile_images[slot_key]
                    touched = True

                if slot == 1:
                    legacy_filename = str(style.get("image_filename", "") or "").strip()
                    if legacy_filename and _delete_style_preview_file(legacy_filename, output_dir=output_dir):
                        deleted_files += 1
                    if str(style.get("image_filename", "") or "") or str(style.get("image_url", "") or ""):
                        style["image_filename"] = ""
                        style["image_url"] = ""
                        touched = True

            style["profile_images"] = profile_images
            if touched:
                styles_cleared += 1

        _write_styles(styles)

    return jsonify({
        "ok": True,
        "profileSlots": sorted(slots),
        "stylesCleared": styles_cleared,
        "deletedFiles": deleted_files,
    })
