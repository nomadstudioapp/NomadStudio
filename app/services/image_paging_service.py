from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services import image_service


def _sort_key(path: Path) -> tuple[int, str]:
    stat = path.stat()
    return stat.st_mtime_ns, path.name


def list_images_page(
    output_dir: str,
    *,
    limit: int,
    offset: int,
    cursor_key: tuple[int, str] | None = None,
    snapshot_key: tuple[int, str] | None = None,
) -> dict[str, Any]:
    safe_limit = max(1, int(limit))
    safe_offset = max(0, int(offset))

    files = image_service.list_image_files_sorted(output_dir)
    resolved_snapshot_key = snapshot_key
    if resolved_snapshot_key is None and files:
        resolved_snapshot_key = _sort_key(files[0])

    scoped_files = files
    if resolved_snapshot_key is not None:
        scoped_files = [
            path for path in files if _sort_key(path) <= resolved_snapshot_key
        ]

    total = len(scoped_files)

    if cursor_key:
        eligible = [path for path in scoped_files if _sort_key(path) < cursor_key]
        page_files = eligible[:safe_limit]
    else:
        page_files = scoped_files[safe_offset : safe_offset + safe_limit]

    images: list[dict[str, Any]] = []
    seen_filenames: set[str] = set()
    for path in page_files:
        if path.name in seen_filenames:
            continue
        seen_filenames.add(path.name)
        entry = image_service.read_image_entry(path)
        if entry is None:
            continue
        images.append(entry)

    if cursor_key:
        has_more = len(
            [path for path in scoped_files if _sort_key(path) < cursor_key]
        ) > len(page_files)
    else:
        has_more = (safe_offset + safe_limit) < total

    next_cursor: tuple[int, str] | None = None
    if page_files and has_more:
        next_cursor = _sort_key(page_files[-1])

    return {
        "images": images,
        "total": total,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "snapshot_key": resolved_snapshot_key,
    }
