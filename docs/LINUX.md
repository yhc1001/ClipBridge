# Linux에서 쓰기

Ubuntu 24.04 x86_64의 **X11 데스크톱**을 기준으로 구현했습니다. Windows·Mac과 같은 TLS 연결·연결 코드·허브를 사용합니다. 압축을 풀고 `ClipBridge/ClipBridge`를 실행한 뒤 허브의 연결 코드를 붙여넣으세요.

- 글자·PNG 이미지·HTML·RTF·실제 파일/폴더 전송을 지원합니다. Qt 클립보드 변경 신호로 감지하며 백그라운드에서 X11 selection 요청에 응답합니다. 선택만 한 PRIMARY selection은 공유하지 않습니다.
- 파일을 수신하면 `text/uri-list`, GNOME 복사 목록, KDE 복사 표시를 등록합니다. 파일 관리자에서 Ctrl+V로 복사합니다. 잘라내기/이동은 복사로 처리합니다.
- 원격 file URL, 심볼릭 링크, Windows에 저장할 수 없는 파일명·경로는 차단합니다. 해당 항목은 상태로 알리고 계속 실행합니다.
- 자동 실행은 현재 사용자의 `~/.config/autostart/clipbridge.desktop`입니다. 그래픽 로그인 후 시작하며 SSH 세션이나 로그인 이전 시스템 서비스로 동작하지 않습니다.
- 설정은 `~/.local/share/ClipBridge` (`XDG_DATA_HOME` 적용)에 저장합니다. 비밀정보는 AES-GCM으로 암호화하며 로컬 키는 같은 계정만 읽는 권한 600 파일에 저장합니다. Windows DPAPI·Mac Keychain과 다른 방식이며 설정 폴더를 다른 OS로 복사하지 마세요.
- 수신 파일은 붙여넣는 동안 보관하고 다음 항목/종료 때 정리합니다. 앱이 종료되면 X11 클립보드 소유권도 사라질 수 있으므로 붙여넣기까지 켜 두세요.

**Wayland:** Qt의 일반 클립보드 API만 사용하므로 포커스가 없는 앱의 복사 감지·클립보드 쓰기를 보장하지 않습니다. 이번 버전의 정식 클립보드 지원 범위는 X11입니다. 로그인 화면에서 Xorg/X11 세션을 선택하세요. Deskflow의 Wayland 마우스 지원과 ClipBridge의 클립보드 지원 범위는 다릅니다.

마우스·키보드는 해당 배포판에서 실행 가능한 **Deskflow 1.27 이상 native `deskflow-core`**를 설치하고 [마우스 설정](MOUSE_KEYBOARD.md)을 따릅니다. Flatpak 실행 래퍼는 이 버전에서 지원하지 않습니다. 엔진 파일을 ‘찾기’로 지정할 수 있습니다.

자동 검사는 Xvfb의 실제 X11 클립보드, 별도 xclip 프로세스의 복사 감지, MIME/파일 URL 변환, 파일 바이트·TLS 전송, 설정 암호화와 패키지 시작·종료를 검사합니다. 배포판별 파일 관리자 UI·실물 Windows↔Linux↔Mac 붙여넣기·실제 재로그인·Wayland는 미검증입니다. [빌드 기록](https://github.com/yhc1001/ClipBridge/actions/workflows/build-linux.yml)

[Qt 클립보드 문서](https://doc.qt.io/qt-6/qclipboard.html) · [Deskflow](https://github.com/deskflow/deskflow)
