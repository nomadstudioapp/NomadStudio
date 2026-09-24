"""Package importer — first version (docs/PACKAGE_FORMAT.md).

Supported today: packages that contribute **engines**, **flows** and
**workflows** (the engine and flow types A and C of §1). Anything else in
``contributes`` (addons, template packs, presets, step types, tags) is
rejected with a clear message until it is implemented. Signatures (§11.4) are
not checked yet: every package installs as unofficial.

Install is two steps, as in §11.1:
1. ``inspect_upload`` reads and validates the ZIP without installing and
   returns a summary plus a token;
2. ``install`` extracts to ``packages/.staging/``, validates the content and
   moves it to ``packages/<id>/``, then the caller applies the contributions
   to the registry (``apply_to_registry``) and the index is rewritten.

Where things go (§12.1; ``<data>`` is the user's data folder, app/paths.py):

    <data>/packages/
    ├── index.json
    ├── .staging/            uploads and extraction in progress
    └── <package id>/        manifest.json, engines/, flows/, workflows/ …

Nothing here touches the registry directly: ``apply_to_registry`` and
``remove_from_registry`` mutate the dict the route passes inside its
registry transaction.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
ID_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9-]+)+$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")
FLOW_CATEGORIES = {"create", "refine", "mix"}
ENGINE_CATEGORIES = {"image", "upscale", "compose"}

# §2.2 container limits
MAX_ZIP_BYTES = 200 * 2**20
MAX_UNPACKED_BYTES = 2**30
MAX_FILES = 5000
MAX_RATIO = 100
MAX_PATH_CHARS = 180  # relative path inside the package (Windows 260-char limit, §12.1)
IGNORED = ("__MACOSX/", ".DS_Store", "Thumbs.db", "__pycache__/")

SUPPORTED_CONTRIBUTIONS = {"engines", "flows", "workflows", "addon", "styles"}
STYLE_KEY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TOKEN_TTL_S = 3600


class PackageError(ValueError):
    """A package that cannot be installed; the message is shown to the user."""


# ── Locations ───────────────────────────────────────────────────────────────


def packages_dir(data_dir: Path) -> Path:
    return data_dir / "packages"


def _staging(data_dir: Path) -> Path:
    path = packages_dir(data_dir) / ".staging"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ── Index ───────────────────────────────────────────────────────────────────


def _empty_index() -> dict[str, Any]:
    return {"schema_version": 1, "generated_at": None, "packages": {}, "flows": {}, "engines": {}, "bundled": {}}


def read_index(data_dir: Path) -> dict[str, Any]:
    base = packages_dir(data_dir)
    for name in ("index.json", "index.json.bak"):
        try:
            data = json.loads((base / name).read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("packages"), dict):
                for key in ("flows", "engines", "bundled"):
                    data.setdefault(key, {})
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
    return _empty_index()


def write_index(data_dir: Path, index: dict[str, Any]) -> None:
    """Atomic write; the previous good index is kept as index.json.bak (§12.3)."""
    base = packages_dir(data_dir)
    base.mkdir(parents=True, exist_ok=True)
    index["generated_at"] = _now()
    target = base / "index.json"
    tmp = base / f"index.json.{uuid.uuid4().hex[:8]}.tmp"
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    if target.exists():
        shutil.copy2(target, base / "index.json.bak")
    os.replace(tmp, target)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Texts (§7.1) ────────────────────────────────────────────────────────────


def text_for(texts: Any, lang: str, default_lang: str = "en") -> str:
    """Pick a text from {lang: str}: app language → default_lang → en → any."""
    if isinstance(texts, str):
        return texts
    if not isinstance(texts, dict):
        return ""
    for key in (lang, default_lang, "en"):
        if texts.get(key):
            return str(texts[key])
    return next((str(v) for v in texts.values() if v), "")


# ── Container (§2.2) ────────────────────────────────────────────────────────


def _is_ignored(name: str) -> bool:
    return any(part in name for part in IGNORED)


def _check_member_name(name: str) -> None:
    if "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise PackageError(f"Unsafe path in package: {name}")
    parts = PurePosixPath(name).parts
    if ".." in parts:
        raise PackageError(f"Unsafe path in package: {name}")
    if len(name) > MAX_PATH_CHARS:
        raise PackageError(f"Path too long in package ({len(name)} characters): {name[:60]}…")


def _read_container(zip_path: Path) -> tuple[dict[str, Any], list[zipfile.ZipInfo]]:
    if zip_path.stat().st_size > MAX_ZIP_BYTES:
        raise PackageError("Package is larger than 200 MB")
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise PackageError("Not a valid ZIP file") from exc
    with zf:
        members = [m for m in zf.infolist() if not m.is_dir() and not _is_ignored(m.filename)]
        if len(members) > MAX_FILES:
            raise PackageError("Package has more than 5,000 files")
        total = 0
        lowered: dict[str, str] = {}
        for m in members:
            _check_member_name(m.filename)
            if (m.external_attr >> 16) & 0o170000 == 0o120000:
                raise PackageError(f"Package contains a symbolic link: {m.filename}")
            if m.compress_size and m.file_size / m.compress_size > MAX_RATIO:
                raise PackageError(f"Suspicious compression ratio: {m.filename}")
            total += m.file_size
            low = m.filename.lower()
            if low in lowered and lowered[low] != m.filename:
                raise PackageError(f"Two files differ only in letter case: {m.filename}")
            lowered[low] = m.filename
        if total > MAX_UNPACKED_BYTES:
            raise PackageError("Package is larger than 1 GB unpacked")
        if "manifest.json" not in {m.filename for m in members}:
            raise PackageError("manifest.json is missing from the root of the ZIP")
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PackageError(f"manifest.json is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise PackageError("manifest.json must be a JSON object")
    return manifest, members


# ── Manifest (§3) ───────────────────────────────────────────────────────────


def validate_manifest(manifest: dict[str, Any], files: set[str]) -> list[str]:
    """Raise PackageError for errors; return warnings."""
    warnings: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise PackageError(f"Unsupported schema_version (this app reads {SCHEMA_VERSION})")
    pkg_id = str(manifest.get("id", ""))
    if not ID_RE.match(pkg_id):
        raise PackageError(f"Invalid package id: {pkg_id!r}")
    if not SEMVER_RE.match(str(manifest.get("version", ""))):
        raise PackageError("version must be SemVer, e.g. 1.0.0")
    default_lang = str(manifest.get("default_lang", "")).strip()
    if not default_lang:
        raise PackageError("default_lang is required")
    name = manifest.get("name")
    if not isinstance(name, dict) or not str(name.get(default_lang, "")).strip():
        raise PackageError(f"name needs a text in default_lang ({default_lang})")
    author = manifest.get("author")
    if not isinstance(author, dict) or not str(author.get("name", "")).strip():
        raise PackageError("author.name is required")
    if not str(manifest.get("license", "")).strip():
        raise PackageError("license is required (SPDX id or \"proprietary\")")

    contributes = manifest.get("contributes")
    if not isinstance(contributes, dict) or not contributes:
        raise PackageError("contributes must declare at least one contribution")
    unsupported = sorted(set(contributes) - SUPPORTED_CONTRIBUTIONS)
    if unsupported:
        raise PackageError("This version of Nomad Studio cannot install: " + ", ".join(unsupported))
    for key in (SUPPORTED_CONTRIBUTIONS - {"addon"}) & set(contributes):
        items = contributes[key]
        if not isinstance(items, list) or not all(isinstance(p, str) for p in items):
            raise PackageError(f"contributes.{key} must be a list of file paths")
        for rel in items:
            if rel not in files:
                raise PackageError(f"contributes.{key}: file not found (check letter case): {rel}")
    if len(contributes.get("engines", [])) > 1:
        raise PackageError("A package can contribute one engine (its id is the package id)")
    # contributes.addon (§9 PACKAGE_FORMAT.md, minimal slice — no ctx API,
    # no hot install/uninstall yet): a dict, not a list of paths, so it
    # can't go through the generic loop above. The addon still imports
    # `from app…` directly and registers a plain Flask blueprint, same as
    # the source-tree addons/ folder — only `entry`'s presence is
    # validated here. addon_loader.py picks it up from
    # data/packages/<pkg>/addon/ on the NEXT app start.
    addon = contributes.get("addon")
    if addon is not None:
        if not isinstance(addon, dict) or not str(addon.get("entry", "")).strip():
            raise PackageError("contributes.addon must be a dict with an \"entry\" file path")
        entry = str(addon["entry"])
        if entry not in files:
            raise PackageError(f"contributes.addon.entry: file not found (check letter case): {entry}")
        warnings.append(
            "restart-required: this package installs code (contributes.addon) — "
            "restart Nomad Studio for it to activate."
        )
    if "LICENSE" not in files:
        warnings.append("no-license")
    warnings.extend(validate_required_models(manifest))
    return warnings


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_required_models(manifest: dict[str, Any]) -> list[str]:
    """requires.models / requires.comfy_nodes (PACKAGE_FORMAT.md §8.2): what
    each entry must look like. Problems are warnings, not rejections — a
    package with a malformed entry still installs; the "Missing files" panel
    just can't identify that one file."""
    requires = manifest.get("requires") if isinstance(manifest.get("requires"), dict) else {}
    warnings: list[str] = []
    models = requires.get("models")
    if models is not None:
        if not isinstance(models, list):
            return ["requires.models must be a list"]
        for i, m in enumerate(models):
            where = f"requires.models[{i}]"
            if not isinstance(m, dict):
                warnings.append(f"{where}: must be an object")
                continue
            if not str(m.get("file", "")).strip() or "/" in str(m.get("file")) or "\\" in str(m.get("file")):
                warnings.append(f"{where}: \"file\" must be a plain file name")
            if not str(m.get("folder", "")).strip():
                warnings.append(f"{where}: \"folder\" is required")
            if m.get("sha256") is not None and not _SHA256_RE.match(str(m["sha256"])):
                warnings.append(f"{where}: \"sha256\" must be 64 lowercase hex characters")
            if m.get("size") is not None and not (isinstance(m["size"], int) and m["size"] > 0):
                warnings.append(f"{where}: \"size\" must be a positive integer")
            if m.get("url") is not None and not str(m["url"]).startswith("https://"):
                warnings.append(f"{where}: \"url\" must start with https://")
    nodes = requires.get("comfy_nodes")
    if nodes is not None:
        if not isinstance(nodes, list):
            warnings.append("requires.comfy_nodes must be a list")
        else:
            for i, n in enumerate(nodes):
                # Old form: a bare pack id string — still accepted.
                if isinstance(n, str):
                    continue
                if not isinstance(n, dict) or not str(n.get("id", "")).strip():
                    warnings.append(f"requires.comfy_nodes[{i}]: needs an \"id\"")
    return warnings


def _load_json_member(zf: zipfile.ZipFile, rel: str) -> Any:
    try:
        return json.loads(zf.read(rel).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"{rel} is not valid JSON: {exc}") from exc


def validate_engine(engine: Any, rel: str) -> None:
    if not isinstance(engine, dict):
        raise PackageError(f"{rel}: an engine must be a JSON object")
    if str(engine.get("category", "")) not in ENGINE_CATEGORIES:
        raise PackageError(f"{rel}: category must be one of {sorted(ENGINE_CATEGORIES)}")
    if not str(engine.get("name", "")).strip():
        raise PackageError(f"{rel}: name is required")
    if not isinstance(engine.get("workflow"), dict) or not engine["workflow"]:
        raise PackageError(f"{rel}: workflow (ComfyUI API format) is required")
    if not isinstance(engine.get("analysis"), dict):
        raise PackageError(f"{rel}: analysis is required")


def validate_flow(flow: Any, rel: str, files: set[str]) -> None:
    if not isinstance(flow, dict):
        raise PackageError(f"{rel}: a flow must be a JSON object")
    flow_id = str(flow.get("id", ""))
    category = str(flow.get("category", ""))
    if category not in FLOW_CATEGORIES:
        raise PackageError(f"{rel}: category must be create, refine or mix")
    if not flow_id.startswith(category + ".") or len(flow_id) <= len(category) + 1:
        raise PackageError(f"{rel}: id must start with '{category}.'")
    if not card_fields(flow, "en")["label"]:
        raise PackageError(f"{rel}: the card needs a label")
    if not isinstance(flow.get("steps"), list) or not flow["steps"]:
        raise PackageError(f"{rel}: steps are required")
    for step in flow["steps"]:
        wf = step.get("workflow_file") if isinstance(step, dict) else None
        if wf and wf not in files:
            raise PackageError(f"{rel}: workflow_file not in the package: {wf}")


def validate_styles(styles: Any, rel: str, default_lang: str, files: set[str] | None = None) -> None:
    """contributes.styles file: a list of styles (§10.3). Styles are text
    only — prefix/suffix wrapped around the user's prompt — and independent
    of any model; `key` identifies each one inside its package."""
    if not isinstance(styles, list) or not styles:
        raise PackageError(f"{rel}: must be a non-empty list of styles")
    keys: set[str] = set()
    for i, style in enumerate(styles):
        where = f"{rel}[{i}]"
        if not isinstance(style, dict):
            raise PackageError(f"{where}: a style must be a JSON object")
        key = str(style.get("key", ""))
        if not STYLE_KEY_RE.match(key):
            raise PackageError(f"{where}: key must be a lowercase slug like 'golden-hour'")
        if key in keys:
            raise PackageError(f"{where}: duplicate key {key!r}")
        keys.add(key)
        if not text_for(style.get("name"), default_lang, default_lang):
            raise PackageError(f"{where}: name needs a text in default_lang ({default_lang})")
        for field in ("prefix", "suffix", "prompt"):
            if not isinstance(style.get(field, ""), str):
                raise PackageError(f"{where}: {field} must be a string")
        if not (str(style.get("prefix", "")).strip() or str(style.get("suffix", "")).strip()):
            raise PackageError(f"{where}: a style needs a prefix or a suffix")
        category = style.get("category", "")
        if not isinstance(category, (str, dict)):
            raise PackageError(f"{where}: category must be a text or a language object")
        # Optional per-model preview images: {engine id: path in the package}.
        images = style.get("images", {})
        if not isinstance(images, dict):
            raise PackageError(f"{where}: images must be an object of engine id → image path")
        for engine_id, path in images.items():
            if not isinstance(path, str) or not path.lower().endswith((".webp", ".png", ".jpg", ".jpeg")):
                raise PackageError(f"{where}: images.{engine_id} must be a .webp/.png/.jpg path")
            if files is not None and path not in files:
                raise PackageError(f"{where}: images.{engine_id} not in the package: {path}")


def load_package_styles(pkg_dir: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Every style an installed package contributes, in file order."""
    out: list[dict[str, Any]] = []
    for rel in (manifest.get("contributes") or {}).get("styles", []) or []:
        try:
            data = json.loads((pkg_dir / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, list):
            out.extend(s for s in data if isinstance(s, dict))
    return out


def _workflow_derived_flows(
    zf: zipfile.ZipFile, workflow_rels: list[str], skip_ids: set[str] = frozenset()
) -> list[tuple[str, dict[str, Any]]]:
    """§5.3 — a `contributes.workflows` file carrying a `{"_meta": {"title":
    "flow_data"}}` node describes a whole flow, not just a ComfyUI graph.
    flow_engine's runtime scanner (`_load_refine_flows_from_workflows`) used
    to redo this conversion on every request, and only for `app/workflows/`
    — never for an installed package. Doing it once, here, at install time
    means the app never has to look for it again (matches the doc's own
    "el nodo flow_data queda en el workflow, pero la app ya no lo busca en
    tiempo de ejecución").

    Returns [(generated flow.json's rel path inside the package, flow dict), ...].
    `rel` passed to the builder is the bare zip-member path (matches
    `contributes.workflows` and what `validate_flow` checks `workflow_file`
    against) — package-id prefixing happens later, only once the package's
    on-disk folder name is known (see `install()`).
    """
    from app.services.flow_engine import (
        _build_mix_flow_definition,
        _build_refine_flow_definition,
        _extract_flow_data_node,
    )

    out: list[tuple[str, dict[str, Any]]] = []
    for rel in workflow_rels:
        data = _load_json_member(zf, rel)
        if not isinstance(data, dict):
            continue
        meta = _extract_flow_data_node(data)
        if meta is None:
            continue
        flow_id = str(meta.get("id", "")).strip()
        if not flow_id:
            # Some workflow variants (e.g. Outpaint's per-engine files) carry
            # a "flow_data"-titled node that's only partial config (e.g. just
            # `preprocess`) read by whichever flow references them through
            # engine_select — not a standalone flow of their own. Same lenient
            # skip flow_engine's runtime scanner already used for this.
            continue
        if flow_id in skip_ids:
            # A workflow file can be both a supporting asset referenced by an
            # authored contributes.flows entry (via workflow_file) AND still
            # carry its own leftover flow_data with the SAME id — the
            # authored flow.json is the maintained one; the embedded copy is
            # stale and would otherwise silently overwrite it at install.
            continue
        is_mix = str(meta.get("category", "")).strip() == "mix" or flow_id.startswith("mix.")
        definition = (
            _build_mix_flow_definition(meta, rel)
            if is_mix
            else _build_refine_flow_definition(meta, rel)
        )
        out.append((f"flows/{flow_id.split('.', 1)[1]}.json", definition))
    return out


def _prefix_workflow_file_paths(node: Any, pkg_id: str) -> None:
    """In place: every `workflow_file` value and every `file=...` inside an
    `options_src` URL gets the installed package's id prefixed on — e.g.
    "workflows/x.json" -> "nomad.core-refine/workflows/x.json". Those bare
    paths are how the ZIP itself and `validate_flow` refer to a workflow
    (relative to the package root); once installed at
    `<data>/packages/<pkg_id>/`, `refine_routes.py::_load_workflow_file`
    needs the pkg_id on the front to know which package's copy to read —
    two installed refine packages can otherwise share the exact same bare
    filename with no way to tell them apart."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "workflow_file" and isinstance(value, str) and value and "/" in value:
                if not value.startswith(pkg_id + "/"):
                    node[key] = f"{pkg_id}/{value}"
            elif key == "options_src" and isinstance(value, str) and "file=" in value:
                prefix, _, rest = value.partition("file=")
                file_val, sep, tail = rest.partition("&")
                if file_val and not file_val.startswith(pkg_id + "/"):
                    file_val = f"{pkg_id}/{file_val}"
                node[key] = f"{prefix}file={file_val}{sep}{tail}"
            else:
                _prefix_workflow_file_paths(value, pkg_id)
    elif isinstance(node, list):
        for item in node:
            _prefix_workflow_file_paths(item, pkg_id)


def card_fields(flow: dict[str, Any], lang: str, default_lang: str = "en") -> dict[str, Any]:
    """Card texts for the hub. Accepts the package format (card.label/desc as
    texts, §6.1) and the legacy flat fields (label, card_desc, card_tags)."""
    card = flow.get("card") if isinstance(flow.get("card"), dict) else {}
    return {
        "label": text_for(card.get("label"), lang, default_lang) or str(flow.get("label", "")),
        "desc": text_for(card.get("desc"), lang, default_lang) or str(flow.get("card_desc", "")),
        "tags": list(card.get("tags") or flow.get("card_tags") or []),
    }


def _flow_texts_by_path(flow: dict[str, Any]) -> dict[str, str]:
    """Every translatable text of a flow, keyed by its path (§7.2) — the same
    keys the package's i18n/<lang>.json uses."""
    out: dict[str, str] = {}
    if isinstance(flow.get("description"), str):
        out["description"] = flow["description"]
    for step in flow.get("steps") or []:
        if not isinstance(step, dict):
            continue
        sid = step.get("id")
        for field in ("label", "placeholder", "hint", "note", "description"):
            if isinstance(step.get(field), str):
                out[f"steps.{sid}.{field}"] = step[field]
        for item in step.get("fields") or []:
            if not isinstance(item, dict):
                continue
            key = item.get("key") or item.get("id")
            for field in ("label", "placeholder", "hint", "note"):
                if isinstance(item.get(field), str):
                    out[f"steps.{sid}.fields.{key}.{field}"] = item[field]
            for option in item.get("options") or []:
                if isinstance(option, dict) and isinstance(option.get("label"), str):
                    out[f"steps.{sid}.fields.{key}.options.{option.get('value')}"] = option["label"]
    return out


def texts_for(data_dir: Path, lang: str) -> dict[str, str]:
    """Translations the installed packages carry for *lang*, as
    {text in the package's default language: translation}.

    Packages are self-contained (§7): the card texts are language objects
    inside the flow and the step texts live in i18n/<lang>.json. The app's own
    dictionary translates by English text (data-i18n-literal / tField), so this
    is keyed the same way and merges into it."""
    out: dict[str, str] = {}
    if not lang or lang == "en":
        return out
    index = read_index(data_dir)
    base = packages_dir(data_dir)
    for pkg_id, pkg in (index.get("packages") or {}).items():
        default_lang = pkg.get("default_lang") or "en"
        flows: dict[str, dict[str, Any]] = {}
        for flow_id, info in (index.get("flows") or {}).items():
            if info.get("package") != pkg_id:
                continue
            try:
                flows[flow_id] = json.loads((base / info["file"]).read_text(encoding="utf-8"))
            except (OSError, KeyError, ValueError):
                continue
        for flow in flows.values():
            card = flow.get("card") if isinstance(flow.get("card"), dict) else {}
            for field in ("label", "desc"):
                value = card.get(field)
                if isinstance(value, dict) and value.get(lang) and value.get(default_lang):
                    out[str(value[default_lang])] = str(value[lang])
        # Style names and categories (§10.3). Build > Styles splits a
        # category on "/" and shows each segment on its own, so segments are
        # translated one by one as well as the full "Group/Sub" string.
        try:
            manifest = json.loads((base / pkg_id / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        for style in load_package_styles(base / pkg_id, manifest):
            name = style.get("name")
            if isinstance(name, dict) and name.get(lang) and name.get(default_lang):
                out[str(name[default_lang])] = str(name[lang])
            category = style.get("category")
            if isinstance(category, dict) and category.get(lang) and category.get(default_lang):
                src, dst = str(category[default_lang]), str(category[lang])
                out[src] = dst
                src_parts, dst_parts = src.split("/"), dst.split("/")
                if len(src_parts) == len(dst_parts):
                    for s, d in zip(src_parts, dst_parts):
                        out.setdefault(s, d)
        try:
            translations = json.loads((base / pkg_id / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(translations, dict):
            continue
        for flow_id, by_path in translations.items():
            flow = flows.get(flow_id)
            if not isinstance(by_path, dict) or flow is None:
                continue
            source = _flow_texts_by_path(flow)
            for path, translated in by_path.items():
                original = source.get(path)
                if original and isinstance(translated, str) and translated.strip():
                    out[original] = translated
    return out


# ── Inspect (upload → summary) ──────────────────────────────────────────────


def inspect_zip(zip_path: Path, index: dict[str, Any], builtin_flow_ids: set[str], lang: str = "en") -> dict[str, Any]:
    """Validate a package without installing it and describe what it would do."""
    manifest, members = _read_container(zip_path)
    files = {m.filename for m in members}
    warnings = validate_manifest(manifest, files)
    pkg_id = manifest["id"]
    contributes = manifest["contributes"]
    default_lang = manifest["default_lang"]

    engines: list[dict[str, Any]] = []
    flows: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as zf:
        for rel in contributes.get("engines", []):
            engine = _load_json_member(zf, rel)
            validate_engine(engine, rel)
            engines.append({"id": pkg_id, "name": engine["name"], "category": engine["category"]})
        for rel in contributes.get("workflows", []):
            if not isinstance(_load_json_member(zf, rel), dict):
                raise PackageError(f"{rel}: a workflow must be a JSON object")
        for rel in contributes.get("flows", []):
            flow = _load_json_member(zf, rel)
            validate_flow(flow, rel, files)
            owner = (index.get("flows", {}).get(flow["id"]) or {}).get("package")
            if flow["id"] in builtin_flow_ids or (owner and owner != pkg_id):
                raise PackageError(f"Flow id already in use: {flow['id']}")
            card = card_fields(flow, lang, default_lang)
            flows.append({"id": flow["id"], "category": flow["category"], "label": card["label"], "desc": card["desc"]})
        static_flow_ids = {f["id"] for f in flows}
        for rel, flow in _workflow_derived_flows(zf, contributes.get("workflows", []), skip_ids=static_flow_ids):
            validate_flow(flow, rel, files)
            owner = (index.get("flows", {}).get(flow["id"]) or {}).get("package")
            if flow["id"] in builtin_flow_ids or (owner and owner != pkg_id):
                raise PackageError(f"Flow id already in use: {flow['id']}")
            card = card_fields(flow, lang, default_lang)
            flows.append({"id": flow["id"], "category": flow["category"], "label": card["label"], "desc": card["desc"]})
        style_count = 0
        style_keys: set[str] = set()
        for rel in contributes.get("styles", []):
            styles = _load_json_member(zf, rel)
            validate_styles(styles, rel, default_lang, files)
            dupes = style_keys & {s["key"] for s in styles}
            if dupes:
                raise PackageError(f"{rel}: style key already used in this package: {sorted(dupes)[0]}")
            style_keys |= {s["key"] for s in styles}
            style_count += len(styles)

    installed = index.get("packages", {}).get(pkg_id)
    operation = "install"
    if installed:
        operation = "reinstall" if installed.get("version") == manifest["version"] else "update"

    missing = _missing_requirements(manifest, index, engines)
    return {
        "id": pkg_id,
        "version": manifest["version"],
        "installedVersion": installed.get("version") if installed else None,
        "operation": operation,
        "name": text_for(manifest.get("name"), lang, default_lang),
        "summary": text_for(manifest.get("summary"), lang, default_lang),
        "author": manifest["author"].get("name"),
        "license": manifest.get("license"),
        "defaultLang": default_lang,
        "signature": "unsigned",
        "engines": engines,
        "flows": flows,
        "styles": style_count,
        "requiresMissing": missing,
        "warnings": warnings,
        "sizeBytes": zip_path.stat().st_size,
        # Optional install order for packages shipped with the app (lower
        # first): the first image engine installed becomes the default one.
        "order": manifest.get("order") if isinstance(manifest.get("order"), int) else 100,
    }


def _missing_requirements(manifest: dict[str, Any], index: dict[str, Any], own_engines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    missing = []
    installed_engines = {**index.get("engines", {}), **{e["id"]: {"category": e["category"]} for e in own_engines}}
    for req in (manifest.get("requires") or {}).get("engines", []) or []:
        if not isinstance(req, dict):
            continue
        if req.get("id") and req["id"] not in installed_engines:
            missing.append({"engine": req["id"]})
        elif req.get("category") and not any(e.get("category") == req["category"] for e in installed_engines.values()):
            missing.append({"engineCategory": req["category"]})
    return missing


def save_upload(data_dir: Path, stream, filename: str) -> tuple[str, Path]:
    """Store an uploaded ZIP in .staging and return (token, path)."""
    _cleanup_staging(data_dir)
    token = uuid.uuid4().hex
    path = _staging(data_dir) / f"upload-{token}.zip"
    written = 0
    with path.open("wb") as fh:
        while True:
            chunk = stream.read(1 << 20)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_ZIP_BYTES:
                fh.close()
                path.unlink(missing_ok=True)
                raise PackageError("Package is larger than 200 MB")
            fh.write(chunk)
    return token, path


def upload_path(data_dir: Path, token: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{32}", str(token or "")):
        return None
    path = _staging(data_dir) / f"upload-{token}.zip"
    return path if path.is_file() else None


def discard_upload(data_dir: Path, token: str) -> None:
    path = upload_path(data_dir, token)
    if path:
        path.unlink(missing_ok=True)


def _cleanup_staging(data_dir: Path) -> None:
    now = time.time()
    for item in _staging(data_dir).iterdir():
        try:
            if now - item.stat().st_mtime > TOKEN_TTL_S:
                shutil.rmtree(item) if item.is_dir() else item.unlink()
        except OSError:
            pass


# ── Install / uninstall ─────────────────────────────────────────────────────


def install(data_dir: Path, zip_path: Path, index: dict[str, Any], builtin_flow_ids: set[str]) -> dict[str, Any]:
    """Extract and move the package into place and update the index in memory.
    Returns {"manifest", "engine", "flows", "summary"} for apply_to_registry.
    Any error before the final move leaves the installation as it was."""
    summary = inspect_zip(zip_path, index, builtin_flow_ids)
    manifest, members = _read_container(zip_path)
    pkg_id = manifest["id"]
    base = packages_dir(data_dir)
    stage = _staging(data_dir) / f"{pkg_id}-{uuid.uuid4().hex[:6]}"
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for m in members:
                target = (stage / m.filename).resolve()
                if not str(target).startswith(str(stage.resolve()) + os.sep):
                    raise PackageError(f"Unsafe path in package: {m.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(m) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        engine = None
        if manifest["contributes"].get("engines"):
            engine = json.loads((stage / manifest["contributes"]["engines"][0]).read_text(encoding="utf-8"))
        flow_rels = list(manifest["contributes"].get("flows", []))
        flows = [json.loads((stage / rel).read_text(encoding="utf-8")) for rel in flow_rels]

        # §5.3 flows synthesized from a `contributes.workflows` file's
        # flow_data node (see _workflow_derived_flows) don't exist as a real
        # file yet — materialize one now under flows/, same as an authored
        # one, so flow_engine's pack loader (which just globs
        # pack_dir/flows/**/*.json, no flow_data awareness of its own) finds
        # it with no changes of its own.
        with zipfile.ZipFile(zip_path) as zf:
            static_flow_ids = {f["id"] for f in flows}
            for rel, flow in _workflow_derived_flows(
                zf, manifest["contributes"].get("workflows", []), skip_ids=static_flow_ids
            ):
                flow_rels.append(rel)
                flows.append(flow)

        # workflow_file/options_src are bare inside the ZIP (validate_flow
        # checks them against the ZIP's own member list); from here on they
        # need the pkg_id prefix _load_workflow_file resolves against
        # PACKAGES_DIR, so every flow — authored or just-generated — gets
        # rewritten and (re)written to disk before the package goes live.
        for rel, flow in zip(flow_rels, flows):
            _prefix_workflow_file_paths(flow, pkg_id)
            target = stage / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(flow, indent=2, ensure_ascii=False), encoding="utf-8")

        final = base / pkg_id
        if final.exists():
            previous = base / ".previous"
            previous.mkdir(exist_ok=True)
            shutil.rmtree(previous / pkg_id, ignore_errors=True)
            os.replace(final, previous / pkg_id)
        os.replace(stage, final)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    # Index (§12.2)
    for flow_id, info in list(index.get("flows", {}).items()):
        if info.get("package") == pkg_id:
            del index["flows"][flow_id]
    index.get("engines", {}).pop(pkg_id, None)
    was_bundled = bool((index.get("packages", {}).get(pkg_id) or {}).get("bundled"))
    default_lang = manifest["default_lang"]
    for rel, flow in zip(flow_rels, flows):
        index["flows"][flow["id"]] = {
            "package": pkg_id,
            "category": flow["category"],
            "slug": flow["id"].split(".", 1)[1].replace("_", "-"),
            "file": f"{pkg_id}/{rel}",
            "state": "active",
            "status": str(flow.get("status", "active")),
            "complexity": flow.get("complexity"),
            "group": _group_id(manifest, flow),
            "label": card_fields(flow, default_lang, default_lang)["label"],
        }
    if engine:
        index["engines"][pkg_id] = {"category": engine["category"], "name": engine["name"], "state": "active"}
    index["packages"][pkg_id] = {
        "version": manifest["version"],
        "installed_at": _now(),
        "state": "missing_requirements" if summary["requiresMissing"] else "active",
        "state_detail": summary["requiresMissing"] or None,
        "default_lang": default_lang,
        "name": manifest["name"],
        "summary": manifest.get("summary"),
        "author": manifest["author"].get("name"),
        "license": manifest.get("license"),
        "info_url": manifest.get("info_url"),
        "store_url": manifest.get("store_url"),
        "signature": {"status": "unsigned"},
        "group": manifest.get("group"),
        "flows": [f["id"] for f in flows],
        "engines": [pkg_id] if engine else [],
        "styles": summary["styles"],
        "has_code": bool(manifest["contributes"].get("addon")),
        "bundled": was_bundled,
    }
    return {"manifest": manifest, "engine": engine, "flows": flows, "summary": summary}


def _group_id(manifest: dict[str, Any], flow: dict[str, Any]) -> str:
    group = manifest.get("group")
    if isinstance(group, dict) and group.get("id"):
        return str(group["id"])
    return str(flow.get("group") or "core")


def uninstall(data_dir: Path, pkg_id: str, index: dict[str, Any]) -> dict[str, Any]:
    if pkg_id not in index.get("packages", {}):
        raise PackageError(f"Package not installed: {pkg_id}")
    info = index["packages"].pop(pkg_id)
    # A package that ships with the app and the user removes on purpose must
    # not come back on the next start (install_bundled).
    if pkg_id in index.get("bundled", {}):
        index["bundled"][pkg_id]["removed"] = True
    for flow_id, flow in list(index.get("flows", {}).items()):
        if flow.get("package") == pkg_id:
            del index["flows"][flow_id]
    index.get("engines", {}).pop(pkg_id, None)
    base = packages_dir(data_dir).resolve()
    for folder in (base / pkg_id, base / ".previous" / pkg_id):
        if folder.is_dir() and folder.resolve().parent in (base, base / ".previous"):
            shutil.rmtree(folder)
    return info


# ── Packages included with the app ──────────────────────────────────────────


def _version_tuple(version: str) -> tuple[int, ...]:
    core = str(version or "0").split("+", 1)[0].split("-", 1)[0]
    try:
        return tuple(int(p) for p in core.split("."))
    except ValueError:
        return (0,)


def plan_bundled(folder: Path, index: dict[str, Any], builtin_flow_ids: set[str]) -> list[tuple[Path, str]]:
    """Which included ZIPs to install or update now, engines first:
    [(zip, "install" | "update")]. Skips packages the user uninstalled and
    ones already at the same or a newer version. Broken ZIPs are skipped (and
    left to the caller's log) so they never block the app from starting.
    ``folder`` is ``bundled-packages/`` next to app.py (paths.BUNDLED_PACKAGES_DIR)."""
    if not folder.is_dir():
        return []
    plan: list[tuple[tuple, Path, str]] = []
    for zip_path in sorted(folder.glob("*.zip")):
        try:
            summary = inspect_zip(zip_path, index, builtin_flow_ids)
        except PackageError:
            continue
        pkg_id = summary["id"]
        if (index.get("bundled", {}).get(pkg_id) or {}).get("removed"):
            continue
        installed = index.get("packages", {}).get(pkg_id)
        if installed is None:
            action = "install"
        elif _version_tuple(summary["version"]) > _version_tuple(installed.get("version", "0")):
            action = "update"
        else:
            continue
        plan.append(((0 if summary["engines"] else 1, summary["order"], zip_path.name), zip_path, action))
    return [(p, a) for _, p, a in sorted(plan, key=lambda x: x[0])]


def mark_bundled(index: dict[str, Any], manifest: dict[str, Any]) -> None:
    pkg_id = manifest["id"]
    index.setdefault("bundled", {})[pkg_id] = {"version": manifest["version"], "removed": False}
    if pkg_id in index.get("packages", {}):
        index["packages"][pkg_id]["bundled"] = True


# ── Registry integration ────────────────────────────────────────────────────


# Input names that point at a specific model FILE rather than a tunable
# generation parameter. An engine update always wins on these — the old
# value names whatever checkpoint/CLIP/VAE/LoRA the PREVIOUS package
# version shipped, and if the update swapped the underlying model (the
# whole point of the update), "preserving user tuning" across these keys
# would silently keep every future generation running the old model with
# no visible sign anything is wrong. Caught via nomad.engine.qwen-image's
# 2511→2.1 update: ComfyUI's own logs showed the old CLIP/VAE files
# loading even though the package's new workflow said otherwise.
_MODEL_FILE_INPUT_NAMES = frozenset({"unet_name", "clip_name", "vae_name", "ckpt_name", "lora_name"})


def _is_model_file_key(key: str) -> bool:
    _, _, input_name = key.partition(".")
    return input_name in _MODEL_FILE_INPUT_NAMES


def apply_to_registry(data: dict[str, Any], data_dir: Path, result: dict[str, Any]) -> None:
    """Register the installed engine as an import and the package's flows as
    an installed pack (read by flow_engine and the hub)."""
    manifest = result["manifest"]
    pkg_id = manifest["id"]
    engine = result["engine"]
    imports = data.setdefault("imports", [])
    if engine:
        previous = next((r for r in imports if r.get("id") == pkg_id), None)
        record = {
            "id": pkg_id,
            "category": engine["category"],
            "name": engine["name"],
            "createdAt": (previous or {}).get("createdAt") or _now(),
            "comfyApiUrl": "",  # the app setting is used (§8.1)
            "workflow": engine["workflow"],
            "analysis": engine["analysis"],
            "basicValues": engine.get("basicValues", {}),
            "advancedValues": engine.get("advancedValues", {}),
            "annotation": engine.get("annotation", {}),
            "package": pkg_id,
            "packageVersion": manifest["version"],
        }
        if previous:
            # An update keeps what the user tuned on this engine — except
            # model-file references (_is_model_file_key), where the new
            # package always wins. See _MODEL_FILE_INPUT_NAMES above.
            prev_advanced = {
                k: v for k, v in (previous.get("advancedValues") or {}).items()
                if not _is_model_file_key(k)
            }
            record["basicValues"] = {**record["basicValues"], **(previous.get("basicValues") or {})}
            record["advancedValues"] = {**record["advancedValues"], **prev_advanced}
            imports[imports.index(previous)] = record
        else:
            imports.append(record)
        if engine["category"] == "image":
            # Only becomes the active engine when there is none yet: Custom
            # mode starts from the active list, and generating on every
            # installed engine at once (most without their model files in
            # ComfyUI) is not a sensible default.
            image_ids = {r.get("id") for r in imports if r.get("category") == "image"}
            active = [i for i in (data.get("activeImportIds") or []) if isinstance(i, str) and i in image_ids]
            if not active:
                active = [pkg_id]
            data["activeImportIds"] = active
            data["activeImportId"] = active[0]
    packs = [p for p in data.get("installedPacks", []) if p.get("packId") != pkg_id]
    if result["flows"]:
        packs.append({
            "packId": pkg_id,
            "packDir": str(packages_dir(data_dir) / pkg_id),
            "name": text_for(manifest.get("name"), "en", manifest["default_lang"]),
            "version": manifest["version"],
            "installDate": _now(),
            "package": True,
        })
    data["installedPacks"] = packs


def remove_from_registry(data: dict[str, Any], pkg_id: str) -> None:
    data["imports"] = [r for r in data.get("imports", []) if r.get("id") != pkg_id]
    active = [i for i in (data.get("activeImportIds") or []) if i != pkg_id]
    data["activeImportIds"] = active
    if data.get("activeImportId") == pkg_id or data.get("activeImportId") not in active:
        data["activeImportId"] = active[0] if active else None
    data["installedPacks"] = [p for p in data.get("installedPacks", []) if p.get("packId") != pkg_id]


# ── Listing ─────────────────────────────────────────────────────────────────


def list_packages(data_dir: Path, lang: str = "en") -> list[dict[str, Any]]:
    index = read_index(data_dir)
    engines = index.get("engines", {})
    out = []
    for pkg_id, info in sorted(index.get("packages", {}).items()):
        default_lang = info.get("default_lang") or "en"
        missing = []
        try:
            manifest = json.loads((packages_dir(data_dir) / pkg_id / "manifest.json").read_text(encoding="utf-8"))
            missing = _missing_requirements(manifest, index, [])
        except (OSError, json.JSONDecodeError):
            info = {**info, "state": "broken"}
        out.append({
            "id": pkg_id,
            "version": info.get("version"),
            "name": text_for(info.get("name"), lang, default_lang) or pkg_id,
            "summary": text_for(info.get("summary"), lang, default_lang),
            "author": info.get("author"),
            "state": "broken" if info.get("state") == "broken" else ("missing_requirements" if missing else "active"),
            "requiresMissing": missing,
            "signature": (info.get("signature") or {}).get("status", "unsigned"),
            "flows": [{"id": f, "label": (index.get("flows", {}).get(f) or {}).get("label") or f,
                       "category": (index.get("flows", {}).get(f) or {}).get("category")} for f in info.get("flows", [])],
            "engines": [{"id": e, "name": engines.get(e, {}).get("name") or e, "category": engines.get(e, {}).get("category")}
                        for e in info.get("engines", [])],
            "installedAt": info.get("installed_at"),
            "infoUrl": info.get("info_url"),
            "bundled": bool(info.get("bundled")),
            "license": info.get("license"),
        })
    return out
