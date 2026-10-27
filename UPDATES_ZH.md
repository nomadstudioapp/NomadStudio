# Nomad Studio 更新内容

[English](UPDATES.md) · [Español](UPDATES_ES.md) · 中文 · [한국어](UPDATES_KO.md)

最新的在最上面。每个版本的下载和校验和见 [Releases](https://github.com/nomadstudioapp/NomadStudio/releases)。应用会自动提示每个新版本（"重启并更新"）。

## 2026-10-27 · 1.1.4

- **所有 Qwen 2.1 编辑 flow 都有负面提示词。** Edit Qwen 2.1 在 **高级** 中提供，基于 Qwen 2.1 引擎的 Photo Editing、Portrait Fix、Creator Pack、Background Tools、Extract 和 Styling 的所有 flow 也会显示。
- **风格预设的负面提示词现在在 Qwen Image 2.1 上生效。** Photo Looks Starter、Film & Shadow 和 Open Air 的每个风格都带有自己的负面提示词，但在 Qwen 引擎上它被发送到 2.1 图中已不存在的节点，因此从未到达 ComfyUI。现在可以了，Outpaint 的也一样。在 Flux Klein 上本来就正常。
- **Create：每张卡片会显示生成它的引擎，** **应用参数** 会先切换到该引擎再恢复其余参数，便于重现多引擎批次中的某张图。
- **再次打开步骤时，Sessions 会保留每张图的生成时间。**
- **基于核心构建的扩展包。** Refine 扩展包不再自带一份 Qwen 2.1 编辑引擎：它们使用 Core Refine 中的引擎，并从中获取字段（提示词、负面提示词、步数……）。Core Refine 改进时，它们随之改进，无需重新下载。在没有 Core Refine 时安装会给出提示；有其他扩展包使用时，Core Refine 无法卸载。
- **扩展包：** Core Refine 0.1.10、Extract 0.1.15 和 Photo Looks Starter 0.1.11 随应用提供。基于 Qwen 2.1 编辑引擎的 Ko-fi 扩展包有新版本（Photo Editing 0.2.2、Portrait Fix 0.2.2、Creator Pack 0.1.10、Background Tools 0.1.10、Styling 0.1.11、Film & Shadow 0.1.11、Open Air 0.1.11 以及 Studio Pro），需要此版本的应用。

## 2026-10-19 · 1.1.3

- **智能选区：一次选择多个物体。** 用逗号分隔（`crow, pig, girl`），每个物体都会得到一张遮罩和一张抠图，另外还有一张合成图，每个物体用不同颜色标出并附有图例，方便一眼检查。也可通过 MCP 使用。
- **智能移除物体：一次移除多个。** `crow, chef pig, girl` 会逐个移除所有这些对象，每个都使用自己的遮罩，并用其后方的场景填补空缺。如果手中拿着的东西也要去掉，请一并写上（`girl, pumpkin lantern`）。
- **智能移除物体现在使用 Qwen Image 2.1**（之前仍加载旧的 Qwen Edit 2511，即第二个 19 GB 的模型），并提供与 Edit Qwen 2.1 相同的变体：Normal，或用时约减半的 Turbo。
- **扩展包：** 应用附带 Extract 0.1.14（智能移除物体基于 Qwen Image 2.1），以及负面提示词已修正的 Qwen Image 2.1 和 Qwen Image 2.1 Turbo 引擎 0.1.1。
- **Qwen Image 2.1 不再回避红狐狸。** 它的默认负面提示词误用了引擎的示例提示词（"a small red fox sitting in snow"），导致狐狸被画成别的东西。已安装的引擎会在启动时自动修正。
- **智能移除物体现在可用于大图**（例如 2 倍放大后的图像）：填充在约 100 万像素下计算，再以原尺寸贴回。
- **Session 会保留每一个步骤。** 使用多个对象（逗号分隔）的智能选区或智能移除物体，现在会作为独立步骤出现在 Session 中，包含合成图、遮罩和抠图；此前该步骤会消失。

## 2026-10-18 · 1.1.2

- **智能移除物体返回清理后的图像。** 之前它可能保存选区遮罩的预览（黑底白色剪影），而不是结果。现在任何带有预览节点的工作流都会返回已保存的图像，在应用内和通过 MCP 均如此。
- **智能移除物体保持原图尺寸。** 结果之前会被轻微缩放，边缘出现透明条带。现在尺寸与原图完全一致，选区以外的部分保留原始像素。
- **“之前用过的输入”中每张图像只显示一次。** 同一张参考图选择多次时，之前每次使用都会出现一次。现在再次选择时会复用已保存的副本，而不是再保存一份。
- **MCP：每次精修都使用新的种子，** 与应用中一致。之前通过 MCP 进行的所有编辑都重复使用工作流中的固定种子，也就会重复同样的错误。如需完全重现某次编辑，请传入 `seed`（或在指令末尾加上 `--seed 1234`）；每次回复都会给出所用的种子。
- **扩展包：** Extract 0.1.13 随应用附带，包含智能移除物体的修复。

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
