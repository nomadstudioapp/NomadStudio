# Nomad Studio

**Local AI image studio.** Create, refine and organize images on your own computer with [ComfyUI](https://github.com/comfyanonymous/ComfyUI) as the image engine and [LM Studio](https://lmstudio.ai/) for writing prompts and describing images. Your images stay in your own folder. No credits, no cloud.

English · [Español](README_ES.md) — the app itself is available in English, Spanish, Chinese and Korean.

## What it is

- **An empty core that installs flows as packages.** Engines, flows, template packs and add-ons come as ZIP packages ([docs/PACKAGE_FORMAT.md](docs/PACKAGE_FORMAT.md)).
- **Profiles and Sessions.** Each profile has its own images, history and Sessions; a Vanish Session saves nothing.
- **Setup wizard.** First run checks ComfyUI and LM Studio, detects which engine files you already have, installs what is missing and recommends language models ([docs/SETUP_WIZARD.md](docs/SETUP_WIZARD.md)).
- **Backups and reset** from Settings.
- **Shared servers.** Several Nomad Studio installs can use the same ComfyUI and LM Studio on your network; they wait for each other instead of competing for the GPU.
- **MCP server** so AI agents can create and refine images — setup for Claude Desktop, ChatGPT and Bionic: [docs/MCP_SETUP.md](docs/MCP_SETUP.md).

## Requirements

- Windows, macOS or Linux
- Python 3.13
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) running (locally or on another computer on your network)
- [LM Studio](https://lmstudio.ai/) — optional, for prompt help and image description
- A GPU with 8 GB of video memory or more is recommended

## Run from source

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.lock   # Windows
# .venv/bin/pip install -r requirements.lock     # macOS / Linux
python app.py
```

Open http://localhost:5123 — the setup wizard starts on the first run. Use `PORT=5124 python app.py` to pick another port.

Portable builds and in-app updates are described in [docs/APP_UPDATES.md](docs/APP_UPDATES.md).

## License

To be defined before the public release. Until then, all rights reserved.
