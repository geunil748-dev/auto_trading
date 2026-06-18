from __future__ import annotations

from dataclasses import dataclass

from trading_bot.config import TradingSettings
from trading_bot.models import AccountState, CandidateSnapshot, PositionState


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str | None = None
    bypass_reason: str | None = None


MARKET_BELOW_MA20 = "MARKET_BELOW_MA20"
MARKET_BELOW_MA20_BYPASSED = "MARKET_BELOW_MA20_BYPASSED"


def global_entry_gate(
    nasdaq_price_usd: float,
    nasdaq_ma20_usd: float,
    fx_change_rate: float,
    account: AccountState,
    settings: TradingSettings,
) -> RiskDecision:
    bypass_reason = None
    if nasdaq_price_usd < nasdaq_ma20_usd:
        if _market_below_ma20_bypass_allowed(settings):
            bypass_reason = MARKET_BELOW_MA20_BYPASSED
        else:
            return RiskDecision(False, MARKET_BELOW_MA20)
    if abs(fx_change_rate) >= settings.max_fx_change:
        return RiskDecision(False, "FX_VOLATILITY")
    if account.daily_profit_rate <= settings.max_daily_account_loss:
        return RiskDecision(False, "DAILY_ACCOUNT_LOSS")
    if account.open_positions >= settings.max_open_positions:
        return RiskDecision(False, "OPEN_POSITION_LIMIT")
    if account.equity_usd <= 0:
        return RiskDecision(False, "INVALID_ACCOUNT_EQUITY")
    if account.invested_usd / account.equity_usd >= settings.max_account_exposure:
        return RiskDecision(False, "ACCOUNT_EXPOSURE_LIMIT")
    return RiskDecision(True, bypass_reason=bypass_reason)


def _market_below_ma20_bypass_allowed(settings: TradingSettings) -> bool:
    return (
        bool(settings.allow_market_below_ma20_bypass)
        and settings.app_mode == "test"
        and bool(settings.mock_trading)
    )


def defensive_candidate_gate(
    candidate: CandidateSnapshot,
    settings: TradingSettings,
) -> RiskDecision:
    if candidate.price_usd < settings.min_price_usd:
        return RiskDecision(False, "PENNY_STOCK")
    if candidate.price_usd > settings.max_price_usd:
        return RiskDecision(False, "PRICE_CAP")
    if candidate.opening_gap >= settings.max_opening_gap:
        return RiskDecision(False, "OPENING_GAP")
    return RiskDecision(True)


def position_entry_gate(
    account: AccountState,
    proposed_order_usd: float,
    settings: TradingSettings,
) -> RiskDecision:
    if proposed_order_usd <= 0:
        return RiskDecision(False, "INVALID_ORDER_VALUE")
    if account.equity_usd <= 0:
        return RiskDecision(False, "INVALID_ACCOUNT_EQUITY")
    if proposed_order_usd / account.equity_usd > settings.max_position_exposure:
        return RiskDecision(False, "POSITION_EXPOSURE_LIMIT")
    next_exposure = (account.invested_usd + proposed_order_usd) / account.equity_usd
    if next_exposure > settings.max_account_exposure:
        return RiskDecision(False, "ACCOUNT_EXPOSURE_LIMIT")
    return RiskDecision(True)


def hard_stop_triggered(position: PositionState, settings: TradingSettings) -> bool:
    return position.profit_rate <= settings.max_position_loss
