# 개발·빌드

Python 3.12 이상과 각 OS에서의 네이티브 빌드가 필요합니다. 테스트/CI는 Python 3.13을 사용합니다.

## Windows

```powershell
git clone https://github.com/yhc1001/ClipBridge.git
cd ClipBridge
.\build.ps1
```

결과: `dist/v1.4.0/ClipBridge.exe`. 기존 실행 파일을 덮어쓰지 않고 버전별 폴더에 빌드합니다. `tools/build_exe.py`가 외부 도구의 ICU DLL 충돌을 방지합니다. v1.0.0 Windows 빌드 재현용 의존성 목록은 `requirements-lock.txt`에 있습니다.

## macOS

```bash
git clone https://github.com/yhc1001/ClipBridge.git
cd ClipBridge
bash build-macos.sh
```

결과: `dist/macos/ClipBridge.app`과 현재 빌드 Mac의 아키텍처 ZIP. Apple 칩/Intel 빌드는 GitHub Actions의 `macOS apps` 워크플로에서 각각 생성할 수 있습니다. Apple Developer ID 서명·공증은 포함하지 않습니다.

## 검사

```bash
python -m pytest -q
```

Windows 전용 검사는 Mac에서, Mac 네이티브 검사는 Windows에서 건너뜁니다. Mac 어댑터의 핵심 처리/경합 검사는 가짜 pasteboard로 양쪽에서 실행합니다. 실제 NSPasteboard와 키체인은 macOS CI에서 검사합니다. 테스트는 지원 가능한 기존 클립보드를 복구하고, Windows 자동 시작 레지스트리의 원래 값을 복구합니다.

Windows 자동 시작은 현재 사용자의 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 등록이며 서비스 설치가 아닙니다. 사용자 로그인 후 `--background`로 시작합니다. 앱 프로세스의 충돌 복구·로그인 전/잠금 화면/UAC 입력은 구현하지 않았습니다. 입력 자식 프로세스 종료와 네트워크 단절은 앱이 실행 중일 때 재시도합니다. 등록 검사와 실제 재부팅 후 검증은 구분합니다.

`tests/test_multidevice.py`는 허브 + 참여 컴퓨터 3대의 실제 로컬 TLS 연결로 중계·파일 승인·동시 복사·재접속·인증키 분리와 해제를 검사합니다. 기기별 클립보드 적용은 메모리 어댑터를 사용하고, OS 클립보드 검사는 별도 네이티브 테스트에서 수행합니다. 서로 다른 실물 기기나 16대 최대 부하를 검증한 결과로 해석하지 마세요.

런타임 로그에 클립보드 내용을 남기지 않습니다. `--smoke-test`와 함께 명시적으로 지정한 시작 진단 환경변수는 개발 검사에만 사용합니다. 개인 설정, 비밀키, 수신 파일은 Git에 포함하지 않습니다.

## Linux

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python tools/build_linux.py
```

Ubuntu 24.04 x86_64 / Python 3.13 기준입니다. 내장 엔진을 빌드할 Qt 6.9.3 SDK와 X11 개발 라이브러리가 필요합니다. 정확한 설치 목록과 빌드 환경은 `.github/workflows/build-linux.yml`에 있습니다. 데스크톱 없는 환경에서는 Xvfb와 xclip을 설치하고 `xvfb-run -a python -m pytest -q`로 실제 X11 클립보드를 검사합니다. 결과는 `dist/ClipBridge-linux-x86_64.tar.gz`. GitHub Actions의 `Linux app`에서 네이티브 검사·빌드·실행 검사를 수행합니다. 다른 배포판은 glibc/Qt 시스템 라이브러리 호환성이 필요하며 미검증입니다.

## 내장 마우스·키보드 엔진

별도 Deskflow 설치는 필요 없습니다. 각 빌드 스크립트가 `tools/prepare_input_bundle.py`로 SHA-256이 고정된 엔진과 실행 라이브러리를 준비해 앱에 포함합니다. 개발 중에는 검사 전에 `python tools/prepare_input_bundle.py`를 실행하세요. 다운로드는 빌드 시에만 합니다. 배포한 앱은 시스템의 Deskflow 설치 경로나 PATH를 검색하지 않습니다.

`input_engine.py`는 내장 엔진의 공개 CLI/INI 인터페이스를 사용합니다. 일반 배포 앱은 Deskflow 설정 파일을 자동으로 찾거나 읽지 않으며 가져오기 UI도 없습니다. 예전에 ClipBridge에 저장한 인증서는 DPAPI/키체인/보호된 로컬 키로 보관합니다. 이전 버전에 외부 인증서 경로가 남아 있다면 보호된 설정으로 이전하고, 원본을 이미 삭제했다면 마우스만 비활성화해 클립보드는 계속 시작합니다. 이 경우 상대 마우스 연결 코드를 다시 등록하세요.

최초 개발 PC의 일회성 이전에 쓰는 읽기 전용 변환 함수는 `tools/legacy_input.py`에만 남겼습니다. 앱의 의존 관계에 포함되지 않아 실행 파일에 들어가지 않으며 일반 사용자 설정 기능으로 제공하지 않습니다. 이미 저장된 ClipBridge 설정과 별개입니다.

Windows는 core와 함께 포함된 DLL을 소유자 전용 임시 폴더에 놓고 실행합니다. Linux는 포함된 별도 Qt 라이브러리와 X11 플러그인을 사용하며, Mac은 앱 내부 리소스의 엔진을 실행합니다. 종료 시 자식 프로세스와 임시 개인키를 정리합니다. 강제 종료로 남은 개인 프로필은 다음 마우스 엔진 시작 시 삭제합니다. 엔진 재시도는 5초입니다.

`tools/bundled_input_smoke.py`는 설치 경로를 사용할 수 없는 독립 설정에서 **배포된 앱 자체**로 내장 core의 의존성·버전·프로필 생성·삭제를 검사합니다. 입력 후크를 시작하지 않습니다. `tools/linux_input_integration.py`는 별도의 가상 X11 화면 두 개에서 TLS 연결·화면 가장자리 이동·키 입력을 검사하며 사용자 데스크톱에 연결하지 않습니다. 실물 Windows/Mac/Linux 사이의 입력·OS 권한 승인 검사는 별도로 필요합니다.

엔진·Qt 대응 소스는 `python tools/package_input_sources.py`로 별도 ZIP을 만듭니다. 빌드 원본·라이선스·Linux의 X11 전용 변경은 [내장 구성 요소](INPUT_COMPONENT.md)에 설명합니다.
