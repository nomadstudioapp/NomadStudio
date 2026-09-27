# Using Nomad Studio from Claude Desktop, ChatGPT and Bionic (MCP)

Nomad Studio includes an **MCP** (Model Context Protocol) server. With it, your AI assistant can generate and edit images on your own PC — with your models, your ComfyUI and no API keys — just by asking in the chat.

> Español: [MCP_SETUP_ES.md](MCP_SETUP_ES.md) · 中文: [MCP_SETUP_ZH.md](MCP_SETUP_ZH.md) · 한국어: [MCP_SETUP_KO.md](MCP_SETUP_KO.md)

## Before you start

1. **Open Nomad Studio** with `NomadStudio.bat` and leave it open. The assistant talks to the running app: if it's closed, it will answer that it can't connect.
2. **ComfyUI** has to be running, just as for generating from the app.
3. **Find your Nomad Studio folder**: the one containing `NomadStudio.bat` and the `app` folder. This guide calls it `C:\NomadStudio` — replace it with yours everywhere you copy.

All three programs need the same values:

| Setting | Value |
|---|---|
| Command | `C:\NomadStudio\app\python\python.exe` |
| Arguments | `-m` `app.mcp.server` |
| Variable `PYTHONPATH` | `C:\NomadStudio\app\lib;C:\NomadStudio\app` |
| Variable `PYTHONUTF8` | `1` |

If you run Nomad Studio on a port other than 5123 (`PORT` variable), also add `NOMAD_STUDIO_BASE_URL` = `http://127.0.0.1:<your port>`.

---

## Claude Desktop

1. In Claude Desktop: **Settings → Developer → Edit Config**. This opens `claude_desktop_config.json` (in `%APPDATA%\Claude\`).
2. Add `nomad-studio` inside `mcpServers` (if the file is empty, paste all of it). In this file every `\` is written twice:

```json
{
  "mcpServers": {
    "nomad-studio": {
      "command": "C:\\NomadStudio\\app\\python\\python.exe",
      "args": ["-m", "app.mcp.server"],
      "env": {
        "PYTHONPATH": "C:\\NomadStudio\\app\\lib;C:\\NomadStudio\\app",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

3. **Quit Claude completely** (also from the icon next to the clock) and open it again. In the chat, the tools icon should list the `nomad_studio` ones.

## ChatGPT (desktop app)

It works in the desktop app's **Codex** and **ChatGPT Work** modes, which run local MCP servers. Regular ChatGPT chat only accepts remote servers over the internet, so it doesn't show up there.

**Option A — from the app:** `Ctrl + ,` → **Integrations → Plugins → Add → Add MCP Server** → type **STDIO**, name `nomad_studio`, and fill in command, arguments and variables from the table above.

**Option B — editing the file** (with the app closed): open `%USERPROFILE%\.codex\config.toml` and add at the end:

```toml
[mcp_servers.nomad_studio]
command = 'C:\NomadStudio\app\python\python.exe'
args = ["-m", "app.mcp.server"]
startup_timeout_sec = 60
tool_timeout_sec = 600

[mcp_servers.nomad_studio.env]
PYTHONPATH = 'C:\NomadStudio\app\lib;C:\NomadStudio\app'
PYTHONUTF8 = "1"
```

`tool_timeout_sec = 600` allows up to 10 minutes per generation: at maximum quality or with several images it takes longer than ChatGPT waits by default. Reopen the app. ChatGPT will ask before generating or editing; lookups (models, actions, last image) don't need it.

## Bionic (LM Studio)

1. In Bionic, open the **MCP servers** settings and add a new one.
2. Name `Nomad Studio`, type **stdio**, and command, arguments and variables from the table above.
3. Save and restart Bionic (or the server).

If you prefer editing the file (with Bionic closed), it's `%USERPROFILE%\.lmstudio\apps\bionic\.internal\ng-mcp.json`:

```json
{
  "name": "Nomad Studio",
  "enabled": true,
  "connection": {
    "type": "stdio",
    "command": "C:\\NomadStudio\\app\\python\\python.exe",
    "args": ["-m", "app.mcp.server"],
    "env": {
      "PYTHONPATH": "C:\\NomadStudio\\app\\lib;C:\\NomadStudio\\app",
      "PYTHONUTF8": "1"
    }
  }
}
```

(That entry goes inside the file's `servers` list.)

**Recommended model in LM Studio:** one with tool use. Tested: **Ornith 1.5 9B** (the best at it), Qwythos 9B and Gemma QAT.

---

## Try it

Type in the chat:

```
Which models do I have in Nomad Studio?
```

and then:

```
Generate with Nomad Studio: a weathered shop sign that says OPEN SOURCE, brick wall, golden hour --ar 16:9 --v monaco --q max
```

Settings can go at the end of the prompt, as in Midjourney: `--ar 16:9` (format), `--no people` (what must not appear), `--seed 42`, `--v <model identifier>` (shown in Settings › Images and in the answer to "which models do I have?"), `--q fast|balanced|max`, `--r 2` (several images).

Images go to the **agent's album** (one folder per program: Claude, Codex, Bionic…), shown on Nomad Studio's "Who's generating?" screen.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Could not connect to Nomad Studio" | Open Nomad Studio. On another port, add `NOMAD_STUDIO_BASE_URL`. |
| The tools don't show up | Check the paths (that `python.exe` is there) and fully restart the program. |
| You moved the Nomad Studio folder | Update the paths in the configuration and restart. |
| It asks for format, speed or model | Normal the first time; answer it, or put them in the prompt (`--ar`, `--q`, `--v`). |
| Long generations get cut off (ChatGPT) | Raise `tool_timeout_sec`. |
