"""Build Nomad Studio packages from the working catalog in OPENHIKER
(docs/PACKAGE_FORMAT.md §15.1 step 3).

    python tools/packages/build_packages.py --source D:\\OPENHIKER

Writes to dist/packages/ and validates every ZIP with the importer's own code
(app/services/package_service.inspect_zip), so a package that builds is a
package the app accepts.

First packages (end-to-end test: empty install → install both → generate):
- nomad.engine.z-image-turbo  engine, from import_registry.json "Z-Image Turbo"
- nomad.core-create           Create › Simple flow, needs any image engine

Engines ship the workflow's own defaults (analysis), never the values saved in
the source registry: those include the developer's last prompts and choices.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from app.services import package_service  # noqa: E402

DIST = REPO / "dist" / "packages"
LICENSE_TEXT = "Copyright (c) Nomad Studio. All rights reserved.\nInternal test package — not for distribution.\n"
AUTHOR = {"name": "Nomad Studio"}


def engine_from_registry(source: Path, name: str) -> dict:
    registry = json.loads((source / "app" / "workflows" / "import_registry.json").read_text(encoding="utf-8"))
    record = next((r for r in registry.get("imports", []) if r.get("name") == name), None)
    if record is None:
        raise SystemExit(f"engine {name!r} not found in {source}")
    analysis = record["analysis"]
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
        "annotation": {k: v for k, v in (record.get("annotation") or {}).items() if k in ("downloads", "loras", "optionalSubgraphs")},
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


def build_engine(source: Path, version: str) -> Path:
    engine = engine_from_registry(source, "Z-Image Turbo")
    manifest = {
        "schema_version": 1,
        "id": "nomad.engine.z-image-turbo",
        "version": version,
        "default_lang": "en",
        "name": {"en": "Z-Image Turbo", "es": "Z-Image Turbo", "zh": "Z-Image Turbo", "ko": "Z-Image Turbo"},
        "summary": {
            "en": "Fast image engine. Generates in a few steps.",
            "es": "Motor de imagen rápido. Genera en pocos pasos.",
            "zh": "快速图像引擎，只需几步即可生成。",
            "ko": "빠른 이미지 엔진. 적은 단계로 생성합니다.",
        },
        "author": AUTHOR,
        "license": "proprietary",
        "contributes": {"engines": ["engines/z_image_turbo.json"]},
    }
    return write_zip("nomad.engine.z-image-turbo", {
        "manifest.json": manifest,
        "engines/z_image_turbo.json": engine,
        "LICENSE": LICENSE_TEXT,
    })


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
    return write_zip("nomad.core-create", {
        "manifest.json": manifest,
        "flows/simple.json": flow,
        "LICENSE": LICENSE_TEXT,
    })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=Path(r"D:\OPENHIKER"))
    ap.add_argument("--version", default="0.1.0")
    args = ap.parse_args()
    for build in (build_engine, build_core_create):
        path = build(args.source, args.version)
        summary = validate(path)
        print(f"{path.name}: {path.stat().st_size / 1024:.0f} KB · {summary['id']} {summary['version']} · "
              f"engines={[e['name'] for e in summary['engines']]} flows={[f['id'] for f in summary['flows']]} "
              f"missing={summary['requiresMissing']} warnings={summary['warnings']}")


if __name__ == "__main__":
    main()
