# ClipBridge v1.6.3 — 파일 복사 반응과 누락 개선

Windows에서 파일 목록을 늦게 준비하면 같은 복사가 다시 감지되어 전송을 재시작하던 문제를 수정했습니다. 파일이 잠깐 잠겼을 때는 새로 복사하지 않아도 자동 재시도합니다.

- 클립보드 변경·수신은 알림으로 바로 처리하고, Windows의 고정 감지 대기와 Mac/Linux의 수신 폴링 대기를 제거했습니다. Mac의 변경 감지 주기는 100ms에서 50ms로 줄였습니다.
- 새 버전끼리는 파일 전체를 미리 읽지 않고 전송하면서 SHA-256을 계산합니다. 수신은 모든 파일의 크기·최종 해시 검사 후에만 클립보드에 등록합니다.
- 여러 PC로 보낼 때 같은 복사의 파일 목록 검사를 공유합니다. 수신은 파일마다 열린 스트림을 재사용하며 한 전송당 최대 한 개만 유지합니다.
- 새 복사는 이전 전송을 취소하고, 오프라인 복사는 재연결 시 재생하지 않습니다. 기존 승인·용량 제한·경로 검증은 유지합니다.
- 이전 버전과도 연결되며 이전 파일 프로토콜로 자동 전환합니다. 개선된 전송 방식은 연결할 PC 모두 업데이트해야 적용됩니다.

일반 Windows는 `ClipBridge-portable.zip`, UAC 설치형은 `ClipBridge-UAC-setup-x64.msi`입니다. Mac ARM/Intel과 Linux X11도 제공합니다. 기존 연결 설정은 유지합니다.

큰 파일은 전송 완료 후 붙여넣으세요. 완료 전에 누른 Ctrl+V/⌘V를 예약하는 기능은 없습니다. 실제 PC·LAN/Tailscale에서의 개선 정도와 모든 앱의 사용감은 별도 확인이 필요합니다.

[사용법](https://github.com/yhc1001/ClipBridge#readme) · [파일 공유](https://github.com/yhc1001/ClipBridge/blob/main/docs/FILE_SHARING.md) · [검증 결과](https://github.com/yhc1001/ClipBridge/blob/main/docs/VALIDATION-v1.6.3.md)
