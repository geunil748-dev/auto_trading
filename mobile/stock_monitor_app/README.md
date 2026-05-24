# 모바일 모니터 앱

Flutter 기반 자동매매 모니터 앱입니다. 현재 PC의 모니터 서버
`/api/state`를 읽어서 모의투자와 실투자 계좌 상태를 보여줍니다.

## 빌드 준비

Windows에 다음 도구가 필요합니다.

- Flutter SDK
- Android Studio 또는 Android SDK
- Android SDK Build Tools

설치 후 아래 명령이 동작해야 합니다.

```powershell
flutter doctor
```

## APK 빌드

에뮬레이터에서 볼 때:

```powershell
tools/build_mobile_apk.ps1
```

실제 휴대폰에서 PC 모니터 서버를 볼 때는 PC의 같은 와이파이 IP를 넣습니다.

```powershell
tools/build_mobile_apk.ps1 "http://내_PC_IP:4174/api/state"
```

생성 파일:

```text
mobile/stock_monitor_app/build/app/outputs/flutter-apk/app-release.apk
```

앱 안에서도 상단 입력칸에서 API 주소를 바꾼 뒤 새로고침할 수 있습니다.
