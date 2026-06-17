from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from trading_bot.exit_rule_simulation import (
    SIMULATION_WARNING_TEXT,
    load_entry_profit_snapshots_from_csv,
    render_exit_rule_archive_summary_text,
    render_exit_rule_simulation_text,
    simulate_exit_rules,
    summarize_exit_rule_simulation_archive,
    write_exit_rule_simulation_output,
)


def test_simulate_exit_rules_parses_csv_and_evaluates_rules(tmp_path: Path) -> None:
    csv_path = tmp_path / "entry_profit_snapshot.csv"
    csv_path.write_text(
        "\n".join(
            [
                "trade_date,ticker,entry_time,profit_after_5m,profit_rate_10m,profit_after_30m,profit_after_60m,final_profit_rate,final_exit_reason",
                "2026-06-16,PURR,22:31:00,+2.25%,0.0100,-0.0225,-0.0500,-0.0506,STOP_LOSS",
                "2026-06-16,KEEL,22:35:00,0.0050,+0.81%,-0.0200,-5.00%,-0.0516,STOP_LOSS",
                "2026-06-16,CRDO,22:40:00,-0.0300,-1.74%,-0.0500,-0.0500,-0.0506,STOP_LOSS",
                "2026-06-16,LASE,22:45:00,0.0290,+10.87%,0.1087,0.1087,0.1087,TAKE_PROFIT",
                "2026-06-16,OPEN,22:50:00,0.0100,0.0200,,,,",
            ]
        ),
        encoding="utf-8",
    )
    rows, warnings = load_entry_profit_snapshots_from_csv(csv_path)

    payload = simulate_exit_rules(
        rows,
        source=f"csv:{csv_path}",
        generated_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        warnings=warnings,
    )

    assert payload["baseline"]["completedCount"] == 4
    assert payload["baseline"]["openCount"] == 1
    assert payload["dataScope"]["tickerCount"] == 5
    assert payload["rules"]["early_loss_5m"]["triggeredCount"] == 1
    assert payload["rules"]["profit_protection_2pct"]["helpedCount"] >= 1
    assert payload["rules"]["partial_take_profit_3pct"]["hurtCount"] >= 1
    crdo = _detail(payload, "CRDO", "early_loss_5m")
    assert crdo["simulatedExitMinute"] == 5
    assert crdo["simulatedProfitRate"] == -0.03
    assert crdo["verdict"] == "helped"
    purr = _detail(payload, "PURR", "profit_protection_2pct")
    assert purr["snapshotProfits"]["5"] == 0.0225
    assert purr["simulatedProfitRate"] == -0.003
    lase = _detail(payload, "LASE", "partial_take_profit_3pct")
    assert round(lase["simulatedProfitRate"], 6) == 0.06935
    assert lase["verdict"] == "hurt"
    assert any(
        detail.get("ticker") == "OPEN"
        and detail.get("skippedReason") == "missing_final_profit_rate"
        for detail in payload["details"]
    )
    assert "profit_protection_2pct" in render_exit_rule_simulation_text(payload)


def test_exit_rule_simulation_output_json_is_utf8_without_bom(tmp_path: Path) -> None:
    payload = simulate_exit_rules(
        [],
        generated_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
    )
    output = tmp_path / "exit_rule_simulation.json"

    rendered = write_exit_rule_simulation_output(payload, output=output)

    assert rendered.startswith("{\n")
    assert b"\xef\xbb\xbf" not in output.read_bytes()[:3]
    assert '\n  "generatedAt"' in output.read_text(encoding="utf-8")


def test_summarize_exit_rule_simulation_archive_and_empty_dir(tmp_path: Path) -> None:
    payload = simulate_exit_rules(
        [
            _row("AAA", 0.04, -0.05),
            _row("BBB", 0.05, -0.04),
        ],
        generated_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
    )
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "exit_rule_simulation_2026-06-17.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = summarize_exit_rule_simulation_archive(archive, days=30)
    text = render_exit_rule_archive_summary_text(summary)

    assert summary["fileCount"] == 1
    assert summary["rules"]["profit_protection_2pct"]["triggeredCount"] == 2
    assert summary["rules"]["profit_protection_2pct"]["recommendedAction"] == "keep_observing"
    assert summary["topHelpedTrades"][0]["ticker"] == "AAA"
    assert SIMULATION_WARNING_TEXT in text
    empty = summarize_exit_rule_simulation_archive(tmp_path / "missing")
    assert empty["fileCount"] == 0
    assert empty["warnings"]
    empty_existing = tmp_path / "empty"
    empty_existing.mkdir()
    assert summarize_exit_rule_simulation_archive(empty_existing)["warnings"]


def _detail(payload: dict[str, object], ticker: str, rule: str) -> dict[str, object]:
    for detail in payload["details"]:  # type: ignore[index]
        if detail["ticker"] == ticker and detail["rule"] == rule:  # type: ignore[index]
            return detail  # type: ignore[return-value]
    raise AssertionError(f"missing detail for {ticker} {rule}")


def _row(ticker: str, profit_5m: float, final_profit: float):
    from trading_bot.exit_rule_simulation import EntryProfitSnapshotRow

    return EntryProfitSnapshotRow(
        trade_date="2026-06-17",
        ticker=ticker,
        snapshots={5: profit_5m, 10: profit_5m, 30: profit_5m, 60: profit_5m},
        final_profit_rate=final_profit,
        final_exit_reason="STOP_LOSS",
    )
