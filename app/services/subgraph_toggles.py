"""subgraph_toggles — detects ComfyUI Subgraphs inside an imported API-format
workflow, so their contents can be exposed as an optional on/off toggle
("Optional part") in Create.

ComfyUI's API format has no concept of Groups or Subgraphs — both are UI/graph
concepts that get flattened away when the frontend builds the execution
prompt. Subgraphs are the one exception: to avoid node-id collisions when a
subgraph is instantiated, ComfyUI prefixes every node it contains with the
subgraph's own node id, e.g. a subgraph node "149" containing internal nodes
"87"/"89"/"90" becomes "149:87"/"149:89"/"149:90" in the flattened prompt.
That shared prefix is the only trace left — this module reconstructs the
subgraph's boundary (which outside nodes feed it, and which outside nodes it
feeds) purely from that naming convention plus each link's target input key.

Bypass rule: if the subgraph's node(s) outside it that consume its output(s)
could instead be fed directly by one of the subgraph's own external inputs of
the *same type*, and there is exactly one such candidate, we call the toggle
"auto" and record that rewire. Zero or multiple candidates of the same type
means we can't tell which one the workflow's author intended as the
pass-through source, so the toggle is left non-auto (not offered at runtime
without a manual mapping).
"""
from __future__ import annotations

from typing import Any

from app.services.workflow_utils import _is_link

# ---------------------------------------------------------------------------
# Best-effort ComfyUI type inference from an input key name. This mirrors the
# same "guess type from is is called" approach the rest of workflow_service.py
# already uses for negative/prompt detection, and avoids requiring a live
# ComfyUI /object_info fetch during (offline) import analysis.
# ---------------------------------------------------------------------------
_KEY_TYPE_HINTS: list[tuple[str, str]] = [
    ("model", "MODEL"),
    ("clip", "CLIP"),
    ("vae", "VAE"),
    ("mask", "MASK"),
    ("latent", "LATENT"),
    ("samples", "LATENT"),
    ("image", "IMAGE"),
    ("conditioning", "CONDITIONING"),
    ("positive", "CONDITIONING"),
    ("negative", "CONDITIONING"),
    ("guider", "GUIDER"),
    ("sampler", "SAMPLER"),
    ("sigmas", "SIGMAS"),
    ("noise", "NOISE"),
]


def _infer_link_type(input_key: str) -> str:
    key = str(input_key or "").strip().lower()
    # Longest-match-first so e.g. "images.image0" hits "image" not a shorter
    # accidental substring, and "latent_image" hits "latent" before "image".
    for needle, type_name in sorted(_KEY_TYPE_HINTS, key=lambda p: -len(p[0])):
        if needle in key:
            return type_name
    return f"unknown:{key}"


def _subgraph_prefix(node_id: str) -> str | None:
    node_id = str(node_id)
    if ":" not in node_id:
        return None
    return node_id.split(":", 1)[0]


def extract_optional_subgraphs(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Detect Subgraph-flattened node clusters and, where unambiguous, the
    rewire needed to bypass them. Returns a list of dicts:

        {
            "id": "149",
            "memberNodeIds": ["149:87", "149:89", ...],
            "memberLabels": ["Load LoRA (Model only)", "Upscale Latent By", ...],
            "externalInputs": [{"memberNode": ..., "inputKey": ..., "source": [id, slot], "type": ...}],
            "externalOutputs": [{"consumerNode": ..., "inputKey": ..., "source": [subId, slot], "type": ...}],
            "auto": bool,
            "bypass": [{"consumerNode": ..., "inputKey": ..., "replacement": [id, slot]}] | [],
        }

    Pure/offline — no ComfyUI connection required.
    """
    if not isinstance(workflow, dict):
        return []

    members_by_subgraph: dict[str, list[str]] = {}
    for node_id in workflow.keys():
        prefix = _subgraph_prefix(node_id)
        if prefix is None:
            continue
        members_by_subgraph.setdefault(prefix, []).append(str(node_id))

    results: list[dict[str, Any]] = []
    for subgraph_id, member_ids in members_by_subgraph.items():
        member_set = set(member_ids)

        member_labels: list[str] = []
        external_inputs: list[dict[str, Any]] = []
        for member_id in member_ids:
            node = workflow.get(member_id, {})
            if not isinstance(node, dict):
                continue
            meta = node.get("_meta", {}) if isinstance(node.get("_meta", {}), dict) else {}
            label = str(meta.get("title", "") or node.get("class_type", "")).strip()
            if label and label not in member_labels:
                member_labels.append(label)
            inputs = node.get("inputs", {}) if isinstance(node.get("inputs", {}), dict) else {}
            for input_key, value in inputs.items():
                if not _is_link(value):
                    continue
                source_id = str(value[0])
                if source_id in member_set:
                    continue  # internal link, not a boundary
                external_inputs.append(
                    {
                        "memberNode": member_id,
                        "inputKey": input_key,
                        "source": [source_id, value[1] if len(value) > 1 else 0],
                        "type": _infer_link_type(input_key),
                    }
                )

        external_outputs: list[dict[str, Any]] = []
        for consumer_id, consumer_node in workflow.items():
            if consumer_id in member_set or not isinstance(consumer_node, dict):
                continue
            consumer_inputs = (
                consumer_node.get("inputs", {})
                if isinstance(consumer_node.get("inputs", {}), dict)
                else {}
            )
            for input_key, value in consumer_inputs.items():
                if not _is_link(value):
                    continue
                source_id = str(value[0])
                if source_id not in member_set:
                    continue
                external_outputs.append(
                    {
                        "consumerNode": str(consumer_id),
                        "inputKey": input_key,
                        "source": [source_id, value[1] if len(value) > 1 else 0],
                        "type": _infer_link_type(input_key),
                    }
                )

        bypass: list[dict[str, Any]] = []
        auto = bool(external_outputs)
        for out in external_outputs:
            # Dedup candidate sources so the same external node feeding two
            # internal nodes only counts once.
            candidates = {
                tuple(ext["source"])
                for ext in external_inputs
                if ext["type"] == out["type"]
            }
            if len(candidates) != 1:
                auto = False
                continue
            replacement = list(next(iter(candidates)))
            bypass.append(
                {
                    "consumerNode": out["consumerNode"],
                    "inputKey": out["inputKey"],
                    "replacement": replacement,
                }
            )

        results.append(
            {
                "id": subgraph_id,
                "memberNodeIds": sorted(member_ids),
                "memberLabels": member_labels,
                "externalInputs": external_inputs,
                "externalOutputs": external_outputs,
                "auto": auto and bool(bypass),
                "bypass": bypass if auto else [],
            }
        )

    results.sort(key=lambda r: r["id"])
    return results


def apply_disabled_subgraphs(
    workflow: dict[str, Any], optional_subgraphs: list[dict[str, Any]], disabled_ids: list[str]
) -> dict[str, Any]:
    """Return a copy of ``workflow`` with each subgraph id in ``disabled_ids``
    removed and its consumers rewired to the recorded bypass source. Silently
    skips ids with no matching (or non-auto) entry — callers only ever offer
    auto=True subgraphs as toggles, so this is a defensive no-op, not an
    error path."""
    if not disabled_ids:
        return workflow

    by_id = {str(sg.get("id")): sg for sg in optional_subgraphs}
    output = dict(workflow)
    for raw_id in disabled_ids:
        sg = by_id.get(str(raw_id))
        if not sg or not sg.get("auto") or not sg.get("bypass"):
            continue
        for rewire in sg["bypass"]:
            consumer = output.get(rewire["consumerNode"])
            if not isinstance(consumer, dict):
                continue
            consumer_inputs = consumer.get("inputs")
            if isinstance(consumer_inputs, dict):
                consumer_inputs[rewire["inputKey"]] = list(rewire["replacement"])
        for member_id in sg.get("memberNodeIds", []):
            output.pop(member_id, None)
    return output
