from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from app.routes.models_api_modules.imports_civitai import _extract_civitai_preview_image
from app.services.workflow_service import _parse_workflow_config_node


def _parse_lora_catalog_line(raw_line: str) -> dict[str, str] | None:
    line = str(raw_line or "").strip()
    if not line:
        return None

    segments = [part.strip() for part in line.split(";") if str(part).strip()]
    if not segments:
        return None

    first = segments[0]
    if ":" in first:
        prefix, value = first.split(":", 1)
        if prefix.strip().lower() == "loras":
            first = value.strip()

    filename = os.path.basename(first.strip())
    if not filename:
        return None

    lora_name = ""
    trigger_words = ""
    civitai_uri = ""
    classification = ""

    for token in segments[1:]:
        if not token:
            continue
        if token.lower().startswith("http://") or token.lower().startswith("https://"):
            if not civitai_uri:
                civitai_uri = token
            continue
        if ":" not in token:
            continue
        key, value = token.split(":", 1)
        key_lower = str(key or "").strip().lower()
        value_text = str(value or "").strip()
        if not value_text:
            continue
        if key_lower in {"uri", "url"}:
            civitai_uri = value_text
        elif key_lower in {"name", "lora_name", "lora"}:
            lora_name = value_text
        elif key_lower in {"trigger", "triggers", "trigger_words"}:
            trigger_words = value_text
        elif key_lower in {"kind", "classification", "class", "category"}:
            classification = value_text

    return {
        "fileName": filename,
        "name": lora_name,
        "triggerWords": trigger_words,
        "uri": civitai_uri,
        "classification": classification,
    }


def _is_lora_catalog_candidate_line(raw_line: str, node_title: str = "") -> bool:
    line = str(raw_line or "").strip().lower()
    if not line:
        return False

    title = str(node_title or "").strip().lower()
    if "lora" in title:
        return True

    if line.startswith("loras:"):
        return True

    # Rich catalog rows usually include explicit metadata fields.
    if (
        ";name:" in line
        or ";trigger:" in line
        or ";kind:" in line
        or ";classification:" in line
    ):
        return True

    return False


def _extract_lora_catalog(workflow: dict) -> list[dict[str, str]]:
    if not isinstance(workflow, dict):
        return []

    catalog: list[dict[str, str]] = []
    catalog_index: dict[str, int] = {}  # key -> index in catalog for field-level merge

    def add_entry(entry: dict[str, str]) -> None:
        filename = os.path.basename(str(entry.get("fileName", "")).strip())
        if not filename:
            return
        key = filename.lower()
        new_name = str(entry.get("name", "")).strip()
        new_trigger = str(entry.get("triggerWords", "")).strip()
        new_uri = str(entry.get("uri", "")).strip()
        new_classification = str(entry.get("classification", "")).strip()
        if key in catalog_index:
            # Merge: fill in any missing fields from this new entry.
            existing = catalog[catalog_index[key]]
            if not existing["name"] and new_name:
                existing["name"] = new_name
            if not existing["triggerWords"] and new_trigger:
                existing["triggerWords"] = new_trigger
            if not existing["uri"] and new_uri:
                existing["uri"] = new_uri
            if not existing["classification"] and new_classification:
                existing["classification"] = new_classification
            return
        catalog_index[key] = len(catalog)
        catalog.append(
            {
                "fileName": filename,
                "name": new_name,
                "triggerWords": new_trigger,
                "uri": new_uri,
                "classification": new_classification,
            }
        )

    def _extract_download_uri_map() -> dict[str, str]:
        uri_map: dict[str, str] = {}

        # Config node format: parse the downloads string embedded in the JSON value.
        config_data = _parse_workflow_config_node(workflow)
        if config_data:
            downloads_raw = str(config_data.get("downloads", "") or "").strip()
            for raw_line in downloads_raw.splitlines():
                if not _is_lora_catalog_candidate_line(raw_line, "downloads"):
                    continue
                parsed = _parse_lora_catalog_line(raw_line)
                if not parsed:
                    continue
                file_name = os.path.basename(str(parsed.get("fileName", "")).strip())
                uri = str(parsed.get("uri", "")).strip()
                if file_name and uri:
                    key = file_name.lower()
                    if key not in uri_map:
                        uri_map[key] = uri

        # Legacy format: scan PrimitiveStringMultiline nodes directly.
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            if str(node.get("class_type", "")).strip() != "PrimitiveStringMultiline":
                continue

            meta = (
                node.get("_meta", {}) if isinstance(node.get("_meta", {}), dict) else {}
            )
            title = str(meta.get("title", "")).strip()

            inputs = (
                node.get("inputs", {})
                if isinstance(node.get("inputs", {}), dict)
                else {}
            )
            raw_value = str(inputs.get("value", "")).strip()
            if not raw_value:
                continue

            for raw_line in raw_value.splitlines():
                if not _is_lora_catalog_candidate_line(raw_line, title):
                    continue
                parsed = _parse_lora_catalog_line(raw_line)
                if not parsed:
                    continue
                file_name = os.path.basename(str(parsed.get("fileName", "")).strip())
                uri = str(parsed.get("uri", "")).strip()
                if not file_name or not uri:
                    continue
                key = file_name.lower()
                if key not in uri_map:
                    uri_map[key] = uri

        return uri_map

    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type", "")).strip() != "PrimitiveStringMultiline":
            continue
        meta = node.get("_meta", {}) if isinstance(node.get("_meta", {}), dict) else {}
        title = str(meta.get("title", "")).strip()

        # Only nodes whose title contains "lora" carry LoRA metadata (name/kind/trigger).
        # The Downloads node is for import/download only — skip it here.
        if "lora" not in title.lower():
            continue

        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        raw_value = str(inputs.get("value", "")).strip()
        if not raw_value:
            continue

        for raw_line in raw_value.splitlines():
            if not _is_lora_catalog_candidate_line(raw_line, title):
                continue
            parsed = _parse_lora_catalog_line(raw_line)
            if parsed:
                add_entry(parsed)

    download_uri_map = _extract_download_uri_map()
    for item in catalog:
        file_key = str(item.get("fileName", "")).strip().lower()
        if not file_key:
            continue
        if not str(item.get("uri", "")).strip() and file_key in download_uri_map:
            item["uri"] = download_uri_map[file_key]
        fallback_uri = str(download_uri_map.get(file_key, "")).strip()
        if fallback_uri:
            item["uri"] = fallback_uri

    if catalog:
        return catalog

    supported_classes = {"LoraLoader", "LoraLoaderModelOnly"}
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", "")).strip()
        inputs = (
            node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
        )
        if class_type not in supported_classes:
            if "lora_name" not in inputs:
                continue
            meta = (
                node.get("_meta", {}) if isinstance(node.get("_meta", {}), dict) else {}
            )
            title = str(meta.get("title", "")).strip().lower()
            class_lower = class_type.lower()
            if not (
                ("lora" in class_lower) or ("load lora" in title) or (title == "lora")
            ):
                continue

        raw_lora_name = inputs.get("lora_name")
        if (
            isinstance(raw_lora_name, list)
            and raw_lora_name
            and isinstance(raw_lora_name[0], str)
        ):
            candidate = str(
                _resolve_text_from_node(workflow, str(raw_lora_name[0]))
            ).strip()
        else:
            candidate = str(raw_lora_name or "").strip()
        filename = os.path.basename(candidate)
        if not filename:
            continue
        fallback_uri = str(download_uri_map.get(filename.lower(), "")).strip()
        add_entry(
            {
                "fileName": filename,
                "name": "",
                "triggerWords": "",
                "uri": fallback_uri,
                "classification": "",
            }
        )

    return catalog


def _extract_verified_loras(workflow: dict) -> list[str]:
    catalog = _extract_lora_catalog(workflow)
    return [
        str(item.get("fileName", "")).strip()
        for item in catalog
        if str(item.get("fileName", "")).strip()
    ]


_MODEL_FILE_EXTENSIONS = {".safetensors", ".gguf", ".pth", ".pt", ".bin", ".ckpt"}


def _extract_model_files(workflow: dict) -> list[str]:
    """Scan workflow inputs and collect model file references by extension."""
    if not isinstance(workflow, dict):
        return []
    files: list[str] = []
    seen: set[str] = set()
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for value in inputs.values():
            if not isinstance(value, str):
                continue
            name = value.strip()
            if not name:
                continue
            ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in _MODEL_FILE_EXTENSIONS and name not in seen:
                files.append(name)
                seen.add(name)
    return sorted(files)


