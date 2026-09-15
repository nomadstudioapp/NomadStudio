from __future__ import annotations

import base64
from urllib.parse import urlparse

from flask import jsonify, make_response, request, Response, stream_with_context

from app.routes.models_api_shared import (
    _ensure_registry,
    _resolve_output_dir,
    _resolve_viewer_output_dir,
    _active_viewer_id,
    _safe_comfy_url,
    _safe_session_subdir,
    _save_registry,
    _try_save_image_to_output_dir,
    models_api_bp,
)
from app.routes.models_api_modules.images_paging import (
    build_paging_payload,
    encode_cursor_key,
    parse_image_paging_request,
)
from app.services import image_service
from app.services import image_paging_service
from app.services.http_client import http_bytes, http_json


def _resolve_image_path_for_filename(data: dict, filename: str) -> "Path | None":
    """Resolve a client-given image `filename` (same strings serve_image()
    above accepts: a plain viewer-relative name, or a "session/…",
    "bundle/…", "vault/…", "input/…" prefixed relative path) to an on-disk
    Path, or None if it doesn't resolve to a real file.

    Used by update_image_meta() and list_tray_images() — both used to only
    handle plain viewer-relative filenames (a flat `"/" in filename` reject),
    which silently broke Send to Tray/tags/favorite/tray-listing for every
    image generated inside a Session, since those always save under a
    shared "session/<folder>/<file>" path, not the active viewer's own
    folder. Mirrors serve_image()'s own branching so a filename that can be
    *viewed* can also have its metadata edited.
    """
    from pathlib import Path

    filename = str(filename or "")
    shared_output_dir = _resolve_output_dir(data)

    for prefix in ("session/", "bundle/", "vault/"):
        if not filename.startswith(prefix):
            continue
        if not shared_output_dir:
            return None
        rel = filename[len(prefix):].strip("/")
        parts = rel.split("/")
        if not rel or len(parts) > 2 or any(p in (".", "..") or "\\" in p for p in parts):
            return None
        for folder in ("session", "bundle", "vault"):
            candidate = Path(shared_output_dir).joinpath(folder, *parts)
            if candidate.is_file():
                return candidate
        return None

    output_dir = _resolve_viewer_output_dir(data)
    if not output_dir:
        return None

    if filename.startswith("input/"):
        rest = filename[len("input/"):]
        if not rest or "/" in rest or "\\" in rest or ".." in rest:
            return None
        candidate = Path(output_dir) / "input" / rest
        return candidate if candidate.is_file() else None

    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return None
    candidate = Path(output_dir) / filename
    return candidate if candidate.is_file() else None


def _collect_comfy_queue_targets(data: dict, payload: dict) -> list[str]:
    urls: list[str] = []

    # Explicit targets from caller take priority.
    raw_targets = payload.get("comfyApiUrls")
    if isinstance(raw_targets, list):
        for raw in raw_targets:
            value = str(raw or "").strip()
            if value:
                urls.append(value)
    else:
        single = str(payload.get("comfyApiUrl", "")).strip()
        if single:
            urls.append(single)

    # If caller did not provide targets, infer active queue URLs plus default settings URL.
    if not urls:
        imports = (
            data.get("imports", []) if isinstance(data.get("imports", []), list) else []
        )
        active_ids = (
            data.get("activeImportIds", [])
            if isinstance(data.get("activeImportIds", []), list)
            else []
        )
        active_id = str(data.get("activeImportId", "") or "").strip()

        if active_id and active_id not in active_ids:
            active_ids = [active_id, *active_ids]

        for import_id in active_ids:
            record = next(
                (
                    item
                    for item in imports
                    if isinstance(item, dict)
                    and str(item.get("id", "")) == str(import_id)
                ),
                None,
            )
            if not record:
                continue
            value = str(record.get("comfyApiUrl", "")).strip()
            if value:
                urls.append(value)

        default_url = str(data.get("settings", {}).get("comfyApiUrl", "")).strip()
        if default_url:
            urls.append(default_url)

    deduped: list[str] = []
    seen = set()
    for raw in urls:
        try:
            safe = _safe_comfy_url(raw)
        except ValueError:
            continue
        if safe in seen:
            continue
        seen.add(safe)
        deduped.append(safe)

    return deduped


@models_api_bp.get("/images")
def list_images():
    """Return paginated images from the active viewer's own output folder."""
    data = _ensure_registry()
    output_dir = _resolve_viewer_output_dir(data)
    if not output_dir:
        return jsonify({"error": "No active viewer session", "images": [], "paging": {}}), 401
    limit, offset, cursor_key, snapshot_key = parse_image_paging_request(request)
    page = image_paging_service.list_images_page(
        output_dir,
        limit=limit,
        offset=offset,
        cursor_key=cursor_key,
        snapshot_key=snapshot_key,
    )
    next_cursor_value = page.get("next_cursor")
    next_cursor = (
        encode_cursor_key(next_cursor_value[0], next_cursor_value[1])
        if isinstance(next_cursor_value, tuple) and len(next_cursor_value) == 2
        else None
    )
    paging = build_paging_payload(
        page.get("total", 0),
        limit,
        offset,
        has_more=bool(page.get("has_more", False)),
        next_cursor=next_cursor,
        snapshot_cursor=(
            encode_cursor_key(page["snapshot_key"][0], page["snapshot_key"][1])
            if isinstance(page.get("snapshot_key"), tuple)
            and len(page.get("snapshot_key")) == 2
            else None
        ),
    )
    return jsonify(
        {
            "images": page.get("images", []),
            "outputDir": output_dir,
            "paging": paging,
        }
    )


@models_api_bp.get("/images/<path:filename>")
def serve_image(filename: str):
    """Serve a single image file — Sessions from the shared output dir,
    everything else (plain gallery output, saved input references) from the
    active viewer's own subfolder."""
    data = _ensure_registry()
    shared_output_dir = _resolve_output_dir(data)

    # Safety net: Session imports live in the <output>/session subfolder. If the
    # catch-all matched before the dedicated route, serve them from there.
    # "bundle/" and "vault/" are kept as legacy aliases — sessions saved
    # before the Vault → Bundle → Session renames still reference
    # /images/vault/... and /images/bundle/... paths.
    if filename.startswith("session/"):
        return _serve_session_path(shared_output_dir, filename[len("session/"):])
    if filename.startswith("bundle/"):
        return _serve_session_path(shared_output_dir, filename[len("bundle/"):])
    if filename.startswith("vault/"):
        return _serve_session_path(shared_output_dir, filename[len("vault/"):])

    output_dir = _resolve_viewer_output_dir(data)
    if not output_dir:
        return jsonify({"error": "No active viewer session"}), 401

    # Flow reference images (uploaded via /images/save-upload with
    # subdir="input") live in <output>/<viewer-slug>/input/<file>. serve_image()
    # rejects any filename containing "/" as a path-traversal guard, so a plain
    # "input/<file>" would always 404 without this branch — resolve it
    # against the "input" subfolder instead, keeping the same guard on the
    # remaining (single-segment) filename.
    if filename.startswith("input/"):
        from pathlib import Path

        rest = filename[len("input/"):]
        if not rest or "/" in rest or "\\" in rest or ".." in rest:
            return jsonify({"error": "Invalid filename"}), 404
        img_bytes = image_service.serve_image(
            str(Path(output_dir) / "input"), rest
        )
        if img_bytes is None:
            return jsonify({"error": "Image not found"}), 404
        ext = rest.rsplit(".", 1)[-1].lower() if "." in rest else "png"
        mime_map = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "png": "image/png",
        }
        resp = make_response(img_bytes)
        resp.headers["Content-Type"] = mime_map.get(ext, "image/png")
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    img_bytes = image_service.serve_image(output_dir, filename)
    if img_bytes is None:
        # Legacy fallback: images saved before per-viewer output folders
        # existed live directly in the shared output dir's root, not under
        # <output>/<viewer-slug>/. Only reachable if not found in the
        # viewer's own folder first, so current per-viewer images always
        # win over any stale same-named legacy file.
        img_bytes = image_service.serve_image(shared_output_dir, filename)
    if img_bytes is None:
        return jsonify({"error": "Image not found"}), 404

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    mime_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "png": "image/png",
    }
    content_type = mime_map.get(ext, "image/png")
    resp = make_response(img_bytes)
    resp.headers["Content-Type"] = content_type
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@models_api_bp.get("/images/<path:filename>/thumb")
def serve_image_thumb(filename: str):
    """Serve a resized JPEG thumbnail (max 400px) for gallery use — Sessions
    from the shared output dir, everything else from the active viewer's
    own subfolder. Mirrors serve_image()'s own branching (see there)."""
    data = _ensure_registry()
    max_size = min(800, max(100, int(request.args.get("w", 400))))

    shared_output_dir = _resolve_output_dir(data)
    if filename.startswith("session/"):
        return _serve_session_thumb(shared_output_dir, filename[len("session/"):], max_size)
    if filename.startswith("bundle/"):
        return _serve_session_thumb(shared_output_dir, filename[len("bundle/"):], max_size)
    if filename.startswith("vault/"):
        return _serve_session_thumb(shared_output_dir, filename[len("vault/"):], max_size)

    output_dir = _resolve_viewer_output_dir(data)
    if not output_dir:
        return jsonify({"error": "No active viewer session"}), 401

    if filename.startswith("input/"):
        rest = filename[len("input/"):]
        if not rest or "/" in rest or "\\" in rest or ".." in rest:
            return jsonify({"error": "Invalid filename"}), 404
        from pathlib import Path
        thumb_bytes = image_service.serve_image_thumb(str(Path(output_dir) / "input"), rest, max_size)
        if thumb_bytes is None:
            return jsonify({"error": "Image not found"}), 404
        content_type = "image/jpeg" if thumb_bytes[:2] == b"\xff\xd8" else "image/png"
        resp = make_response(thumb_bytes)
        resp.headers["Content-Type"] = content_type
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    thumb_bytes = image_service.serve_image_thumb(output_dir, filename, max_size)
    if thumb_bytes is None:
        # Legacy fallback — same reasoning as serve_image() above: pre-viewer
        # images live in the shared output dir's root, not the viewer subfolder.
        thumb_bytes = image_service.serve_image_thumb(shared_output_dir, filename, max_size)
    if thumb_bytes is None:
        return jsonify({"error": "Image not found"}), 404

    # Detect format: if Pillow returned a JPEG (starts with FF D8) use jpeg, otherwise png
    content_type = "image/jpeg" if thumb_bytes[:2] == b"\xff\xd8" else "image/png"
    resp = make_response(thumb_bytes)
    resp.headers["Content-Type"] = content_type
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


def _tray_index(data: dict, viewer_id: str) -> list[str]:
    """Return the mutable tray filename list for *viewer_id* from the
    registry dict. Keyed per-viewer so trays don't mix between users."""
    trays = data.get("imageTrayFilenames")
    if not isinstance(trays, dict):
        # Legacy shape was a flat list shared by everyone — drop it rather
        # than guess who it belonged to; it only held filenames.
        trays = {}
        data["imageTrayFilenames"] = trays
    if not isinstance(trays.get(viewer_id), list):
        trays[viewer_id] = []
    return trays[viewer_id]


@models_api_bp.put("/images/<path:filename>/meta")
def update_image_meta(filename: str):
    """Update the sidecar JSON (tags / favorite / diamond / tray) for an
    image — the active viewer's own output folder for plain generations, or
    the shared session/bundle/vault/input subfolders for anything saved
    there (see _resolve_image_path_for_filename)."""
    data = _ensure_registry()
    viewer_id = _active_viewer_id()
    if not viewer_id:
        return jsonify({"error": "No active viewer session"}), 401

    image_path = _resolve_image_path_for_filename(data, filename)
    if image_path is None:
        return jsonify({"error": "Image not found"}), 404

    payload = request.get_json(silent=True) or {}
    allowed_keys = {"tags", "favorite", "diamond", "tray"}
    current = image_service.read_sidecar(image_path)
    for k in allowed_keys:
        if k in payload:
            current[k] = payload[k]
    image_service.write_sidecar(image_path, current)

    # Keep registry tray index in sync so GET /api/images/tray is O(1)
    if "tray" in payload:
        index = _tray_index(data, viewer_id)
        if payload["tray"]:
            if filename not in index:
                index.append(filename)
        else:
            data["imageTrayFilenames"][viewer_id] = [f for f in index if f != filename]
        _save_registry(data)

    return jsonify({"ok": True, "sidecar": current})


@models_api_bp.get("/images/inputs")
def list_input_images():
    """Return the active viewer's most-recently-used flow reference images —
    every image picked into an image_picker step is already persisted under
    <viewer>/input/ (see POST /images/save-upload, subdir="input"), so this
    is a plain listing of that folder, newest first. No new write-side
    tracking needed."""
    from pathlib import Path

    data = _ensure_registry()
    output_dir = _resolve_viewer_output_dir(data)
    if not output_dir:
        return jsonify({"error": "No active viewer session", "images": []}), 401

    try:
        limit = min(100, max(1, int(request.args.get("limit", 20))))
    except (TypeError, ValueError):
        limit = 20

    entries = image_service.list_images(str(Path(output_dir) / "input"), limit=limit)
    images = [
        {
            "filename": e["filename"],
            "url": f"/api/images/input/{e['filename']}",
            "thumb_url": f"/api/images/input/{e['filename']}/thumb",
            "createdAt": e["createdAt"],
        }
        for e in entries
    ]
    return jsonify({"images": images, "total": len(images)})


@models_api_bp.get("/images/tray")
def list_tray_images():
    """Return the active viewer's tray images using the registry index —
    O(1) lookup, no file scanning."""
    data = _ensure_registry()
    output_dir = _resolve_viewer_output_dir(data)
    viewer_id = _active_viewer_id()
    if not output_dir or not viewer_id:
        return jsonify({"error": "No active viewer session", "images": []}), 401
    index = _tray_index(data, viewer_id)

    result = []
    missing = []
    for fname in index:
        # fname may be a plain viewer-relative name OR a "session/…" (etc.)
        # relative path — see _resolve_image_path_for_filename. A flat
        # `Path(output_dir) / fname` here only ever worked for the former,
        # so any Session image sent to the tray got treated as "missing"
        # and silently pruned on the very next tray fetch.
        path = _resolve_image_path_for_filename(data, fname)
        if path is None:
            missing.append(fname)
            continue
        try:
            mtime = path.stat().st_mtime
            from datetime import datetime, timezone
            created_at = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            created_at = ""
        result.append({
            "filename": fname,
            "url": f"/api/images/{fname}",
            "thumb_url": f"/api/images/{fname}/thumb",
            "createdAt": created_at,
        })

    # Prune deleted files from this viewer's index
    if missing:
        data["imageTrayFilenames"][viewer_id] = [f for f in index if f not in missing]
        _save_registry(data)

    return jsonify({"images": result, "total": len(result)})


@models_api_bp.delete("/images")
def delete_images():
    """Delete a list of image files (and their sidecars) from the active
    viewer's own output folder."""
    from pathlib import Path

    data = _ensure_registry()
    output_dir = _resolve_viewer_output_dir(data)
    if not output_dir:
        return jsonify({"error": "No active viewer session"}), 401

    payload = request.get_json(silent=True) or {}
    filenames = payload.get("filenames", [])
    if not isinstance(filenames, list):
        return jsonify({"error": "filenames must be a list"}), 400

    deleted = []
    errors = []
    out = Path(output_dir)

    for filename in filenames:
        fname = str(filename).strip()
        # path-traversal guard
        if not fname or "/" in fname or "\\" in fname or ".." in fname:
            errors.append({"filename": fname, "error": "Invalid filename"})
            continue
        image_path = out / fname
        if not image_path.is_file():
            errors.append({"filename": fname, "error": "Not found"})
            continue
        try:
            image_path.unlink()
            # Also remove sidecar if it exists
            sidecar = image_service._sidecar_path(image_path)
            if sidecar.is_file():
                sidecar.unlink()
            deleted.append(fname)
        except Exception as exc:
            errors.append({"filename": fname, "error": str(exc)})

    return jsonify({"ok": True, "deleted": deleted, "errors": errors})


@models_api_bp.post("/images/free-memory")
def free_comfyui_memory():
    """Forward a free-memory request to ComfyUI POST /free."""
    data = _ensure_registry()
    payload = request.get_json(silent=True) or {}
    # Allow caller to specify a custom ComfyUI URL (e.g. for multi-model queue free)
    override_url = str(payload.get("comfyApiUrl", "")).strip()
    raw_uri = (
        override_url or str(data.get("settings", {}).get("comfyApiUrl", "")).strip()
    )
    if not raw_uri:
        return jsonify({"error": "ComfyUI URI not configured"}), 400
    try:
        comfy_url = _safe_comfy_url(raw_uri)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    unload_models = bool(payload.get("unload_models", True))
    free_memory = bool(payload.get("free_memory", True))

    try:
        http_json(
            f"{comfy_url}/free",
            method="POST",
            payload={"unload_models": unload_models, "free_memory": free_memory},
            timeout=30,
        )
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@models_api_bp.post("/images/queue/clear")
def clear_comfyui_queue():
    """Interrupt running jobs and clear queued/history jobs in ComfyUI."""
    data = _ensure_registry()
    payload = request.get_json(silent=True) or {}
    include_history = bool(payload.get("includeHistory", True))

    targets = _collect_comfy_queue_targets(data, payload)
    if not targets:
        return jsonify({"error": "ComfyUI URI not configured"}), 400

    results = []
    any_success = False

    for comfy_url in targets:
        item = {
            "comfyApiUrl": comfy_url,
            "interrupt": {"ok": False},
            "queue": {"ok": False},
            "history": {"ok": False, "skipped": not include_history},
        }

        try:
            http_json(f"{comfy_url}/interrupt", method="POST", payload={}, timeout=20)
            item["interrupt"] = {"ok": True}
            any_success = True
        except Exception as exc:
            item["interrupt"] = {"ok": False, "error": str(exc)}

        try:
            http_json(
                f"{comfy_url}/queue", method="POST", payload={"clear": True}, timeout=20
            )
            item["queue"] = {"ok": True}
            any_success = True
        except Exception as exc:
            item["queue"] = {"ok": False, "error": str(exc)}

        if include_history:
            try:
                http_json(
                    f"{comfy_url}/history",
                    method="POST",
                    payload={"clear": True},
                    timeout=20,
                )
                item["history"] = {"ok": True}
                any_success = True
            except Exception as exc:
                item["history"] = {"ok": False, "error": str(exc)}

        results.append(item)

    status_code = 200 if any_success else 502
    return jsonify({"ok": any_success, "results": results}), status_code


@models_api_bp.get("/images/comfy/progress-stream")
def comfy_progress_stream():
    """Proxy ComfyUI WebSocket progress events to the browser as Server-Sent Events (SSE).

    The browser cannot reach ComfyUI's WebSocket directly (CORS / Origin
    rejection), so Flask connects server-side via websocket-client and
    re-emits progress/executing events as SSE that the frontend reads with
    the native EventSource API.

    Query params:
        comfyApiUrl  – full HTTP URL of the ComfyUI instance
        clientId     – clientId used when the prompt was submitted
    """
    import json as _json
    from urllib.parse import quote_plus, urlparse

    raw_url = request.args.get("comfyApiUrl", "").strip()
    client_id = request.args.get("clientId", "").strip()

    if not raw_url or not client_id:
        # SSE error — send as a data event so EventSource can read it
        def _err():
            yield (
                "data: "
                + _json.dumps(
                    {
                        "type": "error",
                        "message": "comfyApiUrl and clientId are required",
                    }
                )
                + "\n\n"
            )

        resp = Response(stream_with_context(_err()), mimetype="text/event-stream")
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    try:
        parsed = urlparse(raw_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = f"{ws_scheme}://{parsed.netloc}/ws?clientId={client_id}"
    except Exception as exc:
        _exc_msg = str(exc)  # capture before Python 3 deletes the exc variable

        def _err2():
            yield (
                "data: "
                + _json.dumps(
                    {"type": "error", "message": f"Invalid comfyApiUrl: {_exc_msg}"}
                )
                + "\n\n"
            )

        resp = Response(stream_with_context(_err2()), mimetype="text/event-stream")
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    def _sse(payload: dict) -> str:
        """Format a dict as a single SSE data line (browser flushes on \n\n)."""
        return "data: " + _json.dumps(payload) + "\n\n"

    def _fallback_payload(message: str) -> dict:
        return {
            "type": "connection_lost",
            "message": message,
            "fallbackUrl": f"/api/images/comfy/progress?comfyApiUrl={quote_plus(raw_url)}",
            "clientId": client_id,
        }

    def _stream():
        try:
            import websocket  # websocket-client
        except ImportError:
            yield _sse(_fallback_payload("websocket-client is not installed"))
            return

        ws = None
        try:
            ws = websocket.create_connection(ws_url, timeout=600)
            yield _sse({"type": "connected", "clientId": client_id})
            while True:
                raw = ws.recv()
                if not raw:
                    yield _sse(
                        _fallback_payload("ComfyUI progress stream closed unexpectedly")
                    )
                    break
                try:
                    msg = _json.loads(raw)
                except Exception:
                    continue

                msg_type = str(msg.get("type", "")).lower()
                data = msg.get("data", {}) or {}

                if msg_type == "progress":
                    value = data.get("value", 0)
                    max_val = data.get("max", 0)
                    if (
                        isinstance(value, (int, float))
                        and isinstance(max_val, (int, float))
                        and max_val > 0
                    ):
                        yield _sse({"type": "progress", "value": value, "max": max_val})

                elif msg_type == "execution_start":
                    yield _sse(
                        {
                            "type": "execution_start",
                            "promptId": str(data.get("prompt_id", "") or ""),
                        }
                    )

                elif msg_type == "execution_cached":
                    nodes = data.get("nodes", [])
                    if isinstance(nodes, list):
                        yield _sse(
                            {
                                "type": "execution_cached",
                                "nodes": [str(node) for node in nodes],
                            }
                        )

                elif msg_type == "executed":
                    node = data.get("node")
                    if node is not None:
                        yield _sse({"type": "executed", "node": str(node)})

                elif msg_type == "executing":
                    node = data.get("node")
                    if node is None:
                        # ComfyUI signals execution complete with node=null
                        yield _sse({"type": "done"})
                        break
                    else:
                        yield _sse({"type": "executing", "node": str(node)})

                elif msg_type == "execution_error":
                    err_msg = str(
                        data.get("exception_message", "ComfyUI execution error")
                    )
                    yield _sse({"type": "error", "message": err_msg})
                    break

                elif msg_type == "status":
                    exec_info = (
                        data.get("exec_info", {})
                        if isinstance(data.get("exec_info", {}), dict)
                        else {}
                    )
                    queue_remaining = exec_info.get("queue_remaining")
                    if isinstance(queue_remaining, (int, float)):
                        yield _sse(
                            {"type": "status", "queueRemaining": int(queue_remaining)}
                        )

                elif msg_type == "execution_success":
                    yield _sse(
                        {
                            "type": "execution_success",
                            "promptId": str(data.get("prompt_id", "") or ""),
                        }
                    )

        except Exception as exc:
            yield _sse(_fallback_payload(str(exc)))
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    resp = Response(stream_with_context(_stream()), mimetype="text/event-stream")
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@models_api_bp.get("/images/comfy/progress")
def comfy_progress_poll():
    """Single-shot proxy for ComfyUI's GET /progress endpoint.

    The browser cannot reach ComfyUI directly (CORS), so the frontend polls
    this Flask endpoint every ~300 ms while a generation is running.

    Query params:
        comfyApiUrl  – full HTTP URL of the ComfyUI instance
    """
    raw_url = request.args.get("comfyApiUrl", "").strip()
    if not raw_url:
        return jsonify({"error": "comfyApiUrl is required"}), 400

    try:
        comfy_url = _safe_comfy_url(raw_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        result = http_json(f"{comfy_url}/progress", timeout=4)
        payload = result if isinstance(result, dict) else {"raw": result}
        payload["ok"] = True
        return jsonify(payload)
    except Exception as exc:
        return jsonify({"ok": False, "transientError": str(exc)})


@models_api_bp.get("/images/comfy/server-state")
def comfy_server_state():
    """Capture a debug snapshot of ComfyUI server state.

    Returns merged data from:
      - GET /status
      - GET /queue
      - GET /system_stats
    """
    raw_url = request.args.get("comfyApiUrl", "").strip()
    if not raw_url:
        return jsonify({"ok": False, "error": "comfyApiUrl is required"}), 400

    try:
        comfy_url = _safe_comfy_url(raw_url)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    result: dict = {
        "ok": True,
        "comfyApiUrl": comfy_url,
        "status": None,
        "queue": None,
        "systemStats": None,
        "queueRemaining": None,
        "errors": {},
    }

    any_success = False

    try:
        status_payload = http_json(f"{comfy_url}/status", timeout=6)
        if isinstance(status_payload, dict):
            result["status"] = status_payload
            exec_info = (
                status_payload.get("exec_info", {})
                if isinstance(status_payload.get("exec_info", {}), dict)
                else {}
            )
            queue_remaining = exec_info.get("queue_remaining")
            if isinstance(queue_remaining, (int, float)):
                result["queueRemaining"] = int(queue_remaining)
            any_success = True
    except Exception as exc:
        result["errors"]["status"] = str(exc)

    try:
        queue_payload = http_json(f"{comfy_url}/queue", timeout=6)
        if isinstance(queue_payload, dict):
            result["queue"] = queue_payload
            any_success = True
    except Exception as exc:
        result["errors"]["queue"] = str(exc)

    try:
        stats_payload = http_json(f"{comfy_url}/system_stats", timeout=6)
        if isinstance(stats_payload, dict):
            result["systemStats"] = stats_payload
            any_success = True
    except Exception as exc:
        result["errors"]["system_stats"] = str(exc)

    if not any_success:
        result["ok"] = False

    # Keep 200 even on partial failures so frontend debug loops can continue.
    return jsonify(result)


@models_api_bp.post("/images/save-comfy")
def save_comfy_images():
    """Download images from ComfyUI and save them to the output directory.

    Used by the frontend after direct ComfyUI polling, which bypasses Flask's
    normal generation flow and therefore never triggers server-side saving.

    Body:
      comfyApiUrl   – ComfyUI base URL
      importId      – import record id (used to resolve output dir)
      images        – list of {filename, subfolder, type}
      filenamePrefix – prefix for saved filenames (default "comfy-output")
      metadata      – dict of PNG metadata tags (seed, positive, etc.)
    """
    body = request.get_json(force=True, silent=True) or {}
    raw_url = str(body.get("comfyApiUrl", "")).strip()
    if not raw_url:
        return jsonify({"ok": False, "error": "comfyApiUrl is required"}), 400

    try:
        comfy_url = _safe_comfy_url(raw_url)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    images = body.get("images") or []
    if not isinstance(images, list) or not images:
        return jsonify({"ok": False, "error": "images list is required"}), 400

    import_id = str(body.get("importId", "")).strip()
    filename_prefix = str(body.get("filenamePrefix", "comfy-output")).strip() or "comfy-output"
    subdir = body.get("subdir")  # optional session/<folder> for session images
    metadata = body.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    data = _ensure_registry()
    saved_filenames = []
    errors = []

    for idx, img in enumerate(images):
        if not isinstance(img, dict):
            saved_filenames.append(None)
            errors.append(f"index {idx}: not a dict")
            continue
        filename = str(img.get("filename", "")).strip()
        subfolder = str(img.get("subfolder", "")).strip()
        img_type = str(img.get("type", "output")).strip() or "output"
        if not filename:
            saved_filenames.append(None)
            errors.append(f"index {idx}: missing filename")
            continue
        try:
            from urllib.parse import urlencode
            query = urlencode({"filename": filename, "subfolder": subfolder, "type": img_type})
            image_bytes = http_bytes(f"{comfy_url}/view?{query}", timeout=300)
            saved = _try_save_image_to_output_dir(data, image_bytes, metadata, filename_prefix, idx, subdir)
            saved_filenames.append(saved)
            if saved is None:
                errors.append(f"index {idx}: output dir write failed")
        except Exception as exc:
            saved_filenames.append(None)
            errors.append(f"index {idx}: {exc}")

    saved_urls = [("/api/images/" + f) if f else None for f in saved_filenames]
    return jsonify({"ok": True, "savedFilenames": saved_filenames, "savedUrls": saved_urls, "errors": errors})


_ALLOWED_IMAGE_MIME = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "image/bmp", "image/avif", "image/tiff",
}


@models_api_bp.post("/images/fetch-url")
def fetch_image_url():
    """Download an image from an external HTTP(S) URL and return it as a base64 data URL.

    Body:
      url – the image URL to fetch
    """
    body = request.get_json(force=True, silent=True) or {}
    url = str(body.get("url", "")).strip()

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return jsonify({"error": "Invalid URL. Only http/https URLs are supported."}), 400

    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get_content_type() or ""
            mime = content_type.split(";")[0].strip().lower()
            if mime not in _ALLOWED_IMAGE_MIME:
                return jsonify({"error": f"URL does not point to an image (got {mime or 'unknown'})."}), 400
            image_bytes = resp.read(20 * 1024 * 1024)  # 20 MB cap
    except Exception as exc:
        return jsonify({"error": f"Failed to download image: {exc}"}), 502

    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    return jsonify({"dataUrl": data_url, "mime": mime})


SESSION_SUBDIR = "session"


def _resolve_session_file(output_dir: str, rel: str) -> "Path | None":
    """Resolve "<file>" or "<folder>/<file>" to a Path under
    <output_dir>/session/, falling back to the legacy <output_dir>/bundle/
    and <output_dir>/vault/ locations (sessions saved during the Vault →
    Bundle → Session renames). Path-traversal safe. None if not found."""
    from pathlib import Path
    rel = str(rel or "").strip().strip("/")
    parts = rel.split("/")
    if not rel or len(parts) > 2:
        return None
    for p in parts:
        if p in (".", "..") or "\\" in p:
            return None
    for folder in ("session", "bundle", "vault"):
        path = Path(output_dir).joinpath(folder, *parts)
        if path.is_file():
            return path
    return None


def _serve_session_path(output_dir: str, rel: str):
    """Serve a file from <output>/session/<rel> (or its legacy bundle/vault
    locations — see _resolve_session_file)."""
    path = _resolve_session_file(output_dir, rel)
    if path is None:
        return jsonify({"error": "Image not found"}), 404
    try:
        img_bytes = path.read_bytes()
    except Exception:
        return jsonify({"error": "Image not found"}), 404
    ext = path.name.rsplit(".", 1)[-1].lower() if "." in path.name else "png"
    mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "png": "image/png"}
    resp = make_response(img_bytes)
    resp.headers["Content-Type"] = mime_map.get(ext, "image/png")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


def _serve_session_thumb(output_dir: str, rel: str, max_size: int):
    """Thumbnail counterpart of _serve_session_path — same resolution, but
    resized via image_service.serve_image_thumb. Session (and Mix-generated,
    etc.) images live under <output>/session/<folder>/<file>, so the plain
    /images/<filename>/thumb route (viewer-relative, single segment only)
    always 404'd for them — the *full*-image route already had this
    session/bundle/vault branching (see serve_image() above); the thumb
    route never did, silently breaking every thumbnail (Tray modal, Session
    history strip, …) for any image living in one of those subfolders."""
    path = _resolve_session_file(output_dir, rel)
    if path is None:
        return jsonify({"error": "Image not found"}), 404
    thumb_bytes = image_service.serve_image_thumb(str(path.parent), path.name, max_size)
    if thumb_bytes is None:
        return jsonify({"error": "Image not found"}), 404
    content_type = "image/jpeg" if thumb_bytes[:2] == b"\xff\xd8" else "image/png"
    resp = make_response(thumb_bytes)
    resp.headers["Content-Type"] = content_type
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@models_api_bp.get("/images/session/<path:rel>")
def serve_session_image(rel: str):
    """Serve a Session image from <output>/session/<rel> (rel = file or folder/file)."""
    data = _ensure_registry()
    output_dir = _resolve_output_dir(data)
    return _serve_session_path_or_thumb(output_dir, rel)


def _serve_session_path_or_thumb(output_dir: str, rel: str):
    """Werkzeug matches ".../session/<folder>/<file>/thumb" to these
    /images/session|bundle|vault/<path:rel> routes (more static segments),
    never to /images/<path:filename>/thumb — so the thumbnail request arrived
    here as a file literally named "<file>/thumb" and 404'd. Hand it on."""
    if rel.endswith("/thumb"):
        max_size = min(800, max(100, int(request.args.get("w", 400))))
        return _serve_session_thumb(output_dir, rel[: -len("/thumb")], max_size)
    return _serve_session_path(output_dir, rel)


@models_api_bp.get("/images/bundle/<path:rel>")
def serve_session_image_legacy_bundle(rel: str):
    """Legacy alias for /images/session/<rel> — kept so sessions saved during
    the brief "Bundle" naming (which still reference /images/bundle/...
    URLs in their stored step data) keep loading."""
    data = _ensure_registry()
    output_dir = _resolve_output_dir(data)
    return _serve_session_path_or_thumb(output_dir, rel)


@models_api_bp.get("/images/vault/<path:rel>")
def serve_session_image_legacy(rel: str):
    """Legacy alias for /images/session/<rel> — kept so sessions saved before
    the Vault → Session rename (which still reference /images/vault/...
    URLs in their stored step data) keep loading."""
    data = _ensure_registry()
    output_dir = _resolve_output_dir(data)
    return _serve_session_path_or_thumb(output_dir, rel)


@models_api_bp.post("/images/save-upload")
def save_uploaded_image():
    """Save a user-uploaded image (base64 data URL) to <output>/session.

    Used by the Session so imported images live on the server filesystem
    (in a dedicated subfolder, kept out of the main gallery) instead of
    bloating browser localStorage.

    Body:
      dataUrl        - "data:image/...;base64,...." string
      filenamePrefix - prefix for the saved filename (default "session-import")
      metadata       - optional dict of PNG metadata tags
    Returns: { ok, savedFilename, url }
    """
    import os
    from datetime import datetime, timezone

    body = request.get_json(force=True, silent=True) or {}
    data_url = str(body.get("dataUrl", "")).strip()
    if not data_url.startswith("data:"):
        return jsonify({"ok": False, "error": "dataUrl is required"}), 400

    try:
        header, b64 = data_url.split(",", 1)
        mime = header[5:].split(";")[0].strip().lower()
        if mime and mime not in _ALLOWED_IMAGE_MIME:
            return jsonify({"ok": False, "error": f"Unsupported image type: {mime}"}), 400
        image_bytes = base64.b64decode(b64, validate=False)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Invalid data URL: {exc}"}), 400

    if not image_bytes:
        return jsonify({"ok": False, "error": "Empty image"}), 400

    filename_prefix = str(body.get("filenamePrefix", "session-import")).strip() or "session-import"
    metadata = body.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata.setdefault("source", "session-import")

    data = _ensure_registry()

    # Per-session subfolder, e.g. "session/cologne-1718900000"; defaults to
    # "session" — shared across viewers. "input" is a per-viewer subdir for
    # flow reference images, resolved under the active viewer's own folder.
    _raw_sub = body.get("subdir")
    if _raw_sub == "input":
        viewer_dir = _resolve_viewer_output_dir(data)
        if not viewer_dir:
            return jsonify({"ok": False, "error": "No active viewer session"}), 401
        subdir = "input"
        target_dir = os.path.join(viewer_dir, "input")
    else:
        output_dir = _resolve_output_dir(data)
        if not output_dir:
            return jsonify({"ok": False, "error": "Output directory not configured"}), 500
        subdir = _safe_session_subdir(_raw_sub) or SESSION_SUBDIR
        target_dir = os.path.join(output_dir, *subdir.split("/"))

    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    filename = f"{filename_prefix}-{ts}.png"
    try:
        image_service.save_image(target_dir, filename, image_bytes, metadata)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Write failed: {exc}"}), 500

    rel = subdir + "/" + filename
    return jsonify({"ok": True, "savedFilename": rel, "url": "/api/images/" + rel})
