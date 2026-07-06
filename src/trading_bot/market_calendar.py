from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
US_MARKET_HOLIDAY_NAMES_2026 = {
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 19): "Martin Luther King Jr. Day",
    date(2026, 2, 16): "Washington's Birthday",
    date(2026, 4, 3): "Good Friday",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth National Independence Day",
    date(2026, 7, 3): "Independence Day observed",
    date(2026, 9, 7): "Labor Day",
    date(2026, 11, 26): "Thanksgiving Day",
    date(2026, 12, 25): "Christmas Day",
}
US_MARKET_HOLIDAYS_2026 = frozenset(US_MARKET_HOLIDAY_NAMES_2026)


def current_us_market_date(now: datetime | None = None) -> date:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(NEW_YORK).date()


def is_us_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in US_MARKET_HOLIDAYS_2026


def us_market_holiday_name(day: date) -> str:
    return US_MARKET_HOLIDAY_NAMES_2026.get(day, "")


def is_current_us_trading_day(now: datetime | None = None) -> bool:
    return is_us_trading_day(current_us_market_date(now))


def is_current_us_regular_session(now: datetime | None = None) -> bool:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(NEW_YORK)
    return is_us_trading_day(local.date()) and time(9, 30) <= local.time() < time(16, 0)
