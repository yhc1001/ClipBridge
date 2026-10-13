# ClipBridge v1.0.0

Windows PC 두 대에서 텍스트·이미지·HTML/RTF·파일을 자동 동기화하는 한국어 트레이 프로그램입니다.

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

## 검증과 제한

Windows 11 x64 / Python 3.13.5에서 자동 테스트 47개 통과. 최종 EXE의 실제 Windows 클립보드와 독립 loopback TLS 엔진 간 텍스트 양방향, 이미지·HTML/RTF, 실제 파일 수신, 루프 방지, 정상 종료·파일 정리도 통과했습니다.

실제 PC 두 대의 LAN/Tailscale 연결, PicPick/캡처 도구/Word/Excel/탐색기/Moonlight의 개별 앱 조작, 재로그인 자동 시작, Windows Server 버전별 호환성은 자동 검증하지 않았습니다. 공개 형식 외 앱 전용/OLE/Excel 원본 개체 형식은 보존을 보장하지 않습니다. 상세 설정과 제한은 README를 확인하세요.

개인 연결 설정과 비밀키는 이 배포에 포함되지 않습니다. 최초 실행 시 Main/newserver의 IP와 연결 코드를 설정하세요.
