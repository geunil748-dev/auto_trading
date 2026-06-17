from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from trading_bot.entry_planner import plan_buy_intents
from trading_bot.entry_root_cause_analysis import (
    CostOptions,
    analyze_entry_root_causes,
    load_entry_root_cause_rows_from_csv,
    render_entry_root_cause_text,
    summarize_entry_root_cause_archive,
    write_entry_root_cause_output,
)
from trading_bot.models import AccountState, BreakoutInput, CandidateEvaluation, ScoreRecord
from trading_bot.config import TradingSettings


def test_entry_root_cause_csv_baseline_groups_and_costs(tmp_path: Path) -> None:
    csv_path = _sample_csv(tmp_path)
    rows, warnings = load_entry_root_cause_rows_from_csv(csv_path)

    payload = analyze_entry_root_causes(
        rows,
        cost_options=CostOptions(0.001, 0.001, 0.001),
        entry_timezone="Asia/Seoul",
        market_timezone="America/New_York",
        source={"type": "csv", "path": str(csv_path)},
        generated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        warnings=warnings,
    )

    baseline = payload["baseline"]
    assert baseline["rowCount"] == 6
    assert baseline["completedCount"] == 5
    assert baseline["openCount"] == 1
    assert baseline["avgNetFinalProfitRate"] == pytest.approx(
        baseline["avgFinalProfitRate"] - 0.003
    )
    assert payload["dataScope"]["sampleWarning"]
    assert payload["groups"]["byEntryTimeBucket"]["open_15_30m"]["completedCount"] == 3
    assert payload["groups"]["byPriceBucket"]["10_20"]["rowCount"] >= 1
    assert payload["groups"]["byCandidateSource"]["manual_buy_list"]["rowCount"] == 1
    assert payload["groups"]["byCandidateSource"]["unknown"]["rowCount"] >= 1
    assert payload["groups"]["byRankingSelectionMode"]["unknown"]["rowCount"] >= 1
    assert payload["groups"]["byEntryReasonTag"]["OPENING_BREAKOUT"]["rowCount"] >= 4
    assert payload["groups"]["byExitReason"]["STOP_LOSS"]["stopLossRate"] == 1.0
    assert payload["groups"]["byEarlyBehavior"]["5m_positive"]["completedCount"] >= 2
    assert payload["groups"]["byEarlyBehavior"]["30m_negative"]["completedCount"] >= 2
    assert payload["groups"]["byBreakoutQuality"]["0_1pct_above_breakout"]["rowCount"] >= 1
    assert payload["groups"]["byLiquidityQuality"]["spread_1pct_plus"]["rowCount"] >= 1
    assert payload["groups"]["byRankingPresence"]["presence_3"]["rowCount"] >= 1
    assert payload["groups"]["byManualAuto"]["manual only"]["rowCount"] == 1
    assert payload["topLossPatterns"]
    assert payload["hypotheses"]
    assert any("interpreted 2.62 as percent" in item for item in payload["warnings"])
    purr = next(item for item in payload["details"] if item["ticker"] == "PURR")
    assert purr["entryTimeBucket"] == "open_15_30m"
    assert purr["priceBucket"] == "10_20"
    assert purr["snapshotProfits"]["5"] == 0.0225
    assert purr["finalProfitRate"] == -0.0506


def test_entry_root_cause_text_and_json_output_utf8_without_bom(tmp_path: Path) -> None:
    rows, warnings = load_entry_root_cause_rows_from_csv(_sample_csv(tmp_path))
    payload = analyze_entry_root_causes(rows, warnings=warnings)
    output = tmp_path / "entry_root_cause.json"

    rendered = write_entry_root_cause_output(payload, output=output)
    text = render_entry_root_cause_text(payload)

    assert rendered.startswith("{\n")
    assert '\n  "generatedAt"' in output.read_text(encoding="utf-8")
    assert not output.read_bytes().startswith(bytes([0xEF, 0xBB, 0xBF]))
    assert "Entry Root Cause Analysis" in text
    assert "진입 시간대별 성과" in text


def test_entry_root_cause_archive_summary(tmp_path: Path) -> None:
    rows, warnings = load_entry_root_cause_rows_from_csv(_sample_csv(tmp_path))
    archive = tmp_path / "archive"
    archive.mkdir()
    for day in (17, 18):
        payload = analyze_entry_root_causes(
            rows,
            generated_at=datetime(2026, 6, day, tzinfo=timezone.utc),
            warnings=warnings,
        )
        (archive / f"entry_root_cause_2026-06-{day}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    summary = summarize_entry_root_cause_archive(
        archive,
        days=5,
        now=datetime(2026, 6, 18, tzinfo=timezone.utc),
    )
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    empty = summarize_entry_root_cause_archive(empty_dir)

    assert summary["fileCount"] == 2
    assert summary["repeatedLossPatterns"]
    assert any(item["group"] == "byEntryTimeBucket" for item in summary["repeatedLossPatterns"])
    assert empty["fileCount"] == 0
    assert empty["warnings"]


def test_entry_root_cause_cli_input_csv_does_not_call_db_or_order_paths(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    import trading_bot.cli as cli

    csv_path = _sample_csv(tmp_path)
    monkeypatch.setattr(cli, "initialize_database", lambda *args, **kwargs: (_raise("db write")))
    monkeypatch.setattr(cli, "repair_database_schema", lambda *args, **kwargs: (_raise("repair")))
    monkeypatch.setattr(cli, "build_mock_buy_executor", lambda *args, **kwargs: (_raise("buy")))
    monkeypatch.setattr(cli, "build_mock_sell_executor", lambda *args, **kwargs: (_raise("sell")))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "trading-bot",
            "analyze-entry-root-cause",
            "--input-csv",
            str(csv_path),
            "--format",
            "text",
        ],
    )

    cli.main()

    assert "Entry Root Cause Analysis" in capsys.readouterr().out


def test_candidate_evaluation_json_enrichment_has_no_sensitive_fields() -> None:
    repository = _Repo()
    settings = TradingSettings()

    plan_buy_intents(
        [ScoreRecord("AAA", news_score=70.0, chart_score=80.0)],
        {"AAA": BreakoutInput(12.0, 10.0, 11.0, 9.0, minutes_above_breakout=2.0)},
        AccountState(cash_usd=10000.0, equity_usd=10000.0, invested_usd=0.0, open_positions=0, daily_profit_rate=0.0),
        settings,
        repository=repository,
        trade_date=date(2026, 6, 18),
        source_by_ticker={"AAA": "manual_buy_list"},
        run_id="test-run",
    )

    assert repository.candidate_evaluations
    evaluation = repository.candidate_evaluations[0]
    raw = json.loads(evaluation.raw_candidate_json or "{}")
    condition = json.loads(evaluation.condition_result_json or "{}")
    settings_json = json.loads(evaluation.settings_snapshot_json or "{}")
    combined = json.dumps({**raw, **condition, **settings_json}, ensure_ascii=False).lower()
    assert raw["candidate_source"] == "manual_buy_list"
    assert raw["ranking_selection_mode"] == settings.ranking_selection_mode
    assert raw["manual_candidate"] is True
    assert raw["entry_price_vs_breakout"] is not None
    assert condition["order_protection_checked"] is False
    assert settings_json["ranking_selection_mode"] == settings.ranking_selection_mode
    for sensitive in ("api_key", "app_key", "app_secret", "token", "account_no", "password", "dsn"):
        assert sensitive not in combined


class _Repo:
    def __init__(self) -> None:
        self.candidate_evaluations: list[CandidateEvaluation] = []

    def save_candidate_evaluations(self, evaluations) -> None:
        self.candidate_evaluations.extend(evaluations)

    def save_log(self, log) -> None:
        return None


def _raise(message: str) -> None:
    raise AssertionError(message)


def _sample_csv(tmp_path: Path) -> Path:
    path = tmp_path / "entry_profit_snapshot.csv"
    path.write_text(
        "\n".join(
            [
                "trade_date,entry_time,ticker,entry_price,final_profit_rate,final_exit_reason,profit_rate_5m,profit_rate_10m,profit_rate_30m,profit_rate_60m,entry_reason,candidate_source,ranking_selection_mode,breakout_threshold,bid_ask_spread_rate,ranking_presence_count",
                "2026-06-16,2026-06-16 22:45:07,PURR,10.67,-5.06%,STOP_LOSS,+2.25%,+0.84%,-2.25%,-2.16%,OPENING_BREAKOUT,auto,intersection,10.60,0.20%,3",
                "2026-06-09,22:45:00,KEEL,13.20,-0.0516,STOP_LOSS,,+0.81%,-1.61%,-5.00%,MANUAL_WATCHLIST+OPENING_BREAKOUT,manual_buy_list,composite,13.10,1.20%,2",
                "2026-06-10,22:48:21,CRDO,12.00,-0.0506,STOP_LOSS,-3.00%,-1.74%,,,OPENING_BREAKOUT,,unknown,12.20,,",
                "2026-06-02,01:10:48,LASE,4.50,+10.87%,PARTIAL_TAKE_PROFIT,+2.90%,+10.87%,+10.87%,+10.87%,OPENING_BREAKOUT,both,intersection,4.40,0.50%,1",
                "2026-06-11,23:30:00,HOOD,78.00,2.62,EOD,+0.50%,+0.70%,+1.00%,+1.20%,CHART_POSITIVE,auto,intersection,77.50,0.10%,3",
                "2026-06-12,23:00:00,OPEN,22.00,,,+0.10%,,,,,OPENING_BREAKOUT,auto,intersection,21.90,0.10%,3",
            ]
        ),
        encoding="utf-8",
    )
    return path
