from datetime import date, datetime, timezone

from trading_bot.market_calendar import (
    current_us_market_date,
    is_current_us_regular_session,
    is_us_trading_day,
)


def test_market_calendar_skips_weekends_and_2026_holidays() -> None:
    assert is_us_trading_day(date(2026, 5, 22))
    assert not is_us_trading_day(date(2026, 5, 23))
    assert not is_us_trading_day(date(2026, 5, 25))


def test_current_market_date_uses_new_york_clock() -> None:
    assert current_us_market_date(datetime(2026, 5, 23, 3, tzinfo=timezone.utc)) == date(
        2026, 5, 22
    )


def test_regular_session_uses_new_york_market_hours() -> None:
    assert not is_current_us_regular_session(
        datetime(2026, 5, 22, 13, 29, tzinfo=timezone.utc)
    )
    assert is_current_us_regular_session(
        datetime(2026, 5, 22, 13, 30, tzinfo=timezone.utc)
    )
    assert not is_current_us_regular_session(
        datetime(2026, 5, 22, 20, 0, tzinfo=timezone.utc)
    )
