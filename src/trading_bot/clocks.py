from __future__ import annotations

from datetime import date

from trading_bot.trading_date import current_trade_date


class SystemClock:
    def today(self) -> date:
        return current_trade_date()
