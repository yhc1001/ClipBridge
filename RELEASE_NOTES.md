# ClipBridge v1.3.0 — Linux·마우스 설정·큰 클립보드

- Linux X11 클립보드와 실제 파일/폴더 전송 추가. Ubuntu 24.04 x86_64 실행 파일 제공.
- 별도 설치된 Deskflow 1.27+ 엔진을 ClipBridge에서 실행·종료·재시도. 기존 배치·인증·마우스 설정 가져오기와 드래그 배치 창 추가.
- 기본 클립보드 256MiB, 파일 16GiB. 설정 최대 512MiB / 1TiB, 20,000개 항목. 큰 클립보드·동반 서식도 분할 전송하고 SHA-256 검사.
- 고급 설정을 스크롤 가능한 별도 창으로 분리. 취소하면 원래 값으로 복구.
- 파일 자동 수신과 여러 대 연결 유지. 수신 디스크 공간 사전 검사.

모든 컴퓨터에서 기존 앱을 트레이로 종료하고 새 버전을 실행하세요. 연결 정보는 유지하고 예전 기본 용량은 자동으로 올립니다. 자동 시작을 새 실행 파일에서 다시 저장하세요. 큰 용량은 허브·송신·수신 컴퓨터 모두 올려야 합니다.

마우스 기능에는 각 컴퓨터의 별도 Deskflow 설치가 필요합니다. 기존 Deskflow에서 정지한 뒤 ClipBridge에서 활성화하세요. 원본 설정은 바꾸지 않습니다. Linux 클립보드 정식 지원은 X11이며 Wayland 백그라운드 동작은 보장하지 않습니다.

[사용법](https://github.com/yhc1001/ClipBridge#readme) · [마우스](https://github.com/yhc1001/ClipBridge/blob/main/docs/MOUSE_KEYBOARD.md) · [Linux](https://github.com/yhc1001/ClipBridge/blob/main/docs/LINUX.md) · [검증 기록](https://github.com/yhc1001/ClipBridge/tree/main/artifacts)

실물 Windows↔Mac↔Linux의 앱별 붙여넣기·마우스 이동·로그인 자동 시작은 미검증입니다. 자동 검사와 빌드 결과는 검증 기록에 구분해 남깁니다.

Windows 83개·Linux 79개·Apple 칩/Intel Mac 각각 77개 자동 검사와 각 실행 파일의 빌드·시작·종료 검사가 통과했습니다.
