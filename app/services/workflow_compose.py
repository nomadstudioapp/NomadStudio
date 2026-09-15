"""workflow_compose — compose model catalog helpers."""
from __future__ import annotations

from typing import Any

from app.services.workflow_utils import _extract_lora_loader_keys

# ---------------------------------------------------------------------------
# Compose model helpers
# ---------------------------------------------------------------------------


def _build_compose_models_from_imports(data: dict[str, Any]) -> list[dict[str, Any]]:
    imports = (
        data.get("imports", []) if isinstance(data.get("imports", []), list) else []
    )
    models: list[dict[str, Any]] = []

    for record in imports:
        if not isinstance(record, dict):
            continue
        if str(record.get("category", "")).strip().lower() != "compose":
            continue
        workflow = (
            record.get("workflow", {})
            if isinstance(record.get("workflow", {}), dict)
            else {}
        )
        analysis = (
            record.get("analysis", {})
            if isinstance(record.get("analysis", {}), dict)
            else {}
        )
        detected = (
            analysis.get("detected", {})
            if isinstance(analysis.get("detected", {}), dict)
            else {}
        )

        lora_keys = _extract_lora_loader_keys(workflow)
        model_item = {
            "id": str(record.get("id", "")),
            "name": str(record.get("name", "Compose Workflow")),
            "importId": str(record.get("id", "")),
            "comfyApiUrl": str(record.get("comfyApiUrl", "")).strip(),
            "hasImageInput": bool(detected.get("hasImageInput", False)),
            "hasStyleImageInput": bool(detected.get("hasStyleImageInput", False)),
            "resizeNodeIds": detected.get("resizeNodeIds", []),
            "hasNegativePrompt": bool(detected.get("hasNegativePrompt", False)),
            "hasLora": len(lora_keys) > 0,
            "loraKeys": lora_keys,
            "hasLatent": bool(str(detected.get("latentNodeId", "")).strip()),
        }
        models.append(model_item)

    return models


def _compose_models_catalog(data: dict[str, Any]) -> list[dict[str, Any]]:
    return _build_compose_models_from_imports(data)


def _compose_model_by_id(data: dict[str, Any], model_id: str) -> dict[str, Any]:
    catalog = _compose_models_catalog(data)
    if not catalog:
        return {}
    target = str(model_id or "").strip()
    for model in catalog:
        if str(model.get("id", "")).strip() == target:
            return model
    return catalog[0]
