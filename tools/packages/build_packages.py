"""Build Nomad Studio packages from the working catalog in OPENHIKER
(docs/PACKAGE_FORMAT.md §15.1 step 3).

    python tools/packages/build_packages.py --source D:\\OPENHIKER

Writes to dist/packages/ and validates every ZIP with the importer's own code
(app/services/package_service.inspect_zip), so a package that builds is a
package the app accepts.

Packages:
- the 7 free image engines (nomad.engine.*), one per engine in
  import_registry.json
- nomad.core-create: Create › Simple, needs any image engine

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
    "Krea2 Roma": ("krea2-roma", {
        "en": "Krea 2 with the Roma setup. Some of its files come from third parties.",
        "es": "Krea 2 con la configuración Roma. Algunos de sus ficheros son de terceros.",
        "zh": "采用 Roma 配置的 Krea 2，部分文件来自第三方。",
        "ko": "Roma 구성의 Krea 2. 일부 파일은 서드파티 제공입니다.",
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
    "Krea2 Roma": [
        {"subfolder": "text_encoders", "filename": "qwen3vl_4b_fp8_scaled.safetensors",
         "url": "https://huggingface.co/Comfy-Org/Krea-2/resolve/main/text_encoders/qwen3vl_4b_fp8_scaled.safetensors?download=true"},
        {"subfolder": "vae", "filename": "wan_2.1_vae.safetensors",
         "url": "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors?download=true"},
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


def build_core_create(source: Path, version: str) -> Path:
    flow = flow_from_source(source, "create.simple")
    manifest = {
        "schema_version": 1,
        "id": "nomad.core-create",
        "version": version,
        "default_lang": "en",
        "name": {"en": "Core Create", "es": "Create básico", "zh": "基础创作", "ko": "기본 만들기"},
        "summary": {
            "en": "Simple: write a prompt, pick an engine, generate.",
            "es": "Simple: escribe un prompt, elige un motor y genera.",
            "zh": "简单：写提示词，选择引擎，生成。",
            "ko": "간단: 프롬프트를 쓰고 엔진을 고른 뒤 생성합니다.",
        },
        "author": AUTHOR,
        "license": "proprietary",
        "group": {"id": "core", "label": {"en": "Core"}},
        "requires": {"engines": [{"category": "image"}]},
        "contributes": {"flows": ["flows/simple.json"]},
    }
    return write_zip("nomad.core-create", {"manifest.json": manifest, "flows/simple.json": flow, "LICENSE": LICENSE_TEXT})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=Path(r"D:\OPENHIKER"))
    ap.add_argument("--version", default="0.1.0")
    args = ap.parse_args()
    paths = [build_engine(args.source, args.version, name) for name in ENGINES] + [build_core_create(args.source, args.version)]
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
