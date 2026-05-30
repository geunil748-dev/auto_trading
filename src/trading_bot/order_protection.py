from __future__ import annotations

from collections.abc import Callable

from trading_bot.config import TradingSettings
from trading_bot.models import BotLog, BuyIntent

QuoteReader = Callable[[str], dict[str, object]]


def buy_order_protection_log(
    intent: BuyIntent,
    settings: TradingSettings,
    quote_reader: QuoteReader | None,
) -> BotLog | None:
    """주문 직전 호가와 예상 체결가가 과도하게 벌어졌는지 확인한다."""
    if quote_reader is None:
        return None
    try:
        quote = quote_reader(intent.ticker)
    except Exception as exc:
        return BotLog(
            "WARNING",
            "execution",
            f"호가 조회 실패로 주문 보호 확인을 건너뜁니다: {intent.ticker} ({exc})",
            symbol=intent.ticker,
            reject_reason="QUOTE_LOOKUP_FAILED",
        )
    bid = _first_number(quote, "bestBid", "bid", "BID", "pbid", "PBID", "ovrs_bidp")
    ask = _first_number(quote, "bestAsk", "ask", "ASK", "pask", "PASK", "ovrs_askp")
    current = _first_number(
        quote,
        "currentPrice",
        "last",
        "LAST",
        "base",
        "BASE",
        "ovrs_now_pric",
        "stck_prpr",
    )
    if current <= 0:
        current = intent.limit_price_usd
    if bid > 0 and ask > 0 and current > 0:
        spread_rate = (ask - bid) / current * 100
        if spread_rate > settings.max_bid_ask_spread_rate:
            return _reject_log(
                intent,
                "BID_ASK_SPREAD_TOO_WIDE",
                spread_rate,
                settings.max_bid_ask_spread_rate,
                "호가 스프레드가 넓어 매수 주문을 차단했습니다.",
            )
    expected = ask if ask > 0 else intent.limit_price_usd
    if expected > 0 and current > 0:
        gap_rate = abs(expected - current) / current * 100
        if gap_rate > settings.max_expected_fill_price_gap_rate:
            return _reject_log(
                intent,
                "EXPECTED_FILL_PRICE_GAP_TOO_HIGH",
                gap_rate,
                settings.max_expected_fill_price_gap_rate,
                "예상 체결가와 현재가 차이가 커 매수 주문을 차단했습니다.",
            )
    return None


def _reject_log(
    intent: BuyIntent,
    reason: str,
    actual: float,
    threshold: float,
    message: str,
) -> BotLog:
    return BotLog(
        "WARNING",
        "execution",
        f"{message} {intent.ticker} 실제 {actual:.2f}% / 기준 {threshold:.2f}%",
        symbol=intent.ticker,
        reject_reason=reason,
        actual_value=actual,
        threshold_value=threshold,
    )


def _first_number(row: dict[str, object], *fields: str) -> float:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for field in fields:
        value = row.get(field)
        if value is None:
            value = lowered.get(field.lower())
        number = _number(value)
        if number > 0:
            return number
    return 0.0


def _number(value: object) -> float:
    try:
        return float(str(value or "0").replace(",", "").strip())
    except ValueError:
        return 0.0
