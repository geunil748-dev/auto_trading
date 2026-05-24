from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from trading_bot.config import TradingSettings
from trading_bot.models import AccountState, BuyIntent, RankedStock
from trading_bot.risk import position_entry_gate

QuoteReader = Callable[[str], dict[str, Any]]
LIST_ALLOCATION_FRACTION = 0.01


def collect_ranked_buy_intents(
    rankings: Iterable[RankedStock],
    quote: QuoteReader,
    account: AccountState,
    settings: TradingSettings,
    limit: int = 3,
) -> list[BuyIntent]:
    intents: list[BuyIntent] = []
    cash = account.cash_usd
    invested = account.invested_usd
    for item in rankings:
        if len(intents) >= limit or account.open_positions + len(intents) >= settings.max_open_positions:
            break
        last = _float_field(quote(item.ticker), "last", "LAST")
        if last is None or not settings.min_price_usd <= last <= settings.max_price_usd:
            continue

        order_value = min(cash, account.equity_usd * LIST_ALLOCATION_FRACTION)
        quantity = int(order_value // last)
        if quantity < 1 or not position_entry_gate(
            _with_invested(account, invested),
            order_value,
            settings,
        ).allowed:
            continue

        filled_value = quantity * last
        intents.append(
            BuyIntent(
                ticker=item.ticker,
                quantity=quantity,
                limit_price_usd=last,
                order_value_usd=filled_value,
                allocation_fraction=LIST_ALLOCATION_FRACTION,
            )
        )
        cash -= filled_value
        invested += filled_value
    return intents


def _float_field(row: dict[str, Any], *fields: str) -> float | None:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return float(str(value).replace(",", ""))
    return None


def _with_invested(account: AccountState, invested_usd: float) -> AccountState:
    return AccountState(
        cash_usd=account.cash_usd,
        equity_usd=account.equity_usd,
        invested_usd=invested_usd,
        open_positions=account.open_positions,
        daily_profit_rate=account.daily_profit_rate,
    )
