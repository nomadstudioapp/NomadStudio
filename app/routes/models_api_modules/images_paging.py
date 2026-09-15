from __future__ import annotations

import base64
import binascii
import json
from flask import Request

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000


def _coerce_int(raw: str | None, fallback: int) -> int:
    try:
        return int(str(raw or "").strip())
    except Exception:
        return fallback


def encode_cursor_key(mtime_ns: int, filename: str) -> str:
    payload = json.dumps(
        {
            "t": max(0, int(mtime_ns)),
            "n": str(filename or ""),
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decode_cursor_key(cursor: str | None) -> tuple[int, str] | None:
    if not cursor:
        return None
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        data = json.loads(decoded)
        if not isinstance(data, dict):
            return None
        t = int(data.get("t", 0))
        n = str(data.get("n", ""))
        if t <= 0 or not n:
            return None
        return t, n
    except (ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        return None


def parse_image_paging_request(
    request: Request,
) -> tuple[int, int, tuple[int, str] | None, tuple[int, str] | None]:
    requested_limit = _coerce_int(request.args.get("limit"), DEFAULT_LIMIT)
    limit = max(1, min(MAX_LIMIT, requested_limit))

    offset = _coerce_int(request.args.get("offset"), 0)
    if offset < 0:
        offset = 0

    cursor_key = decode_cursor_key(request.args.get("cursor"))
    snapshot_key = decode_cursor_key(request.args.get("snapshot"))

    return limit, offset, cursor_key, snapshot_key


def build_paging_payload(
    total: int,
    limit: int,
    offset: int,
    *,
    has_more: bool,
    next_cursor: str | None,
    snapshot_cursor: str | None,
) -> dict[str, int | bool | str | None]:
    safe_total = max(0, int(total))
    safe_limit = max(1, int(limit))
    safe_offset = max(0, int(offset))
    return {
        "limit": safe_limit,
        "offset": safe_offset,
        "total": safe_total,
        "hasMore": bool(has_more),
        "nextCursor": next_cursor,
        "snapshotCursor": snapshot_cursor,
    }
