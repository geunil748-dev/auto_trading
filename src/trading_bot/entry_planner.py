from __future__ import annotations

from collections.abc import Iterable, Mapping

from trading_bot.config import TradingSettings
from trading_bot.models import AccountState, BreakoutInput, BuyIntent, ScoreRecord
from trading_bot.risk import position_entry_gate
from trading_bot.scoring import position_fraction_for_score
from trading_bot.strategy import breakout_triggered


def plan_buy_intents(
    selected_scores: Iterable[ScoreRecord],
    breakout_inputs: Mapping[str, BreakoutInput | tuple[float, float, float, float]],
    account: AccountState,
    settings: TradingSettings,
) -> list[BuyIntent]:
    intents: list[BuyIntent] = []
    invested = account.invested_usd
    cash = account.cash_usd
    for score in selected_scores:
        breakout = _breakout_input(breakout_inputs[score.ticker])
        threshold = _breakout_threshold(breakout, settings)
        if not breakout_triggered(
            breakout.last_price_usd,
            breakout.open_price_usd,
            breakout.previous_high_usd,
            breakout.previous_low_usd,
            settings.breakout_k,
        ):
            continue
        if not _entry_timing_allowed(breakout, threshold, settings):
            continue

        fraction = min(
            position_fraction_for_score(score.total_score, settings),
            settings.max_position_exposure,
        )
        order_value = min(cash, account.equity_usd * fraction)
        decision = position_entry_gate(
            _with_invested(account, invested),
            order_value,
            settings,
        )
        quantity = int(order_value // breakout.last_price_usd)
        if not decision.allowed or quantity < 1:
            continue

        filled_value = quantity * breakout.last_price_usd
        reason, detail = _entry_reason(score)
        intents.append(
            BuyIntent(
                ticker=score.ticker,
                quantity=quantity,
                limit_price_usd=breakout.last_price_usd,
                order_value_usd=filled_value,
                allocation_fraction=fraction,
                entry_reason=reason,
                entry_reason_detail=detail,
            )
        )
        invested += filled_value
        cash -= filled_value
    return intents


def _breakout_input(value: BreakoutInput | tuple[float, float, float, float]) -> BreakoutInput:
    if isinstance(value, BreakoutInput):
        return value
    last, open_price, previous_high, previous_low = value
    return BreakoutInput(last, open_price, previous_high, previous_low)


def _breakout_threshold(breakout: BreakoutInput, settings: TradingSettings) -> float:
    return breakout.open_price_usd + (
        breakout.previous_high_usd - breakout.previous_low_usd
    ) * settings.breakout_k


def _entry_timing_allowed(
    breakout: BreakoutInput,
    threshold: float,
    settings: TradingSettings,
) -> bool:
    if _price_change_from_open(breakout) > settings.max_entry_price_change:
        return False
    if (
        settings.breakout_hold_minutes > 0
        and breakout.minutes_above_breakout > 0
        and breakout.minutes_above_breakout < settings.breakout_hold_minutes
    ):
        return False
    if settings.require_5m_close_above_breakout and (
        breakout.recent_5m_close_usd is not None and breakout.recent_5m_close_usd < threshold
    ):
        return False
    if settings.require_5m_volume_increase and _has_volume_data(breakout) and not _volume_increased(breakout):
        return False
    if settings.require_vwap_or_ma20 and _has_vwap_or_ma20_data(breakout) and not _above_vwap_or_ma20(breakout):
        return False
    if (
        settings.require_pullback_rebreak
        and breakout.pulled_back_after_breakout is not None
        and not breakout.pulled_back_after_breakout
    ):
        return False
    return True


def _price_change_from_open(breakout: BreakoutInput) -> float:
    if breakout.open_price_usd <= 0:
        return 0.0
    return (breakout.last_price_usd - breakout.open_price_usd) / breakout.open_price_usd


def _volume_increased(breakout: BreakoutInput) -> bool:
    return breakout.current_5m_volume > breakout.previous_5m_average_volume


def _has_volume_data(breakout: BreakoutInput) -> bool:
    return breakout.current_5m_volume is not None and breakout.previous_5m_average_volume is not None


def _above_vwap_or_ma20(breakout: BreakoutInput) -> bool:
    refs = [
        value
        for value in (breakout.vwap_usd, breakout.intraday_ma20_usd)
        if value is not None and value > 0
    ]
    return bool(refs) and any(breakout.last_price_usd >= value for value in refs)


def _has_vwap_or_ma20_data(breakout: BreakoutInput) -> bool:
    return any(value is not None and value > 0 for value in (breakout.vwap_usd, breakout.intraday_ma20_usd))


def _entry_reason(score: ScoreRecord) -> tuple[str, str]:
    reasons = ["OPENING_BREAKOUT"]
    if score.news_score >= 60:
        reasons.append("NEWS_POSITIVE")
    if score.chart_score >= 60:
        reasons.append("CHART_POSITIVE")
    detail = (
        f"총점 {score.total_score:.1f}, "
        f"뉴스 {score.news_score:.1f}, 차트 {score.chart_score:.1f}"
    )
    return "+".join(reasons), detail


def _with_invested(account: AccountState, invested_usd: float) -> AccountState:
    return AccountState(
        cash_usd=account.cash_usd,
        equity_usd=account.equity_usd,
        invested_usd=invested_usd,
        open_positions=account.open_positions,
        daily_profit_rate=account.daily_profit_rate,
    )
