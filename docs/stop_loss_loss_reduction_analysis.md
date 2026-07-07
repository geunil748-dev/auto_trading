# STOP_LOSS Loss-Reduction Analysis Framework

This checklist defines the safe review boundary for STOP_LOSS loss-reduction work.
It is analysis-only and must not change live trading behavior by itself.

## Scope

- Use fixture data, exported report rows, or already loaded in-memory rows.
- Review only completed trades whose final exit reason is `STOP_LOSS`.
- Compare STOP_LOSS losses by entry reason, candidate source, ranking mode, strategy version, early price path, spread, and opening gap.
- Treat all outputs as evidence for a later human-reviewed proposal.

## Standalone File Tool

Use `tools/analyze_stop_loss_loss_reduction.py` only with a manually supplied local JSON file that already contains exported trade rows. The tool does not connect to DB, does not read `.env`, and is not wired into `python -m trading_bot`, scheduler, monitor backend, repositories, or report exporters.

Example JSON output:

```powershell
python tools/analyze_stop_loss_loss_reduction.py `
  --input tests/fixtures/stop_loss_loss_reduction_rows.json `
  --output reports/analysis/stop_loss_loss_reduction_sample.json `
  --format json `
  --create-dirs
```

Example Markdown output:

```powershell
python tools/analyze_stop_loss_loss_reduction.py `
  --input tests/fixtures/stop_loss_loss_reduction_rows.json `
  --output reports/analysis/stop_loss_loss_reduction_sample.md `
  --format markdown `
  --create-dirs
```

The output parent directory must already exist unless `--create-dirs` is passed. Generated outputs under `reports/analysis/` are runtime analysis artifacts and must not be committed.

The tool prints only a short row/count summary. It writes the analysis payload to the requested output path and must not be used as automatic proof that stop loss, risk, order, or scheduler behavior should change.

### Safe Input Contract

The input JSON must be a list of row objects. Each row must include:

- `trade_date` or `tradeDate`
- `ticker` or `symbol`
- `final_exit_reason`, `finalExitReason`, or `exit_reason`
- `final_profit_rate`, `finalProfitRate`, or `profit_rate`

Optional context fields include `snapshots` or `snapshotProfits`, `entry_reason`, `candidate_source`, `ranking_selection_mode`, `strategy_version`, `opening_gap`, and `bid_ask_spread_rate`.

## Explicit Non-Scope

- Do not modify trading decisions, risk guards, order submission, sell/fill handling, scheduler timing, KIS code, DB schema, or monitor backend runtime.
- Do not read `.env`, credentials, tokens, account numbers, app keys, or app secrets.
- Do not call KIS, broker, order, Telegram, Slack, Yahoo, AWS, or other external APIs.
- Do not connect to DB or execute SQL from this framework.
- Do not start, stop, or restart scheduler or monitor processes.

## Input Checklist

- [ ] STOP_LOSS rows are completed sell/fill outcomes, not open positions.
- [ ] The analysis window and trade dates are stated.
- [ ] Each row has ticker, final exit reason, final profit rate, and trade date.
- [ ] Intraday snapshots are available where possible: 5m, 10m, 15m, 20m, 30m, 60m.
- [ ] Candidate source, entry reason, ranking mode, and strategy version are available or marked `unknown`.
- [ ] Spread and opening gap context is available where possible.
- [ ] Sample-size warnings are preserved when completed trades are fewer than 30.

## Review Buckets

- `profit_giveback_review`: the trade had positive run-up before ending as STOP_LOSS.
- `early_weakness_review`: the 5m or 10m snapshot was already negative.
- `liquidity_spread_review`: bid/ask spread context is wide enough to review.
- `opening_gap_review`: opening gap context is large enough to review.
- `needs_more_context`: the row lacks enough path/context data for a stronger label.

## Output Checklist

- [ ] Include `actionBoundary` showing the payload is analysis-only.
- [ ] Include row/completed/STOP_LOSS counts.
- [ ] Include total STOP_LOSS loss rate and share of completed loss rate.
- [ ] Include grouped summaries by entry reason, candidate source, ranking mode, strategy version, early path, and primary review signal.
- [ ] Include row-level details for human inspection.
- [ ] Include warnings and evidence checklist items.
- [ ] Do not include raw credentials, account numbers, tokens, app keys, or runtime cache contents.

## Follow-Up Rules

- A later PR may add a CLI or DB-backed loader only after separate approval.
- A later PR may propose trading/risk/scheduler changes only after separate HIGH-risk approval.
- This framework can support hypotheses, but it must not be used as automatic proof that a STOP_LOSS parameter should change.
