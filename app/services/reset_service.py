"""Total reset of Nomad Studio — SIMULATION ONLY for now.

``build_plan`` works out exactly what a reset would do, with counts and
sizes, and nothing else: no function in this module deletes, moves or
writes anything. Execution is added later, once the plan has been reviewed
(the reset's first step will be ``backup_service`` with reason
``before-reset``).

Groups in the plan:
- ``delete``   — always removed: profiles, Sessions, depots, bundles,
                 stories, benchmarks, and the settings (the setup wizard
                 opens again).
- ``optional`` — only if ticked: Build content (styles, characters,
                 backgrounds with their images) and generated images in the
                 image folder.
- ``keep``     — never touched. In OPENHIKER this includes content that will
                 be packages in Nomad Studio but is not yet (the 7 engines,
                 template packs, tag catalogs, library flows), plus ComfyUI
                 and LM Studio models and the backups folder.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import backup_service

# Stop walking the image folder after this many files (count shown as "N+").
_MAX_WALK_FILES = 200_000
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _count(path: Path, key: str | None = None) -> int:
    data = _read_json(path)
    if key and isinstance(data, dict):
        data = data.get(key)
    return len(data) if isinstance(data, (list, dict)) else 0


def _size(path: Path) -> tuple[int, int, bool]:
    """(bytes, files, truncated) for a file or a folder."""
    if path.is_file():
        return path.stat().st_size, 1, False
    total = files = 0
    if not path.is_dir():
        return 0, 0, False
    for root, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
            files += 1
            if files >= _MAX_WALK_FILES:
                return total, files, True
    return total, files, False


def _item(item_id: str, group: str, paths: list[Path], app_dir: Path, **detail: Any) -> dict[str, Any]:
    size = files = 0
    truncated = False
    shown = []
    for p in paths:
        b, f, t = _size(p)
        size += b
        files += f
        truncated = truncated or t
        if p.exists():
            try:
                shown.append(p.relative_to(app_dir.parent).as_posix())
            except ValueError:
                shown.append(str(p))
    return {"id": item_id, "group": group, "bytes": size, "files": files, "truncated": truncated, "paths": shown, **detail}


def build_plan(
    app_dir: Path,
    settings: dict[str, Any],
    imports_count: int,
    include_build: bool,
    include_generated: bool,
) -> dict[str, Any]:
    data = app_dir / "data"
    items: list[dict[str, Any]] = []

    # ── Always removed ──
    items.append(_item("profiles", "delete", [data / "viewers.json"], app_dir, count=_count(data / "viewers.json", "viewers")))
    items.append(_item("sessions", "delete", [data / "sessions.json"], app_dir, count=_count(data / "sessions.json", "sessions")))
    items.append(_item("depots", "delete", [data / "depots.json", data / "bundles.json"], app_dir,
                       count=_count(data / "depots.json", "depots") + _count(data / "bundles.json", "bundles")))
    stories = data / "stories"
    items.append(_item("stories", "delete", [stories], app_dir,
                       count=len(list(stories.glob("*.json"))) if stories.is_dir() else 0))
    items.append(_item("benchmarks", "delete", [data / "story_benchmarks", data / "vision_benchmarks"], app_dir))
    items.append(_item("settings", "delete", [app_dir / backup_service.REGISTRY_REL], app_dir,
                       note="engines-kept"))
    items.append({"id": "browser", "group": "delete", "bytes": 0, "files": 0, "truncated": False, "paths": []})

    # ── Optional: Build content ──
    build_group = "delete" if include_build else "optional"
    items.append(_item("styles", build_group, [data / "styles.json", data / "styles_pages.json", app_dir / "images/styles"], app_dir,
                       count=_count(data / "styles.json"), optional="build"))
    items.append(_item("characters", build_group, [data / "sfw_characters.json", app_dir / "static/images/characters"], app_dir,
                       count=_count(data / "sfw_characters.json"), optional="build"))
    items.append(_item("backgrounds", build_group, [data / "sfw_backgrounds.json", app_dir / "static/images/backgrounds"], app_dir,
                       count=_count(data / "sfw_backgrounds.json"), optional="build"))

    # ── Optional: generated images ──
    output_dir = str(settings.get("outputDir", "") or "").strip()
    gen = _item("generated", "delete" if include_generated else "optional",
                [Path(output_dir)] if output_dir and os.path.isabs(output_dir) else [], app_dir, optional="generated")
    gen["folder"] = output_dir
    items.append(gen)

    # ── Never touched ──
    items.append({"id": "engines", "group": "keep", "count": imports_count, "bytes": 0, "files": 0, "truncated": False, "paths": [], "note": "not-packages-yet"})
    items.append(_item("packContent", "keep", [
        data / "template_packs.json", data / "template_pack_field_values.json",
        data / "sfw_faces.json", data / "sfw_gestures.json", data / "sfw_hair.json", data / "sfw_posture.json",
        data / "library_flows.json", data / "styles_to_import", app_dir / "images/workflow_logos",
    ], app_dir, note="not-packages-yet"))
    items.append({"id": "models", "group": "keep", "bytes": 0, "files": 0, "truncated": False, "paths": []})
    items.append({"id": "backups", "group": "keep", "bytes": 0, "files": 0, "truncated": False,
                  "paths": [str(backup_service.resolve_backup_dir(app_dir, settings))]})

    est = backup_service.estimate(app_dir)
    removed = [i for i in items if i["group"] == "delete"]
    return {
        "simulation": True,
        "includeBuild": include_build,
        "includeGenerated": include_generated,
        "backup": {
            "includesImages": include_build,
            "estimateBytes": est["dataBytes"] + (est["imageBytes"] if include_build else 0),
            "folder": str(backup_service.resolve_backup_dir(app_dir, settings)),
        },
        "items": items,
        "totals": {
            "bytes": sum(i["bytes"] for i in removed),
            "files": sum(i["files"] for i in removed),
        },
    }
