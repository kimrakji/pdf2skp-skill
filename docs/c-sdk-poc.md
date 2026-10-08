# 독립 C API exporter PoC — 2026-10-08

`model.json → 독립 Python 프로세스 → SketchUp C API → .skp`를 구현했다. Python ctypes가 공개 C API ABI를 호출한다. C/C++ 실행 파일을 빌드한 것은 아니다. 생성 중 SketchUp Ruby API와 활성 모델을 사용하지 않는다.

## 실제 실행 조건

- macOS arm64, Python 3.12.14, SketchUp C API 14.2.
- 이번에는 설치된 SketchUp 앱의 `SketchUpAPI.framework`를 직접 로드했다. 바이너리를 복사하거나 패키지에 포함하지 않았다.
- 독립 SDK 다운로드 패키지나 SketchUp 미설치 환경은 아직 시험하지 않았다. 재배포·SDK 이용 조건도 확정하지 않았다.
- SketchUp 앱은 원래 실행 중이었으며 PoC 전후 PID가 같았다. 앱을 종료하거나 기존 모델을 변경하지 않고 독립 프로세스에서 생성·검증했다. 앱 종료 상태의 실행 시험은 별도다.
- Codex 샌드박스 안에서는 `SUModelSaveToFile`이 `SU_ERROR_SERIALIZATION`(7)을 반환했다. 같은 코드를 샌드박스 밖에서 실행하면 저장·재열기 검사가 통과했다. 실패한 작업은 최종 `.skp`나 성공 보고서를 남기지 않는다.

## 검증 결과

| 검사 | 결과 |
| --- | --- |
| 직사각형, 오목한 L자 단면, 내부 구멍, 낮은 벽체 | 4개 모두 실제 `.skp` 저장·C API 재열기 통과 |
| 같은 입력으로 생성 3회 | 의미상 형상·부피·높이 결과 일치 |
| 기본 높이 2700→3200 mm | XY·그룹 유지, 부피 비례 증가 |
| 낮은 벽체 1200 mm | 높이 유지 |
| 실제 방통대 도면의 부분 모델 | 18개 벽체 모두 저장·독립 프로세스 재열기 통과 |
| 기존 Ruby `.skp`와 C API 결과 비교 | 두 결과 모두 같은 입력 좌표·그룹·높이에 일치, 최대 상대 부피 차이 약 1.31e-15 |
| 기존 파일 덮어쓰기, review 상태, hash 불일치, 잘못된 단면·면적 | 거절 |
| 이동된 상위 그룹을 가진 `.skp` | 재열기 검증에서 거절 |
| SketchUp Desktop 화면·편집 확인 | 미검증. 파일 선택 과정에서 UI 도구의 ScreenCaptureKit 오류 -3812 발생 |

실제 도면은 이미 선택된 직선 채움 면의 **부분 모델**이다. 이번 검증으로 전체 도면의 벽체 의미 판별·누락 여부를 입증하지 않는다. 합성 입력의 내부 구멍은 단면을 관통하는 구멍이며 문·창문 높이 복원과 다르다. `.skp`는 GUID 등이 달라질 수 있으므로 파일 byte hash 일치 대신 재열기 후 형상을 비교한다.

## 재현 명령

`--library`에는 로컬 C API **바이너리 파일**을 지정한다. SDK를 별도로 확보하면 해당 framework/DLL 경로를 사용한다. 아래는 이번 Mac에서 검증한 경로다. 출력 폴더는 새 폴더를 사용한다.

```sh
mkdir -p output/native-example
.venv/bin/python skills/pdf-to-sketchup/scripts/main.py export-native --model examples/native-prisms.json --library '/Applications/SketchUp 2026/SketchUp.app/Contents/Frameworks/SketchUpAPI.framework/SketchUpAPI' --out output/native-example/walls.skp
.venv/bin/python skills/pdf-to-sketchup/scripts/main.py verify-native --model examples/native-prisms.json --library '/Applications/SketchUp 2026/SketchUp.app/Contents/Frameworks/SketchUpAPI.framework/SketchUpAPI' --skp output/native-example/walls.skp --out output/native-example/reopen.json
```

전체 PoC와 기존 Ruby 파일 비교를 재현하려면 새 출력 경로로 실행한다.

```sh
.venv/bin/python scripts/run-native-poc.py --library '/Applications/SketchUp 2026/SketchUp.app/Contents/Frameworks/SketchUpAPI.framework/SketchUpAPI' --out output/c-sdk-poc-new --reference-model output/knou-2700/partial-model/model.json --reference-skp output/knou-2700/knou-walls-2700-partial.skp
.venv/bin/python -m unittest discover -s tests -v
```

native 통합 검증은 실제 라이브러리를 사용한다. 다른 경로는 `INTERIOR_OS_TEST_SKETCHUP_API`로 지정한다. 라이브러리가 없으면 native 통합 검증만 skip되므로 성공으로 해석하지 않는다.

## 결과 파일

- [합성 모델](../output/c-sdk-poc-verified/synthetic-1.skp)
- [실제 도면의 18개 벽체](../output/c-sdk-poc-verified/knou-2700-c-api.skp)
- [PoC 요약](../output/c-sdk-poc-verified/poc-summary.json)
- [실제 모델 native 검증 보고서](../output/c-sdk-poc-verified/knou-2700-c-api.skp.validation.json)
- [별도 프로세스 재열기](../output/c-sdk-poc-verified/knou-2700-c-api.reopen.json)

저장 전과 저장 후에 모든 벽체의 솔리드·부피 오차 0.1% 이내, vertex/높이 오차 0.1 mm 이내, 위·아래 면의 구멍 수와 방향, 그룹·태그·원본 속성을 검사한다. 그룹 transform이 identity인지도 확인해 상위 그룹의 이동·회전·축척을 놓치지 않는다. SDK 14.2 규칙에 따라 그룹을 모델에 연결한 뒤 형상을 채운다.

공식 API 근거: [독립 C SDK](https://developer.trimble.com/docs/sketchup/tools/sdk/), [SUEntitiesFill](https://extensions.sketchup.com/developers/sketchup_c_api/sketchup/struct_s_u_entities_ref.html), [부피와 non-manifold 오류](https://extensions.sketchup.com/developers/sketchup_c_api/sketchup/struct_s_u_component_instance_ref.html).
