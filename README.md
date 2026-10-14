# Nomad Studio

![Nomad Studio: your image studio on your own computer](docs/images/nomad-studio-banner.jpg)

**[Download](https://nomadstudio.app/download)** · **[Video tutorials](https://nomadstudio.app/tutorials)** · **[Website](https://nomadstudio.app)** · **[Packs](https://ko-fi.com/nomadstudio/shop)** · **[Discord](https://discord.gg/FZGHRf6NXn)**

**A creative image studio on your own computer.** Create, refine and organize images with [ComfyUI](https://github.com/comfyanonymous/ComfyUI) as the image engine and [LM Studio](https://lmstudio.ai/) for writing prompts and describing images. Your images stay in your own folder. No credits, no cloud.

English · [Español](README_ES.md) · [中文](README_ZH.md) · [한국어](README_KO.md) — the app itself is available in English, Spanish, Chinese and Korean.

## Download

Portable builds for **Windows** and **Linux** are on the [download page](https://nomadstudio.app/download) and in [Releases](https://github.com/nomadstudioapp/NomadStudio/releases/latest), plus an experimental, unsigned one for **macOS** (Apple Silicon). Unzip and run: Python and every library come inside. The setup wizard installs ComfyUI for you, and LM Studio, which we recommend. Short video guides walk you through the first install, the next start and updates.

## What it is

- **Create, Refine, Mix, Session and Build.** Start from a few words, a photo or a template; edit in your own words; bring several pictures together; chain flows on a project; keep your characters, places and styles at hand.
- **An empty core that installs flows as packages.** Engines, flows, template packs and add-ons come as ZIP packages ([docs/PACKAGE_FORMAT.md](docs/PACKAGE_FORMAT.md)).
- **Profiles and Sessions.** Each profile has its own images, history and Sessions; a Vanish Session saves nothing.
- **Setup wizard.** First run checks ComfyUI and LM Studio, detects which engine files you already have, installs what is missing and recommends language models ([docs/SETUP_WIZARD.md](docs/SETUP_WIZARD.md)).
- **Backups and reset** from Settings.
- **Shared servers.** Several Nomad Studio installs can use the same ComfyUI and LM Studio on your network; they wait for each other instead of competing for the GPU.
- **MCP server** so AI agents can create and refine images — setup for Claude Desktop, ChatGPT and Bionic: [docs/MCP_SETUP.md](docs/MCP_SETUP.md).

## Requirements

- Windows or Linux; macOS (Apple Silicon) is experimental
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) running (locally or on another computer on your network) — the setup wizard can install it
- [LM Studio](https://lmstudio.ai/) — recommended, for prompt help, chat and image description
- A GPU with 8 GB of video memory or more is recommended; the examples were made on an RTX 4060 Ti with 16 GB
- Python 3.13 only if you run from source

## Run from source

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.lock   # Windows
.venv/Scripts/python app.py
# .venv/bin/pip install -r requirements.lock     # macOS / Linux
# .venv/bin/python app.py
```

Open http://localhost:5123 — the setup wizard starts on the first run. To pick another port, set `PORT` first: `PORT=5124 python app.py` on Linux and macOS, `$env:PORT=5124; python app.py` in Windows PowerShell.

Portable builds and in-app updates are described in [docs/APP_UPDATES.md](docs/APP_UPDATES.md).

## Community

Questions, bugs and ideas are welcome on Discord: #help to get unstuck, #feedback for what should come next, and #announcements for new versions.

[Discord](https://discord.gg/FZGHRf6NXn) · [X](https://x.com/NomadStudio_app) · [YouTube](https://www.youtube.com/@nomadstudioapp) · [Reddit](https://www.reddit.com/r/NomadStudio/) · [Ko-fi](https://ko-fi.com/nomadstudio)

## License

Nomad Studio is free software under the [GNU General Public License v3.0 or later](LICENSE). The images you generate are yours; packs and AI models have their own licenses. Details in [LICENSING.md](LICENSING.md).

If Nomad Studio is useful to you, a ⭐ on GitHub helps other people find it.
