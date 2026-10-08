# Interior OS

PDF 평면도와 벽체 높이로 편집 가능한 SketchUp **밑그림**을 만드는 Skill과 공통 스크립트다. 추가 질문 없이 도면에서 판단해 출력한다. 해석이 애매한 벽체는 별도 그룹으로 만들고, 원본 평면도를 모델 아래에 넣어 바로 보완할 수 있게 한다.

- 직선 채움 면, 닫힌 선 윤곽, 수평·수직 평행 선의 겹침 구간을 벽체 후보로 제공한다.
- AI가 원본을 보며 후보 ID를 선택하고 축척·병합·높이·저장은 고정 스크립트가 처리한다. 도면마다 코드를 만들지 않는다.
- 벽체를 선택하지 못해도 `Source_Plan` 이미지가 포함된 `.skp`를 출력한다. 스캔·곡선·문창 상세는 참조에서 이어서 작업한다.
- 축척은 실제 치수를 우선하고 없으면 도면 인쇄 축척 또는 기본 1:100을 사용한다. 가정은 결과에 남긴다.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r skills/pdf-to-sketchup/requirements.txt
.venv/bin/python skills/pdf-to-sketchup/scripts/main.py inspect drawing.pdf --outlines --out output/evidence
# Skill이 evidence의 원본 후보 ID와 축척 근거로 decisions.json을 작성
.venv/bin/python skills/pdf-to-sketchup/scripts/main.py compile --evidence output/evidence/evidence.json --decisions decisions.json --wall-height-mm 2800 --out output/model
.venv/bin/python skills/pdf-to-sketchup/scripts/main.py export-native --model output/model/model.json --library '/Applications/SketchUp 2026/SketchUp.app/Contents/Frameworks/SketchUpAPI.framework/SketchUpAPI' --out output/model/walls-draft.skp
.venv/bin/python skills/pdf-to-sketchup/scripts/main.py verify-native --model output/model/model.json --library '/Applications/SketchUp 2026/SketchUp.app/Contents/Frameworks/SketchUpAPI.framework/SketchUpAPI' --skp output/model/walls-draft.skp --out output/model/reopen.json
```

밑그림이 기본 모드이며 `compile --strict`는 기존 검증용이다. `.skp` 저장에는 로컬 SketchUp C API 라이브러리가 필요하다. macOS / API 14.2에서 실제 저장·재열기를 검증하며 SDK 바이너리는 배포하지 않는다. 이 Mac의 샌드박스 안에서는 저장이 거부되므로 native 검증은 권한이 있는 로컬 프로세스에서 실행한다. 기존 파일을 덮어쓰지 않는다.

- [Skill](skills/pdf-to-sketchup/SKILL.md)
- [선택 계약](skills/pdf-to-sketchup/references/decision-contract.md)
- [아키텍처](docs/architecture.md)
- [앱 설치와 업데이트](docs/chatgpt-setup.md)
- [기존 C API PoC](docs/c-sdk-poc.md)

```sh
.venv/bin/python -m unittest discover -s tests -v
```
