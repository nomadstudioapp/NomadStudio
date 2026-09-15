"""Exclusion mutua entre trabajo de ComfyUI y de LM Studio.

En un servidor compartido por varios clientes, ComfyUI y LM Studio pueden
acabar compitiendo por la misma GPU si se lanzan a la vez (una generación de
imagen mientras otro cliente usa el chat/vision/prompt-assist). Por defecto
uno espera al otro: mientras la categoria "comfy" tenga algo activo, un
intento de "lmstudio" espera (y viceversa) — varios trabajos DENTRO de la
misma categoria si pueden convivir (varias generaciones de ComfyUI a la vez
ya es normal, lo gestiona la propia cola de ComfyUI).

Dentro de un proceso basta el lock en memoria (`app.py` corre `threaded=True`,
sin multi-worker). Pero varias INSTALACIONES de Nomad Studio (p. ej. un
portatil y una torre) pueden compartir el mismo ComfyUI y LM Studio, y ese
lock no las ve. Para eso esta la "superqueue" (`wait_external`): antes de
empezar, cada lado mira el estado real del otro servidor:

- antes de LM Studio: `GET /queue` de ComfyUI — trabajos en marcha o
  pendientes de CUALQUIER cliente, incluidos los que el navegador envia
  directamente a ComfyUI (que no pasan por este lock);
- antes de ComfyUI: `listLoaded` de LM Studio por su websocket — un modelo
  cargado con `lastUsedTime` a null esta generando (medido 2026-09-15: la
  señal llega con ~1-2 s de retraso al empezar, es exacta en vision, y un
  cliente que abandona la peticion la libera en ~1 s).

Como la señal de LM Studio llega tarde y dos instalaciones pueden mirar a la
vez, se añade una pequeña espera aleatoria y, tras ver "ocupado", se exigen
dos lecturas libres seguidas. No es un arbitro perfecto (no hay servidor
central); reduce los choques a casos raros. Si el otro servidor no responde,
no se espera (fallar hacia "seguir", para no colgar la app sin LM Studio).
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .. import paths

logger = logging.getLogger(__name__)

_REGISTRY_PATH = paths.REGISTRY_PATH

_cond = threading.Condition()
_active: dict[str, dict[str, float | None]] = {"comfy": {}, "lmstudio": {}}


def _other(category: str) -> str:
    return "lmstudio" if category == "comfy" else "comfy"


def _sweep_locked(category: str) -> None:
    now = time.time()
    dead = [tok for tok, expires in _active[category].items() if expires is not None and now > expires]
    for tok in dead:
        del _active[category][tok]


def _read_settings() -> dict[str, Any]:
    try:
        raw = _REGISTRY_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        settings = data.get("settings", {})
        return settings if isinstance(settings, dict) else {}
    except Exception:
        return {}


def allow_concurrent() -> bool:
    """Lee settings.allowConcurrentComfyLmstudio directamente del registro en
    disco (sin pasar por app.routes, para no crear una dependencia hacia
    arriba desde este servicio). Falla hacia False (esperar) si el fichero
    no existe o no se puede leer — nunca hacia "correr a la vez sin avisar"."""
    return bool(_read_settings().get("allowConcurrentComfyLmstudio", False))


def common_queue() -> bool:
    """settings.commonQueueComfyLmstudio: modo mas estricto que el mutex por
    categoria de arriba — con esto activo, ComfyUI y LM Studio comparten una
    unica cola: nunca hay mas de UN trabajo activo en total (ni siquiera dos
    de la misma categoria a la vez), en vez de solo excluirse entre
    categorias. Tiene prioridad sobre allow_concurrent() si ambos estuvieran
    activos a la vez (no debería configurarse así desde la UI, pero por si
    acaso: "una sola cola" es la lectura mas segura de esa combinacion)."""
    return bool(_read_settings().get("commonQueueComfyLmstudio", False))


def acquire(category: str, token: str, ttl: float | None = None, poll_interval: float = 0.25) -> None:
    """Bloquea segun el modo activo, y registra `token` como activo en
    `category`. `ttl` (segundos) es una red de seguridad para trabajos
    fire-and-forget cuyo release podria no llegar nunca (cliente que deja de
    hacer polling, crash...) — pasado ese tiempo el token se considera
    caducado y deja de bloquear.

    Modos (de mas a menos estricto, se evalua uno solo por llamada):
    - common_queue(): espera a que AMBAS categorias esten vacias — una unica
      cola global, un trabajo activo como mucho en todo el servidor.
    - por defecto (ninguno de los dos ajustes activo): espera solo a que la
      categoria CONTRARIA este vacia — varios trabajos de la misma categoria
      si pueden convivir (varias generaciones de ComfyUI a la vez ya es
      normal, lo gestiona la propia cola de ComfyUI).
    - allow_concurrent(): no espera nada, registra y devuelve al momento.

    Antes del lock en memoria, espera tambien al otro servidor si lo esta
    usando otra instalacion (``wait_external``), salvo con allow_concurrent()."""
    wait_external(category)
    with _cond:
        if common_queue():
            while True:
                _sweep_locked("comfy")
                _sweep_locked("lmstudio")
                if not _active["comfy"] and not _active["lmstudio"]:
                    break
                _cond.wait(poll_interval)
        elif not allow_concurrent():
            while True:
                _sweep_locked(_other(category))
                if not _active[_other(category)]:
                    break
                _cond.wait(poll_interval)
        _active[category][token] = (time.time() + ttl) if ttl is not None else None


# ── Superqueue: the other server's real state ──────────────────────────────

EXTERNAL_MAX_WAIT_S = 600.0  # never block a request forever on someone else's batch
_CHECK_TIMEOUT_S = 3.0
_POLL_S = 1.0
_CACHE_TTL_S = 0.5
_cache: dict[str, tuple[float, bool]] = {}
_cache_lock = threading.Lock()


_UNREACHABLE_TTL_S = 15.0
_CONNECT_TIMEOUT_S = 0.3
_unreachable: dict[str, float] = {}


def _reachable(url: str) -> bool:
    """Fast TCP check, remembered for a while when it fails. Without it a
    stopped LM Studio or ComfyUI (both optional) would add seconds to every
    job: Windows takes ~2 s to refuse a closed port, the SDK ~1 s."""
    import socket

    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    key = f"{host}:{port}"
    until = _unreachable.get(key)
    if until and time.time() < until:
        return False
    try:
        with socket.create_connection((host, port), timeout=_CONNECT_TIMEOUT_S):
            pass
    except OSError:
        _unreachable[key] = time.time() + _UNREACHABLE_TTL_S
        return False
    _unreachable.pop(key, None)
    return True


def comfy_busy(comfy_url: str) -> bool:
    """ComfyUI has anything running or queued (from any client)."""
    if not _reachable(comfy_url):
        return False
    try:
        with urlopen(Request(f"{comfy_url.rstrip('/')}/queue"), timeout=_CHECK_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception:  # noqa: BLE001 — unreachable: don't block on it
        return False
    return bool(data.get("queue_running")) or bool(data.get("queue_pending"))


def lmstudio_busy(lmstudio_url: str) -> bool:
    """A loaded LM Studio model is generating: its lastUsedTime is null while
    a request is in progress (not exposed by the REST API)."""
    parsed = urlparse(lmstudio_url)
    host = f"{parsed.hostname or 'localhost'}:{parsed.port or 1234}"
    if not _reachable(f"http://{host}"):
        return False
    try:
        import lmstudio as lms

        with lms.Client(host) as client:
            rows = client.llm.remote_call("listLoaded")
    except Exception:  # noqa: BLE001
        return False
    return any(isinstance(r, dict) and r.get("lastUsedTime") is None for r in rows or [])


def _external_busy(category: str) -> bool:
    """Is the OTHER server of *category* busy right now? (cached briefly so a
    burst of requests doesn't hammer it)."""
    key = _other(category)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL_S:
            return hit[1]
    settings = _read_settings()
    if key == "comfy":
        url = str(settings.get("comfyApiUrl", "") or "").strip()
        busy = comfy_busy(url) if url else False
    else:
        url = str(settings.get("lmStudioApiUrl", "") or "").strip()
        busy = lmstudio_busy(url) if url else False
    with _cache_lock:
        _cache[key] = (time.time(), busy)
    return busy


def _invalidate(category: str) -> None:
    with _cache_lock:
        _cache.pop(category, None)


def wait_external(category: str) -> float:
    """Wait while the other GPU server is busy. Returns seconds waited.

    Does nothing with allow_concurrent(). A short random delay first spreads
    out two installations checking at the same moment; after seeing "busy",
    two consecutive "free" readings are required (LM Studio's signal lags)."""
    if allow_concurrent():
        return 0.0
    time.sleep(random.uniform(0.0, 0.3))
    start = time.time()
    if not _external_busy(category):
        return 0.0
    logger.info("superqueue: %s waiting for %s used by another client", category, _other(category))
    free_in_a_row = 0
    while time.time() - start < EXTERNAL_MAX_WAIT_S:
        time.sleep(_POLL_S)
        _invalidate(_other(category))
        if _external_busy(category):
            free_in_a_row = 0
        else:
            free_in_a_row += 1
            if free_in_a_row >= 2:
                break
    else:
        logger.warning("superqueue: %s gave up waiting for %s after %.0fs", category, _other(category), EXTERNAL_MAX_WAIT_S)
    waited = time.time() - start
    logger.info("superqueue: %s waited %.1fs", category, waited)
    return waited


def release(category: str, token: str) -> None:
    with _cond:
        _active[category].pop(token, None)
        _cond.notify_all()


class held:
    """Context manager: with gpu_coordinator.held("comfy"): ...  — genera un
    token, hace acquire/release automaticamente. Para el caso bloqueante
    (la peticion Flask se queda esperando el resultado dentro del `with`)."""

    def __init__(self, category: str, ttl: float | None = None) -> None:
        self.category = category
        self.ttl = ttl
        self.token = uuid.uuid4().hex

    def __enter__(self) -> "held":
        acquire(self.category, self.token, ttl=self.ttl)
        return self

    def __exit__(self, *exc_info: Any) -> None:
        release(self.category, self.token)
