"""
flows_api.py
============
Blueprint Flask que expone la API de flujos de Nomad Studio.

Endpoints:
  GET  /api/flows                      Lista todos los flujos (sin definición)
  GET  /api/flows/step-types           Tipos de step disponibles
  GET  /api/flows/<flow_id>            Flujo completo con definición
  POST /api/flows/packs/install        [Phase 4] Instala un pack desde ruta local
  GET  /api/flows/packs                [Phase 4] Lista packs instalados
  DELETE /api/flows/packs/<pack_id>    [Phase 4] Desinstala un pack
  POST /api/stories                    Crea un nuevo proyecto de story (JSON en disco)
  GET  /api/stories/<story_id>         Story completa (narrative_thread + scene_thread)
  GET  /api/stories/<story_id>/context Ventana acotada de contexto (últimos N + último vision)
  POST /api/stories/<story_id>/scenes  Añade una escena (1:1 a narrative_thread + scene_thread)
"""

from __future__ import annotations

import base64
import io
import json as _json
import logging
import re
import zipfile
from html import escape as _esc
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request, send_file, session

from app.routes.models_api import _ensure_registry, _save_registry
from app.routes.models_api_shared import _registry_transaction, _resolve_output_dir
from app.services import session_service, flow_engine, story_project_service

# Must match viewers_routes.SESSION_KEY — duplicated as a plain string (rather
# than importing viewers_routes here) to avoid a route-module import cycle.
_VIEWER_SESSION_KEY = "active_viewer_id"


def _active_viewer_id() -> str | None:
    return session.get(_VIEWER_SESSION_KEY) or None

_APP_DIR = Path(__file__).resolve().parents[1]
_MODEL_EXT = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".bin", ".sft", ".onnx")

logger = logging.getLogger(__name__)

flows_api_bp = Blueprint("flows_api", __name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_settings_and_packs() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = _ensure_registry()
    settings = data.get("settings", {})
    packs = data.get("installedPacks", [])
    return settings, packs


# ── Flujos ────────────────────────────────────────────────────────────────────


@flows_api_bp.get("/flows")
def list_flows():
    """
    Lista todos los flujos conocidos (built-in + packs instalados).

    Query params:
      category  — filtra por categoría (ej: create, refine, explore)
      status    — filtra por status    (ej: active, planned)
      available — "true"/"false"       — filtra por disponibilidad actual
      full      — "true" incluye la definición completa (steps/fields) de cada flow en vez
                  de solo metadatos. Pensado para consumidores que necesitan introspeccionar
                  el schema (ej. el catálogo de acciones del servidor MCP) sin hacer una
                  petición GET /flows/<id> por cada flow.
    """
    settings, packs = _get_settings_and_packs()
    flows = flow_engine.load_all_flows(settings, installed_packs=packs)

    # Filtros opcionales
    cat_filter = request.args.get("category", "").strip().lower()
    stat_filter = request.args.get("status", "").strip().lower()
    avail_str = request.args.get("available", "").strip().lower()
    full_str = request.args.get("full", "").strip().lower()

    if cat_filter:
        flows = [f for f in flows if f["category"].lower() == cat_filter]
    if stat_filter:
        flows = [f for f in flows if f["status"].lower() == stat_filter]
    if avail_str in ("true", "false"):
        want_avail = avail_str == "true"
        flows = [f for f in flows if f["available"] == want_avail]

    if full_str == "true":
        return jsonify({"flows": flows, "total": len(flows)})

    # No incluir la definición completa en el listado — solo metadatos
    summary_keys = (
        "id",
        "action",
        "label",
        "category",
        "description",
        "card_desc",
        "card_tags",
        "card_css_modifier",
        "entry_category",
        "complexity",
        "group",
        "llm_required",
        "comfyui_required",
        "status",
        "pack",
        "available",
        "unavail_reason",
    )

    return jsonify(
        {
            "flows": [{k: f[k] for k in summary_keys if k in f} for f in flows],
            "total": len(flows),
        }
    )


@flows_api_bp.get("/flows/step-types")
def get_step_types():
    """Devuelve todos los tipos de step disponibles."""
    step_types = flow_engine.load_step_types()
    return jsonify({"stepTypes": step_types})


@flows_api_bp.get("/flows/genres")
def get_genres():
    """
    Devuelve los géneros narrativos disponibles (instructions/genres/*.json).

    Usado por create.story / create.scenes para las cards de género — cada
    género trae su propio flair/level sugeridos y un context_hint que se
    inyecta en el system prompt del LLM al generar la escena.
    """
    genres = flow_engine.load_genres()
    return jsonify({"genres": genres, "total": len(genres)})


@flows_api_bp.get("/flows/<path:flow_id>")
def get_flow(flow_id: str):
    """
    Devuelve el flujo completo (metadatos + definición JSON).

    El campo `definition` es el contenido completo del .json del flujo.
    Es None si el flujo está en el index pero el archivo aún no existe.
    """
    # Normaliza el flow_id: "create/simple" → "create.simple"
    flow_id = flow_id.replace("/", ".").strip(".")
    settings, packs = _get_settings_and_packs()
    # Packages carry their own text: serving the flow already translated keeps
    # the translation out of the 36 step renderers (PACKAGE_FORMAT.md §7.2).
    lang = str(request.args.get("lang") or "en")[:5]
    flow = flow_engine.get_flow_by_id(flow_id, settings, installed_packs=packs,
                                      lang=lang if lang in ("es", "zh", "ko") else None)

    if not flow:
        return jsonify({"error": f"Flow '{flow_id}' not found"}), 404

    if flow["definition"] is None:
        return jsonify(
            {
                "error": f"Flow '{flow_id}' is registered but its definition file is missing",
                "status": flow["status"],
            }
        ), 404

    return jsonify({"flow": flow})


# ── Session server persistence ─────────────────────────────────────────────
# Sessions used to live only in browser localStorage. These endpoints back them
# with a real server-side store (data/sessions.json) so a session created on one
# browser/device shows up for the same viewer everywhere. Each session carries
# either scope "all" (visible to everyone) or "user" (visible only to the
# viewer who made it).
#
# Local vars below are named `sess` (not `session`) to avoid shadowing the
# Flask `session` cookie object imported at the top of this module.


@flows_api_bp.get("/sessions")
def list_sessions():
    viewer_id = _active_viewer_id()
    return jsonify({"sessions": session_service.list_sessions(viewer_id)})


@flows_api_bp.post("/sessions")
def create_session():
    viewer_id = _active_viewer_id()
    body = request.get_json(silent=True) or {}
    scope = str(body.get("scope") or session_service.SCOPE_USER)
    sess = session_service.create_session(body, scope, viewer_id)
    return jsonify({"ok": True, "session": sess})


@flows_api_bp.get("/sessions/<session_id>")
def get_session(session_id: str):
    viewer_id = _active_viewer_id()
    sess = session_service.get_session(session_id, viewer_id)
    if sess is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "session": sess})


@flows_api_bp.put("/sessions/<session_id>")
def update_session(session_id: str):
    viewer_id = _active_viewer_id()
    patch = request.get_json(silent=True) or {}
    sess = session_service.upsert_session(session_id, patch, viewer_id)
    if sess is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "session": sess})


@flows_api_bp.delete("/sessions/<session_id>")
def delete_session(session_id: str):
    viewer_id = _active_viewer_id()
    ok = session_service.delete_session(session_id, viewer_id)
    return jsonify({"ok": ok}), (200 if ok else 404)


@flows_api_bp.post("/sessions/<session_id>/duplicate")
def duplicate_session(session_id: str):
    # Always scoped to the current viewer — no "all vs user" prompt for copies.
    viewer_id = _active_viewer_id()
    sess = session_service.duplicate_session(session_id, viewer_id)
    if sess is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "session": sess})


@flows_api_bp.post("/sessions/import")
def import_session():
    viewer_id = _active_viewer_id()
    body = request.get_json(silent=True) or {}
    scope = str(body.get("scope") or session_service.SCOPE_USER)
    payload = body.get("session") or {}
    sess = session_service.import_session(payload, scope, viewer_id)
    return jsonify({"ok": True, "session": sess})


# ── Session export (HTML + MD + images, zipped) ────────────────────────────────


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:50] or "session"


def _extract_models_from_workflow(wf: dict[str, Any]) -> list[str]:
    """Collect model filenames referenced by loader nodes in a ComfyUI graph."""
    found: list[str] = []
    for node in wf.values():
        if not isinstance(node, dict):
            continue
        ins = node.get("inputs", {})
        if not isinstance(ins, dict):
            continue
        for v in ins.values():
            if isinstance(v, str) and v.strip().lower().endswith(_MODEL_EXT):
                found.append(v.strip())
    seen: set[str] = set()
    out: list[str] = []
    for m in found:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _workflow_file_for_flow(flow_id: str, settings: dict[str, Any], packs: list[dict[str, Any]]) -> str:
    """Resolve the workflow .json path (relative to app/) used by a flow."""
    try:
        flow = flow_engine.get_flow_by_id(flow_id, settings, installed_packs=packs)
        definition = (flow or {}).get("definition") or {}
        for step in definition.get("steps", []):
            wf = step.get("workflow_file")
            if wf:
                return str(wf)
            im = step.get("input_map") or {}
            if isinstance(im.get("workflowFile"), str) and im["workflowFile"].endswith(".json"):
                return im["workflowFile"]
    except Exception:
        logger.exception("export: failed resolving workflow for %s", flow_id)
    return ""


def _image_bytes_from_url(output_dir: Path, url: str) -> tuple[bytes, str] | None:
    """Return (bytes, ext) for a step image URL (server path or data: URI)."""
    if not url:
        return None
    try:
        if url.startswith("data:image/"):
            header, b64 = url.split(",", 1)
            ext = "png"
            m = re.search(r"data:image/([a-zA-Z0-9]+)", header)
            if m:
                ext = m.group(1).lower().replace("jpeg", "jpg")
            return base64.b64decode(b64), ext
        rel = url
        if "/api/images/" in rel:
            rel = rel.split("/api/images/", 1)[1]
        rel = rel.split("?", 1)[0].lstrip("/")
        if not rel:
            return None
        candidate = (output_dir / rel).resolve()
        # path-traversal guard
        if output_dir.resolve() not in candidate.parents and candidate != output_dir.resolve():
            return None
        if candidate.is_file():
            ext = candidate.suffix.lstrip(".").lower() or "png"
            return candidate.read_bytes(), ext
    except Exception:
        logger.exception("export: failed reading image %s", url)
    return None


@flows_api_bp.post("/session/export")
def export_session_docs():
    """Build a self-contained ZIP (session.html + session.md + images/) for a session.

    Request body = the session object (from the client Session store).
    """
    payload = request.get_json(silent=True) or {}
    steps = [s for s in (payload.get("steps") or []) if isinstance(s, dict)]
    name = str(payload.get("name") or "Untitled Session")
    created = str(payload.get("createdAt") or "")

    settings, packs = _get_settings_and_packs()
    data = _ensure_registry()
    output_dir = Path(_resolve_output_dir(data))

    # ── Resolve images + models per step ──────────────────────────────────────
    zip_buf = io.BytesIO()
    models_map: dict[str, set[str]] = {}     # model filename → set of flow labels
    wf_cache: dict[str, list[str]] = {}      # flow_id → models
    step_views: list[dict[str, Any]] = []    # for html/md rendering

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, step in enumerate(steps, start=1):
            label = str(step.get("flowLabel") or "Step")
            category = str(step.get("flowCategory") or "")
            action = str(step.get("flowAction") or "")
            params = step.get("params") if isinstance(step.get("params"), dict) else {}
            imgs = step.get("images") if isinstance(step.get("images"), list) else []
            if not imgs and step.get("imageUrl"):
                imgs = [step.get("imageUrl")]

            # Models for this flow
            if action and category not in ("import", ""):
                flow_id = category + "." + action
                if flow_id not in wf_cache:
                    models: list[str] = []
                    wf_rel = _workflow_file_for_flow(flow_id, settings, packs)
                    if wf_rel:
                        wf_path = (_APP_DIR / wf_rel)
                        if wf_path.is_file():
                            try:
                                models = _extract_models_from_workflow(_json.loads(wf_path.read_text(encoding="utf-8")))
                            except Exception:
                                logger.exception("export: bad workflow json %s", wf_rel)
                    wf_cache[flow_id] = models
                for m in wf_cache[flow_id]:
                    models_map.setdefault(m, set()).add(label)

            # Images → zip
            saved: list[str] = []
            for i, url in enumerate(imgs, start=1):
                got = _image_bytes_from_url(output_dir, str(url))
                if not got:
                    continue
                raw, ext = got
                arcname = "images/step%02d_%d.%s" % (idx, i, ext)
                zf.writestr(arcname, raw)
                saved.append(arcname)

            step_views.append({
                "idx": idx,
                "label": label,
                "category": category,
                "prompt": str(params.get("prompt") or params.get("positive") or params.get("promptText") or ""),
                "seed": params.get("seed"),
                "advanced": params.get("advancedValues") if isinstance(params.get("advancedValues"), dict) else {},
                "images": saved,
            })

        # ── Render markdown + html ────────────────────────────────────────────
        md = _render_session_md(name, created, step_views, models_map)
        htmldoc = _render_session_html(name, created, step_views, models_map)
        zf.writestr("session.md", md)
        zf.writestr("session.html", htmldoc)

        # Machine-readable copy of the raw session object (name/createdAt/steps,
        # same shape the client's Session store keeps) — this is what Import
        # actually reads back. session.md/session.html above are just the
        # human-readable report; without this, an exported .zip has no data
        # in it an importer could reconstruct a session from.
        zf.writestr("session.json", _json.dumps(payload, ensure_ascii=False, indent=2))

    zip_buf.seek(0)
    return send_file(
        zip_buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=_slugify(name) + ".zip",
    )


@flows_api_bp.post("/flow/export-images")
def export_flow_images():
    """Build a ZIP containing only the generated images for a flow."""
    payload = request.get_json(silent=True) or {}
    images = payload.get("images") if isinstance(payload.get("images"), list) else []
    name = str(payload.get("name") or "flow-images")
    data = _ensure_registry()
    output_dir = Path(_resolve_output_dir(data))
    zip_buf = io.BytesIO()
    saved = 0

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, url in enumerate(images, start=1):
            got = _image_bytes_from_url(output_dir, str(url))
            if not got:
                continue
            raw, ext = got
            zf.writestr("images/image_%02d.%s" % (idx, ext), raw)
            saved += 1

    if not saved:
        return jsonify({"error": "No exportable images"}), 400
    zip_buf.seek(0)
    return send_file(
        zip_buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=_slugify(name) + "-images.zip",
    )


@flows_api_bp.post("/session/import-zip")
def import_session_zip():
    """Unzip an uploaded Session export and return its session.json contents.

    The browser can't unzip client-side (no bundled zip library), so the
    upload comes here instead: extract session.json, hand the parsed object
    back to the frontend, which then continues through the same import-scope
    flow it already uses for plain .json imports.
    """
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "No file uploaded."}), 400

    try:
        raw = upload.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            if "session.json" not in zf.namelist():
                return jsonify({
                    "error": "This .zip has no session.json — it looks like it was exported "
                             "before Import support existed. Re-export the session and try again.",
                }), 422
            data = _json.loads(zf.read("session.json").decode("utf-8"))
    except zipfile.BadZipFile:
        return jsonify({"error": "That file isn't a valid .zip archive."}), 400
    except Exception:
        logger.exception("import-zip: failed reading session.json")
        return jsonify({"error": "Could not read session.json inside the .zip."}), 400

    if not isinstance(data, dict):
        return jsonify({"error": "session.json inside the .zip isn't a valid session object."}), 422

    return jsonify(data)


def _fmt_models_lines(models_map: dict[str, set[str]]) -> list[tuple[str, str]]:
    return [(m, ", ".join(sorted(models_map[m]))) for m in sorted(models_map)]


def _render_session_md(name, created, steps, models_map) -> str:
    out = ["# " + name, ""]
    if created:
        out.append("_Created: %s_" % created)
        out.append("")
    out.append("## Models required")
    out.append("")
    rows = _fmt_models_lines(models_map)
    if rows:
        out.append("| Model file | Used by |")
        out.append("| --- | --- |")
        for m, used in rows:
            out.append("| `%s` | %s |" % (m, used))
    else:
        out.append("_No model files detected._")
    out.append("")
    out.append("## Steps")
    out.append("")
    for s in steps:
        out.append("### %d. %s%s" % (s["idx"], s["label"], (" · " + s["category"]) if s["category"] else ""))
        out.append("")
        if s["prompt"]:
            out.append("**Prompt:** " + s["prompt"])
            out.append("")
        meta_bits = []
        if s["seed"] not in (None, ""):
            meta_bits.append("seed `%s`" % s["seed"])
        for k, v in (s["advanced"] or {}).items():
            meta_bits.append("`%s` = `%s`" % (k, v))
        if meta_bits:
            out.append("**Params:** " + ", ".join(meta_bits))
            out.append("")
        for img in s["images"]:
            out.append("![%s](%s)" % (s["label"], img))
        out.append("")
    return "\n".join(out)


def _render_session_html(name, created, steps, models_map) -> str:
    rows = _fmt_models_lines(models_map)
    model_rows = "".join(
        "<tr><td><code>%s</code></td><td>%s</td></tr>" % (_esc(m), _esc(used)) for m, used in rows
    ) or '<tr><td colspan="2" class="muted">No model files detected.</td></tr>'

    step_html = []
    for s in steps:
        imgs = "".join('<a href="%s" target="_blank"><img src="%s" loading="lazy"></a>' % (_esc(i), _esc(i)) for i in s["images"])
        bits = []
        if s["seed"] not in (None, ""):
            bits.append("seed <code>%s</code>" % _esc(str(s["seed"])))
        for k, v in (s["advanced"] or {}).items():
            bits.append("<code>%s</code>=<code>%s</code>" % (_esc(str(k)), _esc(str(v))))
        prompt_html = ('<p class="prompt">%s</p>' % _esc(s["prompt"])) if s["prompt"] else ""
        params_html = ('<p class="params">%s</p>' % " · ".join(bits)) if bits else ""
        cat = (' <span class="tag">%s</span>' % _esc(s["category"])) if s["category"] else ""
        step_html.append(
            '<section class="step"><h3><span class="num">%d</span> %s%s</h3>%s%s<div class="grid">%s</div></section>'
            % (s["idx"], _esc(s["label"]), cat, prompt_html, params_html, imgs)
        )

    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title>
<style>
:root{--bg:#0f1420;--panel:#1a2130;--line:rgba(255,255,255,.08);--text:#e8e8e8;--muted:#9aa4b2;--accent:#f0c060}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:1.8rem;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 28px}
h2{font-size:1rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:32px 0 12px}
table{width:100%%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:10px 14px;border-bottom:1px solid var(--line);font-size:.9rem;vertical-align:top}
th{color:var(--muted);font-weight:600}tr:last-child td{border-bottom:none}
code{background:rgba(240,192,96,.10);color:var(--accent);padding:.1em .4em;border-radius:5px;font-size:.85em}
.muted{color:var(--muted)}
.step{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:14px 0}
.step h3{margin:0 0 8px;font-size:1.05rem;display:flex;align-items:center;gap:10px}
.num{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%%;background:rgba(240,192,96,.15);color:var(--accent);font-size:.8rem;font-weight:700}
.tag{font-size:.65rem;text-transform:uppercase;letter-spacing:.05em;color:var(--accent);background:rgba(240,192,96,.10);border:1px solid rgba(240,192,96,.2);padding:.1em .5em;border-radius:999px}
.prompt{color:var(--text);background:rgba(255,255,255,.03);border-left:2px solid var(--accent);padding:8px 12px;border-radius:0 6px 6px 0;margin:6px 0}
.params{color:var(--muted);font-size:.85rem;margin:6px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:12px}
.grid img{width:100%%;border-radius:8px;border:1px solid var(--line);display:block}
.grid a{display:block}
</style></head><body><div class="wrap">
<h1>%s</h1><p class="sub">%s</p>
<h2>Models required</h2>
<table><thead><tr><th>Model file</th><th>Used by</th></tr></thead><tbody>%s</tbody></table>
<h2>Steps</h2>
%s
</div></body></html>""" % (
        _esc(name),
        _esc(name),
        _esc(("Created " + created) if created else ""),
        model_rows,
        "".join(step_html),
    )


# ── Packs (Phase 4 — stubs) ───────────────────────────────────────────────────


@flows_api_bp.get("/flows/packs")
def list_packs():
    """Lista los packs de flujos instalados."""
    data = _ensure_registry()
    packs = data.get("installedPacks", [])
    return jsonify({"packs": packs, "total": len(packs)})


@flows_api_bp.post("/flows/packs/install")
def install_pack():
    """
    Instala un pack desde una ruta de directorio local.

    Body JSON:
      packDir  — ruta absoluta al directorio del pack
      packId   — (opcional) identificador; si se omite se usa el nombre del dir
    """
    payload = request.get_json(silent=True) or {}
    pack_dir = str(payload.get("packDir", "")).strip()
    if not pack_dir:
        return jsonify({"error": "packDir is required"}), 400

    from pathlib import Path

    pack_path = Path(pack_dir)
    if not pack_path.is_dir():
        return jsonify({"error": f"Directory not found: {pack_dir}"}), 400

    # Leer manifest del pack
    manifest_path = pack_path / "manifest.json"
    manifest: dict = {}
    try:
        import json as _json

        manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # Manifest opcional — derivamos packId del nombre del directorio
        pass
    except Exception as exc:
        return jsonify({"error": f"Invalid manifest.json: {exc}"}), 400

    pack_id = str(
        payload.get("packId", "") or manifest.get("packId", "") or pack_path.name
    ).strip()
    if not pack_id:
        return jsonify({"error": "Could not determine packId"}), 400

    # Validar que los flows del pack parsean correctamente
    flow_errors: dict[str, list[str]] = {}
    for flow_file in sorted(pack_path.glob("flows/**/*.json")):
        try:
            import json as _json

            definition = _json.loads(flow_file.read_text(encoding="utf-8"))
        except Exception as exc:
            flow_errors[flow_file.name] = [f"Parse error: {exc}"]
            continue
        errs = flow_engine.validate_flow_definition(definition)
        if errs:
            flow_errors[flow_file.name] = errs

    if flow_errors:
        return jsonify(
            {"error": "Pack contains invalid flow definitions", "details": flow_errors}
        ), 400

    # Registrar pack
    with _registry_transaction() as data:
        packs = data.setdefault("installedPacks", [])

        # Reemplaza si ya estaba instalado
        packs = [p for p in packs if p.get("packId") != pack_id]
        packs.append(
            {
                "packId": pack_id,
                "packDir": str(pack_path.resolve()),
                "name": str(manifest.get("name", pack_id)),
                "version": str(manifest.get("version", "0.0")),
                "description": str(manifest.get("description", "")),
                "installDate": __import__("datetime")
                .datetime.now(__import__("datetime").timezone.utc)
                .isoformat(),
            }
        )
        data["installedPacks"] = packs

    return jsonify({"ok": True, "packId": pack_id, "packsTotal": len(packs)})


@flows_api_bp.delete("/flows/packs/<pack_id>")
def uninstall_pack(pack_id: str):
    """Desinstala un pack por su packId."""
    pack_id = pack_id.strip()
    if not pack_id:
        return jsonify({"error": "packId is required"}), 400

    with _registry_transaction() as data:
        packs = data.get("installedPacks", [])
        before = len(packs)
        packs = [p for p in packs if p.get("packId") != pack_id]

        if len(packs) == before:
            return jsonify({"error": f"Pack '{pack_id}' not installed"}), 404

        data["installedPacks"] = packs
    return jsonify({"ok": True, "packId": pack_id})


# ── Story projects (narrative continuity) ───────────────────────────────────
# Per-story JSON on disk, separate from the flat localStorage session history
# (History panel / Album) — a richer record kept per Create Story session so
# each scene's narrative beat and the vision description used to write it can
# be looked back on, without re-sending the whole accumulated story to the
# LLM every turn (see context_window). See story_project_service.py.


@flows_api_bp.post("/stories")
def create_story_project():
    """Starts a new story project JSON. Body: { title? }."""
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "") or "").strip()
    story = story_project_service.create_story(title)
    return jsonify(story)


@flows_api_bp.get("/stories/<story_id>")
def get_story_project(story_id: str):
    story = story_project_service.load_story(story_id)
    if story is None:
        return jsonify({"error": f"Story '{story_id}' not found"}), 404
    return jsonify(story)


@flows_api_bp.get("/stories/<story_id>/context")
def get_story_project_context(story_id: str):
    """Bounded context window for the next LLM turn — last N narrative
    summaries + the most recent scene's vision_summary. Never the full story.
    """
    try:
        n = int(request.args.get("n", 3))
    except (TypeError, ValueError):
        n = 3
    return jsonify(story_project_service.context_window(story_id, n))


@flows_api_bp.post("/stories/<story_id>/scenes")
def append_story_project_scene(story_id: str):
    """Appends one scene (1:1 entry in narrative_thread + scene_thread).

    Body: { narrativeSummary?, promptUsed?, style?, visionSummary?, imagePath? }
    """
    payload = request.get_json(silent=True) or {}
    story = story_project_service.append_scene(
        story_id,
        narrative_summary=str(payload.get("narrativeSummary", "") or ""),
        prompt_used=str(payload.get("promptUsed", "") or ""),
        style=str(payload.get("style", "") or ""),
        vision_summary=str(payload.get("visionSummary", "") or ""),
        image_path=str(payload.get("imagePath", "") or ""),
    )
    return jsonify(story)
