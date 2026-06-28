from __future__ import annotations

import json
from datetime import date, datetime, timezone

from trading_bot.daily_trade_summary import generate_daily_trade_summary
from trading_bot.models import DailyTradeSummaryReport
from trading_bot.scheduler_market_close import save_daily_trade_summary_report


class FakeTradeSummarySource:
    def __init__(
        self,
        with_fills: bool = True,
        snapshot_count: int = 30,
        with_sensitive_log: bool = False,
    ) -> None:
        self.with_fills = with_fills
        self.snapshot_count = snapshot_count
        self.with_sensitive_log = with_sensitive_log

    def account_summary(self, trade_date: date, is_mock: bool) -> tuple[object, ...]:
        return (1000.0, 1250.0, 250.0, 1, 1.25, 5.0)

    def run_summary(self, trade_date: date, is_mock: bool) -> tuple[object, ...]:
        return ("STRICT_FIXED_NO_PYRAMIDING", "hash123", 5.0, 25.0)

    def fill_rows(self, trade_date: date, is_mock: bool) -> list[tuple[object, ...]]:
        if not self.with_fills:
            return []
        return [
            (
                trade_date,
                "22:40:00",
                "AAA",
                "Alpha",
                "BUY",
                2,
                10.0,
                20.0,
                None,
                None,
                "OPENING_BREAKOUT",
                "",
                "STRICT_FIXED_NO_PYRAMIDING",
                "hash123",
            ),
            (
                trade_date,
                "23:10:00",
                "AAA",
                "Alpha",
                "SELL",
                2,
                12.5,
                25.0,
                5.0,
                0.25,
                "OPENING_BREAKOUT",
                "",
                "STRICT_FIXED_NO_PYRAMIDING",
                "hash123",
            ),
        ]

    def trade_rows(self, trade_date: date, is_mock: bool) -> list[tuple[object, ...]]:
        if not self.with_fills:
            return []
        return [
            (
                trade_date,
                "2026-06-01 23:10:00",
                "AAA",
                "Alpha",
                "SELL",
                12.5,
                2,
                "TAKE_PROFIT",
                None,
                None,
                "OPENING_BREAKOUT",
                "",
                "STRICT_FIXED_NO_PYRAMIDING",
                "hash123",
            )
        ]

    def entry_profit_snapshots(self, trade_date: date) -> list[tuple[object, ...]]:
        return [
            ("AAA", "Alpha", -0.01, -0.02, 0.01, 0.02, 0.03, "TAKE_PROFIT", 0.25, "STRICT")
            for _ in range(self.snapshot_count)
        ]

    def candidate_counts(self, trade_date: date) -> tuple[object, ...]:
        return (5, 3, 2)

    def log_rows(self, trade_date: date) -> list[tuple[object, ...]]:
        if not self.with_sensitive_log:
            return []
        return [
            (
                "2026-06-01 22:32:00",
                "ERROR",
                "order",
                "주문 실패 Authorization: Bearer secret-token APP_SECRET=hidden-value",
                "",
                "AAA",
                None,
                None,
            )
        ]

    def candidate_performance_rows(
        self,
        trade_date: date,
        is_mock: bool,
    ) -> list[tuple[object, ...]]:
        if not self.with_fills:
            return []
        return [
            (
                "AAA",
                5.0,
                0.25,
                "OPENING_BREAKOUT",
                "",
                "fixed_recheck",
                65.0,
            )
        ]


class FakeSummaryRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[date, str], DailyTradeSummaryReport] = {}
        self.save_calls = 0

    def save_daily_trade_summary_report(self, report: DailyTradeSummaryReport) -> None:
        self.save_calls += 1
        self.rows[(report.trade_date, report.mode)] = report


def test_generate_daily_summary_saves_row_for_day_with_trades() -> None:
    repository = FakeSummaryRepository()

    result = generate_daily_trade_summary(
        trade_date=date(2026, 6, 1),
        mode="mock",
        data_source=FakeTradeSummarySource(),
        repository=repository,
        generated_at=datetime(2026, 6, 2, 6, 0, tzinfo=timezone.utc),
    )

    report = result.report
    payload = json.loads(report.summary_json)
    assert repository.rows[(date(2026, 6, 1), "mock")] == report
    assert report.trade_count == 2
    assert report.buy_count == 1
    assert report.sell_count == 1
    assert report.total_profit_usd == 5.0
    assert report.win_rate == 100.0
    assert report.take_profit_count == 1
    assert payload["strategyVersion"] == "STRICT_FIXED_NO_PYRAMIDING"
    assert payload["candidateCount"] == 5
    assert payload["candidateRowCount"] == 5
    assert payload["candidateSymbolCount"] == 5
    assert payload["scoringCount"] == 3
    assert payload["selectedCount"] == 1
    assert payload["selectedCandidateCount"] == 2
    assert payload["tradedSymbolCount"] == 1
    assert payload["candidateSummary"]["candidateCount"] == 5
    assert payload["performanceMetrics"]["expectancyPerTrade"] == 5.0
    assert payload["performanceMetrics"]["profitFactor"] is None
    assert payload["performanceMetrics"]["breakevenWinRate"] == 0.0
    assert payload["performanceMetrics"]["netTotalProfitUsd"] == 5.0
    assert payload["sourceStats"][0]["source"] == "fixed_recheck"
    assert payload["scoreBucketStats"][0]["scoreBucket"] == "60_70"
    assert "모의투자 일일 요약" in report.summary_text
    assert "기대값/거래: $5.00" in report.summary_text


def test_generate_daily_summary_keeps_candidate_row_and_symbol_counts() -> None:
    class Source(FakeTradeSummarySource):
        def candidate_counts(self, trade_date: date) -> tuple[object, ...]:
            return (5, 3, 5, 3, 2, 2)

    result = generate_daily_trade_summary(
        trade_date=date(2026, 6, 3),
        mode="mock",
        data_source=Source(),
        repository=FakeSummaryRepository(),
    )

    payload = json.loads(result.report.summary_json)
    assert payload["candidateCount"] == 3
    assert payload["candidateRowCount"] == 5
    assert payload["candidateSymbolCount"] == 3
    assert payload["scoringCount"] == 5
    assert payload["scoringSymbolCount"] == 3
    assert payload["selectedCount"] == 1
    assert payload["selectedCandidateCount"] == 2
    assert payload["selectedSymbolCount"] == 2
    assert payload["tradedSymbolCount"] == 1


def test_generate_daily_summary_saves_row_without_trades() -> None:
    repository = FakeSummaryRepository()

    result = generate_daily_trade_summary(
        trade_date=date(2026, 6, 1),
        mode="mock",
        data_source=FakeTradeSummarySource(with_fills=False),
        repository=repository,
    )

    assert result.report.trade_count == 0
    assert result.report.buy_count == 0
    assert result.report.sell_count == 0
    assert result.report.total_profit_usd == 0.0


def test_generate_daily_summary_rerun_updates_same_date_mode() -> None:
    repository = FakeSummaryRepository()
    source = FakeTradeSummarySource()

    generate_daily_trade_summary(date(2026, 6, 1), "mock", source, repository)
    generate_daily_trade_summary(date(2026, 6, 1), "mock", source, repository)

    assert repository.save_calls == 2
    assert len(repository.rows) == 1


def test_generate_daily_summary_marks_small_entry_profit_sample_insufficient() -> None:
    repository = FakeSummaryRepository()

    result = generate_daily_trade_summary(
        date(2026, 6, 1),
        "mock",
        FakeTradeSummarySource(snapshot_count=1),
        repository,
    )

    payload = json.loads(result.report.summary_json)
    assert result.report.sample_sufficient is False
    assert payload["sampleSufficient"] is False
    assert "표본 부족: 전략 판단 금지" in payload["warnings"]


def test_generate_daily_summary_redacts_sensitive_text() -> None:
    repository = FakeSummaryRepository()

    result = generate_daily_trade_summary(
        date(2026, 6, 1),
        "mock",
        FakeTradeSummarySource(with_sensitive_log=True),
        repository,
    )

    assert "secret-token" not in result.report.summary_json
    assert "hidden-value" not in result.report.summary_text
    assert "[REDACTED]" in result.report.summary_json


def test_summary_save_failure_is_logged_and_ignored(monkeypatch) -> None:
    logs = []

    def fail_summary(**kwargs):
        raise RuntimeError("db password should not be logged")

    class LogRepository:
        def __init__(self, connect) -> None:
            self.connect = connect

        def save_log(self, log) -> None:
            logs.append(log)

    monkeypatch.setattr("trading_bot.scheduler_market_close.generate_daily_trade_summary", fail_summary)
    monkeypatch.setattr("trading_bot.scheduler_logging.SqlServerDailyRepository", LogRepository)
    monkeypatch.setattr("trading_bot.scheduler_logging.pyodbc_connect_factory", lambda: object)

    save_daily_trade_summary_report()

    assert logs[0].reject_reason == "SUMMARY_REPORT_SAVE_FAILED"
    assert "password" not in logs[0].message
