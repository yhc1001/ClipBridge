# Windows UAC 변형 개발 기록 (진행 중)

일반 버전 v1.4.0은 검증·공개 완료: https://github.com/yhc1001/ClipBridge/releases/tag/v1.4.0

사용자 요청으로 일반 포터블과 UAC 지원 설치형을 따로 제공한다. UAC 변형은 아직 빌드·통합 검증하지 않았으므로 완료/동작 확인으로 안내하면 안 된다. 사용자 PC의 현재 ClipBridge/Deskflow는 작업 중이라 변경·종료하지 않는다. 관리자 설치 승인은 완성된 MSI를 준비한 뒤 사용자에게 받는다. UAC/보안 데스크톱 정책을 낮추지 않는다.

## 선택한 구조

- 트레이·클립보드는 일반 사용자. 입력만 `ClipBridgeInput` LocalSystem Windows 서비스에서 실행.
- 기존 Deskflow daemon은 사용하지 않는다. 원본 daemon은 공용 IPC/레지스트리/프로세스 이름을 사용하며 다른 core를 일괄 종료하는 코드도 있어 기존 프로그램과 격리하기 어렵다. 고정 버전의 core만 별도 서비스가 실행한다.
- SCM 자동 시작·실패 시 재시작 + 고정 core 자식 감시. 현재 SYSTEM 토큰을 복제해 활성 콘솔 세션에 배치하고 TokenUIAccess를 켠다. winlogon/사용자 토큰을 빌려 실행하지 않는다.
- 프로그램/DLL은 MSI로 Program Files의 보호된 경로에 설치. core의 기존 Windows 보안 데스크톱 감지·전환을 사용한다. 사용자 쓰기 가능 실행 파일/명령/경로를 서비스에 전달하지 않는다.
- `prepare_profile(..., copy_windows_runtime=False)`는 설치된 core를 직접 사용한다. 서비스 빌드에서 `_internal/input-engine/settings/Deskflow.conf` 정적 포터블 표시 파일을 추가하고 bundle.json 해시를 갱신해야 한다. 일반 포터블의 기본 실행 방식은 유지한다.
- 서비스 프로필/DPAPI(SYSTEM) 보호 인증서는 ProgramData/ClipBridgeInputService, SYSTEM/Administrators만 읽고 쓰는 ACL. 파일·클립보드 기록은 서비스에 저장하지 않는다. 임시 native PEM은 core 종료 시 지운다.
- 로컬 named pipe만 사용. 원격 pipe 클라이언트 거부, 최초 인스턴스 보호, ACL은 SYSTEM/Administrators/설치 소유자 SID. 요청의 실제 클라이언트 SID를 확인한다.
- 사용자 GUI는 SCM의 서비스 PID/LocalSystem 계정과 실제 이미지 경로를 대조해 pipe 가로채기를 막은 뒤 인증서를 전달한다. 평문 인증서는 로컬 pipe/메모리와 보호된 native 임시 프로필에만 있다.
- 요청은 길이 제한된 JSON bytes. pickle 금지. `status/configure/stop/suspend`만 허용. 설정 필드는 whitelist, 원격 명령·외부 경로·native enter/exit 명령 금지. 수신 PEM은 cert/key 일치를 검사하고 canonical PEM으로 다시 직렬화한다.
- 자식은 suspended로 만들고 kill-on-job-close Job Object에 넣은 뒤 실행한다. 서비스가 죽어도 고권한 core가 고아로 남지 않는다. 소유한 자식만 종료한다.

## 남은 구현

1. 서비스/일반 GUI 연결: `InputManager`가 소유자 SID에 맞는 설치 서비스를 발견하면 로컬 IPC로 구성·상태·정지를 요청. 포터블은 기존 방식. 기존 Deskflow core가 살아 있으면 충돌을 알리고 자동 종료하지 않는다.
2. 종료 의미: 명시적 앱 종료는 `stop`으로 저장된 서비스 enabled=false. OS 종료는 Qt commitDataRequest 또는 SM_SHUTTINGDOWN 확인 후 `suspend`로 이번 프로세스만 정지해 부팅 자동 연결 설정 보존. 설정 변경 stop 후 start/disabled를 명확히 전달.
3. SCM failure restart 설정. native 자식 종료 상태 오류 표시·5초 재시도. 세션 변경 재생성.
4. 서버 모드만 별도 Windows 방화벽 규칙을 COM으로 등록: 고정 Program Files core 경로+입력 포트+사설 프로필, LAN/Tailscale 범위. 등록 상대는 TLS pin으로 제한. 클라이언트는 수신 규칙 불필요. 원래 Deskflow 규칙/서비스는 변경하지 않는다.
5. 서비스 전용 PyInstaller onedir와 MSI: WiX 4.0.6을 CI의 .NET SDK로 사용. MSI ServiceInstall/ServiceControl, LocalSystem auto start, HKLM Software/ClipBridge/InputService OwnerSid=[UserSID], Executable=[설치된 서비스 exe]. 서비스 exe와 의존 DLL은 Program Files. 시작 메뉴/바탕화면 바로가기. 설치/제거 시 서비스 시작·정지·삭제. 앱 최초 설치 실행 시 사용자 로그인 자동 시작 기본값 합리적으로 처리.
6. UAC 버전은 1.5.0으로 버전/빌드 경로를 정리. 일반 1.4.0 공개 파일은 그대로 유지한다. `github_ci.py`는 현재 ref=main/폴더 v1.4.0 고정이므로 새 서비스 브랜치/워크플로 지원을 추가해야 한다. 현재 브랜치 codex/windows-uac-service, 일반 배포 main/tag v1.4.0은 7eb90c8.
7. Windows CI에서 깨끗한 VM에 MSI 실제 설치·서비스 계정/권한·소유자 SID·자식 세션/UIAccess·재시작·IPC 권한/명령 거부·일시 정지/종료·제거를 검사. 사용자 PC에서는 설치/후크 테스트 금지.
8. 가능한 범위에서 별도 보안 ACL 가상 Windows desktop에 실제 TLS native key/mouse를 전달하는 CI 검사 추가. 실제 사용자 UAC 승인 창을 자동으로 누르지 않는다. 실제 UAC/재부팅 검사가 못 되면 명시적으로 미검증으로 기록하고 수동 확인은 사용자가 한다.

## 현재 코드와 검사

서비스 기초: `service_policy.py`, `windows_service_client.py`, `windows_input_service.py`, `service_bootstrap.py`.

`tests/test_service_policy.py` 3개 통과: 명령/경로/필드 거부, 키-인증서 일치·크기·정규화, peer/화면 옵션 제한. 실제 서비스는 아직 설치/실행하지 않았다.

Windows pywin32에는 `QueryFullProcessImageName` 래퍼가 없어 ctypes `QueryFullProcessImageNameW`를 사용했다. 현재 프로세스에 대한 SID/경로 조회 확인 완료. `WTSGetActiveConsoleSessionId`, named pipe client/server PID API는 존재한다.

코드 검토할 점: named pipe overlapped 대기/중단 처리, 명확한 child exit 진단, fail recovery, 보안 desktop 전환 실증, 사용자 계정의 SCM QUERY 접근. 코드가 아직 프로토타입 상태이므로 검증 전 릴리스하지 않는다.

Microsoft 참고: https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasusera , https://learn.microsoft.com/en-us/windows/win32/services/interactive-services
