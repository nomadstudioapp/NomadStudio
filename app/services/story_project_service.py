from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from .. import paths

# Per-story JSON files — one file per Create Story session, living alongside
# the app's other small JSON data stores (see app/data/*.json). Structure per
# the spec: two parallel 1:1 arrays (narrative_thread / scene_thread) instead
# of one array mixing plot language with image-prompt language.
#
#   {
#     "story_id": "story_0007",
#     "title": "...",
#     "narrative_thread": [ { "id": "001", "summary": "..." }, ... ],
#     "scene_thread":     [ { "id": "001", "prompt_used": "...", "style": "...",
#                              "vision_summary": "...", "image_path": "..." }, ... ]
#   }
#
# The History panel and Album are untouched by this — they keep reading the
# existing flat localStorage session list. This is a separate, richer record
# kept per-story for continuity/context purposes (see context_window below),
# not a replacement for either.

STORIES_DIR = paths.data_file("stories")

_lock = threading.Lock()


def _safe_story_id(story_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "", str(story_id or ""))[:64]


def _story_path(story_id: str) -> Path:
    return STORIES_DIR / f"{_safe_story_id(story_id)}.json"


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _next_story_id() -> str:
    STORIES_DIR.mkdir(parents=True, exist_ok=True)
    max_n = 0
    for p in STORIES_DIR.glob("story_*.json"):
        m = re.match(r"story_(\d+)$", p.stem)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"story_{max_n + 1:04d}"


def create_story(title: str = "") -> dict[str, Any]:
    with _lock:
        story_id = _next_story_id()
        data: dict[str, Any] = {
            "story_id": story_id,
            "title": str(title or "").strip(),
            "narrative_thread": [],
            "scene_thread": [],
        }
        _atomic_write(_story_path(story_id), data)
        return data


def load_story(story_id: str) -> dict[str, Any] | None:
    path = _story_path(story_id)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def append_scene(
    story_id: str,
    *,
    narrative_summary: str = "",
    prompt_used: str = "",
    style: str = "",
    vision_summary: str = "",
    image_path: str = "",
) -> dict[str, Any] | None:
    """Appends one 1:1 entry to both narrative_thread and scene_thread.
    Creates the story file (with an empty title) if it's somehow missing —
    callers are expected to have called create_story() first, but a
    generation loop shouldn't hard-fail just because that got skipped.
    """
    with _lock:
        data = load_story(story_id)
        if data is None:
            data = {
                "story_id": _safe_story_id(story_id),
                "title": "",
                "narrative_thread": [],
                "scene_thread": [],
            }
        idx = len(data.get("scene_thread", []))
        entry_id = f"{idx + 1:03d}"
        data.setdefault("narrative_thread", []).append(
            {"id": entry_id, "summary": str(narrative_summary or "").strip()}
        )
        data.setdefault("scene_thread", []).append(
            {
                "id": entry_id,
                "prompt_used": str(prompt_used or "").strip(),
                "style": str(style or "").strip(),
                "vision_summary": str(vision_summary or "").strip(),
                "image_path": str(image_path or "").strip(),
            }
        )
        _atomic_write(_story_path(story_id), data)
        return data


def context_window(story_id: str, n: int = 3) -> dict[str, Any]:
    """The bounded slice actually sent to the LLM for the next turn — never
    the full accumulated story, per the spec (stories can run long; the
    narrative/vision context should stay a fixed-size window, not grow
    unbounded call after call).
    """
    n = max(1, min(int(n or 3), 20))
    data = load_story(story_id) or {}
    narrative = data.get("narrative_thread", [])
    scenes = data.get("scene_thread", [])
    recent_summaries = [
        str(e.get("summary", "")) for e in narrative[-n:] if isinstance(e, dict) and e.get("summary")
    ]
    last_vision_summary = ""
    if scenes and isinstance(scenes[-1], dict):
        last_vision_summary = str(scenes[-1].get("vision_summary", "") or "")
    return {
        "story_id": _safe_story_id(story_id),
        "recent_summaries": recent_summaries,
        "last_vision_summary": last_vision_summary,
        "scene_count": len(scenes),
    }
