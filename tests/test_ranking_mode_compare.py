from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime

from trading_bot.cli import main
from trading_bot.config import KisSettings, TradingSettings
from trading_bot.models import (
    AccountState,
    BuyIntent,
    CandidateEvaluation,
    CandidateSnapshot,
    DailyScore,
    DailyTarget,
    ScoreRecord,
)
from trading_bot.pipeline import ScoringRun
from trading_bot.ranking_mode_compare import (
    compare_ranking_modes,
    format_ranking_mode_archive_summary,
    summarize_ranking_mode_archive,
    write_compare_payload,
)
from trading_bot.runtime import DryRunResult


class FakeRuntime:
    def __init__(self, result: DryRunResult) -> None:
        self.result = result

    def run(self) -> DryRunResult:
        return self.result


class FakeRepository:
    def __init__(
        self,
        evaluations: list[CandidateEvaluation] | None = None,
        ranking_rank_maps: dict[str, dict[str, int]] | None = None,
    ) -> None:
        self.candidate_evaluations = evaluations or []
        self.ranking_rank_maps = ranking_rank_maps or {
            "gainers": {},
            "turnover": {},
            "trade_value": {},
        }
        self.logs = []


def test_compare_ranking_modes_reports_sections_and_deterministic_diff() -> None:
    calls: list[str] = []

    def factory(settings: TradingSettings, _kis_settings: KisSettings):
        calls.append(settings.ranking_selection_mode)
        if settings.ranking_selection_mode == "intersection":
            return (
                FakeRuntime(_dry_result(("AAA", "BBB"), ("AAA",), ("AAA",))),
                FakeRepository([_evaluation("AAA", "BUY_ALLOWED")]),
            )
        return (
            FakeRuntime(_dry_result(("BBB", "CCC"), ("CCC",), ("CCC",))),
            FakeRepository([_evaluation("CCC", "BUY_ALLOWED")]),
        )

    payload = compare_ranking_modes(_settings(), _kis_settings(), runtime_factory=factory)

    assert calls == ["intersection", "composite"]
    assert set(payload) >= {"intersection", "composite", "diff", "summary"}
    assert payload["diff"] == {
        "targetsOnlyInIntersection": ["AAA"],
        "targetsOnlyInComposite": ["CCC"],
        "selectedOnlyInIntersection": ["AAA"],
        "selectedOnlyInComposite": ["CCC"],
        "buyIntentsOnlyInIntersection": ["AAA"],
        "buyIntentsOnlyInComposite": ["CCC"],
    }
    assert payload["summary"] == {
        "intersectionTargetCount": 2,
        "compositeTargetCount": 2,
        "intersectionSelectedCount": 1,
        "compositeSelectedCount": 1,
        "intersectionBuyIntentCount": 1,
        "compositeBuyIntentCount": 1,
    }


def test_compare_ranking_modes_enriches_trade_value_rank_and_sources() -> None:
    def factory(settings: TradingSettings, _kis_settings: KisSettings):
        rank_maps = {
            "gainers": {"AAA": 3, "BBB": 5},
            "turnover": {"AAA": 7},
            "trade_value": {"AAA": 11, "CCC": 13},
        }
        return (
            FakeRuntime(_dry_result(("AAA", "BBB"), ("AAA",), ("AAA",))),
            FakeRepository([_evaluation("AAA", "BUY_ALLOWED")], rank_maps),
        )

    payload = compare_ranking_modes(_settings(), _kis_settings(), runtime_factory=factory)

    row = payload["intersection"]["targets"][0]
    assert row["ticker"] == "AAA"
    assert row["gain_rank"] == 3
    assert row["turnover_rank"] == 7
    assert row["trade_value_rank"] == 11
    assert row["ranking_presence_count"] == 3
    assert row["ranking_sources"] == ["gainers", "turnover", "trade_value"]
    assert payload["intersection"]["rankDiagnostics"] == {
        "gainersCount": 2,
        "turnoverCount": 1,
        "tradeValueCount": 2,
        "rankingUnionCount": 3,
    }

    one_source = payload["intersection"]["targets"][1]
    assert one_source["ticker"] == "BBB"
    assert one_source["trade_value_rank"] is None
    assert one_source["ranking_presence_count"] == 1
    assert one_source["ranking_sources"] == ["gainers"]


def test_compare_ranking_modes_writes_utf8_json_output(tmp_path) -> None:
    output = tmp_path / "ranking_mode_compare.json"
    payload = {
        "tradeDate": "2026-06-15",
        "generatedAt": "2026-06-15T00:00:00+00:00",
        "intersection": {"targets": [], "selected": [], "buyIntentTickers": []},
        "composite": {"targets": [], "selected": [], "buyIntentTickers": []},
        "diff": {},
        "summary": {},
    }

    write_compare_payload(payload, output)

    data = output.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    assert json.loads(data.decode("utf-8"))["tradeDate"] == "2026-06-15"


def test_compare_ranking_modes_cli_prints_and_writes_output(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    output = tmp_path / "compare.json"
    archive_dir = tmp_path / "archive"
    payload = {
        "tradeDate": "2026-06-15",
        "generatedAt": "2026-06-15T12:34:56+00:00",
        "intersection": {"targets": [], "selected": [], "buyIntentTickers": []},
        "composite": {"targets": [], "selected": [], "buyIntentTickers": []},
        "diff": {},
        "summary": {},
    }
    submitter_calls: list[str] = []
    db_schema_calls: list[str] = []

    def fake_compare(
        settings: TradingSettings,
        kis_settings: KisSettings,
        *,
        include_manual: bool = False,
    ):
        assert settings.ranking_selection_mode == "intersection"
        assert kis_settings.base_url == "https://mock.example"
        assert include_manual is False
        return payload

    monkeypatch.setattr(sys, "argv", [
        "trading-bot",
        "compare-ranking-modes",
        "--output",
        str(output),
        "--archive-dir",
        str(archive_dir),
    ])
    monkeypatch.setattr("trading_bot.cli.load_settings", lambda: _settings())
    monkeypatch.setattr("trading_bot.cli.load_kis_settings", lambda: _kis_settings())
    monkeypatch.setattr("trading_bot.cli.compare_ranking_modes", fake_compare)
    monkeypatch.setattr(
        "trading_bot.cli.build_mock_buy_executor",
        lambda *args, **kwargs: submitter_calls.append("buy"),
    )
    monkeypatch.setattr(
        "trading_bot.cli.build_mock_sell_executor",
        lambda *args, **kwargs: submitter_calls.append("sell"),
    )
    monkeypatch.setattr(
        "trading_bot.cli.ensure_mssql_database_exists",
        lambda *args, **kwargs: db_schema_calls.append("ensure"),
    )
    monkeypatch.setattr(
        "trading_bot.cli.initialize_database",
        lambda *args, **kwargs: db_schema_calls.append("init"),
    )
    monkeypatch.setattr(
        "trading_bot.cli.repair_database_schema",
        lambda *args, **kwargs: db_schema_calls.append("repair"),
    )

    main()

    assert submitter_calls == []
    assert db_schema_calls == []
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    archive_file = archive_dir / "ranking_mode_compare_20260615_123456.json"
    assert json.loads(archive_file.read_text(encoding="utf-8")) == payload
    assert not archive_file.read_bytes().startswith(b"\xef\xbb\xbf")
    assert json.loads(capsys.readouterr().out)["tradeDate"] == "2026-06-15"


def test_compare_ranking_modes_cli_can_include_manual_watchlist(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    payload = {
        "tradeDate": "2026-06-15",
        "generatedAt": "2026-06-15T12:34:56+00:00",
        "intersection": {"targets": [], "selected": [], "buyIntentTickers": []},
        "composite": {"targets": [], "selected": [], "buyIntentTickers": []},
        "diff": {},
        "summary": {},
    }
    captured: list[bool] = []

    def fake_compare(
        _settings: TradingSettings,
        _kis_settings: KisSettings,
        *,
        include_manual: bool = False,
    ):
        captured.append(include_manual)
        return payload

    monkeypatch.setattr(sys, "argv", [
        "trading-bot",
        "compare-ranking-modes",
        "--include-manual",
    ])
    monkeypatch.setattr("trading_bot.cli.load_settings", lambda: _settings())
    monkeypatch.setattr("trading_bot.cli.load_kis_settings", lambda: _kis_settings())
    monkeypatch.setattr("trading_bot.cli.compare_ranking_modes", fake_compare)

    main()

    assert captured == [True]
    assert json.loads(capsys.readouterr().out)["tradeDate"] == "2026-06-15"


def test_summarize_ranking_mode_archive_aggregates_files(tmp_path) -> None:
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    _write_archive(archive_dir, "ranking_mode_compare_20260615_010000.json", _archive_payload(
        "2026-06-15T01:00:00+00:00",
        intersection_targets=2,
        composite_targets=4,
        intersection_selected=1,
        composite_selected=2,
        intersection_intents=0,
        composite_intents=1,
        composite_only_selected=("AAA", "CCC"),
        composite_only_intents=("CCC",),
    ))
    _write_archive(archive_dir, "ranking_mode_compare_20260616_010000.json", _archive_payload(
        "2026-06-16T01:00:00+00:00",
        intersection_targets=4,
        composite_targets=5,
        intersection_selected=2,
        composite_selected=3,
        intersection_intents=1,
        composite_intents=2,
        composite_only_selected=("CCC",),
        composite_only_intents=("BBB", "CCC"),
    ))

    payload = summarize_ranking_mode_archive(archive_dir)

    assert payload["fileCount"] == 2
    assert payload["summary"]["avgIntersectionTargetCount"] == 3
    assert payload["summary"]["avgCompositeTargetCount"] == 4.5
    assert payload["summary"]["avgIntersectionSelectedCount"] == 1.5
    assert payload["summary"]["avgCompositeSelectedCount"] == 2.5
    assert payload["summary"]["avgIntersectionBuyIntentCount"] == 0.5
    assert payload["summary"]["avgCompositeBuyIntentCount"] == 1.5
    assert payload["summary"]["compositeOnlySelectedTickerCount"] == 2
    assert payload["summary"]["compositeOnlyBuyIntentTickerCount"] == 2
    assert payload["topCompositeOnlySelectedTickers"][0] == {
        "ticker": "CCC",
        "count": 2,
        "avgRankingPresenceCount": 3.0,
        "sources": ["gainers", "turnover", "trade_value"],
    }


def test_summarize_ranking_mode_archive_text_format(tmp_path, monkeypatch, capsys) -> None:
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    _write_archive(archive_dir, "ranking_mode_compare_20260615_010000.json", _archive_payload(
        "2026-06-15T01:00:00+00:00",
        intersection_targets=1,
        composite_targets=2,
        intersection_selected=0,
        composite_selected=1,
        intersection_intents=0,
        composite_intents=1,
        composite_only_selected=("AAA",),
        composite_only_intents=("AAA",),
    ))
    submitter_calls: list[str] = []
    db_schema_calls: list[str] = []
    monkeypatch.setattr(sys, "argv", [
        "trading-bot",
        "summarize-ranking-mode-archive",
        "--archive-dir",
        str(archive_dir),
        "--format",
        "text",
    ])
    monkeypatch.setattr(
        "trading_bot.cli.build_mock_buy_executor",
        lambda *args, **kwargs: submitter_calls.append("buy"),
    )
    monkeypatch.setattr(
        "trading_bot.cli.ensure_mssql_database_exists",
        lambda *args, **kwargs: db_schema_calls.append("ensure"),
    )
    monkeypatch.setattr(
        "trading_bot.cli.initialize_database",
        lambda *args, **kwargs: db_schema_calls.append("init"),
    )
    monkeypatch.setattr(
        "trading_bot.cli.repair_database_schema",
        lambda *args, **kwargs: db_schema_calls.append("repair"),
    )

    main()

    output = capsys.readouterr().out
    assert "Files: 1" in output
    assert "Top composite-only selected tickers:" in output
    assert "AAA" in output
    assert "candidate comparison only" in output
    assert submitter_calls == []
    assert db_schema_calls == []


def test_summarize_ranking_mode_archive_empty_dir(tmp_path) -> None:
    payload = summarize_ranking_mode_archive(tmp_path / "empty")

    assert payload["fileCount"] == 0
    assert payload["dateRange"] == {"from": None, "to": None}
    assert payload["summary"]["avgIntersectionTargetCount"] == 0
    assert payload["topCompositeOnlySelectedTickers"] == []
    assert payload["topCompositeOnlyBuyIntentTickers"] == []
    assert payload["warnings"] == []
    assert "Files: 0" in format_ranking_mode_archive_summary(payload)


def _dry_result(
    targets: tuple[str, ...],
    selected: tuple[str, ...],
    intents: tuple[str, ...],
) -> DryRunResult:
    trade_date = date(2026, 6, 15)
    scores = tuple(
        DailyScore(trade_date, _score(ticker), ticker in selected)
        for ticker in targets
    )
    return DryRunResult(
        account=AccountState(1000, 1000, 0, 0, 0),
        scoring=ScoringRun(
            trade_date=trade_date,
            blocked_reason=None,
            targets=tuple(DailyTarget(trade_date, _snapshot(ticker)) for ticker in targets),
            scores=scores,
        ),
        buy_intents=tuple(
            BuyIntent(ticker, 1, 10.0, 10.0, 0.01)
            for ticker in intents
        ),
    )


def _snapshot(ticker: str) -> CandidateSnapshot:
    return CandidateSnapshot(
        ticker=ticker,
        price_usd=10.0,
        open_price_usd=10.0,
        previous_close_usd=9.5,
        opening_price_change=0.05,
        opening_volume_ratio=2.0,
        turnover_rank=1,
        gain_rank=1,
        name=f"{ticker} name",
    )


def _score(ticker: str) -> ScoreRecord:
    return ScoreRecord(ticker, news_score=80.0, chart_score=70.0)


def _evaluation(ticker: str, reason: str) -> CandidateEvaluation:
    return CandidateEvaluation(
        run_id=None,
        evaluation_time=datetime(2026, 6, 15, tzinfo=UTC),
        trading_date=date(2026, 6, 15),
        source="dry_run",
        symbol=ticker,
        buy_allowed=reason == "BUY_ALLOWED",
        buy_block_reason=reason,
        final_decision=reason,
    )


def _settings() -> TradingSettings:
    return TradingSettings(ranking_selection_mode="intersection")


def _kis_settings() -> KisSettings:
    return KisSettings(
        app_key="",
        app_secret="",
        account_no="",
        account_product="01",
        base_url="https://mock.example",
    )


def _write_archive(directory: object, name: str, payload: dict[str, object]) -> None:
    path = directory / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _archive_payload(
    generated_at: str,
    *,
    intersection_targets: int,
    composite_targets: int,
    intersection_selected: int,
    composite_selected: int,
    intersection_intents: int,
    composite_intents: int,
    composite_only_selected: tuple[str, ...],
    composite_only_intents: tuple[str, ...],
) -> dict[str, object]:
    composite_rows = [
        _ticker_payload(ticker)
        for ticker in sorted(set(composite_only_selected) | set(composite_only_intents))
    ]
    return {
        "tradeDate": generated_at[:10],
        "generatedAt": generated_at,
        "intersection": {"targets": [], "selected": [], "buyIntentTickers": []},
        "composite": {
            "targets": composite_rows,
            "selected": [
                row for row in composite_rows if row["ticker"] in composite_only_selected
            ],
            "buyIntentTickers": list(composite_only_intents),
        },
        "diff": {
            "targetsOnlyInIntersection": [],
            "targetsOnlyInComposite": [],
            "selectedOnlyInIntersection": [],
            "selectedOnlyInComposite": list(composite_only_selected),
            "buyIntentsOnlyInIntersection": [],
            "buyIntentsOnlyInComposite": list(composite_only_intents),
        },
        "summary": {
            "intersectionTargetCount": intersection_targets,
            "compositeTargetCount": composite_targets,
            "intersectionSelectedCount": intersection_selected,
            "compositeSelectedCount": composite_selected,
            "intersectionBuyIntentCount": intersection_intents,
            "compositeBuyIntentCount": composite_intents,
        },
    }


def _ticker_payload(ticker: str) -> dict[str, object]:
    if ticker == "BBB":
        return {
            "ticker": ticker,
            "ranking_presence_count": 2,
            "ranking_sources": ["turnover", "trade_value"],
        }
    return {
        "ticker": ticker,
        "ranking_presence_count": 3,
        "ranking_sources": ["gainers", "turnover", "trade_value"],
    }
