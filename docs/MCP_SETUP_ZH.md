# 在 Claude Desktop、ChatGPT 和 Bionic 中使用 Nomad Studio（MCP）

Nomad Studio 自带一个 **MCP**（Model Context Protocol）服务器。有了它，你的 AI 助手只需在聊天中提出请求，就能在你自己的电脑上生成和修改图片——使用你的模型、你的 ComfyUI，无需 API 密钥。

> English: [MCP_SETUP.md](MCP_SETUP.md) · Español: [MCP_SETUP_ES.md](MCP_SETUP_ES.md) · 한국어: [MCP_SETUP_KO.md](MCP_SETUP_KO.md)

## 开始之前

1. 用 `NomadStudio.bat` **打开 Nomad Studio** 并保持运行。助手是与正在运行的应用通信的：如果应用已关闭，它会回答无法连接。
2. **ComfyUI** 必须在运行，和在应用里生成图片时一样。
3. **找到你的 Nomad Studio 文件夹**：即包含 `NomadStudio.bat` 和 `app` 文件夹的那个。本指南称它为 `C:\NomadStudio`——复制时请全部替换成你自己的路径。

三个程序需要相同的设置：

| 设置 | 值 |
|---|---|
| 命令 | `C:\NomadStudio\app\python\python.exe` |
| 参数 | `-m` `app.mcp.server` |
| 变量 `PYTHONPATH` | `C:\NomadStudio\app\lib;C:\NomadStudio\app` |
| 变量 `PYTHONUTF8` | `1` |

如果你在 5123 以外的端口运行 Nomad Studio（`PORT` 变量），还要添加 `NOMAD_STUDIO_BASE_URL` = `http://127.0.0.1:<你的端口>`。

---

## Claude Desktop

1. 在 Claude Desktop 中：**Settings → Developer → Edit Config**，会打开 `claude_desktop_config.json`（位于 `%APPDATA%\Claude\`）。
2. 在 `mcpServers` 中添加 `nomad-studio`（如果文件是空的，就全部粘贴）。在这个文件里每个 `\` 都要写两次：

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

3. **完全退出 Claude**（包括时钟旁的托盘图标）再重新打开。在聊天中，工具图标里应能看到 `nomad_studio` 的工具。

## ChatGPT（桌面应用）

它可以在桌面应用的 **Codex** 和 **ChatGPT Work** 模式下使用，这两种模式会运行本地 MCP 服务器。普通的 ChatGPT 聊天只支持通过互联网访问的远程服务器，所以那里不会出现。

**方法 A——在应用中设置：**`Ctrl + ,` → **Integrations → Plugins → Add → Add MCP Server** → 类型选 **STDIO**，名称填 `nomad_studio`，并按上表填写命令、参数和变量。

**方法 B——编辑文件**（先关闭应用）：打开 `%USERPROFILE%\.codex\config.toml`，在末尾添加：

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

`tool_timeout_sec = 600` 允许每次生成最多 10 分钟：在最高质量或一次生成多张图片时，耗时会超过 ChatGPT 默认的等待时间。重新打开应用。ChatGPT 在生成或修改图片前会征求你的同意；查询类操作（模型、操作列表、最近一张图片）不需要。

## Bionic（LM Studio）

1. 在 Bionic 中打开 **MCP 服务器**设置并添加一个新服务器。
2. 名称 `Nomad Studio`，类型 **stdio**，并按上表填写命令、参数和变量。
3. 保存并重启 Bionic（或该服务器）。

如果你更想直接编辑文件（先关闭 Bionic），文件是 `%USERPROFILE%\.lmstudio\apps\bionic\.internal\ng-mcp.json`：

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

（这一项放在文件的 `servers` 列表中。）

**LM Studio 推荐模型：**支持工具调用（tool use）的模型。已测试：**Ornith 1.5 9B**（效果最好）、Qwythos 9B 和 Gemma QAT。

---

## 试一试

在聊天中输入：

```
我在 Nomad Studio 里有哪些模型？
```

然后：

```
用 Nomad Studio 生成：a weathered shop sign that says OPEN SOURCE, brick wall, golden hour --ar 16:9 --v monaco --q max
```

设置可以像 Midjourney 一样写在提示词末尾：`--ar 16:9`（比例）、`--no people`（不要出现的内容）、`--seed 42`、`--v <模型标识符>`（在 Settings › Images 中以及对“我有哪些模型”的回答中可以看到）、`--q fast|balanced|max`、`--r 2`（多张图片）。

图片保存在**代理的相册**中（每个程序一个文件夹：Claude、Codex、Bionic……），可在 Nomad Studio 的“谁在生成？”页面查看。

## 常见问题

| 现象 | 解决方法 |
|---|---|
| “无法连接 Nomad Studio” | 打开 Nomad Studio。如果使用其他端口，请添加 `NOMAD_STUDIO_BASE_URL`。 |
| 看不到工具 | 检查路径（`python.exe` 是否在那里），并完全重启该程序。 |
| 移动了 Nomad Studio 文件夹 | 在配置中更新路径并重启。 |
| 它询问比例、速度或模型 | 第一次是正常的；回答它，或写在提示词里（`--ar`、`--q`、`--v`）。 |
| 长时间生成被中断（ChatGPT） | 调大 `tool_timeout_sec`。 |
