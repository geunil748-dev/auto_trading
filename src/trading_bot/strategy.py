from __future__ import annotations


def volatility_breakout_price(
    open_price_usd: float,
    previous_high_usd: float,
    previous_low_usd: float,
    k: float = 0.5,
) -> float:
    if min(open_price_usd, previous_high_usd, previous_low_usd) <= 0:
        raise ValueError("prices must be positive")
    if previous_high_usd < previous_low_usd:
        raise ValueError("previous high cannot be below previous low")
    return open_price_usd + (previous_high_usd - previous_low_usd) * k


def breakout_triggered(
    last_price_usd: float,
    open_price_usd: float,
    previous_high_usd: float,
    previous_low_usd: float,
    k: float = 0.5,
) -> bool:
    return last_price_usd >= volatility_breakout_price(
        open_price_usd,
        previous_high_usd,
        previous_low_usd,
        k,
    )
