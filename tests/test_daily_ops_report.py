from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone

from trading_bot.daily_ops_report import (
    build_placeholder_metrics,
    daily_ops_report_paths,
    export_daily_ops_report,
)


def test_daily_ops_report_paths_use_requested_output_dir() -> None:
    paths = daily_ops_report_paths(
        date(2026, 6, 23),
        output_dir=__import__("pathlib").Path("reports/analysis/daily_2026-06-23"),
    )

    assert str(paths.summary_path) == (
        "reports/analysis/daily_2026-06-23/daily_ops_summary_2026-06-23.md"
    )
    assert str(paths.metrics_path) == (
        "reports/analysis/daily_2026-06-23/daily_ops_metrics_2026-06-23.json"
    )


def test_build_placeholder_metrics_has_required_report_sections(tmp_path) -> None:
    metrics = build_placeholder_metrics(
        trade_date=date(2026, 6, 23),
        output_dir=tmp_path,
        generated_at=datetime(2026, 6, 24, 1, 0, tzinfo=timezone.utc),
    )

    assert metrics["schema_version"] == 1
    assert metrics["status"] == "PLACEHOLDER"
    assert metrics["trade_date"] == "2026-06-23"
    assert metrics["data_quality"]["status"] == "WARN"
    assert metrics["artifacts"]["summary_path"].endswith(
        "daily_ops_summary_2026-06-23.md"
    )
    assert metrics["artifacts"]["metrics_path"].endswith(
        "daily_ops_metrics_2026-06-23.json"
    )


def test_export_daily_ops_report_writes_only_placeholder_summary_and_metrics(
    tmp_path,
) -> None:
    result = export_daily_ops_report(
        trade_date=date(2026, 6, 23),
        output_dir=tmp_path,
        generated_at=datetime(2026, 6, 24, 1, 0, tzinfo=timezone.utc),
    )

    assert result.summary_path == tmp_path / "daily_ops_summary_2026-06-23.md"
    assert result.metrics_path == tmp_path / "daily_ops_metrics_2026-06-23.json"
    assert "No DB queries are executed" in result.summary_path.read_text(
        encoding="utf-8"
    )
    assert (
        json.loads(result.metrics_path.read_text(encoding="utf-8"))["status"]
        == "PLACEHOLDER"
    )
    assert not (tmp_path / "auto_trading_review_2026-06-23.xlsx").exists()


def test_export_daily_ops_report_cli_parses_date_and_output_dir(tmp_path) -> None:
    output_dir = tmp_path / "daily_2026-06-23"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_bot",
            "export-daily-ops-report",
            "--date",
            "2026-06-23",
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "src"},
    )

    payload = json.loads(completed.stdout)
    assert payload["trade_date"] == "2026-06-23"
    assert payload["summary_path"] == str(
        output_dir / "daily_ops_summary_2026-06-23.md"
    )
    assert payload["metrics_path"] == str(
        output_dir / "daily_ops_metrics_2026-06-23.json"
    )
