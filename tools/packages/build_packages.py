"""Build Nomad Studio packages from the working catalog in OPENHIKER
(docs/PACKAGE_FORMAT.md §15.1 step 3).

    python tools/packages/build_packages.py --source D:\\OPENHIKER

Writes to dist/packages/ and validates every ZIP with the importer's own code
(app/services/package_service.inspect_zip), so a package that builds is a
package the app accepts.

Packages:
- the 7 free image engines (nomad.engine.*), one per engine in
  import_registry.json
- nomad.core-create: the Create › core flows (CORE_CREATE_FLOWS), needs any
  image engine
- nomad.create-layout: the Create › Layout flows (LAYOUT_FLOWS), renamed from
  their source ids

Engines ship the workflow's own defaults (analysis), never the values saved in
the source registry: those include the developer's last prompts and choices.
Download addresses the workflows do not declare (EXTRA_DOWNLOADS, taken from
the vault notes "Modelos - Descargas") go inside each engine package, in
annotation.downloads — the app keeps no per-engine download list of its own.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from app.routes.models_api_modules.imports_routes import _extract_downloads_from_workflow  # noqa: E402
from app.services import package_service  # noqa: E402
from app.services.flow_engine import _DISPLAY_KEYS, _PROMPT_KEYS  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vintage_presets import FAMILIES as VINTAGE_FAMILIES, UI_TEXTS as VINTAGE_UI_TEXTS  # noqa: E402

DIST = REPO / "dist" / "packages"
# Packages that ship with the app go in DIST — paths.BUNDLED_PACKAGES_DIR
# (dist/packages in a dev checkout) is scanned whole and every ZIP in it gets
# auto-installed on startup (package_service.plan_bundled globs *.zip with no
# filtering). Free/optional packs the user installs by choice — CivitAI is
# the first one — must NOT land there, or every fresh app would get them
# whether the user asked for them or not. DIST_OPTIONAL keeps them out of
# that scan while still producing a real, installable ZIP.
DIST_OPTIONAL = REPO / "dist" / "optional-packages"
# Hub-card covers of the Refine preset packs, one <pkg_id>.webp each (made with
# Z-Image Turbo, D:/NOMADSTUDIO_PACKS/tools/sessions/make_preset_pack_covers.py).
PACK_COVERS = Path(__file__).resolve().parent / "covers"
# The pack license every ZIP carries as LICENSE (paid, free and bundled alike;
# see LICENSING.md). Same file in NomadStudioPacks/tools/PACK_LICENSE.txt.
LICENSE_TEXT = (Path(__file__).resolve().parent / "PACK_LICENSE.txt").read_text(encoding="utf-8")
AUTHOR = {"name": "Nomad Studio"}

# registry name → package slug + short summary in the four app languages.
ENGINES = {
    "Krea 2 Turbo": ("krea-2-turbo", {
        "en": "Krea 2 in turbo mode: fast text-to-image generation.",
        "es": "Krea 2 en modo turbo: generación rápida de imágenes a partir de texto.",
        "zh": "Krea 2 极速模式：快速文生图。",
        "ko": "Krea 2 터보 모드: 빠른 텍스트-이미지 생성.",
    }),
    "Z-Image Turbo": ("z-image-turbo", {
        "en": "Fast image engine. Generates in a few steps.",
        "es": "Motor de imagen rápido. Genera en pocos pasos.",
        "zh": "快速图像引擎，只需几步即可生成。",
        "ko": "빠른 이미지 엔진. 적은 단계로 생성합니다.",
    }),
    "Flux Klein": ("flux-klein", {
        "en": "FLUX.2 Klein in 4B and 9B sizes: iterate on the light one, finish on the larger one.",
        "es": "FLUX.2 Klein en tamaños 4B y 9B: prueba con el ligero y termina con el grande.",
        "zh": "FLUX.2 Klein，提供 4B 与 9B 两种规模：用轻量版快速尝试，用大版本完成成品。",
        "ko": "FLUX.2 Klein 4B·9B: 가벼운 모델로 빠르게 시도하고 큰 모델로 마무리하세요.",
    }),
    "Ideogram 4": ("ideogram-4", {
        "en": "Ideogram 4: good with text and lettering inside the image.",
        "es": "Ideogram 4: bueno con texto y rótulos dentro de la imagen.",
        "zh": "Ideogram 4：擅长在图片中生成文字与字体设计。",
        "ko": "Ideogram 4: 이미지 안의 글자와 레터링에 강합니다.",
    }),
    # "Qwen Image" is NOT here anymore — build_qwen_image_21_engine() builds
    # it by hand (Qwen Image 2.1, no OPENHIKER source exists for it yet) and
    # main() calls that directly instead of engine_from_registry(). Keeping
    # the name in ENGINES would have the default build silently overwrite it
    # back to the old 2511-based content every run.
    "Z Anime": ("z-anime", {
        "en": "Anime-style image engine based on Z-Image, distilled to 4 steps.",
        "es": "Motor de imagen de estilo anime basado en Z-Image, destilado a 4 pasos.",
        "zh": "基于 Z-Image 的动漫风格图像引擎，蒸馏至 4 步。",
        "ko": "Z-Image 기반 애니메 스타일 이미지 엔진, 4단계로 증류.",
    }),
    "Krea2 Monaco": ("krea2-monaco", {
        "en": "Krea 2 with the Monaco setup. Some of its files come from third parties under their published terms.",
        "es": "Krea 2 con la configuración Monaco. Algunos de sus ficheros son de terceros y se distribuyen bajo sus términos publicados.",
        "zh": "采用 Monaco 配置的 Krea 2，部分文件来自第三方并遵循其公布的条款。",
        "ko": "Monaco 구성의 Krea 2. 일부 파일은 서드파티 제공이며 게시된 약관을 따릅니다.",
    }),
}

# Engines that are never shipped by Nomad Studio's own bundled set (see
# DIST_OPTIONAL below) — built only on request, for the person who owns the
# CivitAI page to upload themselves. Krea2 Roma's Midjourney-style LoRA
# requires credit and restricts commercial use to CivitAI's own rental
# program (OPENHIKER#91, NomadStudio memory nomad-studio-krea2-roma-license):
# Nomad Studio doesn't redistribute that file under its own name, so this
# package exists only as an asset for the person publishing it on CivitAI —
# never added to ENGINES above, never built by the default `main()` run.
ENGINES_OPTIONAL = {
    "Krea2 Roma": ("krea2-roma", {
        "en": "Krea 2 with a Midjourney-style LoRA for a stronger stylized look. Ships third-party files under their own published licenses — one of them (the Midjourney-style LoRA) requires credit and restricts commercial use to CivitAI's rental program.",
        "es": "Krea 2 con una LoRA de estilo Midjourney para un look más marcado. Incluye ficheros de terceros bajo sus propias licencias — una de ellas (la LoRA de estilo Midjourney) exige crédito y restringe el uso comercial al programa de alquiler de CivitAI.",
        "zh": "搭配 Midjourney 风格 LoRA 的 Krea 2，风格更强烈。包含第三方文件，遵循各自发布的许可条款——其中一个（Midjourney 风格 LoRA）要求署名，且商业用途仅限 CivitAI 的租赁计划。",
        "ko": "더 강한 스타일을 위한 Midjourney 스타일 LoRA가 포함된 Krea 2. 각자의 라이선스를 따르는 서드파티 파일을 포함합니다 — 그중 하나(Midjourney 스타일 LoRA)는 크레딧 표기가 필요하며 상업적 이용은 CivitAI 대여 프로그램으로 제한됩니다.",
    }),
}

# Workflow identifier each engine brings ("--v monaco" in a prompt,
# NomadStudio#27; app/services/import_slugs.py). Short, stable, unique —
# changing one breaks the prompts people saved with it.
ENGINE_SLUGS = {
    "krea-2-turbo": "krea", "z-image-turbo": "zimage", "flux-klein": "klein", "ideogram-4": "ideogram",
    "z-anime": "anime", "krea2-monaco": "monaco", "krea2-roma": "roma", "qwen-image": "qwen",
}

# Downloads the source workflows do not declare (vault: "Modelos - Descargas").
EXTRA_DOWNLOADS = {
    "Z Anime": [
        {"subfolder": "diffusion_models/z_image", "filename": "z-anime-distill-4step-fp8.safetensors",
         "url": "https://huggingface.co/SeeSee21/Z-Anime/resolve/main/diffusion_models/z-anime-distill-4step-fp8.safetensors?download=true"},
        {"subfolder": "text_encoders", "filename": "qwen_3_4b.safetensors",
         "url": "https://huggingface.co/Comfy-Org/flux2-klein/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors?download=true"},
        {"subfolder": "vae", "filename": "ae.safetensors",
         "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors?download=true"},
    ],
    # Krea2 Monaco needs four files published only on CivitAI, which refuses
    # anonymous downloads: the app asks for the user's own API key (Settings).
    # It reuses a Krea 2 base checkpoint and swaps the Midjourney-style LoRA
    # for one with clearer, more permissive terms (OPENHIKER#91). The
    # checkpoint itself derives from Krea 2, whose own
    # licence is still unread — OPENHIKER#16.
    "Krea2 Monaco": [
        {"subfolder": "text_encoders", "filename": "qwen3vl_4b_fp8_scaled.safetensors",
         "url": "https://huggingface.co/Comfy-Org/Krea-2/resolve/main/text_encoders/qwen3vl_4b_fp8_scaled.safetensors?download=true"},
        {"subfolder": "vae", "filename": "wan_2.1_vae.safetensors",
         "url": "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors?download=true"},
        # sha256 of the file the workflow actually uses: a CivitAI version can
        # hold several builds of the same model (this one has nine — fp8, int8,
        # bf16, GGUF), and its "primary" file is not the one here.
        {"subfolder": "diffusion_models/krea2", "filename": "gonzalomoKrea2_v40.safetensors",
         "url": "https://civitai.com/api/download/models/3245099?fileId=3128557",
         "sha256": "FE60E264437D93CAC026025738157D763D1F311B90A22AFD56D1FE7497C36F9F",
         "sizeBytes": 13491950981, "needsCivitaiKey": True,
         "source": {"name": "GonzaLomo Krea 2 v4.0 (int8)", "author": "GBRX",
                    "page": "https://civitai.com/models/2761943",
                    "credit": False, "commercial": ["Image", "RentCivit"], "derivatives": True}},
        {"subfolder": "loras/krea2", "filename": "KREA_MIDJ_1.safetensors",
         "url": "https://civitai.com/api/download/models/3095398?fileId=2974963",
         "sha256": "AD4A9F0B4D61BA77C5783B51FE3A2B637F8245144C1CE5E6A3FCD8225FD7DF8A",
         "sizeBytes": 228587776, "needsCivitaiKey": True,
         "source": {"name": "KREA_2_MIDJOURNEY (KREA_v1.0)", "author": "SPOON_IA",
                    "page": "https://civitai.com/models/2751419",
                    "credit": False, "commercial": ["Image", "RentCivit", "Rent", "Sell"], "derivatives": True}},
        {"subfolder": "loras/krea2", "filename": "ultra_real_krea2_v2.safetensors",
         "url": "https://civitai.com/api/download/models/3182356?fileId=3062944",
         "sha256": "233A8B1DF4B3387F9F2BEDAA2099D0E14CC946D1105F732DE2A8600310B86F07",
         "sizeBytes": 228588904, "needsCivitaiKey": True,
         "source": {"name": "UltraReal - Krea2, Klein9b (KR2_V2)", "author": "vizsumit",
                    "page": "https://civitai.com/models/2462105",
                    "credit": False, "commercial": ["Image", "Rent", "Sell"], "derivatives": True}},
    ],
    # Same checkpoint and UltraReal LoRA as Monaco, plus the restrictive
    # Midjourney-style LoRA Monaco deliberately swapped out.
    "Krea2 Roma": [
        {"subfolder": "text_encoders", "filename": "qwen3vl_4b_fp8_scaled.safetensors",
         "url": "https://huggingface.co/Comfy-Org/Krea-2/resolve/main/text_encoders/qwen3vl_4b_fp8_scaled.safetensors?download=true"},
        {"subfolder": "vae", "filename": "wan_2.1_vae.safetensors",
         "url": "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors?download=true"},
        {"subfolder": "diffusion_models/krea2", "filename": "gonzalomoKrea2_v40.safetensors",
         "url": "https://civitai.com/api/download/models/3245099?fileId=3128557",
         "sha256": "FE60E264437D93CAC026025738157D763D1F311B90A22AFD56D1FE7497C36F9F",
         "sizeBytes": 13491950981, "needsCivitaiKey": True,
         "source": {"name": "GonzaLomo Krea 2 v4.0 (int8)", "author": "GBRX",
                    "page": "https://civitai.com/models/2761943",
                    "credit": False, "commercial": ["Image", "RentCivit"], "derivatives": True}},
        {"subfolder": "loras/krea2", "filename": "midjourney_8_2_k2_epoch_20.safetensors",
         "url": "https://civitai.com/api/download/models/3252404?fileId=3135445",
         "sha256": "849F53831D235BD4DE58E43AE05C78F9F338867F5803747726D47B638F9EA41C",
         "sizeBytes": 228581243, "needsCivitaiKey": True,
         "source": {"name": "Midjourney Style v1.0 K2", "author": "zwaetschge",
                    "page": "https://civitai.com/models/601666",
                    "credit": True, "commercial": ["RentCivit"], "derivatives": False}},
        {"subfolder": "loras/krea2", "filename": "ultra_real_krea2_v2.safetensors",
         "url": "https://civitai.com/api/download/models/3182356?fileId=3062944",
         "sha256": "233A8B1DF4B3387F9F2BEDAA2099D0E14CC946D1105F732DE2A8600310B86F07",
         "sizeBytes": 228588904, "needsCivitaiKey": True,
         "source": {"name": "UltraReal - Krea2, Klein9b (KR2_V2)", "author": "vizsumit",
                    "page": "https://civitai.com/models/2462105",
                    "credit": False, "commercial": ["Image", "Rent", "Sell"], "derivatives": True}},
    ],
}


def engine_from_registry(source: Path, name: str) -> dict:
    registry = json.loads((source / "app" / "workflows" / "import_registry.json").read_text(encoding="utf-8"))
    record = next((r for r in registry.get("imports", []) if r.get("name") == name), None)
    if record is None:
        raise SystemExit(f"engine {name!r} not found in {source}")
    analysis = record["analysis"]
    annotation = {k: v for k, v in (record.get("annotation") or {}).items() if k in ("downloads", "loras", "optionalSubgraphs")}

    declared = {d["filename"].lower() for d in _extract_downloads_from_workflow(record["workflow"])}
    downloads = [d for d in (annotation.get("downloads") or []) if isinstance(d, dict)]
    have = declared | {str(d.get("filename", "")).lower() for d in downloads}
    for extra in EXTRA_DOWNLOADS.get(name, []):
        if extra["filename"].lower() not in have:
            downloads.append(extra)
    annotation["downloads"] = downloads

    return {
        "category": record["category"],
        "name": record["name"],
        "workflow": record["workflow"],
        "analysis": analysis,
        # Workflow defaults, as a fresh import would store them.
        "basicValues": analysis.get("basicValues", {}),
        "advancedValues": {
            p["key"]: p["value"] for p in analysis.get("advancedParameters", []) if not p.get("isLinked")
        },
        "annotation": annotation,
    }


# ── Languages (PACKAGE_FORMAT.md §7) ────────────────────────────────────────
# A package carries its own text: card label and description per language
# (§7.1) and the step texts in i18n/<lang>.json (§7.2). The translations
# already exist in the app dictionary (flow.flowLabels, keyed by the English
# text) — they belong to the flows, so the build moves them into the package.
LANGS = ("es", "zh", "ko")
TEXT_FIELDS = ("label", "placeholder", "hint", "note", "description")


def load_translations(source: Path) -> dict[str, dict[str, str]]:
    """English text → {lang: translation}, from the app dictionaries (the
    source's and this repo's own, which wins) plus the extra table next to
    this script (texts no dictionary has)."""
    table: dict[str, dict[str, str]] = {}
    for base in (source, REPO):
        for lang in LANGS:
            path = base / "app" / "static" / "i18n" / f"{lang}.json"
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            for english, translated in (data.get("flow", {}).get("flowLabels") or {}).items():
                if isinstance(translated, str) and translated.strip():
                    table.setdefault(english, {})[lang] = translated
    extra_path = Path(__file__).with_name("flow_translations.json")
    if extra_path.is_file():
        for english, langs in json.loads(extra_path.read_text(encoding="utf-8")).items():
            table.setdefault(english, {}).update(langs)
    return table


def _texts_by_path(flow: dict) -> dict[str, str]:
    """Every translatable text of a flow, keyed by its §7.2 path."""
    out: dict[str, str] = {}
    if isinstance(flow.get("description"), str):
        out["description"] = flow["description"]
    for step in flow.get("steps") or []:
        if not isinstance(step, dict):
            continue
        sid = step.get("id")
        for field in TEXT_FIELDS:
            if isinstance(step.get(field), str) and step[field].strip():
                out[f"steps.{sid}.{field}"] = step[field]
        for item in step.get("fields") or []:
            if not isinstance(item, dict):
                continue
            key = item.get("key") or item.get("id")
            for field in TEXT_FIELDS:
                if isinstance(item.get(field), str) and item[field].strip():
                    out[f"steps.{sid}.fields.{key}.{field}"] = item[field]
            for option in item.get("options") or []:
                if isinstance(option, dict) and isinstance(option.get("label"), str):
                    out[f"steps.{sid}.fields.{key}.options.{option.get('value')}"] = option["label"]
    return out


# Flows the hub shows in its short "Essentials" view by default (the pin next
# to the filter toggle). Every other flow ships without the field, which the
# app reads as false; each profile can then add or remove its own.
ESSENTIAL_FLOWS = {
    "create.simple", "create.assist",
    "refine.edit_qwen2_basic", "refine.remove_bg", "refine.upscale_model", "refine.pe_restore",
}


def add_card_texts(flow: dict, table: dict[str, dict[str, str]]) -> dict:
    """Card label and description in every language we have (§7.1). The flat
    English fields stay for older installs. Also marks the ESSENTIAL_FLOWS."""
    if flow.get("id") in ESSENTIAL_FLOWS:
        flow["essential"] = True
    def texts(english: str) -> dict[str, str]:
        return {"en": english, **{k: v for k, v in (table.get(english) or {}).items()}}

    card = {"tags": list(flow.get("card_tags") or [])}
    if isinstance(flow.get("label"), str):
        card["label"] = texts(flow["label"])
    if isinstance(flow.get("card_desc"), str):
        card["desc"] = texts(flow["card_desc"])
    flow["card"] = card
    return flow


_SOURCE_FIXES_PATH = Path(__file__).with_name("flow_source_fixes.json")
_SOURCE_FIXES: dict[str, str] = (json.loads(_SOURCE_FIXES_PATH.read_text(encoding="utf-8"))
                                 if _SOURCE_FIXES_PATH.is_file() else {})


def _fix_source_texts(node: object) -> None:
    """A few source flows still carry Spanish labels and descriptions. The
    package's own language is English (default_lang), so they are rewritten
    here, in place, before the translations are looked up by their text."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                if (key in _DISPLAY_KEYS or key == "description") and value in _SOURCE_FIXES:
                    node[key] = _SOURCE_FIXES[value]
            else:
                _fix_source_texts(value)
    elif isinstance(node, list):
        for item in node:
            _fix_source_texts(item)


def flow_i18n(flows: list[dict], table: dict[str, dict[str, str]]) -> tuple[dict[str, dict], dict[str, int]]:
    """{lang: {flow id: {path: text}}} plus how many texts each language covers."""
    files: dict[str, dict] = {lang: {} for lang in LANGS}
    counts = {lang: 0 for lang in LANGS}
    total = 0
    for flow in flows:
        _fix_source_texts(flow)
        paths = _texts_by_path(flow)
        total += len(paths)
        for lang in LANGS:
            translated = {path: table[text][lang] for path, text in paths.items()
                          if text in table and lang in table[text]}
            if translated:
                files[lang][flow["id"]] = translated
                counts[lang] += len(translated)
        # Texts in shapes the paths don't reach (engine pickers, tooltips,
        # option groups…): translated by their own text, "_texts" (see
        # flow_engine._apply_texts, same rules).
        for text in display_texts(flow):
            for lang in LANGS:
                if lang in (table.get(text) or {}):
                    files[lang].setdefault("_texts", {})[text] = table[text][lang]
    counts["total"] = total
    return files, counts


def display_texts(flow: dict) -> set[str]:
    """Every text flow_engine._apply_texts can translate in this flow."""
    out: set[str] = set()

    def walk(node, parent_key=""):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _PROMPT_KEYS:
                    continue
                if key in _DISPLAY_KEYS and isinstance(value, str) and value.strip():
                    out.add(value)
                elif key == "options" and parent_key == "groups" and isinstance(value, list):
                    out.update(o for o in value if isinstance(o, str) and o.strip())
                    walk(value, key)
                else:
                    walk(value, key)
        elif isinstance(node, list):
            for item in node:
                walk(item, parent_key)

    walk(flow.get("steps") or [], "steps")
    return out


def flow_from_source(source: Path, flow_id: str) -> dict:
    index = json.loads((source / "app" / "instructions" / "index.json").read_text(encoding="utf-8"))
    entry = next((e for e in index["flows"] if e["id"] == flow_id), None)
    if entry is None:
        raise SystemExit(f"flow {flow_id!r} not in {source} index.json")
    return json.loads((source / "app" / "instructions" / entry["file"]).read_text(encoding="utf-8"))


def flow_from_path(source: Path, rel_file: str) -> dict:
    """Same as flow_from_source, but for a flow whose file exists and is
    complete but isn't (yet) registered in index.json — e.g.
    refine.pe_remove_glare, confirmed working, just missing its index entry."""
    return json.loads((source / "app" / "instructions" / rel_file).read_text(encoding="utf-8"))


# ── requires.models / requires.comfy_nodes (PACKAGE_FORMAT.md §8, D15) ──────
# The package says WHICH files and nodes its graphs need; WHERE a model is
# downloaded lives in the models catalog (app/static/data/models_catalog.json,
# live copy in the Nomad Studio Packs repo), so a dead link is fixed in one
# place without republishing packages. The graphs themselves are not touched.
# Both lists are derived here from the graphs a package ships (workflows/*,
# engines/*.workflow) — nobody writes them by hand.
MODELS_CATALOG_PATH = REPO / "app" / "static" / "data" / "models_catalog.json"
NODE_PACKS_PATH = REPO / "app" / "static" / "data" / "custom_node_packs.json"
_MODEL_FILE_SUFFIXES_ALL = (".safetensors", ".gguf", ".pth", ".pt", ".bin", ".ckpt", ".sft", ".onnx")
# Loader class → ComfyUI folder, for a file the catalog doesn't know.
_LOADER_FOLDERS = {
    "UNETLoader": "diffusion_models", "UnetLoaderGGUF": "diffusion_models",
    "CLIPLoader": "text_encoders", "DualCLIPLoader": "text_encoders", "TripleCLIPLoader": "text_encoders",
    "VAELoader": "vae", "LoraLoader": "loras", "LoraLoaderModelOnly": "loras",
    "CheckpointLoaderSimple": "checkpoints", "CLIPVisionLoader": "clip_vision",
    "UpscaleModelLoader": "upscale_models", "ModelPatchLoader": "model_patches",
    "StyleModelLoader": "style_models", "ControlNetLoader": "controlnet",
}
_INPUT_FOLDERS = {"unet_name": "diffusion_models", "clip_name": "text_encoders", "vae_name": "vae",
                  "lora_name": "loras", "ckpt_name": "checkpoints", "model_name": "upscale_models"}
_catalog_cache: dict | None = None
_node_packs_cache: dict | None = None


def _models_catalog() -> dict:
    global _catalog_cache
    if _catalog_cache is None:
        _catalog_cache = json.loads(MODELS_CATALOG_PATH.read_text(encoding="utf-8"))
    return _catalog_cache


def _node_packs() -> dict:
    global _node_packs_cache
    if _node_packs_cache is None:
        _node_packs_cache = json.loads(NODE_PACKS_PATH.read_text(encoding="utf-8")) if NODE_PACKS_PATH.is_file() else {}
    return _node_packs_cache


def _graph_model_refs(graph: dict) -> list[tuple[str, str, str]]:
    """(file name, subfolder in the graph, folder guess) for every model file
    the graph loads: loader inputs plus the `config` node's quantization
    variants. Text nodes (a "Downloads" list) are not loaders."""
    refs: list[tuple[str, str, str]] = []
    input_class: dict[str, str] = {}
    for node in graph.values():
        if not isinstance(node, dict) or node.get("class_type") == "PrimitiveStringMultiline":
            continue
        for key, value in (node.get("inputs") or {}).items():
            if isinstance(value, str) and value.lower().endswith(_MODEL_FILE_SUFFIXES_ALL):
                parts = [p for p in re.split(r"[\\/]", value) if p]
                cls = str(node.get("class_type", ""))
                input_class.setdefault(key, cls)
                refs.append((parts[-1], "/".join(parts[:-1]), _LOADER_FOLDERS.get(cls) or _INPUT_FOLDERS.get(key, "")))
    config_node = graph.get("config")
    if isinstance(config_node, dict) and config_node.get("class_type") == "PrimitiveStringMultiline":
        try:
            config = json.loads(str((config_node.get("inputs") or {}).get("value") or ""))
        except ValueError:
            config = {}
        for raw in ((config or {}).get("quantization") or {}).values():
            pairs = [("unet_name", raw)] if isinstance(raw, str) else list(raw.items()) if isinstance(raw, dict) else []
            for key, value in pairs:
                if isinstance(value, str) and value.lower().endswith(_MODEL_FILE_SUFFIXES_ALL):
                    parts = [p for p in re.split(r"[\\/]", value) if p]
                    cls = input_class.get(key, "")
                    refs.append((parts[-1], "/".join(parts[:-1]),
                                 _LOADER_FOLDERS.get(cls) or _INPUT_FOLDERS.get(key, "")))
    return refs


def requirements_for(graphs: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """(requires.models, requires.comfy_nodes, files the catalog doesn't know)."""
    catalog = _models_catalog().get("models", [])
    by_name = {n.lower(): m for m in catalog for n in m.get("names", [])}
    models: dict[str, dict] = {}
    unknown: list[str] = []
    classes: set[str] = set()
    for graph in graphs:
        classes |= {str(n.get("class_type")) for n in graph.values() if isinstance(n, dict) and n.get("class_type")}
        for name, sub, guess in _graph_model_refs(graph):
            if name.lower() in models:
                continue
            entry = by_name.get(name.lower())
            item = {"file": name,
                    "folder": entry["folder"] if entry else "/".join(p for p in (guess, sub) if p) or guess}
            if entry:
                item.update(size=entry["size"], sha256=entry["sha256"])
            else:
                unknown.append(name)
            models[name.lower()] = item
    packs = _node_packs()
    nodes: dict[str, dict] = {}
    for cls in sorted(classes):
        pack_id = (packs.get("classes") or {}).get(cls)
        if not pack_id:
            continue
        pack = (packs.get("packs") or {}).get(pack_id) or {}
        nodes.setdefault(pack_id, {"id": pack_id, "repo": pack.get("repo") or "", "classes": []})["classes"].append(cls)
    return sorted(models.values(), key=lambda m: m["file"].lower()), list(nodes.values()), sorted(set(unknown))


def _add_requirements(name: str, files: dict[str, object]) -> None:
    manifest = files.get("manifest.json")
    if not isinstance(manifest, dict):
        return
    graphs = [c for rel, c in files.items() if rel.startswith("workflows/") and isinstance(c, dict)]
    graphs += [c["workflow"] for rel, c in files.items()
               if rel.startswith("engines/") and isinstance(c, dict) and isinstance(c.get("workflow"), dict)]
    if not graphs:
        return
    models, nodes, unknown = requirements_for(graphs)
    requires = manifest.setdefault("requires", {})
    if models:
        requires["models"] = models
    if nodes:
        requires["comfy_nodes"] = nodes
    if unknown:
        print(f"  {name}: not in the models catalog (no download address): {', '.join(unknown)}")


# Default model file swaps, applied to every package on its way out (#11).
# FLUX.2 Klein 9B FP8 is gated on Hugging Face (accept its license + token in
# Settings) — the INT8 build is not, so it is what a graph loads until the
# user picks another quantization. FP8 stays available as an option.
DEFAULT_MODEL_SWAPS = {
    "flux-2-klein-9b-fp8.safetensors": "flux-2-klein-9b-int8-convrot.safetensors",
}


def _swapped_model(value: object) -> object:
    if not isinstance(value, str):
        return value
    base = re.split(r"[\\/]", value)[-1]
    new = DEFAULT_MODEL_SWAPS.get(base)
    return value[:len(value) - len(base)] + new if new else value


def _swap_default_models(files: dict[str, object]) -> None:
    """Loader values and engine defaults only — never the quantization
    options or the downloads list, which must keep offering the FP8 file."""
    def graph(g: dict) -> None:
        for node in g.values():
            inputs = node.get("inputs") if isinstance(node, dict) else None
            if isinstance(inputs, dict):
                for key, value in inputs.items():
                    inputs[key] = _swapped_model(value)

    for rel, content in files.items():
        if not isinstance(content, dict):
            continue
        if rel.startswith("workflows/"):
            graph(content)
        elif rel.startswith("engines/"):
            if isinstance(content.get("workflow"), dict):
                graph(content["workflow"])
            for key in ("basicValues", "advancedValues"):
                values = content.get(key)
                if isinstance(values, dict):
                    for k, v in values.items():
                        values[k] = _swapped_model(v)
            for param in (content.get("analysis") or {}).get("advancedParameters") or []:
                if isinstance(param, dict) and "value" in param:
                    param["value"] = _swapped_model(param["value"])


# Free packs that ship inside the app ("Included" on the marketplace page).
# Their builders still say dest=DIST_OPTIONAL; write_zip routes them to DIST.
# Krea2 Roma, CivitAI and Fan Styles stay free downloads. The Cinematic
# template pack comes from NomadStudioPacks — build_portable.py adds it.
INCLUDED_FREE = {
    "nomad.core-refine",
    "nomad.refine-extract",
    "nomad.refine-presets-core",
    "nomad.styles-free",
}


def write_zip(name: str, files: dict[str, object], dest: Path = DIST) -> Path:
    if name in INCLUDED_FREE:
        dest = DIST
    for other in {DIST, DIST_OPTIONAL} - {dest}:
        (other / f"{name}.zip").unlink(missing_ok=True)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{name}.zip"
    path.unlink(missing_ok=True)
    _swap_default_models(files)
    _add_requirements(name, files)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, content in files.items():
            if isinstance(content, (str, bytes)):
                data = content
            else:
                data = json.dumps(content, indent=2, ensure_ascii=False)
            zf.writestr(rel, data)
    return path


def validate(path: Path) -> dict:
    return package_service.inspect_zip(path, package_service._empty_index(), builtin_flow_ids=set())


# ── Qwen Image 2.1 (hand-authored, no OPENHIKER source — see build_qwen_image_21_engine) ──
# Reverse-engineered from a generated PNG's embedded ComfyUI metadata (no
# import_registry.json record exists for this yet, it's genuinely new):
# UNETLoader qwen_image_2.1_int8_convrot.safetensors, CLIPLoader
# qwen3vl_8b_int8_convrot.safetensors, VAELoader qwen_image_2.1_vae_bf16.safetensors,
# TextEncodeQwenImage21 (one node, outputs BOTH positive[0] and negative[1] —
# replaces the old pair of TextEncodeQwenImageEditPlus nodes), 25 steps/CFG 1/
# euler/simple — the settings that actually produced the verified-good
# outputs; the old Lightning LoRA is 2511-specific and dropped rather than
# guessed as compatible.
# Precisions every Qwen Image 2.1 graph offers in Advanced (Comfy-Org/
# Qwen-Image-2.1): each swaps the diffusion model AND its text encoder.
# Bare filenames, no subfolder — confirmed against the connected ComfyUI's
# own UNETLoader object_info (a made-up subfolder prefix here caused "node
# errors: 55": the quantization switcher would swap in a unet_name that
# doesn't exist). INT8 first = the default; the Advanced panel disables the
# ones ComfyUI doesn't have (flow-quantization.js).
QWEN_IMAGE_21_QUANTIZATION = {
    "int8": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors",
             "clip_name": "qwen3vl_8b_int8_convrot.safetensors"},
    "bf16": {"unet_name": "qwen_image_2.1_bf16.safetensors",
             "clip_name": "qwen3vl_8b_bf16.safetensors", "label": "BF16"},
}


def _qwen_image_21_config_node(**extra) -> dict:
    return {
        "inputs": {"value": json.dumps({**extra, "quantization": QWEN_IMAGE_21_QUANTIZATION})},
        "class_type": "PrimitiveStringMultiline",
        "_meta": {"title": "config"},
    }


def _qwen_image_21_workflow() -> dict:
    return {
        # No download URLs here: the models catalog says where each file
        # lives (PACKAGE_FORMAT.md §8.2 / D15).
        "config": _qwen_image_21_config_node(name="Qwen Image 2.1", downloads=""),
        "29": {
            "inputs": {"filename_prefix": "qwen-image-2.1-create-simple", "images": ["54", 0]},
            "class_type": "SaveImage",
            "_meta": {"title": "Save Image"},
        },
        "51": {
            "inputs": {
                "prompt": "a small red fox sitting in snow, studio photo",
                "negative_prompt": "text, watermark, signature, logo, blurry, jpeg artifacts, lowres, worst quality, low quality, deformed hands, extra fingers",
                # 0 = no reference images to resize (pure text-to-image, no
                # `images` input wired) — a nonzero value here reportedly
                # triggered the txt_in RMSNorm shape mismatch (3584 vs 4096)
                # even with zero images connected. Confirmed fixed by testing.
                "resolution": 0,
                "clip": ["56", 0],
                "vae": ["57", 0],
            },
            "class_type": "TextEncodeQwenImage21",
            "_meta": {"title": "Text Encode Qwen Image 2.1"},
        },
        "53": {
            "inputs": {
                "seed": 1166088861, "steps": 25, "cfg": 1, "sampler_name": "euler", "scheduler": "simple",
                "denoise": 1, "model": ["55", 0], "positive": ["51", 0], "negative": ["51", 1],
                "latent_image": ["71", 0],
            },
            "class_type": "KSampler",
            "_meta": {"title": "KSampler"},
        },
        "54": {
            "inputs": {"samples": ["53", 0], "vae": ["57", 0]},
            "class_type": "VAEDecode",
            "_meta": {"title": "VAE Decode"},
        },
        "55": {
            "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"},
            "class_type": "UNETLoader",
            "_meta": {"title": "Load Diffusion Model"},
        },
        "56": {
            "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"},
            "class_type": "CLIPLoader",
            "_meta": {"title": "Load CLIP"},
        },
        "57": {
            "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"},
            "class_type": "VAELoader",
            "_meta": {"title": "Load VAE"},
        },
        "71": {
            "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
            "class_type": "EmptySD3LatentImage",
            "_meta": {"title": "EmptySD3LatentImage"},
        },
    }


# ── Qwen 2.1 Edit (replaces refine_qwen_2511_edit.json, the shared engine
# behind Edit Qwen 2.1/Outpaint/Look Book/every Photo Editing-Portrait
# Fix-Creator Pack flow's engine_select) ────────────────────────────────────
# Single reference image via TextEncodeQwenImage21's Autogrow "images.image_1"
# input (dotted key — confirmed against a real generated PNG's embedded
# metadata) instead of the old VAEEncode+ReferenceLatent chain: 2.1 handles
# image conditioning inside the encode node itself. Output latent now comes
# from GetImageSize(source image) -> EmptyLatentImage, so the result keeps
# the input's own resolution the same way the old ReferenceLatent path did.
QWEN_2511_EDIT_WORKFLOW_REL = "workflows/refine/refine_qwen_2511_edit.json"


# ── Extract (Qwen 2.1) — new flow, no OPENHIKER source. Reuses the shared
# Edit Qwen 2.1 graph verbatim (QWEN_2511_EDIT_WORKFLOW_REL, already migrated
# — same node ids as every other Edit-engine flow: 13=TextEncodeQwenImage21,
# 15=KSampler), just with a different default/preset prompts aimed at
# isolating a subject/product/character as a transparent RGBA cutout instead
# of general scene editing. Preset wording supplied by the user, each one
# already wraps the "RGBA image with transparency / alpha channel" phrasing
# Qwen Image 2.1 needs to actually output an alpha channel (confirmed via
# the model's own usage notes) — nothing else has to force transparency.
EXTRACT_SUBJECT_PRESETS = [
    {
        "label": "General subject",
        "text": "Extract the main subject from this image as a clean RGBA image with transparency. "
                "Preserve the subject's full appearance, original colors, fine edges, hair, fur, small "
                "details, and semi-transparent regions. Remove the entire background. The image has an "
                "alpha channel and the background is transparent.",
    },
    {
        "label": "Product",
        "text": "Isolate the main product from this image and return it as a clean RGBA asset with "
                "transparency. Preserve its exact silhouette, materials, colors, branding, reflections, "
                "fine edges, and structural details. Remove the entire background while keeping the "
                "product intact. The image has an alpha channel and the background is transparent.",
    },
    {
        "label": "Character / person",
        "text": "Extract the person or character from this image as a clean transparent RGBA asset. "
                "Preserve identity, hairstyle, clothing, body silhouette, fine hair strands, soft edges, "
                "and all visible details. Remove the background completely. The image has an alpha "
                "channel and the background is transparent.",
    },
]


def _extract_qwen2_flow() -> dict:
    return {
        "id": "refine.extract_qwen2",
        "label": "Extract (Qwen 2.1)",
        "category": "refine",
        "group": "extract",
        "description": "Extract the subject, product or character from a photo as a clean RGBA cutout with transparency, using Qwen Image 2.1.",
        "card_desc": "Clean transparent-background cutouts — subject, product or character — with Qwen Image 2.1.",
        "card_tags": ["Qwen", "2.1", "Extract", "RGBA"],
        "card_css_modifier": "edit-qwen-2511",
        "llm_required": False,
        "comfyui_required": True,
        "steps": [
            {"id": "image", "type": "image_picker", "label": "Source image", "required": True},
            {
                "id": "params",
                "type": "workflow_params",
                "label": "Parameters",
                "workflow_file": QWEN_2511_EDIT_WORKFLOW_REL,
                "image_node": "7",
                "fields": [
                    {
                        "id": "prompt",
                        "adv_key": "13.prompt",
                        "label": "Extract prompt",
                        "type": "textarea",
                        "rows": 4,
                        "block": True,
                        "tooltip": "Pick what to extract, or write your own.",
                        "default": EXTRACT_SUBJECT_PRESETS[0]["text"],
                        "presets": EXTRACT_SUBJECT_PRESETS,
                    },
                    {
                        "id": "steps", "adv_key": "15.steps", "label": "Steps", "type": "number",
                        "default": 25, "min": 1, "max": 25, "step": 1, "quick_options": [8, 16, 25], "advanced": True,
                    },
                    {"id": "seed", "adv_key": "15.seed", "label": "Seed", "type": "seed", "advanced": True},
                ],
            },
            {
                "id": "generate",
                "type": "action",
                "label": "Generate",
                "calls": "generation.submit_refine",
                "input_map": {
                    "workflowFile": "steps.params.output.workflow_file",
                    "imageDataUrl": "steps.image.output.image_data_url",
                    "advancedValues": "steps.params.output.adv_values",
                },
            },
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Refine",
        "entry_model": "Qwen Image 2.1 Edit",
    }


# ── Edit RGBA Asset (Qwen 2.1) — companion to Extract: edits an image that
# is ALREADY transparent (a cutout Extract produced, or any RGBA asset)
# without destroying or refilling the existing alpha. Same shared Edit
# Qwen 2.1 graph, different preset wording — these presets keep the
# [BRACKETED] placeholders the user supplied verbatim (picking a preset
# fills the textarea so the user edits the placeholder text directly,
# same interaction Look Book's free-text presets already use).
#
# "Generic edit" shortened after hand-testing: the original longer wording
# ("Modify only X. Keep the subject's position, proportions, silhouette...")
# made Qwen 2.1 ignore the actual instruction — too many competing
# constraints. The short "Preserve ... alpha channel. [CHANGE]." form
# confirmed working (e.g. "...alpha channel of the input image. show the
# back of the eagle.").
EDIT_RGBA_PRESETS = [
    {
        "label": "Generic edit",
        "text": "Preserve the transparent canvas and alpha channel of the input image. [REQUESTED CHANGE]",
    },
    {
        "label": "Color / material",
        "text": "Preserve the existing transparency and alpha boundaries. Change only [OBJECT OR AREA] to "
                "[COLOR / MATERIAL]. Keep the original shape, placement, proportions, lighting logic, and "
                "all transparent regions unchanged.",
    },
    {
        "label": "Character asset",
        "text": "Preserve the transparent background and alpha channel. Edit only [REQUESTED CHARACTER "
                "CHANGE] while maintaining the character's identity, pose, proportions, silhouette, "
                "clothing structure, and clean transparent edges.",
    },
]


def _edit_rgba_qwen2_flow() -> dict:
    return {
        "id": "refine.edit_rgba_qwen2",
        "label": "Edit RGBA Asset",
        "category": "refine",
        "group": "extract",
        "description": "Edit an already-transparent RGBA image without destroying or refilling the existing alpha channel, using Qwen Image 2.1.",
        "card_desc": "Modify a transparent cutout — color, material or detail — while keeping its alpha intact.",
        "card_tags": ["Qwen", "2.1", "RGBA", "Edit"],
        "card_css_modifier": "edit-qwen-2511",
        "llm_required": False,
        "comfyui_required": True,
        "steps": [
            {"id": "image", "type": "image_picker", "label": "RGBA source image", "required": True},
            {
                "id": "params",
                "type": "workflow_params",
                "label": "Parameters",
                "workflow_file": QWEN_2511_EDIT_WORKFLOW_REL,
                "image_node": "7",
                "fields": [
                    {
                        "id": "prompt",
                        "adv_key": "13.prompt",
                        "label": "Edit prompt",
                        "type": "textarea",
                        "rows": 4,
                        "block": True,
                        "tooltip": "Pick a template and fill in the bracketed part, or write your own.",
                        "default": EDIT_RGBA_PRESETS[0]["text"],
                        "presets": EDIT_RGBA_PRESETS,
                    },
                    {
                        "id": "steps", "adv_key": "15.steps", "label": "Steps", "type": "number",
                        "default": 25, "min": 1, "max": 25, "step": 1, "quick_options": [8, 16, 25], "advanced": True,
                    },
                    {"id": "seed", "adv_key": "15.seed", "label": "Seed", "type": "seed", "advanced": True},
                ],
            },
            {
                "id": "generate",
                "type": "action",
                "label": "Generate",
                "calls": "generation.submit_refine",
                "input_map": {
                    "workflowFile": "steps.params.output.workflow_file",
                    "imageDataUrl": "steps.image.output.image_data_url",
                    "advancedValues": "steps.params.output.adv_values",
                },
            },
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Refine",
        "entry_model": "Qwen Image 2.1 Edit",
    }


# ── Local Editing: Region Selection (Qwen 2.1) — new flow, no OPENHIKER
# source. Inserts the new `region_annotate` step (app/static/js/pages/flow/
# flow-step-region-annotate.js) between image_picker and workflow_params:
# the user paints colored freehand strokes over the source image, and the
# FLATTENED annotated image (not the raw source) is what gets sent as
# imageDataUrl — same shared Edit Qwen 2.1 graph and node ids as every
# other Edit-engine flow, no backend change needed (flattening happens
# client-side via canvas.toDataURL()).
def _local_edit_qwen2_flow() -> dict:
    return {
        "id": "refine.local_edit_qwen2",
        "label": "Local Editing: Region Selection",
        "_i18n_overrides": {
            "label": {
                "en": "Local Editing: Region Selection", "es": "Edición local: selección de región",
                "zh": "局部编辑：区域选择", "ko": "로컬 편집: 영역 선택",
            },
            "desc": {
                "en": "Mark regions by color, then tell Qwen 2.1 what to change in each one.",
                "es": "Marca regiones por color y dile a Qwen 2.1 qué cambiar en cada una.",
                "zh": "按颜色标记区域，然后告诉 Qwen 2.1 每个区域要改什么。",
                "ko": "색상으로 영역을 표시한 뒤 각 영역에서 무엇을 바꿀지 Qwen 2.1에게 알려주세요.",
            },
        },
        "category": "refine",
        "group": "photo-editing",
        "description": "Paint colored circles or scribbles over specific regions of a photo, then describe what to change in each one by color — powered by Qwen Image 2.1's native region-aware editing.",
        "card_desc": "Mark regions by color, then tell Qwen 2.1 what to change in each one.",
        "card_tags": ["Qwen", "2.1", "Local Edit", "Region"],
        "card_css_modifier": "edit-qwen-2511",
        "llm_required": False,
        "comfyui_required": True,
        "steps": [
            {"id": "image", "type": "image_picker", "label": "Source image", "required": True},
            {
                "id": "annotate",
                "type": "region_annotate",
                "label": "Mark regions",
                "image_step": "image",
            },
            {
                "id": "params",
                "type": "workflow_params",
                "label": "Parameters",
                "workflow_file": QWEN_2511_EDIT_WORKFLOW_REL,
                "image_node": "7",
                "fields": [
                    {
                        "id": "prompt",
                        "adv_key": "13.prompt",
                        "label": "Edit prompt",
                        "type": "textarea",
                        "rows": 4,
                        "block": True,
                        "tooltip": "Reference the colors you painted, e.g. \"remove the object in the blue circle, change the hair in the red circle to black\".",
                        "default": "Remove the object in the blue circle, and change the hair in the red circle to black.",
                    },
                    {
                        "id": "steps", "adv_key": "15.steps", "label": "Steps", "type": "number",
                        "default": 25, "min": 1, "max": 25, "step": 1, "quick_options": [8, 16, 25], "advanced": True,
                    },
                    {"id": "seed", "adv_key": "15.seed", "label": "Seed", "type": "seed", "advanced": True},
                ],
            },
            {
                "id": "generate",
                "type": "action",
                "label": "Generate",
                "calls": "generation.submit_refine",
                "input_map": {
                    "workflowFile": "steps.params.output.workflow_file",
                    "imageDataUrl": "steps.annotate.output.annotated_image_data_url",
                    "advancedValues": "steps.params.output.adv_values",
                },
            },
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Refine",
        "entry_model": "Qwen Image 2.1 Edit",
    }


# ── Text Editor in Image — same region_annotate + flatten-then-edit pattern
# as Local Editing above, just defaulted to rectangle mode (text sits in
# rectangular blocks, not blobs a freehand loop suits) and with a preset
# aimed at text replacement instead of a generic region edit. Marking the
# rectangle IS the "which text" input — no separate "old text" field needed,
# unlike the original template idea, so the prompt only needs the new text
# filled into the bracket. Two engine variants, same as Background Swap, so
# they can be compared directly.
TEXT_EDITOR_PRESETS = [
    {
        "label": "Replace text",
        "text": "Replace the text inside the red rectangle with \"[NEW TEXT]\". Keep font style, color, size, "
                "and placement consistent with the original.",
    },
    {
        "label": "Add text",
        "text": "Add the text \"[NEW TEXT]\" inside the red rectangle, where there is no text yet. Style it to "
                "naturally match the scene — matching perspective, lighting, and the surface it sits on.",
    },
]


def _text_editor_qwen2_flow() -> dict:
    return {
        "id": "refine.text_editor_qwen2",
        "label": "Text Editor in Image — Qwen 2.1",
        "_i18n_overrides": {
            "label": {
                "en": "Text Editor in Image — Qwen 2.1", "es": "Editor de texto en imagen — Qwen 2.1",
                "zh": "图像文字编辑 — Qwen 2.1", "ko": "이미지 텍스트 편집 — Qwen 2.1",
            },
            "desc": {
                "en": "Mark the text with a rectangle and replace it, keeping the original font, color and placement.",
                "es": "Marca el texto con un rectángulo y reemplázalo, conservando fuente, color y posición.",
                "zh": "用矩形标记文字并替换，保留原有字体、颜色和位置。",
                "ko": "사각형으로 텍스트를 표시하고 교체 — 원래 글꼴, 색상, 배치는 유지합니다.",
            },
        },
        "category": "refine",
        "group": "photo-editing",
        "description": "Mark the text you want to change with a rectangle, then replace it — keeping font, "
                        "color, size and placement — using Qwen Image 2.1.",
        "card_desc": "Mark the text with a rectangle and replace it, keeping the original font, color and placement.",
        "card_tags": ["Qwen", "2.1", "Text", "Edit"],
        "card_css_modifier": "edit-qwen-2511",
        "llm_required": False,
        "comfyui_required": True,
        "steps": [
            {"id": "image", "type": "image_picker", "label": "Source image", "required": True},
            {
                "id": "annotate",
                "type": "region_annotate",
                "label": "Mark the text",
                "image_step": "image",
                "shape_mode": "rectangle",
                "hint": "Draw a rectangle around the text you want to replace.",
            },
            {
                "id": "params",
                "type": "workflow_params",
                "label": "Parameters",
                "workflow_file": QWEN_2511_EDIT_WORKFLOW_REL,
                "image_node": "7",
                "fields": [
                    {
                        "id": "prompt",
                        "adv_key": "13.prompt",
                        "label": "Edit prompt",
                        "type": "textarea",
                        "rows": 4,
                        "block": True,
                        "tooltip": "Fill in the bracketed part with the new text, or write your own instruction.",
                        "default": TEXT_EDITOR_PRESETS[0]["text"],
                        "presets": TEXT_EDITOR_PRESETS,
                    },
                    {
                        "id": "steps", "adv_key": "15.steps", "label": "Steps", "type": "number",
                        "default": 25, "min": 1, "max": 25, "step": 1, "quick_options": [8, 16, 25], "advanced": True,
                    },
                    {"id": "seed", "adv_key": "15.seed", "label": "Seed", "type": "seed", "advanced": True},
                ],
            },
            {
                "id": "generate",
                "type": "action",
                "label": "Generate",
                "calls": "generation.submit_refine",
                "input_map": {
                    "workflowFile": "steps.params.output.workflow_file",
                    "imageDataUrl": "steps.annotate.output.annotated_image_data_url",
                    "advancedValues": "steps.params.output.adv_values",
                },
            },
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Refine",
        "entry_model": "Qwen Image 2.1 Edit",
    }


def _text_editor_klein9b_flow() -> dict:
    return {
        "id": "refine.text_editor_klein9b",
        "label": "Text Editor in Image — Klein 9B",
        "_i18n_overrides": {
            "label": {
                "en": "Text Editor in Image — Klein 9B", "es": "Editor de texto en imagen — Klein 9B",
                "zh": "图像文字编辑 — Klein 9B", "ko": "이미지 텍스트 편집 — Klein 9B",
            },
            "desc": {
                "en": "Mark the text with a rectangle and replace it, keeping the original font, color and placement.",
                "es": "Marca el texto con un rectángulo y reemplázalo, conservando fuente, color y posición.",
                "zh": "用矩形标记文字并替换，保留原有字体、颜色和位置。",
                "ko": "사각형으로 텍스트를 표시하고 교체 — 원래 글꼴, 색상, 배치는 유지합니다.",
            },
        },
        "category": "refine",
        "group": "photo-editing",
        "description": "Mark the text you want to change with a rectangle, then replace it — keeping font, "
                        "color, size and placement — using Flux 2 Klein 9B.",
        "card_desc": "Mark the text with a rectangle and replace it, keeping the original font, color and placement.",
        "card_tags": ["Klein", "9B", "Text", "Edit"],
        "card_css_modifier": "edit-fluxklein",
        "llm_required": False,
        "comfyui_required": True,
        "steps": [
            {"id": "image", "type": "image_picker", "label": "Source image", "required": True},
            {
                "id": "annotate",
                "type": "region_annotate",
                "label": "Mark the text",
                "image_step": "image",
                "shape_mode": "rectangle",
                "hint": "Draw a rectangle around the text you want to replace.",
            },
            {
                "id": "params",
                "type": "workflow_params",
                "label": "Parameters",
                "workflow_file": "workflows/refine/refine_flux2_klein_9b.json",
                "image_node": "76",
                "fields": [
                    {
                        "id": "prompt",
                        "adv_key": "139.text",
                        "label": "Edit prompt",
                        "type": "textarea",
                        "rows": 4,
                        "block": True,
                        "tooltip": "Fill in the bracketed part with the new text, or write your own instruction.",
                        "default": TEXT_EDITOR_PRESETS[0]["text"],
                        "presets": TEXT_EDITOR_PRESETS,
                    },
                    {
                        "id": "steps", "adv_key": "132.steps", "label": "Steps", "type": "number",
                        "default": 4, "min": 1, "max": 40, "step": 1, "quick_options": [4, 8], "advanced": True,
                    },
                    {
                        "id": "cfg", "adv_key": "133.cfg", "label": "CFG", "type": "number",
                        "default": 1, "min": 0, "max": 10, "step": 0.5, "advanced": True,
                    },
                    {"id": "seed", "adv_key": "136.noise_seed", "label": "Seed", "type": "seed", "advanced": True},
                ],
            },
            {
                "id": "generate",
                "type": "action",
                "label": "Generate",
                "calls": "generation.submit_refine",
                "input_map": {
                    "workflowFile": "steps.params.output.workflow_file",
                    "imageDataUrl": "steps.annotate.output.annotated_image_data_url",
                    "advancedValues": "steps.params.output.adv_values",
                },
            },
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Refine",
        "entry_model": "Flux 2 Klein",
    }


def _qwen_image_21_edit_workflow() -> dict:
    return {
        "config": _qwen_image_21_config_node(),
        "2": {
            "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"},
            "class_type": "VAELoader",
            "_meta": {"title": "Load VAE"},
        },
        "3": {
            "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"},
            "class_type": "CLIPLoader",
            "_meta": {"title": "Load CLIP"},
        },
        "6": {
            "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"},
            "class_type": "UNETLoader",
            "_meta": {"title": "Load Diffusion Model"},
        },
        "7": {
            "inputs": {"image": "oj-refine-placeholder.png"},
            "class_type": "LoadImage",
            "_meta": {"title": "Load Image"},
        },
        "13": {
            "inputs": {
                "prompt": "change the background to a sunset beach",
                "negative_prompt": "",
                "resolution": 0,
                "clip": ["3", 0],
                "vae": ["2", 0],
                "images.image_1": ["7", 0],
            },
            "class_type": "TextEncodeQwenImage21",
            "_meta": {"title": "Text Encode Qwen Image 2.1"},
        },
        "15": {
            "inputs": {
                "seed": 796693962184957, "steps": 25, "cfg": 1, "sampler_name": "euler", "scheduler": "simple",
                "denoise": 1, "model": ["6", 0], "positive": ["13", 0], "negative": ["13", 1],
                "latent_image": ["25", 0],
            },
            "class_type": "KSampler",
            "_meta": {"title": "KSampler"},
        },
        "17": {
            "inputs": {"samples": ["15", 0], "vae": ["2", 0]},
            "class_type": "VAEDecode",
            "_meta": {"title": "VAE Decode"},
        },
        "21": {
            "inputs": {"filename_prefix": "qwen-image-2.1-edit", "images": ["17", 0]},
            "class_type": "SaveImage",
            "_meta": {"title": "Save Image"},
        },
        "24": {
            "inputs": {"image": ["7", 0]},
            "class_type": "GetImageSize",
            "_meta": {"title": "Get Image Size"},
        },
        "25": {
            "inputs": {"width": ["24", 0], "height": ["24", 1], "batch_size": 1},
            "class_type": "EmptyLatentImage",
            "_meta": {"title": "Empty Latent Image"},
        },
    }


# ── Multi-Reference Compose (Mix, Qwen 2.1) — new graph, no OPENHIKER
# source. Same loaders/sampler/decode as the single-image Edit graph above,
# but TextEncodeQwenImage21 gets up to 4 "images.image_N" Autogrow keys
# instead of 1 — its multi-image conditioning is confirmed to work this way
# from real generated-PNG metadata (see _qwen_image_21_edit_workflow's
# comment), just never exercised past a single slot until now. Node 7
# stays the primary/subject reference; 8/9/10 are the secondary/tertiary/
# quaternary references. Unfilled optional slots (3rd/4th) get a neutral
# gray placeholder uploaded by prepare_mix_workflow's
# _neutral_placeholder_png() — same mechanism already used for Clothes
# Mix's optional reference photo, so an unused slot here is a
# known-working no-op rather than new risk.
#
# Output canvas: unlike single-image Edit flows (where GetImageSize(source)
# -> EmptyLatentImage makes sense — you're editing THAT image), combining
# 2-4 references with different aspect ratios has no one "right" source to
# inherit size from. Node 25 gets a literal default (1024x1024, same
# default the base engine already uses) instead of GetImageSize(7) — the
# flow's own `aspect_ratio` field (see _multi_reference_compose_flow)
# always overrides it via advancedValues at generation time; the literal
# default only matters as a fallback if that field somehow doesn't fire.
MIX_MULTI_REFERENCE_WORKFLOW_REL = "workflows/mix/multi_reference_compose_qwen21.json"


def _qwen_image_21_multi_reference_workflow() -> dict:
    graph = _qwen_image_21_edit_workflow()
    for node_id, filename in (("8", "oj-mix-placeholder-2.png"),
                               ("9", "oj-mix-placeholder-3.png"),
                               ("10", "oj-mix-placeholder-4.png")):
        graph[node_id] = {
            "inputs": {"image": filename},
            "class_type": "LoadImage",
            "_meta": {"title": "Load Image"},
        }
    graph["13"]["inputs"]["images.image_2"] = ["8", 0]
    graph["13"]["inputs"]["images.image_3"] = ["9", 0]
    graph["13"]["inputs"]["images.image_4"] = ["10", 0]
    graph["21"]["inputs"]["filename_prefix"] = "qwen-image-2.1-multi-ref"
    del graph["24"]  # GetImageSize — no longer referenced, see comment above
    graph["25"]["inputs"] = {"width": 1024, "height": 1024, "batch_size": 1}
    return graph


# Prompt wording supplied verbatim by the user — each already frames the
# <image1>/<image2>/... role convention TextEncodeQwenImage21 expects, so
# no rewriting needed, only picking a default and giving each a short label.
MULTI_REFERENCE_COMPOSE_PRESETS = [
    {
        "label": "General composition",
        "text": "Use <image1> as the main subject reference and <image2> as the secondary reference. "
                "Combine the important visual information from both images into one coherent final image. "
                "Preserve the recognizable identity and key details of the subject from <image1> while "
                "integrating the relevant elements from <image2> naturally. Match perspective, scale, "
                "lighting, color harmony, and scene coherence.",
    },
    {
        "label": "Structured role-based mix",
        "text": "Use <image1> as the subject reference. Use <image2> as the style, object, clothing, or "
                "environment reference. Create a single unified image that preserves the subject identity "
                "from <image1> while incorporating the requested features from <image2>. Avoid a collage "
                "look and ensure the final scene feels naturally constructed.",
    },
    {
        "label": "Extendable multi-input",
        "text": "Use <image1> as the primary subject reference. Use <image2> as the secondary reference. "
                "If additional images are provided, use them as supporting references for style, objects, "
                "clothing, environment, or composition. Blend all references into one coherent final image "
                "with consistent lighting, scale, perspective, and visual logic.",
    },
]


# Shared vision system prompt for the per-image "What's in this image?"
# optional field (subject_input + subject_vision_assist, same mechanism
# Photo Session uses) — one short sentence, phrased generically since any
# of the 4 slots could end up holding a subject, a style reference, an
# object, or an environment shot.
_MULTI_REF_VISION_SYSTEM_PROMPT = (
    "Describe this reference image in one concise sentence — what it shows and any visual "
    "details (subject, colors, clothing, style, objects, setting) that would matter for "
    "combining it with other images into one final composition. Output only the sentence."
)

# System prompt for the "idea -> full composition prompt" AI-assist step.
# Style is deliberately terse/anchored (matched to the user's own reference
# examples: "The girl in Image 1 wears the necklace from Image 2 and
# carries the bag from Image 3") rather than the long descriptive
# paragraphs Create's Assist produces — a multi-reference prompt needs to
# stay unambiguous about which image plays which role, not evocative.
MULTI_REF_COMPOSE_SYSTEM_PROMPT = (
    "You are a prompt writer for an AI image model that combines 2-4 reference images into one "
    "final image. The user will give you a rough idea of what they want, and optionally short "
    "descriptions of what each reference image shows (labeled 'Image 1:', 'Image 2:', etc. — only "
    "as many as were provided).\n\n"
    "Write a short, concrete instruction that assigns each image mentioned in the idea a clear "
    "role, referring to it as Image 1, Image 2, Image 3, Image 4 (matching the image numbers "
    "given, written as two plain words — the word \"Image\", a space, then the digit — no brackets, "
    "no punctuation between them). Follow this exact style — short declarative sentences anchored "
    "to an image number, e.g. \"The subject in Image 1 wears the jacket from Image 2 and stands in "
    "the setting from Image 3.\" or \"Use Image 1 as the main subject and Image 2 as the style "
    "reference.\"\n\n"
    "Rules:\n"
    "- EVERY reference image mentioned MUST carry its \"Image N\" label exactly as described above "
    "— never replace it with just \"the circle\"/\"the image\"/\"it\", never drop it, never "
    "paraphrase it away. This is the single most important rule.\n"
    "- Only reference image numbers that were actually mentioned or described — never invent a "
    "5th image or reference one that has no idea/description behind it.\n"
    "- Keep it to 1-3 sentences. No preamble, no explanation, no quotes — output only the "
    "instruction itself.\n"
    "- If the idea is vague about a role, infer the most sensible one from the image descriptions."
)


def _multi_ref_image_step(step_id: str, label: str, required: bool, hint: str | None = None,
                           vision: bool = True) -> dict:
    """Shared image_picker builder for all 3 multi-reference flows. `vision=True`
    adds the "what's in this image?" text field + inline vision-assist button
    (Multi-Reference Compose only — the Quick and MultiComposer flows don't
    need it, they don't have an AI prompt-composer step to feed context to)."""
    step: dict = {"id": step_id, "type": "image_picker", "label": label, "required": required}
    if vision:
        step["subject_input"] = True
        step["subject_label"] = "What's in this image? (optional)"
        step["subject_placeholder"] = "e.g. woman in a red coat, gold necklace, beach at sunset…"
        step["subject_vision_assist"] = {"system_prompt": _MULTI_REF_VISION_SYSTEM_PROMPT}
    if not required:
        step["optional"] = True
    if hint:
        step["hint"] = hint
    return step


def _multi_reference_compose_flow() -> dict:
    _ref_image_step = _multi_ref_image_step
    return {
        "id": "mix.multi_reference_compose",
        "label": "Multi-Reference Compose",
        "category": "mix",
        "description": "Combine 2-4 reference images into one coherent final image, assigning each a clear "
                        "role (subject, style, object, clothing, environment) with Qwen Image 2.1.",
        "card_desc": "Combine multiple references — subject, style, object, environment — into one coherent image.",
        "card_tags": ["Qwen", "2.1", "Mix", "Compose"],
        "card_css_modifier": "mix-compose",
        "llm_required": False,
        "comfyui_required": True,
        "steps": [
            _ref_image_step(
                "image", "Background (optional)", False,
                "Optional — leave empty to compose purely from the reference images and your prompt, or add "
                "a real background photo to place them into.",
            ),
            _ref_image_step("image_2", "Main subject reference", True),
            _ref_image_step(
                "image_3", "Additional reference (optional)", False,
                "Optional — add a 3rd reference (style, object, environment) if the prompt needs it.",
            ),
            _ref_image_step(
                "image_4", "Additional reference (optional)", False,
                "Optional — add a 4th reference if the prompt needs it.",
            ),
            {
                "id": "idea",
                "type": "prompt_input",
                "label": "Your idea (optional)",
                "required": False,
                "placeholder": "A rough idea is enough — e.g. \"put the person from image 1 in the jacket "
                               "from image 2\". Combine with the image descriptions above for best results.",
                "rows": 3,
            },
            {
                "id": "compose",
                "type": "llm_transform",
                "label": "Compose prompt with AI",
                "calls": "llm.studio_enhance",
                "input_from": "steps.idea.output.prompt_text",
                "context_from": {
                    "reference_prompt": [
                        {"label": "Image 1", "ref": "steps.image.output.subject"},
                        {"label": "Image 2", "ref": "steps.image_2.output.subject"},
                        {"label": "Image 3", "ref": "steps.image_3.output.subject"},
                        {"label": "Image 4", "ref": "steps.image_4.output.subject"},
                    ],
                },
                # Fixed single "level" (not a user-facing quick/style/scene/master
                # choice like Create's Assist) — just what studio-enhance needs to
                # pick our system_prompts["scene"] entry below.
                "params": {"level": {"type": "user_choice", "options": ["scene"], "default": "scene"}},
                "system_prompts": {"scene": MULTI_REF_COMPOSE_SYSTEM_PROMPT},
                "output_to": "prompt",
                # This local LLM (small models especially) reliably drops or mangles literal
                # "<image1>"-style angle-bracket tags in its output (observed live: Gemma treats
                # them like a control-token pattern and silently strips them) — so the system
                # prompt above asks it for the plain words "Image 1"/"Image 2" instead, and this
                # flag tells runLLM's llm.studio_enhance branch to deterministically convert
                # "Image N" -> "<imageN>" afterwards, client-side, before it reaches the prompt
                # box. Far more reliable than hoping a small model preserves exact punctuation.
                "tag_image_refs": True,
            },
            {
                "id": "prompt",
                "type": "prompt_input",
                "label": "Composition prompt",
                "placeholder": "Reference each image as <image1>, <image2>, <image3>, <image4> and describe "
                               "its role — pick a template, use the AI composer above, or write your own.",
                "default": MULTI_REFERENCE_COMPOSE_PRESETS[0]["text"],
                "presets": MULTI_REFERENCE_COMPOSE_PRESETS,
                "rows": 5,
            },
            {
                "id": "params",
                "type": "workflow_params",
                "label": "Parameters",
                "workflow_file": MIX_MULTI_REFERENCE_WORKFLOW_REL,
                "image_node": "7",
                "fields": [
                    {
                        "id": "aspect_ratio",
                        "type": "aspect_ratio",
                        "label": "Output aspect ratio",
                        "default": "r1x1",
                        "resolution": "md",
                        "adv_keys": {"width": "25.width", "height": "25.height"},
                    },
                    {
                        "id": "steps", "adv_key": "15.steps", "label": "Steps", "type": "number",
                        "default": 25, "min": 1, "max": 25, "step": 1, "quick_options": [8, 16, 25], "advanced": True,
                    },
                    {"id": "seed", "adv_key": "15.seed", "label": "Seed", "type": "seed", "advanced": True},
                ],
            },
            {
                "id": "generate",
                "type": "action",
                "label": "Generate",
                "calls": "generation.submit_mix",
                "input_map": {
                    "workflowFile": "steps.params.output.workflow_file",
                    "images": [
                        {"dataUrl": "steps.image.output.image_data_url", "nodeId": "7", "optional": True},
                        {"dataUrl": "steps.image_2.output.image_data_url", "nodeId": "8"},
                        {"dataUrl": "steps.image_3.output.image_data_url", "nodeId": "9", "optional": True},
                        {"dataUrl": "steps.image_4.output.image_data_url", "nodeId": "10", "optional": True},
                    ],
                    "advancedValues": "steps.params.output.adv_values",
                    "promptKey": "13.prompt",
                    "promptValue": "steps.prompt.output.prompt_text",
                },
            },
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Mix",
        "entry_model": "Qwen Image 2.1 Edit",
    }


# ── Multi-Reference Compose (Quick) — same graph/engine as the flow above,
# no AI: just the deterministic role-picker (Part 3 of that flow's original
# design, split out here so the main flow isn't overloaded with 3 different
# ways to build the same prompt). No vision, no LM Studio dependency.
def _multi_reference_compose_quick_flow() -> dict:
    _ref_image_step = _multi_ref_image_step
    return {
        "id": "mix.multi_reference_compose_quick",
        "label": "Multi-Reference Compose (Quick)",
        "category": "mix",
        "description": "Combine 2-4 reference images into one coherent final image using a quick role picker "
                        "— no AI, no typing, with Qwen Image 2.1.",
        "card_desc": "Combine multiple references fast — pick each image's role from a dropdown, no AI needed.",
        "card_tags": ["Qwen", "2.1", "Mix", "Quick"],
        "card_css_modifier": "mix-compose",
        "llm_required": False,
        "comfyui_required": True,
        "steps": [
            _ref_image_step(
                "image", "Background (optional)", False,
                "Optional — leave empty to compose purely from the reference images and your prompt, or add "
                "a real background photo to place them into.",
                vision=False,
            ),
            _ref_image_step("image_2", "Main subject reference", True, vision=False),
            _ref_image_step(
                "image_3", "Additional reference (optional)", False,
                "Optional — add a 3rd reference (style, object, environment) if the prompt needs it.",
                vision=False,
            ),
            _ref_image_step(
                "image_4", "Additional reference (optional)", False,
                "Optional — add a 4th reference if the prompt needs it.",
                vision=False,
            ),
            {
                "id": "prompt",
                "type": "prompt_input",
                "label": "Composition prompt",
                "placeholder": "Reference each image as <image1>, <image2>, <image3>, <image4> and describe "
                               "its role — pick a template, use the role picker below, or write your own.",
                "default": MULTI_REFERENCE_COMPOSE_PRESETS[0]["text"],
                "presets": MULTI_REFERENCE_COMPOSE_PRESETS,
                "rows": 5,
            },
            {
                "id": "params",
                "type": "workflow_params",
                "label": "Parameters",
                "workflow_file": MIX_MULTI_REFERENCE_WORKFLOW_REL,
                "image_node": "7",
                "fields": [
                    {
                        "id": "aspect_ratio",
                        "type": "aspect_ratio",
                        "label": "Output aspect ratio",
                        "default": "r1x1",
                        "resolution": "md",
                        "adv_keys": {"width": "25.width", "height": "25.height"},
                    },
                    {
                        "id": "role_picker",
                        "type": "compose",
                        "label": "Quick role picker (optional — fills the prompt above instead of typing)",
                        "separator": " ",
                        "groups": [
                            {"id": "image1_role", "label": "Image 1", "template": "Use <image1> as {value}.",
                             "options": ["the background", "the main subject", "the style reference",
                                         "the pose reference"]},
                            {"id": "image2_role", "label": "Image 2", "template": "Use <image2> as {value}.",
                             "options": ["the main subject", "the secondary reference", "the style reference",
                                         "the clothing/object reference", "the environment/background reference"]},
                            {"id": "image3_role", "label": "Image 3", "template": "Use <image3> as {value}.",
                             "options": ["an additional style reference", "the clothing/object reference",
                                         "the environment/background reference", "the pose reference"]},
                            {"id": "image4_role", "label": "Image 4", "template": "Use <image4> as {value}.",
                             "options": ["an additional style reference", "the clothing/object reference",
                                         "the environment/background reference", "the pose reference"]},
                        ],
                    },
                    {
                        "id": "role_picker_preview",
                        "type": "compose_preview",
                        "label": "Picker preview",
                        "target_step": "prompt",
                        "rows": 3,
                    },
                    {
                        "id": "steps", "adv_key": "15.steps", "label": "Steps", "type": "number",
                        "default": 25, "min": 1, "max": 25, "step": 1, "quick_options": [8, 16, 25], "advanced": True,
                    },
                    {"id": "seed", "adv_key": "15.seed", "label": "Seed", "type": "seed", "advanced": True},
                ],
            },
            {
                "id": "generate",
                "type": "action",
                "label": "Generate",
                "calls": "generation.submit_mix",
                "input_map": {
                    "workflowFile": "steps.params.output.workflow_file",
                    "images": [
                        {"dataUrl": "steps.image.output.image_data_url", "nodeId": "7", "optional": True},
                        {"dataUrl": "steps.image_2.output.image_data_url", "nodeId": "8"},
                        {"dataUrl": "steps.image_3.output.image_data_url", "nodeId": "9", "optional": True},
                        {"dataUrl": "steps.image_4.output.image_data_url", "nodeId": "10", "optional": True},
                    ],
                    "advancedValues": "steps.params.output.adv_values",
                    "promptKey": "13.prompt",
                    "promptValue": "steps.prompt.output.prompt_text",
                },
            },
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Mix",
        "entry_model": "Qwen Image 2.1 Edit",
    }


# ── MultiComposer — position-aware compose: a background image gets colored
# RECTANGLE-OUTLINE regions marked on it (region_annotate's new rectangle
# mode), and each additional reference image is assigned one of those colors
# (image_picker's new zone_picker select) — "put the subject from image_2 in
# the red-outlined area". Same free `aspect_ratio` field as the other two
# multi-reference flows (not GetImageSize(background) — tried that first,
# but the model's positioning from the rectangles is already guided/semantic
# rather than an exact pixel mask, so there's no real reason to force the
# output canvas to match the background's own size; every input here,
# background included, is just another reference).
MIX_MULTI_COMPOSER_WORKFLOW_REL = "workflows/mix/multi_composer_qwen21.json"

_ZONE_COLORS = [
    {"value": "red", "label": "Red"}, {"value": "green", "label": "Green"},
    {"value": "blue", "label": "Blue"}, {"value": "yellow", "label": "Yellow"},
    {"value": "purple", "label": "Purple"}, {"value": "orange", "label": "Orange"},
]


def _qwen_image_21_multi_composer_workflow() -> dict:
    graph = _qwen_image_21_multi_reference_workflow()
    graph["21"]["inputs"]["filename_prefix"] = "qwen-image-2.1-multi-composer"
    return graph


# Starting-point templates for use cases the zone/color builder doesn't
# cover well (it only handles "place reference N in the color-N rectangle"
# — these are richer, more specific compositing jobs). {{bracketed}} tokens
# are left for the user to hand-edit — e.g. {{image_list}} becomes
# "<image2>, <image3> and <image4>" once they know how many references
# they actually picked, {{subject_description}} becomes whatever they want
# redrawn in the style. Picking one fills the Composition prompt textarea
# below, same as a regular preset; <imageN> tags used throughout (not the
# word-form "ImageN") to match what the ComfyUI graph actually keys off.
MULTI_COMPOSER_TEMPLATES = [
    {
        "label": "Swap Face",
        "text": "Edit <image1>. Replace the face with the face from <image2>. Preserve <image1>'s hairstyle, "
                "body, pose, clothing, lighting, and background exactly. Match skin tone and lighting to <image1>.",
    },
    {
        "label": "Group Photo Composer",
        "text": "Use the people from {{image_list}}. Combine them into one natural group photo, same scene and "
                "lighting. Preserve each person's face, expression, and proportions exactly.",
    },
    {
        "label": "Outfit Builder",
        "text": "Dress the person from <image1> using {{clothing_items_from_images}}. Preserve <image1>'s face, "
                "pose, and body. Match fabric lighting and scale to the scene.",
    },
    {
        "label": "Product Scene Placer",
        "text": "Use the product from <image1> and the scene from <image2>. Place the product from <image1> "
                "naturally into <image2>, matching scale, lighting, and shadows. Preserve the product's label, "
                "texture, and shape exactly.",
    },
    {
        "label": "Interior/Scene Composer",
        "text": "Use the pieces from {{image_list}}. Arrange them into one coherent interior scene with "
                "consistent lighting and perspective.",
    },
    {
        "label": "Style Transfer",
        "text": "Using the visual style from <image1>, redraw {{subject_description}}. Preserve the color "
                "palette, texture, and rendering technique of <image1>. Do not use <image1>'s content, only "
                "its style.",
    },
]


def _multi_composer_flow() -> dict:
    def _zone_image_step(step_id: str, label: str, required: bool, hint: str | None = None) -> dict:
        step: dict = {
            "id": step_id, "type": "image_picker", "label": label, "required": required,
            "zone_picker": True, "zone_colors": _ZONE_COLORS,
            # Manual description (+ optional vision-assist), same mechanism
            # Multi-Reference Compose uses — was missing here, no way to
            # note "the woman in the blue coat" etc. by hand before compose.
            "subject_input": True,
            "subject_label": "What's in this image? (optional)",
            "subject_placeholder": "e.g. woman in a blue suit, gold necklace…",
            "subject_vision_assist": {"system_prompt": _MULTI_REF_VISION_SYSTEM_PROMPT},
        }
        if not required:
            step["optional"] = True
        if hint:
            step["hint"] = hint
        return step

    return {
        "id": "mix.multi_composer",
        "label": "MultiComposer",
        "category": "mix",
        "description": "Mark colored rectangle zones on a background image, assign a reference image to each "
                        "color, and compose them into that exact spot — with Qwen Image 2.1.",
        "card_desc": "Mark colored zones on a background, drop a reference image into each one.",
        "card_tags": ["Qwen", "2.1", "Mix", "Compose", "Position"],
        "card_css_modifier": "mix-compose",
        "llm_required": False,
        "comfyui_required": True,
        "steps": [
            {"id": "background", "type": "image_picker", "label": "Background", "required": True},
            {
                "id": "annotate",
                "type": "region_annotate",
                "label": "Mark zones",
                "image_step": "background",
                "shape_mode": "rectangle",
                "hint": "Draw a rectangle outline for each spot you want to fill, one color per reference image.",
            },
            _zone_image_step("image_2", "Reference for zone 1", True),
            _zone_image_step("image_3", "Reference for zone 2 (optional)", False,
                              "Optional — add another reference if you marked a 2nd zone."),
            _zone_image_step("image_4", "Reference for zone 3 (optional)", False,
                              "Optional — add another reference if you marked a 3rd zone."),
            {
                "id": "template_picker",
                "type": "compose_template_picker",
                "label": "Start from a template",
                "target_step": "prompt",
                "templates": MULTI_COMPOSER_TEMPLATES,
            },
            {
                "id": "zone_builder",
                "type": "zone_prompt_builder",
                "label": "Build prompt from zones",
                "target_step": "prompt",
                "source_steps": ["image_2", "image_3", "image_4"],
                "background_ref": "<image1>",
            },
            {
                "id": "prompt",
                "type": "prompt_input",
                "label": "Composition prompt",
                "placeholder": "Reference the background as <image1> and each reference as <image2>, <image3>, "
                               "<image4> — or use \"Build prompt from zones\" above.",
                "default": "",
                "rows": 4,
            },
            {
                "id": "params",
                "type": "workflow_params",
                "label": "Parameters",
                "workflow_file": MIX_MULTI_COMPOSER_WORKFLOW_REL,
                "image_node": "7",
                "fields": [
                    {
                        "id": "aspect_ratio",
                        "type": "aspect_ratio",
                        "label": "Output aspect ratio",
                        "default": "r1x1",
                        "resolution": "md",
                        "adv_keys": {"width": "25.width", "height": "25.height"},
                    },
                    {
                        "id": "steps", "adv_key": "15.steps", "label": "Steps", "type": "number",
                        "default": 25, "min": 1, "max": 25, "step": 1, "quick_options": [8, 16, 25], "advanced": True,
                    },
                    {"id": "seed", "adv_key": "15.seed", "label": "Seed", "type": "seed", "advanced": True},
                ],
            },
            {
                "id": "generate",
                "type": "action",
                "label": "Generate",
                "calls": "generation.submit_mix",
                "input_map": {
                    "workflowFile": "steps.params.output.workflow_file",
                    "images": [
                        {
                            "dataUrl": "steps.annotate.output.annotated_image_data_url || "
                                       "steps.background.output.image_data_url",
                            "nodeId": "7",
                        },
                        {"dataUrl": "steps.image_2.output.image_data_url", "nodeId": "8"},
                        {"dataUrl": "steps.image_3.output.image_data_url", "nodeId": "9", "optional": True},
                        {"dataUrl": "steps.image_4.output.image_data_url", "nodeId": "10", "optional": True},
                    ],
                    "advancedValues": "steps.params.output.adv_values",
                    "promptKey": "13.prompt",
                    "promptValue": "steps.prompt.output.prompt_text",
                },
            },
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Mix",
        "entry_model": "Qwen Image 2.1 Edit",
    }


def build_mix_multi_reference(source: Path, version: str) -> Path:
    table = load_translations(source)
    files: dict[str, object] = {}
    workflow_refs: set[str] = set()

    flow1 = add_card_texts(_multi_reference_compose_flow(), table)
    flow1["card"]["label"] = {
        "en": "Multi-Reference Compose", "es": "Composición multi-referencia",
        "zh": "多参考图合成", "ko": "다중 참조 합성",
    }
    flow1["card"]["desc"] = {
        "en": "Combine multiple references — subject, style, object, environment — into one coherent image.",
        "es": "Combina varias referencias — sujeto, estilo, objeto, entorno — en una sola imagen coherente.",
        "zh": "将主体、风格、物体、环境等多个参考图合成为一张连贯的图像。",
        "ko": "피사체, 스타일, 오브젝트, 환경 등 여러 참조 이미지를 하나의 일관된 이미지로 합성합니다.",
    }

    flow2 = add_card_texts(_multi_reference_compose_quick_flow(), table)
    flow2["card"]["label"] = {
        "en": "Multi-Reference Compose (Quick)", "es": "Composición multi-referencia (rápida)",
        "zh": "多参考图合成（快速）", "ko": "다중 참조 합성 (빠른)",
    }
    flow2["card"]["desc"] = {
        "en": "Combine multiple references fast — pick each image's role from a dropdown, no AI needed.",
        "es": "Combina varias referencias rápido — elige el rol de cada imagen en un desplegable, sin IA.",
        "zh": "快速合成多个参考图——从下拉菜单为每张图选择角色，无需 AI。",
        "ko": "빠르게 여러 참조 이미지를 합성 — 드롭다운에서 각 이미지의 역할을 선택, AI 불필요.",
    }

    flow3 = add_card_texts(_multi_composer_flow(), table)
    flow3["card"]["label"] = {
        "en": "MultiComposer", "es": "MultiComposer", "zh": "MultiComposer", "ko": "MultiComposer",
    }
    flow3["card"]["desc"] = {
        "en": "Mark colored zones on a background, drop a reference image into each one.",
        "es": "Marca zonas de color en un fondo y coloca una imagen de referencia en cada una.",
        "zh": "在背景图上标记彩色区域，为每个区域放入一张参考图。",
        "ko": "배경에 색상 구역을 표시하고 각 구역에 참조 이미지를 넣습니다.",
    }

    flows = [flow1, flow2, flow3]
    for flow in flows:
        _upgrade_seed_fields_to_similarity(flow)
        files[f"flows/{flow['id'].split('.', 1)[1]}.json"] = flow
        workflow_refs |= _collect_workflow_file_refs(flow)

    for ref in sorted(workflow_refs):
        graph = _load_workflow_ref(source, ref)
        _strip_foreign_flow_data(graph)
        files[ref] = graph

    i18n, counts = flow_i18n(flows, table)
    manifest = {
        "schema_version": 1,
        "id": "nomad.mix-multi-reference",
        "version": version,
        "default_lang": "en",
        "name": {"en": "Multi-Reference Compose", "es": "Composición multi-referencia",
                  "zh": "多参考图合成", "ko": "다중 참조 합성"},
        "summary": {
            "en": "Combine 2-4 reference images into one coherent final image — write an idea and let AI "
                  "compose the prompt, pick each image's role from a quick dropdown, or mark colored zones "
                  "on a background and drop a reference into each one. Qwen Image 2.1.",
            "es": "Combina de 2 a 4 imágenes de referencia en una sola imagen final — escribe una idea y deja "
                  "que la IA componga el prompt, elige el rol de cada imagen en un desplegable rápido, o marca "
                  "zonas de color en un fondo y coloca una referencia en cada una. Qwen Image 2.1.",
            "zh": "将 2 到 4 张参考图合成为一张连贯的最终图像——写下想法让 AI 生成提示词，从下拉菜单快速选择"
                  "每张图的角色，或在背景上标记彩色区域并放入参考图。由 Qwen Image 2.1 驱动。",
            "ko": "2~4장의 참조 이미지를 하나의 최종 이미지로 합성 — 아이디어를 적으면 AI가 프롬프트를 작성하거나, "
                  "드롭다운에서 각 이미지의 역할을 빠르게 선택하거나, 배경에 색상 구역을 표시하고 참조 이미지를 "
                  "넣습니다. Qwen Image 2.1 기반.",
        },
        "author": AUTHOR,
        "license": "proprietary",
        "group": {"id": "compose", "label": {"en": "Compose"}},
        "requires": {"engines": [{"category": "image"}]},
        "languages": ["en", *(lang for lang in LANGS if i18n[lang])],
        "contributes": {
            "flows": [f"flows/{flow['id'].split('.', 1)[1]}.json" for flow in flows],
            "workflows": sorted(workflow_refs),
        },
    }
    print(f"  mix-multi-reference texts: {counts['total']} · " + " ".join(f"{lang} {counts[lang]}" for lang in LANGS))
    return write_zip("nomad.mix-multi-reference", {"manifest.json": manifest, **files, "LICENSE": LICENSE_TEXT,
                                                     **{f"i18n/{lang}.json": i18n[lang] for lang in LANGS if i18n[lang]}},
                      dest=DIST_OPTIONAL)


# ── Qwen 2.1 Outpaint (replaces outpaint_qwen_2511.json, one of Outpaint's
# engine_select options) ─────────────────────────────────────────────────
# Same conversion as the Edit engine (single reference image via
# "images.image_1", no LoraLoaderModelOnly), except the output latent stays
# a plain EmptyLatentImage sized to the pre-padded canvas (node 11 in the
# source, untouched by app code that fills in the real width/height at
# generation time) rather than GetImageSize(source) — outpaint's whole point
# is generating INTO an area larger than the source image, so matching the
# source's own size here would defeat it.
QWEN_2511_OUTPAINT_WORKFLOW_REL = "workflows/refine/outpaint_qwen_2511.json"


def _qwen_image_21_outpaint_workflow() -> dict:
    return {
        # Not wired to anything in the graph — refine_routes.py's
        # _get_flow_preprocess() reads this straight off the submitted
        # workflow to pad/position the source image onto the target canvas
        # before it ever reaches ComfyUI (11.width/height are this same
        # replacement's EmptySD3LatentImage). Carried over unchanged from
        # the source outpaint_qwen_2511.json — dropping it when hand-writing
        # this replacement silently broke Outpaint's position/scale panel
        # for the Qwen option specifically (caught by hand-testing).
        "flow_data": {
            "inputs": {"value": json.dumps({
                "preprocess": {
                    "type": "pad_canvas", "width_key": "11.width", "height_key": "11.height",
                    "background": "transparent", "position": "center",
                },
            })},
            "class_type": "PrimitiveStringMultiline",
            "_meta": {"title": "flow_data"},
        },
        "config": _qwen_image_21_config_node(),
        "2": {
            "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"},
            "class_type": "VAELoader",
            "_meta": {"title": "Load VAE"},
        },
        "3": {
            "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"},
            "class_type": "CLIPLoader",
            "_meta": {"title": "Load CLIP"},
        },
        "6": {
            "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"},
            "class_type": "UNETLoader",
            "_meta": {"title": "Load Diffusion Model"},
        },
        "7": {
            "inputs": {"image": "oj-refine-placeholder.png"},
            "class_type": "LoadImage",
            "_meta": {"title": "Load Image"},
        },
        "11": {
            "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
            "class_type": "EmptySD3LatentImage",
            "_meta": {"title": "EmptySD3LatentImage"},
        },
        "13": {
            "inputs": {
                "prompt": "Replace the black area with a continuation of the image. change a bit",
                "negative_prompt": "",
                "resolution": 0,
                "clip": ["3", 0],
                "vae": ["2", 0],
                "images.image_1": ["7", 0],
            },
            "class_type": "TextEncodeQwenImage21",
            "_meta": {"title": "Text Encode Qwen Image 2.1"},
        },
        "15": {
            "inputs": {
                "seed": 718059206771042, "steps": 25, "cfg": 1, "sampler_name": "euler", "scheduler": "simple",
                "denoise": 1, "model": ["6", 0], "positive": ["13", 0], "negative": ["13", 1],
                "latent_image": ["11", 0],
            },
            "class_type": "KSampler",
            "_meta": {"title": "KSampler"},
        },
        "17": {
            "inputs": {"samples": ["15", 0], "vae": ["2", 0]},
            "class_type": "VAEDecode",
            "_meta": {"title": "VAE Decode"},
        },
        "21": {
            "inputs": {"filename_prefix": "qwen-image-2.1-outpaint", "images": ["17", 0]},
            "class_type": "SaveImage",
            "_meta": {"title": "Save Image"},
        },
    }


# The 2 flows that live under a real-world "camera" theme: Camera Shoot
# (Klein 9B — real camera/lens/lighting/color-grading presets) and Relight
# (moved out of Portrait Fix — lighting direction/mood is a camera concern,
# not a portrait-retouch one). A hand-authored Qwen 2.1 Camera Shoot variant
# was tried and dropped after hand-testing: 2.1 didn't reproduce the
# camera/lens/lighting look reliably, Klein 9B stays the only engine here.
CAMERA_PACK_FLOWS = ["refine.pf_relight", "refine.camera_shoot_klein_9b"]


def build_camera_pack(source: Path, version: str) -> Path:
    return build_refine_static_group(
        source, version, "nomad.refine-camera", "camera",
        name={"en": "Camera", "es": "Cámara", "zh": "相机", "ko": "카메라"},
        summary={
            "en": "Cinematic camera looks — real camera/lens/lighting/color-grading presets — plus directional relighting.",
            "es": "Looks cinematográficos de cámara — presets reales de cámara/lente/luz/color — más relighting direccional.",
            "zh": "电影感相机风格——真实相机/镜头/灯光/调色预设——以及方向性重新布光。",
            "ko": "시네마틱 카메라 룩 — 실제 카메라/렌즈/조명/컬러 그레이딩 프리셋 — 과 방향성 재조명.",
        },
        flow_ids=CAMERA_PACK_FLOWS,
        group_overrides={fid: "camera" for fid in CAMERA_PACK_FLOWS},
    )


def build_qwen_image_21_engine(version: str) -> Path:
    from app.services.workflow_service import _analyze_workflow

    workflow = _qwen_image_21_workflow()
    analysis = _analyze_workflow(workflow)
    engine = {
        "category": "image",
        "name": "Qwen Image 2.1",
        "slug": ENGINE_SLUGS["qwen-image"],
        "workflow": workflow,
        "analysis": analysis,
        "basicValues": analysis.get("basicValues", {}),
        "advancedValues": {p["key"]: p["value"] for p in analysis.get("advancedParameters", []) if not p.get("isLinked")},
        "annotation": {"downloads": [], "loras": [], "optionalSubgraphs": []},
    }
    pkg_id = "nomad.engine.qwen-image"
    file_rel = "engines/qwen_image.json"
    manifest = {
        "schema_version": 1,
        "id": pkg_id,
        "version": version,
        "default_lang": "en",
        "name": {lang: "Qwen Image 2.1" for lang in ("en", "es", "zh", "ko")},
        "summary": {
            "en": "Qwen Image 2.1: fast text-to-image, native transparent-background generation.",
            "es": "Qwen Image 2.1: texto a imagen rápido, con generación nativa de fondo transparente.",
            "zh": "Qwen Image 2.1：快速文生图，原生支持透明背景生成。",
            "ko": "Qwen Image 2.1: 빠른 텍스트-이미지 생성, 네이티브 투명 배경 지원.",
        },
        "author": AUTHOR,
        "license": "proprietary",
        "order": 50,
        "contributes": {"engines": [file_rel]},
    }
    return write_zip(pkg_id, {"manifest.json": manifest, file_rel: engine, "LICENSE": LICENSE_TEXT})


def build_engine(source: Path, version: str, name: str, catalog: dict = ENGINES, dest: Path = DIST) -> Path:
    slug, summary = catalog[name]
    engine = {**engine_from_registry(source, name), "slug": ENGINE_SLUGS[slug]}
    pkg_id = f"nomad.engine.{slug}"
    file_rel = f"engines/{slug.replace('-', '_')}.json"
    manifest = {
        "schema_version": 1,
        "id": pkg_id,
        "version": version,
        "default_lang": "en",
        "name": {lang: name for lang in ("en", "es", "zh", "ko")},
        "summary": summary,
        "author": AUTHOR,
        "license": "proprietary",
        # Install order when shipped with the app: the first image engine
        # becomes the default one (Z-Image Turbo: fast, small files).
        "order": 10 if slug == "z-image-turbo" else 50,
        "contributes": {"engines": [file_rel]},
    }
    return write_zip(pkg_id, {"manifest.json": manifest, file_rel: engine, "LICENSE": LICENSE_TEXT}, dest=dest)


# Create › core flows shipped with the app. They only need an image engine,
# plus LM Studio for the LLM ones. Left out: the CivitAI flows (their own free
# pack, build_core_civitai below) and the unfinished ones (Character, From
# Brief, Style). From Template ships here with no templates of its own: they
# come in template packs (contributes.template_packs, built in the Nomad
# Studio Packs repo).
CORE_CREATE_FLOWS = [
    "create.simple", "create.simple_json", "create.assist", "create.chat",
    "create.variations", "create.variations_json", "create.story", "create.scenes",
    "create.portraits", "create.posters", "create.describe_image", "create.bulk_vision",
    "create.from_template",
]
CORE_CREATE_VERSION = "0.3.1"  # 0.3.1: flow texts in ES/ZH/KO (#1)
# The source card still describes the single cinematic catalog it started with.
CORE_CREATE_OVERRIDES = {
    "create.from_template": {
        "description": "Pick a template from an installed template pack, fill in its blanks, and generate.",
        "card_desc": "Pick a template from your template packs, fill in the blanks and generate. No AI needed.",
        "card_tags": ["No LLM", "Catalog"],
    },
}


def build_core_create(source: Path, version: str) -> Path:
    table = load_translations(source)
    files: dict[str, object] = {}
    flows = []
    for flow_id in CORE_CREATE_FLOWS:
        flow = add_card_texts({**flow_from_source(source, flow_id), **CORE_CREATE_OVERRIDES.get(flow_id, {})}, table)
        flows.append(flow)
        files[f"flows/{flow_id.split('.', 1)[1]}.json"] = flow
    i18n, counts = flow_i18n(flows, table)
    manifest = {
        "schema_version": 1,
        "id": "nomad.core-create",
        # 0.1.0 carried Simple only; bundled packages update only to a higher version.
        "version": CORE_CREATE_VERSION,
        "default_lang": "en",
        "name": {"en": "Core Create", "es": "Create básico", "zh": "基础创作", "ko": "기본 만들기"},
        "summary": {
            "en": "The base Create flows: Simple, Assist, Chat, Variations, Story, Scenes, Portraits, Posters, From Template and image description. The AI-assisted ones use LM Studio.",
            "es": "Los flows base de Create: Simple, Assist, Chat, Variations, Story, Scenes, Portraits, Posters, From Template y descripción de imágenes. Los que usan IA necesitan LM Studio.",
            "zh": "Create 基础流程：Simple、Assist、Chat、Variations、Story、Scenes、Portraits、Posters、From Template 以及图像描述。AI 辅助流程需要 LM Studio。",
            "ko": "Create 기본 플로우: Simple, Assist, Chat, Variations, Story, Scenes, Portraits, Posters, From Template, 이미지 설명. AI 보조 플로우는 LM Studio가 필요합니다.",
        },
        "author": AUTHOR,
        "license": "proprietary",
        "group": {"id": "core", "label": {"en": "Core"}},
        "requires": {"engines": [{"category": "image"}]},
        "languages": ["en", *(lang for lang in LANGS if i18n[lang])],
        "contributes": {"flows": list(files)},
    }
    print(f"  core-create texts: {counts['total']} · " + " ".join(f"{lang} {counts[lang]}" for lang in LANGS))
    return write_zip("nomad.core-create", {"manifest.json": manifest, **files, "LICENSE": LICENSE_TEXT,
                                           **{f"i18n/{lang}.json": i18n[lang] for lang in LANGS if i18n[lang]}})


# Create › Layout: composition flows (Ideogram JSON layouts). Source id → the
# id they ship with, so ids and URLs say "layout" instead of an engine name.
# Internal names (step type ideogram_composer, llm.ideogram_* calls) stay.
LAYOUT_FLOWS = {
    "create.assist_ideogram": "create.layout_assist",
    "create.assist_ideogram_ref": "create.layout_reference",
    "create.assist_ideogram_lettering": "create.layout_lettering",
    "create.ideogram_charref": "create.layout_character_reference",
    "create.ideogram_poster": "create.layout_poster",
    "create.ideogram_scene": "create.layout_scene",
    "create.ideogram_storyboard": "create.layout_storyboard",
    "create.character_sheet": "create.character_sheet",
}
LAYOUT_VERSION = "0.3.1"  # 0.3.1: flow texts in ES/ZH/KO (#1)

# Layout Assist on any engine (NomadStudio#18). Tested 2026-09-26 on Krea 2
# Turbo / Monaco / Roma: they don't read bbox numbers as positions — they
# ignore them, and Monaco even paints them (next to a text element, as more
# lettering). The SAME JSON works on every engine once each position is also
# written in words, in high_level_description and in every desc; Ideogram
# still gets its bboxes. So the composer is asked for both, accepts a free
# description as well as ';' fragments, and stops asking for hex colours
# (two levels asked for them right after forbidding them).
def _layout_position_rules(*extra: str) -> str:
    """The POSITIONS IN WORDS block, with each flow's own lines for its
    element types (text elements differ: Assist quotes the words in desc,
    Lettering/Poster keep them in the element's own "text" field)."""
    return "\n".join([
        "POSITIONS IN WORDS — this layout is used with engines that cannot read bbox numbers (they ignore them, "
        "or paint them into the image as text), so every position must ALSO be written in plain words:",
        "- high_level_description says where the main elements are: \"a red sphere in the upper left and a blue "
        "sphere in the lower right\".",
        "- Every element's desc states its position and size in words, matching its bbox: \"in the upper-left "
        "corner\", \"centered along the bottom edge\", \"filling the right half\", \"small, in the lower-left third\".",
        *extra,
        "- Never write numbers, coordinates or bbox values in any prose field — only in the bbox arrays.",
    ])


_LAYOUT_TEXT_QUOTED = ("- For type \"text\", the desc gives the exact words in quotes, their look and where they sit: "
                       "\"the word 'HELLO' in bold black capitals, centered at the top\".")

LAYOUT_ASSIST_RULES = (
    "\n\nINPUT: either composition fragments separated by ';' (one element each) or a free description of the "
    "scene. With a free description, pick out each physical element yourself (people, objects, pieces of lettering) "
    "and give each one its own entry.\n\n" + _layout_position_rules(_LAYOUT_TEXT_QUOTED))

# The rest of the Layout flows (NomadStudio#18): same POSITIONS IN WORDS
# block, inserted just before their closing "Output ONLY valid JSON" rule.
# Storyboard already names each panel's cell in words ("Top-left grid cell")
# and its high_level_description legitimately carries "16:9"-style labels, so
# it only gets the hex clean-up.
_LAYOUT_TEXT_FIELD = ("- For type \"text\", the words stay in the element's \"text\" field only; desc gives their look "
                      "and where they sit, in words — \"bold black capitals, centered along the top edge\" — never "
                      "the words themselves.")
_LAYOUT_TEXT_POSTER = ("- For type \"text\", the words stay in \"text\"; desc gives the treatment and where it sits, in "
                       "words — \"large bold serif capitals across the lower third\" — never the element's role "
                       "(title, tagline, credits).")
_LAYOUT_CHARACTER = ("- The character's desc begins with where they are and how much of the frame they fill: "
                     "\"standing in the left third, seen from head to knees\".")
LAYOUT_POSITION_RULES = {
    "create.layout_reference": _layout_position_rules(_LAYOUT_TEXT_QUOTED),
    "create.layout_lettering": _layout_position_rules(_LAYOUT_TEXT_FIELD),
    "create.layout_character_reference": _layout_position_rules(_LAYOUT_CHARACTER),
    "create.layout_poster": _layout_position_rules(_LAYOUT_TEXT_POSTER),
    "create.layout_storyboard": None,
}
# Hex requests left in these prompts right after "never hex codes" (and in
# character descriptions: "skin tone (hex)") — any engine but Ideogram paints
# a hex string into the image.
_LAYOUT_HEX_PATTERNS = [
    (r"(\d+(?:–\d+)?) (?:specific )?hex (?:colors|values)", r"\1 color names"),
    (r"color \(hex\)", "color name"),
    (r" \(hex\)", ""),
    (r"every hex, ", "every color, "),
    (r"exact hex colors", "exact color names"),
    (r"accurate hex values", "precise color names"),
    (r"hex codes throughout", "color names throughout"),
]
# Poster examples: the model copies them, so they show positions in words too.
_LAYOUT_POSTER_EXAMPLES = [
    ('"main character full/3-4 body, dramatically lit"',
     '"main character full/3-4 body filling the upper two thirds, dramatically lit"'),
    ('"large bold theatrical lettering, the dominant type on the poster"',
     '"large bold theatrical lettering across the lower part of the poster, the dominant type on it"'),
    ('"main character or ensemble — horizontal spread"',
     '"main character or ensemble spread across the left half"'),
    ('"wide horizontal lettering, the dominant type on the key art"',
     '"wide horizontal lettering in the upper right, the dominant type on the key art"'),
]


# Character Reference's high_level_description template ("A photograph of
# [character]. [Scene: pose, action, …]") outweighed the rule: tested, it
# described the scene with no positions. The template itself asks for them.
_LAYOUT_CHARREF_SCENE = ("[Scene: ", "[Scene: where the character is in the frame and where the main scene elements "
                                     "sit, in words; ")


def _improve_layout_positions(flow: dict) -> dict:
    rules = LAYOUT_POSITION_RULES[flow["id"]]
    marker = "\n- Output ONLY valid JSON."
    for step in flow["steps"]:
        prompts = step.get("system_prompts")
        if not isinstance(prompts, dict):
            continue
        for level, text in prompts.items():
            where = f"{flow['id']} {level}"
            for pattern, repl in _LAYOUT_HEX_PATTERNS:
                text = re.sub(pattern, repl, text)
            if re.search(r"hex", re.sub(r"never hex codes|a hex string", "", text)):
                raise SystemExit(f"{where}: still asks for hex colours")
            if flow["id"] == "create.layout_poster":
                for old, new in _LAYOUT_POSTER_EXAMPLES:
                    text = text.replace(old, new)
            if flow["id"] == "create.layout_character_reference":
                if _LAYOUT_CHARREF_SCENE[0] not in text:
                    raise SystemExit(f"{where}: scene template not found")
                text = text.replace(*_LAYOUT_CHARREF_SCENE)
            if rules:
                if marker not in text:
                    raise SystemExit(f"{where}: output rule not found")
                head, tail = text.rsplit(marker, 1)
                text = head + "\n\n" + rules + "\n" + marker + tail
            prompts[level] = text
    return flow


_LAYOUT_ASSIST_HEX_TO_NAMES = [
    ("Include 5 global hex colors in style_description.color_palette", "Include 5 global color names in style_description.color_palette"),
    ("Add 2–3 hex colors per element color_palette", "Add 2–3 color names per element color_palette"),
    ("Per-element color_palette: 3–5 hex values dominant in that element", "Per-element color_palette: 3–5 color names dominant in that element"),
    ("Global color_palette: 5 hex values that define the mood of the whole piece", "Global color_palette: 5 color names that define the mood of the whole piece"),
    ("Every element must have 4–5 specific hex colors", "Every element must have 4–5 specific color names"),
    ("Place each input fragment as one element with a sensible bbox", "Place each element (one per ';' fragment, or each one you pick out of a free description) with a sensible bbox"),
    ("Given a list of composition elements,", "Given a composition idea,"),
    ("Given composition fragments,", "Given a composition idea,"),
    ("an Ideogram composition AI", "a layout composition AI"),
    ("world-class Ideogram composition director", "world-class layout composition director"),
    ("Ideogram JSON", "layout JSON"),
]
# The scene level's few-shot example still carried hex palettes and a
# high_level_description with no positions: models copy the example.
_LAYOUT_ASSIST_EXAMPLE_HEX = {
    "#1E73BE": "sky blue", "#FDFDFD": "off white", "#C82A2A": "stamp red", "#657C9C": "slate blue",
    "#EFEFEF": "paper white", "#E0E0E0": "light grey", "#D3DBE2": "pale blue grey", "#FFDAB9": "peach",
    "#A11D1D": "deep red", "#1A1A1A": "near black",
}
_LAYOUT_ASSIST_EXAMPLE_DESC = (
    "backed by giant puffy 3D letters spelling 'COMFY'.\", \"style_description\"",
    "with giant puffy 3D letters spelling 'COMFY' across the upper half, the skateboarder in the center, "
    "red grunge stamps in the top right and torn paper banners on the left edge and along the bottom.\", "
    "\"style_description\"",
)


def _improve_layout_assist(flow: dict) -> dict:
    flow["description"] = ("Describe a composition — freely, or as elements separated by ';' — and the AI lays it "
                           "out: bounding boxes plus every position written in words, so it places things on any "
                           "engine, not only Ideogram.")
    flow["card_desc"] = "Describe the scene and the AI places each element on a canvas you can adjust. Works on any engine."
    flow["card_tags"] = ["Assist", "Layout", "Any engine", "AI Compose"]
    for step in flow["steps"]:
        if step.get("id") == "idea":
            step["note"] = "Describe the scene freely, or separate the elements with ';' — each fragment becomes one placed element."
            step["placeholder"] = ("a woman skateboarder mid-air in the center, giant puffy letters COMFY behind her, "
                                   "a torn paper strip along the bottom that says STAY COZY")
        if step.get("id") == "compose":
            prompts = step["system_prompts"]
            for level, text in prompts.items():
                for old, new in _LAYOUT_ASSIST_HEX_TO_NAMES:
                    text = text.replace(old, new)
                for hex_code, name in _LAYOUT_ASSIST_EXAMPLE_HEX.items():
                    text = text.replace(f'"{hex_code}"', f'"{name}"')
                if "Few-shot example" in text:
                    if _LAYOUT_ASSIST_EXAMPLE_DESC[0] not in text:
                        raise SystemExit(f"layout_assist {level}: example description not found")
                    text = text.replace(*_LAYOUT_ASSIST_EXAMPLE_DESC)
                # Before the closing output rule, so "Output ONLY valid JSON" stays last.
                marker = "\n- Output ONLY valid JSON."
                if marker not in text:
                    raise SystemExit(f"layout_assist {level}: output rule not found")
                head, tail = text.rsplit(marker, 1)
                if "Few-shot example" in tail:
                    # scene: the example comes after the rules — keep it there.
                    rules_end, example = tail.split("\n\nFew-shot example", 1)
                    text = head + marker + rules_end + LAYOUT_ASSIST_RULES + "\n\nFew-shot example" + example
                else:
                    text = head + marker + tail + LAYOUT_ASSIST_RULES
                if re.search(r"hex (colors|values)", text):
                    raise SystemExit(f"layout_assist {level}: still asks for hex colours")
                prompts[level] = text
    return flow


def build_create_layout(source: Path, version: str) -> Path:
    table = load_translations(source)
    files: dict[str, object] = {}
    flows = []
    for source_id, flow_id in LAYOUT_FLOWS.items():
        flow = flow_from_source(source, source_id)
        if flow.get("id") != source_id:
            raise SystemExit(f"{source_id}: flow file declares id {flow.get('id')!r}")
        flow["id"] = flow_id
        text = json.dumps(flow)
        if source_id != flow_id and source_id in text:
            raise SystemExit(f"{source_id}: old id still referenced inside the flow")
        if flow_id == "create.layout_assist":
            flow = _improve_layout_assist(flow)
        elif flow_id in LAYOUT_POSITION_RULES:
            flow = _improve_layout_positions(flow)
        flows.append(add_card_texts(flow, table))
        files[f"flows/{flow_id.split('.', 1)[1]}.json"] = flow
    i18n, counts = flow_i18n(flows, table)
    manifest = {
        "schema_version": 1,
        "id": "nomad.create-layout",
        "version": LAYOUT_VERSION,
        "default_lang": "en",
        "name": {"en": "Layout", "es": "Layout", "zh": "版式布局", "ko": "레이아웃"},
        "summary": {
            "en": "Compose the image by parts: layout, lettering, posters, scenes, storyboards, character references and sheets. Best with Ideogram 4; the AI-assisted ones use LM Studio.",
            "es": "Compón la imagen por partes: layout, rótulos, pósters, escenas, storyboards, referencias y hojas de personaje. Mejor con Ideogram 4; los que usan IA necesitan LM Studio.",
            "zh": "分部分构图：版式、字体、海报、场景、分镜、角色参考与角色设定图。搭配 Ideogram 4 效果最佳；AI 辅助流程需要 LM Studio。",
            "ko": "이미지를 부분별로 구성: 레이아웃, 레터링, 포스터, 장면, 스토리보드, 캐릭터 레퍼런스와 시트. Ideogram 4와 가장 잘 맞으며, AI 보조 플로우는 LM Studio가 필요합니다.",
        },
        "author": AUTHOR,
        "license": "proprietary",
        "group": {"id": "layout", "label": {"en": "Layout"}},
        "requires": {"engines": [{"category": "image"}]},
        "languages": ["en", *(lang for lang in LANGS if i18n[lang])],
        "contributes": {"flows": list(files)},
    }
    print(f"  layout texts: {counts['total']} · " + " ".join(f"{lang} {counts[lang]}" for lang in LANGS))
    return write_zip("nomad.create-layout", {"manifest.json": manifest, **files, "LICENSE": LICENSE_TEXT,
                                             **{f"i18n/{lang}.json": i18n[lang] for lang in LANGS if i18n[lang]}})


# Create › CivitAI: paste a CivitAI generation block, match its model/LoRAs
# against an installed engine, generate. Left out of nomad.core-create
# (comment there) so a user who never touches CivitAI doesn't get a card
# offering to paste one — this is its own free pack, installed separately.
CIVITAI_FLOWS = [
    "create.simple_civitai", "create.enhance_civitai", "create.chat_civitai",
]
CORE_CIVITAI_VERSION = "0.1.1"  # 0.1.1: flow texts in ES/ZH/KO (#1)


def build_core_civitai(source: Path, version: str) -> Path:
    table = load_translations(source)
    files: dict[str, object] = {}
    flows = []
    for flow_id in CIVITAI_FLOWS:
        flow = flow_from_source(source, flow_id)
        # The source flow (OPENHIKER) predates this pack and carries no group
        # of its own — unlike the Layout flows, which already say "layout" in
        # their source file. flow_engine._enrich_entry cards which section a
        # flow shows under off the flow file's own "group" field, not the
        # manifest's (that one only feeds the packages page) — has to be set
        # here.
        flow["group"] = "civitai"
        flow = add_card_texts(flow, table)
        flows.append(flow)
        files[f"flows/{flow_id.split('.', 1)[1]}.json"] = flow
    i18n, counts = flow_i18n(flows, table)
    manifest = {
        "schema_version": 1,
        "id": "nomad.core-civitai",
        "version": CORE_CIVITAI_VERSION,
        "default_lang": "en",
        "name": {"en": "CivitAI", "es": "CivitAI", "zh": "CivitAI", "ko": "CivitAI"},
        "summary": {
            "en": "Paste a CivitAI generation block: Simple runs it directly, Enhance uses it as an AI style reference, Chat keeps it as a fixed style anchor across turns. Model and LoRAs are matched to your installed engines automatically.",
            "es": "Pega un bloque de generación de CivitAI: Simple lo ejecuta directo, Enhance lo usa como referencia de estilo para la IA, Chat lo mantiene fijo como ancla de estilo turno a turno. El modelo y las LoRAs se casan automáticamente con tus motores instalados.",
            "zh": "粘贴一个 CivitAI 生成块：Simple 直接运行，Enhance 将其作为 AI 风格参考，Chat 在多轮对话中保持其为固定的风格锚点。模型和 LoRA 会自动与你安装的引擎匹配。",
            "ko": "CivitAI 생성 블록을 붙여넣으세요: Simple은 바로 실행하고, Enhance는 AI 스타일 참조로 사용하며, Chat은 턴마다 고정된 스타일 기준점으로 유지합니다. 모델과 LoRA는 설치된 엔진과 자동으로 매칭됩니다.",
        },
        "author": AUTHOR,
        "license": "proprietary",
        "group": {"id": "civitai", "label": {"en": "CivitAI", "es": "CivitAI", "zh": "CivitAI", "ko": "CivitAI"}},
        "requires": {"engines": [{"category": "image"}]},
        "languages": ["en", *(lang for lang in LANGS if i18n[lang])],
        "contributes": {"flows": list(files)},
    }
    print(f"  core-civitai texts: {counts['total']} · " + " ".join(f"{lang} {counts[lang]}" for lang in LANGS))
    return write_zip("nomad.core-civitai", {"manifest.json": manifest, **files, "LICENSE": LICENSE_TEXT,
                                            **{f"i18n/{lang}.json": i18n[lang] for lang in LANGS if i18n[lang]}},
                      dest=DIST_OPTIONAL)


# ── Refine pilot (docs/PACKAGE_FORMAT.md §5.2/§5.3, contributes.workflows) ──
# Refine has never had a package at all — every flow here either:
#  - already has an authored flow.json (Edit x5, Outpaint, Upscale Model —
#    the exact same contributes.flows path Create/Layout/CivitAI use), or
#  - only exists as a `flow_data` node buried inside its ComfyUI workflow
#    file (the 4 newer Upscale engines) — package_service.install() now
#    knows how to turn that into a real flow at install time (§5.3), so it
#    ships via contributes.workflows alone, no flow.json authored for it at
#    all.
# Deliberately NOT wired into the default build yet — this is the first,
# small pilot proving the contributes.workflows path end-to-end before the
# rest of Refine (photo-editing, portrait-fix, creator-pack, presets,
# look-book, mix) gets the same treatment.
REFINE_PILOT_STATIC_FLOWS = [
    "refine.edit_qwen_2511_basic", "refine.edit_fluxklein_9b_basic", "refine.edit_fluxklein_4b_basic",
    "refine.edit_boogu_turbo_basic", "refine.edit_fluxklein_9b_restore", "refine.outpaint",
    "refine.upscale_model",
]
# Both still run the 2511 engine internally (refine_qwen_2511_edit.json and
# the Qwen upscale LoRA haven't been migrated to Qwen Image 2.1 yet — that's
# its own follow-up) — renamed anyway, on request, ahead of that migration.
REFINE_PILOT_ID_OVERRIDES = {
    "refine.edit_qwen_2511_basic": "refine.edit_qwen2_basic",
    "refine.upscale_qwen_2511": "refine.upscale_qwen2",
}
# Same rename, for the flow whose id/label live inside its workflow's
# embedded flow_data (not a top-level dict field build_packages.py loaded
# directly) — applied by _rename_embedded_flow_data.
REFINE_PILOT_FLOW_DATA_LABEL_OVERRIDES = {
    "refine.upscale_qwen_2511": "Upscale (Qwen 2.1)",
}
# The source flow.json files (OPENHIKER) all say group "core" — Edit/Outpaint
# and the classic Upscale model belong under their own groups instead. The 4
# flow_data-only Upscale engines already declare "group": "upscale" in their
# own metadata, so only the static ones need a build-time override here.
REFINE_PILOT_GROUP_OVERRIDES = {
    "refine.edit_qwen_2511_basic": "edit", "refine.edit_fluxklein_9b_basic": "edit",
    "refine.edit_fluxklein_4b_basic": "edit", "refine.edit_boogu_turbo_basic": "edit",
    "refine.edit_fluxklein_9b_restore": "edit", "refine.outpaint": "edit",
    "refine.upscale_model": "upscale",
}
# Action-first naming ("Edit <engine>", matching Upscale's own "Upscale
# (<engine>)" cards) instead of the source's "<engine> Edit" — Outpaint is
# already action-first, left alone. Hand-translated (not run through
# load_translations: that table is keyed by the OLD English text, which
# these labels no longer are).
# card_desc/description/card_tags for the same flow — the source still says
# "Qwen 2511 Vision" and carries a literal "2511" tag; label alone wasn't
# the whole story (caught by the card subtitle still reading old in the UI).
# Hand-translated like REFINE_PILOT_LABEL_OVERRIDES, for the same reason:
# load_translations' table is keyed by the OLD English text.
REFINE_PILOT_DESC_OVERRIDES = {
    "refine.edit_qwen_2511_basic": {
        "description": "Image-to-image editing with Qwen Image 2.1. Prompt-driven scene editing at original resolution.",
        "card_tags": ["Qwen", "2.1", "Edit", "Prompt"],
        "desc": {
            "en": "Edit images with Qwen Image 2.1 — fast prompt-driven scene editing.",
            "es": "Edita imágenes con Qwen Image 2.1 — edición de escena rápida guiada por prompt.",
            "zh": "使用 Qwen Image 2.1 编辑图像——由提示词驱动的快速场景编辑。",
            "ko": "Qwen Image 2.1로 이미지 편집 — 프롬프트 기반의 빠른 장면 편집.",
        },
    },
}
# The source field (default 4, quick_options [4, 8], max 20) matched the old
# 2511 + Lightning-LoRA 4-step setup. 2.1 has no confirmed fast LoRA and runs
# at 25 steps (the verified-good setting) — bumped max so 25 is reachable at
# all, default now matches what the engine actually ships with.
REFINE_PILOT_STEPS_FIELD_OVERRIDES = {
    "refine.edit_qwen_2511_basic": {"default": 25, "max": 25, "quick_options": [8, 16, 25]},
}
REFINE_PILOT_LABEL_OVERRIDES = {
    "refine.edit_qwen_2511_basic": {"en": "Edit Qwen 2.1", "es": "Editar Qwen 2.1", "zh": "编辑 Qwen 2.1", "ko": "편집 Qwen 2.1"},
    "refine.edit_fluxklein_9b_basic": {"en": "Edit Flux Klein 9B", "es": "Editar Flux Klein 9B", "zh": "编辑 Flux Klein 9B", "ko": "편집 Flux Klein 9B"},
    "refine.edit_fluxklein_4b_basic": {"en": "Edit Flux Klein 4B", "es": "Editar Flux Klein 4B", "zh": "编辑 Flux Klein 4B", "ko": "편집 Flux Klein 4B"},
    "refine.edit_boogu_turbo_basic": {"en": "Edit Boogu Turbo", "es": "Editar Boogu Turbo", "zh": "编辑 Boogu Turbo", "ko": "편집 Boogu Turbo"},
    "refine.edit_fluxklein_9b_restore": {"en": "Edit Flux Klein 9B (Restore)", "es": "Editar Flux Klein 9B (Restaurar)", "zh": "编辑 Flux Klein 9B（修复）", "ko": "편집 Flux Klein 9B (복원)"},
}
# Relative to `source` (the OPENHIKER checkout), not to the package.
REFINE_PILOT_WORKFLOW_ONLY_FILES = [
    "app/workflows/upscale/upscale_klein_4b.json",
    "app/workflows/upscale/upscale_klein_9b.json",
    "app/workflows/upscale/upscale_qwen_2511.json",
    "app/workflows/upscale/refine_upscale_seedvr2.json",
]
REFINE_PILOT_VERSION = "0.1.3"  # 0.1.3: "Qwen Image 2.1 Edit" label; 0.1.1: Klein 9B defaults to INT8 (#11); 0.1.2: flow texts in ES/ZH/KO (#1)


# Applied unconditionally to every flow build_refine_pilot/
# build_refine_static_group package — a no-op for flows without this
# engine_select option, an update for the ones that offer it (Outpaint, Look
# Book once packaged, every Photo Editing/Portrait Fix/Creator Pack flow).
# steps_quick_options/steps_default: the flow-step-workflow-params.js side
# (esApplyEngine) reads these off the selected engine and re-renders the
# Steps field's quick-pick pills to match — Qwen 2.1 (8/16/25, no confirmed
# fast LoRA) needs different ones than Klein/Boogu's Lightning-style 4/8.
QWEN_ENGINE_SELECT_OVERRIDES = {
    "qwen_2511": {"label": "Qwen Image 2.1 Edit", "steps_quick_options": [8, 16, 25], "steps_default": 25},
}


def _update_engine_select_option(flow: dict, option_id: str, overrides: dict) -> None:
    """Merges `overrides` onto one option inside an engine_select field (e.g.
    Outpaint's "qwen_2511" -> label "Qwen Image 2.1 Edit" + new steps presets) —
    same idea as _override_flow_field, but engine_select's options live one
    level deeper, in field.engines[], keyed by their own "id" rather than
    the field's."""
    for step in flow.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "workflow_params":
            continue
        for f in step.get("fields") or []:
            if not isinstance(f, dict) or f.get("type") != "engine_select":
                continue
            for engine in f.get("engines") or []:
                if isinstance(engine, dict) and engine.get("id") == option_id:
                    engine.update(overrides)


def _override_flow_field(flow: dict, field_id: str, overrides: dict) -> None:
    """Applies `overrides` onto the named field (by its own "id", e.g.
    "steps") inside a flow's workflow_params step — wherever it lives among
    possibly several steps/fields."""
    for step in flow.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "workflow_params":
            continue
        for f in step.get("fields") or []:
            if isinstance(f, dict) and f.get("id") == field_id:
                f.update(overrides)


def _add_flow_field(flow: dict, field: dict) -> None:
    """Appends a brand-new field to a flow's (single) workflow_params step —
    for a control the source flow never exposed at all (Camera Angles baked
    its steps count straight into the graph, no UI for it)."""
    for step in flow.get("steps") or []:
        if isinstance(step, dict) and step.get("type") == "workflow_params":
            step.setdefault("fields", []).append(field)
            return


def _upgrade_seed_fields_to_similarity(flow: dict) -> None:
    """Every seed field across every Refine flow in OPENHIKER still uses the
    old plain numeric-input-plus-dice-button UI (no seed_mode set at all) —
    audited across all ~90 flows this build packages, zero already opted
    into the "Visual similarity" toggle flow-step-workflow-params.js
    already supports (f.seed_mode === 'similarity': a single switch, ON
    pins the seed so repeats stay visually close, OFF randomizes each
    time — same control Create's own Simple/Guided panel already uses).
    Applied unconditionally to every field of type "seed" that doesn't
    already declare its own seed_mode."""
    for step in flow.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "workflow_params":
            continue
        for f in step.get("fields") or []:
            if isinstance(f, dict) and f.get("type") == "seed" and not f.get("seed_mode"):
                f["seed_mode"] = "similarity"
                f["label"] = "Visual similarity"


def _collect_workflow_file_refs(node: object) -> set[str]:
    """Recursively finds every `workflow_file` value and every `file=...`
    inside an `options_src` URL — a flow can reference one from a top-level
    `workflow_params` step, or several more from an `engine_select` field's
    nested `engines[].workflow_file` (e.g. Outpaint, Look Book)."""
    import re

    refs: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "workflow_file" and isinstance(value, str) and value:
                refs.add(value)
            elif key == "options_src" and isinstance(value, str):
                m = re.search(r"file=([^&]+)", value)
                if m:
                    refs.add(m.group(1))
            else:
                refs |= _collect_workflow_file_refs(value)
    elif isinstance(node, list):
        for item in node:
            refs |= _collect_workflow_file_refs(item)
    return refs


def _rename_embedded_flow_data(graph: dict, id_overrides: dict[str, str], label_overrides: dict[str, str]) -> None:
    """For a flow_data-only flow (no top-level dict to edit — its id/label
    live inside the workflow's own flow_data node, as a JSON *string*), apply
    the same id_overrides/label rename build_refine_pilot uses for the
    authored ones, so both kinds get consistent treatment."""
    from app.services.flow_engine import _extract_flow_data_node

    for node in graph.values():
        if not isinstance(node, dict) or str(node.get("_meta", {}).get("title", "")) != "flow_data":
            continue
        meta = _extract_flow_data_node(graph)
        if meta is None or str(meta.get("id", "")) not in id_overrides:
            return
        old_id = str(meta["id"])
        meta["id"] = id_overrides[old_id]
        if old_id in label_overrides:
            meta["label"] = label_overrides[old_id]
        node["inputs"]["value"] = json.dumps(meta)
        return


def _load_workflow_ref(source: Path, ref: str) -> dict:
    """Loads a `workflow_file`-referenced ComfyUI graph — from a hand-authored
    Qwen 2.1 replacement for the refs that have one (see their own comments
    for why), otherwise straight from OPENHIKER, same as always."""
    if ref == QWEN_2511_EDIT_WORKFLOW_REL:
        return _qwen_image_21_edit_workflow()
    if ref == QWEN_2511_OUTPAINT_WORKFLOW_REL:
        return _qwen_image_21_outpaint_workflow()
    if ref == MIX_MULTI_REFERENCE_WORKFLOW_REL:
        return _qwen_image_21_multi_reference_workflow()
    if ref == MIX_MULTI_COMPOSER_WORKFLOW_REL:
        return _qwen_image_21_multi_composer_workflow()
    if ref == STYLE_TRANSFER_QWEN21_WORKFLOW_REL:
        return _qwen_image_21_style_transfer_workflow()
    if ref == ANIMA_STYLE_WORKFLOW_REL:
        return _anima_style_workflow(source)
    if ref == STYLE_REFERENCE_KLEIN_4B_WORKFLOW_REL:
        return _klein_style_reference_workflow(source, "4b")
    if ref == STYLE_REFERENCE_KLEIN_9B_WORKFLOW_REL:
        return _klein_style_reference_workflow(source, "9b")
    if ref in STYLE_REFERENCE_QWEN_2511_WORKFLOWS:
        return _rf_style_reference_workflow(source, STYLE_REFERENCE_QWEN_2511_WORKFLOWS[ref])
    src_path = source / "app" / ref
    if not src_path.is_file():
        raise SystemExit(f"referenced workflow_file not found: {src_path}")
    return _repair_model_paths(json.loads(src_path.read_text(encoding="utf-8")))


# A Windows path typed into a graph with one backslash, e.g. "flux2_klein\flux-...",
# is valid JSON where "\f" means a form feed, so the file name ComfyUI receives
# is "flux2_klein<FF>lux-..." (outpaint_flux2_klein_4b/9b.json in OPENHIKER).
# Only file-name values are repaired; prompts keep their characters.
_JSON_CONTROL_ESCAPES = {"\f": "f", "\b": "b", "\t": "t", "\n": "n", "\r": "r"}
_MODEL_FILE_SUFFIXES = (".safetensors", ".gguf", ".pth", ".pt", ".bin", ".ckpt", ".sft")


def _repair_model_paths(graph: dict) -> dict:
    for node in graph.values():
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict):
            continue
        for key, value in inputs.items():
            if not (isinstance(value, str) and value.lower().endswith(_MODEL_FILE_SUFFIXES)):
                continue
            for ch, letter in _JSON_CONTROL_ESCAPES.items():
                value = value.replace(ch, "\\" + letter)
            inputs[key] = value
    return graph


def _strip_foreign_flow_data(graph: dict) -> None:
    """A shared base workflow (e.g. refine_qwen_2511_edit.json, reused by
    several flows via `workflow_file`) can itself carry a `flow_data` node
    that's the authoritative source of a DIFFERENT flow — Edit Qwen 2.1, in
    the pilot package. Bundling that file unmodified into another package
    would let package_service's install-time flow_data conversion (§5.3)
    redeclare that flow here too — under its OLD id even when the owning
    package renamed it (build_refine_pilot/build_refine_static_group's
    id_overrides), since this embedded copy is untouched by that rename.

    Only strips a flow_data node that carries an "id" — that's the one that
    would make package_service synthesize a competing flow (it already
    skips id-less ones on its own, see _workflow_derived_flows). An id-less
    flow_data can still be load-bearing on its own: Outpaint's per-engine
    files (outpaint_qwen_2511.json etc.) carry no id, only a `preprocess`
    block that refine_routes.py's _get_flow_preprocess() reads straight off
    the SUBMITTED workflow at generation time — stripping it unconditionally
    silently broke Outpaint's canvas-padding step (position/scale settings
    stopped doing anything, caught by hand-testing, not by any error)."""
    from app.services.flow_engine import _extract_flow_data_node

    meta = _extract_flow_data_node(graph)
    if meta is None or not str(meta.get("id", "")).strip():
        return
    for node_id, node in list(graph.items()):
        if isinstance(node, dict) and str(node.get("_meta", {}).get("title", "")) == "flow_data":
            del graph[node_id]
            return


def build_refine_static_group(
    source: Path, version: str, pkg_id: str, group_id: str,
    name: dict[str, str], summary: dict[str, str], flow_ids: list[str],
    unregistered: dict[str, str] | None = None,
    id_overrides: dict[str, str] | None = None,
    label_overrides: dict[str, dict[str, str]] | None = None,
    new_fields: dict[str, list[dict]] | None = None,
    group_overrides: dict[str, str] | None = None,
    hand_authored: list[dict] | None = None,
    extra_files: dict[str, object] | None = None,
    extra_contributes: dict | None = None,
    extra_texts: dict[str, dict[str, str]] | None = None,
    extra_i18n: dict[str, dict] | None = None,
    cover_image: Path | None = None,
) -> Path:
    """A Refine package whose flows all already have an authored flow.json
    (contributes.flows only, no flow_data-only ones — see build_refine_pilot
    for that path) — same shape as Create/Layout/CivitAI. group_id is set on
    the manifest for clarity/consistency with the docs, though these flows
    already declare their own group correctly (unlike the pilot's
    Edit/Outpaint, which had to be moved out of "core").

    `unregistered` is for a flow confirmed complete and working but missing
    its own index.json entry on the OPENHIKER side (e.g. pe_remove_glare) —
    {flow_id: path relative to app/instructions/}, loaded directly instead
    of through the index. `id_overrides`/`label_overrides` are keyed by the
    OLD id, same pattern as REFINE_PILOT_ID_OVERRIDES/LABEL_OVERRIDES.
    `group_overrides` re-buckets a flow into a different Refine-hub card
    than the `group` its source flow.json already declares (e.g. moving a
    handful of OPENHIKER's "core"-tagged flows into their own hub card) —
    same idea as REFINE_PILOT_GROUP_OVERRIDES. `hand_authored` is for flows
    with no OPENHIKER source at all (e.g. Local Editing: Region Selection) —
    a list of already-complete flow dicts (already carrying their own id/
    group/card texts) to fold in alongside the source-loaded ones, same
    pattern build_extract_pack used before this got generalized.
    `extra_files`/`extra_contributes` bolt on non-flow zip content — e.g. an
    `addon/` folder (contributes.addon, PACKAGE_FORMAT.md §9 minimal slice,
    see build_styling) — merged straight into the files dict and the
    manifest's contributes respectively, no other effect on this function.
    `extra_i18n` ({lang: {flow id: {path: text}}}) adds ready-made texts for
    flows that are not in `flows` — the addon's own flow.json."""
    table = load_translations(source)
    # Hand translations for UI strings the OPENHIKER table doesn't carry yet
    # (e.g. the style flows' step labels) — only fills gaps.
    for text, langs in (extra_texts or {}).items():
        table.setdefault(text, {}).update({k: v for k, v in langs.items() if k not in table.get(text, {})})
    files: dict[str, object] = {}
    flows = []
    workflow_refs: set[str] = set()
    unregistered = unregistered or {}
    id_overrides = id_overrides or {}
    label_overrides = label_overrides or {}
    new_fields = new_fields or {}
    group_overrides = group_overrides or {}
    hand_authored = hand_authored or []
    extra_files = extra_files or {}
    extra_contributes = extra_contributes or {}

    final_flow_ids: list[str] = []
    for flow_id in flow_ids:
        raw = (
            flow_from_path(source, unregistered[flow_id])
            if flow_id in unregistered
            else flow_from_source(source, flow_id)
        )
        flow = add_card_texts(raw, table)
        if flow_id in label_overrides:
            names = label_overrides[flow_id]
            flow["label"] = names["en"]
            flow["card"]["label"] = names
        if flow_id in group_overrides:
            flow["group"] = group_overrides[flow_id]
        for option_id, opt_overrides in QWEN_ENGINE_SELECT_OVERRIDES.items():
            _update_engine_select_option(flow, option_id, opt_overrides)
        for new_field in new_fields.get(flow_id, []):
            _add_flow_field(flow, new_field)
        _upgrade_seed_fields_to_similarity(flow)
        final_id = id_overrides.get(flow_id, flow_id)
        flow["id"] = final_id
        final_flow_ids.append(final_id)
        flows.append(flow)
        files[f"flows/{final_id.split('.', 1)[1]}.json"] = flow
        workflow_refs |= _collect_workflow_file_refs(flow)

    for raw_flow in hand_authored:
        # "_i18n_overrides" (popped, never written to the shipped flow.json):
        # {"label": {...}, "desc": {...}} hand translations for brand-new
        # wording that was never run through load_translations' table (keyed
        # by OLD English text) — same need REFINE_PILOT_DESC_OVERRIDES/
        # LABEL_OVERRIDES filled for the pilot's new flows.
        i18n_overrides = raw_flow.pop("_i18n_overrides", None)
        flow = add_card_texts(raw_flow, table)
        if i18n_overrides:
            if "label" in i18n_overrides:
                flow["card"]["label"] = i18n_overrides["label"]
            if "desc" in i18n_overrides:
                flow["card"]["desc"] = i18n_overrides["desc"]
        _upgrade_seed_fields_to_similarity(flow)
        flows.append(flow)
        final_flow_ids.append(flow["id"])
        files[f"flows/{flow['id'].split('.', 1)[1]}.json"] = flow
        workflow_refs |= _collect_workflow_file_refs(flow)

    for ref in sorted(workflow_refs):
        graph = _load_workflow_ref(source, ref)
        _strip_foreign_flow_data(graph)
        files[ref] = graph

    i18n, counts = flow_i18n(flows, table)
    for lang, by_flow in (extra_i18n or {}).items():
        if lang in i18n:
            i18n[lang].update(by_flow)
    manifest = {
        "schema_version": 1,
        "id": pkg_id,
        "version": version,
        "default_lang": "en",
        "name": name,
        "summary": summary,
        "author": AUTHOR,
        "license": "proprietary",
        "group": {"id": group_id, "label": {"en": name.get("en", group_id)}},
        "requires": {"engines": [{"category": "image"}]},
        "languages": ["en", *(lang for lang in LANGS if i18n[lang])],
        "contributes": {
            "flows": [f"flows/{fid.split('.', 1)[1]}.json" for fid in final_flow_ids],
            "workflows": sorted(workflow_refs),
            **extra_contributes,
        },
    }
    # The pack's own hub-card cover (NomadStudio#29): a picture for the set,
    # not borrowed from whichever preset happens to load first. New file name
    # on purpose — /packages/ files are served `immutable` for a year.
    if cover_image is not None:
        manifest["cover_image"] = "images/cover.webp"
        files["images/cover.webp"] = cover_image.read_bytes()
    print(f"  {pkg_id} texts: {counts['total']} · " + " ".join(f"{lang} {counts[lang]}" for lang in LANGS))
    return write_zip(pkg_id, {"manifest.json": manifest, **files, **extra_files, "LICENSE": LICENSE_TEXT,
                               **{f"i18n/{lang}.json": i18n[lang] for lang in LANGS if i18n[lang]}},
                      dest=DIST_OPTIONAL)


# Photo Editing / Portrait Fix / Creator Pack: each flow already carries its
# own correct "group" (unlike Edit/Outpaint, no override needed here).
PHOTO_EDITING_FLOWS = [
    "refine.pe_color_grading", "refine.pe_color_preset_cinema", "refine.pe_color_preset_editorial",
    "refine.pe_correct_enhance", "refine.pe_effects_artistic", "refine.pe_effects_cinematic",
    "refine.pe_open_eyes", "refine.pe_portrait_enhance", "refine.pe_portrait_retouch",
    "refine.qwen_2511_angles", "refine.pe_remove_hair_face",
    "refine.pe_remove_watermark", "refine.pe_restore",
    # Present and confirmed working, just missing its own index.json entry
    # (unlike refine/layer_composer.json and remove_checker.json, which are
    # genuinely broken/orphaned) — loaded via `unregistered` below instead
    # of the index.
    "refine.pe_remove_glare",
]
PHOTO_EDITING_UNREGISTERED = {
    "refine.pe_remove_glare": "flows/refine/photo-editing/pe_remove_glare.json",
}
PORTRAIT_FIX_FLOWS = [
    "refine.pf_change_hair_color", "refine.pf_dark_circles", "refine.pf_expression_changer",
    "refine.pf_hairstyle_changer", "refine.pf_hand_wrinkles", "refine.pf_red_eye_removal",
    "refine.pf_remove_freckles", "refine.pf_remove_glasses_glare",
    "refine.pf_remove_overexposed_highlights", "refine.pf_remove_skin_glare",
    # refine.pf_relight moved to nomad.refine-camera — lighting/camera looks
    # belong together, not split across two packages.
]
CREATOR_PACK_FLOWS = [
    "refine.cp_cartoon_to_realistic", "refine.cp_comic_book_style", "refine.cp_headshot_generator",
    "refine.cp_pet_portrait_generator", "refine.cp_profile_picture_generator", "refine.cp_selfie_generator",
    "refine.cp_silhouette_maker", "refine.cp_superhero_generator", "refine.cp_yearbook_generator",
]
# The 5 flows that are literally "remove/extract the background" out of the
# 13 still tagged group:"core" in OPENHIKER — split out into their own hub
# card instead of piling onto Edit/Outpaint/Upscale's existing "Core" (which
# already has 11). The other flows (Style Transfer, Pixel Art, Smart
# Selection — Skin Detailer and Camera Shoot already found homes) are a
# separate, not-yet-decided grouping.
BACKGROUND_TOOLS_FLOWS = [
    "refine.remove_bg", "refine.remove_bg_multi", "refine.remove_bg_simple",
    "refine.extract_background_boogu", "refine.extract_background_klein9b",
]
BACKGROUND_TOOLS_GROUP_OVERRIDES = {fid: "background-tools" for fid in BACKGROUND_TOOLS_FLOWS}
# Skin Detailer adds fine texture/pore detail rather than removing anything —
# closer in spirit to Upscale (more fidelity/resolution) than to any of the
# above, so it joins the existing "upscale" hub group (nomad.core-refine's
# Upscale (Model/Klein 4B/Klein 9B/Qwen 2.1/SeedVR2)) instead of getting a
# card of its own for just 2 flows.
SKIN_DETAILER_FLOWS = ["refine.skin_detailer_klein_4b", "refine.skin_detailer_klein_9b"]
SKIN_DETAILER_GROUP_OVERRIDES = {fid: "upscale" for fid in SKIN_DETAILER_FLOWS}
# Style Transfer (re-render in a saved Style's visual language) and Pixel Art
# (70+ curated style presets) are both "restyle the whole image" tools —
# last 3 of the original 13 core-tagged leftovers, rounding out the Refine
# packaging work.
# Style Transfer Klein 4B/9B are rebuilt by hand (_style_transfer_text_flows) —
# their OPENHIKER flow.json targets nodes the source graph no longer has.
STYLING_FLOWS = ["refine.pixel_art_klein_9b"]
STYLING_GROUP_OVERRIDES = {fid: "styling" for fid in STYLING_FLOWS}
REFINE_GROUPS_VERSION = "0.1.0"


def _vintage_flows(source: Path) -> list[dict]:
    """The 4 Vintage flows (tools/packages/vintage_presets.py), cloned from
    Effects Artistic so they share its engines, steps and buttons — only id,
    texts and the preset list change."""
    base = flow_from_source(source, "refine.pe_effects_artistic")
    flows = []
    for family in VINTAGE_FAMILIES:
        flow = copy.deepcopy(base)
        flow.update({
            "id": f"refine.{family['slug']}",
            "label": family["label"]["en"],
            "description": family["desc"]["en"],
            "card_desc": family["desc"]["en"],
            "card_tags": family["tags"],
            "_i18n_overrides": {"label": family["label"], "desc": family["desc"]},
        })
        flow.pop("card", None)
        # Source flows get this in build_refine_static_group; hand-authored
        # ones skip that loop, so the clone needs it here (Qwen 2.1 label/steps).
        for option_id, opt_overrides in QWEN_ENGINE_SELECT_OVERRIDES.items():
            _update_engine_select_option(flow, option_id, opt_overrides)
        for step in flow["steps"]:
            for field in step.get("fields") or []:
                if field.get("id") == "prompt":
                    field["presets"] = copy.deepcopy(family["presets"])
                    field["default"] = family["presets"][0]["text"]
                    field["tooltip"] = "Pick a vintage look, or write your own."
        flows.append(flow)
    return flows


def build_photo_editing(source: Path, version: str) -> Path:
    return build_refine_static_group(
        source, version, "nomad.refine-photo-editing", "photo-editing",
        name={"en": "Photo Editing", "es": "Edición de fotos", "zh": "照片编辑", "ko": "사진 편집"},
        summary={
            "en": "Color grading, cinematic looks, restoration, watermark/glare removal, camera-angle changes, "
                  "region-based local editing and in-image text replacement.",
            "es": "Gradación de color, looks cinematográficos, restauración, quitar marcas de agua/brillos, "
                  "cambio de ángulo de cámara, edición local por región y sustitución de texto en la imagen.",
            "zh": "调色、电影感风格、修复、去除水印/眩光、机位角度调整、基于区域的局部编辑以及图像内文字替换。",
            "ko": "컬러 그레이딩, 시네마틱 룩, 복원, 워터마크/글레어 제거, 카메라 앵글 변경, 영역 기반 로컬 편집, "
                  "이미지 내 텍스트 교체.",
        },
        flow_ids=PHOTO_EDITING_FLOWS,
        unregistered=PHOTO_EDITING_UNREGISTERED,
        # Angles was migrated to bare Qwen 2.1 (no LoRA) earlier, but
        # hand-testing showed 2.1 doesn't reproduce the viewpoint change
        # reliably without the "multiple-angles" LoRA — reverted to the
        # source's own Qwen 2511 + LoRA workflow verbatim (see
        # _load_workflow_ref: no more override for this ref), so id/label/
        # steps stay whatever the source itself declares (fixed 4-step
        # Lightning LoRA setup, no exposed Steps field).
        hand_authored=[_local_edit_qwen2_flow(), _text_editor_qwen2_flow(), _text_editor_klein9b_flow(),
                       *_vintage_flows(source)],
        extra_texts=VINTAGE_UI_TEXTS,
    )


def build_portrait_fix(source: Path, version: str) -> Path:
    return build_refine_static_group(
        source, version, "nomad.refine-portrait-fix", "portrait-fix",
        name={"en": "Portrait Fix", "es": "Retoque de retrato", "zh": "人像修饰", "ko": "인물 보정"},
        summary={
            "en": "Targeted portrait fixes: hair color/style, dark circles, expression, relight, red-eye, glare and more.",
            "es": "Arreglos concretos de retrato: color/estilo de pelo, ojeras, expresión, relight, ojos rojos, brillos y más.",
            "zh": "针对性人像修饰：发色/发型、黑眼圈、表情、重新布光、红眼、眩光等。",
            "ko": "타깃 인물 보정: 헤어 컬러/스타일, 다크서클, 표정, 리라이팅, 적목 현상, 글레어 등.",
        },
        flow_ids=PORTRAIT_FIX_FLOWS,
    )


def build_creator_pack(source: Path, version: str) -> Path:
    return build_refine_static_group(
        source, version, "nomad.refine-creator-pack", "creator-pack",
        name={"en": "Creator Pack", "es": "Pack Creador", "zh": "创作者礼包", "ko": "크리에이터 팩"},
        summary={
            "en": "Ready-made looks: headshot, selfie, profile picture, pet portrait, superhero, comic book and more.",
            "es": "Looks ya hechos: headshot, selfie, foto de perfil, retrato de mascota, superhéroe, cómic y más.",
            "zh": "现成风格：形象照、自拍、头像、宠物肖像、超级英雄、漫画风格等。",
            "ko": "완성형 룩: 헤드샷, 셀카, 프로필 사진, 반려동물 초상화, 슈퍼히어로, 만화 스타일 등.",
        },
        flow_ids=CREATOR_PACK_FLOWS,
    )


# ── Background Swap — new flows, no OPENHIKER source (the 2 candidates from
# the "Refine (single image input)" template list that weren't already
# covered by an existing flow — see build_background_tools's summary for the
# rest, already redundant with Remove Background/Extract/Portrait Fix/Local
# Editing). Two engine variants so they can be compared directly: Qwen Image
# 2.1 (shared edit graph, same as every other Qwen-engine single-image flow)
# and Flux 2 Klein 9B (referenced straight from OPENHIKER's own
# refine_flux2_klein_9b.json — no hand-authored graph override needed here,
# unlike Qwen 2.1, since Klein's source graph works as-is; image_node "76"
# and its RandomNoise/CFGGuider/SamplerCustomAdvanced "advanced sampling"
# node ids come straight from that source flow).
BG_SWAP_PRESETS = [
    {
        "label": "Describe the new background",
        "text": "Keep the subject, pose, and lighting on the subject unchanged. Replace only the background "
                "with [NEW BACKGROUND DESCRIPTION]. Match the new background's light direction and color "
                "temperature to the subject so it looks naturally photographed there.",
    },
]


def _bg_swap_qwen2_flow() -> dict:
    return {
        "id": "refine.bg_swap_qwen2",
        "label": "Background Swap — Qwen 2.1",
        "category": "refine",
        "group": "background-tools",
        "description": "Replace the background of a photo with a new one you describe, keeping the subject, "
                        "pose and lighting untouched, using Qwen Image 2.1.",
        "card_desc": "Swap the background for one you describe, keeping the subject and its lighting untouched.",
        "card_tags": ["Qwen", "2.1", "Background", "Swap"],
        "card_css_modifier": "edit-qwen-2511",
        "llm_required": False,
        "comfyui_required": True,
        "steps": [
            {"id": "image", "type": "image_picker", "label": "Source image", "required": True},
            {
                "id": "params",
                "type": "workflow_params",
                "label": "Parameters",
                "workflow_file": QWEN_2511_EDIT_WORKFLOW_REL,
                "image_node": "7",
                "fields": [
                    {
                        "id": "prompt",
                        "adv_key": "13.prompt",
                        "label": "New background",
                        "type": "textarea",
                        "rows": 4,
                        "block": True,
                        "tooltip": "Describe the new background — pick the template and fill in the bracketed "
                                   "part, or write your own.",
                        "default": BG_SWAP_PRESETS[0]["text"],
                        "presets": BG_SWAP_PRESETS,
                    },
                    {
                        "id": "steps", "adv_key": "15.steps", "label": "Steps", "type": "number",
                        "default": 25, "min": 1, "max": 25, "step": 1, "quick_options": [8, 16, 25], "advanced": True,
                    },
                    {"id": "seed", "adv_key": "15.seed", "label": "Seed", "type": "seed", "advanced": True},
                ],
            },
            {
                "id": "generate",
                "type": "action",
                "label": "Generate",
                "calls": "generation.submit_refine",
                "input_map": {
                    "workflowFile": "steps.params.output.workflow_file",
                    "imageDataUrl": "steps.image.output.image_data_url",
                    "advancedValues": "steps.params.output.adv_values",
                },
            },
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Refine",
        "entry_model": "Qwen Image 2.1 Edit",
        "_i18n_overrides": {
            "label": {
                "en": "Background Swap — Qwen 2.1", "es": "Cambio de fondo — Qwen 2.1",
                "zh": "背景替换 — Qwen 2.1", "ko": "배경 교체 — Qwen 2.1",
            },
            "desc": {
                "en": "Swap the background for one you describe, keeping the subject and its lighting untouched.",
                "es": "Cambia el fondo por uno que describas, sin tocar el sujeto ni su iluminación.",
                "zh": "将背景替换为你描述的新背景，主体及其光照保持不变。",
                "ko": "묘사한 새 배경으로 교체 — 피사체와 조명은 그대로 유지합니다.",
            },
        },
    }


def _bg_swap_klein9b_flow() -> dict:
    return {
        "id": "refine.bg_swap_klein9b",
        "label": "Background Swap — Klein 9B",
        "category": "refine",
        "group": "background-tools",
        "description": "Replace the background of a photo with a new one you describe, keeping the subject, "
                        "pose and lighting untouched, using Flux 2 Klein 9B.",
        "card_desc": "Swap the background for one you describe, keeping the subject and its lighting untouched.",
        "card_tags": ["Klein", "9B", "Background", "Swap"],
        "card_css_modifier": "edit-fluxklein",
        "llm_required": False,
        "comfyui_required": True,
        "steps": [
            {"id": "image", "type": "image_picker", "label": "Source image", "required": True},
            {
                "id": "params",
                "type": "workflow_params",
                "label": "Parameters",
                "workflow_file": "workflows/refine/refine_flux2_klein_9b.json",
                "image_node": "76",
                "fields": [
                    {
                        "id": "prompt",
                        "adv_key": "139.text",
                        "label": "New background",
                        "type": "textarea",
                        "rows": 4,
                        "block": True,
                        "tooltip": "Describe the new background — pick the template and fill in the bracketed "
                                   "part, or write your own.",
                        "default": BG_SWAP_PRESETS[0]["text"],
                        "presets": BG_SWAP_PRESETS,
                    },
                    {
                        "id": "steps", "adv_key": "132.steps", "label": "Steps", "type": "number",
                        "default": 4, "min": 1, "max": 40, "step": 1, "quick_options": [4, 8], "advanced": True,
                    },
                    {
                        "id": "cfg", "adv_key": "133.cfg", "label": "CFG", "type": "number",
                        "default": 1, "min": 0, "max": 10, "step": 0.5, "advanced": True,
                    },
                    {"id": "seed", "adv_key": "136.noise_seed", "label": "Seed", "type": "seed", "advanced": True},
                ],
            },
            {
                "id": "generate",
                "type": "action",
                "label": "Generate",
                "calls": "generation.submit_refine",
                "input_map": {
                    "workflowFile": "steps.params.output.workflow_file",
                    "imageDataUrl": "steps.image.output.image_data_url",
                    "advancedValues": "steps.params.output.adv_values",
                },
            },
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Refine",
        "entry_model": "Flux 2 Klein",
        "_i18n_overrides": {
            "label": {
                "en": "Background Swap — Klein 9B", "es": "Cambio de fondo — Klein 9B",
                "zh": "背景替换 — Klein 9B", "ko": "배경 교체 — Klein 9B",
            },
            "desc": {
                "en": "Swap the background for one you describe, keeping the subject and its lighting untouched.",
                "es": "Cambia el fondo por uno que describas, sin tocar el sujeto ni su iluminación.",
                "zh": "将背景替换为你描述的新背景，主体及其光照保持不变。",
                "ko": "묘사한 새 배경으로 교체 — 피사체와 조명은 그대로 유지합니다.",
            },
        },
    }


def build_background_tools(source: Path, version: str) -> Path:
    return build_refine_static_group(
        source, version, "nomad.refine-background-tools", "background-tools",
        name={"en": "Background Tools", "es": "Herramientas de fondo", "zh": "背景工具", "ko": "배경 도구"},
        summary={
            "en": "Remove or extract the background — BiRefNet, multi-subject, simple, and edit-model variants. "
                  "Plus Background Swap: replace it with one you describe, on Qwen 2.1 or Flux 2 Klein 9B.",
            "es": "Quita o extrae el fondo — BiRefNet, multi-sujeto, simple y variantes por modelo de edición. "
                  "Y Cambio de fondo: sustitúyelo por uno que describas, con Qwen 2.1 o Flux 2 Klein 9B.",
            "zh": "去除或提取背景 —— BiRefNet、多主体、简易及编辑模型变体。还有背景替换：用 Qwen 2.1 或 "
                  "Flux 2 Klein 9B 替换为你描述的新背景。",
            "ko": "배경 제거 또는 추출 — BiRefNet, 다중 피사체, 심플, 편집 모델 변형. 그리고 배경 교체: "
                  "Qwen 2.1 또는 Flux 2 Klein 9B로 묘사한 배경으로 교체.",
        },
        flow_ids=BACKGROUND_TOOLS_FLOWS,
        group_overrides=BACKGROUND_TOOLS_GROUP_OVERRIDES,
        hand_authored=[_bg_swap_qwen2_flow(), _bg_swap_klein9b_flow()],
    )


def build_skin_detailer(source: Path, version: str) -> Path:
    return build_refine_static_group(
        source, version, "nomad.refine-skin-detailer", "upscale",
        name={"en": "Skin Detailer", "es": "Detalle de piel", "zh": "皮肤细节", "ko": "피부 디테일"},
        summary={
            "en": "Add realistic skin texture and pore detail to a portrait, preserving color, exposure and identity — Klein 4B or Klein 9B.",
            "es": "Añade textura de piel y detalle de poro realista a un retrato, preservando color, exposición e identidad — Klein 4B o Klein 9B.",
            "zh": "为人像添加逼真的皮肤纹理和毛孔细节，保留颜色、曝光和身份特征——Klein 4B 或 Klein 9B。",
            "ko": "인물 사진에 사실적인 피부 텍스처와 모공 디테일을 추가하며 색상, 노출, 정체성을 유지합니다 — Klein 4B 또는 Klein 9B.",
        },
        flow_ids=SKIN_DETAILER_FLOWS,
        group_overrides=SKIN_DETAILER_GROUP_OVERRIDES,
    )


def _pixel_art_qwen2_flow(source: Path) -> dict:
    """Pixel Art, retargeted to the Qwen 2.1 engine — reuses the Klein 9B
    source's 70+ style presets (10 groups) verbatim, only rewiring
    adv_key/workflow_file/image_node to the Qwen 2.1 graph's node ids
    (13=TextEncodeQwenImage21, 15=KSampler) instead of Klein 9B's
    (165=CLIPTextEncode, 159=Flux2Scheduler, 154=RandomNoise). Hand-tested
    by the user and confirmed working — unlike Camera Shoot's Qwen 2.1
    attempt, kept as a second engine option alongside Klein 9B rather than
    replacing it, since both are known-good."""
    flow = json.loads(json.dumps(flow_from_source(source, "refine.pixel_art_klein_9b")))
    flow["id"] = "refine.pixel_art_qwen2"
    flow["label"] = "Pixel Art — Qwen 2.1"
    flow["group"] = "styling"
    flow["card_css_modifier"] = "edit-qwen-2511"
    flow["description"] = "Apply a curated pixel-art visual style to your image using Qwen Image 2.1. 70+ styles in 10 groups."
    flow["card_desc"] = "70+ curated pixel-art styles, on Qwen Image 2.1."
    flow["card_tags"] = ["Qwen", "2.1", "Pixel Art", "Style"]
    for step in flow.get("steps", []):
        if step.get("type") != "workflow_params":
            continue
        step["workflow_file"] = QWEN_2511_EDIT_WORKFLOW_REL
        step["image_node"] = "7"
        for f in step.get("fields", []):
            if f.get("id") in ("style", "style_preview"):
                f["adv_key"] = "13.prompt"
            elif f.get("id") == "steps":
                f["adv_key"] = "15.steps"
                f["default"] = 25
                f["max"] = 25
                f["quick_options"] = [8, 16, 25]
            elif f.get("id") == "seed":
                f["adv_key"] = "15.seed"
    flow["_i18n_overrides"] = {
        "label": {
            "en": "Pixel Art — Qwen 2.1", "es": "Pixel Art — Qwen 2.1",
            "zh": "像素艺术 — Qwen 2.1", "ko": "픽셀 아트 — Qwen 2.1",
        },
        "desc": {
            "en": "70+ curated pixel-art styles, on Qwen Image 2.1.",
            "es": "Más de 70 estilos curados de pixel art, en Qwen Image 2.1.",
            "zh": "70 多种精选像素艺术风格，基于 Qwen Image 2.1。",
            "ko": "70개 이상의 엄선된 픽셀 아트 스타일, Qwen Image 2.1 기반.",
        },
    }
    return flow


# Pixel Matcher (contributes.addon, PACKAGE_FORMAT.md §9 minimal slice —
# see build_refine_static_group's extra_files/extra_contributes): local,
# no-AI pixel-art conversion (KMeans or an imported .pal/.gpl/.hex palette),
# the natural next step after Pixel Art's AI-model presets. Its source lives
# in THIS repo, tools/packages/addons/pixel_matcher/ (not in --source), and
# is bundled as source text into Styling's zip under addon/. The folder's
# i18n.json ({lang: {path: text}}, §7.2 paths) is merged into the package's
# own i18n/<lang>.json under the flow's id.
# Installing this package extracts addon/ to data/packages/<pkg>/addon/;
# app/services/addon_loader.py picks it up from there on the NEXT app
# start (no hot-load).
PIXEL_MATCHER_ADDON_DIR = Path(__file__).with_name("addons") / "pixel_matcher"


def _pixel_matcher_addon_contribution() -> tuple[dict[str, str], dict, dict[str, dict]]:
    addon_dir = PIXEL_MATCHER_ADDON_DIR
    files = {
        f"addon/{name}": (addon_dir / name).read_text(encoding="utf-8")
        for name in ("__init__.py", "routes.py", "service.py", "palettes.py", "default_palettes.json")
    }
    flow = json.loads((addon_dir / "flow.json").read_text(encoding="utf-8"))
    flow["group"] = "styling"
    files["addon/flow.json"] = json.dumps(flow, indent=2, ensure_ascii=False)
    texts = json.loads((addon_dir / "i18n.json").read_text(encoding="utf-8"))
    i18n = {lang: {flow["id"]: by_path} for lang, by_path in texts.items() if by_path}
    return files, {"addon": {"entry": "addon/__init__.py"}}, i18n


# ── Style Transfer across Create / Refine / Mix ──────────────────────────────
# One idea, three inputs (user's framing, 2026-09-23):
#   Create — style as TEXT (Build > Styles prefix/suffix, create flows' own
#            style picker; nothing to package here).
#   Refine — one image + a style, either as TEXT (style_picker, below:
#            Klein 9B/4B + Qwen 2.1 on each engine's plain edit graph) or as
#            an IMAGE reference (Anima / USO / Z-Image — describe a scene,
#            borrow the look of a reference picture).
#   Mix    — image + image: content photo + style reference (Klein RF
#            Inversion, Qwen 2511, Klein Styler, Klein Migration, USO
#            Style+Subject, and a new Qwen Image 2.1 one).
#
# The OPENHIKER Refine/Mix style flows only exist as `flow_data` nodes inside
# their ComfyUI graphs. They're turned into static flow.json files HERE, at
# build time, with the app's own converters (flow_engine._build_*_flow_
# definition — the same code package_service would run at install), so they
# can carry hand-translated card texts like every other packaged flow; the
# embedded flow_data is then stripped (_strip_foreign_flow_data).
#
# The two old "Style Transfer · Klein 4B/9B" Refine flows pointed at nodes
# 76/165/159/154 of an older single-image graph; OPENHIKER later rewrote that
# same file as two-image RF Inversion (629/612/607), leaving both flows
# broken there too. They're rebuilt below on Klein's plain edit graph,
# keeping their ids so existing installs update in place.
STYLE_TRANSFER_QWEN21_WORKFLOW_REL = "workflows/mix/style_transfer_qwen21.json"
ANIMA_STYLE_WORKFLOW_REL = "workflows/refine/refine_style_transfer_anima.json"

# Model files as this install's ComfyUI actually has them (checked against
# /object_info 2026-09-23): the Anima graph asks for "Anima\\…" and turbo
# LoRA v0.2, the machine has the UNET at the root and LoRA v0.1 only.
ANIMA_MODEL_FIXES = {
    "623": {"unet_name": "anima_baseV10.safetensors"},
    "636": {"lora_name": "anima-turbo-lora-v0.1.safetensors"},
}


def _qwen_image_21_style_transfer_workflow() -> dict:
    """Qwen Image 2.1 two-image style transfer: node 8 = the style
    reference (<image1>, the flow's first picker), node 7 = the photo to
    restyle (<image2>, second picker; still sizes the output via
    GetImageSize). Image numbers follow the pickers' order on screen so the
    prompt's <image1>/<image2> read the way the user sees them. Same
    loaders/sampler as the Edit graph."""
    graph = _qwen_image_21_edit_workflow()
    graph["8"] = {
        "inputs": {"image": "oj-mix-placeholder-2.png"},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image (style reference)"},
    }
    graph["7"]["_meta"]["title"] = "Load Image (image to restyle)"
    graph["13"]["inputs"]["images.image_1"] = ["8", 0]
    graph["13"]["inputs"]["images.image_2"] = ["7", 0]
    graph["21"]["inputs"]["filename_prefix"] = "qwen-image-2.1-style-transfer"
    return graph


# Style Reference on Flux 2 Klein: the Mix Klein graph is exactly the
# Z-Image Style Reference graph plus the content photo (629 LoadImage, 630
# its scale, 631 ConditioningAddImageReference). Dropping those three and
# wiring the prompt (607) straight into the guider and RF Inversion — with the
# style image's own scale (265) sizing the empty latent (282), as in Z-Image —
# turns it into "one style image + a described scene". Everything else
# (RF Inversion 603, Untwisting RoPE 623, Unofficial Extensions 637, sampler,
# the `config` node's quantization options) stays as in the source.
STYLE_REFERENCE_KLEIN_4B_WORKFLOW_REL = "workflows/refine/refine_style_reference_klein_4b.json"
STYLE_REFERENCE_KLEIN_9B_WORKFLOW_REL = "workflows/refine/refine_style_reference_klein_9b.json"
# Qwen Image Edit 2511 (+ Lightning LoRA, node 635) — the Qwen-Image family
# Untwisting RoPE supports. Qwen Image 2.1 is NOT: its single-stream
# transformer (QwenImage21) has no adapter in the node.
STYLE_REFERENCE_QWEN_2511_WORKFLOWS = {
    "workflows/refine/refine_style_reference_qwen_2511.json": "workflows/refine/refine_style_transfer_qwen_2511.json",
    "workflows/refine/refine_style_reference_qwen_2511_turbo.json":
        "workflows/refine/refine_style_transfer_qwen_2511_turbo.json",
}


def _klein_style_reference_workflow(source: Path, variant: str) -> dict:
    return _rf_style_reference_workflow(source, f"workflows/refine/refine_style_transfer_klein_{variant}.json")


def _rf_style_reference_workflow(source: Path, mix_rel: str) -> dict:
    """Any two-image RF Inversion Mix graph (Klein, Qwen Edit 2511) → the
    one-image Style Reference graph — same node surgery for all of them."""
    variant = mix_rel
    graph = json.loads((source / "app" / mix_rel).read_text(encoding="utf-8"))
    graph.pop("flow_data", None)
    for node_id in ("629", "630", "631"):
        graph.pop(node_id, None)
    graph["559"]["inputs"]["positive"] = ["607", 0]
    graph["603"]["inputs"]["ref_conditioning"] = ["607", 0]
    for key in ("width", "height"):
        graph["265"]["inputs"].pop(key, None)
    graph["265"]["inputs"]["megapixels"] = 1
    graph["265"]["_meta"]["title"] = "Scale Image to Total Pixels Adv"
    graph["282"]["inputs"]["width"] = ["265", 1]
    graph["282"]["inputs"]["height"] = ["265", 2]
    graph["607"]["_meta"]["title"] = "CLIP Text Encode (Prompt)"
    graph["612"]["_meta"]["title"] = "Load Image (style reference)"
    dangling = [(nid, k) for nid, n in graph.items() if isinstance(n, dict)
                for k, v in (n.get("inputs") or {}).items()
                if isinstance(v, list) and v and str(v[0]) not in graph]
    if dangling:
        raise SystemExit(f"style reference graph from {variant} has dangling links: {dangling}")
    return graph


def _anima_style_workflow(source: Path) -> dict:
    graph = json.loads((source / "app" / ANIMA_STYLE_WORKFLOW_REL).read_text(encoding="utf-8"))
    for node_id, inputs in ANIMA_MODEL_FIXES.items():
        graph[node_id]["inputs"].update(inputs)
    return graph


def _flow_from_embedded_flow_data(source: Path, rel: str, group: str) -> dict:
    """Static flow.json from an OPENHIKER graph's flow_data node, built by the
    app's own converter (see the section comment)."""
    from app.services.flow_engine import (
        _build_mix_flow_definition,
        _build_refine_flow_definition,
        _extract_flow_data_node,
    )

    meta = _extract_flow_data_node(json.loads((source / "app" / rel).read_text(encoding="utf-8")))
    if not meta or not meta.get("id"):
        raise SystemExit(f"no flow_data with an id in {rel}")
    is_mix = str(meta.get("category", "")) == "mix" or str(meta["id"]).startswith("mix.")
    flow = (_build_mix_flow_definition if is_mix else _build_refine_flow_definition)(meta, rel)
    flow["group"] = group
    for key in ("entry_category", "entry_model"):
        if meta.get(key):
            flow[key] = meta[key]
    return flow


STYLE_TRANSFER_KEEP_LAYOUT = ("Restyle this image, keeping its exact composition, subjects, poses and layout")


def _style_transfer_text_flow(flow_id: str, engine_label: str, workflow_file: str, image_node: str,
                              prompt_key: str, param_fields: list[dict], css: str, entry_model: str,
                              i18n: dict) -> dict:
    """Refine: one image + a style as TEXT. The style_picker wraps the
    'keep the layout' instruction with the chosen Style's prefix/suffix."""
    return {
        "id": flow_id,
        "label": f"Style Transfer — {engine_label}",
        "category": "refine",
        "group": "styling",
        "description": _ST_TEXT_DESC["en"],
        "card_desc": "Restyle a photo with one of your saved Styles, keeping its composition.",
        "card_tags": [engine_label.split()[0], "Style", "Text"],
        "card_css_modifier": css,
        "llm_required": False,
        "comfyui_required": True,
        "steps": [
            {"id": "image", "type": "image_picker", "label": "Source image", "required": True, "multiple": True},
            {
                "id": "params",
                "type": "workflow_params",
                "label": "Parameters",
                "workflow_file": workflow_file,
                "image_node": image_node,
                "fields": [
                    {
                        "id": "style", "adv_key": prompt_key, "label": "Style", "type": "style_picker",
                        "rows": 4, "default": STYLE_TRANSFER_KEEP_LAYOUT,
                        "placeholder": "Choose a style — it wraps this instruction with the style's wording.",
                    },
                    *param_fields,
                ],
            },
            {
                "id": "generate",
                "type": "action",
                "label": "Generate",
                "calls": "generation.submit_refine",
                "input_map": {
                    "workflowFile": "steps.params.output.workflow_file",
                    "imageDataUrl": "steps.image.output.image_data_url",
                    "advancedValues": "steps.params.output.adv_values",
                    "cardPrompt": "steps.params.output.field_style",
                },
            },
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Style",
        "entry_model": entry_model,
        "_i18n_overrides": i18n,
    }


_ST_TEXT_DESC = {
    "en": "Restyle a photo with one of your saved Styles, keeping its composition.",
    "es": "Reestiliza una foto con uno de tus Estilos guardados, manteniendo su composición.",
    "zh": "用你保存的风格重新演绎照片，保留原有构图。",
    "ko": "저장된 스타일로 사진을 재스타일링하고 구도는 그대로 유지합니다.",
}


def _style_transfer_text_flows() -> list[dict]:
    klein_fields = [
        {"id": "steps", "adv_key": "132.steps", "label": "Steps", "type": "number",
         "default": 4, "min": 1, "max": 40, "step": 1, "quick_options": [4, 8], "advanced": True},
        {"id": "cfg", "adv_key": "133.cfg", "label": "CFG", "type": "number",
         "default": 1, "min": 0, "max": 10, "step": 0.5, "advanced": True},
        {"id": "seed", "adv_key": "136.noise_seed", "label": "Seed", "type": "seed", "advanced": True},
    ]
    qwen_fields = [
        {"id": "steps", "adv_key": "15.steps", "label": "Steps", "type": "number",
         "default": 25, "min": 1, "max": 25, "step": 1, "quick_options": [8, 16, 25], "advanced": True},
        {"id": "seed", "adv_key": "15.seed", "label": "Seed", "type": "seed", "advanced": True},
    ]

    def names(engine: str) -> dict:
        return {"label": {"en": f"Style Transfer — {engine}", "es": f"Transferencia de estilo — {engine}",
                          "zh": f"风格迁移 — {engine}", "ko": f"스타일 전이 — {engine}"},
                "desc": _ST_TEXT_DESC}

    return [
        _style_transfer_text_flow("refine.style_transfer_klein_9b", "Klein 9B",
                                  "workflows/refine/refine_flux2_klein_9b.json", "76", "139.text",
                                  klein_fields, "edit-fluxklein", "Flux 2 Klein", names("Klein 9B")),
        _style_transfer_text_flow("refine.style_transfer_klein_4b", "Klein 4B",
                                  "workflows/refine/refine_flux2_klein_4b.json", "76", "139.text",
                                  klein_fields, "edit-fluxklein", "Flux 2 Klein", names("Klein 4B")),
        _style_transfer_text_flow("refine.style_transfer_qwen2", "Qwen 2.1", QWEN_2511_EDIT_WORKFLOW_REL,
                                  "7", "13.prompt", qwen_fields, "edit-qwen-2511", "Qwen Image 2.1 Edit",
                                  names("Qwen 2.1")),
    ]


# Create: style as TEXT. Shipped in the Styling package too (its manifest
# group "styling" gives them their own "Styling" group in the Create hub).
# `style_picker` on a prompt_input (flow-step-prompt-input.js) opens the
# Build > Styles catalog and wraps the box's text with the style's
# prefix/suffix. OPENHIKER only ever had create.style as a "planned" index
# entry with no flow file — both flows are new.
STYLE_BLEND_SYSTEM_PROMPT = (
    "You write prompts for AI image generation. You get the user's idea and a Style: a list of visual "
    "keywords (medium, technique, palette, lighting, texture).\n"
    "Write ONE image prompt that shows the idea's subject and scene rendered in that style.\n"
    "Rules:\n"
    "- Keep every concrete element of the idea; do not add new subjects.\n"
    "- Weave the style's visual keywords into the description naturally instead of pasting them as a list.\n"
    "- No text, captions, signatures or logos in the image unless the idea asks for them.\n"
    "- Suitable for a general audience.\n"
    "- Under 90 words. Reply with the prompt only: no quotes, no preamble."
)

_CREATE_PARAMS_STEP = {"id": "params", "type": "param_group", "label": "Parameters",
                       "fields": ["seed", "steps", "cfg", "num_images"], "collapsed_by_default": True}


def _create_style_flows() -> list[dict]:
    direct = {
        "id": "create.style",
        "label": "Style",
        "category": "create",
        "group": "styling",
        "description": "Write your idea and wrap it in one of your saved Styles, then generate.",
        "card_desc": "Write your idea, pick a style from your catalog, generate. No AI needed.",
        "card_tags": ["Style", "No LLM", "Fast"],
        "card_css_modifier": "style",
        "llm_required": False,
        "comfyui_required": True,
        "steps": [
            {"id": "workflow", "type": "workflow_picker", "label": "Choose engine", "required": True,
             "auto_select_if_single": True},
            # The idea box stays the idea; the picked style is kept apart
            # (style_picker "separate") and the box below shows — and sends —
            # "prefix, idea, suffix", still editable by hand.
            {"id": "idea", "type": "prompt_input", "label": "Your idea", "required": True, "rows": 3,
             "style_picker": "separate", "drop_image_prompt": True,
             "placeholder": "Describe what you want, then pick a style with the palette button."},
            {"id": "prompt", "type": "prompt_input", "label": "Final prompt", "rows": 5,
             "style_compose_from": "idea",
             "placeholder": "Your idea wrapped in the style's wording — edit it if you like."},
            _CREATE_PARAMS_STEP,
            {"id": "generate", "type": "action", "label": "Generate Image", "calls": "generation.submit_queue",
             "input_map": {"basicValues.positive": "steps.prompt.output.prompt_text || steps.idea.output.prompt_text",
                           "basicValues.seed": "steps.params.output.basic_values.seed",
                           "numImages": "steps.params.output.basic_values.num_images"}},
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Style",
        "entry_model": "Local",
        "complexity": 1,
        "_i18n_overrides": {
            "label": {"en": "Style", "es": "Estilo", "zh": "风格", "ko": "스타일"},
            "desc": {"en": "Write your idea, pick a style from your catalog, generate. No AI needed.",
                     "es": "Escribe tu idea, elige un estilo de tu catálogo y genera. Sin IA de texto.",
                     "zh": "写下你的想法，从风格库中选择一种风格，然后生成。无需 AI。",
                     "ko": "아이디어를 쓰고 카탈로그에서 스타일을 골라 생성합니다. AI 불필요."},
        },
    }
    blend = {
        "id": "create.style_ai",
        "label": "Style + AI",
        "category": "create",
        "group": "styling",
        "description": "The local AI blends your idea with one of your saved Styles into a single, well-written prompt.",
        "card_desc": "Pick a style from your catalog — the AI blends it with your idea into a single prompt.",
        "card_tags": ["Style", "Assist", "Blend"],
        "card_css_modifier": "style",
        "llm_required": True,
        "comfyui_required": True,
        "steps": [
            {"id": "workflow", "type": "workflow_picker", "label": "Choose engine", "required": True,
             "auto_select_if_single": True},
            {"id": "idea", "type": "prompt_input", "label": "Your idea", "required": True, "rows": 3,
             "drop_image_prompt": True, "placeholder": "A rough idea is enough — the AI will blend it with the style…"},
            {"id": "style", "type": "prompt_input", "label": "Style", "required": False, "rows": 3,
             "style_picker": True, "placeholder": "Pick a style from your catalog, or describe one…"},
            {
                "id": "blend",
                "type": "llm_transform",
                "label": "Blend with AI",
                "calls": "llm.studio_enhance",
                "input_from": "steps.idea.output.prompt_text",
                "context_from": {"reference_prompt": [{"label": "Style", "ref": "steps.style.output.prompt_text"}]},
                "params": {"level": {"type": "user_choice", "options": ["style"], "default": "style"}},
                "system_prompts": {"style": STYLE_BLEND_SYSTEM_PROMPT},
                "output_to": "prompt",
                "editable_output": True,
            },
            {"id": "prompt", "type": "prompt_input", "label": "Final prompt", "rows": 5,
             "prefill_from": "steps.blend.output.transformed_text", "drop_image_prompt": True,
             "placeholder": "You can edit this later"},
            _CREATE_PARAMS_STEP,
            {"id": "generate", "type": "action", "label": "Generate Image", "calls": "generation.submit_queue",
             "input_map": {"basicValues.positive": "steps.prompt.output.prompt_text || steps.idea.output.prompt_text",
                           "basicValues.seed": "steps.params.output.basic_values.seed",
                           "numImages": "steps.params.output.basic_values.num_images"}},
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Style",
        "entry_model": "Local",
        "complexity": 1,
        "_i18n_overrides": {
            "label": {"en": "Style + AI", "es": "Estilo + IA", "zh": "风格 + AI", "ko": "스타일 + AI"},
            "desc": {"en": "Pick a style from your catalog — the AI blends it with your idea into a single prompt.",
                     "es": "Elige un estilo de tu catálogo: la IA lo funde con tu idea en un único prompt.",
                     "zh": "从风格库中选择一种风格——AI 会将它与你的想法融合成一条提示词。",
                     "ko": "카탈로그에서 스타일을 고르면 AI가 아이디어와 합쳐 하나의 프롬프트로 만듭니다."},
        },
    }
    return [direct, blend]


# Refine: image style reference + a described scene. ONE flow, engine picker
# — the OPENHIKER sources were three separate flow_data flows (Anima, USO,
# Z-Image), two of them the same RF Inversion + Untwisting RoPE technique on
# a different model, which read as three unrelated tools. All three graphs
# take the prompt on node 607; image/steps/seed nodes differ per engine and
# are remapped by engine_select (flow-step-workflow-params.js esApplyEngine).
# Same fluid prompt as Create's Style flow: the scene is typed once, the
# "Final prompt" below composes it live with the wording of a catalog style
# picked from the image header (the style IMAGE is what drives the look; the
# wording only reinforces it, so it's removable with the chip's ×).
_ST_REF_DESC = {
    "en": "Describe a scene and render it in the look of a reference image.",
    "es": "Describe una escena y píntala con el look de una imagen de referencia.",
    "zh": "描述一个场景，并以参考图像的风格呈现。",
    "ko": "장면을 묘사하면 참조 이미지의 룩으로 렌더링합니다.",
}
STYLE_REFERENCE_ENGINES = [
    {"id": "zimage", "label": "Z-Image Turbo", "workflow_file": "workflows/refine/refine_style_transfer_zimage.json",
     "image_node": "612", "steps_key": "31.steps", "seed_key": "167.noise_seed",
     "steps_default": 12, "steps_quick_options": [8, 12, 16]},
    {"id": "klein_9b", "label": "Flux 2 Klein 9B", "workflow_file": STYLE_REFERENCE_KLEIN_9B_WORKFLOW_REL,
     "image_node": "612", "steps_key": "31.steps", "seed_key": "167.noise_seed",
     "steps_default": 8, "steps_quick_options": [4, 8, 12]},
    {"id": "klein_4b", "label": "Flux 2 Klein 4B", "workflow_file": STYLE_REFERENCE_KLEIN_4B_WORKFLOW_REL,
     "image_node": "612", "steps_key": "31.steps", "seed_key": "167.noise_seed",
     "steps_default": 8, "steps_quick_options": [4, 8, 12]},
    {"id": "qwen_2511", "label": "Qwen Edit 2511", "workflow_file": "workflows/refine/refine_style_reference_qwen_2511.json",
     "image_node": "612", "steps_key": "31.steps", "seed_key": "167.noise_seed",
     "steps_default": 8, "steps_quick_options": [8, 12]},
    {"id": "qwen_2511_turbo", "label": "Qwen Edit 2511 Turbo",
     "workflow_file": "workflows/refine/refine_style_reference_qwen_2511_turbo.json",
     "image_node": "612", "steps_key": "31.steps", "seed_key": "167.noise_seed",
     "steps_default": 4, "steps_quick_options": [4, 6]},
    {"id": "uso", "label": "USO (Flux.1)", "workflow_file": "workflows/refine/refine_style_transfer_uso.json",
     "image_node": "612", "steps_key": "622.steps", "seed_key": "622.seed",
     "steps_default": 20, "steps_quick_options": [20, 30]},
    {"id": "anima", "label": "Anima — anime & illustration", "workflow_file": ANIMA_STYLE_WORKFLOW_REL,
     "image_node": "632", "steps_key": "31.steps", "seed_key": "167.noise_seed",
     "steps_default": 12, "steps_quick_options": [12, 35]},
]


def _style_reference_refine_flows(source: Path) -> list[dict]:
    first = STYLE_REFERENCE_ENGINES[0]
    flow = {
        "id": "refine.style_reference",
        "label": "Style Reference",
        "category": "refine",
        "group": "styling",
        "description": _ST_REF_DESC["en"],
        "card_desc": _ST_REF_DESC["en"],
        "card_tags": ["Style", "Image", "RF Inversion"],
        "card_css_modifier": "edit-fluxklein",
        "llm_required": False,
        "comfyui_required": True,
        "steps": [
            {
                "id": "params",
                "type": "workflow_params",
                "label": "Choose engine",
                "show_label": True,
                "workflow_file": first["workflow_file"],
                "image_node": first["image_node"],
                "fields": [
                    {"id": "engine", "type": "engine_select", "default": first["id"],
                     "engines": STYLE_REFERENCE_ENGINES},
                    {"id": "steps", "adv_key": first["steps_key"], "label": "Steps", "type": "number",
                     "default": first["steps_default"], "min": 1, "max": 40, "step": 1,
                     "quick_options": first["steps_quick_options"], "advanced": True},
                    {"id": "seed", "adv_key": first["seed_key"], "label": "Visual similarity", "type": "seed",
                     "seed_mode": "similarity", "advanced": True},
                ],
            },
            {"id": "image", "type": "image_picker", "label": "Style reference image", "required": True,
             "style_image_input": True},
            {"id": "idea", "type": "prompt_input", "label": "Describe the scene", "required": True, "rows": 3,
             "placeholder": "What should be painted in that style? e.g. a lighthouse on a cliff at dusk"},
            {"id": "prompt", "type": "prompt_input", "label": "Final prompt", "rows": 4,
             "style_compose_from": "idea", "style_source": "image",
             "placeholder": "Your scene, plus the wording of the style you pick — edit it if you like."},
            {
                "id": "generate",
                "type": "action",
                "label": "Generate",
                "calls": "generation.submit_refine",
                "input_map": {
                    "workflowFile": "steps.params.output.workflow_file",
                    "imageDataUrl": "steps.image.output.image_data_url",
                    "advancedValues": "steps.params.output.adv_values",
                    "promptKey": "607.text",
                    "promptValue": "steps.prompt.output.prompt_text || steps.idea.output.prompt_text",
                },
            },
            {"id": "result", "type": "result_view", "label": "Result"},
        ],
        "entry_category": "Style",
        "entry_model": "Multi",
        "_i18n_overrides": {
            "label": {"en": "Style Reference", "es": "Referencia de estilo", "zh": "风格参考", "ko": "스타일 참조"},
            "desc": _ST_REF_DESC,
        },
    }
    return [flow]


# Mix: content photo + style reference image.
STYLE_TRANSFER_MIX_SOURCES = [
    ("workflows/refine/refine_style_transfer_klein_9b.json", "Flux 2 Klein"),
    ("workflows/refine/refine_style_transfer_qwen_2511.json", "Qwen 2511"),
    ("workflows/refine/refine_klein_styler_9b.json", None),
    ("workflows/refine/refine_style_migration_klein_9b.json", None),
    ("workflows/refine/refine_style_subject_uso.json", None),
]
STYLE_TRANSFER_MIX_TEXTS = {
    "mix.style_transfer_flux_klein": {
        "label": {"en": "Style Transfer — Flux 2 Klein", "es": "Transferencia de estilo — Flux 2 Klein",
                  "zh": "风格迁移 — Flux 2 Klein", "ko": "스타일 전이 — Flux 2 Klein"},
        "desc": {"en": "Edit a photo and apply the look of a separate reference image (Klein 9B/4B).",
                 "es": "Edita una foto y aplícale el look de otra imagen de referencia (Klein 9B/4B).",
                 "zh": "编辑照片并套用另一张参考图的风格（Klein 9B/4B）。",
                 "ko": "사진을 편집하고 별도 참조 이미지의 룩을 적용합니다 (Klein 9B/4B)."},
    },
    "mix.style_transfer_qwen_2511": {
        "label": {"en": "Style Transfer — Qwen 2511", "es": "Transferencia de estilo — Qwen 2511",
                  "zh": "风格迁移 — Qwen 2511", "ko": "스타일 전이 — Qwen 2511"},
        "desc": {"en": "Edit a photo and apply the look of a separate reference image, on Qwen Image Edit 2511.",
                 "es": "Edita una foto y aplícale el look de otra imagen de referencia, con Qwen Image Edit 2511.",
                 "zh": "编辑照片并套用另一张参考图的风格，基于 Qwen Image Edit 2511。",
                 "ko": "사진을 편집하고 별도 참조 이미지의 룩을 적용합니다 — Qwen Image Edit 2511."},
    },
    "mix.klein_styler": {
        "label": {"en": "Klein Styler", "es": "Klein Styler", "zh": "Klein Styler", "ko": "Klein Styler"},
        "desc": {"en": "Combine a style reference and a subject photo on Flux 2 Klein 9B.",
                 "es": "Combina una referencia de estilo y una foto del sujeto con Flux 2 Klein 9B.",
                 "zh": "在 Flux 2 Klein 9B 上结合风格参考图与主体照片。",
                 "ko": "Flux 2 Klein 9B에서 스타일 참조와 피사체 사진을 결합합니다."},
    },
    "mix.style_migration_klein_9b": {
        "label": {"en": "Style Migration — Klein 9B", "es": "Migración de estilo — Klein 9B",
                  "zh": "风格迁移（Migration）— Klein 9B", "ko": "스타일 마이그레이션 — Klein 9B"},
        "desc": {"en": "Move the painting style of one image onto another with the Klein Migration LoRA.",
                 "es": "Lleva el estilo pictórico de una imagen a otra con la LoRA Klein Migration.",
                 "zh": "用 Klein Migration LoRA 将一张图的绘画风格迁移到另一张图。",
                 "ko": "Klein Migration LoRA로 한 이미지의 화풍을 다른 이미지로 옮깁니다."},
    },
    "mix.style_subject_uso": {
        "label": {"en": "Style + Subject — USO", "es": "Estilo + sujeto — USO",
                  "zh": "风格 + 主体 — USO", "ko": "스타일 + 피사체 — USO"},
        "desc": {"en": "Keep a subject's identity while applying a reference style, with ByteDance USO.",
                 "es": "Conserva la identidad del sujeto aplicando un estilo de referencia, con ByteDance USO.",
                 "zh": "保留主体身份的同时套用参考风格，基于字节跳动 USO。",
                 "ko": "피사체의 정체성은 유지하면서 참조 스타일을 적용합니다 — ByteDance USO."},
    },
    "mix.style_transfer_qwen2": {
        "label": {"en": "Style Transfer — Qwen 2.1", "es": "Transferencia de estilo — Qwen 2.1",
                  "zh": "风格迁移 — Qwen 2.1", "ko": "스타일 전이 — Qwen 2.1"},
        "desc": {"en": "Restyle a photo with the look of a reference image, on Qwen Image 2.1.",
                 "es": "Reestiliza una foto con el look de una imagen de referencia, con Qwen Image 2.1.",
                 "zh": "以参考图的风格重新演绎照片，基于 Qwen Image 2.1。",
                 "ko": "참조 이미지의 룩으로 사진을 재스타일링합니다 — Qwen Image 2.1."},
    },
}

# Prompt templates for the new Qwen 2.1 mix flow. <image1> = the photo to
# restyle, <image2> = the style reference (TextEncodeQwenImage21 order).
STYLE_TRANSFER_QWEN21_PRESETS = [
    {
        "label": "Full style",
        "text": "Redraw <image2> in the visual style of <image1>. Transfer its color palette, lighting mood, "
                "texture and rendering technique. Keep the composition, subjects, poses and layout of <image2> "
                "unchanged, and do not copy any objects or content from <image1>.",
    },
    {
        "label": "Colors and light only",
        "text": "Keep <image2> exactly as it is — same subjects, details and medium — and only recolor it with "
                "the color palette, contrast and lighting mood of <image1>.",
    },
    {
        "label": "Medium and texture",
        "text": "Re-render <image2> using the artistic medium and texture of <image1> — its brushwork, line "
                "quality, grain and surface. Keep the composition and subjects of <image2>; ignore the "
                "content of <image1>.",
    },
]


def _style_transfer_qwen21_mix_flow() -> dict:
    """New Mix flow: built through the same converter as the OPENHIKER mix
    flows (flow_engine._build_mix_flow_definition) so it behaves the same:
    first picker = style reference (with the Build > Styles image button),
    second = the photo to restyle."""
    from app.services.flow_engine import _build_mix_flow_definition

    meta = {
        "id": "mix.style_transfer_qwen2",
        "category": "mix",
        "label": "Style Transfer — Qwen 2.1",
        "description": "Restyle a photo (<image2>) with the look of a separate reference image (<image1>) — "
                       "Qwen Image 2.1's native multi-image editing, no LoRA or inversion needed.",
        "card_desc": STYLE_TRANSFER_MIX_TEXTS["mix.style_transfer_qwen2"]["desc"]["en"],
        "card_tags": ["Qwen", "2.1", "Style", "Mix"],
        "card_css_modifier": "edit-qwen-2511",
        "image_node": "8",
        "image_node_2": "7",
        "no_subject_input": True,
        "style_image_input": True,
        "image_label": "Style reference (image 1)",
        "image_2_label": "Image to restyle (image 2)",
        "prompt_presets": STYLE_TRANSFER_QWEN21_PRESETS,
        "params": [
            {"id": "prompt", "key": "13.prompt", "label": "Style prompt", "type": "text",
             "default": STYLE_TRANSFER_QWEN21_PRESETS[0]["text"]},
            {"id": "steps", "key": "15.steps", "label": "Steps", "type": "number", "default": 25, "min": 1,
             "max": 25, "step": 1, "quick_options": [8, 16, 25], "advanced": True},
            {"id": "seed", "key": "15.seed", "label": "Visual similarity", "type": "seed",
             "seed_mode": "similarity", "advanced": True},
        ],
    }
    flow = _build_mix_flow_definition(meta, STYLE_TRANSFER_QWEN21_WORKFLOW_REL)
    flow["entry_category"] = "Style"
    flow["entry_model"] = "Qwen Image 2.1 Edit"
    return flow


def build_mix_style_transfer(source: Path, version: str) -> Path:
    table = load_translations(source)
    for text, langs in STYLE_TRANSFER_UI_TEXTS.items():  # only fills gaps
        table.setdefault(text, {}).update({k: v for k, v in langs.items() if k not in table.get(text, {})})
    files: dict[str, object] = {}
    workflow_refs: set[str] = set()
    flows = []
    for rel, _ in STYLE_TRANSFER_MIX_SOURCES:
        flows.append(_flow_from_embedded_flow_data(source, rel, "style-transfer"))
    # mix.style_transfer_qwen2 (Qwen Image 2.1) is left out: tested by the
    # user 2026-09-23 with many combinations and the results were poor.
    # _style_transfer_qwen21_mix_flow() stays for a later retry.
    for i, flow in enumerate(flows):
        flow["group"] = "style-transfer"
        texts = STYLE_TRANSFER_MIX_TEXTS[flow["id"]]
        flow["label"] = texts["label"]["en"]
        flow["card_desc"] = texts["desc"]["en"]
        flow["description"] = texts["desc"]["en"]
        table.setdefault(texts["desc"]["en"], {}).update({k: v for k, v in texts["desc"].items() if k != "en"})
        flow = add_card_texts(flow, table)
        flow["card"]["label"] = texts["label"]
        flow["card"]["desc"] = texts["desc"]
        _upgrade_seed_fields_to_similarity(flow)
        flows[i] = flow
        files[f"flows/{flow['id'].split('.', 1)[1]}.json"] = flow
        workflow_refs |= _collect_workflow_file_refs(flow)
    for ref in sorted(workflow_refs):
        graph = _load_workflow_ref(source, ref)
        _strip_foreign_flow_data(graph)
        files[ref] = graph

    i18n, counts = flow_i18n(flows, table)
    manifest = {
        "schema_version": 1,
        "id": "nomad.mix-style-transfer",
        "version": version,
        "default_lang": "en",
        "name": {"en": "Style Transfer (Mix)", "es": "Transferencia de estilo (Mix)",
                 "zh": "风格迁移（Mix）", "ko": "스타일 전이 (Mix)"},
        "summary": {
            "en": "Image + image: restyle a photo with the look of a separate reference picture — five engines "
                  "and techniques (Qwen 2511, Flux 2 Klein RF Inversion, Klein Styler, Klein "
                  "Migration, USO Style + Subject).",
            "es": "Imagen + imagen: reestiliza una foto con el look de otra imagen de referencia — cinco motores "
                  "y técnicas (Qwen 2511, Flux 2 Klein RF Inversion, Klein Styler, Klein "
                  "Migration, USO Estilo + sujeto).",
            "zh": "图像 + 图像：以另一张参考图的风格重新演绎照片——五种引擎与技术（Qwen 2511、"
                  "Flux 2 Klein RF Inversion、Klein Styler、Klein Migration、USO 风格 + 主体）。",
            "ko": "이미지 + 이미지: 별도 참조 이미지의 룩으로 사진을 재스타일링 — 5가지 엔진과 기법 ("
                  "Qwen 2511, Flux 2 Klein RF Inversion, Klein Styler, Klein Migration, USO 스타일 + 피사체).",
        },
        "author": AUTHOR,
        "license": "proprietary",
        "group": {"id": "style-transfer", "label": {"en": "Style Transfer", "es": "Transferencia de estilo",
                                                    "zh": "风格迁移", "ko": "스타일 전이"}},
        "requires": {"engines": [{"category": "image"}]},
        "languages": ["en", *(lang for lang in LANGS if i18n[lang])],
        "contributes": {
            "flows": [f"flows/{flow['id'].split('.', 1)[1]}.json" for flow in flows],
            "workflows": sorted(workflow_refs),
        },
    }
    print(f"  mix-style-transfer texts: {counts['total']} · " + " ".join(f"{lang} {counts[lang]}" for lang in LANGS))
    return write_zip("nomad.mix-style-transfer", {"manifest.json": manifest, **files, "LICENSE": LICENSE_TEXT,
                                                    **{f"i18n/{lang}.json": i18n[lang] for lang in LANGS if i18n[lang]}},
                      dest=DIST_OPTIONAL)


# UI strings of the style flows that OPENHIKER's translation table doesn't
# carry yet (merged into it before flow_i18n) — keeps every step label in
# EN/ES/ZH/KO.
STYLE_TRANSFER_UI_TEXTS = {
    "Style reference image": {"es": "Imagen de referencia de estilo", "zh": "风格参考图", "ko": "스타일 참조 이미지"},
    "Image to edit": {"es": "Imagen a editar", "zh": "要编辑的图像", "ko": "편집할 이미지"},
    "Image to restyle": {"es": "Imagen a reestilizar", "zh": "要重新风格化的图像", "ko": "재스타일링할 이미지"},
    "Image to restyle (image 2)": {"es": "Imagen a reestilizar (imagen 2)", "zh": "要重新风格化的图像（图 2）",
                                   "ko": "재스타일링할 이미지 (이미지 2)"},
    "Style prompt": {"es": "Prompt de estilo", "zh": "风格提示词", "ko": "스타일 프롬프트"},
    "Edit prompt": {"es": "Prompt de edición", "zh": "编辑提示词", "ko": "편집 프롬프트"},
    "Target prompt": {"es": "Prompt de la escena", "zh": "目标场景提示词", "ko": "대상 장면 프롬프트"},
    "Migration prompt": {"es": "Prompt de migración", "zh": "迁移提示词", "ko": "마이그레이션 프롬프트"},
    "Prompt": {"es": "Prompt", "zh": "提示词", "ko": "프롬프트"},
    "Style": {"es": "Estilo", "zh": "风格", "ko": "스타일"},
    "Source image": {"es": "Imagen de origen", "zh": "源图像", "ko": "원본 이미지"},
    "Style reference (image 1)": {"es": "Referencia de estilo (imagen 1)", "zh": "风格参考（图 1）", "ko": "스타일 참조 (이미지 1)"},
    "Subject to edit (image 2)": {"es": "Sujeto a editar (imagen 2)", "zh": "要编辑的主体（图 2）", "ko": "편집할 피사체 (이미지 2)"},
    "Style reference image (image 2)": {"es": "Imagen de referencia de estilo (imagen 2)", "zh": "风格参考图（图 2）", "ko": "스타일 참조 이미지 (이미지 2)"},
    "Image to edit (image 1)": {"es": "Imagen a editar (imagen 1)", "zh": "要编辑的图像（图 1）", "ko": "편집할 이미지 (이미지 1)"},
    "Subject / content reference": {"es": "Referencia de sujeto / contenido", "zh": "主体 / 内容参考", "ko": "피사체 / 콘텐츠 참조"},
    "Choose engine": {"es": "Elige el motor", "zh": "选择引擎", "ko": "엔진 선택"},
    "Parameters": {"es": "Parámetros", "zh": "参数", "ko": "매개변수"},
    "Steps": {"es": "Pasos", "zh": "步数", "ko": "스텝"},
    "Seed": {"es": "Semilla", "zh": "种子", "ko": "시드"},
    "Visual similarity": {"es": "Similitud visual", "zh": "视觉相似度", "ko": "시각적 유사도"},
    "LoRA strength": {"es": "Fuerza de la LoRA", "zh": "LoRA 强度", "ko": "LoRA 강도"},
    "Turbo LoRA": {"es": "LoRA Turbo", "zh": "Turbo LoRA", "ko": "터보 LoRA"},
    "Generate": {"es": "Generar", "zh": "生成", "ko": "생성"},
    "Refine": {"es": "Refinar", "zh": "精修", "ko": "리파인"},
    "Result": {"es": "Resultado", "zh": "结果", "ko": "결과"},
    "Full style": {"es": "Estilo completo", "zh": "完整风格", "ko": "전체 스타일"},
    "Your idea": {"es": "Tu idea", "zh": "你的想法", "ko": "아이디어"},
    "Describe the scene": {"es": "Describe la escena", "zh": "描述场景", "ko": "장면 설명"},
    "What should be painted in that style? e.g. a lighthouse on a cliff at dusk": {
        "es": "¿Qué quieres pintar con ese estilo? p. ej. un faro en un acantilado al atardecer",
        "zh": "想用这种风格画什么？例如：黄昏时悬崖上的灯塔",
        "ko": "그 스타일로 무엇을 그릴까요? 예: 해질녘 절벽 위의 등대",
    },
    "Your scene, plus the wording of the style you pick — edit it if you like.": {
        "es": "Tu escena más el texto del estilo que elijas; puedes editarlo.",
        "zh": "你的场景加上所选风格的描述——可以自行编辑。",
        "ko": "장면에 고른 스타일의 문구가 더해집니다. 원하면 수정하세요.",
    },
    "Final prompt": {"es": "Prompt final", "zh": "最终提示词", "ko": "최종 프롬프트"},
    "Blend with AI": {"es": "Fusionar con IA", "zh": "用 AI 融合", "ko": "AI로 합치기"},
    "Generate Image": {"es": "Generar imagen", "zh": "生成图像", "ko": "이미지 생성"},
    "You can edit this later": {"es": "Puedes editarlo después", "zh": "之后可以编辑", "ko": "나중에 수정할 수 있습니다"},
    "Describe what you want, then pick a style with the palette button.": {
        "es": "Describe lo que quieres y elige un estilo con el botón de la paleta.",
        "zh": "描述你想要的内容，然后用调色板按钮选择一种风格。",
        "ko": "원하는 것을 적은 뒤 팔레트 버튼으로 스타일을 고르세요.",
    },
    "Your idea wrapped in the style's wording — edit it if you like.": {
        "es": "Tu idea envuelta con el texto del estilo; puedes editarla.",
        "zh": "用风格描述包裹后的想法——可以自行编辑。",
        "ko": "스타일 문구로 감싼 아이디어입니다. 원하면 수정하세요.",
    },
    "A rough idea is enough — the AI will blend it with the style…": {
        "es": "Basta con una idea aproximada: la IA la fundirá con el estilo…",
        "zh": "粗略的想法就够了——AI 会把它与风格融合…",
        "ko": "대략적인 아이디어면 충분합니다. AI가 스타일과 합쳐 줍니다…",
    },
    "Pick a style from your catalog, or describe one…": {
        "es": "Elige un estilo de tu catálogo o describe uno…",
        "zh": "从风格库中选择一种风格，或自己描述…",
        "ko": "카탈로그에서 스타일을 고르거나 직접 설명하세요…",
    },
    "Write your idea and wrap it in one of your saved Styles, then generate.": {
        "es": "Escribe tu idea, envuélvela en uno de tus Estilos guardados y genera.",
        "zh": "写下你的想法，用你保存的风格包裹它，然后生成。",
        "ko": "아이디어를 적고 저장된 스타일로 감싼 뒤 생성합니다.",
    },
    "The local AI blends your idea with one of your saved Styles into a single, well-written prompt.": {
        "es": "La IA local funde tu idea con uno de tus Estilos guardados en un único prompt bien escrito.",
        "zh": "本地 AI 将你的想法与你保存的风格融合成一条精心撰写的提示词。",
        "ko": "로컬 AI가 아이디어와 저장된 스타일을 하나의 잘 다듬어진 프롬프트로 합칩니다.",
    },
    "CFG": {"es": "CFG", "zh": "CFG", "ko": "CFG"},
    "Flux guidance": {"es": "Guía de Flux", "zh": "Flux 引导强度", "ko": "Flux 가이던스"},
    "Prompt preview": {"es": "Vista previa del prompt", "zh": "提示词预览", "ko": "프롬프트 미리보기"},
    _ST_TEXT_DESC["en"]: {k: v for k, v in _ST_TEXT_DESC.items() if k != "en"},
    _ST_REF_DESC["en"]: {k: v for k, v in _ST_REF_DESC.items() if k != "en"},
    "Apply a curated visual style to your image using Flux 2 Klein 9B. 70+ styles in 10 groups.": {
        "es": "Aplica a tu imagen un estilo visual curado con Flux 2 Klein 9B. Más de 70 estilos en 10 grupos.",
        "zh": "使用 Flux 2 Klein 9B 为图像套用精选视觉风格。10 组共 70 多种风格。",
        "ko": "Flux 2 Klein 9B로 이미지에 엄선된 비주얼 스타일을 적용합니다. 10개 그룹, 70개 이상의 스타일.",
    },
    "Apply a curated pixel-art visual style to your image using Qwen Image 2.1. 70+ styles in 10 groups.": {
        "es": "Aplica a tu imagen un estilo de pixel art curado con Qwen Image 2.1. Más de 70 estilos en 10 grupos.",
        "zh": "使用 Qwen Image 2.1 为图像套用精选像素艺术风格。10 组共 70 多种风格。",
        "ko": "Qwen Image 2.1로 이미지에 엄선된 픽셀 아트 스타일을 적용합니다. 10개 그룹, 70개 이상의 스타일.",
    },
    "Colors and light only": {"es": "Solo colores y luz", "zh": "仅颜色与光线", "ko": "색과 빛만"},
    "Medium and texture": {"es": "Técnica y textura", "zh": "媒介与质感", "ko": "매체와 질감"},
    STYLE_TRANSFER_KEEP_LAYOUT: {
        "es": "Reestiliza esta imagen manteniendo exactamente su composición, sujetos, poses y distribución",
        "zh": "重新风格化这张图像，完全保留其构图、主体、姿势和布局",
        "ko": "이 이미지의 구도, 피사체, 포즈, 레이아웃은 그대로 유지하면서 재스타일링",
    },
    "Choose a style — it wraps this instruction with the style's wording.": {
        "es": "Elige un estilo: envolverá esta instrucción con el texto del estilo.",
        "zh": "选择一种风格——它会用该风格的描述包裹这条指令。",
        "ko": "스타일을 고르면 이 지시문을 스타일 문구로 감쌉니다.",
    },
}


def build_styling(source: Path, version: str) -> Path:
    addon_files, addon_contributes, addon_i18n = _pixel_matcher_addon_contribution()
    return build_refine_static_group(
        source, version, "nomad.refine-styling", "styling",
        name={"en": "Styling", "es": "Estilizado", "zh": "风格化", "ko": "스타일링"},
        summary={
            "en": "Everything style — in Create, write an idea and wrap it in one of your saved Styles (directly or blended by the AI); in Refine, restyle the whole image with one of your saved Styles as text (Klein 9B/4B, Qwen 2.1), "
                  "with a reference image as the style (Anima, USO, Z-Image), with one of 70+ curated pixel-art "
                  "presets (Klein 9B, Qwen Image 2.1), or convert to pixel art locally (no AI) with Pixel Matcher.",
            "es": "Todo lo de estilo — en Create, escribe una idea y envuélvela en uno de tus Estilos guardados (directo o fundido por la IA); en Refine, reestiliza toda la imagen con uno de tus Estilos guardados como texto (Klein 9B/4B, Qwen 2.1), "
                  "con una imagen de referencia como estilo (Anima, USO, Z-Image), con uno de más de 70 presets "
                  "curados de pixel art (Klein 9B, Qwen Image 2.1), o conviértela a pixel art localmente (sin IA) "
                  "con Pixel Matcher.",
            "zh": "风格相关的一切——在 Create 中写下想法并用已保存的风格包裹（直接或由 AI 融合）；在 Refine 中重新设计整张图像的风格——以已保存的风格作为文本（Klein 9B/4B、Qwen 2.1），以参考图作为风格"
                  "（Anima、USO、Z-Image），套用 70 多种精选像素艺术预设之一（Klein 9B、Qwen Image 2.1），"
                  "或用 Pixel Matcher 在本地（无 AI）转换为像素艺术。",
            "ko": "스타일의 모든 것 — Create에서는 아이디어를 저장된 스타일로 감싸고(직접 또는 AI로 융합), Refine에서는 이미지 전체를 재스타일링 — 저장된 스타일을 텍스트로(Klein 9B/4B, Qwen 2.1), 참조 이미지를 스타일로"
                  "(Anima, USO, Z-Image), 70개 이상의 엄선된 픽셀 아트 프리셋으로(Klein 9B, Qwen Image 2.1) 적용하거나, "
                  "Pixel Matcher로 로컬(AI 없이)에서 픽셀 아트로 변환합니다.",
        },
        flow_ids=STYLING_FLOWS,
        group_overrides=STYLING_GROUP_OVERRIDES,
        hand_authored=[*_create_style_flows(), *_style_transfer_text_flows(), *_style_reference_refine_flows(source),
                       _pixel_art_qwen2_flow(source)],
        extra_files=addon_files,
        extra_contributes=addon_contributes,
        extra_texts=STYLE_TRANSFER_UI_TEXTS,
        extra_i18n=addon_i18n,
    )


# Presets — 44 one-click photo color-grading looks (Photo Packs gallery,
# /nomad-studio/refine/presets/photo_pack — ns_refine_presets.html), split
# into 3 packages per the plan worked out with the user (2026-08-30
# marketing-site session, recovered from transcript 2026-09-21): 2 kept
# free/standalone, the other 42 split 21/21 into two paid packs by mood
# (light/airy vs. dark/analog). Every preset shares the same Qwen 2.1 Edit
# engine (workflow_file already migrated, see QWEN_2511_EDIT_WORKFLOW_REL)
# — no per-preset engine work needed, only packaging.
PRESETS_CORE_FLOWS = ["refine.presets_riviera", "refine.presets_spectra"]
PRESETS_OPEN_AIR_FLOWS = [
    "refine.presets_amour", "refine.presets_blush", "refine.presets_breeze", "refine.presets_clarity",
    "refine.presets_ether", "refine.presets_evermore", "refine.presets_fetch", "refine.presets_gusto",
    "refine.presets_halo", "refine.presets_icon", "refine.presets_linen", "refine.presets_lumen",
    "refine.presets_minim", "refine.presets_mirage", "refine.presets_muse", "refine.presets_prism",
    "refine.presets_pure", "refine.presets_reverie", "refine.presets_staple", "refine.presets_urbana",
    "refine.presets_wander",
]
PRESETS_FILM_SHADOW_FLOWS = [
    "refine.presets_azure", "refine.presets_afterglow", "refine.presets_aurea", "refine.presets_celluloid",
    "refine.presets_companion", "refine.presets_dusk", "refine.presets_ember", "refine.presets_fade",
    "refine.presets_fjord", "refine.presets_frame", "refine.presets_hearth", "refine.presets_marais",
    "refine.presets_mode", "refine.presets_nocturne", "refine.presets_onyx", "refine.presets_pristine",
    "refine.presets_reel", "refine.presets_relic", "refine.presets_rogue", "refine.presets_sand",
    "refine.presets_terra",
]


def _preset_cover_files(source: Path, flow_ids: list[str]) -> dict[str, bytes]:
    """Each preset's own preset_meta.cover_image (e.g.
    "images/presets/afterglow/cover.webp") ships inside the package zip at
    that SAME relative path, so packages_routes.py's serve_package_file
    (/packages/<pkg>/<path>) can find it — the Photo Packs gallery can't
    reach it via url_for('static', …), it's never copied into app/static/."""
    files: dict[str, bytes] = {}
    for flow_id in flow_ids:
        flow = flow_from_source(source, flow_id)
        cover_rel = (flow.get("preset_meta") or {}).get("cover_image")
        if not cover_rel:
            continue
        files[cover_rel] = (source / "app" / "static" / cover_rel).read_bytes()
    return files


def build_presets_core(source: Path, version: str) -> Path:
    return build_refine_static_group(
        source, version, "nomad.refine-presets-core", "presets",
        name={"en": "Photo Looks Starter", "es": "Photo Looks Starter", "zh": "照片风格入门", "ko": "포토 룩 스타터"},
        summary={
            "en": "Two signature one-click photo looks — Riviera and Spectra — included free.",
            "es": "Dos looks de foto de un clic — Riviera y Spectra — incluidos gratis.",
            "zh": "两款标志性一键照片效果——Riviera 和 Spectra——免费附带。",
            "ko": "시그니처 원클릭 포토 룩 2종 — Riviera, Spectra — 무료 포함.",
        },
        flow_ids=PRESETS_CORE_FLOWS,
        extra_files=_preset_cover_files(source, PRESETS_CORE_FLOWS),
        cover_image=PACK_COVERS / "nomad.refine-presets-core.webp",
    )


def build_presets_open_air(source: Path, version: str) -> Path:
    return build_refine_static_group(
        source, version, "nomad.refine-presets-open-air", "presets",
        name={"en": "Open Air", "es": "Open Air", "zh": "Open Air", "ko": "Open Air"},
        summary={
            "en": "21 luminous, clean photo looks for lifestyle, food, interiors and social — Breeze, Clarity, Ether, Halo, Lumen, Muse, Prism and more.",
            "es": "21 looks de foto luminosos y limpios para lifestyle, comida, interiores y redes — Breeze, Clarity, Ether, Halo, Lumen, Muse, Prism y más.",
            "zh": "21 种明亮清新的照片效果，适合生活方式、美食、室内和社交场景——Breeze、Clarity、Ether、Halo、Lumen、Muse、Prism 等。",
            "ko": "라이프스타일, 음식, 인테리어, 소셜 미디어를 위한 밝고 깨끗한 포토 룩 21종 — Breeze, Clarity, Ether, Halo, Lumen, Muse, Prism 등.",
        },
        flow_ids=PRESETS_OPEN_AIR_FLOWS,
        extra_files=_preset_cover_files(source, PRESETS_OPEN_AIR_FLOWS),
        cover_image=PACK_COVERS / "nomad.refine-presets-open-air.webp",
    )


def build_presets_film_shadow(source: Path, version: str) -> Path:
    return build_refine_static_group(
        source, version, "nomad.refine-presets-film-shadow", "presets",
        name={"en": "Film & Shadow", "es": "Film & Shadow", "zh": "Film & Shadow", "ko": "Film & Shadow"},
        summary={
            "en": "21 dark, analog-leaning photo looks for portrait, night and film emulation — Celluloid, Ember, Nocturne, Onyx, Rogue, Fjord and more.",
            "es": "21 looks de foto oscuros y de aire analógico para retrato, noche y emulación de película — Celluloid, Ember, Nocturne, Onyx, Rogue, Fjord y más.",
            "zh": "21 种深色、模拟胶片风格的照片效果，适合人像、夜景和胶片模拟——Celluloid、Ember、Nocturne、Onyx、Rogue、Fjord 等。",
            "ko": "인물, 야경, 필름 에뮬레이션을 위한 어둡고 아날로그 감성의 포토 룩 21종 — Celluloid, Ember, Nocturne, Onyx, Rogue, Fjord 등.",
        },
        flow_ids=PRESETS_FILM_SHADOW_FLOWS,
        extra_files=_preset_cover_files(source, PRESETS_FILM_SHADOW_FLOWS),
        cover_image=PACK_COVERS / "nomad.refine-presets-film-shadow.webp",
    )


# Smart Selection (text-prompted SAM3 cutout) and Smart Object Removal
# (SAM3 selection + Qwen-painted fill) are both foreground-extraction tools
# at heart — grouped with the new hand-authored Extract (Qwen 2.1) flow.
EXTRACT_SOURCE_FLOWS = ["refine.smart_selection", "refine.smart_selection_fill"]
EXTRACT_GROUP_OVERRIDES = {fid: "extract" for fid in EXTRACT_SOURCE_FLOWS}

# Smart Object Removal never removed anything (NOMADSTUDIO_TUTORIALS
# IMPROVEMENTS.md note 10): the source graph burns the SAM3 mask into the
# photo as white pixels and asks Qwen Edit 2511 — through a White-to-Scene
# LoRA trained for 2509 and the Qwen *Image* Lightning LoRA — to "fill the
# white area". Measured 2026-10-02 on the tutorial garden: two teddy bears
# where the chairs were (2509 + its own LoRAs: two white dogs). What works:
# Qwen Edit 2511 + its own Lightning gets the ORIGINAL photo and "Remove
# <object>. <fill>", the SAM3 mask goes in as a latent noise mask, and the
# result is pasted back only inside the mask, so the rest stays untouched.
SMART_FILL_OBJECT_NODE = "240"
SMART_FILL_TEXT_NODE = "241"
SMART_FILL_DEFAULT = ("Fill that area with what was behind it, matching the same lighting, perspective and style "
                      "as the rest of the photo.")
SMART_FILL_DESCRIPTION = ("Describe an object in plain text, SAM3 finds it, and Qwen Image Edit 2511 repaints only "
                          "that area with what was behind it — a one-step magic eraser.")


def _fix_smart_fill_workflow(graph: dict) -> None:
    graph["4"]["inputs"]["lora_name"] = "qwen_2511\\Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"
    graph["4"]["inputs"]["model"] = ["6", 0]
    for node in ("5", "106", "144", "150", "151"):  # White-to-Scene LoRA + the white composite
        graph.pop(node, None)
    graph["22"]["inputs"]["image"] = ["79", 0]
    graph[SMART_FILL_OBJECT_NODE] = {"class_type": "PrimitiveString", "inputs": {"value": ""},
                                     "_meta": {"title": "Object to remove"}}
    graph[SMART_FILL_TEXT_NODE] = {"class_type": "PrimitiveStringMultiline", "inputs": {"value": SMART_FILL_DEFAULT},
                                   "_meta": {"title": "How to fill it in"}}
    graph["99:78"]["inputs"]["text"] = [SMART_FILL_OBJECT_NODE, 0]
    graph["242"] = {"class_type": "StringConcatenate",
                    "inputs": {"string_a": "Remove ", "string_b": [SMART_FILL_OBJECT_NODE, 0], "delimiter": ""}}
    graph["243"] = {"class_type": "StringConcatenate",
                    "inputs": {"string_a": ["242", 0], "string_b": [SMART_FILL_TEXT_NODE, 0], "delimiter": ". "}}
    graph["13"]["inputs"]["prompt"] = ["243", 0]
    # the feathered SAM3 mask at the edit resolution
    graph["244"] = {"class_type": "MaskToImage", "inputs": {"mask": ["115", 0]}}
    graph["245"] = {"class_type": "FluxKontextImageScale", "inputs": {"image": ["244", 0]}}
    graph["246"] = {"class_type": "ImageToMask", "inputs": {"image": ["245", 0], "channel": "red"}}
    graph["247"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["22", 0], "vae": ["2", 0]}}
    graph["248"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["247", 0], "mask": ["246", 0]}}
    graph["15"]["inputs"]["latent_image"] = ["248", 0]
    graph.pop("11", None)
    graph.pop("20", None)
    graph["249"] = {"class_type": "ImageCompositeMasked",
                    "inputs": {"destination": ["22", 0], "source": ["17", 0], "x": 0, "y": 0,
                               "resize_source": True, "mask": ["246", 0]}}
    graph["9"]["inputs"]["images"] = ["249", 0]


def _fix_smart_fill_flow(flow: dict) -> None:
    flow["description"] = SMART_FILL_DESCRIPTION
    for step in flow["steps"]:
        for field in step.get("fields", []):
            if field["id"] == "object_prompt":
                field["adv_key"] = f"{SMART_FILL_OBJECT_NODE}.value"
            elif field["id"] == "fill_prompt":
                field["adv_key"] = f"{SMART_FILL_TEXT_NODE}.value"
                field["default"] = SMART_FILL_DEFAULT


# Chroma Key (contributes.addon, same PACKAGE_FORMAT.md §9 minimal slice as
# Pixel Matcher — see _pixel_matcher_addon_contribution): local, no-AI
# chrominance-space background removal, the natural companion to Extract's
# AI cutout flows for flat/studio backgrounds. Its source lives in THIS repo,
# tools/packages/addons/chroma_key/ (moved out of --source 2026-10-03 to fix
# the key eating neutral pixels; the old chroma_key_source*.py drafts stayed
# behind). Bundled straight into Extract's zip under addon/,
# flow.json's group overridden to "extract" (source says "core"). Installing
# this package extracts addon/ to data/packages/<pkg>/addon/;
# app/services/addon_loader.py picks it up from there on the NEXT app start
# (no hot-load, same restart Pixel Matcher already needed).
CHROMA_KEY_ADDON_DIR = Path(__file__).with_name("addons") / "chroma_key"


def _chroma_key_addon_contribution() -> tuple[dict[str, str], dict]:
    addon_dir = CHROMA_KEY_ADDON_DIR
    files = {
        f"addon/{name}": (addon_dir / name).read_text(encoding="utf-8")
        for name in ("__init__.py", "routes.py", "service.py")
    }
    flow = json.loads((addon_dir / "flow.json").read_text(encoding="utf-8"))
    flow["group"] = "extract"
    files["addon/flow.json"] = json.dumps(flow, indent=2, ensure_ascii=False)
    return files, {"addon": {"entry": "addon/__init__.py"}}


def build_extract_pack(source: Path, version: str) -> Path:
    table = load_translations(source)
    files: dict[str, object] = {}
    flows: list[dict] = []
    workflow_refs: set[str] = set()

    addon_files, addon_contributes = _chroma_key_addon_contribution()
    files.update(addon_files)

    for flow_id in EXTRACT_SOURCE_FLOWS:
        raw = flow_from_source(source, flow_id)
        if flow_id == "refine.smart_selection_fill":
            _fix_smart_fill_flow(raw)
        flow = add_card_texts(raw, table)
        flow["group"] = "extract"
        _upgrade_seed_fields_to_similarity(flow)
        flows.append(flow)
        files[f"flows/{flow_id.split('.', 1)[1]}.json"] = flow
        workflow_refs |= _collect_workflow_file_refs(flow)

    hand_authored = [
        (_extract_qwen2_flow(), {
            "en": "Extract (Qwen 2.1)", "es": "Extraer (Qwen 2.1)", "zh": "提取 (Qwen 2.1)", "ko": "추출 (Qwen 2.1)",
        }, {
            "en": "Clean transparent-background cutouts — subject, product or character — with Qwen Image 2.1.",
            "es": "Recortes limpios con fondo transparente — sujeto, producto o personaje — con Qwen Image 2.1.",
            "zh": "干净的透明背景抠图——主体、产品或角色——由 Qwen Image 2.1 驱动。",
            "ko": "깔끔한 투명 배경 컷아웃 — 피사체, 제품 또는 캐릭터 — Qwen Image 2.1로 제작.",
        }),
        (_edit_rgba_qwen2_flow(), {
            "en": "Edit RGBA Asset", "es": "Editar asset RGBA", "zh": "编辑 RGBA 素材", "ko": "RGBA 에셋 편집",
        }, {
            "en": "Modify a transparent cutout — color, material or detail — while keeping its alpha intact.",
            "es": "Modifica un recorte transparente — color, material o detalle — sin tocar su alfa.",
            "zh": "修改透明抠图——颜色、材质或细节——同时保持其 alpha 通道完整。",
            "ko": "투명 컷아웃을 수정 — 색상, 재질 또는 디테일 — 하면서 알파 채널은 그대로 유지합니다.",
        }),
    ]
    for raw_flow, label_i18n, desc_i18n in hand_authored:
        flow = add_card_texts(raw_flow, table)
        flow["card"]["label"] = label_i18n
        flow["card"]["desc"] = desc_i18n
        _upgrade_seed_fields_to_similarity(flow)
        flows.append(flow)
        files[f"flows/{flow['id'].split('.', 1)[1]}.json"] = flow
        workflow_refs |= _collect_workflow_file_refs(flow)

    for ref in sorted(workflow_refs):
        graph = _load_workflow_ref(source, ref)
        _strip_foreign_flow_data(graph)
        if ref.endswith("refine_smart_selection_fill.json"):
            _fix_smart_fill_workflow(graph)
        files[ref] = graph

    # The addon's flow is served from this package too (flow_engine translates
    # it from this i18n/), so its texts are translated with the rest.
    i18n, counts = flow_i18n(flows + [json.loads(addon_files["addon/flow.json"])], table)
    manifest = {
        "schema_version": 1,
        "id": "nomad.refine-extract",
        "version": version,
        "default_lang": "en",
        "name": {"en": "Extract", "es": "Extraer", "zh": "提取", "ko": "추출"},
        "summary": {
            "en": "Pull a subject, product, character or object out of a photo as a clean transparent cutout — SAM3 text-prompted selection, Qwen Image 2.1's native RGBA extraction, or local no-AI Chroma Key for flat/studio backgrounds — then edit that RGBA asset without losing its alpha.",
            "es": "Saca un sujeto, producto, personaje u objeto de una foto como recorte transparente limpio — selección por texto con SAM3, extracción nativa RGBA de Qwen Image 2.1, o Chroma Key local sin IA para fondos planos de estudio — y edita ese asset RGBA sin perder su alfa.",
            "zh": "从照片中提取主体、产品、角色或物体，生成干净的透明抠图——SAM3 文本提示选择、Qwen Image 2.1 原生 RGBA 提取，或用于纯色/影棚背景的本地无 AI Chroma Key——然后在不丢失 alpha 的情况下编辑该 RGBA 素材。",
            "ko": "사진에서 피사체, 제품, 캐릭터, 객체를 깔끔한 투명 컷아웃으로 추출 — SAM3 텍스트 기반 선택, Qwen Image 2.1의 네이티브 RGBA 추출, 또는 단색/스튜디오 배경을 위한 로컬 무AI Chroma Key — 한 뒤 알파를 유지한 채 해당 RGBA 에셋을 편집합니다.",
        },
        "author": AUTHOR,
        "license": "proprietary",
        "group": {"id": "extract", "label": {"en": "Extract"}},
        "requires": {"engines": [{"category": "image"}]},
        "languages": ["en", *(lang for lang in LANGS if i18n[lang])],
        "contributes": {
            "flows": [f"flows/{f['id'].split('.', 1)[1]}.json" for f in flows],
            "workflows": sorted(workflow_refs),
            **addon_contributes,
        },
    }
    print(f"  extract-pack texts: {counts['total']} · " + " ".join(f"{lang} {counts[lang]}" for lang in LANGS))
    return write_zip("nomad.refine-extract", {"manifest.json": manifest, **files, "LICENSE": LICENSE_TEXT,
                                               **{f"i18n/{lang}.json": i18n[lang] for lang in LANGS if i18n[lang]}},
                      dest=DIST_OPTIONAL)


def build_refine_pilot(source: Path, version: str) -> Path:
    table = load_translations(source)
    files: dict[str, object] = {}
    flows = []
    workflow_refs: set[str] = set()

    final_flow_ids: list[str] = []
    for flow_id in REFINE_PILOT_STATIC_FLOWS:
        flow = add_card_texts(flow_from_source(source, flow_id), table)
        if flow_id in REFINE_PILOT_LABEL_OVERRIDES:
            names = REFINE_PILOT_LABEL_OVERRIDES[flow_id]
            flow["label"] = names["en"]
            flow["card"]["label"] = names
        if flow_id in REFINE_PILOT_DESC_OVERRIDES:
            desc_override = REFINE_PILOT_DESC_OVERRIDES[flow_id]
            flow["description"] = desc_override["description"]
            flow["card_desc"] = desc_override["desc"]["en"]
            flow["card_tags"] = desc_override["card_tags"]
            flow["card"]["tags"] = desc_override["card_tags"]
            flow["card"]["desc"] = desc_override["desc"]
        if flow_id in REFINE_PILOT_GROUP_OVERRIDES:
            flow["group"] = REFINE_PILOT_GROUP_OVERRIDES[flow_id]
        if flow_id in REFINE_PILOT_STEPS_FIELD_OVERRIDES:
            _override_flow_field(flow, "steps", REFINE_PILOT_STEPS_FIELD_OVERRIDES[flow_id])
        for option_id, opt_overrides in QWEN_ENGINE_SELECT_OVERRIDES.items():
            _update_engine_select_option(flow, option_id, opt_overrides)
        _upgrade_seed_fields_to_similarity(flow)
        final_id = REFINE_PILOT_ID_OVERRIDES.get(flow_id, flow_id)
        flow["id"] = final_id
        final_flow_ids.append(final_id)
        flows.append(flow)
        files[f"flows/{final_id.split('.', 1)[1]}.json"] = flow
        workflow_refs |= _collect_workflow_file_refs(flow)

    for ref in sorted(workflow_refs):
        graph = _load_workflow_ref(source, ref)
        _strip_foreign_flow_data(graph)
        files[ref] = graph

    workflow_only_rels = []
    for rel_from_source in REFINE_PILOT_WORKFLOW_ONLY_FILES:
        src_path = source / rel_from_source
        if not src_path.is_file():
            raise SystemExit(f"flow_data workflow not found: {src_path}")
        pkg_rel = f"workflows/{src_path.name}"
        graph = json.loads(src_path.read_text(encoding="utf-8"))
        _rename_embedded_flow_data(graph, REFINE_PILOT_ID_OVERRIDES, REFINE_PILOT_FLOW_DATA_LABEL_OVERRIDES)
        files[pkg_rel] = graph
        workflow_only_rels.append(pkg_rel)

    # The flow_data-only flows are installed as flows too (their "params"
    # become a workflow_params step), so their texts get translated like the
    # authored ones — the label as well, since they have no card to carry it.
    from app.services.flow_engine import _extract_flow_data_node
    embedded = []
    for rel in workflow_only_rels:
        meta = _extract_flow_data_node(files[rel])
        if meta:
            embedded.append({"id": meta["id"], "label": meta.get("label"), "description": meta.get("description"),
                             "steps": [{"id": "params", "fields": meta.get("params") or []}]})
    i18n, counts = flow_i18n(flows + embedded, table)
    for flow in embedded:
        for lang in LANGS:
            translated = (table.get(flow["label"]) or {}).get(lang)
            if translated:
                i18n[lang].setdefault(flow["id"], {})["label"] = translated
    manifest = {
        "schema_version": 1,
        "id": "nomad.core-refine",
        "version": REFINE_PILOT_VERSION,
        "default_lang": "en",
        "name": {"en": "Core Refine (Edit/Outpaint/Upscale)", "es": "Refine Núcleo (Edit/Outpaint/Upscale)",
                  "zh": "Refine 核心（Edit/Outpaint/Upscale）", "ko": "Refine 코어 (Edit/Outpaint/Upscale)"},
        "summary": {
            "en": "Core Refine tools: prompt-driven edit engines, outpaint, and model/AI upscalers.",
            "es": "Herramientas núcleo de Refine: motores de edición por prompt, outpaint y upscalers.",
            "zh": "Refine 核心工具：提示词驱动的编辑引擎、外扩绘制与放大器。",
            "ko": "Refine 핵심 도구: 프롬프트 기반 편집 엔진, 아웃페인트, 업스케일러.",
        },
        "author": AUTHOR,
        "license": "proprietary",
        "requires": {"engines": [{"category": "image"}]},
        "languages": ["en", *(lang for lang in LANGS if i18n[lang])],
        "contributes": {
            "flows": [f"flows/{fid.split('.', 1)[1]}.json" for fid in final_flow_ids],
            "workflows": [ref for ref in sorted(workflow_refs)] + workflow_only_rels,
        },
    }
    print(f"  core-refine texts: {counts['total']} · " + " ".join(f"{lang} {counts[lang]}" for lang in LANGS))
    return write_zip("nomad.core-refine", {"manifest.json": manifest, **files, "LICENSE": LICENSE_TEXT,
                                             **{f"i18n/{lang}.json": i18n[lang] for lang in LANGS if i18n[lang]}},
                      dest=DIST_OPTIONAL)


STYLE_IMAGE_EXTS = (".webp", ".png", ".jpg", ".jpeg")


def _collect_style_images(images_dir: Path | None) -> dict[str, dict[str, Path]]:
    """{style key: {engine id: file}} from the folder Build > Styles copies
    generated previews into ("Also save to output subfolder"):
    <images_dir>/<engine id>/<style key>.<ext> — or the app data folder.
    Style keys are unique across every pack, so one folder feeds them all."""
    found: dict[str, dict[str, Path]] = {}
    if not images_dir:
        return found
    if not images_dir.is_dir():
        raise SystemExit(f"--style-images: not a folder: {images_dir}")
    # The app's own data folder (has styles.json): take the images the user
    # generated for each pack style straight from Build's store
    # (<data>/images/styles/<model_images[..].image_filename>), matched by
    # package_key — works whether or not an output subfolder was set.
    if (images_dir / "styles.json").is_file():
        store = images_dir / "images" / "styles"
        for style in json.loads((images_dir / "styles.json").read_text(encoding="utf-8")):
            key = style.get("package_key") if isinstance(style, dict) else None
            if not key:
                continue
            for model_id, img in (style.get("model_images") or {}).items():
                if not isinstance(img, dict) or img.get("package"):
                    continue
                f = store / str(img.get("image_filename") or "")
                if img.get("image_filename") and f.is_file() and f.suffix.lower() in STYLE_IMAGE_EXTS:
                    found.setdefault(key, {})[model_id] = f
        return found
    for model_dir in sorted(p for p in images_dir.iterdir() if p.is_dir()):
        for f in sorted(model_dir.iterdir()):
            if f.suffix.lower() in STYLE_IMAGE_EXTS:
                found.setdefault(f.stem, {})[model_dir.name] = f
    return found


def build_style_packs(version: str, images_dir: Path | None = None) -> list[Path]:
    """Style packs (contributes.styles, PACKAGE_FORMAT.md §10.3) from the
    curated catalog in styles_catalog/ — see styles_catalog.py, which also
    validates it. Styles are independent of any model; with *images_dir*
    (Build's output subfolder) each style also carries the per-model
    previews generated for it, as images/<engine id>/<key>.<ext>."""
    import styles_catalog as sc

    catalog = sc.load_catalog()
    errors, _ = sc.check(catalog, None)
    if errors:
        raise SystemExit("styles catalog has errors — run styles_catalog.py --check:\n  " + "\n  ".join(errors))
    images = _collect_style_images(images_dir)
    known = {e["key"] for p in catalog["packs"] for e in p["styles"]}
    stray = sorted(set(images) - known)
    if stray:
        print(f"  ignoring {len(stray)} image(s) with no matching style key: {', '.join(stray[:8])}")
    out = []
    for pack in catalog["packs"]:
        styles = []
        image_files: dict[str, bytes] = {}
        for e in pack["styles"]:
            style = {
                "key": e["key"],
                "name": {lang: e["name"][lang] for lang in sc.LANGS if e["name"].get(lang)},
                "category": sc.category_texts(e["category"], catalog["categories"]),
                "prefix": e["prefix"],
                "suffix": e["suffix"],
                "prompt": e["prompt"],
            }
            for model_id, f in sorted(images.get(e["key"], {}).items()):
                rel = f"images/{model_id}/{e['key']}{f.suffix.lower()}"
                image_files[rel] = f.read_bytes()
                style.setdefault("images", {})[model_id] = rel
            styles.append(style)
        with_images = sum(1 for s in styles if s.get("images"))
        print(f"  {pack['id']}: {len(styles)} styles, {with_images} with images ({len(image_files)} files)")
        manifest = {
            "schema_version": 1,
            "id": pack["id"],
            "version": version,
            "default_lang": "en",
            "name": pack["name"],
            "summary": pack["summary"],
            "author": AUTHOR,
            "license": "proprietary",
            "languages": list(sc.LANGS),
            "contributes": {"styles": ["data/styles.json"]},
        }
        if pack.get("replaces"):
            manifest["replaces"] = pack["replaces"]
        out.append(write_zip(pack["id"], {"manifest.json": manifest, "data/styles.json": styles,
                                          **image_files, "LICENSE": LICENSE_TEXT}, dest=DIST_OPTIONAL))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=Path(r"D:\OPENHIKER"))
    ap.add_argument("--version", default="0.1.0")
    # Off by default — ENGINES_OPTIONAL packages are never part of a normal
    # build, only produced when explicitly asked for (see ENGINES_OPTIONAL's
    # own comment for why Krea2 Roma lives there instead of in ENGINES).
    ap.add_argument("--optional", action="store_true")
    ap.add_argument("--refine-pilot", action="store_true")
    ap.add_argument("--refine-groups", action="store_true")
    # Style packs only (they don't depend on the rest): skips engines/flows.
    ap.add_argument("--style-packs", action="store_true")
    # Just the Styling (Refine) + Style Transfer (Mix) packages.
    ap.add_argument("--style-transfer", action="store_true")
    # Folder Build > Styles saved previews into (<dir>/<engine id>/<key>.webp),
    # e.g. "C:\Users\<you>\Nomad Studio\style-previews" — or the app data
    # folder itself (e.g. "data"), whose styles.json knows every image.
    ap.add_argument("--style-images", type=Path)
    args = ap.parse_args()
    if args.style_transfer:
        for path in (build_styling(args.source, args.version), build_mix_style_transfer(args.source, args.version)):
            summary = validate(path)
            print(f"{path.name:40} {path.stat().st_size / 1024:5.0f} KB · {summary['id']} {summary['version']}"
                  f" · flows={[f['id'] for f in summary['flows']]}")
        return
    if args.style_packs:
        for path in build_style_packs(args.version, args.style_images):
            summary = validate(path)
            print(f"{path.name:40} {path.stat().st_size / 1024:5.0f} KB · {summary['id']} {summary['version']}"
                  f" · styles={summary['styles']}")
        return
    paths = [build_engine(args.source, args.version, name) for name in ENGINES] + [
        build_qwen_image_21_engine(args.version),
        build_core_create(args.source, args.version), build_create_layout(args.source, args.version),
        build_core_civitai(args.source, args.version)]
    if args.optional:
        paths += [build_engine(args.source, args.version, name, catalog=ENGINES_OPTIONAL, dest=DIST_OPTIONAL)
                  for name in ENGINES_OPTIONAL]
    if args.refine_pilot:
        paths.append(build_refine_pilot(args.source, args.version))
    if args.refine_groups:
        paths += [build_photo_editing(args.source, args.version), build_portrait_fix(args.source, args.version),
                  build_creator_pack(args.source, args.version), build_background_tools(args.source, args.version),
                  build_camera_pack(args.source, args.version), build_skin_detailer(args.source, args.version),
                  build_extract_pack(args.source, args.version), build_styling(args.source, args.version),
                  build_presets_core(args.source, args.version), build_presets_open_air(args.source, args.version),
                  build_presets_film_shadow(args.source, args.version),
                  build_mix_multi_reference(args.source, args.version),
                  build_mix_style_transfer(args.source, args.version)]
    for path in paths:
        summary = validate(path)
        engine_note = ""
        if summary["engines"]:
            with zipfile.ZipFile(path) as zf:
                rel = json.loads(zf.read("manifest.json"))["contributes"]["engines"][0]
                engine = json.loads(zf.read(rel))
            wf = len(_extract_downloads_from_workflow(engine["workflow"]))
            ann = len(engine["annotation"].get("downloads", []))
            engine_note = f" · downloads: workflow={wf} package={ann}"
        print(f"{path.name:40} {path.stat().st_size / 1024:5.0f} KB · {summary['id']} {summary['version']}"
              f" · engines={[e['name'] for e in summary['engines']]} flows={[f['id'] for f in summary['flows']]}{engine_note}")


if __name__ == "__main__":
    main()
