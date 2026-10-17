# What's new in Nomad Studio

English · [Español](UPDATES_ES.md) · [中文](UPDATES_ZH.md) · [한국어](UPDATES_KO.md)

Newest first. Downloads and checksums for each version are in [Releases](https://github.com/nomadstudioapp/NomadStudio/releases). The app offers each new version by itself ("Restart and update").

## 2026-10-17 · 1.1.1

- **Updated Ko-fi packs show as official again.** The packs rebuilt for the Qwen 2.1 Turbo variation were reported as "unofficial package" by 1.1.0. The in-app catalogue knows their new fingerprints and keeps the earlier ones, so packs downloaded before stay official too.

## 2026-10-17 · 1.1.0

- **Qwen Image 2.1 Turbo for editing.** Edit Qwen 2.1, Multi-reference Compose and every flow on the Qwen 2.1 edit engine have **Advanced › Variation: Normal / Turbo**. Turbo runs at 8 steps, about twice as fast (an edit from ~41 s to ~20 s on an RTX 4060 Ti) with similar quality. Quantization lists the precisions of the chosen variation, and Steps follows it.
- **Output aspect ratio in Edit Qwen 2.1.** The Resolution panel offers *Original* (the default), ratios from 9:16 to 21:9 that keep the source's pixel count in the new shape — for example a 9:16 portrait recomposed as 16:9 — and a typeable **Custom resolution**.
- **MCP:** refine and mix accept `variation` (`normal` / `turbo`); Edit Qwen 2.1 accepts `aspect_ratio` or `width`/`height`.
- **Packs:** Core Refine 0.1.6, Extract 0.1.12 and Presets Core 0.1.10 come with the app. The Ko-fi packs on the Qwen 2.1 edit engine have new versions with Turbo; they need this version of the app.

## 2026-10-15 · 1.0.1

- **Session import from .zip** restores the images inside the zip, so a Session shared from another computer opens complete.
- **Session export** lists the model files each step needs.

## 2026-10-13 · 1.0.0

- First public release: create and refine images 100% locally with ComfyUI and LM Studio — no account, no API keys. The setup wizard installs ComfyUI and LM Studio (Windows and Linux) and downloads a first image engine.
