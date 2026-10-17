# Nomad Studio 更新内容

[English](UPDATES.md) · [Español](UPDATES_ES.md) · 中文 · [한국어](UPDATES_KO.md)

最新的在最上面。每个版本的下载和校验和见 [Releases](https://github.com/nomadstudioapp/NomadStudio/releases)。应用会自动提示每个新版本（"重启并更新"）。

## 2026-10-17 · 1.1.1

- **Ko-fi 上更新的扩展包重新显示为官方。** 1.1.0 会把为 Qwen 2.1 Turbo 变体重新构建的扩展包标记为"非官方扩展包"。应用内目录现已收录它们的新指纹，并保留旧指纹，因此你之前下载的扩展包仍然是官方的。

## 2026-10-17 · 1.1.0

- **编辑也能用 Qwen Image 2.1 Turbo。** 编辑 Qwen 2.1、Multi-reference Compose 以及所有使用 Qwen 2.1 编辑引擎的流程都有 **Advanced › 变体：Normal / Turbo**。Turbo 只需 8 步，速度约快一倍（在 RTX 4060 Ti 上一次编辑从约 41 秒降到约 20 秒），质量相近。量化列表显示所选变体的精度，步数也随之改变。
- **编辑 Qwen 2.1 的输出宽高比。** 分辨率面板提供*原始*（默认）、从 9:16 到 21:9 的比例（以新形状保留源图的像素数——例如把 9:16 竖图重新构图为 16:9），以及可直接输入的**自定义分辨率**。
- **MCP：** refine 和 mix 支持 `variation`（`normal` / `turbo`）；编辑 Qwen 2.1 支持 `aspect_ratio` 或 `width`/`height`。
- **扩展包：** Core Refine 0.1.6、Extract 0.1.12 和 Presets Core 0.1.10 随应用提供。Ko-fi 上使用 Qwen 2.1 编辑引擎的扩展包有了带 Turbo 的新版本，需要这个版本的应用。

## 2026-10-15 · 1.0.1

- **导入 Session 的 .zip** 时会恢复其中的图片，从其他电脑分享来的 Session 可以完整打开。
- **导出 Session** 时会列出每一步所需的模型文件。

## 2026-10-13 · 1.0.0

- 首个公开版本：用 ComfyUI 和 LM Studio 100% 本地创建和修饰图像，无需账号，无需 API 密钥。设置向导会安装 ComfyUI 和 LM Studio（Windows 和 Linux），并下载第一个图像引擎。
