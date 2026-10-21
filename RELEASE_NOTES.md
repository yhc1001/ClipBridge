# ClipBridge v1.4.0 — ClipBridge만으로 마우스·키보드까지

**Deskflow를 따로 설치하지 않아도 됩니다.** Windows·Apple 칩 Mac·Intel Mac·Linux X11 배포본에 마우스·키보드 엔진과 실행 라이브러리를 포함했습니다. Python 설치도 필요 없습니다.

1. 모든 컴퓨터에서 기존 ClipBridge를 트레이로 종료한 뒤 새 버전을 실행하세요.
2. **마우스·키보드 / 화면 배치…**에서 서로의 마우스 연결 코드를 등록하고 화면을 배치하세요.
3. 기존 Deskflow가 실행 중이면 정지하고 **ClipBridge에서 마우스·키보드도 공유**를 켜세요. 로그인 자동 시작도 새 실행 파일에서 저장하세요.

기존 ClipBridge의 클립보드 연결·마우스 설정은 유지합니다. 일반 배포 앱에서 Deskflow 설정 가져오기 버튼과 자동 탐색을 제거했습니다. 별도 프로그램의 설치 폴더에 의존하지 않고 ClipBridge 자체 연결·화면 배치로 설정합니다. 기존 Deskflow를 자동으로 종료하거나 제거하지 않습니다. 사용 중인 PC의 실행 파일도 이 배포 작업으로 강제 교체하지 않았습니다.

- 여러 대 클립보드·실제 파일/폴더 자동 공유, 별도 고급 설정 창과 큰 용량 설정을 유지했습니다.
- 배포본 자체에서 시스템 Deskflow 경로 없이 엔진 의존성·실행·전용 프로필 정리를 검사했습니다.
- Windows 87개, Linux 83개, Apple 칩/Intel Mac 각각 81개 자동 검사와 실행 파일 시작·종료 검사를 통과했습니다. Linux 가상 화면 두 개 사이의 실제 TLS·마우스 화면 이동·키 수신도 통과했습니다.
- 내장 구성 요소의 원본·라이선스·Qt 대응 소스와 빌드 스크립트는 `ClipBridge-input-sources.zip`으로 제공합니다. 일반 사용자는 내려받지 않아도 됩니다.

자동 시작은 **사용자 로그인 후**입니다. Windows 서비스 설치·앱 비정상 종료 감시·로그인 전/잠금 화면/UAC 입력은 구현하지 않았습니다. Linux는 Ubuntu 24.04 x86_64 X11 기준입니다. Wayland 입력·백그라운드 클립보드, 실물 Windows↔Mac↔Linux의 앱별 붙여넣기·마우스 이동·OS 권한 승인·실제 재로그인은 미검증입니다. Mac 앱은 개발자 서명·공증하지 않았습니다.

[쉬운 사용법](https://github.com/yhc1001/ClipBridge#readme) · [마우스 설정](https://github.com/yhc1001/ClipBridge/blob/main/docs/MOUSE_KEYBOARD.md) · [검증 결과](https://github.com/yhc1001/ClipBridge/blob/main/docs/VALIDATION-v1.4.md)
