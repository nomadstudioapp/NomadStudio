# What's new in Nomad Studio

English · [Español](UPDATES_ES.md) · [中文](UPDATES_ZH.md) · [한국어](UPDATES_KO.md)

Newest first. Downloads and checksums for each version are in [Releases](https://github.com/nomadstudioapp/NomadStudio/releases). The app offers each new version by itself ("Restart and update").

## 2026-10-27 · 1.1.4

- **Negative prompt in every Qwen 2.1 edit flow.** Edit Qwen 2.1 has it in **Advanced**, and every Photo Editing, Portrait Fix, Creator Pack, Background Tools, Extract and Styling flow on the Qwen 2.1 engine shows it too.
- **The negative prompts of the looks now apply with Qwen Image 2.1.** Photo Looks Starter, Film & Shadow and Open Air carry their own negative for each look, but on the Qwen engine it went to a node the 2.1 graph no longer has, so it never reached ComfyUI. It does now, and Outpaint's too. On Flux Klein it already worked.
- **Create: each card says which engine made it,** and **Apply params** switches to that engine before restoring the rest, so an image from a batch with several engines can be repeated.
- **Sessions keep each image's generation time** when a step is opened again.
- **Packs built on the core.** The Refine packs no longer carry their own copy of the Qwen 2.1 edit engine: they use the one in Core Refine, and take its fields (prompt, negative, steps…) from it. When Core Refine improves, they improve with it, with no new download. Installing one without Core Refine says so, and Core Refine cannot be uninstalled while other packs use it.
- **Packs:** Core Refine 0.1.10, Extract 0.1.15 and Photo Looks Starter 0.1.11 come with the app. The Ko-fi packs on the Qwen 2.1 edit engine have new versions (Photo Editing 0.2.2, Portrait Fix 0.2.2, Creator Pack 0.1.10, Background Tools 0.1.10, Styling 0.1.11, Film & Shadow 0.1.11, Open Air 0.1.11, and Studio Pro); they need this version of the app.

## 2026-10-19 · 1.1.3

- **Smart Selection: several objects at once.** Write them separated by commas (`crow, pig, girl`) and you get one mask and one cutout per object, plus a composite image with each object in its own colour and a legend to check them at a glance. Also through the MCP.
- **Smart Object Removal: several objects at once.** `crow, chef pig, girl` removes all of them, one after another, each with its own mask, and fills the gaps with the scene behind them. Add what they hold if it should go too (`girl, pumpkin lantern`).
- **Smart Object Removal now runs on Qwen Image 2.1** (it still loaded the older Qwen Edit 2511, a second 19 GB model), with the same Variation as Edit Qwen 2.1: Normal, or Turbo at about half the time.
- **Packs:** Extract 0.1.14 comes with the app, with Smart Object Removal on Qwen Image 2.1, and the Qwen Image 2.1 and Qwen Image 2.1 Turbo engines 0.1.1, with the right negative prompt.
- **Qwen Image 2.1 no longer avoids red foxes.** Its default negative prompt was, by mistake, the engine's example prompt ("a small red fox sitting in snow"), so foxes turned into something else. Installed engines are corrected on start.
- **Smart Object Removal on large images** (for example a 2x upscale) works: the fill is computed at about one megapixel and pasted back at full size.
- **Sessions keep every step.** A Smart Selection or Smart Object Removal with several objects (separated by commas) now appears in the Session as its own step, with the composite, the masks and the cutouts; before, the step disappeared.

## 2026-10-18 · 1.1.2

- **Smart Object Removal returns the cleaned image.** It could save the preview of its selection mask (a white shape on black) instead of the result. Any workflow with a preview node now gives back the saved image, in the app and through the MCP.
- **Smart Object Removal keeps the size of the original.** The result came back slightly resized, with transparent bands at the edges. Now it has exactly the original's size, and everything outside the selection keeps its original pixels.
- **Previously used inputs shows each image once.** The same reference picked several times appeared once per use. Picking it again now reuses the stored copy instead of saving another one.
- **MCP: every refine uses a new seed,** as the app does. Before, all edits made through the MCP repeated the workflow's fixed seed, and with it the same mistakes. To repeat an exact edit, pass `seed` (or end the instruction with `--seed 1234`); each answer says the seed it used.
- **Packs:** Extract 0.1.13 comes with the app, with the Smart Object Removal fix.

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
