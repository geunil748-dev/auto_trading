from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from trading_bot.config import TradingSettings
from trading_bot.models import BuyIntent, PositionState


NO_ORDER_INTRADAY_ROUND_LIMIT = "NO_ORDER_INTRADAY_ROUND_LIMIT"
NO_ORDER_ROUND_CAP_REACHED = "NO_ORDER_ROUND_CAP_REACHED"
NO_ORDER_UNFILLED_ORDER = "NO_ORDER_UNFILLED_ORDER"
NO_ORDER_ALREADY_SUBMITTED = "NO_ORDER_ALREADY_SUBMITTED"
NO_ORDER_PYRAMIDING_BLOCKED = "NO_ORDER_PYRAMIDING_BLOCKED"


@dataclass(frozen=True)
class NoOrderDiagnostic:
    ticker: str
    reason: str
    detail: str = ""


def limited_intraday_buy_intents(
    buy_intents: Iterable[BuyIntent],
    positions: Iterable[PositionState],
    submitted_tickers: Iterable[str],
    add_on_tickers: Iterable[str],
    unfilled_tickers: Iterable[str],
    completed_rounds: int,
    settings: TradingSettings,
) -> list[BuyIntent]:
    accepted, _ = limited_intraday_buy_intents_with_diagnostics(
        buy_intents,
        positions,
        submitted_tickers,
        add_on_tickers,
        unfilled_tickers,
        completed_rounds,
        settings,
    )
    return accepted


def limited_intraday_buy_intents_with_diagnostics(
    buy_intents: Iterable[BuyIntent],
    positions: Iterable[PositionState],
    submitted_tickers: Iterable[str],
    add_on_tickers: Iterable[str],
    unfilled_tickers: Iterable[str],
    completed_rounds: int,
    settings: TradingSettings,
) -> tuple[list[BuyIntent], list[NoOrderDiagnostic]]:
    candidates = list(buy_intents)
    diagnostics: list[NoOrderDiagnostic] = []
    if completed_rounds >= settings.max_intraday_entry_rounds:
        return (
            [],
            [
                NoOrderDiagnostic(
                    _ticker(intent.ticker),
                    NO_ORDER_INTRADAY_ROUND_LIMIT,
                    "max_intraday_entry_rounds reached",
                )
                for intent in candidates
            ],
        )

    held = {_ticker(item.ticker): item for item in positions}
    submitted = {_ticker(item) for item in submitted_tickers}
    added = {_ticker(item) for item in add_on_tickers}
    unfilled = {_ticker(item) for item in unfilled_tickers}
    accepted: list[BuyIntent] = []
    for intent in candidates:
        ticker = _ticker(intent.ticker)
        if len(accepted) >= settings.max_intraday_buy_intents_per_round:
            diagnostics.append(
                NoOrderDiagnostic(
                    ticker,
                    NO_ORDER_ROUND_CAP_REACHED,
                    "max_intraday_buy_intents_per_round reached",
                )
            )
            continue
        if ticker in unfilled:
            diagnostics.append(
                NoOrderDiagnostic(ticker, NO_ORDER_UNFILLED_ORDER, "unfilled order exists")
            )
            continue
        reason = "INTRADAY_RECHECK"
        detail = "15분 재평가 후보"
        if ticker in held:
            position = held[ticker]
            if not _pyramiding_allowed(position, ticker, added, settings):
                diagnostics.append(
                    NoOrderDiagnostic(
                        ticker,
                        NO_ORDER_PYRAMIDING_BLOCKED,
                        "pyramiding is disabled or add-on threshold was not met",
                    )
                )
                continue
            reason = "PYRAMIDING"
            detail = f"보유 종목 수익률 {position.profit_rate:.2%} 이상 추세 확인 후 추가 매수"
        elif ticker in submitted:
            diagnostics.append(
                NoOrderDiagnostic(
                    ticker,
                    NO_ORDER_ALREADY_SUBMITTED,
                    "ticker already submitted earlier in the day",
                )
            )
            continue
        accepted.append(_append_entry_reason(intent, reason, detail))
        submitted.add(ticker)
    return accepted, diagnostics


def _ticker(value: str) -> str:
    return value.strip().upper()


def _pyramiding_allowed(
    position: PositionState,
    ticker: str,
    add_on_tickers: set[str],
    settings: TradingSettings,
) -> bool:
    if not settings.enable_pyramiding:
        return False
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
