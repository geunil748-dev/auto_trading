# Real Trading Separation

현재 단계의 원칙은 "전략은 하나, 실행기는 둘"입니다.

- `mock-*`, `dry-run-live`, `poll-exits-live`, `run-scheduler`는 항상 모의투자 경로입니다.
- `real-*` 명령은 실투자 설정/계좌 read-only 또는 skeleton 경로입니다.
- `APP_MODE=real`만으로 기존 mock 명령이 실주문으로 바뀌지 않습니다.
- 실제 KIS real order API 호출은 이번 단계에서 기본 비활성입니다.
- `real-preflight`는 주문 없이 실투자 설정, unlock 상태, token 환경,
  DB 연결 가능 여부, 상태파일 격리를 JSON으로 점검합니다.

실투자 주문 가능 조건은 모두 만족해야 합니다.

- `APP_MODE=real`
- `REAL_TRADING_ENABLED=true`
- `REAL_EMERGENCY_STOP=false`
- runtime/manual unlock=true
- 주문 한도 통과
- 주문 보호 통과
- `REAL_ORDER_EXECUTION_ENABLED=true`
- 자동 scheduler에서는 추가로 `REAL_AUTO_TRADING_ENABLED=true`

현재 단계:

1. `real-preflight`, `real-account`, `real-dry-run-live`: read-only 확인.
2. `real-buy-live`, `real-sell-exits-live`: 주문 계획 확인 후 차단.
3. `run-real-scheduler`: read-only skeleton, 주문 단계 스킵.

실투자 WebSocket은 `KisRealWebSocketClient` skeleton만 준비되어 있으며,
자동매매에는 아직 연결되어 있지 않습니다.

상태파일과 heartbeat는 mock과 real을 분리합니다.

- mock state: `monitor/state.json`
- real state: `monitor/real_state.json`
- mock scheduler heartbeat: `monitor/scheduler_heartbeat.json`
- real scheduler heartbeat: `monitor/real_scheduler_heartbeat.json`

`real-dry-run-live`는 기본적으로 `monitor/real_state.json`에만 계획 상태를
쓰며, repository는 no-op read-only 구현을 사용합니다. 따라서 현재 단계에서
후보/점수/거래 rows를 운영 DB에 쓰지 않습니다. DB write가 필요해지는 경우는
향후 `--write-db` 같은 명시 옵션과 별도 검증 작업으로 분리합니다.

예시:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot real-preflight
python -m trading_bot real-preflight --check-account
python -m trading_bot real-dry-run-live
python -m trading_bot run-real-scheduler
```

`real-preflight` 출력의 `kisRealConfig.appKey`, `appSecret`, `accountNo`는
원문 값이 아니라 존재 여부 boolean입니다. 오류 메시지도 app key, secret,
계좌번호, token 값이 노출되지 않도록 redaction 처리합니다.
