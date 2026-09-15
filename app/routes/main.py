from __future__ import annotations

import json
import re
from pathlib import Path

from flask import Blueprint, abort, make_response, redirect, render_template, session, url_for

from .viewers_routes import SESSION_KEY as _VIEWER_SESSION_KEY
from ..services import viewer_service

main_bp = Blueprint("main", __name__)


def _active_viewer_context() -> dict:
    """Avatar/name of the current viewer, for the header logo-button that
    doubles as "switch viewer" — falls back to the raccoon logo when no
    viewer is active (e.g. session expired mid-page)."""
    viewer_id = session.get(_VIEWER_SESSION_KEY)
    viewer = viewer_service.get_viewer(viewer_id) if viewer_id else None
    if viewer:
        return {
            "viewer_avatar_url": url_for("static", filename="images/avatars/" + viewer["avatar"]),
            "viewer_name": viewer["name"],
            "viewer_is_vanish": bool(viewer.get("is_vanish", False)),
        }
    return {
        "viewer_avatar_url": url_for("static", filename="images/logo/raccoon.svg"),
        "viewer_name": None,
        "viewer_is_vanish": False,
    }

_INSTRUCTIONS_DIR = Path(__file__).parent.parent / "instructions"
_WORKFLOWS_DIR = Path(__file__).parent.parent / "workflows"


def _load_package_flows(category: str, route_prefix: str) -> list[dict]:
    """Cards for flows contributed by installed packages (packages/index.json,
    written by the importer — docs/PACKAGE_FORMAT.md §12). Texts in the
    package's default language; the hub's data-i18n-literal still translates
    labels the app already knows."""
    from ..services import package_service
    from . import packages_routes

    app_dir = packages_routes.APP_DIR
    index = package_service.read_index(app_dir)
    base = package_service.packages_dir(app_dir)
    flows = []
    for flow_id, info in index.get("flows", {}).items():
        if info.get("category") != category:
            continue
        pkg = index.get("packages", {}).get(info.get("package"), {})
        try:
            definition = json.loads((base / info["file"]).read_text(encoding="utf-8"))
        except (OSError, KeyError, json.JSONDecodeError):
            continue
        card = package_service.card_fields(definition, pkg.get("default_lang") or "en", pkg.get("default_lang") or "en")
        action = flow_id.split(".", 1)[1]
        flows.append({
            "id": flow_id,
            "action": action,
            "route": f"{route_prefix}/{action.replace('_', '-')}",
            "status": info.get("status", "active"),
            "llm_required": bool(definition.get("llm_required", False)),
            "label": card["label"],
            "card_desc": card["desc"],
            "card_tags": card["tags"],
            "card_css_modifier": str(definition.get("card_css_modifier", "")),
            "entry_category": str(definition.get("entry_category", "")),
            "entry_model": str(definition.get("entry_model", "")),
            "complexity": definition.get("complexity"),
            "group": info.get("group") or "core",
            "preset_meta": definition.get("preset_meta"),
            "package": info.get("package"),
        })
    return flows


def _load_category_flows(category: str, route_prefix: str) -> list[dict]:
    index = json.loads((_INSTRUCTIONS_DIR / "index.json").read_text(encoding="utf-8"))
    flows = []
    for entry in index["flows"]:
        if entry.get("category") != category:
            continue
        action = entry["id"].split(".", 1)[1]
        url_slug = action.replace("_", "-")
        card: dict = {
            "id": entry["id"],
            "action": action,
            "route": f"{route_prefix}/{url_slug}",
            "status": entry.get("status", "active"),
            "llm_required": entry.get("llm_required", False),
            "label": entry.get("label", action),
            "card_desc": entry.get("card_desc", ""),
            "card_tags": entry.get("card_tags", []),
            "card_css_modifier": entry.get("card_css_modifier", ""),
            "entry_category": entry.get("entry_category", ""),
            "entry_model": entry.get("entry_model", ""),
            # Complexity indicator (1-3, see nomad_studio.css .cs-card-complexity).
            # None when unclassified — a flow with no rating never falls back to
            # level 1, it just shows no indicator at all.
            "complexity": entry.get("complexity"),
            # Expansion-pack grouping (Refine only, for now — see
            # _group_flows_by_pack). "core" = built-in, otherwise the pack's
            # slug once purchased packs land in installedPacks.
            "group": entry.get("group", "core"),
        }
        flow_file = _INSTRUCTIONS_DIR / entry["file"]
        if flow_file.exists():
            try:
                flow_data = json.loads(flow_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                flow_data = {}
            card["label"] = flow_data.get("label", card["label"])
            card["card_desc"] = flow_data.get("card_desc", card["card_desc"])
            card["card_tags"] = flow_data.get("card_tags", card["card_tags"])
            card["card_css_modifier"] = flow_data.get("card_css_modifier", card["card_css_modifier"])
            card["entry_category"] = flow_data.get("entry_category", card["entry_category"])
            card["entry_model"] = flow_data.get("entry_model", card["entry_model"])
            card["complexity"] = flow_data.get("complexity", card["complexity"])
            card["group"] = flow_data.get("group", card["group"])
            card["preset_meta"] = flow_data.get("preset_meta")
        flows.append(card)
    seen = {f["id"] for f in flows}
    flows += [f for f in _load_package_flows(category, route_prefix) if f["id"] not in seen]
    return flows


def _load_create_flows() -> list[dict]:
    return _load_category_flows("create", "/nomad-studio/create")


@main_bp.get("/")
def index():
    # First run: the setup wizard comes before the profile picker, because it
    # is where the first profile is created (docs/SETUP_WIZARD.md §1.1).
    from .setup_routes import setup_completed

    if not setup_completed():
        return redirect(url_for("setup.setup_page"))
    if not session.get(_VIEWER_SESSION_KEY):
        return redirect(url_for("viewers.who_screen"))
    return redirect(url_for("main.nomad_studio_page"))


@main_bp.get("/album")
def album():
    # The NEW Album: session/flow-based gallery (Netflix-style hover cards),
    # reading the same uncapped history list as the "Generations" recent
    # panel on the main hub. See flow-state.js / create/index.js
    # saveSessionSnapshot() for the write side.
    return render_template("pages/album.html", active_page="album")


@main_bp.get("/agents/<slug>/album")
def agent_album(slug: str):
    """Read-only Album for one MCP agent viewer (Claude Desktop, Bionic...),
    reached from the agents row on /who. Uses the agent's own images, served
    via the existing ``?viewer=<slug>`` fallback (see _active_viewer_id() in
    models_api_shared.py) — no session switch, browsing stays anonymous."""
    agent = viewer_service.get_agent_viewer_by_slug(slug)
    if agent is None:
        abort(404)
    # get_agent_viewer_by_slug() returns the raw viewer record (no "slug"
    # key — that's only added by list_agent_viewers()'s public view), so
    # compute it here for the template/JS to key their API calls on.
    agent_view = {**agent, "slug": viewer_service.slugify_name(agent["name"])}
    return render_template("pages/agent_album.html", active_page="agent-album", agent=agent_view)


def _load_flows_from_workflows(category: str) -> list[dict]:
    """Scan workflows/**/*.json for flow_data nodes matching `category`."""
    flows: list[dict] = []
    existing_ids: set[str] = set()
    for wf_path in sorted(_WORKFLOWS_DIR.glob("**/*.json")):
        try:
            data = json.loads(wf_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        meta = next(
            (
                json.loads(node["inputs"]["value"])
                for node in data.values()
                if isinstance(node, dict)
                and node.get("_meta", {}).get("title") == "flow_data"
                and node.get("inputs", {}).get("value")
            ),
            None,
        )
        if not isinstance(meta, dict):
            continue
        flow_id = str(meta.get("id", "")).strip()
        if not flow_id or flow_id in existing_ids:
            continue
        flow_category = str(meta.get("category", "refine")).strip()
        if flow_category != category:
            continue
        action = flow_id.split(".", 1)[1] if "." in flow_id else flow_id
        url_slug = action.replace("_", "-")
        flows.append({
            "id": flow_id,
            "action": action,
            "route": f"/nomad-studio/{category}/{url_slug}",
            "status": "active",
            "llm_required": bool(meta.get("llm_required", False)),
            "label": str(meta.get("label", flow_id)),
            "card_desc": str(meta.get("card_desc", "")),
            "card_tags": list(meta.get("card_tags", [])),
            "card_css_modifier": str(meta.get("card_css_modifier", "")),
            "entry_category": str(meta.get("entry_category", "")),
            "entry_model": str(meta.get("entry_model", "")),
            "group": str(meta.get("group", "core")),
        })
        existing_ids.add(flow_id)
    return flows


# Display label for a flow group/pack — "core" (built-in, always first) plus
# whatever purchased expansion packs register (e.g. "photo-editing",
# "filters"). Packs not listed here just get their slug title-cased, so a
# new pack works without a code change here.
_GROUP_LABELS: dict[str, str] = {
    "core": "Core",
    "photo-editing": "Photo Editing",
    "portrait-fix": "Portrait Fix",
    "creator-pack": "Creator Pack",
    "look-book": "Look Book",
    "presets": "Presets",
    "layout": "Layout",
    "upscale": "Upscale",
}


def _group_label(group_id: str) -> str:
    return _GROUP_LABELS.get(group_id, group_id.replace("-", " ").replace("_", " ").title())


def _group_flows_by_pack(flows: list[dict]) -> list[dict]:
    """Buckets a flat flow list into [{id, label, flows}, ...] by their
    "group" field — "core" always first, everything else alphabetically by
    label. Preserves each group's existing internal ordering."""
    buckets: dict[str, list[dict]] = {}
    for flow in flows:
        buckets.setdefault(flow.get("group") or "core", []).append(flow)

    def _sort_key(group_id: str) -> tuple[int, str]:
        return (0 if group_id == "core" else 1, _group_label(group_id).lower())

    return [
        {"id": gid, "label": _group_label(gid), "flows": buckets[gid]}
        for gid in sorted(buckets.keys(), key=_sort_key)
    ]


def _load_refine_flows() -> list[dict]:
    flows = _load_category_flows("refine", "/nomad-studio/refine")
    existing_ids = {f["id"] for f in flows}
    for f in _load_flows_from_workflows("refine"):
        if f["id"] not in existing_ids:
            flows.append(f)
            existing_ids.add(f["id"])
    return flows


def _load_mix_flows() -> list[dict]:
    flows = _load_category_flows("mix", "/nomad-studio/mix")
    existing_ids = {f["id"] for f in flows}
    for f in _load_flows_from_workflows("mix"):
        if f["id"] not in existing_ids:
            flows.append(f)
            existing_ids.add(f["id"])
    # Canvas Composer is a dedicated page (multi-layer freeform editor), not a
    # step-sequential flow — it has no instructions/flows/mix/*.json, so it's
    # appended here by hand to appear as a card in the Mix grid.
    if "mix.canvas_composer" not in existing_ids:
        flows.append({
            "id": "mix.canvas_composer",
            "action": "canvas_composer",
            "route": "/nomad-studio/mix/canvas-composer",
            "status": "active",
            "llm_required": False,
            "label": "Canvas Composer",
            "card_desc": "Collage multiple images on a free canvas — position, scale, round corners, and flatten to a single PNG.",
            "card_tags": ["Compose", "Layers", "Local"],
            "card_css_modifier": "canvas-composer",
            "entry_category": "Compose",
            "entry_model": "Local",
        })
    return flows


_NOMAD_STUDIO_VIEW_LABELS = {"create": "Create", "refine": "Refine", "mix": "Mix", "session": "Session"}


def _render_nomad_studio(initial_view: str | None = None):
    create_flows = _load_create_flows()
    refine_flows = _load_refine_flows()
    mix_flows = _load_mix_flows()
    html = render_template(
        "pages/nomad_studio.html",
        active_page="nomad-studio",
        flows=create_flows,
        create_flow_groups=_group_flows_by_pack(create_flows),
        refine_flows=refine_flows,
        refine_flow_groups=_group_flows_by_pack(refine_flows),
        # Template packs (Cinematic, ...) — imported prompt templates, so they
        # are a Create group of their own, one card per pack with its first
        # image as the cover.
        template_packs=_load_pack_summaries(),
        mix_flows=mix_flows,
        mix_flow_groups=_group_flows_by_pack(mix_flows),
        initial_view=initial_view,
        initial_view_label=_NOMAD_STUDIO_VIEW_LABELS.get(initial_view or ""),
        **_active_viewer_context(),
    )
    # The cards come from installed packages: never serve a cached hub, or
    # coming back after installing one still shows the old, empty sections.
    response = make_response(html)
    response.headers["Cache-Control"] = "no-store"
    return response


@main_bp.get("/nomad-studio")
def nomad_studio_page():
    return _render_nomad_studio()


@main_bp.get("/mobile")
def mobile_page():
    return render_template("pages/mobile.html", active_page="mobile")


@main_bp.get("/nomad-studio/create")
def nomad_studio_create_page():
    return _render_nomad_studio("create")


@main_bp.get("/nomad-studio/refine")
def nomad_studio_refine_page():
    return _render_nomad_studio("refine")


@main_bp.get("/nomad-studio/mix")
def nomad_studio_mix_page():
    return _render_nomad_studio("mix")


@main_bp.get("/nomad-studio/session")
def nomad_studio_session_page():
    return _render_nomad_studio("session")


@main_bp.get("/nomad-studio/session/<session_id>")
def nomad_studio_session_workspace_page(session_id):
    """A single open Session — its own page/URL (like Create's flow pages),
    not a sub-view inside the /nomad-studio SPA. Left panel = session name +
    actions, main area = History. session_id is resolved client-side against
    the shared NomadSession store (server-synced), same as the entry list."""
    refine_flows = _load_refine_flows()
    return render_template(
        "pages/ns_session_workspace.html",
        active_page="nomad-studio",
        session_id=session_id,
        flows=_load_create_flows(),
        refine_flows=refine_flows,
        mix_flows=_load_mix_flows(),
        **_active_viewer_context(),
    )


@main_bp.get("/build")
def build_page():
    return render_template("pages/library.html", active_page="build")


@main_bp.get("/library")
def library_page_redirect():
    # Renamed to /build — kept as a redirect so old links/bookmarks still land somewhere.
    return redirect(url_for("main.build_page"))


def _render_flow_page(**kwargs):
    """render_template for pages/ns_create_flow.html, always carrying the
    active-viewer context so the topbar can show who's in session."""
    return render_template(
        "pages/ns_create_flow.html",
        **kwargs,
        **_active_viewer_context(),
    )


@main_bp.get("/nomad-studio/create/simple")
def ns_create_simple_page():
    return _render_flow_page(
        flow_id="create.simple",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/simple-json")
def ns_create_simple_json_page():
    return _render_flow_page(
        flow_id="create.simple_json",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/simple-civitai")
def ns_create_simple_civitai_page():
    return _render_flow_page(
        flow_id="create.simple_civitai",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/assist")
def ns_create_assist_page():
    return _render_flow_page(
        flow_id="create.assist",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/assist-ideogram")
def ns_create_assist_ideogram_page():
    return _render_flow_page(
        flow_id="create.assist_ideogram",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/assist-ideogram-lettering")
def ns_create_assist_ideogram_lettering_page():
    return _render_flow_page(
        flow_id="create.assist_ideogram_lettering",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/assist-ideogram-ref")
def ns_create_assist_ideogram_ref_page():
    return _render_flow_page(
        flow_id="create.assist_ideogram_ref",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/ideogram-charref")
def ns_create_ideogram_charref_page():
    return _render_flow_page(
        flow_id="create.ideogram_charref",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/posters")
def ns_create_posters_page():
    return _render_flow_page(
        flow_id="create.posters",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/ideogram-poster")
def ns_create_ideogram_poster_page():
    return _render_flow_page(
        flow_id="create.ideogram_poster",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/ideogram-storyboard")
def ns_create_ideogram_storyboard_page():
    return _render_flow_page(
        flow_id="create.ideogram_storyboard",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/enhance-civitai")
def ns_create_enhance_civitai_page():
    return _render_flow_page(
        flow_id="create.enhance_civitai",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/chat")
def ns_create_chat_page():
    return _render_flow_page(
        flow_id="create.chat",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/chat-civitai")
def ns_create_chat_civitai_page():
    return _render_flow_page(
        flow_id="create.chat_civitai",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/variations-json")
def ns_create_variations_json_page():
    return _render_flow_page(
        flow_id="create.variations_json",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/variations")
def ns_create_variations_page():
    return _render_flow_page(
        flow_id="create.variations",
        active_page="nomad-studio",
    )



@main_bp.get("/nomad-studio/create/ideogram-scene")
def ns_create_ideogram_scene_page():
    return _render_flow_page(flow_id="create.ideogram_scene", active_page="nomad-studio")


@main_bp.get("/nomad-studio/create/portraits")
def ns_create_portraits_page():
    return _render_flow_page(
        flow_id="create.portraits",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/story")
def ns_create_story_page():
    return _render_flow_page(
        flow_id="create.story",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/create/<slug>")
def ns_create_generic_flow_page(slug: str):
    flow_id = "create." + slug.replace("-", "_")
    return _render_flow_page(
        flow_id=flow_id,
        active_page="nomad-studio",
    )


_TEMPLATE_PACKS_JSON = Path(__file__).parent.parent / "data" / "template_packs.json"


def _pack_slug(text: str) -> str:
    """Same dash-based slug style as every other Nomad Studio route
    (assist-ideogram, enhance-civitai, ...) — lowercase, non-alnum runs
    collapsed to a single '-'. Used both ways: to build a pack/theme's URL
    segment, and to resolve an incoming URL segment back to its original
    name (there's no separate slug field stored in template_packs.json)."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().lower())
    return re.sub(r"-+", "-", slug).strip("-") or "pack"


def _load_template_pack_items() -> list[dict]:
    try:
        data = json.loads(_TEMPLATE_PACKS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _load_pack_summaries() -> list[dict]:
    """One card per distinct `pack` value in template_packs.json (e.g.
    "Cinematic") — cover image from its first item, count = number of
    distinct themes so the card reads "24 looks" like the design, not the
    144 raw image variants underneath."""
    packs: dict[str, dict] = {}
    for it in _load_template_pack_items():
        pack_name = str(it.get("pack") or "").strip()
        if not pack_name:
            continue
        entry = packs.setdefault(
            pack_name,
            {"name": pack_name, "slug": _pack_slug(pack_name), "themes": set(), "cover": None},
        )
        theme = str(it.get("theme") or "").strip()
        if theme:
            entry["themes"].add(theme)
        images = it.get("images") or []
        if entry["cover"] is None and images:
            entry["cover"] = images[0].get("filename")
    return [
        {
            "name": p["name"],
            "slug": p["slug"],
            "cover_image": p["cover"],
            "count": len(p["themes"]),
        }
        for p in sorted(packs.values(), key=lambda p: p["name"])
    ]


def _load_pack_themes(pack_slug: str) -> tuple[str | None, list[dict]]:
    """Resolve pack_slug back to its real pack name, then group that pack's
    items by theme — one card per theme (e.g. "90s Smalltown"), cover =
    first image found under it."""
    items = _load_template_pack_items()
    pack_name = next(
        (str(it.get("pack") or "").strip() for it in items
         if str(it.get("pack") or "").strip() and _pack_slug(it["pack"]) == pack_slug),
        None,
    )
    if pack_name is None:
        return None, []

    themes: dict[str, dict] = {}
    for it in items:
        if str(it.get("pack") or "").strip() != pack_name:
            continue
        theme = str(it.get("theme") or "").strip()
        if not theme:
            continue
        entry = themes.setdefault(
            theme,
            {"name": theme, "slug": _pack_slug(theme), "cover": None, "description": None, "variant_count": 0},
        )
        entry["variant_count"] += 1
        images = it.get("images") or []
        if images:
            if entry["cover"] is None:
                entry["cover"] = images[0].get("filename")
            # Description shown on the theme card: the actual generated
            # prompt for its cover image — real, readable copy instead of
            # the raw {placeholder} template string. Clamped to 2 lines via
            # .rp-card-desc (same CSS the one-click preset cards already use).
            if entry["description"] is None:
                entry["description"] = images[0].get("prompt")
    return pack_name, sorted(themes.values(), key=lambda t: t["name"])


def _load_pack_theme_detail(pack_slug: str, theme_slug: str):
    """Resolve both slugs, then return (pack_name, theme_name, variants) —
    the individual template entries that make up this theme (e.g.
    "90s Smalltown — Portrait", "— Wide Shot", ...), each keeping its own
    id/name/template string/image."""
    pack_name, theme_name, variants = None, None, []
    for it in _load_template_pack_items():
        p = str(it.get("pack") or "").strip()
        t = str(it.get("theme") or "").strip()
        if not p or _pack_slug(p) != pack_slug:
            continue
        if not t or _pack_slug(t) != theme_slug:
            continue
        pack_name, theme_name = p, t
        variants.append(it)
    return pack_name, theme_name, variants


@main_bp.get("/nomad-studio/refine/presets")
def ns_refine_presets_page_redirect():
    # Moved under /presets/photo_pack so the breadcrumb can show Presets (the
    # group) and Photo Packs (this specific listing) as two separate levels —
    # kept as a redirect so old links/bookmarks still land somewhere.
    return redirect(url_for("main.ns_refine_presets_page"))


@main_bp.get("/nomad-studio/refine/presets/photo_pack")
def ns_refine_presets_page():
    presets = [
        f for f in _load_refine_flows()
        if f.get("group") == "presets" and f.get("preset_meta")
    ]
    return render_template(
        "pages/ns_refine_presets.html",
        active_page="nomad-studio",
        presets=presets,
    )


@main_bp.get("/nomad-studio/create/packs/<pack_slug>")
def ns_create_pack_gallery_page(pack_slug: str):
    # Template packs generate from a prompt, so they live under Create. A
    # theme card opens Create > From Template filtered to that theme's cards.
    pack_name, themes = _load_pack_themes(pack_slug)
    if pack_name is None:
        abort(404)
    return render_template(
        "pages/ns_create_pack_gallery.html",
        active_page="nomad-studio",
        pack_name=pack_name,
        pack_slug=pack_slug,
        themes=themes,
    )


# Packs used to sit under Refine > Presets; kept as redirects so old links and
# bookmarks still land somewhere.
@main_bp.get("/nomad-studio/refine/presets/pack/<pack_slug>")
def ns_refine_pack_gallery_page(pack_slug: str):
    return redirect(url_for("main.ns_create_pack_gallery_page", pack_slug=pack_slug))


@main_bp.get("/nomad-studio/refine/presets/pack/<pack_slug>/<theme_slug>")
def ns_refine_pack_composer_page(pack_slug: str, theme_slug: str):
    pack_name, theme_name, raw_variants = _load_pack_theme_detail(pack_slug, theme_slug)
    if pack_name is None or not raw_variants:
        abort(404)
    return redirect(url_for(
        "main.ns_create_generic_flow_page", slug="from-template",
        pack=pack_name, theme=theme_name,
    ))


@main_bp.get("/nomad-studio/refine/<slug>")
def ns_refine_flow_page(slug: str):
    flow_id = "refine." + slug.replace("-", "_")
    return _render_flow_page(
        flow_id=flow_id,
        section="refine",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/mix/canvas-composer")
def ns_canvas_composer_page():
    return render_template(
        "pages/ns_canvas_composer.html",
        active_page="nomad-studio",
    )


@main_bp.get("/nomad-studio/mix/<slug>")
def ns_mix_flow_page(slug: str):
    flow_id = "mix." + slug.replace("-", "_")
    return _render_flow_page(
        flow_id=flow_id,
        section="mix",
        active_page="nomad-studio",
    )


@main_bp.get("/models/import")
def models_import_page():
    return render_template("pages/models_import.html", active_page="models-import")


@main_bp.get("/models/chat")
def models_chat_page():
    return render_template("pages/models_chat.html", active_page="models-chat")


@main_bp.get("/models/vision")
def models_vision_page():
    return render_template("pages/models_chat.html", active_page="models-vision")


@main_bp.get("/models/upscale")
def models_upscale_page():
    return render_template("pages/models_upscale.html", active_page="models-upscale")


@main_bp.get("/models/compose")
def models_compose_page():
    return render_template("pages/models_compose.html", active_page="models-compose")


@main_bp.get("/settings")
def settings_page():
    return render_template("pages/settings.html", active_page="settings")


@main_bp.get("/help")
def help_page():
    return render_template("pages/help.html", active_page="help")
