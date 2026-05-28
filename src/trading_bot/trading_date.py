from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from trading_bot.market_calendar import current_us_market_date

KOREA = ZoneInfo("Asia/Seoul")


def current_trade_date(now: datetime | None = None) -> date:
    """시스템 전체에서 사용하는 표준 거래일을 반환한다."""
    mode = os.getenv("TRADING_DAY_MODE", "us_market").strip().lower()
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    if mode == "korea_session":
        return _korea_session_date(value)
    if mode == "local_date":
        return value.astimezone().date()
    return current_us_market_date(value)


def _korea_session_date(value: datetime) -> date:
    # 한국 시간 22시 전까지는 전날 밤에 시작한 미국장 세션으로 묶는다.
    local = value.astimezone(KOREA)
    if local.hour < 22:
        return (local - timedelta(days=1)).date()
    return local.date()
