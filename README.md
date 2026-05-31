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

Create missing SQL Server tables after setting `MSSQL_DSN`:

```powershell
$env:PYTHONPATH='src'
python -m trading_bot init-db
```

Check mock-trading readiness before a live session:

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
`KIS_REAL_*` values:

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

## Monitor

The browser monitor lives in `monitor/`. It first requests `/api/state` from
the local monitor server and falls back to `state.json` if the API is not
available.
