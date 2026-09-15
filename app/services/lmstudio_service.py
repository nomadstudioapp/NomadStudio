from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from .http_client import http_json

lms = None
try:
    import lmstudio as lms

    _HAS_LMS_SDK = True
except ImportError:
    _HAS_LMS_SDK = False

logger = logging.getLogger(__name__)


def _sdk_list_models(base_url: str) -> list[dict[str, Any]]:
    if not _HAS_LMS_SDK:
        return []
    if lms is None:
        return []

    try:
        lms.configure_default_client(_sdk_host(base_url))
    except Exception as exc:
        # SDK keeps a singleton default client in-process. Reuse it if already initialized.
        if "already created" not in str(exc).lower():
            logger.exception("Failed configuring LM Studio SDK client")
            return []

    try:
        downloaded = lms.list_downloaded_models("llm")
    except Exception:
        logger.exception("Failed listing downloaded models via LM Studio SDK")
        return []

    out: list[dict[str, Any]] = []
    for item in downloaded if isinstance(downloaded, list) else []:
        data = getattr(item, "_data", None)
        if data is None:
            continue

        model_id = str(getattr(data, "model_key", "") or "").strip()
        if not model_id:
            continue

        display_name = str(getattr(data, "display_name", "") or model_id).strip()
        architecture = str(getattr(data, "architecture", "") or "").strip()
        vision = bool(getattr(data, "vision", False))

        out.append(
            {
                "id": model_id,
                "model": model_id,
                "name": display_name,
                "vision": vision,
                "architecture": architecture,
            }
        )

    return out


def models_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/models"
    return f"{base}/v1/models"


def chat_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def rest_models_load_endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    return f"{root}/api/v1/models/load"


def rest_chat_endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    return f"{root}/api/v1/chat"


def rest_models_unload_endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    return f"{root}/api/v1/models/unload"


def rest_models_endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    return f"{root}/api/v1/models"


def _coerce_model_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "models", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def _entry_model_name(entry: dict[str, Any]) -> str:
    for key in ("model", "model_id", "id", "name"):
        value = str(entry.get(key, "")).strip()
        if value:
            return value
    return ""


def _entry_model_id(entry: dict[str, Any]) -> str:
    for key in ("id", "model", "model_id", "name", "key"):
        value = str(entry.get(key, "")).strip()
        if value:
            return value
    return ""


def _entry_is_loaded(entry: dict[str, Any]) -> bool:
    loaded_flag = entry.get("loaded")
    if isinstance(loaded_flag, bool):
        return loaded_flag

    state = str(entry.get("state", "") or entry.get("status", "")).strip().lower()
    if state in {"loaded", "running", "active", "ready"}:
        return True

    instance_id = str(
        entry.get("instance_id", "") or entry.get("instanceId", "")
    ).strip()
    return bool(instance_id)


def find_loaded_instance_id(base_url: str, model_name: str) -> str | None:
    target = str(model_name or "").strip()
    if not target:
        return None

    try:
        payload = http_json(rest_models_endpoint(base_url), timeout=20)
    except Exception:
        return None

    for entry in _coerce_model_entries(payload):
        current = _entry_model_name(entry)
        if not current or current != target:
            continue
        if not _entry_is_loaded(entry):
            continue
        instance_id = str(
            entry.get("instance_id", "") or entry.get("instanceId", "")
        ).strip()
        return instance_id or target

    return None


def _sdk_host(base_url: str) -> str:
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 1234
    return f"{host}:{port}"


def load_model(
    base_url: str, model_name: str, context_size: int | None = None, force: bool = False
) -> tuple[bool, str]:
    # `force` skips the "already loaded" pre-check and issues the load call
    # unconditionally. Used to recover when LM Studio reports a model as
    # loaded (via /v1/models) but has actually since evicted it — e.g. a
    # second model (vision) got loaded in between and pushed it out of VRAM.
    if not force:
        already_loaded_instance = find_loaded_instance_id(base_url, model_name)
        if already_loaded_instance:
            return False, ""

    try:
        if _HAS_LMS_SDK:
            if lms is None:
                return False, model_name
            try:
                lms.configure_default_client(_sdk_host(base_url))
            except Exception as exc:
                # SDK keeps a singleton default client in-process. Reuse it if already initialized.
                if "already created" not in str(exc).lower():
                    raise
            load_config: dict[str, Any] = {}
            if context_size is not None:
                load_config["contextLength"] = context_size
                load_config["gpu"] = {"ratio": 1}
            lms.llm(model_name, config=load_config if load_config else None)  # type: ignore[arg-type]
            return True, model_name
        else:
            payload: dict = {"model": model_name}
            if context_size is not None:
                # snake_case only. The REST endpoint validates its keys
                # strictly and rejects the whole request with
                # "Unrecognized key(s) in object: 'contextLength'" if the
                # camelCase spelling is sent alongside — which made every
                # load fail on installs without the Python SDK, silently,
                # leaving LM Studio to JIT-load with its own settings.
                # (camelCase is correct for the SDK's config above, but not here.)
                payload["context_length"] = context_size
            response = http_json(
                rest_models_load_endpoint(base_url),
                method="POST",
                payload=payload,
                timeout=30,
            )
            instance_id = str(response.get("instance_id", "")).strip() or model_name
            return True, instance_id
    except Exception:
        logger.exception("Failed to load LM Studio model '%s'", model_name)
        return False, model_name


def unload_model(base_url: str, model_name: str) -> bool:
    if not str(model_name or "").strip():
        return False
    try:
        http_json(
            rest_models_unload_endpoint(base_url),
            method="POST",
            payload={"instance_id": model_name},
            timeout=20,
        )
        return True
    except Exception:
        logger.exception("Failed to unload LM Studio model '%s'", model_name)
        return False


def list_model_ids(base_url: str) -> list[str]:
    models_raw = list_models(base_url)
    out: list[str] = []
    for item in models_raw:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", "")).strip()
        if model_id:
            out.append(model_id)
    return sorted(set(out))


def list_models(base_url: str) -> list[dict[str, Any]]:
    sdk_models = _sdk_list_models(base_url)
    if sdk_models:
        # Enrich SDK rows with /api/v1/models capability metadata (e.g. reasoning options).
        try:
            rest_payload = http_json(rest_models_endpoint(base_url), timeout=30)
            rest_rows = _coerce_model_entries(rest_payload)
        except Exception:
            rest_rows = []

        if rest_rows:
            rest_index: dict[str, dict[str, Any]] = {}
            for row in rest_rows:
                if not isinstance(row, dict):
                    continue
                model_key = _entry_model_id(row)
                if model_key:
                    rest_index[model_key] = row

            for row in sdk_models:
                model_key = _entry_model_id(row)
                if not model_key:
                    continue
                rest_row = rest_index.get(model_key)
                if not rest_row:
                    continue

                capabilities = rest_row.get("capabilities")
                if isinstance(capabilities, dict):
                    row["capabilities"] = capabilities
                    if isinstance(capabilities.get("vision"), bool):
                        row["vision"] = bool(capabilities.get("vision"))
                    reasoning = capabilities.get("reasoning")
                    if isinstance(reasoning, dict):
                        row["reasoning"] = reasoning

                for key in (
                    "max_context_length",
                    "architecture",
                    "publisher",
                    "selected_variant",
                    "variants",
                ):
                    if key in rest_row and key not in row:
                        row[key] = rest_row[key]

        return sdk_models

    payload = http_json(models_endpoint(base_url), timeout=30)
    models_raw = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(models_raw, list):
        return []
    return [item for item in models_raw if isinstance(item, dict)]


def _stringify_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip().lower()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip().lower()
        if text:
            out.append(text)
    return out


def model_supports_vision(entry: dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False

    explicit_flags: list[bool] = []
    for key in (
        "vision",
        "supports_vision",
        "vision_enabled",
        "multimodal",
        "is_multimodal",
    ):
        flag = entry.get(key)
        if isinstance(flag, bool):
            explicit_flags.append(flag)

    # If the API returns any explicit positive capability flag, trust it immediately.
    # When only explicit false flags are present, keep evaluating modality/name hints
    # to avoid false negatives from incomplete LM Studio metadata.
    if any(explicit_flags):
        return True

    candidate_lists: list[str] = []
    for key in ("modalities", "input_modalities", "output_modalities"):
        candidate_lists.extend(_stringify_list(entry.get(key)))

    capabilities = entry.get("capabilities")
    if isinstance(capabilities, dict):
        for key in ("modalities", "input_modalities"):
            candidate_lists.extend(_stringify_list(capabilities.get(key)))
        if bool(capabilities.get("vision") or capabilities.get("image")):
            return True
    elif isinstance(capabilities, list):
        candidate_lists.extend(_stringify_list(capabilities))

    architecture = entry.get("architecture")
    if isinstance(architecture, dict):
        for key in ("modalities", "input_modalities"):
            candidate_lists.extend(_stringify_list(architecture.get(key)))

    tokens = set(candidate_lists)
    if tokens.intersection({"vision", "image", "images", "multimodal", "vlm"}):
        return True

    model_id = (
        str(entry.get("id", "") or entry.get("model", "") or entry.get("name", ""))
        .strip()
        .lower()
    )
    if not model_id:
        return False

    vision_hints = (
        "vision",
        "llava",
        "vl",
        "vlm",
        "pixtral",
        "minicpm-v",
        "internvl",
        "moondream",
        "llama-vision",
        "qwen2-vl",
        "qwen-vl",
        "gemma-vision",
    )
    return any(hint in model_id for hint in vision_hints)


def list_vision_model_ids(base_url: str) -> list[str]:
    out: list[str] = []
    for entry in list_models(base_url):
        model_id = str(entry.get("id", "")).strip()
        if model_id and model_supports_vision(entry):
            out.append(model_id)
    return sorted(set(out))


def model_reasoning_options(entry: dict[str, Any]) -> list[str]:
    if not isinstance(entry, dict):
        return []

    direct_reasoning = entry.get("reasoning")
    if isinstance(direct_reasoning, dict):
        raw_opts = direct_reasoning.get("allowed_options")
        if isinstance(raw_opts, list):
            return [str(item).strip() for item in raw_opts if str(item).strip()]

    capabilities = entry.get("capabilities")
    if isinstance(capabilities, dict):
        reasoning = capabilities.get("reasoning")
        if isinstance(reasoning, dict):
            raw_opts = reasoning.get("allowed_options")
            if isinstance(raw_opts, list):
                opts = [str(o) for o in raw_opts if isinstance(o, str)]
                if opts:
                    return opts
    return []
