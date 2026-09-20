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
# Packages that ship with the app go in DIST — paths.BUNDLED_PACKAGES_DIR
# (dist/packages in a dev checkout) is scanned whole and every ZIP in it gets
# auto-installed on startup (package_service.plan_bundled globs *.zip with no
# filtering). Free/optional packs the user installs by choice — CivitAI is
# the first one — must NOT land there, or every fresh app would get them
# whether the user asked for them or not. DIST_OPTIONAL keeps them out of
# that scan while still producing a real, installable ZIP.
DIST_OPTIONAL = REPO / "dist" / "optional-packages"
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


def flow_from_path(source: Path, rel_file: str) -> dict:
    """Same as flow_from_source, but for a flow whose file exists and is
    complete but isn't (yet) registered in index.json — e.g.
    refine.pe_remove_glare, confirmed working, just missing its index entry."""
    return json.loads((source / "app" / "instructions" / rel_file).read_text(encoding="utf-8"))


def write_zip(name: str, files: dict[str, object], dest: Path = DIST) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{name}.zip"
    path.unlink(missing_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, content in files.items():
            data = content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False)
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
def _qwen_image_21_workflow() -> dict:
    return {
        "config": {
            "inputs": {"value": json.dumps({
                "name": "Qwen Image 2.1",
                # Bare filename, no subfolder — confirmed against the connected
                # ComfyUI's own UNETLoader object_info (a made-up subfolder
                # prefix here caused "node errors: 55": the quantization
                # switcher would swap in a unet_name that doesn't exist).
                "quantization": {"int8": "qwen_image_2.1_int8_convrot.safetensors"},
                # No confirmed download URLs yet for this model (too new to
                # have a settled HF repo layout at build time) — left empty
                # rather than guessing a URL that would 404 in the Setup
                # wizard. Fill in once confirmed.
                "downloads": "",
            })},
            "class_type": "PrimitiveStringMultiline",
            "_meta": {"title": "config"},
        },
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


def _qwen_image_21_edit_workflow() -> dict:
    return {
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


# ── Qwen 2.1 Camera Angles (replaces refine_qwen_2511_angles.json) ─────────
# The source chained TWO LoRAs on top of the base model: a 2511-specific
# "multiple-angles" LoRA plus the Lightning 4-step speed LoRA. Qwen 2.1 does
# viewpoint changes natively off the base model with no LoRA at all —
# verified today generating several angle changes of the same
# character/scene from one reference image, plain UNETLoader straight into
# KSampler. Both LoRA nodes (and the identity-scale ImageScaleBy the source
# had ahead of the encode step) are dropped rather than carried over
# unverified. Node ids match the source's own where the node itself carries
# over (2/3/6/7/11/15/17/20/21) so nothing else has to change.
QWEN_2511_ANGLES_WORKFLOW_REL = "workflows/refine/refine_qwen_2511_angles.json"


def _qwen_image_21_angles_workflow() -> dict:
    return {
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
                "prompt": "front view",
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
                "seed": 388457959464449, "steps": 25, "cfg": 1, "sampler_name": "euler", "scheduler": "simple",
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
        "20": {
            "inputs": {"image": ["7", 0]},
            "class_type": "GetImageSize",
            "_meta": {"title": "Get Image Size"},
        },
        "11": {
            "inputs": {"width": ["20", 0], "height": ["20", 1], "batch_size": 1},
            "class_type": "EmptyLatentImage",
            "_meta": {"title": "Empty Latent Image"},
        },
        "21": {
            "inputs": {"filename_prefix": "qwen-image-2.1-angles", "images": ["17", 0]},
            "class_type": "SaveImage",
            "_meta": {"title": "Save Image"},
        },
    }


def build_qwen_image_21_engine(version: str) -> Path:
    from app.services.workflow_service import _analyze_workflow

    workflow = _qwen_image_21_workflow()
    analysis = _analyze_workflow(workflow)
    engine = {
        "category": "image",
        "name": "Qwen Image 2.1",
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
    return write_zip(pkg_id, {"manifest.json": manifest, file_rel: engine, "LICENSE": LICENSE_TEXT}, dest=dest)


# Create › core flows shipped with the app. They only need an image engine,
# plus LM Studio for the LLM ones. Left out: the CivitAI flows (their own free
# pack, build_core_civitai below), From Template (needs template packs, which
# packages cannot carry yet) and the unfinished ones (Character, From Brief, Style).
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


# Create › CivitAI: paste a CivitAI generation block, match its model/LoRAs
# against an installed engine, generate. Left out of nomad.core-create
# (comment there) so a user who never touches CivitAI doesn't get a card
# offering to paste one — this is its own free pack, installed separately.
CIVITAI_FLOWS = [
    "create.simple_civitai", "create.enhance_civitai", "create.chat_civitai",
]
CORE_CIVITAI_VERSION = "0.1.0"


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
REFINE_PILOT_VERSION = "0.1.0"


# Applied unconditionally to every flow build_refine_pilot/
# build_refine_static_group package — a no-op for flows without this
# engine_select option, an update for the ones that offer it (Outpaint, Look
# Book once packaged, every Photo Editing/Portrait Fix/Creator Pack flow).
# steps_quick_options/steps_default: the flow-step-workflow-params.js side
# (esApplyEngine) reads these off the selected engine and re-renders the
# Steps field's quick-pick pills to match — Qwen 2.1 (8/16/25, no confirmed
# fast LoRA) needs different ones than Klein/Boogu's Lightning-style 4/8.
QWEN_ENGINE_SELECT_OVERRIDES = {
    "qwen_2511": {"label": "Qwen 2.1 Edit", "steps_quick_options": [8, 16, 25], "steps_default": 25},
}


def _update_engine_select_option(flow: dict, option_id: str, overrides: dict) -> None:
    """Merges `overrides` onto one option inside an engine_select field (e.g.
    Outpaint's "qwen_2511" -> label "Qwen 2.1 Edit" + new steps presets) —
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
    if ref == QWEN_2511_ANGLES_WORKFLOW_REL:
        return _qwen_image_21_angles_workflow()
    src_path = source / "app" / ref
    if not src_path.is_file():
        raise SystemExit(f"referenced workflow_file not found: {src_path}")
    return json.loads(src_path.read_text(encoding="utf-8"))


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
    OLD id, same pattern as REFINE_PILOT_ID_OVERRIDES/LABEL_OVERRIDES."""
    table = load_translations(source)
    files: dict[str, object] = {}
    flows = []
    workflow_refs: set[str] = set()
    unregistered = unregistered or {}
    id_overrides = id_overrides or {}
    label_overrides = label_overrides or {}
    new_fields = new_fields or {}

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
        for option_id, opt_overrides in QWEN_ENGINE_SELECT_OVERRIDES.items():
            _update_engine_select_option(flow, option_id, opt_overrides)
        for new_field in new_fields.get(flow_id, []):
            _add_flow_field(flow, new_field)
        final_id = id_overrides.get(flow_id, flow_id)
        flow["id"] = final_id
        final_flow_ids.append(final_id)
        flows.append(flow)
        files[f"flows/{final_id.split('.', 1)[1]}.json"] = flow
        workflow_refs |= _collect_workflow_file_refs(flow)

    for ref in sorted(workflow_refs):
        graph = _load_workflow_ref(source, ref)
        _strip_foreign_flow_data(graph)
        files[ref] = graph

    i18n, counts = flow_i18n(flows, table)
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
        },
    }
    print(f"  {pkg_id} texts: {counts['total']} · " + " ".join(f"{lang} {counts[lang]}" for lang in LANGS))
    return write_zip(pkg_id, {"manifest.json": manifest, **files, "LICENSE": LICENSE_TEXT,
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
    "refine.pf_relight", "refine.pf_remove_freckles", "refine.pf_remove_glasses_glare",
    "refine.pf_remove_overexposed_highlights", "refine.pf_remove_skin_glare",
]
CREATOR_PACK_FLOWS = [
    "refine.cp_cartoon_to_realistic", "refine.cp_comic_book_style", "refine.cp_headshot_generator",
    "refine.cp_pet_portrait_generator", "refine.cp_profile_picture_generator", "refine.cp_selfie_generator",
    "refine.cp_silhouette_maker", "refine.cp_superhero_generator", "refine.cp_yearbook_generator",
]
REFINE_GROUPS_VERSION = "0.1.0"


def build_photo_editing(source: Path, version: str) -> Path:
    return build_refine_static_group(
        source, version, "nomad.refine-photo-editing", "photo-editing",
        name={"en": "Photo Editing", "es": "Edición de fotos", "zh": "照片编辑", "ko": "사진 편집"},
        summary={
            "en": "Color grading, cinematic looks, restoration, watermark/glare removal and camera-angle changes.",
            "es": "Gradación de color, looks cinematográficos, restauración, quitar marcas de agua/brillos y cambio de ángulo de cámara.",
            "zh": "调色、电影感风格、修复、去除水印/眩光以及机位角度调整。",
            "ko": "컬러 그레이딩, 시네마틱 룩, 복원, 워터마크/글레어 제거, 카메라 앵글 변경.",
        },
        flow_ids=PHOTO_EDITING_FLOWS,
        unregistered=PHOTO_EDITING_UNREGISTERED,
        id_overrides={"refine.qwen_2511_angles": "refine.qwen2_angles"},
        label_overrides={"refine.qwen_2511_angles": {
            "en": "Qwen 2.1 Angles", "es": "Ángulos Qwen 2.1", "zh": "Qwen 2.1 视角", "ko": "Qwen 2.1 앵글",
        }},
        # The source never exposed Steps at all — baked at 4 into the graph,
        # tied to the Lightning LoRA the 2.1 migration dropped. Now that it's
        # a plain number input like Edit Qwen 2.1's, same quick-pick presets.
        new_fields={"refine.qwen_2511_angles": [{
            "id": "steps", "adv_key": "15.steps", "label": "Steps", "type": "number",
            "default": 25, "min": 1, "max": 25, "step": 1, "quick_options": [8, 16, 25], "advanced": True,
        }]},
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

    i18n, counts = flow_i18n(flows, table)
    manifest = {
        "schema_version": 1,
        "id": "nomad.refine-pilot",
        "version": REFINE_PILOT_VERSION,
        "default_lang": "en",
        "name": {"en": "Refine Pilot (Edit/Outpaint/Upscale)", "es": "Refine Piloto (Edit/Outpaint/Upscale)",
                  "zh": "Refine 试点（Edit/Outpaint/Upscale）", "ko": "Refine 파일럿 (Edit/Outpaint/Upscale)"},
        "summary": {
            "en": "Pilot package proving Refine's contributes.workflows path: prompt-driven edit engines, outpaint, and model/AI upscalers.",
            "es": "Paquete piloto que prueba la vía contributes.workflows de Refine: motores de edición por prompt, outpaint y upscalers.",
            "zh": "验证 Refine 的 contributes.workflows 路径的试点包：提示词驱动的编辑引擎、外扩绘制与放大器。",
            "ko": "Refine의 contributes.workflows 경로를 검증하는 파일럿 패키지: 프롬프트 기반 편집 엔진, 아웃페인트, 업스케일러.",
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
    print(f"  refine-pilot texts: {counts['total']} · " + " ".join(f"{lang} {counts[lang]}" for lang in LANGS))
    return write_zip("nomad.refine-pilot", {"manifest.json": manifest, **files, "LICENSE": LICENSE_TEXT,
                                             **{f"i18n/{lang}.json": i18n[lang] for lang in LANGS if i18n[lang]}},
                      dest=DIST_OPTIONAL)


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
    args = ap.parse_args()
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
                  build_creator_pack(args.source, args.version)]
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
