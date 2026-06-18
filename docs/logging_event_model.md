# Trading Event Log Model

`dbo.trading_event_log` is the append-only analytical event stream for trading
decisions and operational outcomes. It does not replace the existing tables.

## Table Roles

- `candidate_evaluations`: latest per-candidate state such as final decision and
  whether an order was submitted.
- `bot_log`: human-facing operational log used by existing monitor and report
  paths.
- `trading_event_log`: normalized event history for later analysis of why a
  ticker did or did not reach order submission, fill, exit, or notification.

## Schema Shape

Common analysis columns are first-class fields:

- time and scope: `event_time`, `trade_date`, `mode`, `app_mode`, `run_id`,
  `correlation_id`
- instrument/order: `ticker`, `ticker_name`, `side`, `order_id`, `order_no`,
  `quantity`, `price_usd`, `order_value_usd`
- classification: `stage`, `event_type`, `severity`, `decision`, `reason_code`,
  `reason_label`
- decision flags: `is_blocking`, `is_final_decision`, `order_submitted`,
  `buy_allowed`, `sell_allowed`
- analysis dimensions: `candidate_source`, `ranking_selection_mode`,
  `strategy_version`, `settings_snapshot_hash`
- flexible diagnostics: `details_json`

New reason-specific values should normally go into `details_json`. Promote a
value to a real column only when it is repeatedly used across analysis queries.

## Stage Examples

- `SCREENING`
- `SCORING`
- `ENTRY_PLANNER`
- `ORDER_PROTECTION`
- `ORDER_SUBMISSION`
- `ORDER_FILL`
- `INTRADAY_RECHECK`
- `RISK_GUARD`
- `EXIT_PLANNER`
- `SELL_EXECUTION`
- `NOTIFICATION`
- `SCHEDULER`
- `MONITOR`

## Event Type Examples

- `BUY_ALLOWED`
- `BUY_BLOCKED`
- `BUY_NOT_SUBMITTED`
- `ORDER_PROTECTION_BLOCKED`
- `ORDER_SUBMIT_SUCCEEDED`
- `ORDER_SUBMIT_FAILED`
- `ORDER_RETRY`
- `FILL_SAVED`
- `EXIT_SIGNAL`
- `SELL_ORDER_SUBMITTED`
- `CANDIDATE_LIST_TELEGRAM_SENT`
- `FILL_NOTIFICATION_SKIPPED_DUPLICATE`

## Adding A New Reject Reason

1. Keep the existing business behavior unchanged.
2. Add or reuse a stable English `reason_code`.
3. Record the event through `trading_bot.trading_event_logger`.
4. If the event blocks a buy candidate, update `candidate_evaluations` through
   `record_buy_not_submitted` when possible.
5. Keep existing `bot_log` writes when monitor or reports still depend on them.
6. Put extra values in `details_json` and never include secrets.

Example:

```python
record_buy_not_submitted(
    repository,
    ticker="AAA",
    trade_date=trade_date,
    reason_code="NO_ORDER_UNFILLED_ORDER",
    stage="INTRADAY_RECHECK",
    details={"unfilled_order_count": 1},
)
```

## Correlation

Do not add columns for every new relationship. The event logger writes a
standard `details_json.correlation` object for each event:

- `correlation_id`: primary DB column value, usually `YYYY-MM-DD:TICKER`.
- `flow_key`: stable ticker-day key, `YYYY-MM-DD:TICKER`.
- `ticker_day_key`: same stable key for simpler downstream grouping.
- `order_key`: `order_no` or `order_id` when available.
- `fill_key`: ticker/date/side/quantity/price/order key when available.
- `stage` and `event_type`: copied for easier JSON-only analysis.

This lets analysis connect candidate evaluation, no-order diagnostics, order
submission, fill, exit, and notification events without a schema change.

## Timeline API

The monitor server exposes a read-only ticker timeline endpoint:

```powershell
curl.exe "http://localhost:4174/api/trading-events/timeline?date=2026-06-17&ticker=PURR&limit=200"
```

The endpoint reads `trading_event_log` only. It does not initialize schema,
repair schema, submit orders, send Telegram messages, or restart scheduler
components.

## Sensitive Data

Do not store these values in `details_json` or messages:

- KIS app key/app secret/access token/approval key
- account number or account product code
- DB DSN, username, or password
- Telegram token or chat id
- monitor bearer token

The common logger redacts known sensitive key names, but callers should still
avoid passing secret values in the first place.

## Analysis Examples

```sql
SELECT reason_code, COUNT(*) AS event_count
FROM dbo.trading_event_log
WHERE trade_date BETWEEN '2026-06-01' AND '2026-06-17'
  AND event_type = 'BUY_NOT_SUBMITTED'
GROUP BY reason_code
ORDER BY event_count DESC;
```

```sql
SELECT ticker, reason_code, COUNT(*) AS blocking_count
FROM dbo.trading_event_log
WHERE trade_date = '2026-06-17'
  AND is_blocking = 1
GROUP BY ticker, reason_code
ORDER BY blocking_count DESC;
```
