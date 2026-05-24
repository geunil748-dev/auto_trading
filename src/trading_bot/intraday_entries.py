from __future__ import annotations

from collections.abc import Iterable

from trading_bot.config import TradingSettings
from trading_bot.models import BuyIntent, PositionState


def limited_intraday_buy_intents(
    buy_intents: Iterable[BuyIntent],
    positions: Iterable[PositionState],
    submitted_tickers: Iterable[str],
    add_on_tickers: Iterable[str],
    unfilled_tickers: Iterable[str],
    completed_rounds: int,
    settings: TradingSettings,
) -> list[BuyIntent]:
    if completed_rounds >= settings.max_intraday_entry_rounds:
        return []

    held = {_ticker(item.ticker): item for item in positions}
    submitted = {_ticker(item) for item in submitted_tickers}
    added = {_ticker(item) for item in add_on_tickers}
    unfilled = {_ticker(item) for item in unfilled_tickers}
    accepted: list[BuyIntent] = []
    for intent in buy_intents:
        if len(accepted) >= settings.max_intraday_buy_intents_per_round:
            break
        ticker = _ticker(intent.ticker)
        if ticker in unfilled:
            continue
        if ticker in held:
            if not _pyramiding_allowed(held[ticker], ticker, added, settings):
                continue
        elif ticker in submitted:
            continue
        accepted.append(intent)
        submitted.add(ticker)
    return accepted


def _ticker(value: str) -> str:
    return value.strip().upper()


def _pyramiding_allowed(
    position: PositionState,
    ticker: str,
    add_on_tickers: set[str],
    settings: TradingSettings,
) -> bool:
    return (
        position.profit_rate >= settings.min_pyramiding_profit_rate
        and ticker not in add_on_tickers
    )
