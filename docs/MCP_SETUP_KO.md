# Claude Desktop, ChatGPT, Bionic에서 Nomad Studio 사용하기 (MCP)

Nomad Studio에는 **MCP**(Model Context Protocol) 서버가 포함되어 있습니다. 이를 사용하면 AI 어시스턴트에게 채팅으로 요청하기만 해도 내 PC에서 — 내 모델과 내 ComfyUI로, API 키 없이 — 이미지를 생성하고 수정할 수 있습니다.

> English: [MCP_SETUP.md](MCP_SETUP.md) · Español: [MCP_SETUP_ES.md](MCP_SETUP_ES.md) · 中文: [MCP_SETUP_ZH.md](MCP_SETUP_ZH.md)

## 시작하기 전에

1. `NomadStudio.bat`로 **Nomad Studio를 실행**하고 켜 둔 채로 두세요. 어시스턴트는 실행 중인 앱과 통신합니다. 앱이 꺼져 있으면 연결할 수 없다고 답합니다.
2. 앱에서 생성할 때와 마찬가지로 **ComfyUI**가 실행 중이어야 합니다.
3. **Nomad Studio 폴더를 확인하세요**: `NomadStudio.bat`과 `app` 폴더가 들어 있는 폴더입니다. 이 가이드에서는 `C:\NomadStudio`라고 부릅니다 — 복사할 때 모두 본인의 경로로 바꾸세요.

세 프로그램 모두 같은 값이 필요합니다:

| 항목 | 값 |
|---|---|
| 명령 | `C:\NomadStudio\app\python\python.exe` |
| 인수 | `-m` `app.mcp.server` |
| 변수 `PYTHONPATH` | `C:\NomadStudio\app\lib;C:\NomadStudio\app` |
| 변수 `PYTHONUTF8` | `1` |

Nomad Studio를 5123 이외의 포트(`PORT` 변수)로 실행한다면 `NOMAD_STUDIO_BASE_URL` = `http://127.0.0.1:<포트>`도 추가하세요.

---

## Claude Desktop

1. Claude Desktop에서 **Settings → Developer → Edit Config**. `claude_desktop_config.json`(`%APPDATA%\Claude\` 안)이 열립니다.
2. `mcpServers` 안에 `nomad-studio`를 추가하세요(파일이 비어 있으면 전체를 붙여 넣으세요). 이 파일에서는 `\`를 두 번씩 씁니다:

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

3. **Claude를 완전히 종료**(시계 옆 트레이 아이콘에서도)한 뒤 다시 여세요. 채팅의 도구 아이콘에 `nomad_studio` 도구가 보여야 합니다.

## ChatGPT (데스크톱 앱)

데스크톱 앱의 **Codex** 및 **ChatGPT Work** 모드에서 작동합니다. 이 모드들은 로컬 MCP 서버를 실행합니다. 일반 ChatGPT 채팅은 인터넷을 통한 원격 서버만 지원하므로 그곳에는 나타나지 않습니다.

**방법 A — 앱에서:** `Ctrl + ,` → **Integrations → Plugins → Add → Add MCP Server** → 유형 **STDIO**, 이름 `nomad_studio`, 그리고 위 표의 명령, 인수, 변수를 입력하세요.

**방법 B — 파일 편집**(앱을 닫은 상태에서): `%USERPROFILE%\.codex\config.toml`을 열고 끝에 추가하세요:

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

`tool_timeout_sec = 600`은 생성 한 번에 최대 10분을 허용합니다. 최고 품질이나 여러 장을 생성할 때는 ChatGPT의 기본 대기 시간보다 오래 걸립니다. 앱을 다시 여세요. ChatGPT는 생성이나 수정 전에 허락을 구합니다. 조회(모델, 작업 목록, 마지막 이미지)에는 필요 없습니다.

## Bionic (LM Studio)

1. Bionic에서 **MCP 서버** 설정을 열고 새 서버를 추가하세요.
2. 이름 `Nomad Studio`, 유형 **stdio**, 그리고 위 표의 명령, 인수, 변수를 입력하세요.
3. 저장하고 Bionic(또는 해당 서버)을 다시 시작하세요.

파일을 직접 편집하려면(Bionic을 닫은 상태에서) `%USERPROFILE%\.lmstudio\apps\bionic\.internal\ng-mcp.json`입니다:

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

(이 항목은 파일의 `servers` 목록 안에 들어갑니다.)

**LM Studio 추천 모델:** 도구 사용(tool use)을 지원하는 모델. 테스트 결과: **Ornith 1.5 9B**(가장 잘 작동), Qwythos 9B, Gemma QAT.

---

## 사용해 보기

채팅에 입력하세요:

```
Nomad Studio에 어떤 모델이 있어?
```

그다음:

```
Nomad Studio로 생성해 줘: a weathered shop sign that says OPEN SOURCE, brick wall, golden hour --ar 16:9 --v monaco --q max
```

설정은 Midjourney처럼 프롬프트 끝에 붙일 수 있습니다: `--ar 16:9`(비율), `--no people`(나오면 안 되는 것), `--seed 42`, `--v <모델 식별자>`(Settings › Images와 "어떤 모델이 있어?"에 대한 답에서 볼 수 있음), `--q fast|balanced|max`, `--r 2`(여러 장).

이미지는 **에이전트 앨범**(프로그램마다 폴더 하나: Claude, Codex, Bionic…)에 저장되며, Nomad Studio의 "누가 생성하나요?" 화면에서 볼 수 있습니다.

## 문제 해결

| 증상 | 해결 방법 |
|---|---|
| "Nomad Studio에 연결할 수 없습니다" | Nomad Studio를 실행하세요. 다른 포트를 쓴다면 `NOMAD_STUDIO_BASE_URL`을 추가하세요. |
| 도구가 보이지 않음 | 경로(`python.exe`가 그 위치에 있는지)를 확인하고 프로그램을 완전히 다시 시작하세요. |
| Nomad Studio 폴더를 옮김 | 설정의 경로를 바꾸고 다시 시작하세요. |
| 비율, 속도, 모델을 물어봄 | 처음에는 정상입니다. 답하거나 프롬프트에 넣으세요(`--ar`, `--q`, `--v`). |
| 긴 생성이 중간에 끊김(ChatGPT) | `tool_timeout_sec`을 늘리세요. |
