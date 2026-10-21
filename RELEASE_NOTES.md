# ClipBridge v1.6.1 — 양방향 복사 안정화

- 같은 텍스트를 다시 복사할 때 전송이 빠지던 문제를 수정했습니다. 연결 실패·일시 중지 후 같은 내용을 다시 복사해도 전송합니다.
- 같은 파일을 수정한 뒤 다시 복사하면 실제 내용을 새로 전송합니다.
- 통합 연결에 남아 있던 예전 단방향 설정을 양방향으로 맞춥니다.
- Main/newserver/Laptop 세 대의 모든 6방향에서 텍스트·HTML·이미지·파일·폴더 전달을 loopback TLS로 검사합니다.
- PC 승인과 실제 클립보드 연결 표시를 구분하고, 기존 Deskflow 실행 중에는 클립보드 충돌 가능성을 표시합니다.

**연결할 PC 모두 v1.6.1로 업데이트하세요.** Windows 설치형은 `ClipBridge-UAC-setup-x64.msi`, 일반 버전은 `ClipBridge-portable.zip`입니다. macOS ARM/Intel과 Linux X11도 제공합니다. 기존 연결과 인증서는 유지합니다.

Deskflow와 ClipBridge가 동시에 클립보드를 바꾸면 덮어써질 수 있습니다. Deskflow를 정지하고 ClipBridge의 마우스 동작을 확인한 뒤 Deskflow를 제거해도 됩니다. 세 대를 쓰려면 노트북과 서버가 각각 같은 Main에 연결되어야 합니다. Main의 클립보드 상대 연결 수는 두 대입니다.

연결이 끊겼던 동안의 클립보드를 자동으로 재생하지 않습니다. 재연결 후 다시 복사하세요. 실물 PC의 앱별 붙여넣기, 실제 UAC 승인 창과 재부팅은 미검증입니다.

[쉬운 사용법](https://github.com/yhc1001/ClipBridge#readme) · [검증 결과](https://github.com/yhc1001/ClipBridge/blob/main/docs/VALIDATION-v1.6.1.md)
