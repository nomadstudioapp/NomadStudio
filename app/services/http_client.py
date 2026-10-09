from __future__ import annotations

import json
import os
import uuid
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.services import gpu_coordinator


def http_json(
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 90,
    gpu_category: str | None = None,
) -> dict[str, Any]:
    """`gpu_category` ("comfy"/"lmstudio"): when set, this call waits for the
    other category to be idle before running (see gpu_coordinator) — only
    pass it for calls that are themselves the full GPU-consuming request
    (e.g. LM Studio chat completions, where the HTTP call blocks until the
    whole response is ready). ComfyUI's submit-then-poll-/history loops span
    several http_json calls — those wrap the whole loop in
    `gpu_coordinator.held("comfy")` instead of tagging each call here."""
    body = None
    headers: dict[str, str] = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url=url, data=body, headers=headers, method=method)

    def _do_request() -> dict[str, Any]:
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                error_body = ""
            detail = f"HTTP Error {exc.code}: {exc.reason}"
            if error_body:
                detail = f"{detail} | {error_body}"
            raise RuntimeError(detail) from exc
        return json.loads(raw) if raw else {}

    if gpu_category:
        with gpu_coordinator.held(gpu_category):
            return _do_request()
    return _do_request()


def download_url(url: str) -> str:
    """Where to fetch a public download (model files, ComfyUI, installers).

    Normally the URL itself. With NOMAD_DOWNLOAD_MIRROR set (e.g.
    http://127.0.0.1:8890), https://host/path?q becomes <mirror>/host/path?q:
    a local copy for recording install tutorials without waiting for the same
    gigabytes again; the mirror redirects to the original URL for anything it
    does not hold. Not a user setting — an environment variable for that one
    use."""
    mirror = os.environ.get("NOMAD_DOWNLOAD_MIRROR", "").strip().rstrip("/")
    if mirror and url.startswith("https://"):
        return f"{mirror}/{url[len('https://'):]}"
    return url


def http_bytes(url: str, timeout: int = 90) -> bytes:
    headers: dict[str, str] = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    request = Request(url=url, headers=headers, method="GET")
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def http_multipart_upload_image(
    url: str, filename: str, file_bytes: bytes, mime_type: str
) -> dict[str, Any]:
    boundary = f"----OpenJourneyBoundary{uuid.uuid4().hex}"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = head + file_bytes + tail

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    request_obj = Request(
        url=url,
        data=body,
        headers=headers,
        method="POST",
    )
    with urlopen(request_obj, timeout=90) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}
