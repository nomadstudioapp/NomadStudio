"""Settings › Agents: how to connect Claude Desktop, ChatGPT (Codex / Work
modes), Antigravity and Bionic to this Nomad Studio's MCP server.

The server already knows everything a user would otherwise type by hand:
the Python it runs on (sys.executable — the portable build's app\\python,
or a dev venv), the folder it runs from (PYTHONPATH: app\\lib;app in the
portable build) and the port it answers on. So the setup shown is filled in
with this installation's real values, and each program's own config file is
read to tell whether it already points here, somewhere else (another folder
or port — e.g. an old checkout), or nowhere.

connect() writes this installation's entry into one program's file (Connect
/ Fix in Settings › Agents): a dated copy first (DATA_DIR/backups/agents),
then only Nomad Studio's own entry changes — an existing one keeps its name
and any extra settings, everything else in the file is checked to be
identical before anything is written.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tomllib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

MCP_MODULE = "app.mcp.server"
DEFAULT_MCP_PORT = 5123  # app/mcp/config.py: NOMAD_BASE_URL without the env var
SERVER_NAMES = {"claude": "nomad-studio", "codex": "nomad_studio", "bionic": "Nomad Studio",
                "antigravity": "nomad-studio"}
CLIENTS = ("claude", "codex", "antigravity", "bionic")
# Programs whose config is {"mcpServers": {name: {command, args, env}}}
_MCP_SERVERS_JSON = ("claude", "antigravity")


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
        "antigravity": _antigravity_config(home),
        "bionic": home / ".lmstudio" / "apps" / "bionic" / ".internal" / "ng-mcp.json",
    }


def _antigravity_config(home: Path) -> Path:
    """Antigravity (Google, Gemini) keeps its MCP servers in ~/.gemini/antigravity-ide/mcp_config.json;
    some versions use ~/.gemini/antigravity/. The one that already has a file wins."""
    candidates = [home / ".gemini" / "antigravity-ide" / "mcp_config.json",
                  home / ".gemini" / "antigravity" / "mcp_config.json"]
    return next((p for p in candidates if p.is_file()), next((p for p in candidates if p.parent.is_dir()), candidates[0]))


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
            if client in _MCP_SERVERS_JSON:
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
        "antigravity": json.dumps({"mcpServers": {SERVER_NAMES["antigravity"]: cfg}}, indent=2, ensure_ascii=False),
        "bionic": json.dumps(bionic, indent=2, ensure_ascii=False),
        "codex": "\n".join(toml),
    }


def setup_info(port: int) -> dict[str, Any]:
    return {
        "port": port,
        "launch": launch(port),
        "snippets": snippets(port),
        "clients": {client: status(client, port) for client in CLIENTS},
    }


# ── Connect / Fix: write this installation's entry ──────────────────────

# Variables this installation sets; any other one already in the entry
# (PYTHONIOENCODING…) is kept. The base URL goes when the port is the default.
_OUR_ENV = {"PYTHONPATH", "NOMAD_STUDIO_BASE_URL", "PYTHONUTF8"}


class ConnectError(RuntimeError):
    """The file can't be updated safely (unreadable, or the result would change more than our entry)."""


def _merged_env(old: dict[str, Any], port: int) -> dict[str, str]:
    env = {str(k): str(v) for k, v in (old or {}).items() if k not in _OUR_ENV}
    env.update(launch(port)["env"])
    return env


def _indent_of(raw: str) -> int:
    m = re.search(r"\n( +)\S", raw)
    return len(m.group(1)) if m else 2


def _write(path: Path, raw: str, text: str) -> None:
    newline = "\r\n" if "\r\n" in raw else "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline=newline) as fh:
        fh.write(text)


def _connect_json(client: str, path: Path, raw: str, port: int) -> str:
    data = json.loads(raw) if raw.strip() else {}
    if not isinstance(data, dict):
        raise ConnectError("the file is not a JSON object")
    here = launch(port)
    if client in _MCP_SERVERS_JSON:
        servers = data.setdefault("mcpServers", {})
        name = next((n for n, c in servers.items() if isinstance(c, dict) and MCP_MODULE in (c.get("args") or [])),
                    SERVER_NAMES[client])
        old = servers.get(name) if isinstance(servers.get(name), dict) else {}
        servers[name] = {**{k: v for k, v in old.items() if k not in ("command", "args", "env", "cwd")},
                         "command": here["command"], "args": here["args"], "env": _merged_env(old.get("env"), port)}
    else:  # bionic: {"servers": [{id, name, enabled, connection: {type, command, args, env}}]}
        servers = data.setdefault("servers", [])
        entry = next((s for s in servers if isinstance(s, dict)
                      and MCP_MODULE in ((s.get("connection") or {}).get("args") or [])), None)
        if entry is None:
            entry = {"id": str(uuid.uuid4()), "name": SERVER_NAMES["bionic"], "enabled": True, "connection": {}}
            servers.append(entry)
        old = entry.get("connection") or {}
        entry["enabled"] = True
        entry["connection"] = {**{k: v for k, v in old.items() if k not in ("command", "args", "env", "cwd")},
                               "type": "stdio", "command": here["command"], "args": here["args"],
                               "env": _merged_env(old.get("env"), port)}
    text = json.dumps(data, indent=_indent_of(raw), ensure_ascii=False) + "\n"
    before = json.loads(raw) if raw.strip() else {}
    after = json.loads(text)
    key = "mcpServers" if client in _MCP_SERVERS_JSON else "servers"
    if {k: v for k, v in before.items() if k != key} != {k: v for k, v in after.items() if k != key}:
        raise ConnectError("the rest of the file would change")
    return text


_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(key: str) -> str:
    return key if _BARE_KEY.match(key) else json.dumps(key)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return _toml_str(str(value))


def _toml_tables(prefix: str, table: dict[str, Any]) -> list[str]:
    lines = [f"[{prefix}]"]
    subtables = []
    for key, value in table.items():
        if isinstance(value, dict):
            subtables.append((key, value))
        else:
            lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
    for key, value in subtables:
        lines += [""] + _toml_tables(f"{prefix}.{_toml_key(key)}", value)
    return lines


def _connect_toml(path: Path, raw: str, port: int) -> str:
    doc = tomllib.loads(raw) if raw.strip() else {}
    servers = doc.get("mcp_servers") or {}
    name = next((n for n, c in servers.items() if isinstance(c, dict) and MCP_MODULE in (c.get("args") or [])),
                SERVER_NAMES["codex"])
    old = servers.get(name) if isinstance(servers.get(name), dict) else {}
    here = launch(port)
    entry: dict[str, Any] = {k: v for k, v in old.items()
                             if k not in ("command", "args", "cwd", "env", "startup_timeout_sec", "tool_timeout_sec")}
    entry = {"command": here["command"], "args": here["args"], "cwd": str(app_root()),
             "startup_timeout_sec": max(60, int(old.get("startup_timeout_sec") or 0)),
             "tool_timeout_sec": max(600, int(old.get("tool_timeout_sec") or 0)),
             **entry, "env": _merged_env(old.get("env"), port)}
    block = _toml_tables(f"mcp_servers.{_toml_key(name)}", entry)

    # Drop the old [mcp_servers.<name>] / [mcp_servers.<name>.*] tables (header
    # + body up to the next header) and put the new block where they were.
    names = "|".join(re.escape(form) for form in {name, json.dumps(name), f"'{name}'"})
    header = re.compile(r"^\s*\[\s*mcp_servers\s*\.\s*(?:" + names + r")\s*(?:\.[^\]]*)?\]\s*(?:#.*)?$")
    lines = raw.splitlines()
    kept: list[str] = []
    insert_at = None
    skipping = False
    for line in lines:
        if line.lstrip().startswith("["):
            skipping = bool(header.match(line))
            if skipping and insert_at is None:
                insert_at = len(kept)
        if not skipping:
            kept.append(line)
    if insert_at is None:
        while kept and not kept[-1].strip():
            kept.pop()
        insert_at = len(kept)
        block = ([""] if kept else []) + block
    else:
        block = block + [""]
    text = "\n".join(kept[:insert_at] + block + kept[insert_at:]).rstrip("\n") + "\n"

    after = tomllib.loads(text)
    before_rest = {k: v for k, v in doc.items() if k != "mcp_servers"}
    after_rest = {k: v for k, v in after.items() if k != "mcp_servers"}
    others_before = {k: v for k, v in servers.items() if k != name}
    others_after = {k: v for k, v in (after.get("mcp_servers") or {}).items() if k != name}
    if before_rest != after_rest or others_before != others_after or after["mcp_servers"][name] != entry:
        raise ConnectError("the rest of the file would change")
    return text


def connect(client: str, port: int, backups_dir: Path) -> dict[str, Any]:
    """Write this installation's MCP entry into ``client``'s config file,
    after a dated copy of it in ``backups_dir``."""
    if client not in SERVER_NAMES:
        raise ConnectError("unknown program")
    path = config_paths()[client]
    if not _installed(client, path):
        raise ConnectError("the program is not installed")
    current = status(client, port)
    if current["state"] == "connected":
        return {"client": client, "configPath": str(path), "backupPath": None, "unchanged": True, "status": current}
    try:
        raw = path.read_text(encoding="utf-8") if path.is_file() else ""
    except OSError as exc:
        raise ConnectError(f"can't read {path}: {exc}") from exc
    try:
        text = _connect_toml(path, raw, port) if client == "codex" else _connect_json(client, path, raw, port)
    except (ValueError, tomllib.TOMLDecodeError) as exc:
        raise ConnectError(f"can't read {path.name}: {exc}") from exc
    backup = None
    if path.is_file():
        backups_dir.mkdir(parents=True, exist_ok=True)
        backup = backups_dir / f"{client}-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}"
        shutil.copyfile(path, backup)
    _write(path, raw, text)
    return {"client": client, "configPath": str(path), "backupPath": str(backup) if backup else None,
            **{"status": status(client, port)}}
