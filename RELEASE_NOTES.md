# ClipBridge v1.6.2 — 화면 경계 즉시 전환

화면 경계에서 잠깐 멈추던 이전 기본 대기 **250ms를 제거**했습니다. 화면 가장자리에 도달하면 바로 전환하도록 기본값을 바꿨습니다.

- 기존 통합 그룹의 기본 250ms 설정도 업데이트할 때 한 번 해제합니다.
- 이전 수동 연결과 다른 사용자 지정 지연값, 업데이트 후 직접 바꾼 설정은 유지합니다.
- 입력 이벤트는 별도 내장 Deskflow 엔진이 직접 TLS로 송수신합니다. 클립보드·파일 작업은 별도 채널에서 처리합니다.
- 실제 내장 엔진을 사용해 분리된 두 X11 테스트 화면에서 이전 설정과 새 기본값의 전환 시간을 비교합니다.

일반 Windows 버전은 `ClipBridge-portable.zip`, UAC 설치형은 `ClipBridge-UAC-setup-x64.msi`입니다. Mac ARM/Intel과 Linux X11도 제공합니다. 기존 인증과 연결 설정은 유지합니다.

기존 Deskflow는 서비스까지 종료하세요. 클립보드 연결과 마우스 연결은 각각 상태를 확인할 수 있습니다. 실물 PC의 DPI·고주사율·게임/고부하와 실제 UAC 승인 창에서의 성능 측정은 미검증입니다.

[사용법](https://github.com/yhc1001/ClipBridge#readme) · [마우스 안내](https://github.com/yhc1001/ClipBridge/blob/main/docs/MOUSE_KEYBOARD.md) · [검증 결과](https://github.com/yhc1001/ClipBridge/blob/main/docs/VALIDATION-v1.6.2.md)
