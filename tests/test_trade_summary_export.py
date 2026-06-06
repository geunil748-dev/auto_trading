from __future__ import annotations

from datetime import date, datetime, timezone

from trading_bot.trade_summary_export import export_trade_summary


class FakeTradeSummaryDataSource:
    def __init__(self, with_fills: bool = True, with_error_log: bool = False) -> None:
        self.with_fills = with_fills
        self.with_error_log = with_error_log

    def account_summary(self, trade_date: date, is_mock: bool) -> tuple[object, ...]:
        return (1000.0, 1250.0, 250.0, 1, 1.25, 15.5)

    def run_summary(self, trade_date: date, is_mock: bool) -> tuple[object, ...]:
        return ("STRICT_FIXED_NO_PYRAMIDING", "hash123", 15.5, 6.2)

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
        ]

    def candidate_counts(self, trade_date: date) -> tuple[object, ...]:
        return (5, 3, 2)

    def log_rows(self, trade_date: date) -> list[tuple[object, ...]]:
        rows: list[tuple[object, ...]] = [
            (
                "2026-06-01 22:30:00",
                "INFO",
                "pipeline",
                "[FILTER] removed_by_price=2 removed_by_gap=1 final_count=3",
                "",
                "",
                None,
                None,
            ),
            (
                "2026-06-01 22:31:00",
                "INFO",
                "pipeline",
                "STRICT_FILTER_NO_CANDIDATES",
                "",
                "",
                None,
                None,
            ),
        ]
        if self.with_error_log:
            rows.append(
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
            )
        return rows


def test_export_trade_summary_creates_file_for_day_with_fills(tmp_path) -> None:
    result = export_trade_summary(
        trade_date=date(2026, 6, 1),
        mode="mock",
        output_dir=tmp_path,
        data_source=FakeTradeSummaryDataSource(),
        generated_at=datetime(2026, 6, 2, 6, 0, tzinfo=timezone.utc),
    )

    assert result.path == tmp_path / "2026-06-01_mock_trade_summary.txt"
    content = result.path.read_text(encoding="utf-8")
    assert "매수 체결 수: 1" in content
    assert "매도 체결 수: 1" in content
    assert "TAKE_PROFIT" in content
    assert "STRICT_FIXED_NO_PYRAMIDING" in content


def test_export_trade_summary_creates_file_without_fills(tmp_path) -> None:
    result = export_trade_summary(
        trade_date=date(2026, 6, 1),
        mode="mock",
        output_dir=tmp_path,
        data_source=FakeTradeSummaryDataSource(with_fills=False),
    )

    content = result.path.read_text(encoding="utf-8")
    assert "매수 체결 수: 0" in content
    assert "체결 없음" in content


def test_export_trade_summary_warns_when_entry_profit_sample_is_small(tmp_path) -> None:
    result = export_trade_summary(
        trade_date=date(2026, 6, 1),
        mode="mock",
        output_dir=tmp_path,
        data_source=FakeTradeSummaryDataSource(),
    )

    assert "표본 부족: 전략 판단 금지" in result.path.read_text(encoding="utf-8")


def test_export_trade_summary_includes_error_logs_and_redacts_sensitive_text(tmp_path) -> None:
    result = export_trade_summary(
        trade_date=date(2026, 6, 1),
        mode="mock",
        output_dir=tmp_path,
        data_source=FakeTradeSummaryDataSource(with_error_log=True),
    )

    content = result.path.read_text(encoding="utf-8")
    assert "주문 실패" in content
    assert "secret-token" not in content
    assert "hidden-value" not in content
    assert "[REDACTED]" in content


def test_export_trade_summary_writes_utf8_without_bom(tmp_path) -> None:
    result = export_trade_summary(
        trade_date=date(2026, 6, 1),
        mode="mock",
        output_dir=tmp_path,
        data_source=FakeTradeSummaryDataSource(),
    )

    assert not result.path.read_bytes().startswith(b"\xef\xbb\xbf")
