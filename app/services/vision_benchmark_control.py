from __future__ import annotations

from threading import Lock


_lock = Lock()
_active_runs: set[str] = set()
_stop_requested: set[str] = set()


def start_run(run_id: str) -> None:
    key = str(run_id or "").strip()
    if not key:
        return
    with _lock:
        _active_runs.add(key)
        _stop_requested.discard(key)


def request_stop(run_id: str) -> bool:
    key = str(run_id or "").strip()
    if not key:
        return False
    with _lock:
        if key not in _active_runs:
            return False
        _stop_requested.add(key)
        return True


def should_stop(run_id: str) -> bool:
    key = str(run_id or "").strip()
    if not key:
        return False
    with _lock:
        return key in _stop_requested


def finish_run(run_id: str) -> None:
    key = str(run_id or "").strip()
    if not key:
        return
    with _lock:
        _active_runs.discard(key)
        _stop_requested.discard(key)
