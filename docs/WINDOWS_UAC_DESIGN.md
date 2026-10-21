# Windows UAC 설치형 구조

일반 EXE와 MSI의 GUI·클립보드는 같은 코드입니다. MSI는 입력만 처리하는 `ClipBridgeInput` LocalSystem 서비스를 추가합니다. Deskflow GUI·daemon·설치 프로그램은 사용하지 않습니다. 고정 버전의 내장 core만 실행합니다. 실제 검사 범위는 [v1.5 검증 기록](VALIDATION-v1.5.md)에 따릅니다.

## 권한 경계

- 서비스·core·DLL은 MSI의 비공개 설치 디렉터리 속성으로 지정한 Program Files 하위에 설치합니다. 일반 사용자가 실행 파일 경로·DLL 경로·명령행을 요청에 지정할 수 없습니다.
- 설치 시 개별 사용자 SID를 HKLM에 등록합니다. 서비스 로컬 pipe는 SYSTEM·Administrators·이 사용자만 접근하며 remote pipe client를 거부합니다. 사용자에게 pipe 인스턴스를 추가할 수 있는 권한은 주지 않습니다. 실제 client PID의 토큰 SID도 대조합니다.
- GUI는 SCM에 등록된 서비스 PID·LocalSystem 계정·설치 이미지 경로를 확인한 뒤 pipe로 인증서를 전달합니다. IPC는 길이가 제한된 JSON bytes입니다. pickle은 사용하지 않습니다.
- v1.6은 설치 소유자에게 서비스 프로세스의 `PROCESS_QUERY_LIMITED_INFORMATION`만 추가로 허용합니다. UAC로 필터링된 일반 사용자 토큰에서도 이미지 경로 대조가 가능하며 프로세스 메모리 쓰기·주입·강제 종료 권한은 주지 않습니다.
- 허용 요청은 `status`, `configure`, `stop`, `suspend`뿐입니다. 입력 설정 필드는 whitelist이며 화면의 enter/exit 명령도 금지합니다. 인증서는 키 일치·크기·알고리즘을 확인한 뒤 canonical PEM으로 다시 직렬화합니다.
- 서비스 인증서는 SYSTEM DPAPI로 보호하며 설정과 런타임 프로필은 SYSTEM/Administrators만 접근 가능한 ProgramData 폴더에 둡니다. 런타임 PEM은 child 종료 시 삭제합니다. 저장 상태는 설치 소유자 SID에 묶으며 소유자가 달라지면 폐기합니다. 클립보드·받은 파일은 서비스에서 처리하거나 기록하지 않습니다.

## 입력 프로세스

자신의 SYSTEM 토큰을 복제해 활성 콘솔 세션과 UIAccess를 설정하고 `CreateProcessAsUser`로 보호된 core를 시작합니다. winlogon이나 사용자 토큰을 빌리지 않습니다. core는 suspended로 생성하고 kill-on-job-close Job Object에 넣은 뒤 실행합니다. 서비스가 강제 종료돼도 고권한 core가 고아로 남지 않습니다.

원본 core의 보안 데스크톱 감지·전환 기능을 사용합니다. 원본 core의 로컬 IPC는 연결한 server PID가 자신이 실행한 core인지 확인한 뒤 SYSTEM/Administrators 전용 ACL로 좁힙니다. 이 연결로 실제 연결 상태를 받고 종료 시 키·커서 정리를 요청합니다. 여러 프로세스에 영향을 주는 원본의 전역 종료 이벤트는 사용하지 않습니다. 기존 다른 입력 core가 실행 중이면 시작을 보류하며 기존 프로그램을 종료하지 않습니다.

서비스용 core는 고정 Program Files에서 직접 실행하고 전용 portable marker와 private 설정 경로를 사용합니다. 일반 버전은 기존 사용자 전용 임시 런타임을 사용합니다. 두 경로 모두 엔진 TLS와 인증서 고정을 켜며 엔진 자체 클립보드·enter/exit 명령·업데이트 확인은 끕니다. 별도 Qt 실행 라이브러리는 GUI의 Qt DLL 경로와 분리합니다.

## 수명과 네트워크

- SCM은 Windows 시작 시 서비스를 실행하고 비정상 종료 시 5초 후 복구합니다. 서비스는 입력 자식 종료·세션 변경을 감지하고 5초 간격으로 재시도합니다. 기본값으로 입력 공유가 켜지지는 않으며 최초 페어링·설정이 필요합니다.
- GUI의 명시적 종료/공유 끄기는 `stop`으로 저장 상태를 비활성화합니다. Windows 종료 시에는 `suspend`로 이번 child를 정지하고 다음 서비스 시작의 자동 연결 설정은 보존합니다. GUI·클립보드 자동 시작은 기존 사용자 Run 등록입니다.
- 입력 서버에서만 자기 규칙 하나를 관리합니다. 설치된 고정 core 경로, 지정한 TCP 포트, Private 프로필, LocalSubnet·Tailscale IPv4/IPv6 범위로 제한합니다. 클라이언트 모드에는 인바운드 규칙이 없습니다. 중지·제거 시 규칙을 지웁니다. 인증은 별도의 TLS pin으로 제한합니다.
- v1.6의 통합 연결은 설치된 GUI에 TCP 24802·45832 사설 규칙을 별도로 등록합니다. 승인·화면 배치와 클립보드 네트워크는 일반 사용자 GUI에서 처리합니다. 서비스 종료 시 자기 GUI 규칙도 지웁니다. 범용 방화벽 설정 API는 제공하지 않습니다.
- UAC·보안 데스크톱 정책은 변경하지 않습니다. 외부 명령 실행이나 범용 관리자 작업 API는 제공하지 않습니다. RDP·여러 로그인 세션·실제 보안 화면에 대한 범위는 검증 기록을 확인하세요.

서비스 구현: `clipbridge/windows_input_service.py`, 클라이언트: `windows_service_client.py`, 정책: `service_policy.py`, MSI 빌드: `tools/build_windows_uac.py`.

Microsoft API 문서: [CreateProcessAsUser](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasusera), [대화형 서비스](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services), [서비스 장애 복구](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-changeserviceconfig2a).
