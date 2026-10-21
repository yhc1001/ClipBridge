# v1.5.0 Windows 두 버전 검증 — 2026-10-21

Windows 일반 EXE/포터블과 UAC 지원 MSI를 제공하며, Mac·Linux 배포본은 v1.4.0을 유지합니다. 사용 중인 Main PC의 ClipBridge·Deskflow를 종료·교체하거나 이 PC에 서비스를 설치하지 않았습니다.

## 확인된 자동 검사

[Windows 설치·입력·복구 통합 검사](https://github.com/yhc1001/ClipBridge/actions/runs/39549341687)에서 다음을 통과했습니다. Deskflow가 설치되지 않은 Windows Server 2022 x64 / Python 3.13.16 환경입니다. 배포 실행 파일의 소스는 `264186ab02e8f4f9a6172a0a984c2c7cd0e66e6b`이며 이후에는 문서·배포 검사 도구만 보완했습니다.

| 검사 | 결과 |
|---|---|
| 클립보드·TLS·다중 연결·용량·서비스 정책·native IPC 등 | 92 통과, 다른 OS 모듈 2 제외 |
| 일반 EXE: 새 설정·이전 설정으로 시작, 네이티브 클립보드 감시·트레이·정상 종료 | 통과 |
| 일반 EXE 안의 입력 core·DLL 실행, 전용 인증 프로필 생성·삭제 | 통과 |
| MSI 실제 설치, 사용자 SID 등록, SCM 서비스 이미지·계정과 로컬 pipe 서버 대조 | 통과 |
| 서비스 입력 core의 SYSTEM SID·활성 콘솔 세션·UIAccess 토큰 | 통과 |
| 실제 TLS 상호 인증 후 SYSTEM/Administrators 전용 데스크톱의 테스트 창에 마우스 이동·클릭·키 입력 | 통과 |
| 허용하지 않은 실행 명령 요청 거부 | 통과 |
| 입력 core 강제 종료 후 자동 재시도·TLS 재연결 | 통과 |
| 서비스 강제 종료 후 SCM 자동 재시작·저장된 인증서로 TLS 재연결 | 통과 |
| 명시적 정지 시 입력 프로세스 종료 | 통과 |
| Windows 종료용 suspend 이후 서비스 재시작 시 enabled 유지·재연결 | 통과 |
| 명시적 stop 이후 서비스 재시작 시 비활성 상태 유지 | 통과 |
| 실제 방화벽 COM 규칙 등록·프로그램 경로/포트/Private/LAN·Tailscale 제한·정지 시 삭제 | 통과 |
| MSI 제거 시 서비스·설치 등록 제거 | 통과 |

별도 이름의 실제 로컬 pipe를 사용해 서비스 framing·요청 거부·대기 중 정지, native core 제어 handshake·연결 상태·정지 명령·SYSTEM/Admin 전용 ACL도 검사했습니다. 이 로컬 검사는 실제 입력 엔진·후크·사용자 클립보드를 실행하지 않습니다.

다운로드 후 앱을 실행하지 않는 정적 검사로 EXE·MSI의 v1.5.0 버전, 내장 엔진 파일 해시, 고정 Program Files 설치 위치, 자동 시작 LocalSystem 서비스 등록, 소스/포터블에 개인 설정·키·로그가 없는 것과 SHA-256 목록을 확인합니다. MSI에 포함한 문서는 빌드 시점의 스냅샷이며 최종 검증 결과는 이 문서와 소스 ZIP에 기록합니다.

## 해석 범위

보안 데스크톱 검사는 **별도로 생성한 SYSTEM/Administrators 전용 Windows desktop**에 테스트 창을 만들고 실제 네이티브 입력을 보낸 결과입니다. 검사가 끝나면 원래 desktop으로 복귀합니다. 실제 UAC 승인 창을 열거나 승인 버튼을 자동으로 누르지 않았습니다. UAC·보안 데스크톱 정책도 변경하지 않았습니다.

실제 UAC 승인 창·잠금/로그인 화면, Main/newserver 실물 재부팅 후 연결, RDP·다중 로그인 세션, 실물 Windows 11의 DPI·키보드 언어 조합은 **미검증**입니다. 서비스 재시작은 실제 PC 전원 재시작 검사와 구분합니다. Ctrl+Alt+Del 같은 보안 주의 시퀀스 전송은 보장하지 않습니다.

클립보드의 PicPick·캡처 도구·브라우저·Word·Excel·파일 관리자·Moonlight 실물 앱 붙여넣기는 이전과 마찬가지로 별도 확인이 필요합니다. 최대 용량·16대 최대 부하는 미검증입니다. Windows 전용 서비스 변경이며 Mac/Linux v1.4.0의 검증 범위는 [이전 기록](VALIDATION-v1.4.md)을 따릅니다.

[설치형 사용법](WINDOWS_UAC.md) · [보안 구조](WINDOWS_UAC_DESIGN.md) · [기계 판독 기록](../artifacts/verification-v1.5.0.json)
