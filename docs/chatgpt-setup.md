# ChatGPT 데스크톱 앱 설정

macOS에서 로컬 Plugin으로 `PDF to SketchUp` Skill과 고정 스크립트를 설치하는 방법이다. 앱에 Work와 Plugins 메뉴가 보이는 환경에서 진행한다. Pro 구독만으로 해당 메뉴와 실행 환경이 제공된다고 확정하지 않는다.

## 1. 개인 목록에 등록

이 Mac의 터미널에서 실행한다. 현재 저장소에는 Python 가상환경과 의존성이 준비되어 있다.

```sh
cd /Users/minjae/Workspace/interior-os
.venv/bin/python scripts/install-chatgpt-plugin.py
```

명령은 다음 두 경로를 사용한다.

- `~/.codex/plugins/interior-os`: `plugin.json`과 `skills/` 복사본
- `~/.agents/plugins/marketplace.json`: 앱에 표시할 개인 플러그인 목록

기존 목록의 다른 항목과 마켓플레이스 이름을 보존한다. 목록을 변경하면 같은 폴더에 원본 백업을 남긴다. 설치 명령이 출력한 마켓플레이스 이름을 다음 단계에서 사용한다. 새 목록이면 `Interior OS Local`이다. 회사 PDF와 변환 결과는 복사하지 않는다.

다른 PC에서는 저장소를 복사한 위치에서 먼저 실행 환경을 준비한다.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r skills/pdf-to-sketchup/requirements.txt
.venv/bin/python scripts/install-chatgpt-plugin.py
```

## 2. 앱에서 설치

1. ChatGPT 데스크톱 앱을 완전히 종료하고 다시 연다.
2. **Plugins**를 열고, 위 명령이 출력한 로컬 마켓플레이스 이름을 선택한다.
3. **Interior OS** 상세 화면의 **+** 버튼으로 설치한다.
4. 새 **Work** 대화를 연다. 입력창에 `@`를 입력하고 **Interior OS** 또는 포함된 **PDF to SketchUp** Skill을 선택한다.

이는 [공식 OpenAI 로컬 Plugin 설치 방식](https://developers.openai.com/plugins/build/plugins)과 [앱에서 설치·호출하는 방식](https://learn.chatgpt.com/docs/plugins)을 따른다. 이 패키지에는 MCP 서버 설정이 없다.

## 3. 실행 환경부터 확인

Skill을 선택한 새 대화에서 아래 내용을 보낸다.

```text
PDF 변환을 위한 실행 환경을 확인해줘.
작업 폴더: /Users/minjae/Workspace/interior-os
Python: /Users/minjae/Workspace/interior-os/.venv/bin/python
이 Python으로 pdfplumber, pypdf, pypdfium2, shapely, jsonschema를 import하고,
설치된 Skill의 scripts/main.py --help를 실행해줘.
성공한 명령과 실제 실행 위치를 알려줘.
```

앱이 해당 Mac의 파일과 명령을 실행할 수 있어야 다음 단계로 진행할 수 있다. 클라우드 실행 위치에서는 위 Mac 경로가 보이지 않을 수 있다. Skill 설치만으로 로컬 Python 접근이나 SketchUp 실행 권한이 생기지는 않는다. 실행 환경을 확인하지 못하면 앱 버전, Work/Plugins 메뉴 유무, 실패한 명령을 확인한다.

## 4. PDF 변환 시험

실행 환경 확인 후 PDF를 첨부하거나 접근 가능한 로컬 PDF 경로를 지정하고, Skill을 선택해 다음처럼 요청한다.

```text
이 PDF의 벽체를 높이 2700mm로 처리해줘.
공통 규칙으로 추출하고, 벽체 선택 미리보기와 검증 결과를 보여줘.
```

AI가 Skill의 순서에 따라 후보를 선택하고 결정 JSON을 작성한다. 고정 Python 스크립트는 축척·병합·높이를 처리하고 `model.json`, `validation.json`, `selection.png`를 만든다. 실제 `.skp`는 [독립 C API exporter](c-sdk-poc.md)로 저장할 수 있다. 해당 로컬 실행 환경에서 native 라이브러리 로드와 저장이 가능해야 한다. 앱에서 `.skp`를 바로 내려받는 과정은 아직 검증하지 않았다.

## 업데이트와 현재 검증 범위

Skill을 수정하면 등록 명령을 다시 실행하고 앱을 재시작한다. 앱은 설치한 캐시 복사본을 사용하므로 새 대화에서 변경 사항을 확인한다. 필요하면 Plugins 상세 화면에서 업데이트하거나 다시 설치한다.

등록 스크립트는 임시 폴더에서 신규 등록, 기존 목록 보존, 재실행을 확인한다. 실제 사용자 홈에 등록하거나 ChatGPT 앱에서 설치·실행하는 과정은 별도 시험 대상이다. 기존 `pdf-to-sketchup-poc.zip`은 Skill 소스만 담은 전달 파일이며, 이 설치 명령은 저장소의 `plugin.json`과 `skills/`를 사용한다.
