from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DailyOpsReportPaths:
    trade_date: date
    output_dir: Path
    summary_path: Path
    metrics_path: Path


@dataclass(frozen=True)
class DailyOpsReportResult:
    trade_date: date
    summary_path: Path
    metrics_path: Path


def daily_ops_report_paths(trade_date: date, output_dir: Path) -> DailyOpsReportPaths:
    """Return the report package paths for a daily operations report skeleton."""
    date_text = trade_date.isoformat()
    return DailyOpsReportPaths(
        trade_date=trade_date,
        output_dir=output_dir,
        summary_path=output_dir / f"daily_ops_summary_{date_text}.md",
        metrics_path=output_dir / f"daily_ops_metrics_{date_text}.json",
    )


def build_placeholder_metrics(
    *,
    trade_date: date,
    output_dir: Path,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build schema-versioned placeholder metrics without querying any data source."""
    timestamp = generated_at or datetime.now(timezone.utc)
    paths = daily_ops_report_paths(trade_date, output_dir)
    excel_path = output_dir / f"auto_trading_review_{trade_date.isoformat()}.xlsx"
    return {
        "schema_version": 1,
        "status": "PLACEHOLDER",
        "generated_at": timestamp.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "trade_date": trade_date.isoformat(),
        "analysis_period": {
            "start_date": trade_date.isoformat(),
            "end_date": trade_date.isoformat(),
            "trading_days": [trade_date.isoformat()],
            "notes": ["Skeleton only; data collection is not implemented yet."],
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
            "warnings": [
                "Placeholder report: no database connection or SELECT queries are implemented."
            ],
        },
        "profit_loss": {
            "total_realized_profit_fill_history": 0.0,
            "total_realized_profit_daily_summary": 0.0,
            "top_profit_ticker": None,
            "top_profit_amount": 0.0,
            "top_loser_ticker": None,
            "top_loser_amount": 0.0,
            "profit_without_top_ticker": 0.0,
            "win_rate": None,
            "trade_count": 0,
            "buy_count": 0,
            "sell_count": 0,
        },
        "funnel": {
            "candidate_count": 0,
            "selected_count": 0,
            "buy_allowed_count": 0,
            "order_submitted_count": 0,
            "fill_count": 0,
            "blocked_count": 0,
            "selected_to_buy_allowed_rate": None,
            "buy_allowed_to_order_submitted_rate": None,
            "order_submitted_to_fill_rate": None,
        },
        "block_reasons": [],
        "runner_analysis": {
            "top_winners": [],
            "top_losers": [],
            "runner_score_top": [],
            "missed_runner_candidates": [],
            "notes": [
                "Runner analysis is pending a future read-only data source implementation."
            ],
        },
        "noisy_universe": {
            "candidate_count": 0,
            "traded_count": 0,
            "flags": [],
            "notes": [
                "Noisy universe analysis is pending a future read-only data source implementation."
            ],
        },
        "data_quality": {
            "status": "WARN",
            "warning_count": 1,
            "error_count": 0,
            "daily_summary_mismatch": False,
            "missing_snapshots": False,
            "candidate_evaluations_missing": False,
            "issues": ["Placeholder report contains no operational data yet."],
        },
        "recommended_codex_work": [],
        "artifacts": {
            "excel_path": str(excel_path),
            "summary_path": str(paths.summary_path),
            "metrics_path": str(paths.metrics_path),
        },
    }


def build_placeholder_summary(metrics: dict[str, Any]) -> str:
    trade_date = metrics["trade_date"]
    return "\n".join(
        [
            f"# Daily Operations Report Placeholder - {trade_date}",
            "",
            "This is the first safe skeleton for the read-only daily operations report CLI.",
            "It does not connect to the database, call external APIs, or modify trading behavior.",
            "",
            "## 1. PASS / WARN / FAIL summary",
            "- WARN: Placeholder only; operational data collection is not implemented yet.",
            "",
            "## 2. Analysis period",
            f"- Start: {metrics['analysis_period']['start_date']}",
            f"- End: {metrics['analysis_period']['end_date']}",
            "",
            "## 3. Data coverage",
            "- No DB queries are executed in this skeleton.",
            "",
            "## 4. Key profit/loss",
            "- Not calculated yet.",
            "",
            "## 5. Candidate -> selected -> buy_allowed -> order_submitted -> fill funnel",
            "- Not calculated yet.",
            "",
            "## 6. Main reasons orders were not submitted",
            "- Not analyzed yet.",
            "",
            "## 7. Runner analysis",
            "- Not analyzed yet.",
            "",
            "## 8. Noisy universe analysis",
            "- Not analyzed yet.",
            "",
            "## 9. Data quality WARN items",
            "- Placeholder report contains no operational data yet.",
            "",
            "## 10. Recommended next work candidates",
            "- Add a read-only data-source boundary and tests before connecting operational tables.",
            "",
        ]
    )


def export_daily_ops_report(
    *,
    trade_date: date,
    output_dir: Path,
    generated_at: datetime | None = None,
) -> DailyOpsReportResult:
    """Write placeholder daily ops report artifacts without external side effects."""
    paths = daily_ops_report_paths(trade_date, output_dir)
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    metrics = build_placeholder_metrics(
        trade_date=trade_date,
        output_dir=output_dir,
        generated_at=generated_at,
    )
    paths.metrics_path.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    paths.summary_path.write_text(
        build_placeholder_summary(metrics), encoding="utf-8"
    )
    return DailyOpsReportResult(
        trade_date=trade_date,
        summary_path=paths.summary_path,
        metrics_path=paths.metrics_path,
    )
