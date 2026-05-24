from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
US_MARKET_HOLIDAYS_2026 = frozenset(
    {
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    }
)


def current_us_market_date(now: datetime | None = None) -> date:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(NEW_YORK).date()


def is_us_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in US_MARKET_HOLIDAYS_2026


def is_current_us_trading_day(now: datetime | None = None) -> bool:
    return is_us_trading_day(current_us_market_date(now))


def is_current_us_regular_session(now: datetime | None = None) -> bool:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(NEW_YORK)
    return is_us_trading_day(local.date()) and time(9, 30) <= local.time() < time(16, 0)
