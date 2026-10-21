# 내장 마우스·키보드 구성 요소

ClipBridge는 Deskflow 1.27.0의 입력 엔진과 필요한 실행 라이브러리를 함께 배포합니다. Deskflow를 별도로 설치하거나 실행하지 않아도 됩니다. 엔진은 별도 자식 프로세스로 실행하고 ClipBridge가 설정·인증·연결·종료를 관리합니다. Deskflow GUI/서비스 설치는 하지 않습니다.

원본: https://github.com/deskflow/deskflow/tree/v1.27.0

엔진의 라이선스는 GPL-2.0-only 및 OpenSSL 예외이며 배포본에 원문을 포함합니다. ClipBridge 소스와 함께 제공하는 `ClipBridge-input-sources.zip`에서 해당 버전의 원본 소스, 재현 스크립트, Linux 변경 내용을 받을 수 있습니다. Qt 등 각 독립 구성 요소의 라이선스도 적용합니다. 내장 Qt 라이브러리는 동적 라이브러리이며 호환되는 수정본으로 교체하고 재빌드할 수 있습니다.

Windows/macOS 엔진은 공식 릴리스의 SHA-256 고정 아티팩트에서 가져옵니다. Windows는 GUI·서비스·원본 설정을 제외하고 core EXE와 DLL만 포함합니다. macOS는 의존 프레임워크와 원본 번들을 내부 리소스로 유지하고 core만 실행합니다. Linux는 Ubuntu 24.04에서 X11 지원으로 빌드합니다. 두 `pkg_check_modules`의 `REQUIRED`와 무조건 적용되는 `WINAPI_LIBEI`·`WINAPI_LIBPORTAL` 정의를 제거해 Wayland 입력을 제외합니다. 이 세 곳의 빌드 변경은 스크립트에 명시하고 원본 소스와 함께 배포합니다.

재현: `assets/input-engine-lock.json`의 고정 원본과 `tools/prepare_input_bundle.py`, 각 OS의 빌드 스크립트를 사용합니다. Linux 빌드에는 CMake, Ninja, C++20 컴파일러, Qt 6.9.3 SDK, OpenSSL 개발 파일, X11/XTest/XRandR/Xinerama/Xkbfile/Xkbcommon/Xkbregistry 개발 파일이 필요합니다. 실행 파일은 빌드 때만 다운로드하며 ClipBridge 실행 중에는 다운로드·업데이트 확인·인터넷 서버 연결을 하지 않습니다.

배포 앱에는 Deskflow 설정 가져오기·자동 탐색이 없습니다. 최초 개발 PC의 일회성 변환 도구는 소스의 `tools/legacy_input.py`에만 두며 실행 파일에 포함하지 않습니다. 예전 ClipBridge에 저장한 설정과 인증서는 계속 유지하고, 외부 파일에 남은 인증서는 보호된 설정으로 이전합니다. 다른 입력 프로그램을 동시에 켜면 충돌하므로 기존 Deskflow가 있다면 정지하세요. ClipBridge가 기존 프로그램을 자동 삭제하지 않습니다.
