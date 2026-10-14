# Nomad Studio

![Nomad Studio: 내 컴퓨터 속 이미지 스튜디오](docs/images/nomad-studio-banner.jpg)

**[다운로드](https://nomadstudio.app/download)** · **[영상 튜토리얼](https://nomadstudio.app/tutorials)** · **[웹사이트](https://nomadstudio.app)** · **[Packs](https://ko-fi.com/nomadstudio/shop)**

**내 컴퓨터에서 돌아가는 크리에이티브 이미지 스튜디오.** [ComfyUI](https://github.com/comfyanonymous/ComfyUI)를 이미지 엔진으로, [LM Studio](https://lmstudio.ai/)를 프롬프트 작성과 이미지 설명에 사용해 이미지를 만들고, 다듬고, 정리하세요. 이미지는 내 폴더에 그대로 남습니다. 크레딧도, 클라우드도 없습니다.

[English](README.md) · [Español](README_ES.md) · [中文](README_ZH.md) · 한국어 — 앱은 영어, 스페인어, 중국어, 한국어를 지원합니다.

## 다운로드

**Windows**와 **Linux**용 포터블 버전은 [다운로드 페이지](https://nomadstudio.app/download)와 [Releases](https://github.com/nomadstudioapp/NomadStudio/releases/latest)에 있습니다. **macOS**(Apple Silicon)용 실험 버전도 있습니다(서명되지 않음). 압축을 풀고 실행하면 끝입니다. Python과 모든 라이브러리가 들어 있습니다. 설정 마법사가 ComfyUI와, 저희가 추천하는 LM Studio를 설치해 줍니다. 짧은 영상 가이드가 첫 설치, 다음 실행, 업데이트 과정을 안내합니다.

## 소개

- **Create, Refine, Mix, Session, Build.** 몇 단어, 사진 한 장 또는 템플릿으로 시작하세요. 내 말로 수정하고, 여러 이미지를 하나로 합치고, 프로젝트에서 flow를 이어 붙이고, 캐릭터·장소·스타일을 늘 곁에 두세요.
- **비어 있는 코어에 flow를 패키지로 설치.** 엔진, flow, 템플릿 팩, 애드온은 ZIP 패키지로 제공됩니다([docs/PACKAGE_FORMAT.md](docs/PACKAGE_FORMAT.md)).
- **프로필과 Session.** 프로필마다 이미지, 기록, Session이 따로 있으며, Vanish Session은 아무것도 저장하지 않습니다.
- **설정 마법사.** 처음 실행할 때 ComfyUI와 LM Studio를 확인하고, 이미 가진 엔진 파일을 찾아내고, 없는 것을 설치하고, 언어 모델을 추천합니다([docs/SETUP_WIZARD.md](docs/SETUP_WIZARD.md)).
- **백업과 초기화**를 설정에서 할 수 있습니다.
- **공유 서버.** 여러 Nomad Studio가 네트워크의 같은 ComfyUI와 LM Studio를 함께 쓸 수 있으며, GPU를 두고 다투지 않고 서로 기다립니다.
- **MCP 서버**로 AI 에이전트가 이미지를 만들고 다듬을 수 있습니다 — Claude Desktop, ChatGPT, Bionic 연결 방법: [docs/MCP_SETUP_KO.md](docs/MCP_SETUP_KO.md).

## 요구 사항

- Windows 또는 Linux, macOS(Apple Silicon)는 실험 단계
- 실행 중인 [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (내 컴퓨터 또는 네트워크의 다른 컴퓨터) — 설정 마법사가 설치해 줄 수 있습니다
- [LM Studio](https://lmstudio.ai/) — 추천, 프롬프트 도움·채팅·이미지 설명용
- 비디오 메모리 8 GB 이상의 GPU를 권장합니다. 예시 이미지는 16 GB RTX 4060 Ti로 만들었습니다
- 소스에서 실행할 때만 Python 3.13 필요

## 소스에서 실행

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.lock   # Windows
# .venv/bin/pip install -r requirements.lock     # macOS / Linux
python app.py
```

http://localhost:5123 을 여세요 — 처음 실행하면 설정 마법사가 시작됩니다. 다른 포트를 쓰려면 `PORT=5124 python app.py`.

포터블 버전과 앱 내 업데이트는 [docs/APP_UPDATES.md](docs/APP_UPDATES.md)에 설명되어 있습니다.

## 라이선스

Nomad Studio는 [GNU General Public License v3.0 이상](LICENSE)의 자유 소프트웨어입니다. 생성한 이미지는 여러분의 것이며, 팩과 AI 모델에는 각각의 라이선스가 있습니다. 자세한 내용은 [LICENSING.md](LICENSING.md#한국어)를 참고하세요.

Nomad Studio가 유용했다면 GitHub에서 ⭐ 하나가 다른 사람들이 찾는 데 도움이 됩니다.
