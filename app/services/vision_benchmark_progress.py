from __future__ import annotations

from threading import Lock
from typing import Any


_lock = Lock()
_progress_by_run: dict[str, dict[str, Any]] = {}


def init_run(run_id: str, models: list[dict[str, Any]]) -> None:
    key = str(run_id or "").strip()
    if not key:
        return

    cards: list[dict[str, Any]] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("id", "")).strip()
        if not model_id:
            continue
        cards.append(
            {
                "model": model_id,
                "visionSource": str(model.get("source", "unknown")),
                "reasoning": bool(model.get("reasoning", False)),
                "reasoningOptions": list(model.get("reasoningOptions", []))
                if isinstance(model.get("reasoningOptions"), list)
                else [],
                "status": "pending",
                "description": "",
                "error": "",
                "durationMs": 0,
            }
        )

    with _lock:
        _progress_by_run[key] = {
            "runId": key,
            "running": True,
            "stopped": False,
            "cards": cards,
            "summary": {"total": len(cards), "ok": 0, "failed": 0, "done": 0},
        }


def mark_stopped(run_id: str) -> None:
    key = str(run_id or "").strip()
    if not key:
        return
    with _lock:
        state = _progress_by_run.get(key)
        if not isinstance(state, dict):
            return
        state["stopped"] = True


def mark_model_started(run_id: str, model_id: str) -> None:
    key = str(run_id or "").strip()
    target = str(model_id or "").strip()
    if not key or not target:
        return
    with _lock:
        state = _progress_by_run.get(key)
        if not isinstance(state, dict):
            return
        cards = state.get("cards", []) if isinstance(state.get("cards"), list) else []
        for card in cards:
            if not isinstance(card, dict):
                continue
            if str(card.get("model", "")) != target:
                continue
            if str(card.get("status", "")) == "pending":
                card["status"] = "running"
                break


def mark_model_finished(run_id: str, model_result: dict[str, Any]) -> None:
    key = str(run_id or "").strip()
    model_id = str(model_result.get("model", "")).strip()
    if not key or not model_id:
        return

    with _lock:
        state = _progress_by_run.get(key)
        if not isinstance(state, dict):
            return

        cards = state.get("cards", []) if isinstance(state.get("cards"), list) else []
        for card in cards:
            if not isinstance(card, dict):
                continue
            if str(card.get("model", "")) != model_id:
                continue
            ok = bool(model_result.get("ok"))
            card["status"] = "ok" if ok else "failed"
            card["description"] = str(model_result.get("description", ""))
            card["error"] = str(model_result.get("error", ""))
            card["durationMs"] = int(model_result.get("durationMs", 0) or 0)
            break

        ok_count = 0
        failed_count = 0
        done_count = 0
        for card in cards:
            if not isinstance(card, dict):
                continue
            status = str(card.get("status", ""))
            if status == "ok":
                ok_count += 1
                done_count += 1
            elif status == "failed":
                failed_count += 1
                done_count += 1

        summary = (
            state.get("summary", {}) if isinstance(state.get("summary"), dict) else {}
        )
        summary["ok"] = ok_count
        summary["failed"] = failed_count
        summary["done"] = done_count
        state["summary"] = summary


def finish_run(run_id: str, stopped: bool = False) -> None:
    key = str(run_id or "").strip()
    if not key:
        return
    with _lock:
        state = _progress_by_run.get(key)
        if not isinstance(state, dict):
            return
        state["running"] = False
        state["stopped"] = bool(stopped)


def get_progress(run_id: str) -> dict[str, Any] | None:
    key = str(run_id or "").strip()
    if not key:
        return None
    with _lock:
        state = _progress_by_run.get(key)
        if not isinstance(state, dict):
            return None
        cards_copy = []
        for card in (
            state.get("cards", []) if isinstance(state.get("cards"), list) else []
        ):
            if isinstance(card, dict):
                cards_copy.append(dict(card))
        summary = (
            state.get("summary", {}) if isinstance(state.get("summary"), dict) else {}
        )
        return {
            "runId": key,
            "running": bool(state.get("running", False)),
            "stopped": bool(state.get("stopped", False)),
        }
