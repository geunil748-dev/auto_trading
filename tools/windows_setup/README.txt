auto_trading Windows 세팅 가이드
================================

이 폴더는 새 Windows PC, 안 쓰는 노트북, AWS Windows 서버에서
auto_trading을 바로 세팅하기 위한 스크립트 모음입니다.


파일 설명
---------

setup_windows.ps1
  최초 세팅용 스크립트입니다.
  .env 생성, .venv 가상환경 생성, 패키지 설치, DB 초기화,
  작업 스케줄러 등록, 서비스 즉시 시작까지 처리할 수 있습니다.

register_windows_tasks.ps1
  작업 스케줄러 등록만 따로 처리하는 스크립트입니다.
  아래 2개 작업을 등록합니다.
  - AutoTrading-Monitor
  - AutoTrading-Scheduler


실행 전 준비
------------

1. Git 설치
2. Python 3.11 이상 설치
3. GitHub에서 소스 내려받기

   git clone https://github.com/geunil748-dev/auto_trading.git C:\auto_trading
   cd C:\auto_trading


1. 기본 세팅
------------

아래 명령을 한 번 실행합니다.

   powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup\setup_windows.ps1

이 명령은 다음 작업을 합니다.

  - .env.example을 복사해서 .env 생성
  - .venv Python 가상환경 생성
  - 필요한 Python 패키지 설치

실행 후 메모장으로 .env 파일을 열고 아래 정보를 입력합니다.

  - MSSQL 접속 정보
  - 한국투자증권 모의투자 APP Key / Secret
  - 모의투자 계좌번호
  - MONITOR_BEARER_TOKEN


2. DB 초기화
------------

.env 입력을 끝낸 뒤 DB 테이블을 준비하려면 아래 명령을 실행합니다.

   powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup\setup_windows.ps1 -SkipInstall -InitDb


3. 일반 PC/노트북에서 자동 실행 등록
------------------------------------

Windows 로그인 시 자동으로 모니터와 자동매매 스케줄러가 실행되게 하려면
아래 명령을 실행합니다.

   powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup\setup_windows.ps1 -SkipInstall -RegisterTasks -ReplaceTasks -StartNow

이 방식은 현재 사용자 로그인 후 자동 실행됩니다.


4. AWS Windows 서버에서 자동 실행 등록
-------------------------------------

AWS Windows 서버에서 로그인 없이 부팅 시 자동 실행되게 하려면
PowerShell을 관리자 권한으로 열고 아래 명령을 실행합니다.

   powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup\setup_windows.ps1 -SkipInstall -RegisterTasks -RunAs System -ReplaceTasks -StartNow

이 방식은 SYSTEM 계정으로 등록됩니다.


5. 접속 주소
------------

서비스가 실행되면 브라우저에서 아래 주소로 접속합니다.

   http://127.0.0.1:4174/

같은 Wi-Fi의 휴대폰이나 다른 PC에서 접속하려면 127.0.0.1 대신
자동매매 PC의 내부 IP를 사용합니다.

예:

   http://192.168.0.7:4174/


중요 주의사항
-------------

- .env, 토큰 파일, logs, .venv는 GitHub에 올리면 안 됩니다.
- 자동매매 중에는 절전모드를 꺼야 합니다.
- 화면이 꺼지는 것은 괜찮지만 PC가 잠들면 자동매매도 멈춥니다.
- AWS에서 외부 접속을 허용하려면 Windows 방화벽과 AWS 보안 그룹을 확인해야 합니다.
- 실투자 주문은 별도 안전장치가 켜져 있어야 하며, 모의투자 검증 전에는 열지 않는 것을 권장합니다.
