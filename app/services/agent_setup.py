"""Settings › Agents: how to connect Claude Desktop, ChatGPT (Codex / Work
modes) and Bionic to this Nomad Studio's MCP server.

The server already knows everything a user would otherwise type by hand:
the Python it runs on (sys.executable — the portable build's app\\python,
or a dev venv), the folder it runs from (PYTHONPATH: app\\lib;app in the
portable build) and the port it answers on. So the setup shown is filled in
with this installation's real values, and each program's own config file is
read to tell whether it already points here, somewhere else (another folder
or port — e.g. an old checkout), or nowhere.

Phase 1 only reads other programs' files; it never writes them.
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

MCP_MODULE = "app.mcp.server"
DEFAULT_MCP_PORT = 5123  # app/mcp/config.py: NOMAD_BASE_URL without the env var
SERVER_NAMES = {"claude": "nomad-studio", "codex": "nomad_studio", "bionic": "Nomad Studio"}


def app_root() -> Path:
    """The folder holding the ``app`` package (portable: <NomadStudio>\\app)."""
    return Path(__file__).resolve().parents[2]


def launch(port: int) -> dict[str, Any]:
    root = app_root()
    paths = [str(root / "lib")] if (root / "lib").is_dir() else []
    paths.append(str(root))
    env = {"PYTHONPATH": os.pathsep.join(paths), "PYTHONUTF8": "1"}
    if port != DEFAULT_MCP_PORT:
        env["NOMAD_STUDIO_BASE_URL"] = f"http://127.0.0.1:{port}"
    return {"command": sys.executable, "args": ["-m", MCP_MODULE], "env": env}


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def config_paths() -> dict[str, Path]:
    home = _home()
    if sys.platform == "darwin":
        claude = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        claude = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / "Claude" / "claude_desktop_config.json"
    return {
        "claude": claude,
        "codex": home / ".codex" / "config.toml",
        "bionic": home / ".lmstudio" / "apps" / "bionic" / ".internal" / "ng-mcp.json",
    }


def _installed(client: str, path: Path) -> bool:
    if client == "bionic":
        return (_home() / ".lmstudio" / "apps" / "bionic").is_dir()
    return path.parent.is_dir()


def _entries(client: str, path: Path) -> list[dict[str, Any]]:
    """Every server in that program's config that launches Nomad Studio's MCP,
    as {name, command, args, env, cwd}."""
    try:
        if client == "codex":
            servers = (tomllib.loads(path.read_text(encoding="utf-8")).get("mcp_servers") or {})
            items = [(name, cfg) for name, cfg in servers.items() if isinstance(cfg, dict)]
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            if client == "claude":
                items = [(name, cfg) for name, cfg in (data.get("mcpServers") or {}).items() if isinstance(cfg, dict)]
            else:
                items = [(s.get("name") or "", s.get("connection") or {})
                         for s in (data.get("servers") or []) if isinstance(s, dict)]
    except (OSError, ValueError):
        return []
    found = []
    for name, cfg in items:
        args = [str(a) for a in (cfg.get("args") or [])]
        if MCP_MODULE in args:
            found.append({"name": name, "command": str(cfg.get("command") or ""), "args": args,
                          "env": {str(k): str(v) for k, v in (cfg.get("env") or {}).items()},
                          "cwd": str(cfg.get("cwd") or "")})
    return found


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path)) if path else ""


def _entry_port(entry: dict[str, Any]) -> int:
    url = entry["env"].get("NOMAD_STUDIO_BASE_URL", "")
    try:
        return int(url.rstrip("/").rsplit(":", 1)[1]) if url else DEFAULT_MCP_PORT
    except (IndexError, ValueError):
        return DEFAULT_MCP_PORT


def _entry_root(entry: dict[str, Any]) -> str:
    """The folder that entry runs Nomad Studio from: its cwd, else the last
    PYTHONPATH item (the app folder comes after lib)."""
    if entry["cwd"]:
        return entry["cwd"]
    parts = [p for p in entry["env"].get("PYTHONPATH", "").split(os.pathsep) if p]
    return parts[-1] if parts else ""


def status(client: str, port: int) -> dict[str, Any]:
    path = config_paths()[client]
    info: dict[str, Any] = {"configPath": str(path), "installed": _installed(client, path)}
    entries = _entries(client, path) if path.is_file() else []
    if not entries:
        info["state"] = "missing" if info["installed"] else "not_installed"
        return info
    here = launch(port)

    def mismatches(entry: dict[str, Any]) -> list[dict[str, Any]]:
        """What differs from this installation: its Python, its folder, its port."""
        out = []
        if _norm(entry["command"]) != _norm(here["command"]):
            out.append({"what": "python", "is": entry["command"], "shouldBe": here["command"]})
        if _norm(_entry_root(entry)) != _norm(str(app_root())):
            out.append({"what": "folder", "is": _entry_root(entry), "shouldBe": str(app_root())})
        if _entry_port(entry) != port:
            out.append({"what": "port", "is": _entry_port(entry), "shouldBe": port})
        return out

    checked = sorted(((mismatches(e), e) for e in entries), key=lambda pair: len(pair[0]))
    diff, entry = checked[0]
    info["name"] = entry["name"]
    if diff:
        info.update(state="other", mismatches=diff)
    else:
        info["state"] = "connected"
    return info


def _toml_str(value: str) -> str:
    return f"'{value}'" if "'" not in value and "\n" not in value else json.dumps(value)


def snippets(port: int) -> dict[str, str]:
    cfg = launch(port)
    claude = {"mcpServers": {SERVER_NAMES["claude"]: cfg}}
    bionic = {"name": SERVER_NAMES["bionic"], "enabled": True, "connection": {"type": "stdio", **cfg}}
    toml = [f"[mcp_servers.{SERVER_NAMES['codex']}]",
            f"command = {_toml_str(cfg['command'])}",
            'args = ["-m", "' + MCP_MODULE + '"]',
            "startup_timeout_sec = 60",
            "tool_timeout_sec = 600",
            "",
            f"[mcp_servers.{SERVER_NAMES['codex']}.env]"]
    toml += [f"{k} = {_toml_str(v)}" for k, v in cfg["env"].items()]
    return {
        "claude": json.dumps(claude, indent=2, ensure_ascii=False),
        "bionic": json.dumps(bionic, indent=2, ensure_ascii=False),
        "codex": "\n".join(toml),
    }


def setup_info(port: int) -> dict[str, Any]:
    return {
        "port": port,
        "launch": launch(port),
        "snippets": snippets(port),
        "clients": {client: status(client, port) for client in ("claude", "codex", "bionic")},
    }
