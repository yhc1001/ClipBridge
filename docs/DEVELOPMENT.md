# 개발·빌드

Python 3.12 이상과 각 OS에서의 네이티브 빌드가 필요합니다. 테스트/CI는 Python 3.13을 사용합니다.

## Windows

```powershell
git clone https://github.com/yhc1001/ClipBridge.git
cd ClipBridge
.\build.ps1
```

결과: `dist/v1.1.0/ClipBridge.exe`. 기존 실행 중인 v1.0.0 파일을 덮어쓰지 않고 별도 폴더에 빌드합니다. `tools/build_exe.py`가 외부 도구의 ICU DLL 충돌을 방지합니다. v1.0.0 Windows 빌드 재현용 의존성 목록은 `requirements-lock.txt`에 있습니다.

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

런타임 로그에 클립보드 내용을 남기지 않습니다. `--smoke-test`와 함께 명시적으로 지정한 시작 진단 환경변수는 개발 검사에만 사용합니다. 개인 설정, 비밀키, 수신 파일은 Git에 포함하지 않습니다.
