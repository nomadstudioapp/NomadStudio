"""Generate app/static/data/custom_node_packs.json — which custom-node pack
provides each ComfyUI node class, and where to get it.

Read from a working ComfyUI (the one the flows were built and tested on):
``/object_info`` says which module each class comes from
(``custom_nodes.<folder>``); the folder's pyproject.toml ``[project.urls]
Repository`` (or its own git remote) says where it lives. The app uses this
to tell a user which pack to install when ComfyUI reports a node it does not
know (app/services/flow_requirements.py).

Usage:
    python tools/packages/gen_node_packs.py --comfy-url http://127.0.0.1:8188 \
        --comfy-root D:/COMFYUI_HIKER_INT8/ComfyUI
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "app" / "static" / "data" / "custom_node_packs.json"

# Packs whose folder carries neither a pyproject URL nor its own git remote.
KNOWN_REPOS: dict[str, str] = {
    # A single file ComfyUI ships as an example, copied into custom_nodes.
    "websocket_image_save": "https://github.com/comfyanonymous/ComfyUI/blob/master/custom_nodes/websocket_image_save.py",
}


def _pack_info(folder: Path) -> dict[str, str]:
    info = {"name": folder.name, "repo": "", "registry_id": ""}
    pyproject = folder / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project = data.get("project") or {}
            info["registry_id"] = str(project.get("name") or "")
            urls = project.get("urls") or {}
            info["repo"] = str(urls.get("Repository") or urls.get("repository") or urls.get("Homepage") or "")
        except (tomllib.TOMLDecodeError, OSError):
            pass
    if not info["repo"] and (folder / ".git").exists():
        try:
            info["repo"] = subprocess.run(["git", "-C", str(folder), "remote", "get-url", "origin"],
                                          capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    info["repo"] = re.sub(r"\.git$", "", info["repo"] or KNOWN_REPOS.get(folder.name, ""))
    return info


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--comfy-root", required=True, help="ComfyUI folder (the one holding custom_nodes)")
    args = parser.parse_args()

    object_info = json.loads(urlopen(f"{args.comfy_url.rstrip('/')}/object_info", timeout=60).read())
    custom_nodes = Path(args.comfy_root) / "custom_nodes"
    packs: dict[str, dict[str, str]] = {}
    classes: dict[str, str] = {}
    for class_type, info in sorted(object_info.items()):
        module = str(info.get("python_module") or "")
        if not module.startswith("custom_nodes."):
            continue
        folder_name = module.split(".", 1)[1].split(".")[0]
        if folder_name not in packs:
            folder = custom_nodes / folder_name
            packs[folder_name] = _pack_info(folder) if folder.is_dir() else {
                "name": folder_name, "repo": KNOWN_REPOS.get(folder_name, ""), "registry_id": ""}
        classes[class_type] = folder_name

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"packs": packs, "classes": classes}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    missing = [p for p, i in packs.items() if not i["repo"]]
    print(f"{len(classes)} classes from {len(packs)} packs -> {OUT}")
    if missing:
        print("no repository for:", ", ".join(missing))


if __name__ == "__main__":
    main()
