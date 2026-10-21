# ClipBridge v1.5.0 — 일반 버전과 UAC 지원 설치형

Windows 두 버전을 준비했습니다. **일반 버전은 압축만 풀고 실행**, **UAC 화면에서도 입력하려면 설치형**을 사용하세요. Deskflow·Python을 따로 설치할 필요 없습니다.

| 필요한 버전 | 다운로드 파일 |
|---|---|
| 일반 실행 | `ClipBridge-portable.zip` 또는 `ClipBridge.exe` |
| UAC 지원 설치형 | `ClipBridge-UAC-setup-x64.msi` |

Main과 newserver 모두 설치형을 설치하면 같은 ClipBridge 설정으로 사용할 수 있습니다. 기존 앱을 트레이로 종료하고, MSI 설치 후 시작 메뉴 **ClipBridge**를 열어 **로그인하면 자동으로 켜기 → 저장 및 연결**을 누르세요. 마우스 공유는 화면 배치에서 켭니다. 기존 연결 정보는 유지합니다.

- 설치형은 Windows 자동 시작 입력 서비스, 입력 프로세스·서비스 장애 시 재연결을 추가합니다. Main을 껐다 켜고 newserver는 계속 켜 두는 구성을 지원합니다. 클립보드·트레이는 사용자 로그인 후 실행합니다.
- 기존 여러 대 클립보드·실제 파일/폴더 자동 공유·큰 용량·별도 고급 설정은 그대로 사용합니다.
- 서비스는 승인된 연결 설정만 받고 임의 명령이나 외부 실행 파일 경로를 받지 않습니다. 인증서는 SYSTEM DPAPI와 폴더 권한으로 보호하며 UAC 정책을 낮추지 않습니다.
- 별도 Windows 환경에서 MSI 설치·TLS 인증·SYSTEM/UIAccess 입력·보안 ACL 데스크톱의 실제 마우스/키·장애 복구·제거를 검사했습니다. **실제 UAC 승인 창·잠금/로그인 화면·실물 PC 재부팅은 미검증**입니다. 설치 파일은 개발자 코드 서명이 없습니다.
- 이번 릴리스는 Windows용입니다. [Mac·Linux 일반 버전은 v1.4.0](https://github.com/yhc1001/ClipBridge/releases/tag/v1.4.0)에서 받으면 Windows 두 버전과 연결됩니다.

일반 사용자는 소스 ZIP을 받지 않아도 됩니다. `ClipBridge-input-sources.zip`은 내장 엔진·Qt 대응 소스와 재현 자료입니다.

[간단한 설치 방법](https://github.com/yhc1001/ClipBridge/blob/main/docs/WINDOWS_UAC.md) · [검증 결과](https://github.com/yhc1001/ClipBridge/blob/main/docs/VALIDATION-v1.5.md) · [전체 사용법](https://github.com/yhc1001/ClipBridge#readme)
