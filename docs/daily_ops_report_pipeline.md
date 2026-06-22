# Daily Operations Report Pipeline

## Purpose

The daily operations report package gives ChatGPT a safe, repeatable input for reviewing auto-trading operations without changing the trading system.

The package is read-only. It must never submit orders, call KIS, call Telegram, call Slack, alter schema, restart scheduler or monitor processes, or commit generated report files.

## Output Package

The daily package is written under `reports/analysis/` and is not committed:

```text
reports/analysis/daily_ops_YYYY-MM-DD.xlsx
reports/analysis/daily_ops_YYYY-MM-DD.md
reports/analysis/daily_ops_YYYY-MM-DD.json
```

`YYYY-MM-DD` is the KST trading date or analysis end date.

## Read-Only DB Scope

The report may use only read-only `SELECT` queries against existing operational data. It must not run:

- `INSERT`
- `UPDATE`
- `DELETE`
- `MERGE`
- `ALTER`
- `DROP`
- Stored procedures that mutate data

Sensitive values must be omitted or masked. The report must not print raw `.env` values, tokens, app keys, app secrets, account numbers, passwords, or credentials.

## Workbook Contents

The `.xlsx` workbook should include these sheets when source data exists:

- `Summary`
- `Progress`
- `Daily Targets`
- `Candidate Funnel`
- `Block Reasons`
- `Orders`
- `Fills`
- `PnL`
- `Runner Analysis`
- `Noisy Universe`
- `Warnings`
- `Data Quality`
- `Recommendations`

Missing source tables or empty date ranges should produce `WARN` rows in `Data Quality`, not runtime mutations.

## Markdown Summary Contents

The `.md` report is the human-readable daily review. It should include:

1. PASS / WARN / FAIL summary.
2. Analysis period.
3. Data coverage and row counts.
4. Daily progress percentage and delta.
5. Core profit and loss summary.
6. Candidate -> selected -> buy_allowed -> order_submitted -> fill funnel.
7. Main reasons orders did not go out.
8. Runner analysis.
9. Noisy universe analysis.
10. Data quality warnings.
11. Recommended next tasks with LOW / MEDIUM / HIGH risk labels.

## JSON Summary Contract

The `.json` report is the machine-readable source for ChatGPT progress calculation and Slack reporting.

Required top-level fields:

```json
{
  "report_date": "YYYY-MM-DD",
  "generated_at": "YYYY-MM-DDTHH:MM:SS+09:00",
  "analysis_period": {
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD",
    "timezone": "Asia/Seoul"
  },
  "status": "PASS",
  "daily_progress_percent": 0.0,
  "daily_progress_delta": null,
  "data_coverage": {},
  "pnl": {},
  "funnel": {},
  "block_reasons": [],
  "runner_analysis": {},
  "noisy_universe": {},
  "data_quality_warnings": [],
  "recommendations": []
}
```

Allowed `status` values are `PASS`, `WARN`, and `FAIL`.

## PASS / WARN / FAIL Rules

Use `PASS` when the report package is complete, data coverage is sufficient, and no critical safety or data quality issue is detected.

Use `WARN` when the package is generated but has missing non-critical tables, stale rows, partial date coverage, mismatched summaries, or unresolved operational warnings.

Use `FAIL` when the package cannot be trusted, required data is unavailable, read-only safety is violated, credentials are exposed, or a live trading/API side effect is detected.
