"""First-run setup wizard: service checks and engine model detection.

Spec: docs/SETUP_WIZARD.md (§1 steps, §4 engines).

Engine detection asks ComfyUI itself which model files it can see
(``GET /models/{folder}``) instead of walking a folder on disk, so it also
covers ``extra_model_paths.yaml`` and a ComfyUI running on another machine.
The models folder path is only needed later, to download what is missing.

Nothing here writes to the registry or to disk.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from .http_client import http_json

logger = logging.getLogger(__name__)


MODEL_EXTENSIONS = (".safetensors", ".gguf", ".pth", ".pt", ".bin", ".ckpt", ".sft")

# Loader input key -> kind of model file.
_INPUT_KINDS = {
    "unet_name": "unet",
    "unet_unconditional_name": "unet",
    "clip_name": "clip",
    "clip_name1": "clip",
    "clip_name2": "clip",
    "vae_name": "vae",
    "lora_name": "lora",
    "ckpt_name": "checkpoint",
}

# Kind -> ComfyUI model folders where such a file may live. ComfyUI treats
# these as equivalent (clip/text_encoders, unet/diffusion_models).
_KIND_FOLDERS = {
    "unet": ("diffusion_models", "unet"),
    "clip": ("text_encoders", "clip"),
    "vae": ("vae",),
    "lora": ("loras",),
    "checkpoint": ("checkpoints",),
}
_KIND_DEFAULT_FOLDER = {kind: folders[0] for kind, folders in _KIND_FOLDERS.items()}
_SEARCH_FOLDERS = tuple(dict.fromkeys(f for folders in _KIND_FOLDERS.values() for f in folders))

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NomadStudio-setup"}


def _basename(value: str) -> str:
    return re.split(r"[\\/]", str(value or "").strip())[-1]


def _dirname(value: str) -> str:
    parts = [p for p in re.split(r"[\\/]", str(value or "").strip()) if p]
    return "/".join(parts[:-1])


# ── Services ────────────────────────────────────────────────────────────────


def is_local_url(url: str) -> bool:
    """True when *url* points at this machine (loopback or one of its own
    addresses). A ComfyUI on another machine can be detected and used through
    its API, but model files can't be installed into its folders from here."""
    from .local_access import is_local_url as _is_local_url

    return _is_local_url(url)


def check_comfy(comfy_url: str) -> dict[str, Any]:
    """system_stats: reachable, ComfyUI version and GPUs."""
    try:
        stats = http_json(f"{comfy_url}/system_stats", timeout=8)
    except Exception as exc:  # noqa: BLE001 — any failure means "not reachable"
        return {"ok": False, "error": str(exc)}
    system = stats.get("system", {}) if isinstance(stats, dict) else {}
    gpus = []
    for dev in (stats.get("devices") or []) if isinstance(stats, dict) else []:
        name = str(dev.get("name", ""))
        # "cuda:0 NVIDIA GeForce RTX 4060 Ti : cudaMallocAsync" -> readable name
        clean = re.sub(r"^\w+:\d+\s+", "", name).split(" : ")[0].strip() or name
        gpus.append({
            "name": clean,
            "type": dev.get("type"),
            "vramTotal": int(dev.get("vram_total") or 0),
            "vramFree": int(dev.get("vram_free") or 0),
        })
    return {
        "ok": True,
        "version": system.get("comfyui_version"),
        "os": system.get("os"),
        "gpus": gpus,
    }


# ── Find ComfyUI / LM Studio on the local network ───────────────────────────

COMFY_PORTS = (8188, 8000)  # ComfyUI portable/manual · ComfyUI Desktop
LMSTUDIO_PORTS = (1234,)
_SCAN_CONNECT_TIMEOUT_S = 0.4
_SCAN_RETRY_TIMEOUT_S = 1.2  # second round, for addresses that were not in the ARP cache
_SCAN_WORKERS = 160
_SCAN_MAX_HOSTS_PER_SUBNET = 254
_SCAN_MAX_SUBNETS = 4


def _local_subnets() -> list[str]:
    """Private IPv4 /24 prefixes this machine is on ("192.168.1.")."""
    import ipaddress

    from .local_access import _own_addresses

    prefixes: list[str] = []
    for addr in sorted(_own_addresses()):
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local:
            continue
        prefix = ".".join(addr.split(".")[:3]) + "."
        if prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes[:_SCAN_MAX_SUBNETS]


def _port_open(host: str, port: int, timeout: float = _SCAN_CONNECT_TIMEOUT_S) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def discover_services(
    comfy_ports: tuple[int, ...] = COMFY_PORTS,
    lmstudio_ports: tuple[int, ...] = LMSTUDIO_PORTS,
    hosts: list[str] | None = None,
) -> dict[str, Any]:
    """Look for ComfyUI and LM Studio on this machine and its local /24
    networks: a quick TCP check on their usual ports, then a real API call to
    confirm what answers (ComfyUI ``/system_stats``, LM Studio
    ``/api/v1/models``). Only private networks are scanned. Run on request
    from the setup wizard; nothing is saved."""
    import time

    started = time.time()
    if hosts is None:
        hosts = ["127.0.0.1"]
        for prefix in _local_subnets():
            hosts += [f"{prefix}{i}" for i in range(1, _SCAN_MAX_HOSTS_PER_SUBNET + 1)]
    targets = [(h, p, "comfy") for h in hosts for p in comfy_ports] + [(h, p, "lmstudio") for h in hosts for p in lmstudio_ports]

    # Two rounds. The first is quick; over Wi-Fi it misses servers whose
    # address the laptop has not talked to yet, because resolving the MAC
    # address alone can take longer than the timeout (this is why the wizard
    # found nothing on the first search and found it on the second). The
    # second round retries only what did not answer, with room to spare — by
    # then the address is in the ARP cache and the reply is immediate.
    def scan(items: list[tuple], timeout: float) -> tuple[list[tuple], list[tuple]]:
        with ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as pool:
            results = list(pool.map(lambda t: _port_open(t[0], t[1], timeout), items))
        return ([t for t, ok in zip(items, results) if ok],
                [t for t, ok in zip(items, results) if not ok])

    open_targets, missed = scan(targets, _SCAN_CONNECT_TIMEOUT_S)
    if missed:
        retried, _ = scan(missed, _SCAN_RETRY_TIMEOUT_S)
        open_targets += retried

    def confirm(target):
        host, port, kind = target
        url = f"http://{host}:{port}"
        if kind == "comfy":
            res = check_comfy(url)
            if not res.get("ok") or "gpus" not in res:
                return None
            gpu = (res.get("gpus") or [{}])[0]
            return {"kind": kind, "url": url, "host": host, "version": res.get("version"), "gpu": gpu.get("name"),
                    "vramTotal": gpu.get("vramTotal")}
        try:
            data = http_json(f"{url}/api/v1/models", timeout=3)
        except Exception:  # noqa: BLE001
            return None
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return None
        return {"kind": kind, "url": url, "host": host, "models": len(models)}

    with ThreadPoolExecutor(max_workers=16) as pool:
        found = [f for f in pool.map(confirm, open_targets) if f]

    # The same server can show up as 127.0.0.1 and as this machine's LAN
    # address: keep the loopback one.
    own = {"127.0.0.1"}
    try:
        from .local_access import _own_addresses

        own |= _own_addresses()
    except Exception:  # noqa: BLE001
        pass
    result: dict[str, list[dict[str, Any]]] = {"comfy": [], "lmstudio": []}
    for kind in result:
        items = [f for f in found if f["kind"] == kind]
        local_ports = {urlparse_port(f["url"]) for f in items if f["host"] == "127.0.0.1"}
        for f in items:
            if f["host"] != "127.0.0.1" and f["host"] in own and urlparse_port(f["url"]) in local_ports:
                continue
            f["isLocal"] = f["host"] in own
            result[kind].append(f)
    return {**result, "scanned": len(hosts), "seconds": round(time.time() - started, 1)}


def urlparse_port(url: str) -> int | None:
    from urllib.parse import urlparse

    return urlparse(url).port


def check_lmstudio(models_url: str) -> dict[str, Any]:
    try:
        data = http_json(models_url, timeout=5)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    models = data.get("data", []) if isinstance(data, dict) else []
    return {"ok": True, "models": len(models) if isinstance(models, list) else 0}


# ── Recommended language models (LM Studio) ─────────────────────────────────

_RECOMMENDED_LLM_PATH = Path(__file__).resolve().parents[1] / "static" / "data" / "recommended_llm_models.json"
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def recommended_llm_models() -> list[dict[str, Any]]:
    try:
        data = json.loads(_RECOMMENDED_LLM_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning("setup: could not read %s", _RECOMMENDED_LLM_PATH)
        return []
    models = data.get("models", []) if isinstance(data, dict) else []
    return [m for m in models if isinstance(m, dict) and m.get("id")]


def _norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", str(value or "").lower())


def llm_models_status(rest_models_url: str) -> dict[str, Any]:
    """Which recommended models LM Studio already has (GET /api/v1/models).

    A recommended model counts as installed when an LM Studio model key
    contains one of its ``match`` tokens. Tokens are tried in order (most
    specific first, so the exact build from the website beats a sibling like
    ``qwythos-9b-v2``); within a token the shortest key wins."""
    try:
        data = http_json(rest_models_url, timeout=8)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    entries = data.get("models", []) if isinstance(data, dict) else []
    keys = []
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and entry.get("type", "llm") == "llm" and entry.get("key"):
            caps = entry.get("capabilities") if isinstance(entry.get("capabilities"), dict) else {}
            keys.append((str(entry["key"]), bool(caps.get("vision"))))
    out = []
    for rec in recommended_llm_models():
        found: list[tuple[str, bool]] = []
        for tok in (_norm_key(t) for t in rec.get("match", []) if t):
            found = sorted((k for k in keys if tok in _norm_key(k[0])), key=lambda k: len(k[0]))
            if found:
                break
        out.append({
            "id": rec["id"],
            "name": rec.get("name", rec["id"]),
            "quant": rec.get("quant", ""),
            "sizeGb": rec.get("sizeGb"),
            "vramGb": rec.get("vramGb"),
            "installedKey": found[0][0] if found else None,
            "vision": found[0][1] if found else None,
        })
    return {"ok": True, "models": out}


def llm_download_start(rest_models_url: str, model_id: str) -> dict[str, Any]:
    """Ask LM Studio to download a recommended model (never an arbitrary one).
    LM Studio keeps downloading in the background even if the wizard closes."""
    rec = next((m for m in recommended_llm_models() if m["id"] == model_id), None)
    if rec is None:
        return {"ok": False, "error": "unknown model"}
    body: dict[str, Any] = {"model": rec["download"]}
    if rec.get("quantization"):
        body["quantization"] = rec["quantization"]
    try:
        res = http_json(f"{rest_models_url}/download", method="POST", payload=body, timeout=60)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    if not isinstance(res, dict):
        return {"ok": False, "error": "unexpected LM Studio response"}
    return {"ok": True, "jobId": res.get("job_id"), "status": res.get("status"), "totalBytes": res.get("total_size_bytes")}


def llm_download_status(rest_models_url: str, job_id: str) -> dict[str, Any]:
    if not _JOB_ID_RE.match(str(job_id or "")):
        return {"ok": False, "error": "invalid job id"}
    try:
        res = http_json(f"{rest_models_url}/download/status/{job_id}", timeout=10)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    if not isinstance(res, dict):
        return {"ok": False, "error": "unexpected LM Studio response"}
    return {
        "ok": True,
        "status": res.get("status"),
        "downloadedBytes": res.get("downloaded_bytes"),
        "totalBytes": res.get("total_size_bytes"),
        "bytesPerSecond": res.get("bytes_per_second"),
    }


# ── Model files visible to ComfyUI ────────────────────────────────────────────


def comfy_model_index(comfy_url: str) -> tuple[dict[str, list[str]], list[str]]:
    """Return ({basename_lower: ["folder/sub/file", ...]}, available_folders)."""
    folders = http_json(f"{comfy_url}/models", timeout=8)
    available = [f for f in folders if isinstance(f, str)] if isinstance(folders, list) else []
    wanted = [f for f in _SEARCH_FOLDERS if f in available]

    def fetch(folder: str) -> tuple[str, list[str]]:
        try:
            items = http_json(f"{comfy_url}/models/{quote(folder)}", timeout=15)
            return folder, [str(i) for i in items] if isinstance(items, list) else []
        except Exception:  # noqa: BLE001
            logger.warning("setup: could not list ComfyUI models folder %s", folder)
            return folder, []

    index: dict[str, list[str]] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for folder, items in pool.map(fetch, wanted):
            for rel in items:
                rel_norm = rel.replace("\\", "/")
                index.setdefault(_basename(rel_norm).lower(), []).append(f"{folder}/{rel_norm}")
    return index, available


# ── Engines ─────────────────────────────────────────────────────────────────


def _engine_downloads(imp: dict[str, Any]) -> list[dict[str, str]]:
    """Downloads an engine carries besides its workflow: annotation.downloads
    (engine packages put there the addresses their workflow does not declare,
    and the import screen stores the ones added by hand)."""
    annotation = imp.get("annotation") if isinstance(imp.get("annotation"), dict) else {}
    return [d for d in (annotation.get("downloads") or []) if isinstance(d, dict)]


def _loader_refs(workflow: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key, kind in _INPUT_KINDS.items():
            value = inputs.get(key)
            if not isinstance(value, str) or not value.lower().endswith(MODEL_EXTENSIONS):
                continue
            base = _basename(value).lower()
            if base in seen:
                continue
            seen.add(base)
            refs.append({"kind": kind, "value": value})
    return refs


def _quant_options(config: dict[str, Any]) -> list[dict[str, Any]]:
    quant = config.get("quantization") if isinstance(config, dict) else None
    if not isinstance(quant, dict):
        return []
    options = []
    for key, raw in quant.items():
        files: list[dict[str, str]] = []
        label = str(key).upper()
        if isinstance(raw, str):
            files.append({"kind": "unet", "value": raw})
        elif isinstance(raw, dict):
            label = str(raw.get("label") or label)
            for field, kind in (("unet_name", "unet"), ("unet_unconditional_name", "unet"), ("clip_name", "clip")):
                if isinstance(raw.get(field), str) and raw[field].strip():
                    files.append({"kind": kind, "value": raw[field]})
        if files:
            options.append({"key": str(key), "label": label, "files": files})
    return options


def _recommend(options: list[dict[str, Any]], gpus: list[dict[str, Any]]) -> str | None:
    """Pick a quantization option for the user's GPU. Orientative (spec §4.3)."""
    if not options:
        return None
    vram_gb = max((g.get("vramTotal", 0) for g in gpus), default=0) / (1024 ** 3)
    names = " ".join(str(g.get("name", "")) for g in gpus).lower()
    supports_nvfp4 = "rtx 50" in names or "blackwell" in names
    if vram_gb >= 20:
        order = ["fp8", "bf16", "int8", "w4a8", "int4"]
    elif vram_gb >= 12:
        order = ["int8", "fp8", "w4a8", "int4", "bf16"]
    else:
        order = ["int4", "w4a8", "int8", "fp8"]
    size_pref = "9b" if vram_gb >= 12 else "4b"

    def score(opt: dict[str, Any]) -> tuple[int, int, int]:
        text = f"{opt['key']} {opt['label']}".lower()
        if "nvfp4" in text and not supports_nvfp4:
            return (9, 999, 9)
        # Never recommend a variant the wizard cannot install: a file that is
        # neither present nor downloadable would leave the engine unusable.
        installable = all(f.get("present") or f.get("url") for f in opt.get("files", []))
        prec = next((i for i, tok in enumerate(order) if tok in text), 50)
        size = 0 if (size_pref in text or ("4b" not in text and "9b" not in text)) else 1
        return (0 if installable else 1, prec, size)

    return min(options, key=score)["key"]


def detect_engines(
    imports: list[dict[str, Any]],
    comfy_url: str,
    gpus: list[dict[str, Any]],
    parse_config,
    extract_downloads,
) -> dict[str, Any]:
    """Status of every engine against the files ComfyUI can see.

    ``parse_config`` / ``extract_downloads`` are the app's own workflow
    helpers (imports_routes), passed in to avoid an import cycle.
    """
    index, available = comfy_model_index(comfy_url)

    def locate(value: str) -> str | None:
        hits = index.get(_basename(value).lower())
        return hits[0] if hits else None

    engines = []
    for imp in imports:
        workflow = imp.get("workflow") if isinstance(imp.get("workflow"), dict) else {}
        name = str(imp.get("name") or imp.get("id") or "")
        config = parse_config(workflow) or {}

        downloads: dict[str, dict[str, str]] = {}
        for d in list(extract_downloads(workflow)) + _engine_downloads(imp):
            fname = _basename(d.get("filename", ""))
            if fname and d.get("url"):
                downloads.setdefault(fname.lower(), {"subfolder": str(d.get("subfolder", "")), "url": d["url"]})

        def describe(ref: dict[str, str]) -> dict[str, Any]:
            fname = _basename(ref["value"])
            found = locate(ref["value"])
            dl = downloads.get(fname.lower())
            default_folder = _KIND_DEFAULT_FOLDER[ref["kind"]]
            if dl:
                sub = dl["subfolder"].replace("\\", "/").strip("/")
                first = sub.split("/")[0] if sub else ""
                # A declared subfolder that is not a ComfyUI model folder
                # (e.g. "krea2") is relative to the loader's default folder.
                subfolder = sub if first in available else "/".join(p for p in (default_folder, sub) if p)
            else:
                subfolder = "/".join(p for p in (default_folder, _dirname(ref["value"])) if p)
            return {
                "kind": ref["kind"],
                "filename": fname,
                "present": found is not None,
                "foundAt": found,
                "subfolder": subfolder,
                "url": dl["url"] if dl else None,
            }

        options = _quant_options(config)
        option_names = {_basename(f["value"]).lower() for o in options for f in o["files"]}
        common = [describe(r) for r in _loader_refs(workflow) if _basename(r["value"]).lower() not in option_names]

        opt_out = []
        for opt in options:
            files = [describe(f) for f in opt["files"]]
            opt_out.append({
                "key": opt["key"],
                "label": opt["label"],
                "files": files,
                "installed": all(f["present"] for f in files),
            })

        installed_option = next((o["key"] for o in opt_out if o["installed"]), None)
        common_missing = [f for f in common if not f["present"]]
        if options:
            if installed_option and not common_missing:
                status = "ready"
            elif installed_option or any(f["present"] for f in common):
                status = "incomplete"
            else:
                status = "not_installed"
        else:
            if not common_missing:
                status = "ready"
            elif len(common_missing) < len(common):
                status = "incomplete"
            else:
                status = "not_installed"

        engines.append({
            "id": imp.get("id"),
            "name": name,
            "status": status,
            "options": opt_out,
            "installedOption": installed_option,
            "recommendedOption": installed_option or _recommend(opt_out, gpus),
            "common": common,
        })

    return {"engines": engines, "folders": available}


def validate_models_folder(path: str, index: dict[str, list[str]]) -> dict[str, Any]:
    """Check that a folder on disk is the one ComfyUI reads: the files ComfyUI
    lists must exist under it. Returns how many of a sample were found."""
    base = Path(path)
    if not base.is_dir():
        return {"ok": False, "reason": "not_found", "checked": 0, "matched": 0}
    sample = [rel for rels in index.values() for rel in rels][:40]
    if not sample:
        return {"ok": True, "reason": "comfy_has_no_models", "checked": 0, "matched": 0}
    matched = sum(1 for rel in sample if base.joinpath(*rel.split("/")).is_file())
    return {
        "ok": matched > 0,
        "reason": None if matched else "no_match",
        "checked": len(sample),
        "matched": matched,
    }


def remote_sizes(urls: list[str]) -> dict[str, int | None]:
    """Content-Length of each URL (HEAD, following redirects)."""

    def head(url: str) -> tuple[str, int | None]:
        try:
            req = Request(url, headers=_UA, method="HEAD")
            with urlopen(req, timeout=15) as resp:
                length = resp.headers.get("Content-Length")
                return url, int(length) if length and length.isdigit() else None
        except Exception:  # noqa: BLE001
            return url, None

    unique = list(dict.fromkeys(u for u in urls if isinstance(u, str) and u.startswith("https://")))[:40]
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(head, unique))


def free_space(path: str) -> int | None:
    try:
        target = Path(path)
        while not target.exists() and target != target.parent:
            target = target.parent
        return shutil.disk_usage(target).free
    except Exception:  # noqa: BLE001
        return None


def sync_folder_warning(path: str) -> str | None:
    """Folders that sync or get locked are a poor place for generated images."""
    low = str(path or "").replace("\\", "/").lower()
    for marker, key in (("onedrive", "onedrive"), ("dropbox", "dropbox"), ("icloud", "icloud"), ("google drive", "gdrive")):
        if marker in low:
            return key
    if re.search(r"/(documents|documentos|pictures|imágenes|imagenes|desktop|escritorio)(/|$)", low):
        return "protected"
    return None
