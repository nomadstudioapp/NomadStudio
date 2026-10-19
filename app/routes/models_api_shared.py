from __future__ import annotations

import json
import logging
import re
import secrets
from contextlib import contextmanager
from html import unescape
import time
import uuid
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote, urlencode
import base64
import bleach
from threading import Lock

from flask import Blueprint, jsonify, make_response, request, session

from app.config import (
    DEFAULT_COMFY_URL,
    DEFAULT_LMSTUDIO_CONTEXT_SIZE,
    DEFAULT_LMSTUDIO_TEMPERATURE,
    DEFAULT_LMSTUDIO_URL,
    DEFAULT_OUTPUT_DIR,
    LMSTUDIO_OUTPUT_LOG_MAX_ITEMS,
)
from app.services.http_client import http_bytes, http_json, http_multipart_upload_image
from app.services import lmstudio_service
from app.services import registry_service
from app import paths
from app.services import image_service
from app.services import viewer_service
from app.services.workflow_service import (  # noqa: F401 — re-exported for backward compat
    _advanced_input_metadata,
    _analyze_workflow,
    _apply_basic_values_to_workflow,
    _apply_clip_last_layer_bypass,
    _apply_lora_chain_to_workflow,
    _apply_resize_toggle_to_workflow,
    _as_scalar,
    _auto_context_size,
    _build_compose_models_from_imports,
    _build_upscale_models_from_imports,
    _bypass_optional_image_input_nodes,
    _clip_text,
    _coerce_context_size,
    _coerce_int_scalar,
    _coerce_lmstudio_temperature,
    _coerce_profile_slot,
    _coerce_quality_value,
    _collect_node_output_consumers,
    _compose_model_by_id,
    _compose_models_catalog,
    _compute_comfy_poll_timeouts,
    _decode_data_url_image_bytes,
    _describe_cache_get,
    _describe_cache_key,
    _extract_applied_seeds,
    _extract_checkpoint_loader_keys,
    _extract_checkpoint_options_from_object_info,
    _extract_clip_last_layer_keys,
    _extract_dimension_from_sampler,
    _extract_filename_from_image_url,
    _extract_lora_loader_keys,
    _extract_lora_options_from_object_info,
    _extract_loras_used_from_workflow,
    _extract_unet_loader_keys,
    _extract_unet_options_from_object_info,
    _extract_quality_blocks_from_text,
    _extract_quality_presets,
    _extract_seed_from_inputs,
    _fallback_latent_node_id_for_image_bypass,
    _find_text_target_node,
    _get_describe_cache,
    _get_next_page_number,
    _get_style_page_entry,
    _get_style_profile_entry,
    _inject_uploaded_image_into_workflow,
    _is_link,
    _is_negative_like_key,
    _is_prompt_like_key,
    _is_sampler_like_node,
    _next_numeric_node_id,
    _normalize_basic_values_aliases,
    _normalize_clip_last_layer_advanced_values,
    _normalize_lora_chain_payload,
    _normalize_quality_token,
    _normalize_record_negative,
    _parse_image_data_url,
    _parse_workflow_config_node,
    _parse_workflow_payload,
    _pick_upscale_scale_key,
    _prune_stale_clip_last_layer_overrides,
    _quality_field_aliases,
    _replace_links_from_node_output,
    _resolve_quality_target_key,
    _resolve_text_from_node,
    _resolve_upscale_scale,
    _safe_comfy_url,
    _safe_http_url,
    _select_output_images,
    _swap_save_image_for_preview,
    _style_has_image_for_page,
    _style_has_image_for_slot,
    _style_preview_filename,
    _style_preview_page_path,
    _upscale_model_by_id,
    _upscale_models_catalog,
    _validate_clip_last_layer_advanced_values,
    _workflow_load_image_nodes,
)

models_api_bp = Blueprint("models_api", __name__)
logger = logging.getLogger(__name__)

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "workflows"
FALLBACK_OUTPUT_DIR = paths.user_images("originals")

# Must match viewers_routes.SESSION_KEY — duplicated as a plain string (rather
# than importing viewers_routes here) to avoid a route-module import cycle.
_VIEWER_SESSION_KEY = "active_viewer_id"
# User data lives outside the program folder (app/paths.py).
REGISTRY_PATH = paths.REGISTRY_PATH
STYLES_PATH = paths.data_file("styles.json")
STYLES_IMAGES_DIR = paths.user_images("styles")
STYLES_PAGES_PATH = paths.data_file("styles_pages.json")
STYLE_PREVIEW_FALLBACK_URL = "/static/images/style-default-sd.svg"
_styles_lock = Lock()
_styles_pages_lock = Lock()

UPSCALE_MODELS = [
    {
        "id": "realesrgan_x4_fixed",
        "name": "RealESRGAN x4 (Fixed)",
        "scaleMode": "fixed",
        "fixedScale": 4,
    },
    {
        "id": "anime_x2_fixed",
        "name": "AnimeSharp x2 (Fixed)",
        "scaleMode": "fixed",
        "fixedScale": 2,
    },
    {
        "id": "multi_scale_flexible",
        "name": "MultiScale Flex (Selectable)",
        "scaleMode": "selectable",
        "minScale": 2,
        "maxScale": 6,
        "defaultScale": 3,
    },
]

CLIP_LAST_LAYER_ALLOWED_VALUES = {0, -2, -3}
CLIP_LAST_LAYER_INPUT_KEYS = {"stop_at_clip_layer", "layer"}


def _heal_shared_encoder_negatives(imports: list) -> None:
    """Engines whose single text encoder holds both prompts (Qwen Image 2.1's
    TextEncodeQwenImage21: `prompt` + `negative_prompt`) were analysed with
    the POSITIVE example text as their default negative ("a small red fox
    sitting in snow, studio photo"), so every image was made with "no red
    fox". That value sits in installed registries and in engine packages, and
    package updates keep it as if the user had chosen it. It is never a user
    choice when it equals the encoder's own positive text: swap in the
    encoder's real negative_prompt (2026-10-19)."""
    for record in imports:
        if not isinstance(record, dict) or not isinstance(record.get("workflow"), dict):
            continue
        analysis = record.get("analysis") if isinstance(record.get("analysis"), dict) else {}
        # basicValues (what generation uses) and analysis.basicValues (what
        # "reset values" restores) both carry it.
        for basic in (record.get("basicValues"), analysis.get("basicValues")):
            if not isinstance(basic, dict):
                continue
            negative = str(basic.get("negative") or "").strip()
            if not negative:
                continue
            for node in record["workflow"].values():
                inputs = node.get("inputs") if isinstance(node, dict) else None
                if (isinstance(inputs, dict) and isinstance(inputs.get("negative_prompt"), str)
                        and str(inputs.get("prompt") or "").strip() == negative):
                    basic["negative"] = inputs["negative_prompt"]
                    break


def _ensure_registry() -> dict[str, Any]:
    default_data = registry_service.build_default_registry(
        default_comfy_url=DEFAULT_COMFY_URL,
        default_lmstudio_url=DEFAULT_LMSTUDIO_URL,
        default_context_size=DEFAULT_LMSTUDIO_CONTEXT_SIZE,
        default_upscale_model_id=str(UPSCALE_MODELS[0]["id"]),
        default_upscale_scale=int(UPSCALE_MODELS[0].get("fixedScale", 2)),
    )
    try:
        data = registry_service.ensure_registry(REGISTRY_PATH, default_data)
    except Exception:
        logger.exception("Failed reading registry file, using defaults")
        data = default_data
    if "imports" not in data or not isinstance(data["imports"], list):
        data["imports"] = []
    if "activeImportId" not in data:
        data["activeImportId"] = None
    if "activeImportIds" not in data or not isinstance(data["activeImportIds"], list):
        # Migrate: if there is an existing activeImportId, seed the list from it
        existing = str(data.get("activeImportId", "") or "").strip()
        data["activeImportIds"] = [existing] if existing else []

    # Self-heal orphaned references: activeImportId/activeImportIds should
    # only ever point at real entries in `imports`. delete_import() cleans
    # both up together when going through it, but the migration above (old
    # activeImportId-only registries -> activeImportIds) copies whatever
    # activeImportId already held without checking it's still valid — if it
    # was already stale at that point (e.g. removed by an older code path
    # that predates delete_import's own cleanup), the dangling id gets baked
    # permanently into the new list instead of getting fixed (see issue #7).
    # Pruning here on every load, not just during the one-time migration,
    # means any future drift between the two also heals itself instead of
    # accumulating.
    _real_import_ids = {item.get("id") for item in data["imports"] if isinstance(item, dict)}
    data["activeImportIds"] = [i for i in data["activeImportIds"] if i in _real_import_ids]
    if data.get("activeImportId") not in _real_import_ids:
        data["activeImportId"] = data["activeImportIds"][0] if data["activeImportIds"] else None

    _heal_shared_encoder_negatives(data["imports"])

    if "settings" not in data or not isinstance(data["settings"], dict):
        data["settings"] = {
            "comfyApiUrl": DEFAULT_COMFY_URL,
            "lmStudioApiUrl": DEFAULT_LMSTUDIO_URL,
            "lmStudioModel": "",
            "lmStudioPromptModel": "",
            "lmStudioVisionModel": "",
            "lmStudioModels": [],
            "lmStudioVisionModels": [],
            "lmStudioFavoriteModels": [],
            "lmStudioVisionFavoriteModels": [],
            "lmStudioShowFavoritesOnly": False,
            "lmStudioVisionShowFavoritesOnly": False,
            "lmStudioAutoDisconnect": False,
            "lmStudioContextSize": DEFAULT_LMSTUDIO_CONTEXT_SIZE,
            "lmStudioTemperature": DEFAULT_LMSTUDIO_TEMPERATURE,
            "lmStudioOutputLog": [],
        }
    if "comfyApiUrl" not in data["settings"]:
        data["settings"]["comfyApiUrl"] = DEFAULT_COMFY_URL
    if "lmStudioApiUrl" not in data["settings"]:
        data["settings"]["lmStudioApiUrl"] = DEFAULT_LMSTUDIO_URL
    if "lmStudioModel" not in data["settings"]:
        data["settings"]["lmStudioModel"] = ""
    if "lmStudioPromptModel" not in data["settings"]:
        data["settings"]["lmStudioPromptModel"] = str(data["settings"].get("lmStudioModel", "")).strip()
    if "lmStudioVisionModel" not in data["settings"]:
        data["settings"]["lmStudioVisionModel"] = str(data["settings"].get("lmStudioPromptModel", "")).strip()
    if "lmStudioModels" not in data["settings"] or not isinstance(data["settings"].get("lmStudioModels"), list):
        data["settings"]["lmStudioModels"] = []
    if "lmStudioVisionModels" not in data["settings"] or not isinstance(data["settings"].get("lmStudioVisionModels"), list):
        data["settings"]["lmStudioVisionModels"] = []
    if "lmStudioFavoriteModels" not in data["settings"] or not isinstance(data["settings"].get("lmStudioFavoriteModels"), list):
        data["settings"]["lmStudioFavoriteModels"] = []
    if "lmStudioVisionFavoriteModels" not in data["settings"] or not isinstance(data["settings"].get("lmStudioVisionFavoriteModels"), list):
        data["settings"]["lmStudioVisionFavoriteModels"] = []
    if "lmStudioShowFavoritesOnly" not in data["settings"]:
        data["settings"]["lmStudioShowFavoritesOnly"] = False
    if "lmStudioVisionShowFavoritesOnly" not in data["settings"]:
        data["settings"]["lmStudioVisionShowFavoritesOnly"] = False
    if "lmStudioAutoDisconnect" not in data["settings"]:
        data["settings"]["lmStudioAutoDisconnect"] = False
    if "lmStudioContextSize" not in data["settings"]:
        data["settings"]["lmStudioContextSize"] = DEFAULT_LMSTUDIO_CONTEXT_SIZE
    elif _coerce_context_size(data["settings"]["lmStudioContextSize"]) < 1024:
        # Migrate users who had the old small default (900) up to the new default
        data["settings"]["lmStudioContextSize"] = DEFAULT_LMSTUDIO_CONTEXT_SIZE
    if "lmStudioTemperature" not in data["settings"]:
        data["settings"]["lmStudioTemperature"] = DEFAULT_LMSTUDIO_TEMPERATURE
    if "lmStudioOutputLog" not in data["settings"] or not isinstance(data["settings"].get("lmStudioOutputLog"), list):
        data["settings"]["lmStudioOutputLog"] = []
    if "queueFreeMemoryBetweenModels" not in data["settings"]:
        data["settings"]["queueFreeMemoryBetweenModels"] = False
    if "workflowAnnotateFields" not in data["settings"] or not isinstance(data["settings"].get("workflowAnnotateFields"), dict):
        data["settings"]["workflowAnnotateFields"] = {
            "downloads": ["subfolder", "filename", "url"],
            "loras": ["fileName", "name", "triggerWords", "uri", "notes"],
        }

    if "upscaleSettings" not in data or not isinstance(data.get("upscaleSettings"), dict):
        data["upscaleSettings"] = {
            "comfyApiUrl": str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip() or DEFAULT_COMFY_URL,
            "modelId": UPSCALE_MODELS[0]["id"],
            "scale": UPSCALE_MODELS[0].get("fixedScale", 2),
        }
    if "comfyApiUrl" not in data["upscaleSettings"]:
        data["upscaleSettings"]["comfyApiUrl"] = str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip() or DEFAULT_COMFY_URL
    if "modelId" not in data["upscaleSettings"]:
        data["upscaleSettings"]["modelId"] = UPSCALE_MODELS[0]["id"]
    if "scale" not in data["upscaleSettings"]:
        data["upscaleSettings"]["scale"] = UPSCALE_MODELS[0].get("fixedScale", 2)

    if "composeSettings" not in data or not isinstance(data.get("composeSettings"), dict):
        data["composeSettings"] = {}
    if "comfyApiUrl" not in data["composeSettings"]:
        data["composeSettings"]["comfyApiUrl"] = str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip() or DEFAULT_COMFY_URL
    if "modelId" not in data["composeSettings"]:
        data["composeSettings"]["modelId"] = ""

    # Backward compatibility: older imports may not have their own ComfyUI URI.
    default_comfy = str(data.get("settings", {}).get("comfyApiUrl", DEFAULT_COMFY_URL)).strip() or DEFAULT_COMFY_URL
    for item in data.get("imports", []):
        if isinstance(item, dict) and "comfyApiUrl" not in item:
            item["comfyApiUrl"] = default_comfy
        if not isinstance(item, dict):
            continue
        annotation = item.get("annotation")
        if not isinstance(annotation, dict):
            annotation = {}
            item["annotation"] = annotation
        if "downloads" not in annotation or not isinstance(annotation.get("downloads"), list):
            annotation["downloads"] = []
        if "loras" not in annotation or not isinstance(annotation.get("loras"), list):
            annotation["loras"] = []
        if "placeholderImage" not in annotation or not isinstance(annotation.get("placeholderImage"), str):
            annotation["placeholderImage"] = ""
        if "updatedAt" not in annotation or not isinstance(annotation.get("updatedAt"), str):
            annotation["updatedAt"] = ""

    if "outputDir" not in data["settings"]:
        data["settings"]["outputDir"] = DEFAULT_OUTPUT_DIR

    return data


@contextmanager
def _registry_transaction(deleted_import_ids: set[str] | None = None) -> Iterator[dict[str, Any]]:
    """Atomic read-modify-write for route handlers that read via
    _ensure_registry(), mutate one or more keys, and save via
    _save_registry() as two separate calls — replace that pattern with
    `with _registry_transaction() as data: ...mutate data...` instead.

    Without this, two near-simultaneous PATCH requests each read their own
    snapshot, mutate independently, and whichever saves second silently
    overwrites the first's change (demonstrated with two Settings toggles
    saved back-to-back — issue found 2026-09-01). registry_service's own
    _save_registry-level lock only serializes the physical file WRITE, not
    the read+mutate step before it, so it doesn't prevent this by itself.

    Uses registry_service._mutation_lock (separate from _registry_lock,
    which guards the low-level file write only, to avoid deadlocking with
    _save_registry's own internal locking when this block calls it).

    deleted_import_ids: imports removed on purpose in this block — without
    it, _save_registry re-adds any import still on disk (its guard against a
    concurrent writer), and the deletion would silently not happen."""
    with registry_service._mutation_lock:
        data = _ensure_registry()
        yield data
        _save_registry(data, deleted_import_ids=deleted_import_ids)


def _save_registry(data: dict[str, Any], deleted_import_ids: set[str] | None = None) -> None:
    # Serialize all writes through the global lock to prevent race-condition data loss.
    # Reads in _ensure_registry run lock-free (atomic rename makes them always see a
    # complete file), so only writes are serialized — concurrent reads are not blocked.
    with registry_service._registry_lock:
        current = registry_service._read_json_safe(REGISTRY_PATH)
        if current is not None and isinstance(current.get("imports"), list):
            mem_ids = {str(item.get("id", "")) for item in data.get("imports", []) if isinstance(item, dict)}
            excluded = deleted_import_ids or set()
            # Imports present on disk but not in our copy were added by another thread — keep them.
            # But do NOT re-add imports that were intentionally deleted in this operation.
            for item in current["imports"]:
                item_id = str(item.get("id", ""))
                if isinstance(item, dict) and item_id not in mem_ids and item_id not in excluded:
                    data.setdefault("imports", []).append(item)

        # Backup without fsync (convenience only)
        try:
            if current is not None:
                registry_service._atomic_write(REGISTRY_PATH.with_suffix(".json.bak"), current, fsync=False)
        except Exception:
            logger.warning("Failed to create registry backup")

        registry_service._atomic_write(REGISTRY_PATH, data)


def _safe_session_subdir(raw: Any) -> str | None:
    """Validate a relative ``session/<folder>`` subdir. Returns the cleaned
    relative path (forward slashes) or ``None`` if invalid.

    Also accepts the legacy ``bundle/<folder>`` and ``vault/<folder>``
    prefixes so sessions created before the Vault → Bundle → Session renames
    keep saving into their existing on-disk folder instead of splitting
    across three locations."""
    rel = str(raw or "").strip().strip("/")
    if not rel:
        return None
    parts = rel.split("/")
    if parts[0] not in ("session", "bundle", "vault") or len(parts) > 2:
        return None
    for p in parts:
        if p in (".", "..") or not re.match(r"^[A-Za-z0-9._-]+$", p):
            return None
    return "/".join(parts)


def _slugify_viewer_name(text: str) -> str:
    return viewer_service.slugify_name(text)


def _active_viewer_id() -> str | None:
    """Raw session viewer id (uuid), or ``None`` when nobody is logged in.
    Used as a stable dict key (unlike the slug, unaffected by renames).

    A ``?viewer=<id-or-slug>`` query param wins over the session cookie, but
    ONLY when it resolves to an agent viewer — lets a plain link (a chat
    client with no cookie jar, or the in-app Agent Album page) always open
    that agent's own images, regardless of which human is currently logged
    into the browser's own session. Checked first (not as a fallback):
    otherwise browsing the Agent Album while logged in as a human viewer
    would silently show the human's own folder instead, since the session
    cookie is still sent alongside the query param on every fetch from that
    page. Human viewers still require the real session (PIN-gated ones
    especially); the query param is never accepted for them, and an
    unresolved/invalid ``?viewer=`` falls through to the session as before."""
    query_viewer = request.args.get("viewer")
    if query_viewer:
        viewer = viewer_service.get_viewer(query_viewer)
        if viewer and viewer.get("is_agent", False):
            return query_viewer
        viewer = viewer_service.get_agent_viewer_by_slug(query_viewer)
        if viewer:
            return viewer["id"]

    session_viewer_id = session.get(_VIEWER_SESSION_KEY)
    if session_viewer_id:
        return session_viewer_id

    return None


def _active_viewer_slug() -> str | None:
    """Slug for the active viewer (e.g. "bird"), or ``None`` when nobody is
    logged in. Derived live from the viewer's name — no separate slug field
    is persisted, so renaming a viewer changes its folder. Goes through
    _active_viewer_id() so the ?viewer= query-param fallback for agents
    applies here too, not just to the raw id lookup."""
    viewer_id = _active_viewer_id()
    if not viewer_id:
        return None
    viewer = viewer_service.get_viewer(viewer_id)
    if not viewer:
        return None
    return _slugify_viewer_name(viewer.get("name"))


def _active_viewer_is_vanish() -> bool:
    """True when the active session viewer is the singleton "Vanish Session"
    profile (see viewer_service.get_or_create_vanish_viewer()) — generations
    still run, but nothing about them is ever written to disk. Callers that
    persist per-viewer data (image saves, Tray/album metadata, Sessions)
    should check this and skip the write instead of guessing from the
    generic "no active viewer" case, which means something different
    (nobody logged in at all)."""
    viewer_id = _active_viewer_id()
    if not viewer_id:
        return False
    viewer = viewer_service.get_viewer(viewer_id)
    return bool(viewer and viewer.get("is_vanish", False))


def _apply_comfy_output_policy(data: dict[str, Any], prepared_workflow: dict[str, Any]) -> int:
    """Swap ``SaveImage`` for ``PreviewImage`` right before a workflow goes to
    ComfyUI when its permanent ``output/`` copy isn't wanted:

    - Vanish Session: nothing may ever be left on disk.
    - ``settings.skipComfyOutputCopy`` (setup wizard / Settings, off by
      default): Nomad Studio already saves every image in the viewer's own
      folder, so ComfyUI's copy is a duplicate. Only applied while a regular
      viewer is logged in — without one ``_try_save_image_to_output_dir``
      refuses to write, and the ComfyUI copy would be the only one left.

    ComfyUI then writes to ``temp/`` (wiped when ComfyUI starts) and history
    reports ``type: temp``, which every download path already forwards to
    ``/view``. Returns how many nodes were swapped."""
    if _active_viewer_is_vanish():
        return _swap_save_image_for_preview(prepared_workflow)
    settings = data.get("settings", {}) if isinstance(data.get("settings"), dict) else {}
    if settings.get("skipComfyOutputCopy") is True and _active_viewer_id():
        return _swap_save_image_for_preview(prepared_workflow)
    return 0


def _resolve_viewer_output_dir(data: dict[str, Any]) -> str | None:
    """``<output_dir>/<viewer-slug>`` for the session's active viewer.

    Scopes the Album/gallery, Tray and saved input references to the
    logged-in viewer. Returns ``None`` when nobody is logged in — callers
    must treat that as a hard stop (no shared/fallback folder; the app
    always expects an active "who's watching" session before this point)."""
    slug = _active_viewer_slug()
    if not slug:
        return None
    return str(Path(_resolve_output_dir(data)) / slug)


def _try_save_image_to_output_dir(
    data: dict[str, Any],
    image_bytes: bytes,
    metadata: dict[str, str],
    filename_prefix: str,
    idx: int,
    subdir: str | None = None,
) -> str | None:
    """Save *image_bytes* for the active viewer.

    When *subdir* is a valid ``session/<folder>`` path (Sessions are shared
    across viewers) the image is written there, unchanged from before.
    Otherwise — the common case, plain generation output, and the "input"
    subdir used for flow reference images — it's written under the active
    viewer's own ``<output_dir>/<viewer-slug>/`` folder.

    Returns the saved relative path on success, or ``None`` if the output
    directory is not configured, nobody is logged in, or the write fails.
    """
    if _active_viewer_is_vanish():
        logger.info("Vanish Session active: skipping image save (in-memory only)")
        return None

    output_dir = _resolve_output_dir(data)
    # A graph's SaveImage filename_prefix may carry a ComfyUI subfolder
    # ("monaco/level-01-quick", Krea2 Monaco): only the name part is ours —
    # the subfolder doesn't exist in the viewer's folder and the write failed.
    prefix = re.split(r"[\\/]", filename_prefix or "")[-1] or "comfy-output"

    clean_session_subdir = _safe_session_subdir(subdir) if subdir else None
    if clean_session_subdir:
        target_dir = str(Path(output_dir).joinpath(*clean_session_subdir.split("/")))
        rel_dir = clean_session_subdir + "/"
    else:
        viewer_dir = _resolve_viewer_output_dir(data)
        if not viewer_dir:
            logger.warning("Refusing to save image: no active viewer in session")
            return None
        if subdir == "input":
            target_dir = str(Path(viewer_dir) / "input")
            rel_dir = "input/"
        else:
            target_dir = viewer_dir
            rel_dir = ""

    filename = _unique_image_filename(target_dir, prefix)
    try:
        image_service.save_image(target_dir, filename, image_bytes, metadata)
        return rel_dir + filename
    except Exception:
        logger.exception("Failed to save image to output dir '%s'", target_dir)
        return None


def _unique_image_filename(target_dir: str, prefix: str) -> str:
    """``{prefix}-{6 hex chars}.png`` — short and still readable, unlike the
    old ``{prefix}-{seed}-{idx}-{timestamp_ms}.png`` scheme (the seed is
    already in the PNG's own metadata/sidecar, and ordering comes from
    filesystem mtime via image_paging_service._sort_key, not the filename —
    neither needed encoding here). Retries on the astronomically unlikely
    collision instead of trusting randomness blindly."""
    target = Path(target_dir)
    for _ in range(5):
        candidate = f"{prefix}-{secrets.token_hex(3)}.png"
        if not (target / candidate).exists():
            return candidate
    # Practically unreachable (16M+ combinations per prefix/folder) — fall
    # back to a longer id rather than ever returning a colliding name.
    return f"{prefix}-{secrets.token_hex(8)}.png"


def _resolve_output_dir(data: dict[str, Any]) -> str:
    configured = str(data.get("settings", {}).get("outputDir", "")).strip()
    if configured:
        return configured
    return str(FALLBACK_OUTPUT_DIR)




def _lmstudio_models_endpoint(base_url: str) -> str:
    return lmstudio_service.models_endpoint(base_url)


def _lmstudio_chat_endpoint(base_url: str) -> str:
    return lmstudio_service.chat_endpoint(base_url)


def _lmstudio_rest_chat_endpoint(base_url: str) -> str:
    return lmstudio_service.rest_chat_endpoint(base_url)


def _lmstudio_rest_models_load_endpoint(base_url: str) -> str:
    return lmstudio_service.rest_models_load_endpoint(base_url)


def _lmstudio_rest_models_unload_endpoint(base_url: str) -> str:
    return lmstudio_service.rest_models_unload_endpoint(base_url)


def _lmstudio_load_model(
    base_url: str, model_name: str, context_size: int | None = None, force: bool = False
) -> tuple[bool, str]:
    return lmstudio_service.load_model(base_url, model_name, context_size, force=force)


def _lmstudio_unload_model(base_url: str, model_name: str) -> bool:
    return lmstudio_service.unload_model(base_url, model_name)


def _sanitize_lmstudio_edited_prompt(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return value

    # Decode HTML entities first (e.g. &lt;blockquote&gt;).
    value = unescape(value)

    # Remove common LM Studio/control tokens (e.g. <|end_of_box|>).
    value = re.sub(r"<\|[a-zA-Z0-9_.:-]{1,80}\|>", "", value)

    # Remove markdown code fences if a model wrapped the response.
    value = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", value)
    value = re.sub(r"\s*```$", "", value)

    # Strip any HTML/XML tags safely (e.g. <blockquote>...</blockquote>).
    value = bleach.clean(value, tags=[], attributes={}, strip=True)

    # Remove leftover escaped control tokens if they survived sanitization.
    value = re.sub(r"&lt;\|[a-zA-Z0-9_.:-]{1,80}\|&gt;", "", value, flags=re.IGNORECASE)

    # LM Studio models sometimes wrap final answer in quotes/parentheses.
    pairs = [
        ('"', '"'),
        ("'", "'"),
        ('(', ')'),
        ('[', ']'),
    ]
    for open_char, close_char in pairs:
        if value.startswith(open_char) and value.endswith(close_char) and len(value) > 2:
            value = value[1:-1].strip()

    # Normalize escaped punctuation often returned by LLMs.
    value = value.replace("\\(", "(").replace("\\)", ")")

    # Remove common labels and cleanup whitespace.
    value = re.sub(r"^(edited\s+prompt|final\s+prompt|prompt)\s*:\s*", "", value, flags=re.IGNORECASE)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)

    return value


def _apply_max_tokens_override(payload: dict[str, Any], base_max_tokens: int) -> int:
    """Let the client request a higher max_tokens than the server-computed default.

    Used for the "retry with more tokens" flow (see `_reasoning_only_error` below):
    when a model spends its whole budget on chain-of-thought and returns no
    content, the frontend offers to retry with double the tokens — this is what
    lets that retry actually request more. Only ever raises the budget, never
    lowers it below the server's own computed minimum.
    """
    requested = payload.get("maxTokens")
    if isinstance(requested, int) and requested > base_max_tokens:
        return requested
    return base_max_tokens


def _reasoning_only_error(source: str, max_output_tokens: int, fallback_message: str) -> dict[str, Any]:
    """Build the error payload for an empty LM Studio response.

    When `source` is "reasoning_only" (see `_extract_lmstudio_message_text` in
    chat_routes.py), the model spent its whole token budget on chain-of-thought
    and never reached the final answer — that's a token-budget problem, not a
    generic failure, so the frontend can offer to retry with more tokens
    instead of just showing a dead-end error (see issue #1 / `emptyWithReasoning`,
    first wired up for Recipes' "Generate Style from Image" in recipes.js).
    """
    if source == "reasoning_only":
        return {
            "error": "LM Studio model used all its tokens on reasoning and produced no output.",
            "emptyWithReasoning": True,
            "currentMaxTokens": max_output_tokens,
        }
    return {"error": fallback_message}


_THINK_TRICK_INSTRUCTION = (
    "\n\nBefore the final answer, write a brief \"Thinking Process:\" as a short numbered list "
    "(analyze the request, plan the response) — 2-3 items max. Then write \"---\" on its own "
    "line, then write the complete final answer directly below it (the real content requested "
    "above — never a placeholder, always the full text itself)."
)


def _apply_think_trick(system_prompt: str, think_mode: bool) -> str:
    """Append the 'Thinking Process' prompting instruction when think_mode is on.

    This is NOT LM Studio's native reasoning API — that proved unreliable (it can
    silently exhaust its token budget and return an empty answer on several
    locally-installed models). This is plain prompting: cheap, fast, and works on
    every model regardless of native reasoning support.
    """
    if not think_mode:
        return system_prompt
    return system_prompt + _THINK_TRICK_INSTRUCTION


def _strip_think_trick_preamble(raw_text: str) -> str:
    """Drop the visible 'Thinking Process: ... ---' preamble, keeping only the
    real answer that follows — the thinking block must never leak into a
    generated image prompt. If the model didn't follow the format, the text
    is returned unchanged."""
    text = str(raw_text or "")
    marker_match = re.search(r"\n\s*-{3,}\s*\n", text)
    if marker_match:
        return text[marker_match.end():].strip()
    return text


def _extract_json_array_from_text(text: str) -> list[Any]:
    value = str(text or "").strip()
    if not value:
        return []

    value = unescape(value)
    value = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", value)
    value = re.sub(r"\s*```$", "", value)

    candidates = [value]
    match = re.search(r"\[\s*[\s\S]*\]\s*$", value)
    if match:
        candidates.insert(0, match.group(0).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            parsed = None

        if isinstance(parsed, list):
            return parsed

        # Recovery path for truncated LLM output: decode as much of the array as possible.
        # This salvages valid items before the cut instead of failing the whole response.
        array_start = candidate.find("[")
        if array_start < 0:
            continue

        decoder = json.JSONDecoder()
        items: list[Any] = []
        idx = array_start + 1
        length = len(candidate)

        while idx < length:
            while idx < length and candidate[idx] in " \t\r\n,":
                idx += 1
            if idx >= length:
                break
            if candidate[idx] == "]":
                break

            try:
                item, next_idx = decoder.raw_decode(candidate, idx)
            except Exception:
                break

            items.append(item)
            idx = next_idx

        if items:
            return items

    return []


def _normalize_lmstudio_conversation_messages(raw_messages: Any, context_size: int) -> list[dict[str, str]]:
    if not isinstance(raw_messages, list):
        return []

    per_message_max_chars = max(120, min(1600, int(context_size * 1.2)))
    total_max_chars = max(600, min(12000, int(context_size * 6)))
    normalized: list[dict[str, str]] = []
    total_chars = 0

    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = _clip_text(str(item.get("content", "")).strip(), per_message_max_chars)
        if not content:
            continue
        total_chars += len(content)
        normalized.append({"role": role, "content": content})

    if not normalized:
        return []

    while normalized and total_chars > total_max_chars:
        removed = normalized.pop(0)
        total_chars -= len(removed.get("content", ""))

    max_messages = 24
    if len(normalized) > max_messages:
        normalized = normalized[-max_messages:]

    return normalized


def _append_lmstudio_output_log(data: dict[str, Any], settings: dict[str, Any], entry: dict[str, Any]) -> None:
    # `data`/`settings` are the caller's own snapshot — typically read via
    # _ensure_registry() *before* the slow LLM call whose result this entry
    # records, so by now it can be stale (issue #4: ~20 call sites across
    # prompt_routes.py/studio_routes.py/vision_routes.py/vision_benchmark_routes.py,
    # each firing after its own LLM round-trip). Kept in the signature so none
    # of those call sites need to change, but the actual mutation re-fetches a
    # fresh copy under the registry lock instead of trusting them — two of
    # these racing (or one racing a Settings save) would otherwise silently
    # drop a log entry.
    with _registry_transaction() as fresh_data:
        fresh_settings = fresh_data.setdefault("settings", {})
        logs = fresh_settings.get("lmStudioOutputLog")
        if not isinstance(logs, list):
            logs = []
        logs.insert(0, entry)
        fresh_settings["lmStudioOutputLog"] = logs[:LMSTUDIO_OUTPUT_LOG_MAX_ITEMS]


def _describe_cache_set(data: dict[str, Any], settings: dict[str, Any], image_hash: str, describe_type: str, entry: dict[str, Any]) -> None:
    # Same reasoning as _append_lmstudio_output_log just above — `settings`
    # may be stale by the time the (slow) describe-image call this caches
    # has actually returned, so re-fetch fresh under the lock rather than
    # trusting it.
    with _registry_transaction() as fresh_data:
        fresh_settings = fresh_data.setdefault("settings", {})
        cache = _get_describe_cache(fresh_settings)
        key = _describe_cache_key(image_hash, describe_type)
        cache.pop(key, None)
        cache[key] = entry

        max_items = 80
        while len(cache) > max_items:
            oldest_key = next(iter(cache))
            cache.pop(oldest_key, None)

        fresh_settings["lmStudioDescribeCache"] = cache





# Route modules register grouped endpoints using the shared models_api_bp blueprint.

# ---------------------------------------------------------------------------
# Style image helpers (used by styles_routes, backgrounds_routes, characters_routes)
# ---------------------------------------------------------------------------

def _load_source_image_bytes_for_style(data: dict[str, Any], image_filename: str, image_url: str) -> bytes | None:
    from app.services.workflow_service import _extract_filename_from_image_url, _decode_data_url_image_bytes
    filename = str(image_filename or "").strip()
    if not filename:
        filename = _extract_filename_from_image_url(image_url)
    if filename:
        # Current generations are saved under the active viewer's own
        # <output>/<viewer-slug>/ folder (images_routes.py serves from there
        # first) — looking only in the output root, as this used to, made
        # "Send to Character / Background" fail with "image source not found"
        # for every result. Same order as styles_routes' own copy of this.
        viewer_output_dir = _resolve_viewer_output_dir(data)
        if viewer_output_dir:
            image_bytes = image_service.serve_image(viewer_output_dir, filename)
            if image_bytes:
                return image_bytes
        # Legacy fallback: pre-viewer saves in the output root.
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
