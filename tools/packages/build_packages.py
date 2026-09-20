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
import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from app.routes.models_api_modules.imports_routes import _extract_downloads_from_workflow  # noqa: E402
from app.services import package_service  # noqa: E402

DIST = REPO / "dist" / "packages"
LICENSE_TEXT = "Copyright (c) Nomad Studio. All rights reserved.\nInternal test package — not for distribution.\n"
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
    "Qwen Image": ("qwen-image", {
        "en": "Qwen Image Edit 2511 with a Lightning LoRA for fewer steps.",
        "es": "Qwen Image Edit 2511 con una LoRA Lightning para usar menos pasos.",
        "zh": "Qwen Image Edit 2511，配合 Lightning LoRA 以更少步数生成。",
        "ko": "Qwen Image Edit 2511과 Lightning LoRA로 더 적은 단계에서 생성합니다.",
    }),
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
    "Qwen Image": [
        {"subfolder": "loras/qwen_2511", "filename": "Qwen-Image-Lightning-4steps-V2.0-bf16.safetensors",
         "url": "https://huggingface.co/lightx2v/Qwen-Image-Lightning/resolve/main/Qwen-Image-Lightning-4steps-V2.0-bf16.safetensors?download=true"},
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
    """English text → {lang: translation}, from the app dictionary plus the
    extra table next to this script (texts the dictionary never had)."""
    table: dict[str, dict[str, str]] = {}
    for lang in LANGS:
        data = json.loads((source / "app" / "static" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
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


def add_card_texts(flow: dict, table: dict[str, dict[str, str]]) -> dict:
    """Card label and description in every language we have (§7.1). The flat
    English fields stay for older installs."""
    def texts(english: str) -> dict[str, str]:
        return {"en": english, **{k: v for k, v in (table.get(english) or {}).items()}}

    card = {"tags": list(flow.get("card_tags") or [])}
    if isinstance(flow.get("label"), str):
        card["label"] = texts(flow["label"])
    if isinstance(flow.get("card_desc"), str):
        card["desc"] = texts(flow["card_desc"])
    flow["card"] = card
    return flow


def flow_i18n(flows: list[dict], table: dict[str, dict[str, str]]) -> tuple[dict[str, dict], dict[str, int]]:
    """{lang: {flow id: {path: text}}} plus how many texts each language covers."""
    files: dict[str, dict] = {lang: {} for lang in LANGS}
    counts = {lang: 0 for lang in LANGS}
    total = 0
    for flow in flows:
        paths = _texts_by_path(flow)
        total += len(paths)
        for lang in LANGS:
            translated = {path: table[text][lang] for path, text in paths.items()
                          if text in table and lang in table[text]}
            if translated:
                files[lang][flow["id"]] = translated
                counts[lang] += len(translated)
    counts["total"] = total
    return files, counts


def flow_from_source(source: Path, flow_id: str) -> dict:
    index = json.loads((source / "app" / "instructions" / "index.json").read_text(encoding="utf-8"))
    entry = next((e for e in index["flows"] if e["id"] == flow_id), None)
    if entry is None:
        raise SystemExit(f"flow {flow_id!r} not in {source} index.json")
    return json.loads((source / "app" / "instructions" / entry["file"]).read_text(encoding="utf-8"))


def write_zip(name: str, files: dict[str, object]) -> Path:
    DIST.mkdir(parents=True, exist_ok=True)
    path = DIST / f"{name}.zip"
    path.unlink(missing_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, content in files.items():
            data = content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False)
            zf.writestr(rel, data)
    return path


def validate(path: Path) -> dict:
    return package_service.inspect_zip(path, package_service._empty_index(), builtin_flow_ids=set())


def build_engine(source: Path, version: str, name: str) -> Path:
    slug, summary = ENGINES[name]
    engine = engine_from_registry(source, name)
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
    return write_zip(pkg_id, {"manifest.json": manifest, file_rel: engine, "LICENSE": LICENSE_TEXT})


# Create › core flows shipped with the app. They only need an image engine,
# plus LM Studio for the LLM ones. Left out: the CivitAI flows (their own free
# pack later), From Template (needs template packs, which packages cannot
# carry yet) and the unfinished ones (Character, From Brief, Style).
CORE_CREATE_FLOWS = [
    "create.simple", "create.simple_json", "create.assist", "create.chat",
    "create.variations", "create.variations_json", "create.story", "create.scenes",
    "create.portraits", "create.posters", "create.describe_image", "create.bulk_vision",
]
CORE_CREATE_VERSION = "0.2.0"


def build_core_create(source: Path, version: str) -> Path:
    table = load_translations(source)
    files: dict[str, object] = {}
    flows = []
    for flow_id in CORE_CREATE_FLOWS:
        flow = add_card_texts(flow_from_source(source, flow_id), table)
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
            "en": "The base Create flows: Simple, Assist, Chat, Variations, Story, Scenes, Portraits, Posters and image description. The AI-assisted ones use LM Studio.",
            "es": "Los flows base de Create: Simple, Assist, Chat, Variations, Story, Scenes, Portraits, Posters y descripción de imágenes. Los que usan IA necesitan LM Studio.",
            "zh": "Create 基础流程：Simple、Assist、Chat、Variations、Story、Scenes、Portraits、Posters 以及图像描述。AI 辅助流程需要 LM Studio。",
            "ko": "Create 기본 플로우: Simple, Assist, Chat, Variations, Story, Scenes, Portraits, Posters, 이미지 설명. AI 보조 플로우는 LM Studio가 필요합니다.",
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
        flows.append(add_card_texts(flow, table))
        files[f"flows/{flow_id.split('.', 1)[1]}.json"] = flow
    i18n, counts = flow_i18n(flows, table)
    manifest = {
        "schema_version": 1,
        "id": "nomad.create-layout",
        "version": version,
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=Path(r"D:\OPENHIKER"))
    ap.add_argument("--version", default="0.1.0")
    args = ap.parse_args()
    paths = [build_engine(args.source, args.version, name) for name in ENGINES] + [
        build_core_create(args.source, args.version), build_create_layout(args.source, args.version)]
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
