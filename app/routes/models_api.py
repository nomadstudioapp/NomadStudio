from __future__ import annotations

# ---------------------------------------------------------------------------
# Re-export everything from shared module so external code still works
# ---------------------------------------------------------------------------
from app.routes.models_api_shared import (  # noqa: F401
    models_api_bp,
    logger,
    _ensure_registry,
    _save_registry,
    _safe_session_subdir,
    _try_save_image_to_output_dir,
    _resolve_output_dir,
    _lmstudio_models_endpoint,
    _lmstudio_chat_endpoint,
    _lmstudio_rest_models_load_endpoint,
    _lmstudio_rest_models_unload_endpoint,
    _lmstudio_load_model,
    _lmstudio_unload_model,
    _sanitize_lmstudio_edited_prompt,
    _extract_json_array_from_text,
    _normalize_lmstudio_conversation_messages,
    _append_lmstudio_output_log,
    _describe_cache_set,
)

# Re-export workflow helpers for backward compatibility
from app.services.workflow_service import (  # noqa: F401
    _advanced_input_metadata,
    _analyze_workflow,
    _apply_basic_values_to_workflow,
    _apply_clip_last_layer_bypass,
    _apply_lora_chain_to_workflow,
    _apply_resize_toggle_to_workflow,
    _as_scalar,
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
    _style_has_image_for_page,
    _style_has_image_for_slot,
    _style_preview_filename,
    _style_preview_page_path,
    _upscale_model_by_id,
    _upscale_models_catalog,
    _validate_clip_last_layer_advanced_values,
    _workflow_load_image_nodes,
)

# ---------------------------------------------------------------------------
# Load route sub-modules (must be AFTER all definitions above)
# ---------------------------------------------------------------------------
from app.routes.models_api_modules import chat_routes as _chat_routes          # noqa: F401,E402
from app.routes.models_api_modules import prompt_routes as _prompt_routes      # noqa: F401,E402
from app.routes.models_api_modules import vision_routes as _vision_routes      # noqa: F401,E402
from app.routes.models_api_modules import studio_routes as _studio_routes      # noqa: F401,E402
from app.routes.models_api_modules import styles_routes as _styles_routes      # noqa: F401,E402
from app.routes.models_api_modules import generation_routes as _gen_routes     # noqa: F401,E402
from app.routes.models_api_modules import imports_routes as _imports_routes    # noqa: F401,E402
from app.routes.models_api_modules import images_routes as _images_routes          # noqa: F401,E402
from app.routes.models_api_modules import settings_routes as _settings_routes      # noqa: F401,E402
from app.routes.models_api_modules import upscale_routes as _upscale_routes        # noqa: F401,E402
from app.routes.models_api_modules import compose_routes as _compose_routes        # noqa: F401,E402
from app.routes.models_api_modules import backgrounds_routes as _backgrounds        # noqa: F401,E402
from app.routes.models_api_modules import vision_benchmark_routes as _vb_routes    # noqa: F401,E402
from app.routes.models_api_modules import refine_routes as _refine_routes          # noqa: F401,E402
from app.routes.models_api_modules import characters_routes as _characters_routes  # noqa: F401,E402
from app.routes.models_api_modules import library_routes as _library_routes        # noqa: F401,E402
from app.routes.models_api_modules import template_packs_routes as _template_packs_routes  # noqa: F401,E402
from app.routes.models_api_modules import depots_routes as _depots_routes          # noqa: F401,E402
# pixel_match_routes moved to addons/pixel_matcher — loaded via addon_loader
