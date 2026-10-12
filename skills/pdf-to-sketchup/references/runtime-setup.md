# 실행 환경 자동 준비

디자이너는 스킬 설치 후 PDF와 벽체 높이를 전달한다. 에이전트가 첫 실행에서 준비 스크립트를 실행하며 Python 설치나 가상환경 설정을 사용자에게 맡기지 않는다. 준비만 요청한 경우에도 같은 스크립트를 실행한다.

## 에이전트 실행

`SKILL_DIR`은 현재 설치된 스킬의 실제 경로로 바꾼다. 저장소 복제나 개발용 `.venv`는 필요하지 않다.

macOS:

```sh
sh "SKILL_DIR/scripts/setup.sh"
```

Windows PowerShell:

```powershell
& 'SKILL_DIR\scripts\setup.ps1'
```

최초 다운로드에는 인터넷과 사용자 폴더 쓰기 권한이 필요하다. 실행 권한이나 회사 보안 정책이 차단하면 우회하지 않고 차단된 단계와 필요한 조치를 보고한다. Windows 스크립트와 DLL 검색은 구현되어 있지만 Windows 실제 설치·저장 검증은 아직 수행하지 않았다. macOS의 실제 성공과 구분한다.

## 내부 처리

1. 준비된 uv가 없으면 [공식 설치기](https://docs.astral.sh/uv/reference/installer/)로 사용자 폴더에 설치한다. 셸 프로필·시스템 PATH를 바꾸지 않는다. Homebrew·Node.js·컴파일러는 사용하지 않는다.
2. 실행 환경이 없으면 uv로 Python 3.12 가상환경을 만든다. [uv는 Python이 없어도 필요한 인터프리터를 다운로드한다](https://docs.astral.sh/uv/guides/install-python/).
3. 설치된 스킬의 `requirements.txt`를 적용하고 PDF 처리·형상 생성 모듈의 import를 확인한다.
4. 설치된 SketchUp의 C API 바이너리를 찾는다. 사용자가 지정한 라이브러리는 우선 사용하며 자동 검색으로 다른 경로로 바꾸지 않는다.
5. 임시 폴더에서 벽체와 원본 참조 이미지가 포함된 `.skp`를 저장하고, 별도 프로세스에서 높이·입체·참조 이미지를 검사한다. 시험 파일은 지운다.
6. `runtime.json`에 실제 Python·C API 경로와 `ready` 상태를 기록한다. 종료 코드 0과 `ready: true`가 모두 확인되어야 사용 가능으로 안내한다.

SketchUp과 SDK 바이너리는 스킬에 포함하지 않는다. 기존 SketchUp에 C API가 없거나 로드되지 않는 경우, Python 준비 성공과 `.skp` 저장 가능 여부를 구분해 보고한다. 이 스크립트가 SketchUp 구매·로그인·SDK 확보까지 완료한다고 안내하지 않는다.

## 개발자 옵션

`PDF2SKP_RUNTIME_DIR`로 기본 사용자 폴더 대신 시험용 경로를 지정할 수 있다. `PDF2SKP_PYTHON`은 가상환경을 만들 때 사용할 인터프리터 경로 또는 버전이다. `--library` 또는 `PDF2SKP_SKETCHUP_API`로 로컬 native 바이너리를 지정한다.

macOS 기본 Python은 `~/.local/share/pdf2skp-skill/.venv/bin/python`, Windows는 `%LOCALAPPDATA%/pdf2skp-skill/.venv/Scripts/python.exe`다. 정확한 경로는 `runtime.json`을 사용한다. 실행 환경은 스킬 폴더 밖에 있으므로 스킬 업데이트 뒤에도 유지된다.
