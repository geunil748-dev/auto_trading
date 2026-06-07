import io
import json
from datetime import date

from trading_bot.monitor_request import (
    _optional_bool,
    _optional_float,
    _optional_int,
    _query_date,
    _query_limit,
    _query_mode,
    _query_tickers,
    read_json_body,
)


def test_query_date_parses_valid_iso_date() -> None:
    assert _query_date("/api/history?date=2026-06-03") == date(2026, 6, 3)


def test_query_date_falls_back_to_current_trade_date(monkeypatch) -> None:
    monkeypatch.setattr(
        "trading_bot.monitor_request.current_trade_date",
        lambda: date(2026, 6, 8),
    )

    assert _query_date("/api/history?date=bad-date") == date(2026, 6, 8)


def test_query_mode_only_accepts_mock_or_real() -> None:
    assert _query_mode("/api/daily-summary?mode=mock") == "mock"
    assert _query_mode("/api/daily-summary?mode=REAL") == "real"
    assert _query_mode("/api/daily-summary?mode=test") is None
    assert _query_mode("/api/daily-summary") is None


def test_query_limit_uses_default_clamps_maximum_and_falls_back_for_invalid() -> None:
    assert _query_limit("/api/daily-summary", default=30, maximum=100) == 30
    assert _query_limit("/api/daily-summary?limit=200", default=30, maximum=100) == 100
    assert _query_limit("/api/daily-summary?limit=0", default=30, maximum=100) == 1
    assert _query_limit("/api/daily-summary?limit=abc", default=30, maximum=100) == 30


def test_query_tickers_handles_empty_all_and_comma_separated_values() -> None:
    assert _query_tickers("/api/manual-screening") is None
    assert _query_tickers("/api/manual-screening?ticker=ALL") is None
    assert _query_tickers("/api/manual-screening?ticker=aapl, tsla,,nvda") == [
        "AAPL",
        "TSLA",
        "NVDA",
    ]


def test_optional_int_removes_commas_and_share_suffix() -> None:
    assert _optional_int("1,000\uc8fc") == 1000
    assert _optional_int("") is None


def test_optional_float_removes_commas() -> None:
    assert _optional_float("1,234.5") == 1234.5
    assert _optional_float(None) is None


def test_optional_bool_handles_bool_and_true_like_strings() -> None:
    assert _optional_bool(True) is True
    assert _optional_bool("true") is True
    assert _optional_bool("1") is True
    assert _optional_bool("yes") is True
    assert _optional_bool("false") is False
    assert _optional_bool("") is None


def test_read_json_body_returns_empty_dict_for_empty_body() -> None:
    assert read_json_body(io.BytesIO(b""), "0") == {}


def test_read_json_body_returns_empty_dict_for_non_dict_json() -> None:
    raw = json.dumps(["not", "dict"]).encode("utf-8")

    assert read_json_body(io.BytesIO(raw), str(len(raw))) == {}


def test_read_json_body_respects_max_bytes() -> None:
    raw = json.dumps({"ok": True}).encode("utf-8") + b"ignored"

    assert read_json_body(io.BytesIO(raw), str(len(raw)), max_bytes=len(raw) - 7) == {
        "ok": True
    }
