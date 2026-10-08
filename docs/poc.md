# PoC 실행과 검증 범위

## 입력과 회사 규칙

첫 범위는 PDF, 선택적 벽체 높이, 공통 회사 규칙이다. `company-rules.json`의 기본 2700 mm, 낮은 벽체 1200 mm는 의뢰인이 확정한 값이 아니다. DWG는 후속 범위로 남긴다.

`inspect`는 PDF 원본 렌더, 좌표가 있는 채움 면 후보, 글자, 전체 CAD 레이어 목록을 추출한다. 각 후보에 레이어 이름을 붙이거나 자동으로 벽체라고 확정하지 않는다. 직선 복합 면의 채움 규칙과 내부 구멍은 보존하며 곡선·자가 교차 채움은 제외 수량을 기록한다. 선 두 줄로 표시된 벽은 현재 후보에 없다.

`compile`은 결정 JSON을 검증하고 같은 높이의 채움 면을 병합한다. 높이 설정으로 3D extrusion에 필요한 윤곽과 높이를 만들고 `model.json`, `validation.json`, `selection.png`를 출력한다. 그 뒤 `export-native`가 로컬 C API 라이브러리를 호출해 실제 `.skp`를 생성한다.

## 독립 C API 저장 시험

SketchUp 내부 Ruby 실행 없이 native 라이브러리로 저장하고 재열기 검사한다. 실행 명령, 라이브러리 경로와 검증 결과는 [C SDK PoC](c-sdk-poc.md)에 기록했다. SDK 바이너리는 별도로 필요하다.

## 기존 Desktop Ruby 저장 시험

SketchUp Desktop의 빈 모델에서 Ruby Console을 열고 exporter를 로드한다. 다음은 저장소 위치의 실행 예다. 다른 PC에서는 파일을 복사한 실제 경로를 사용한다.

```ruby
load '/Users/minjae/Workspace/interior-os/skills/pdf-to-sketchup/scripts/externals/sketchup/export_walls.rb'
InteriorOS::WallExporter.export('/Users/minjae/Workspace/interior-os/output/demo-model/model.json', '/Users/minjae/Workspace/interior-os/output/demo-model/walls.skp')
```

스크립트는 선택한 면을 그룹으로 만들고 높이만큼 `pushpull`한다. 각 벽체가 솔리드이고 예상 부피와 0.1% 이내로 일치해야 새 `.skp`를 `save_copy`로 저장한다. 같은 경로에 파일이 있으면 중단한다. 원본이 있는 모델에서는 실행을 거절한다. 이후 `.skp`를 재열어 모델 치수와 편집 가능 여부를 확인한다.

공식 구현 근거: [Face.pushpull](https://ruby.sketchup.com/Sketchup/Face.html#pushpull-instance_method), [Model.save_copy](https://ruby.sketchup.com/Sketchup/Model.html#save_copy-instance_method). 별도 프로그램에서 `.skp`를 생성할 수 있는 [SketchUp C API](https://extensions.sketchup.com/developers/sketchup_c_api/sketchup/index.html)도 있으나 이 패키지에는 SDK가 포함되어 있지 않다.

## 설치와 배포

`skills/pdf-to-sketchup` 폴더는 SKILL.md, 고정 스크립트, 의존성, 규칙을 포함한 소스 패키지다. ZIP은 전달용이며 계정에 설치되었다는 뜻이 아니다. 회사 PDF 원본과 분석 결과는 전달용 Skill ZIP에 넣지 않는다.

ChatGPT 데스크톱 앱에서 사용하려면 [로컬 Plugin 설정 절차](chatgpt-setup.md)를 따른다. 저장소의 `plugin.json`과 등록 스크립트는 Skill과 고정 스크립트를 개인 목록에 추가한다. 실제 ChatGPT Pro 계정의 기능 제공 여부, 실행 도구, Python 의존성, `.skp` exporter 사용 가능 여부는 해당 계정에서 확인해야 한다. API hosted shell이나 Codex 로컬에서의 성공을 ChatGPT Pro의 성공으로 간주하지 않는다.

## 완료 기준

추출·고정 geometry 재현성 검증, 디자이너 간 벽체 선택 평가, native `.skp` 저장 및 재열기, 실제 ChatGPT Pro 실행 검증을 구분해 기록한다. 현재 모르는 항목을 완료로 표시하지 않는다.

## 합성 도면 시험

`examples/synthetic-plan.pdf`는 실제 의뢰 도면이 아닌 작은 시험 도면이다. 기본 벽체 두 삼각형과 낮은 벽체 사각형을 포함한다. 아래 결과로 native exporter부터 먼저 시험할 수 있다.

```sh
.venv/bin/python skills/pdf-to-sketchup/scripts/main.py inspect examples/synthetic-plan.pdf --out output/demo-evidence
.venv/bin/python skills/pdf-to-sketchup/scripts/main.py compile --evidence output/demo-evidence/evidence.json --decisions examples/synthetic-decisions.json --wall-height-mm 2700 --out output/demo-model
```
