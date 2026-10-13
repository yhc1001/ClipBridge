# ClipBridge v1.1.0 — Mac 지원과 간단한 설정

Windows와 Mac 두 컴퓨터에서 평소처럼 복사·붙여넣으면 됩니다.

## 이번 변경

- Apple 칩/Intel Mac용 메뉴 막대 앱, 네이티브 클립보드 감지, 키체인 보안 저장, 로그인 자동 실행.
- Windows↔Mac 텍스트·이미지·HTML/RTF·파일 변환·전송.
- 처음 연결하는 항목만 보이는 설정 화면과 ‘내 IP 주소 확인’ 버튼. 세부 옵션은 고급 설정으로 이동.
- README를 다운로드 → 최초 연결 → 평소 사용의 짧은 안내로 정리. 기술 문서는 docs에 보관.

## 공통 기능

- 텍스트와 이미지 양방향 자동 동기화, Main → newserver 단방향 및 일시 중지.
- TLS 암호화, 인증서 핀, 공유 키 인증, 최초 장치 연결 승인, DPAPI 비밀정보 저장.
- 실제 파일·폴더 분할 전송, 수신 승인, SHA-256 무결성 검사, 안전한 수신 경로와 임시 파일 정리.
- 중복 루프 방지, 동시 복사 충돌 처리, 자동 재연결, Windows 로그인 시 자동 실행 옵션.
- Main과 newserver에 설치하며 Moonlight를 사용하는 노트북에는 설치하지 않습니다.

## 다운로드

- `ClipBridge-portable.zip`: 실행 파일, 한국어 README, 방화벽 설정 스크립트, 제3자 라이선스.
- `ClipBridge.exe`: Python 설치 없이 실행 가능한 Windows x64 파일.
- `ClipBridge-source.zip`: 전체 소스, 테스트, 빌드 및 배포 도구.
- `SHA256SUMS.txt`: 위 파일들의 SHA-256 체크섬.
- `ClipBridge-macOS-arm64.zip`: Apple 칩 Mac의 `.app`.
- `ClipBridge-macOS-intel.zip`: Intel Mac의 `.app`.

## 검증과 제한

Windows 11에서 자동 테스트 52개 통과 및 v1.1.0 EXE 시작·감시·정상 종료 검사 통과. macOS 15 Apple 칩/Intel에서는 네이티브 NSPasteboard, 키체인, 로컬 TLS 등 검사 47개씩 통과했고, 두 .app의 빌드·시작·정상 종료 검사도 통과했습니다. [Mac 빌드 기록](https://github.com/yhc1001/ClipBridge/actions/runs/38369518940)

Windows↔Mac 실물 기기의 앱별 붙여넣기, 재로그인 자동 시작, Gatekeeper 첫 실행은 추가 확인이 필요합니다. Mac 앱에는 Apple Developer ID 서명·공증을 적용하지 않았으며 최초 실행 허용이 필요할 수 있습니다. 공개 형식 외 앱 전용/OLE/Excel 원본 개체 형식은 보존을 보장하지 않습니다.

개인 연결 설정과 비밀키는 이 배포에 포함되지 않습니다. 최초 실행 시 Main/newserver의 IP와 연결 코드를 설정하세요.
