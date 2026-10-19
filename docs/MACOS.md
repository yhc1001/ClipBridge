# Mac 지원

Windows↔Mac, Mac↔Mac에 같은 연결 방식과 TLS 인증을 사용합니다. v1.2부터 허브 한 대에 여러 Windows/Mac을 연결합니다. newserver를 허브로 두고 Mac에는 허브 IP와 연결 코드를 입력하세요. Mac도 허브로 쓸 수 있지만 계속 켜 두어야 합니다.

- macOS NSPasteboard의 변경 번호를 0.1초마다 확인하여 앱이 숨겨져 있어도 새 복사를 감지합니다.
- Unicode 텍스트, PNG/TIFF 이미지, HTML, RTF, Finder 파일·폴더의 실제 전송을 구현했습니다.
- Windows HTML의 바이트 오프셋과 Mac HTML을 서로 변환합니다. Windows DIB 이미지도 PNG로 변환하여 Mac에 등록합니다.
- Mac 비밀정보는 로그인 키체인에 저장한 키로 AES-GCM 암호화합니다. 설정은 `~/Library/Application Support/ClipBridge`에 저장합니다.
- 자동 실행은 현재 사용자의 LaunchAgent를 사용합니다. ‘로그인하면 자동으로 켜기’를 체크한 뒤 저장하세요. 앱을 응용 프로그램 폴더로 옮긴 뒤 설정하세요.
- 수신 파일은 임시 저장소에 놓고 Finder가 붙여넣을 수 있는 file URL로 등록합니다. 실제 붙여넣기를 완료한 뒤 프로그램을 종료하세요.
- 수신 데이터와 연결 코드에 `currentHostOnly`를 사용하여 Apple Universal Clipboard에 공유하지 않습니다.

## 검증

현재 버전의 실제 macOS 테스트 및 Apple 칩/Intel .app 빌드는 [GitHub Actions](https://github.com/yhc1001/ClipBridge/actions/workflows/build-macos.yml)와 [버전별 검증 기록](../artifacts/)에서 확인합니다. 여러 대 연결 검사는 실제 TLS 소켓을 사용하지만 같은 호스트 안에서 수행합니다.

**v1.2.0:** Apple 칩과 Intel에서 각각 60개 검사를 통과했고, 두 .app 모두 빌드·시작·정상 종료가 통과했습니다. [v1.2.0 빌드 기록](https://github.com/yhc1001/ClipBridge/actions/runs/39243272272). 이후 수정은 Windows 클립보드와 Windows 검사·문서에 한정됩니다.

이전 v1.1.0에서도 macOS 15 Apple 칩과 Intel 각각 검사 47개와 .app 빌드·시작·종료가 통과했습니다. [v1.1.0 빌드 기록](https://github.com/yhc1001/ClipBridge/actions/runs/38369518940)

Mac과 Windows **서로 다른 실물 기기**의 앱별 붙여넣기, Finder UI 조작, 재로그인 자동 시작, 새 Mac에서 Gatekeeper 및 키체인 승인 절차는 자동으로 검증하지 않았습니다. 클립보드 접근 알림이 나타나는 macOS 버전에서는 접근을 허용해야 합니다.

기존 1:1 장치의 인증은 유지합니다. 여러 대 공유에는 모든 컴퓨터를 v1.2 이상으로 업데이트하세요. 새 Mac은 허브에서 새로 복사한 코드로 추가합니다. 이미 등록한 다른 기기의 연결을 초기화할 필요는 없습니다.

[Apple: currentHostOnly](https://developer.apple.com/documentation/appkit/nspasteboard/contentsoptions/currenthostonly) · [Apple: 서명되지 않은 앱의 첫 실행 안내](https://support.apple.com/en-ie/102445)
