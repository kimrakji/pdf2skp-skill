# pdf2skp-skill

An agent skill that turns PDF floor plans into editable SketchUp drafts.

PDF 평면도와 벽체 높이를 받아 디자이너가 이어서 편집할 수 있는 SketchUp 밑그림을 만듭니다. 에이전트가 도면의 벽체 후보를 선택하고, 공통 Python 스크립트가 축척·높이·형상 생성·저장을 처리합니다.

[Agent Skills](https://agentskills.io/specification) 형식의 `SKILL.md`와 실행 코드를 함께 제공합니다. 실행은 사용자의 컴퓨터에서 이루어지며, GitHub에는 스킬과 코드만 보관합니다.

## Output: 출력물

| 파일 | 용도 |
| --- | --- |
| `.skp` | 원본 평면도와 벽체 그룹이 포함된 편집 가능한 밑그림 |
| `selection.png` | 도면에서 선택한 벽체 영역을 확인하는 미리보기 |

최종 전달 폴더에는 위 두 파일만 넣습니다. 모델 입력, JSON 검증 보고서, 원본 참조 이미지는 내부 작업 폴더에 보관합니다. 적용 높이와 축척 가정, 보완할 항목은 전달 메시지에 짧게 설명합니다.

원본 평면도는 `Source_Plan`에, 추정 벽체는 `Walls_Suggested` 등 별도 그룹에 넣습니다. 벽체를 선택하기 어려운 도면은 원본 평면도만 포함한 `.skp`를 출력합니다. 해석이 애매한 부분은 추가 질문 대신 기본값을 적용합니다.

`.skp` 저장에 필요한 실행 환경이 없거나 저장이 실패하면, 생성된 `selection.png`와 실패 원인을 전달합니다. 생성하지 않은 `.skp`를 성공 결과로 안내하지 않습니다.

## Requirements: 실행 환경

- 로컬 파일을 읽고 명령을 실행할 수 있는 Agent Skills 지원 에이전트
- Python과 [Python 의존성](skills/pdf-to-sketchup/requirements.txt)
- 실제 `.skp` 저장을 위한 로컬 SketchUp C API 라이브러리

macOS arm64, Python 3.12, SketchUp C API 14.2에서 저장·재열기를 검증했습니다. SDK 바이너리는 이 저장소에 포함하지 않습니다. 다른 운영체제와 독립 SDK 설치 환경은 별도 검증이 필요합니다.

## Installation: 설치

Codex에서는 내장 `skill-installer`에 GitHub 링크를 전달해 설치합니다. 아래 요청을 새 대화에 입력합니다.

```text
$skill-installer
https://github.com/kimrakji/pdf2skp-skill/tree/main/skills/pdf-to-sketchup
이 스킬을 설치해줘.
```

[Codex의 스킬 설치 기능](https://learn.chatgpt.com/docs/build-skills)을 사용하므로 별도의 Node.js나 `npx` 설치는 필요하지 않습니다. 비공개 저장소는 해당 저장소에 접근할 수 있는 GitHub 인증이 필요합니다.

설치 후 스킬을 선택하고 실행 환경을 준비하도록 요청합니다.

```text
PDF to SketchUp 스킬의 Python 실행 환경을 준비하고,
이 컴퓨터의 SketchUp C API 라이브러리를 사용할 수 있는지 확인해줘.
```

Python 의존성은 처음 실행할 때 준비합니다. 실제 `.skp` 저장에는 로컬 SketchUp C API 라이브러리가 필요합니다. 다른 에이전트에서의 폴더 설치, 업데이트, Python 수동 설정은 [설치 가이드](docs/chatgpt-setup.md)를 참고하세요.

## Usage: 사용 방법

스킬을 선택하고 PDF를 첨부하거나 접근 가능한 로컬 파일 경로를 지정한 뒤 요청합니다.

```text
이 PDF의 벽체를 높이 2800mm로 처리해줘.
편집 가능한 SketchUp 밑그림과 벽체 선택 미리보기를 만들어줘.
```

에이전트가 원본 도면을 확인하고 벽체를 선택하면, 공통 스크립트가 모델을 생성하고 실제 `.skp`를 저장·재열기 검사합니다. 도면마다 새 변환 코드를 작성하지 않습니다.

PDF와 결과물은 로컬에 보관하고, 변환 작업은 `output/` 아래에서 진행합니다. 작업별로 `work/`에 중간 자료를, `final/`에 `.skp`와 `selection.png`를 보관합니다. `output/`은 Git 추적에서 제외되며 기존 결과 파일은 덮어쓰지 않습니다.

## Scope: 지원 범위

- 벡터 PDF의 직선 채움 면, 닫힌 선 윤곽, 수평·수직 평행 선의 겹침 구간을 벽체 후보로 사용합니다.
- 실제 치수를 축척 기준으로 우선 사용합니다. 치수가 없으면 도면의 인쇄 축척 또는 기본 **1:100**을 적용하고 가정을 기록합니다.
- 벽체 높이는 사용자 요청을 적용하며, 생략하면 기본 **2700mm**를 사용합니다.
- 스캔 도면·곡선·자동 생성하지 못한 문창 상세는 원본 평면도를 참조해 이어서 편집합니다.

결과물은 편집을 시작하기 위한 밑그림입니다. 벽체 의미 판별과 누락 여부는 미리보기에서 확인해야 합니다. C API의 형상·높이·재열기 검증과 SketchUp Desktop에서의 화면·편집 확인은 구분하며, Desktop 확인은 아직 검증하지 않았습니다.

## Development: 개발 및 검증

소스를 수정하거나 테스트하려는 경우에는 저장소를 복제합니다.

```sh
git clone https://github.com/kimrakji/pdf2skp-skill.git
cd pdf2skp-skill
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
```

Native 통합 검증에는 실제 SketchUp C API 라이브러리가 필요합니다. 라이브러리가 없으면 해당 검증은 건너뜁니다. CLI 명령과 라이브러리 지정 방법은 [C API 가이드](docs/c-sdk-poc.md), 벽체 선택 및 모델 입력 규칙은 [선택 계약](skills/pdf-to-sketchup/references/decision-contract.md)에 정리되어 있습니다.

## Documentation: 문서

- [스킬 지침](skills/pdf-to-sketchup/SKILL.md)
- [스킬 설치와 업데이트](docs/chatgpt-setup.md)
- [아키텍처](docs/architecture.md)
- [SketchUp C API 실행과 검증](docs/c-sdk-poc.md)
- [도면 선택 계약](skills/pdf-to-sketchup/references/decision-contract.md)
- [기본 모델링 규칙](skills/pdf-to-sketchup/references/company-rules.json)
- [품질 평가 기준](skills/pdf-to-sketchup/references/evaluation.md)
