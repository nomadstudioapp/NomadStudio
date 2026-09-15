from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.services.http_client import http_json

def _extract_civitai_identifiers(uri: str) -> tuple[str, str]:
    text = str(uri or "").strip()
    if not text:
        return "", ""

    parsed = urlparse(text)
    host = str(parsed.netloc or "").lower()
    if "civitai.com" not in host:
        return "", ""

    model_id = ""
    model_version_id = ""

    query = parse_qs(parsed.query or "")
    model_version_id = str((query.get("modelVersionId") or [""])[0] or "").strip()

    path = parsed.path or ""
    model_match = re.search(r"/models/(\d+)", path, flags=re.IGNORECASE)
    if model_match:
        model_id = str(model_match.group(1) or "").strip()

    download_match = re.search(r"/api/download/models/(\d+)", path, flags=re.IGNORECASE)
    if download_match and not model_version_id:
        model_version_id = str(download_match.group(1) or "").strip()

    return model_id, model_version_id


def _extract_civitai_details(
    uri: str, cache: dict[str, dict[str, str]]
) -> dict[str, str]:
    raw_uri = str(uri or "").strip()
    if not raw_uri:
        return {"imageUrl": "", "name": "", "triggerWords": "", "classification": ""}
    if raw_uri in cache:
        return cache[raw_uri]

    model_id, model_version_id = _extract_civitai_identifiers(raw_uri)
    details = {
        "imageUrl": "",
        "name": "",
        "triggerWords": "",
        "classification": "",
        "weight": "",
    }

    def _normalize_words(value) -> str:
        if isinstance(value, list):
            words = [str(item).strip() for item in value if str(item).strip()]
            return ", ".join(words)
        return str(value or "").strip()

    try:
        if model_version_id:
            model_version_url = (
                f"https://civitai.com/api/v1/model-versions/{model_version_id}"
            )
            logger.warning(
                "[LoRA][Civitai] GET %s (source=%s)", model_version_url, raw_uri
            )
            payload = http_json(model_version_url, timeout=8)
            images = payload.get("images", []) if isinstance(payload, dict) else []
            if isinstance(payload, dict):
                details["name"] = str(payload.get("name", "")).strip()
                details["triggerWords"] = _normalize_words(
                    payload.get("trainedWords", "")
                )
                details["classification"] = str(payload.get("baseModel", "")).strip()
            if isinstance(images, list):
                for item in images:
                    if not isinstance(item, dict):
                        continue
                    if not details.get("weight"):
                        meta_info = item.get("meta") or {}
                        resources = meta_info.get("resources") or []
                        if isinstance(resources, list):
                            for r in resources:
                                if (
                                    isinstance(r, dict)
                                    and r.get("type") == "lora"
                                    and r.get("weight")
                                ):
                                    details["weight"] = str(r["weight"])
                                    break
                    candidate = str(item.get("url", "")).strip()
                    if candidate and not details.get("imageUrl"):
                        details["imageUrl"] = candidate
                    if details.get("imageUrl") and details.get("weight"):
                        break
            model_ref = payload.get("model") if isinstance(payload, dict) else None
            if isinstance(model_ref, dict):
                if not details["name"]:
                    details["name"] = str(model_ref.get("name", "")).strip()
                if not details["classification"]:
                    details["classification"] = str(model_ref.get("type", "")).strip()

            # Fallback: resolve model info by modelId for richer metadata and preview.
            model_ref_id = ""
            if isinstance(payload, dict):
                model_ref_id = str(payload.get("modelId", "")).strip()
            if not model_ref_id and isinstance(model_ref, dict):
                model_ref_id = str(model_ref.get("id", "")).strip()

            if model_ref_id and (
                not details["imageUrl"] or not details["classification"]
            ):
                model_url = f"https://civitai.com/api/v1/models/{model_ref_id}"
                logger.warning(
                    "[LoRA][Civitai] GET %s (fallback modelId from version)", model_url
                )
                model_payload = http_json(model_url, timeout=8)
                if isinstance(model_payload, dict):
                    if not details["classification"]:
                        details["classification"] = str(
                            model_payload.get("type", "")
                        ).strip()
                    versions = model_payload.get("modelVersions", [])
                    if isinstance(versions, list):
                        for version in versions:
                            if not isinstance(version, dict):
                                continue
                            if not details["name"]:
                                details["name"] = str(version.get("name", "")).strip()
                            if not details["triggerWords"]:
                                details["triggerWords"] = _normalize_words(
                                    version.get("trainedWords", "")
                                )
                            if not details["classification"]:
                                details["classification"] = str(
                                    version.get("baseModel", "")
                                ).strip()
                            images = (
                                version.get("images", [])
                                if isinstance(version.get("images", []), list)
                                else []
                            )
                            for item in images:
                                if not isinstance(item, dict):
                                    continue
                                candidate = str(item.get("url", "")).strip()
                                if candidate:
                                    details["imageUrl"] = candidate
                                    break
                            if details["imageUrl"]:
                                break
        elif model_id:
            model_url = f"https://civitai.com/api/v1/models/{model_id}"
            logger.warning("[LoRA][Civitai] GET %s (source=%s)", model_url, raw_uri)
            payload = http_json(model_url, timeout=8)
            if isinstance(payload, dict):
                details["classification"] = str(payload.get("type", "")).strip()
            versions = (
                payload.get("modelVersions", []) if isinstance(payload, dict) else []
            )
            if isinstance(versions, list):
                for version in versions:
                    if not isinstance(version, dict):
                        continue
                    if not details["name"]:
                        details["name"] = str(version.get("name", "")).strip()
                    if not details["triggerWords"]:
                        details["triggerWords"] = _normalize_words(
                            version.get("trainedWords", "")
                        )
                    if not details["classification"]:
                        details["classification"] = str(
                            version.get("baseModel", "")
                        ).strip()
                    images = (
                        version.get("images", [])
                        if isinstance(version.get("images", []), list)
                        else []
                    )
                    for item in images:
                        if not isinstance(item, dict):
                            continue
                        candidate = str(item.get("url", "")).strip()
                        if candidate:
                            details["imageUrl"] = candidate
                            break
                    if details["imageUrl"]:
                        break
    except Exception as exc:
        logger.warning(
            "[LoRA][Civitai] failed source=%s modelId=%s modelVersionId=%s error=%s",
            raw_uri,
            model_id,
            model_version_id,
            exc,
        )
        details = {"imageUrl": "", "name": "", "triggerWords": "", "classification": ""}

    cache[raw_uri] = details
    return details




def _extract_civitai_preview_image(uri: str, cache: dict[str, str]) -> str:
    raw_uri = str(uri or "").strip()
    if not raw_uri:
        return ""
    if raw_uri in cache:
        return cache[raw_uri]
    details = _extract_civitai_details(raw_uri, {})
    image_url = str(details.get("imageUrl", "")).strip()
    cache[raw_uri] = image_url
    return image_url
