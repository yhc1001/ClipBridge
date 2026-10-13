# ClipBridge

Windows PC 두 대의 클립보드를 LAN/Tailscale에서 자동으로 양방향 동기화하는 한국어 트레이 프로그램입니다. Main과 newserver에 같은 `ClipBridge.exe`를 실행합니다. 노트북에는 설치하지 않습니다. Deskflow, Moonlight, Sunshine의 설정이나 설치 파일은 변경하지 않습니다.

## GitHub에서 다시 받기

- 소스 저장소: [yhc1001/ClipBridge](https://github.com/yhc1001/ClipBridge) — 비공개.
- 실행 파일·포터블 ZIP·소스 ZIP·SHA-256: [v1.0.0 Release](https://github.com/yhc1001/ClipBridge/releases/tag/v1.0.0).

소유자 GitHub 계정으로 로그인한 뒤 Release에서 `ClipBridge-portable.zip`을 받아 압축을 풀고 `ClipBridge.exe`를 실행하면 됩니다. 소스코드와 빌드 스크립트도 저장소에 보관합니다.

개별 PC의 AppData 설정, 페어링 비밀키, 수신 파일, 가상환경 및 빌드 산출물은 Git에 저장하지 않습니다. 다른 PC에서 처음 사용할 때는 아래 순서로 다시 페어링합니다. 기존 PC의 설정은 AppData에 유지되므로 EXE만 같은 위치에서 업데이트하면 그대로 사용할 수 있습니다. 자동 시작 등록은 각 PC의 `Windows 로그인 시 자동 실행` 설정으로 관리합니다.

```powershell
git clone https://github.com/yhc1001/ClipBridge.git
cd ClipBridge
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\build.ps1
```

향후 수정한 소스는 이 폴더에서 커밋하고 `git push origin main`으로 보관할 수 있습니다. 새 배포 버전은 Git 태그를 푸시한 뒤 `tools/package_release.py`로 패키지를 만들고 `tools/github_release.py release --tag <태그> --notes <설명 파일>`로 업로드할 수 있습니다. 게시 도구는 Windows Git Credential Manager 또는 명시적으로 제공한 GitHub 환경 토큰을 사용하며 인증정보를 파일이나 로그에 저장하지 않습니다.

## 바로 실행

`dist/ClipBridge.exe`는 Python 설치가 필요 없는 Windows x64 포터블 실행 파일입니다. EXE를 양쪽 PC의 고정된 폴더에 복사해서 실행하세요. 설정은 EXE 옆이 아닌 `%LOCALAPPDATA%\ClipBridge\settings.json`에 저장됩니다. 관리자 권한은 일반 실행에 필요하지 않습니다.

1. **Main:** 역할을 `Main · 연결 대기`로 두고 상대 PC IP에 **newserver의 LAN/Tailscale IP**를 입력합니다. 포트는 기본 `45832`입니다. `저장 및 연결`을 누릅니다.
2. **Main:** `Main 연결 코드 복사`를 누르고, 믿을 수 있는 방법으로 코드를 newserver에 전달합니다. 코드에는 공유 비밀키가 들어 있으므로 공개 채팅·저장소에 올리지 마세요. 이 버튼으로 복사한 코드는 ClipBridge 동기화, Windows 클립보드 기록/클라우드 대상에서 제외합니다.
3. **newserver:** `newserver 코드 등록`에 Main 코드를 붙여넣습니다. 역할은 자동으로 newserver가 됩니다. 상대 PC IP에 **Main의 IP**, Main과 같은 포트를 입력하고 `저장 및 연결`을 누릅니다.
4. **Main:** 나타나는 장치 연결 요청에서 IP와 장치 ID를 확인하고 승인합니다. 그 장치만 이후 연결할 수 있습니다. 설정 창과 트레이가 `연결됨`으로 바뀝니다.
5. **새로** 텍스트나 이미지를 복사합니다. 상대 PC 적용 ACK를 받으면 `송신 완료`, 수신 PC에는 `수신 완료`와 시각·형식이 표시됩니다. 연결 전에 복사했던 항목은 자동 전송하지 않습니다.

예: Main `192.168.0.10`, newserver `192.168.0.20`이라면 Main의 상대 IP는 `.20`, newserver의 상대 IP는 `.10`입니다. Tailscale에서는 양쪽 장치의 `100.x.x.x` 또는 ULA IPv6 주소를 사용합니다. IP를 직접 입력하며 도메인/DNS·인터넷 서버·장치 자동 검색은 사용하지 않습니다.

Moonlight에서는 **Sunshine이 표시하는 newserver의 같은 로그인 세션**에 ClipBridge가 실행되어 있어야 합니다. Main에서 복사한 뒤 수신 완료를 확인하고 노트북 Moonlight 화면에서 Ctrl+V를 누릅니다. RDP의 별도 사용자 세션이나 Windows 서비스의 session 0은 클립보드가 다릅니다. 이 배포본은 사용자별 한 인스턴스만 실행합니다.

## Windows 방화벽

수신 포트는 Main의 TCP 45832 하나입니다. 프로그램이 방화벽 설정을 자동으로 넓히지 않습니다. Windows 허용 창을 사용한다면 **사설 네트워크만** 허용하고 공용 네트워크는 선택하지 마세요.

관리자 PowerShell에서 제공한 스크립트로 EXE·포트·상대 IP를 모두 제한할 수 있습니다. 실제 사용할 EXE 경로를 지정하세요.

```powershell
.\Configure-Firewall.ps1 -PeerIp 192.168.0.20 -Port 45832 -ExePath 'C:\Tools\ClipBridge\ClipBridge.exe'
```

이 스크립트는 `ClipBridge-v1-Private` 이름의 규칙만 생성/교체합니다. 범위는 지정한 프로그램, TCP 포트, 상대 IP, **Private** 프로필입니다. 공용 프로필이나 라우터 포트 포워딩을 열지 않습니다. 일반적으로 newserver에는 새 수신 예외가 필요 없습니다.

Tailscale 어댑터가 Public 프로필이면 이 Private 규칙은 적용되지 않습니다. 해당 어댑터의 프로필과 조직의 Tailscale ACL/Windows 방화벽 정책을 확인하세요. 프로그램이나 스크립트가 프로필을 자동 변경하지 않습니다. LAN/Tailscale 두 PC에서 실제 연결 및 방화벽 규칙 적용은 아직 미검증입니다.

## 구현된 형식과 제한

| 항목 | 구현 |
|---|---|
| 일반 텍스트 | CF_UNICODETEXT → UTF-8 전송 → CF_UNICODETEXT. CF_TEXT는 Windows ANSI 코드 페이지로 Unicode 변환 |
| 이미지 | 등록 PNG, CF_DIB, CF_DIBV5 보존. CF_BITMAP만 있으면 DIB로 변환. PNG/DIB 호환 형식을 추가하여 붙여넣기 지원 |
| HTML/RTF | `HTML Format`, `Rich Text Format`, `Rich Text Format Without Objects`의 원본 바이트 보존. HTML 헤더의 UTF-8 바이트 오프셋도 유지 |
| Excel 셀 | 공개 텍스트/HTML/RTF, CF_SYLK/CF_DIF가 제공되면 함께 보존. SYLK/DIF의 실제 Excel 호환성은 미검증 |
| 파일·폴더 | CF_HDROP에서 실제 로컬 파일을 읽고 폴더 구조, 빈 파일/폴더, 복수 파일을 전송. 수신 파일 경로로 새 CF_HDROP 등록 |
| 파일의 다른 형식 | 파일 목록과 함께 제공된 지원 텍스트/이미지 형식도 전송·등록 |

동시에 제공되는 지원 형식을 합산 용량 범위에서 함께 보존합니다. 기본 클립보드 합산 제한은 **96 MiB**, 설정 가능 범위는 1–128 MiB입니다. 이미지 크기는 최대 2,500만 픽셀입니다. 큰 이미지의 여러 DIB 표현이 합산 제한을 넘으면 일부 형식을 생략하고 상태를 표시합니다. CF_DIB는 일반 BI_RGB/비트 마스크 계열을 지원하며 RLE/JPEG/PNG 압축 DIB·16비트 색상 특수 팔레트 등은 호환성을 보장하지 않습니다.

앱 전용 비공개 형식, Excel BIFF/수식·통합문서 참조, OLE/IDataObject, 파일 가상 스트림, Outlook 첨부의 FileContents/FileGroupDescriptor, 메타파일, 오디오, 사용자 정의 GDI 핸들 등은 직렬화하지 않습니다. Excel의 셀 값과 표 서식은 공개 텍스트/HTML을 통해 전달되지만 원본 수식·OLE 개체의 완전 보존은 보장하지 않습니다. 지연 렌더링은 원본 앱이 GetClipboardData에 데이터를 제공할 수 있을 때만 읽을 수 있습니다. 원본 앱이 종료되었거나 형식을 제공하지 못하면 생략/재시도합니다. 지원하지 않는 형식 때문에 프로그램을 종료하지 않습니다.

## 트레이와 기본값

- 텍스트·이미지: 켜짐, 양방향 자동 동기화.
- 파일: 켜짐, **수신마다 승인**. 첫 승인 때 `이 장치의 다음 파일도 항상 허용`을 선택하면 이후에는 그 신뢰 장치에서 자동 수신합니다. 설정에서 파일 기능을 끄거나 수신·전송을 차단할 수 있습니다.
- 파일 합계 제한: 기본 512 MiB, 1–1024 MiB. 파일+디렉터리 합계 최대 2,000개, 상대 경로 최대 220자.
- `Main → newserver`를 사용할 때는 **양쪽에서 같은 방향 설정**을 선택합니다. 상대 설정과 달라도 각 PC의 송·수신 제한이 각각 적용됩니다.
- 일시 중지 중에는 새 항목을 송·수신 적용하지 않습니다. 재개 시 현재 항목을 재전송하지 않습니다.
- 창 닫기는 트레이로 숨김입니다. 트레이 `종료`는 리스너·네트워크·작업 스레드를 종료하고 수신 파일을 정리합니다.
- 자동 실행은 기본 꺼짐입니다. 체크 후 `저장 및 연결`하면 현재 사용자의 HKCU Run에 실행 경로와 `--background`를 등록합니다. EXE를 옮겼다면 다시 저장하세요.
- 연결 코드/장치 변경 시 `신뢰 초기화` 후 양쪽에서 다시 페어링합니다. 새 키가 만들어지고 기존 장치 신뢰가 폐기됩니다.

## 동기화와 충돌 규칙

Windows의 **AddClipboardFormatListener / WM_CLIPBOARDUPDATE**를 사용합니다. PicPick이나 캡처 단축키에 의존하지 않습니다. 클립보드 Windows 메시지 처리와 이미지 변환은 전용 스레드, TLS/파일 전송은 별도 asyncio 스레드에서 처리하므로 파일 해시·전송·승인 대기 중에도 UI가 동작합니다.

내용의 SHA-256과 수신 항목의 출처 마커로 중복/되돌림 전송을 방지합니다. 동시에 복사하면 `(Lamport 논리 카운터, 장치 UUID)`가 큰 이벤트를 선택합니다. 같은 카운터에서는 UUID의 사전순이 큰 장치가 우선하며 PC 시각 차이는 결과에 영향을 주지 않습니다. 서로의 이벤트를 관측한 뒤 복사한 이벤트는 더 큰 카운터를 받습니다.

클립보드 sequence 번호도 확인하여 수신 준비·파일 전송 동안 발생한 새 로컬 복사를 오래된 수신 항목으로 덮어쓰지 않습니다. 새 복사가 이전 파일 전송보다 우선하며 이전 전송은 취소·정리됩니다. 클립보드가 다른 앱에 열려 있으면 약 4초 범위에서 읽기/쓰기 재시도를 합니다.

newserver는 끊긴 연결을 1→2→4→8→15초 간격으로 재시도합니다. Main은 계속 지정한 PC의 연결을 기다립니다. 재연결 시 논리 카운터만 교환하고 **클립보드 내용·오프라인 복사·이전 미완료 전송은 재전송하지 않습니다**. 연결된 후 다시 복사하세요. 두 PC가 연결되지 않은 동안 서로 다른 클립보드를 유지하는 것은 의도한 동작입니다.

## 보안 및 수신 파일

- TLS 1.2 이상. newserver는 Main 인증서의 SHA-256 핀을 확인한 뒤 인증을 진행합니다. 양쪽이 무작위 nonce와 역할·장치 ID를 묶은 HMAC-SHA256 공유 키 인증을 합니다.
- Main은 설정된 숫자 IP 및 승인된 장치 UUID 한 개만 허용합니다. 허용 IP는 RFC1918 LAN, Tailscale CGNAT/ULA, loopback/link-local입니다. 공인 IP 접속은 기본 기능에 포함되지 않습니다.
- 공유 키와 인증서 개인키는 현재 사용자의 **Windows DPAPI**로 보호하여 저장합니다. OpenSSL에 필요한 임시 개인키 파일도 매번 임의 암호로 암호화하며 로드 직후 제거합니다.
- 런타임에서 외부 서버·텔레메트리·클라우드·웹/API·원격 명령 실행·원격 제어를 사용하지 않습니다. 일반 클립보드 내용을 디스크 기록으로 보관하거나 로그에 쓰지 않습니다. 런타임 디스크 로그 기능 자체가 없습니다.
- 수신 항목에는 Windows 클립보드 기록·클라우드 제외 형식도 등록합니다. 기존 원본 앱, Windows 자체 설정, Deskflow 등 다른 프로그램의 클립보드 처리는 그 프로그램의 설정에 따릅니다.
- 패킷 길이, 형식 allowlist, 합산 크기, 이미지 치수, 파일 개수/합계/청크 위치/해시를 검사합니다. 파일 전체 SHA-256 검증 후에만 클립보드에 등록합니다.
- 절대 경로, `..`, ADS `:`, Windows 예약 이름, 대소문자 이름 충돌, 디렉터리 위장, 심볼릭 링크/정션/재분석 지점, UNC/네트워크 원본은 차단합니다. 로컬 일반 파일·폴더만 지원합니다. 경로/권한/변경된 원본 오류는 해당 전송을 실패 처리합니다.
- 파일은 `%LOCALAPPDATA%\ClipBridge\transfers\<임의 UUID>`에 필요한 기간 동안 저장합니다. 완료된 최근 수신 묶음 1개와 진행 중 수신 묶음 1개가 남을 수 있습니다. 다음 파일 묶음 적용 후 이전 묶음을 삭제하고 정상 종료 시 모두 삭제합니다. 비정상 종료 잔여물은 다음 실행에서 정리합니다. **파일 데이터는 전송을 위해 디스크에 존재하며, 파일 기록 보관 기능은 없습니다.**
- 종료 전에 탐색기 등에 붙여넣어 최종 위치로 복사하세요. 파일 목록만 받은 상태에서 종료하면 수신 임시 파일이 삭제되고, 현재 프로그램이 소유한 파일 클립보드도 비웁니다. 탐색기의 긴 붙여넣기가 진행 중이라면 완료 후 종료/다음 파일 수신을 진행하세요.
- 파일 잘라내기는 안전하게 **복사**로 변환합니다. 원본 파일을 삭제하거나 원격에서 실행하지 않습니다. 수신한 실행 파일도 자동 실행하지 않습니다.

## 빌드·개발

테스트/빌드 기준: Windows 11 x64, Python **3.13.5**. 소스는 Python 3.12+를 대상으로 작성했지만 3.12 환경 자체는 미검증입니다. 서버 PC에서는 Qt 트레이와 사용자 클립보드를 사용할 수 있는 GUI 로그인 세션이 필요합니다. Windows Server Core 및 Windows Server 버전별 호환성은 미검증입니다.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
.\build.ps1
```

`build.ps1`은 의존성 설치, pytest, 아이콘 생성, PyInstaller onefile/windowed 빌드를 진행합니다. 테스트 실패 시 빌드를 중단합니다. `tools/build_exe.py`는 DLL 검색 경로를 분리하여 빌드 PC의 다른 도구가 가진 ICU/Qt DLL이 잘못 포함되지 않도록 합니다. 이미 검사한 개발 빌드는 `-SkipTests`를 사용할 수 있습니다. 같은 버전 재현에는 `requirements-lock.txt`를 사용할 수 있습니다. 실행 파일은 자체 코드 서명 인증서로 서명하지 않았습니다. 배포 서명이 필요한 환경에서는 사용자의 코드 서명 절차를 추가하세요.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools\ui_smoke.py
.\.venv\Scripts\python.exe tools\exe_smoke.py
.\.venv\Scripts\python.exe tools\exe_integration.py
```

테스트는 로컬 Windows 클립보드를 일시 변경하고 저장 가능한 지원 형식을 복구합니다. HKCU 자동 실행 테스트도 원래 등록 값을 복구합니다. 패키지 smoke test는 임시 AppData에서 실행합니다. 자동 테스트는 LAN의 실제 다른 PC나 Moonlight 화면을 사용하지 않습니다.

주요 파일: `clipbridge/clipboard.py`(Win32 클립보드), `network.py`(TLS/프로토콜), `security.py`(DPAPI/페어링), `files.py`(검증/실제 파일 전송), `model.py`(논리 시계/데이터), `ui.py`(트레이/한국어 UI), `config.py`(AppData/자동 실행), `main.py`(진입/단일 인스턴스), `bootstrap.py`(EXE 시작 오류 처리).

## 테스트 결과 — 2026-10-13

자동 테스트 **47개 통과**. 네이티브 Windows 클립보드 검사와 동일 PC 안의 두 독립 엔진을 사용하는 loopback TLS 검사를 수행했습니다. 한국어 설정 창의 렌더링·정상 종료도 확인했습니다. 아래 표의 **미검증**은 성공으로 주장하지 않습니다.

최종 **PyInstaller EXE 자체**도 임시 AppData에서 실행했습니다. 시작·트레이·네이티브 감시·정상 종료 검사가 통과했고, 독립 TLS 상대 엔진과 연결하여 실제 Windows 클립보드의 Unicode 양방향 전송, PNG/DIB/DIBV5+HTML/RTF 등록, 실제 파일 내용 수신과 CF_HDROP 등록, 되돌림 루프 방지 및 종료 후 임시 파일 삭제까지 통과했습니다. 텍스트 수신 1회 측정은 loopback에서 약 **28 ms**였습니다. 이 값은 LAN/Tailscale 성능 보장이 아닙니다.

| 요청된 테스트 | 현재 결과 |
|---|---|
| 1. Main → newserver 텍스트 | 로컬 TLS 엔진 송수신 및 실제 Windows Unicode 클립보드 쓰기/읽기 통과. **실제 PC 두 대 붙여넣기 미검증** |
| 2. newserver → Main 텍스트 | 로컬 TLS 역방향 통과. **실제 PC 두 대 붙여넣기 미검증** |
| 3. PicPick 캡처 | PNG/DIB/DIBV5·Bitmap 변환 자동 검사 통과. **PicPick 직접 캡처 미검증** |
| 4. Windows 캡처 도구 | 이미지 형식 검사 통과. **캡처 도구 직접 사용 미검증** |
| 5. 브라우저 이미지 | PNG/DIB 왕복 통과. **브라우저 메뉴에서 복사·다른 앱 붙여넣기 미검증** |
| 6. Word/브라우저 HTML | HTML/RTF 동시 전송과 원본 바이트 클립보드 등록 통과. **Word/브라우저 실제 서식 붙여넣기 미검증** |
| 7. Excel 표 | 공개 텍스트/HTML/RTF 처리 구현. **Excel, SYLK/DIF 및 원본 서식 호환성 미검증** |
| 8. 탐색기 파일 | CF_HDROP 감지·등록과 실제 파일 내용 전송·SHA-256 검증 통과. **탐색기 Ctrl+C/Ctrl+V 조작 미검증** |
| 9. 여러 파일 | 두 파일/폴더, 빈 폴더/파일, 한글 이름, 분할 전송 내용 비교 통과. **실제 두 PC 탐색기 붙여넣기 미검증** |
| 10. 네트워크 끊김·재연결 | 로컬 서버 정지/재시작 후 자동 재연결 및 오프라인 내용 미재전송 통과. **LAN/Tailscale 실제 단절 미검증** |
| 11. 동시 변경 | 논리 시계 tie-break 및 로컬 TLS 동시 복사 10회 수렴 통과 |
| 12. 중복 루프 | 실제 Windows 수신 마커 적용 후 재송신 이벤트 없음 통과. 중간 수신 후 같은 텍스트 재복사도 통과 |
| 13. 자동 시작 | 실제 HKCU Run 등록·삭제·기존 값 복원 통과. **로그아웃/로그인 후 EXE 실행 미검증** |
| 14. Moonlight Ctrl+V | **미검증**. Sunshine이 공유하는 newserver의 로그인 세션에서 최종 확인 필요 |

추가 통과: 공인 IP 차단, 경로 traversal/ADS/예약 이름/충돌 차단, 용량·청크·해시 검사, 인증서 핀/잘못된 공유 키/미승인 장치 차단, DPAPI 저장·재로드, 클립보드 점유 재시도, 새 로컬 복사 보호, 파일 수신 거부, 일시 중지·단방향 제한, 파일 전송 중 새 텍스트 우선 처리, 연결 코드 미동기화.

## 실제 PC 두 대에서 최종 확인

양쪽 연결 완료 후 한글·이모지 텍스트를 각 방향으로 복사/붙여넣습니다. PicPick 및 캡처 도구의 작은 캡처, 브라우저 이미지, Word의 굵은 글씨/표, Excel의 작은 표, 탐색기의 단일·복수 파일/폴더를 순서대로 시험하세요. 송신 완료와 수신 완료를 확인하고 파일 원본/붙여넣은 파일의 `Get-FileHash -Algorithm SHA256` 결과를 비교할 수 있습니다.

이후 연결을 끊고 양쪽에서 다른 내용을 복사한 뒤 연결합니다. 기존 내용이 유지되는지, 연결 후 **새 복사**는 전달되는지 확인하세요. 거의 동시에 양쪽에서 복사하여 둘 중 한 항목으로 수렴하는지도 확인합니다. 마지막으로 newserver가 보이는 Moonlight 화면에서 Ctrl+V, 자동 시작 설정 후 Windows 재로그인을 시험하면 요청한 14개 실사용 항목을 마무리할 수 있습니다.

## 문제 해결

- 연결 대기/끊김: 역할, 상대 IP, 동일 포트, Main Private TCP 방화벽, Tailscale ACL, 어댑터 프로필, 같은 포트를 사용하는 다른 프로세스를 확인합니다.
- 인증 오류: 기존 코드를 재사용하지 말고 Main의 `신뢰 초기화` 후 새 코드를 등록하고 다시 승인합니다. 재설치로 장치 ID가 바뀌어도 재페어링합니다.
- 일부 형식 없음: 지원 표와 합산 용량을 확인하고 원본 앱을 실행한 상태에서 다시 복사합니다. 일부 앱은 HTML이나 이미지를 지연 제공합니다.
- 붙여넣기 안 됨: 새 복사를 했는지, 수신 완료인지, 대상 앱과 ClipBridge가 동일한 Windows 로그인 세션인지 확인합니다. 다른 클립보드 동기화 프로그램이 서로 다른 내용을 다시 쓰는 경우 해당 프로그램의 클립보드 공유 옵션을 점검합니다.
- AppData/DPAPI 오류: 다른 PC의 `settings.json`을 복사하지 마세요. DPAPI는 사용자/PC에 묶입니다. 종료 후 자신의 설정을 별도 백업/제거하여 새 설정을 만들고 재페어링할 수 있습니다.
- 클립보드 점유: 원본 앱을 닫거나 복사 작업을 마친 뒤 다시 복사합니다. 오류가 계속되면 설정 창의 상태 메시지에 나타난 오류 종류를 확인하세요. 민감 내용은 로그에 남기지 않습니다.
- 종료/제거: 트레이에서 종료합니다. 자동 실행을 사용했다면 체크를 끄고 저장한 뒤 EXE를 삭제합니다. 설정 삭제가 필요하면 자신의 `%LOCALAPPDATA%\ClipBridge` 폴더를 제거합니다. 방화벽 규칙은 관리자 PowerShell의 `Remove-NetFirewallRule -Name ClipBridge-v1-Private`로 제거할 수 있습니다.

## 구현 참고 문서

- [Microsoft: AddClipboardFormatListener](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-addclipboardformatlistener)
- [Microsoft: 표준 클립보드 형식](https://learn.microsoft.com/en-us/windows/win32/dataxchg/standard-clipboard-formats)
- [Microsoft: HTML 클립보드 형식](https://learn.microsoft.com/en-us/windows/win32/dataxchg/html-clipboard-format)
- [Python: asyncio streams](https://docs.python.org/3/library/asyncio-stream.html)

외부 문서는 설계·개발 참고 자료이며 배포 프로그램의 런타임 접속 대상이 아닙니다.
