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

    # Make VRAM room first when ComfyUI is holding what this model needs
    # (see ensure_room below, NomadStudio#12).
    ensure_room(base_url, model_name, _registry_comfy_url())

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


# ═══════════════════════════════════════════════════════════════════════════
# Reliability: native chat, engine recovery, VRAM room (NomadStudio#12, MVP)
# ═══════════════════════════════════════════════════════════════════════════
#
# Three failures seen on a real 16 GB machine (2026-09, benchmark reports and
# live tests), all of which used to reach the user as an empty answer or a
# cascade of errors:
#
# 1. Reasoning that can't be turned off. The OpenAI-style /v1/chat/completions
#    endpoint has no reliable switch — /no_think only reaches Qwen, several
#    GGUFs ignore thinking.budget_tokens — and a reasoning model spends the
#    whole token budget thinking and returns empty content. The native
#    /api/v1/chat endpoint takes `reasoning: "off"` and honours it (measured:
#    qwen3.8-4b answers in 38 tokens at "off", empty at "on").
# 2. The engine dying. When a model does not fit, LM Studio's llama.cpp engine
#    dies ("Channel Error", "terminated") and for a few seconds every request
#    fails — in story_benchmark_20260829_081332 every model after the first
#    failure "failed to load" in 0.3 s. native_chat() waits for LM Studio to
#    answer again (wait_until_ready) and retries once instead of failing too.
# 3. Not enough VRAM. With ComfyUI holding 11 of 16 GB, any model over ~5 GB
#    fails or crawls on the CPU. Before a model is loaded, ensure_room() checks
#    its size against the free VRAM and, when ComfyUI's own share would make
#    the difference, asks ComfyUI to free it (POST /free, the same call the
#    app's "Free memory" buttons make).

import subprocess  # noqa: E402
import time  # noqa: E402
from urllib.error import URLError  # noqa: E402

# Text of errors that mean "the engine is down or restarting", not "this
# request is wrong". Lower-case; matched against str(exc).
_ENGINE_DOWN_MARKERS = (
    "channel error",
    "terminated",
    "failed to load model",
    "model has crashed",
    "exited unexpectedly",
    "connection refused",
    "connection reset",
    "remote end closed",
    "http error 502",
    "http error 503",
    "no model loaded",
    "model unloaded",
)
READY_TIMEOUT_SEC = 120

# Room a model needs beyond its file size: KV cache for a normal context plus
# CUDA/runtime buffers. Deliberately rough — the check exists to catch the
# clearly-won't-fit case (a 9 GB model with 4 GB free), not to predict to the
# megabyte, and LM Studio can still offload layers to the CPU.
_LOAD_OVERHEAD_FACTOR = 1.1
_LOAD_OVERHEAD_BYTES = 800 * 1024 * 1024
# Below this ComfyUI holds nothing worth unloading.
_COMFY_MIN_FREEABLE = 512 * 1024 * 1024


def looks_like_engine_down(exc: BaseException) -> bool:
    if isinstance(exc, (URLError, ConnectionError, TimeoutError)):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _ENGINE_DOWN_MARKERS)


def is_ready(base_url: str) -> bool:
    try:
        http_json(rest_models_endpoint(base_url), timeout=5)
        return True
    except Exception:
        try:
            http_json(models_endpoint(base_url), timeout=5)
            return True
        except Exception:
            return False


def wait_until_ready(base_url: str, timeout: float = READY_TIMEOUT_SEC, interval: float = 2.0) -> bool:
    """Poll LM Studio until it answers twice in a row (the first answer after
    an engine restart is sometimes followed by another failure), or until
    ``timeout`` seconds pass. Returns whether it is back."""
    deadline = time.monotonic() + timeout
    good = 0
    while time.monotonic() < deadline:
        if is_ready(base_url):
            good += 1
            if good >= 2:
                return True
        else:
            good = 0
        time.sleep(interval)
    return False


def _is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def gpu_memory(lmstudio_url: str, comfy_url: str = "") -> dict[str, Any] | None:
    """Free / total VRAM of the GPU LM Studio would load onto, or None when it
    can't be known (LM Studio on another machine and no ComfyUI beside it).

    nvidia-smi first: it sees the whole card (other programs included), which
    is what decides whether a load fits. ComfyUI's /system_stats as fallback —
    its vram_free is also device-wide, just less exact."""
    if _is_local(lmstudio_url):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.free,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=4,
            ).stdout
            rows = [[int(x) for x in line.split(",")] for line in out.strip().splitlines() if "," in line]
            if rows:
                free_mb, total_mb = max(rows)
                return {"free": free_mb * 1024 * 1024, "total": total_mb * 1024 * 1024, "source": "nvidia-smi"}
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    if comfy_url and (_is_local(comfy_url) == _is_local(lmstudio_url)):
        try:
            dev = (http_json(f"{comfy_url.rstrip('/')}/system_stats", timeout=5).get("devices") or [{}])[0]
            if dev.get("vram_total"):
                return {"free": int(dev.get("vram_free") or 0), "total": int(dev["vram_total"]), "source": "comfyui"}
        except Exception:
            pass
    return None


def comfy_held_bytes(comfy_url: str) -> int:
    """VRAM ComfyUI's PyTorch allocator holds (models kept loaded between
    generations) — what POST /free gives back."""
    if not comfy_url:
        return 0
    try:
        dev = (http_json(f"{comfy_url.rstrip('/')}/system_stats", timeout=5).get("devices") or [{}])[0]
        return int(dev.get("torch_vram_total") or 0)
    except Exception:
        return 0


def model_footprints(base_url: str) -> dict[str, dict[str, Any]]:
    """model key → {size, loaded} from /api/v1/models."""
    try:
        payload = http_json(rest_models_endpoint(base_url), timeout=10)
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for entry in _coerce_model_entries(payload):
        key = _entry_model_id(entry) or _entry_model_name(entry)
        if not key:
            continue
        size = entry.get("size_bytes")
        out[key] = {
            "size": int(size) if isinstance(size, (int, float)) and size > 0 else None,
            "loaded": bool(entry.get("loaded_instances")) or _entry_is_loaded(entry),
        }
    return out


def required_bytes(size: int) -> int:
    return int(size * _LOAD_OVERHEAD_FACTOR) + _LOAD_OVERHEAD_BYTES


def vram_report(lmstudio_url: str, comfy_url: str = "") -> dict[str, Any]:
    """Everything the model pickers need to mark what fits: free VRAM, what
    ComfyUI could give back, and each model's size and state."""
    mem = gpu_memory(lmstudio_url, comfy_url)
    held = comfy_held_bytes(comfy_url) if mem else 0
    models = model_footprints(lmstudio_url)
    rows = {}
    for key, info in models.items():
        need = required_bytes(info["size"]) if info["size"] else None
        if info["loaded"] or not mem or need is None:
            fit = "loaded" if info["loaded"] else "unknown"
        elif need <= mem["free"]:
            fit = "fits"
        elif held >= _COMFY_MIN_FREEABLE and need <= mem["free"] + held:
            fit = "needs_comfy_free"
        else:
            fit = "too_big"
        rows[key] = {"size": info["size"], "loaded": info["loaded"], "need": need, "fit": fit}
    return {
        "known": bool(mem),
        "freeBytes": mem["free"] if mem else None,
        "totalBytes": mem["total"] if mem else None,
        "source": mem["source"] if mem else None,
        "comfyHeldBytes": held,
        "models": rows,
    }


def free_comfy_vram(comfy_url: str) -> bool:
    try:
        http_json(f"{comfy_url.rstrip('/')}/free", method="POST",
                  payload={"unload_models": True, "free_memory": True}, timeout=30)
        return True
    except Exception:
        logger.warning("Could not ask ComfyUI at %s to free memory", comfy_url, exc_info=True)
        return False


def ensure_room(lmstudio_url: str, model: str, comfy_url: str = "") -> dict[str, Any]:
    """Before LM Studio loads ``model``: if it is not loaded yet, will not fit
    in the free VRAM and ComfyUI is holding enough to make it fit, free
    ComfyUI's VRAM. Never raises — a failed check just lets the load go ahead
    (LM Studio may still manage by offloading to the CPU).

    Returns {"action": "none"|"freed_comfy"|"insufficient"|"unknown", ...}."""
    try:
        info = model_footprints(lmstudio_url).get(model)
        if not info or info["loaded"] or not info["size"]:
            return {"action": "none"}
        if comfy_url:
            from . import gpu_coordinator

            # Mid-generation the free-VRAM figure means nothing, and the LM
            # Studio call waits for ComfyUI to finish anyway (gpu_coordinator).
            # native_chat() makes room after a failed load if it comes to that.
            if gpu_coordinator.comfy_busy(comfy_url):
                return {"action": "deferred"}
        mem = gpu_memory(lmstudio_url, comfy_url)
        if not mem:
            return {"action": "unknown"}
        need = required_bytes(info["size"])
        if need <= mem["free"]:
            return {"action": "none", "need": need, "free": mem["free"]}
        held = comfy_held_bytes(comfy_url)
        if held >= _COMFY_MIN_FREEABLE and need <= mem["free"] + held:
            logger.info(
                "LM Studio model %s needs ~%.1f GB, %.1f GB free: freeing ComfyUI's %.1f GB first",
                model, need / 1e9, mem["free"] / 1e9, held / 1e9,
            )
            if free_comfy_vram(comfy_url):
                time.sleep(1.5)
                after = gpu_memory(lmstudio_url, comfy_url) or mem
                return {"action": "freed_comfy", "need": need, "free": after["free"], "freed": held}
        logger.warning(
            "LM Studio model %s needs ~%.1f GB but only %.1f GB of VRAM is free "
            "(ComfyUI holds %.1f GB): it may load partly on the CPU or fail.",
            model, need / 1e9, mem["free"] / 1e9, held / 1e9,
        )
        return {"action": "insufficient", "need": need, "free": mem["free"], "comfyHeld": held}
    except Exception:
        logger.debug("ensure_room check failed", exc_info=True)
        return {"action": "unknown"}


def _registry_comfy_url() -> str:
    """ComfyUI URL from the saved settings — read straight from disk, like
    gpu_coordinator does, so this service needs nothing from app.routes."""
    try:
        from . import gpu_coordinator

        return str(gpu_coordinator._read_settings().get("comfyApiUrl", "") or "").strip()
    except Exception:
        return ""


# Graduated levels aren't supported by every model; LM Studio says so with a
# "not supported by model" error. "off" included: a reasoning-only model
# answers "Reasoning setting 'off' is not supported … Supported settings:
# 'on'", and failing there made it unusable (ministral-3-14b-reasoning: 12 of
# 12 calls dead). Those models then reason whether we like it or not — a slow
# answer beats none.
REASONING_FALLBACK = {"off": "on", "low": "on", "medium": "on", "high": "on"}


def native_chat(
    base_url: str,
    model: str,
    system_prompt: str,
    user_input: Any,
    temperature: float,
    max_tokens: int,
    reasoning: str | None = "off",
    timeout: int = 300,
    comfy_url: str | None = None,
) -> tuple[dict[str, Any], str]:
    """One call to LM Studio's native /api/v1/chat, made reliable:

    - reasoning level honoured, stepping to "on" when the model only reasons
      and omitting the field for models that expose no reasoning setting;
    - VRAM made room for first when the model isn't loaded (ensure_room);
    - when the engine dies or LM Studio stops answering, wait for it to come
      back (up to READY_TIMEOUT_SEC) and try once more — also making room,
      since a failed load is the usual reason it died.

    ``user_input`` is a string or the native parts list
    ([{"type": "text", "content": …}, {"type": "image", "data_url": …}]).
    Returns (response, reasoning level actually used)."""
    comfy = _registry_comfy_url() if comfy_url is None else comfy_url
    url = rest_chat_endpoint(base_url)

    def payload(level: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "system_prompt": system_prompt,
            "input": user_input,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if level is not None:
            body["reasoning"] = level
        return body

    def call(level: str | None) -> dict[str, Any]:
        return http_json(url=url, method="POST", payload=payload(level), timeout=timeout, gpu_category="lmstudio")

    def with_level(level: str | None) -> tuple[dict[str, Any], str | None]:
        try:
            return call(level), level
        except RuntimeError as exc:
            text = str(exc).lower()
            fallback = REASONING_FALLBACK.get(level or "")
            if fallback and "not supported by model" in text:
                return call(fallback), fallback
            if "does not expose reasoning configuration" in text:
                # Plain models reject the field outright, even at "off".
                return call(None), None
            raise

    ensure_room(base_url, model, comfy)
    try:
        response, used = with_level(reasoning)
    except Exception as exc:
        if not looks_like_engine_down(exc):
            raise
        logger.warning("LM Studio failed on %s (%s); waiting for it to come back", model, exc)
        if not wait_until_ready(base_url, READY_TIMEOUT_SEC):
            raise RuntimeError(
                f"LM Studio stopped responding while running {model} and did not come back within "
                f"{READY_TIMEOUT_SEC} s. The model may not fit in the GPU's memory — try a smaller "
                f"model or free ComfyUI's memory. ({exc})"
            ) from exc
        ensure_room(base_url, model, comfy)
        response, used = with_level(reasoning)
    return response, (used or "off")


def native_message_text(response: dict[str, Any]) -> str:
    """Final answer text of a native /api/v1/chat response (reasoning items
    skipped)."""
    output = response.get("output") if isinstance(response, dict) else None
    for item in output if isinstance(output, list) else []:
        if isinstance(item, dict) and str(item.get("type", "")).strip().lower() == "message":
            content = item.get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""
