# Nomad Studio 새 소식

[English](UPDATES.md) · [Español](UPDATES_ES.md) · [中文](UPDATES_ZH.md) · 한국어

최신 항목이 맨 위에 있습니다. 각 버전의 다운로드와 체크섬은 [Releases](https://github.com/nomadstudioapp/NomadStudio/releases)에 있습니다. 새 버전이 나오면 앱이 직접 알려 줍니다("다시 시작하고 업데이트").

## 2026-10-17 · 1.1.1

- **Ko-fi에서 업데이트된 팩이 다시 공식 팩으로 표시됩니다.** 1.1.0은 Qwen 2.1 Turbo 변형에 맞춰 다시 빌드한 팩을 "비공식 패키지"로 표시했습니다. 이제 앱 카탈로그가 새 지문을 알고 있고 이전 지문도 유지하므로, 전에 다운로드한 팩도 계속 공식 팩입니다.

## 2026-10-17 · 1.1.0

- **편집에도 Qwen Image 2.1 Turbo.** 편집 Qwen 2.1, Multi-reference Compose 및 Qwen 2.1 편집 엔진을 쓰는 모든 플로우에 **Advanced › 변형: Normal / Turbo**가 생겼습니다. Turbo는 8단계로 비슷한 품질에 약 2배 빠릅니다(RTX 4060 Ti에서 편집 한 번이 약 41초에서 약 20초로). 양자화 목록은 선택한 변형의 정밀도를 보여 주고, 단계 수도 그에 맞춰 바뀝니다.
- **편집 Qwen 2.1의 출력 비율.** 해상도 패널에서 *원본*(기본값), 원본의 픽셀 수를 유지한 채 새 형태로 바꾸는 9:16~21:9 비율(예: 9:16 세로 이미지를 16:9로 재구성), 직접 입력하는 **사용자 지정 해상도**를 고를 수 있습니다.
- **MCP:** refine과 mix가 `variation`(`normal` / `turbo`)을, 편집 Qwen 2.1이 `aspect_ratio` 또는 `width`/`height`를 지원합니다.
- **팩:** Core Refine 0.1.6, Extract 0.1.12, Presets Core 0.1.10이 앱에 포함됩니다. Qwen 2.1 편집 엔진을 쓰는 Ko-fi 팩에 Turbo를 넣은 새 버전이 나왔으며, 이 버전의 앱이 필요합니다.

## 2026-10-15 · 1.0.1

- **Session .zip을 가져올 때** 안에 든 이미지도 복원되므로, 다른 컴퓨터에서 공유된 Session이 온전하게 열립니다.
- **Session 내보내기**에 각 단계에 필요한 모델 파일이 표시됩니다.

## 2026-10-13 · 1.0.0

- 첫 공개 버전: ComfyUI와 LM Studio로 이미지를 100% 로컬에서 만들고 다듬습니다. 계정도 API 키도 필요 없습니다. 설정 마법사가 ComfyUI와 LM Studio를 설치하고(Windows, Linux) 첫 이미지 엔진을 내려받습니다.
