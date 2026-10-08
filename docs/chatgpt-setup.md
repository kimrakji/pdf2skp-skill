# Skill Installation: 스킬 설치와 업데이트

GitHub의 `kimrakji/pdf2skp-skill`에서 Agent Skill을 설치합니다. Codex의 내장 설치기 또는 스킬 폴더 복사를 사용하며 별도의 Node.js·npm·npx 설치는 필요하지 않습니다. 변환은 사용자의 컴퓨터에서 실행합니다.

## Codex: 내장 설치기로 설치

Codex의 새 대화에서 다음 요청을 보냅니다.

```text
$skill-installer
https://github.com/kimrakji/pdf2skp-skill/tree/main/skills/pdf-to-sketchup
이 스킬을 사용자 스킬로 설치해줘.
```

[Codex의 스킬 설치 기능](https://learn.chatgpt.com/docs/build-skills)이 스킬 폴더를 받아 등록합니다. 비공개 저장소는 접근 권한과 GitHub 인증이 준비되어 있어야 합니다. 설치 후 새 대화에서 **PDF to SketchUp** 스킬을 선택합니다. 표시되지 않으면 앱을 다시 시작합니다.

GitHub에 게시된 내용이 설치되므로, 로컬 수정 사항은 저장소에 올린 후 배포합니다. 기존 **Interior OS** 플러그인과 단독 스킬이 함께 설치되어 있다면 사용할 항목을 명시해 중복 호출을 피합니다.

## Manual: 폴더를 복사해 설치

내장 설치기가 없는 에이전트에서는 GitHub 저장소의 **Code → Download ZIP**으로 소스를 받습니다. 압축을 풀고 `skills/pdf-to-sketchup/` 폴더 전체를 에이전트의 사용자 스킬 위치에 복사합니다.

| 에이전트 | 사용자 스킬 폴더 |
| --- | --- |
| Codex | `~/.agents/skills/pdf-to-sketchup/` |
| Claude Code | `~/.claude/skills/pdf-to-sketchup/` |

설치된 폴더 바로 아래에 `SKILL.md`, `scripts/`, `references/`, `requirements.txt`가 있어야 합니다. `SKILL.md`만 복사하면 변환 코드와 참고 자료가 빠집니다. 다른 에이전트는 해당 제품의 스킬 설치 위치를 따릅니다.

폴더 위치는 [Codex 문서](https://learn.chatgpt.com/docs/build-skills)와 [Claude의 스킬 문서](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)를 참고하세요.

## Runtime: 실행 환경 준비

스킬을 선택하고 다음처럼 요청합니다.

```text
PDF to SketchUp 스킬의 Python 실행 환경을 준비하고,
이 컴퓨터의 SketchUp C API 라이브러리를 사용할 수 있는지 확인해줘.
```

스킬은 사용자가 지정한 Python을 우선 사용하고, 지정이 없으면 `~/.local/share/pdf2skp-skill/.venv`에 실행 환경을 준비합니다. 가상환경은 스킬 설치 폴더 밖에 두어 스킬을 업데이트해도 유지합니다. Python을 실행할 수 있는 환경과 로컬 SketchUp C API 라이브러리는 필요합니다.

위 수동 설치 위치에 Codex 스킬을 복사한 경우, Python 환경을 직접 준비하려면 다음 명령을 실행합니다.

```sh
python3 -m venv "$HOME/.local/share/pdf2skp-skill/.venv"
"$HOME/.local/share/pdf2skp-skill/.venv/bin/python" -m pip install -r "$HOME/.agents/skills/pdf-to-sketchup/requirements.txt"
"$HOME/.local/share/pdf2skp-skill/.venv/bin/python" -c "import pdfplumber, pypdf, pypdfium2, shapely, jsonschema"
```

다른 설치 위치에서는 `requirements.txt` 경로를 실제 스킬 위치로 바꿉니다. 스킬 설치만으로 Python 의존성과 SketchUp SDK가 설치되지는 않습니다.

실제 `.skp` 저장에는 로컬 C API 바이너리 경로가 필요합니다. macOS에서 검증한 경로는 다음과 같습니다.

```text
/Applications/SketchUp 2026/SketchUp.app/Contents/Frameworks/SketchUpAPI.framework/SketchUpAPI
```

설치된 SketchUp 버전에 따라 경로가 달라집니다. SDK 바이너리는 이 저장소에서 배포하지 않습니다. 바이너리 로드와 파일 저장이 가능한지는 [C API 가이드](c-sdk-poc.md)의 명령으로 확인합니다.

## Usage: 변환 요청

스킬을 선택하고 PDF를 첨부하거나 접근 가능한 로컬 경로를 지정합니다.

```text
이 PDF의 벽체를 높이 2800mm로 처리해줘.
편집 가능한 SketchUp 밑그림과 벽체 선택 미리보기를 만들어줘.
```

최종 전달 폴더에는 `.skp`와 `selection.png`만 넣습니다. 모델 입력, JSON 검증 보고서, 원본 참조 이미지는 내부 작업 폴더에 보관합니다. 파일·명령 실행 권한과 실제 native 저장이 가능한지는 해당 에이전트의 실행 환경에서 확인합니다.

## Update: 업데이트

Codex에서는 설치된 스킬의 위치와 GitHub 링크를 함께 전달해 업데이트를 요청합니다.

```text
설치된 PDF to SketchUp 스킬을 아래 GitHub의 최신 내용으로 업데이트해줘.
https://github.com/kimrakji/pdf2skp-skill/tree/main/skills/pdf-to-sketchup
기존 스킬 위치에 반영하고 Python 실행 환경은 유지해줘.
```

내장 설치기는 기존 폴더가 있으면 자동으로 덮어쓰지 않습니다. 업데이트 작업은 에이전트가 기존 설치 위치를 확인하고 새 소스를 받아 반영하도록 요청합니다. 수동 설치에서는 최신 ZIP에서 같은 스킬 폴더를 받아 기존 위치에 반영합니다.

업데이트 후 새 대화에서 사용합니다. Python 의존성이 바뀌었다면 실행 환경 준비를 다시 요청하거나 설치된 스킬의 `requirements.txt`로 `pip install -r`을 다시 실행합니다.

## Local Plugin: 기존 로컬 플러그인 방식

앱의 Plugins 목록에서 **Interior OS** 플러그인을 사용하는 경우에는 기존 등록 스크립트를 유지합니다. 소스를 받은 폴더에서 실행합니다.

```sh
python3 scripts/install-chatgpt-plugin.py
```

이 명령은 `plugin.json`과 `skills/`를 `~/.codex/plugins/interior-os`에 복사하고 `~/.agents/plugins/marketplace.json`에 등록합니다. 앱을 재시작한 뒤 해당 로컬 목록에서 플러그인을 설치·업데이트하고 새 대화에서 사용합니다. Python 실행 환경은 위와 같이 별도로 준비합니다.

이 방식은 [OpenAI 로컬 플러그인 설치](https://developers.openai.com/plugins/build/plugins)를 따릅니다. 단독 스킬 설치에는 이 등록 스크립트가 필요하지 않습니다.
