from __future__ import annotations

from collections.abc import Iterable, Mapping

from trading_bot.config import TradingSettings
from trading_bot.models import AccountState, BuyIntent, ScoreRecord
from trading_bot.risk import position_entry_gate
from trading_bot.scoring import position_fraction_for_score
from trading_bot.strategy import breakout_triggered


def plan_buy_intents(
    selected_scores: Iterable[ScoreRecord],
    breakout_inputs: Mapping[str, tuple[float, float, float, float]],
    account: AccountState,
    settings: TradingSettings,
) -> list[BuyIntent]:
    intents: list[BuyIntent] = []
    invested = account.invested_usd
    cash = account.cash_usd
    for score in selected_scores:
        last, open_price, previous_high, previous_low = breakout_inputs[score.ticker]
        if not breakout_triggered(
            last,
            open_price,
            previous_high,
            previous_low,
            settings.breakout_k,
        ):
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
        quantity = int(order_value // last)
        if not decision.allowed or quantity < 1:
            continue

        filled_value = quantity * last
        intents.append(
            BuyIntent(
                ticker=score.ticker,
                quantity=quantity,
                limit_price_usd=last,
                order_value_usd=filled_value,
                allocation_fraction=fraction,
            )
        )
        invested += filled_value
        cash -= filled_value
    return intents


def _with_invested(account: AccountState, invested_usd: float) -> AccountState:
    return AccountState(
        cash_usd=account.cash_usd,
        equity_usd=account.equity_usd,
        invested_usd=invested_usd,
        open_positions=account.open_positions,
        daily_profit_rate=account.daily_profit_rate,
    )
