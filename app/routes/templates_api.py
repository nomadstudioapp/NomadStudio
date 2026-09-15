from __future__ import annotations

import re
from copy import deepcopy

from flask import Blueprint, jsonify, request

from app.config import (
    MAX_TEMPLATE_CONTENT_LENGTH,
    MAX_TEMPLATE_DESCRIPTION_LENGTH,
    MAX_TEMPLATE_NAME_LENGTH,
)

templates_api_bp = Blueprint("templates_api", __name__)

VARIABLE_REGEX = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

TEMPLATES = [
    {
        "id": "tpl-1",
        "name": "Street Character",
        "description": "Fast character drop-in template",
        "content": "This is a {character} in the street, cinematic lighting, {style}",
        "fields": [
            {
                "key": "character",
                "label": "Character",
                "type": "text",
                "required": True,
                "defaultValue": "samurai",
            },
            {
                "key": "style",
                "label": "Style",
                "type": "select",
                "required": True,
                "defaultValue": "anime",
                "options": ["anime", "photo", "comic"],
            },
        ],
    },
    {
        "id": "tpl-2",
        "name": "Product Hero",
        "description": "Product shot for landing pages",
        "content": "A premium {product} on {surface} with {lighting} lighting",
        "fields": [
            {
                "key": "product",
                "label": "Product",
                "type": "text",
                "required": True,
                "defaultValue": "headphones",
            },
            {
                "key": "surface",
                "label": "Surface",
                "type": "text",
                "required": False,
                "defaultValue": "black marble",
            },
            {
                "key": "lighting",
                "label": "Lighting",
                "type": "select",
                "required": True,
                "defaultValue": "soft",
                "options": ["soft", "hard", "neon"],
            },
        ],
    },
]


def _extract_variables(content: str) -> list[str]:
    keys = VARIABLE_REGEX.findall(content)
    seen = set()
    ordered = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def _render_prompt(content: str, values: dict[str, str]) -> tuple[str, list[str]]:
    missing = []

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = str(values.get(key, "")).strip()
        if not value:
            missing.append(key)
            return "{" + key + "}"
        return value

    staged = content.replace("{{", "__LBRACE__").replace("}}", "__RBRACE__")
    rendered = VARIABLE_REGEX.sub(_replace, staged)
    rendered = rendered.replace("__LBRACE__", "{").replace("__RBRACE__", "}")
    return rendered, missing


@templates_api_bp.get("/templates")
def list_templates():
    return jsonify(TEMPLATES)


@templates_api_bp.post("/templates")
def create_template():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid JSON payload"}), 400

    content = str(payload.get("content", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not name or not content:
        return jsonify({"error": "name and content are required"}), 400
    if len(name) > MAX_TEMPLATE_NAME_LENGTH:
        return jsonify(
            {"error": f"name exceeds max length ({MAX_TEMPLATE_NAME_LENGTH})"}
        ), 400
    if len(content) > MAX_TEMPLATE_CONTENT_LENGTH:
        return jsonify(
            {"error": f"content exceeds max length ({MAX_TEMPLATE_CONTENT_LENGTH})"}
        ), 400

    description = str(payload.get("description", "")).strip()
    if len(description) > MAX_TEMPLATE_DESCRIPTION_LENGTH:
        return jsonify(
            {
                "error": f"description exceeds max length ({MAX_TEMPLATE_DESCRIPTION_LENGTH})"
            }
        ), 400

    template_id = f"tpl-{len(TEMPLATES) + 1}"
    fields = payload.get("fields") or []
    record = {
        "id": template_id,
        "name": name,
        "description": description,
        "content": content,
        "fields": fields,
    }
    TEMPLATES.append(record)
    return jsonify(record), 201


@templates_api_bp.post("/templates/parse")
def parse_template():
    payload = request.get_json(silent=True) or {}
    content = str(payload.get("content", ""))
    return jsonify({"variables": _extract_variables(content)})


@templates_api_bp.post("/templates/render")
def render_template_prompt():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid JSON payload"}), 400

    content = str(payload.get("content", ""))
    values = payload.get("values") or {}
    if not isinstance(values, dict):
        return jsonify({"error": "values must be an object"}), 400

    rendered, missing = _render_prompt(content, values)
    return jsonify(
        {
            "renderedPrompt": rendered,
            "missing": missing,
            "canGenerate": len(missing) == 0,
        }
    )


@templates_api_bp.get("/templates/<template_id>")
def get_template(template_id: str):
    record = next((item for item in TEMPLATES if item["id"] == template_id), None)
    if record is None:
        return jsonify({"error": "template not found"}), 404
