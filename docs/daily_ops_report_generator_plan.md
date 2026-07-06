# Daily Operations Report Generator Plan

## Purpose

Define a docs-only implementation plan for a local Windows server job that creates a daily, read-only operations report package after market close. The package is intended for a ChatGPT Scheduled Task to review actual auto-trading operations and propose the next bounded Codex work candidates.

This plan follows `docs/data_review_excel_spec.md` and intentionally does not implement runtime code, database writes, schema changes, trading logic changes, scheduler timing changes, order logic changes, risk logic changes, monitor behavior changes, or generated report artifacts.

## Scope and risk level

- Risk level: LOW, documentation only.
- Runtime impact: none.
- Trading impact: none.
- Generated files are expected under `reports/analysis/` at runtime, but this plan does not create or commit generated output files.

## Proposed CLI command

Proposed command name:

```bash
python -m auto_trading.reports.daily_ops_report generate --trade-date YYYY-MM-DD --output-dir reports/analysis
```

Optional implementation may expose an equivalent script entry point:

```bash
auto-trading-daily-ops-report --trade-date YYYY-MM-DD --output-dir reports/analysis
```

### Inputs

Required:

- `--trade-date YYYY-MM-DD`: report date, normally the completed US market trading date.
- `--output-dir reports/analysis`: local output directory for generated artifacts.

Optional:

- `--start-date YYYY-MM-DD`: analysis window start date. If omitted, use the same default period defined by `docs/data_review_excel_spec.md` for operations review, normally recent two weeks unless the operator overrides it.
- `--end-date YYYY-MM-DD`: analysis window end date. Defaults to `--trade-date`.
- `--timezone America/New_York`: market/reporting timezone used for after-close date boundaries.
- `--db-path PATH`: local SQLite database path or local read-only database connection alias. The command must not print the raw path if it contains sensitive account or user information.
- `--dry-run`: validate date range and planned output paths without querying data or creating files.

### Outputs

For `--trade-date 2026-06-23`, the command creates exactly these report package files:

- `reports/analysis/auto_trading_review_2026-06-23.xlsx`
- `reports/analysis/daily_ops_summary_2026-06-23.md`
- `reports/analysis/daily_ops_metrics_2026-06-23.json`

The Excel workbook should follow the sheet and column contract in `docs/data_review_excel_spec.md`, including Summary, Daily Targets, Scoring, Candidate Eval, Block Reasons, Final Decisions, Fills, Fill Detail, Daily Summary, Compare, Run Summary, Snapshots, Orders, Warnings, Recent Warnings, Latest Targets, and Candidate Detail.

The Markdown summary should be concise enough for ChatGPT Scheduled Task ingestion while preserving the required final-review sections:

1. PASS / WARN / FAIL summary
2. Analysis period
3. Data coverage
4. Key profit/loss
5. Candidate -> selected -> buy_allowed -> order_submitted -> fill funnel
6. Main reasons orders were not submitted
7. Runner analysis
8. Noisy universe analysis
9. Data quality WARN items
10. Recommended next work candidates

The JSON metrics file should provide structured values for automation, trend comparison, and Slack/ChatGPT handoff.

## Safety rules

The implementation PR must preserve all of these constraints:

- Use read-only `SELECT` queries only.
- Do not execute `INSERT`, `UPDATE`, `DELETE`, `ALTER`, `DROP`, migration, vacuum, pragma write-mode, or schema mutation statements.
- Open the database in read-only mode where supported.
- Do not call KIS API.
- Do not call order API.
- Do not call Telegram API.
- Do not call Slack API.
- Do not access or print `.env`, tokens, app keys, app secrets, account numbers, database passwords, or credentials.
- Mask account numbers and sensitive identifiers if they appear in source data.
- Do not modify trading decision logic.
- Do not modify scheduler timing.
- Do not modify order submission logic.
- Do not modify risk logic.
- Do not modify monitor runtime behavior.
- Do not restart scheduler or monitor processes.
- Do not create or commit generated files under `reports/analysis/` in implementation PRs.

## File naming and retention

Runtime-generated package names must use the completed trading date:

- Excel: `auto_trading_review_YYYY-MM-DD.xlsx`
- Markdown: `daily_ops_summary_YYYY-MM-DD.md`
- JSON: `daily_ops_metrics_YYYY-MM-DD.json`

Recommended local retention policy for the Windows server:

- Keep the latest 30 daily packages locally.
- Archive older packages outside the repository if long-term retention is needed.
- Never commit generated package files.

## Proposed JSON schema

The first implementation can write schema version `1` with the following shape:

```json
{
  "schema_version": 1,
  "generated_at": "2026-06-23T21:15:00Z",
  "trade_date": "2026-06-23",
  "analysis_period": {
    "start_date": "2026-06-10",
    "end_date": "2026-06-23",
    "trading_days": ["2026-06-10", "2026-06-11", "2026-06-12", "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19", "2026-06-22", "2026-06-23"]
  },
  "data_coverage": {
    "daily_target_rows": 0,
    "scoring_rows": 0,
    "candidate_evaluations_rows": 0,
    "trade_history_rows": 0,
    "order_snapshot_rows": 0,
    "fill_history_rows": 0,
    "bot_log_rows": 0,
    "daily_run_summary_rows": 0,
    "entry_profit_snapshot_rows": 0,
    "missing_tables": [],
    "warnings": []
  },
  "profit_loss": {
    "total_realized_profit_fill_history": 0.0,
    "total_realized_profit_daily_summary": 0.0,
    "top_profit_ticker": null,
    "top_profit_amount": 0.0,
    "top_loser_ticker": null,
    "top_loser_amount": 0.0,
    "profit_without_top_ticker": 0.0,
    "win_rate": null,
    "trade_count": 0,
    "buy_count": 0,
    "sell_count": 0
  },
  "funnel": {
    "candidate_count": 0,
    "selected_count": 0,
    "buy_allowed_count": 0,
    "order_submitted_count": 0,
    "fill_count": 0,
    "blocked_count": 0,
    "selected_to_buy_allowed_rate": null,
    "buy_allowed_to_order_submitted_rate": null,
    "order_submitted_to_fill_rate": null
  },
  "block_reasons": [
    {
      "reason": "example_reason",
      "count": 0,
      "buy_allowed_count": 0,
      "order_submitted_count": 0
    }
  ],
  "runner_analysis": {
    "top_winners": [],
    "top_losers": [],
    "runner_score_top": [],
    "missed_runner_candidates": [],
    "notes": []
  },
  "noisy_universe": {
    "candidate_count": 0,
    "traded_count": 0,
    "flags": [],
    "notes": []
  },
  "data_quality": {
    "status": "PASS",
    "warning_count": 0,
    "error_count": 0,
    "daily_summary_mismatch": false,
    "missing_snapshots": false,
    "candidate_evaluations_missing": false,
    "issues": []
  },
  "recommended_codex_work": [
    {
      "priority": 1,
      "title": "Example bounded follow-up",
      "risk_level": "LOW",
      "reason": "Evidence from the daily report",
      "suggested_scope": "Docs/test/read-only reporting only"
    }
  ],
  "artifacts": {
    "excel_path": "reports/analysis/auto_trading_review_2026-06-23.xlsx",
    "summary_path": "reports/analysis/daily_ops_summary_2026-06-23.md",
    "metrics_path": "reports/analysis/daily_ops_metrics_2026-06-23.json"
  }
}
```

Notes:

- Numeric fields should use JSON numbers, not formatted strings.
- Unknown rates should be `null`, not `0`, when the denominator is zero.
- Ticker-level arrays must not include account numbers or credentials.
- If an analysis value is a proxy because intraday minute price data is unavailable, the JSON should state that explicitly in `notes` or `issues`.

## Slack upload handoff

The generator must not call Slack API directly. Instead, it writes local files and prints a sanitized completion message that the Windows operator or a separate approved uploader can use.

Example sanitized console output:

```text
Daily operations report package generated for 2026-06-23:
- reports/analysis/auto_trading_review_2026-06-23.xlsx
- reports/analysis/daily_ops_summary_2026-06-23.md
- reports/analysis/daily_ops_metrics_2026-06-23.json
Upload these files to the configured Slack thread using the approved manual or separate uploader process.
```

Slack handoff rules:

- Do not embed Slack tokens or channel credentials in generator configuration.
- Do not call Slack Web API from the generator.
- Do not print sensitive local database paths or credentials in the upload instruction.
- The handoff message may include the target Slack channel/thread label only if it is non-secret operational metadata.

## ChatGPT Scheduled Task consumption flow

1. Local Windows server runs the generator after market close and after expected trade/fill/order snapshots have landed.
2. The generator creates the Excel, Markdown, and JSON package in `reports/analysis/` using read-only database access.
3. The operator or approved upload process attaches the package to the configured Slack thread.
4. ChatGPT Scheduled Task reads `daily_ops_summary_YYYY-MM-DD.md` first for narrative context.
5. ChatGPT Scheduled Task reads `daily_ops_metrics_YYYY-MM-DD.json` for structured metrics and thresholds.
6. ChatGPT Scheduled Task may inspect `auto_trading_review_YYYY-MM-DD.xlsx` for workbook details and sheet-level evidence.
7. ChatGPT Scheduled Task proposes next Codex work candidates with risk labels.
8. Only LOW or MEDIUM bounded follow-ups should be turned into automatic Codex PR requests. HIGH risk follow-ups require explicit human approval before implementation.

If Slack contains `[AUTO_TRADING_DATA_PACKET]`, the Scheduled Task must follow the packet chunk intake rules in `docs/chatgpt_scheduled_task_prompt.md` before analysis. It must group messages by `packet_id`, sort `part: N/M`, verify all parts and `packet_complete: true`, then read `[EXECUTION_LEDGER_COMPACT]`, `[PROBLEM_CASES_FOR_CODEX]`, and `[CODEX_FIX_INPUT_HINTS]`. Reading only the latest Slack message is not sufficient when a packet is split into chunks. If `strategy_change_allowed: false` or `score_source_analysis_allowed: false`, the next work candidates must be data/logging/report fixes, not strategy parameter changes.

If Slack contains `[AUTO_TRADING_DATA_PACKET_SKIPPED]`, the Scheduled Task treats
it as a normal market-closed skip notice. It must not create a Codex prompt from
the skipped packet, and it should investigate calendar/session handling only when
the skipped date was expected to be a trading day. If neither a regular packet nor
a skipped packet is present after the expected close, investigate market-close
triggering or Slack delivery before proposing code changes.

## Follow-up implementation PR steps

1. Add a read-only reporting module and CLI entry point for `daily_ops_report generate`.
2. Add a database adapter that opens the local database in read-only mode and rejects non-SELECT SQL.
3. Reuse the workbook sheet and column definitions from `docs/data_review_excel_spec.md`.
4. Generate the Markdown summary with the required PASS / WARN / FAIL, funnel, runner, noisy-universe, and data-quality sections.
5. Generate `daily_ops_metrics_YYYY-MM-DD.json` using schema version `1`.
6. Add unit tests for date parsing, output file naming, JSON schema shape, sensitive-value masking, and SQL read-only guardrails.
7. Add fixture-based tests for workbook sheet names and required columns without using production data.
8. Add documentation for the Windows Task Scheduler command, expected runtime directory, retention policy, and manual Slack upload handoff.
9. Confirm generated `reports/analysis/` outputs remain untracked and are not committed.
10. Keep implementation PR scope read-only; defer any trading, scheduler, risk, order, KIS, Telegram, or Slack API changes to separately approved work.
