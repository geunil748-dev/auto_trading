# Algo_Trading

주식 자동 매도/매수 모의투자 시스템입니다.

## 빠른 시작: Windows 로컬 서버

새 Windows PC나 로컬 서버 노트북에서 저장소를 받은 뒤 아래 순서로 진행합니다.
민감정보가 들어가는 `.env`는 GitHub에 올리지 않고 서버마다 직접 만듭니다.

```powershell
git clone https://github.com/geunil748-dev/auto_trading.git C:\auto_trading
cd C:\auto_trading
.\tools\windows_setup_scheduler\setup_windows.ps1
```

위 명령은 `.env.example`을 `.env`로 복사하고, `.venv` 가상환경을 만든 뒤
필요한 Python 패키지를 설치합니다. 그 다음 `.env`에 MSSQL, KIS 모의투자,
모니터 토큰 값을 입력합니다.

DB 테이블까지 초기화하려면 `.env` 입력 후 아래 명령을 실행합니다.

```powershell
.\tools\windows_setup_scheduler\setup_windows.ps1 -SkipInstall -InitDb
```

로그인 시 자동 실행까지 등록하려면 일반 PC에서는 현재 사용자 방식으로 등록합니다.

```powershell
.\tools\windows_setup_scheduler\setup_windows.ps1 -SkipInstall -RegisterTasks -ReplaceTasks -StartNow
```

자세한 실행 순서는 [tools/windows_setup_scheduler/README.txt](tools/windows_setup_scheduler/README.txt)에도
별도로 정리되어 있습니다.

자동 실행 작업은 두 개입니다.

- `AutoTrading-Monitor`: `http://서버주소:4174/` 모니터 서버
- `AutoTrading-Scheduler`: 종목 수집, 매수/매도 판단, 장중 감시 스케줄러

로컬 PC나 노트북에서 운영할 때는 장중 절전모드가 들어가지 않도록 전원 설정을
꺼두어야 합니다.

For a Windows 11 Home notebook running as a local 24-hour server, see
[docs/local_windows_server.md](docs/local_windows_server.md).

For automatic server updates from `origin/main`, see
[docs/auto_update.md](docs/auto_update.md).

For sharing one KIS access token across the real and test servers, see
[docs/kis_token_cache.md](docs/kis_token_cache.md).

For DB preflight/init/repair command boundaries, see
[docs/db_migration_repair.md](docs/db_migration_repair.md).

## Telegram Alerts

운영 텔레그램 알림은 `ALERT_TELEGRAM_BOT_TOKEN`과
`ALERT_TELEGRAM_CHAT_ID`를 우선 사용합니다. 장마감 완료 안내와 장마감
체결/보유 요약 리포트는 같은 `ALERT_TELEGRAM_*` 설정을 사용합니다.

기존 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`는 하위 호환 fallback입니다.
`ALERT_TELEGRAM_*`가 일부만 설정되어 있고 기존 `TELEGRAM_*`가 완전하면
legacy fallback을 사용하며, 실제 토큰과 chat id 값은 로그에 남기지 않습니다.
새 운영 서버 설정은 `ALERT_TELEGRAM_*`에만 값을 넣고, 실제 토큰과 chat id는
`.env`에만 저장합니다. 토큰, chat id, API key, 계좌번호, DB 접속정보는
커밋하지 않습니다.

## Trading Bot Phase 2

This repository starts the mock-trading foundation described in the planning
document. It keeps trading rules separate from KIS, Yahoo Finance, and MSSQL
integration code so the same rules can be reused when REST polling is replaced
with live WebSocket prices.

## Included

- Priority-ordered global risk gates for market and FX volatility
- Defensive candidate filters for price range and opening gaps
- Ranking intersection and opening-volume screening
- News and chart score selection with score-based position sizing
- Price-bar chart pattern scoring for moving averages, RSI, MACD, and
  Bollinger behavior
- Volatility breakout trigger helpers
- Buy-intent planning that combines breakout checks, score sizing, cash, and
  exposure limits before an order adapter is called
- Exit-intent planning for stop-loss, trailing-stop, and end-of-day closes
- Trailing stop, hard stop, account loss stop, and exposure checks
- A screening/scoring pipeline with testable ports for market data and accounts
- A Yahoo-ready scoring adapter with request delay and retry policy hooks
- KIS JSON/token client helpers for overseas price-fluctuation, trade-volume,
  quote, daily-price, overseas balance, and limit-order endpoints
- Yahoo Finance recent-news title source with a 24-hour and five-item cap
- Yahoo headline sentiment source with a replaceable classifier boundary
- KIS screening market-data mapper for ranking ranks, quotes, and 20-session
  volume averages
- Yahoo Finance Nasdaq MA20 and USD/KRW daily-change market context source
- SQL Server daily target, scoring, and bot log repository writes
- MSSQL schema for screening, scoring, trades, and bot logs

## Run tests

```powershell
python -m pytest
```

KIS clients and Yahoo Finance fetchers should implement the protocols in
`trading_bot.ports`. The current SQL Server repository accepts a DB-API-style
connection factory, so credentials can stay in `.env` and the connection
library can be chosen at deployment time.

## CLI

Inspect resolved strategy settings:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot show-settings
```

Runtime mode defaults to mock-investment operation:

```powershell
APP_MODE=test
```

`APP_MODE=real` is required before real KIS settings can be loaded. Real
order-capable paths still remain locked unless `REAL_TRADING_ENABLED=true`,
`REAL_EMERGENCY_STOP=false`, and the runtime manual unlock are all satisfied.

Create missing SQL Server tables after setting `MSSQL_DSN`:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot init-db
```

Run explicit schema repair only when a preflight or release note requires it:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot repair-db-schema
```

Check mock-trading readiness before a live session. This command is read-only
and does not repair or migrate MSSQL schema:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot preflight
python -m trading_bot preflight --us-date 2026-05-26
```

Fetch KIS Nasdaq ranking rows after filling `.env`:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot kis-rankings --exchange NAS --limit 20
```

Inspect mapped KIS mock-account state:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot kis-account
```

Inspect mapped KIS real-account state without submitting orders after setting
`APP_MODE=real` and `KIS_REAL_*` values:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot kis-account --real
```

Run live-data screening/scoring as a dry run with no order submission and update
the monitor JSON:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot dry-run-live --monitor-state monitor/state.json
```

Submit the same planned orders to KIS mock trading explicitly:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot mock-buy-live --monitor-state monitor/state.json
```

Collect a small list from KIS trade-volume rankings and submit up to three
1%-allocation mock buys without bypassing price or account exposure limits:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot mock-buy-list --limit 3
```

Run the KST daily APScheduler timeline after installing the integrations extra:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot run-scheduler --monitor-state monitor/state.json
```

For a Windows logon task, point PowerShell at
`tools/start_scheduler.ps1`; the script sets the workspace and `PYTHONPATH`
before starting the same scheduler command.

The scheduler prepares the KIS token at 09:00, runs screening/scoring every
minute from 22:35 to 22:40, submits mock buys at 22:45 KST, and refreshes
order/fill/holding monitor state at 22:50. During the regular U.S. session it
polls holdings each minute for stop-loss and trailing-stop mock sells, then
re-runs screening/scoring every 15 minutes for constrained additional mock
entries. By default each intraday entry recheck may submit one ticker and at
most two such rounds per day. Existing
holdings are skipped unless the ticker is selected again, still passes the
breakout entry check, has no unfilled order, and is at least 3% above its
average entry price. Tickers already submitted by the scheduler are skipped for
new entries, and add-on buys are limited to once per ticker per day. Tune those
limits with `MAX_INTRADAY_BUY_INTENTS_PER_ROUND`,
`MAX_INTRADAY_ENTRY_ROUNDS`, and `MIN_PYRAMIDING_PROFIT_RATE`. The close job
cancels unfilled mock orders at 15:55 America/New_York, then submits end-of-day
mock sell orders for remaining KIS mock holdings at 16:00 America/New_York so
daylight-saving changes do not shift the market close. The close job writes a
daily JSON report under `monitor/reports/`. Trading jobs skip U.S. weekends and
the included 2026 Nasdaq holiday set. Screening also writes filter-rejection
summaries to the daily repository log.

Serve the monitor and optional bearer-protected `/api/state` endpoint. When
MSSQL settings are present, the endpoint reads dashboard rows from SQL Server:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot serve-monitor --port 8000
```

Refresh `monitor/state.json` from today's KIS mock orders, fills, and holdings:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot refresh-monitor-live --monitor-state monitor/state.json
```

Poll KIS mock holdings once and inspect stop/trailing sell intents:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot poll-exits-live
```

Submit those exit intents to KIS mock trading explicitly:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot mock-sell-exits-live
```

The KIS screening mapper combines official `price-fluct`, `trade-vol`, `price`,
and `dailyprice` responses into pipeline candidates. The default Yahoo market
context source calculates the Nasdaq 20-session average and USD/KRW daily
change from history closes; callable context inputs remain available for another
verified source.

Candidate collection reads `GAINER_RANKING_LIMIT` and `TURNOVER_RANKING_LIMIT`
from settings. KIS overseas ranking responses currently return up to 100 rows,
so both defaults are 100. Raising the setting above 100 does not expand the
currently verified API response beyond 100 rows. `TURNOVER_RANKING_LIMIT` is
used for the KIS `trade-vol` trade-volume ranking limit, not the `trade-pbmn`
trade-value ranking.

The screening universe is the union of price-fluctuation, trade-volume, and
trade-value rankings. After rank fallback sorting, expensive quote and daily
price evaluation runs in batches: `INITIAL_RANKED_EVALUATION_LIMIT` candidates
first, then `RANKED_EVALUATION_BATCH_SIZE` more until
`TARGET_FILTERED_CANDIDATES` pass filters, `MAX_RANKED_EVALUATION_CANDIDATES`
is reached, or `CANDIDATE_EVAL_TIMEOUT_SECONDS` is exceeded. The final selected
candidate cap remains `MAX_SELECTED_CANDIDATES`.

Candidate evaluation count settings must be positive, and
`INITIAL_RANKED_EVALUATION_LIMIT` must not exceed
`MAX_RANKED_EVALUATION_CANDIDATES`. If one ranking source fails, the pipeline
logs `RANKING_FETCH_FAILED` and continues with the remaining ranking candidates.
Pipeline logs include the union size, evaluated count, quote/daily request
counts, snapshot failures, elapsed time, and the stopped reason so operators can
see whether evaluation stopped by target, max candidate limit, timeout, or
candidate exhaustion.

## 운영 기능 요약

현재 운영 흐름은 KIS 모의투자 기반 후보 수집, 후보 평가, 모의 주문,
체결/보유 동기화, 일일 요약 저장, 모니터 화면 표시로 구성됩니다. 실투자
주문은 `APP_MODE=real`, `REAL_TRADING_ENABLED=true`,
`REAL_EMERGENCY_STOP=false`, 별도 런타임 잠금 해제가 모두 만족되기 전에는
열리지 않도록 설계되어 있습니다.

### 후보 수집과 후보 평가

스케줄러는 KIS 해외주식 상승률, 거래량, 거래대금 랭킹을 읽어 후보군을
만듭니다. 이후 가격, 시가 갭, 거래량 비율, 장초반 등락률, 점수 기준을
통과한 종목만 최종 후보가 됩니다. 평가 과정에서 매수까지 가지 않은 종목도
`candidate_evaluations`에 저장되어, 왜 주문이 제출되지 않았는지 나중에
확인할 수 있습니다.

주요 판단 컬럼은 다음과 같습니다.

- `buy_allowed`: 매수 판단까지 허용됐는지 여부
- `order_submitted`: 실제 주문 제출까지 이어졌는지 여부
- `buy_block_reason`: 매수 차단 또는 미제출 사유
- `condition_result_json`: 과열, 5분봉, 거래량 증가, VWAP/장중 20선,
  눌림 후 재돌파 등 조건별 평가 결과

최근 기본 운용 기준은 매수 과열 상한 15%, 돌파 유지 시간 1분입니다. 5분봉
종가 돌파와 5분 거래량 증가 조건은 점수 감산 방식으로 사용할 수 있고,
과열 상한은 하드 필터로 동작합니다.

### VWAP/장중 20선 조건 상태

VWAP/장중 20선 조건은 UI, 설정 저장, 후보 평가, 로그/DB 저장 구조가
준비되어 있습니다. 다만 현재 라이브 KIS 매수 판단 입력은 현재가, 시가,
전일 고가/저가를 중심으로 만들어지며 `BreakoutInput.vwap_usd`와
`BreakoutInput.intraday_ma20_usd`를 채우는 실시간 데이터 공급은 아직
연결되어 있지 않습니다.

따라서 VWAP/장중 20선 조건을 켜더라도 데이터가 없으면
`SKIPPED_NO_DATA`로 기록되고 매수 차단 조건으로 작동하지 않습니다. 실제
필터로 쓰려면 KIS 또는 다른 데이터 소스에서 장중 분봉을 가져와 VWAP와
장중 20선을 계산한 뒤 `BreakoutInput`에 넣는 구현이 필요합니다.

### 주문, 체결, 보유 저장

모니터/스케줄러의 라이브 스냅샷 저장은 주문, 체결, 보유, 계좌 상태를
SQL Server에 기록합니다. 주문 스냅샷은 `order_snapshot`, 체결 이력은
`fill_history`, 매수 주문/매도 주문 기록은 `trade_history`에 저장됩니다.
매수 체결은 `entry_profit_snapshot`으로 이어져 5/10/15/20/30/60분 후
수익률과 최종 청산 사유를 분석할 수 있게 합니다.

중복 체결 저장을 피하기 위해 기존 `fill_history`를 조회한 뒤 새 체결만
저장합니다. 장마감 이후에는 `daily_run_summary`와 일일 요약 리포트를
갱신합니다.

### 일일 요약 리포트

장마감 흐름과 수동 CLI는 당일 거래 데이터를 요약해
`daily_trade_summary_report`에 저장합니다. 기준은 `trade_date + mode`이며,
같은 날짜와 모드로 다시 생성하면 중복 삽입하지 않고 업데이트합니다.

수동 생성 예시:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot generate-daily-summary --date 2026-06-05 --mode mock
```

텍스트 파일로 내보내는 CLI도 있습니다.

```powershell
$env:PYTHONPATH='src'
python -m trading_bot export-trade-summary --date 2026-06-05 --mode mock
```

요약에는 총 손익, 총 수익률, 매수/매도 체결 수, 승률, 청산 사유별 성과,
전략 버전별 성과, 진입 후 수익률 스냅샷, 후보/선정 요약, 주요 오류 로그가
포함됩니다. 민감정보인 계좌번호, KIS 토큰, API key, DB 접속정보, `.env`
내용은 포함하지 않습니다.

### 주요 DB 테이블

- `daily_target`: 당일 후보 리스트
- `listed_target_snapshot`: 후보 스냅샷
- `scoring`: 점수 계산 결과
- `candidate_evaluations`: 매수 후보별 조건 평가와 주문 제출 여부
- `trade_history`: 매수/매도 주문 기록
- `fill_history`: KIS 체결 이력
- `entry_profit_snapshot`: 매수 진입 후 수익률 추적
- `daily_run_summary`: 일 단위 실행 요약
- `daily_trade_summary_report`: 일일 거래 요약 화면/리포트
- `bot_log`: 후보, 주문, 체결, 오류, 차단 사유 로그
- `KisTokenCache`: 서버 간 공유 KIS 토큰 캐시

## Monitor

The browser monitor lives in `monitor/`. It first requests `/api/state` from
the local monitor server and falls back to `state.json` if the API is not
available.

### Operations preflight

Run this before starting or restarting monitor/scheduler. It is read-only and
does not call order APIs or write database data.

```powershell
& "C:\auto_trading\.venv\Scripts\python.exe" "C:\auto_trading\tools\preflight_check.py"
```

For startup gating, fail when monitor port 4174 is already occupied:

```powershell
& "C:\auto_trading\.venv\Scripts\python.exe" "C:\auto_trading\tools\preflight_check.py" --fail-used-port
```

Useful spot checks:

```powershell
Get-CimInstance Win32_Process -Filter "ProcessId=24440" |
Select-Object ProcessId, ExecutablePath, CommandLine |
Format-List

& "C:\auto_trading\.venv\Scripts\python.exe" -c "import sys; print(sys.executable); import clr; print('clr OK')"

& "C:\auto_trading\.venv\Scripts\python.exe" -m pip show pythonnet

curl.exe http://localhost:4174/health

curl.exe http://localhost:4174/api/state

# When MONITOR_BEARER_TOKEN is configured:
curl.exe -H "Authorization: Bearer <MONITOR_BEARER_TOKEN>" http://localhost:4174/api/state

Get-Content "C:\auto_trading\logs\startup-monitor.log" -Tail 80 |
Select-String -Pattern "ModuleNotFoundError|No module named 'clr'|Traceback"
```

Expected startup behavior:

- `tools/start_monitor_server.ps1` and `tools/start_scheduler.ps1` use
  `C:\auto_trading\.venv\Scripts\python.exe` unless `AUTO_TRADING_PYTHON` is
  set explicitly.
- Startup is blocked if required modules such as `clr`, `pyodbc`, `dotenv`, or
  scheduler dependencies are missing.
- `/health` always returns JSON over HTTP 200 and reports degraded state through
  fields such as `dependency_status`, `clr_import`, `db_connected`,
  `monitor_state_status`, `scheduler_heartbeat`, and `security_status`.
- If monitor binds to `0.0.0.0` or a LAN address, `MONITOR_BEARER_TOKEN` is
  required for `/api/*`; `/health` reports `security_status=fail` when it is
  missing.
- Do not paste the real monitor bearer token into logs, chat messages, shell
  history screenshots, or committed files. Use placeholders such as
  `<MONITOR_BEARER_TOKEN>` in documentation and reports.
- Scheduler trading cycles skip with `SKIP trading cycle: monitor degraded ...`
  when dependencies, DB connectivity, or monitor state freshness are not ready.

Monitor-only restart:

```powershell
.\tools\stop_monitor_server.ps1
.\tools\start_monitor_server.ps1
```

Use this when monitor static files or monitor server code changed and scheduler
code did not. The stop script targets the monitor launcher and
`trading_bot serve-monitor` process for port `4174`; it does not stop
`run-scheduler`.

### PowerShell UTF-8 Encoding

Windows PowerShell 5.1 can start with CP949/US-ASCII settings even though this
project stores source, JSON state, and logs as UTF-8. Before manual operations,
apply the project console bootstrap:

```powershell
. "C:\auto_trading\scripts\Set-Utf8Console.ps1"
```

The monitor and scheduler start scripts dot-source this bootstrap automatically.
On the next after-hours manual restart they set `chcp 65001`, console
input/output encoding, `$OutputEncoding`, `PYTHONUTF8=1`, and
`PYTHONIOENCODING=utf-8`. During market hours, do not restart monitor/scheduler
only to fix display encoding; wait until after close if running processes must
pick up changed start scripts.

PowerShell 5.1 reads UTF-8 no-BOM `.ps1` files inconsistently when Korean text
is embedded directly in the script. Keep operational `.ps1` files ASCII-only
where possible, and write Korean runtime text from Python, JSON, or logs with
explicit UTF-8 encoding. PowerShell 7 has better UTF-8 defaults, but still
verify the active code page and `$OutputEncoding`.

Diagnostic command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\auto_trading\scripts\check_encoding.ps1"
```

If your PowerShell execution policy allows local scripts, the shorter
`& "C:\auto_trading\scripts\check_encoding.ps1"` form is also fine.

Spot checks:

```powershell
chcp
[Console]::InputEncoding
[Console]::OutputEncoding
$OutputEncoding
& "C:\auto_trading\.venv\Scripts\python.exe" -c "import sys, locale; print(sys.stdout.encoding); print(sys.stderr.encoding); print(locale.getpreferredencoding(False)); print('한글테스트: 삼성전자 매수 성공 현재가 72,300원')"
Get-Content "C:\auto_trading\logs\startup-monitor.log" -Encoding utf8 -Tail 50
Get-Content "C:\auto_trading\logs\startup-scheduler.log" -Encoding utf8 -Tail 50
```

Python file logs and JSON state files must use `encoding="utf-8"` and
`ensure_ascii=False` when Korean user-facing text is stored. PowerShell file
writes must use `-Encoding UTF8`; avoid `>` and `>>` for Korean log files.
