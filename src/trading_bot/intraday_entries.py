from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

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
        reason = "INTRADAY_RECHECK"
        detail = "15분 재평가 후보"
        if ticker in held:
            position = held[ticker]
            if not _pyramiding_allowed(position, ticker, added, settings):
                continue
            reason = "PYRAMIDING"
            detail = f"보유 종목 수익률 {position.profit_rate:.2%} 이상 추세 확인 후 추가 매수"
        elif ticker in submitted:
            continue
        accepted.append(_append_entry_reason(intent, reason, detail))
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


def _append_entry_reason(intent: BuyIntent, reason: str, detail: str) -> BuyIntent:
    reasons = [item for item in intent.entry_reason.split("+") if item]
    if reason not in reasons:
        reasons.append(reason)
    detail_text = "; ".join(item for item in (intent.entry_reason_detail, detail) if item)
    return replace(intent, entry_reason="+".join(reasons), entry_reason_detail=detail_text)
