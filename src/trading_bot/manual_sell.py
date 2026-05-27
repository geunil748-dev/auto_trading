from __future__ import annotations

from typing import Any

from trading_bot.composition import build_live_exit_poll, build_mock_sell_executor
from trading_bot.config import load_kis_settings, load_settings
from trading_bot.models import SellIntent


def submit_manual_mock_sell(ticker: str, quantity: int | None = None) -> dict[str, Any]:
    """화면에서 요청한 모의투자 수동 매도 주문을 접수한다."""
    requested_ticker = ticker.strip().upper()
    if not requested_ticker:
        raise ValueError("매도할 종목이 없습니다.")

    settings = load_settings()
    kis_settings = load_kis_settings()
    accounts, _monitor, repository = build_live_exit_poll(settings, kis_settings)
    position = next(
        (item for item in accounts.positions() if item.ticker.upper() == requested_ticker),
        None,
    )
    if position is None:
        raise ValueError(f"{requested_ticker} 보유 수량을 찾지 못했습니다.")

    sell_quantity = position.quantity if quantity is None else min(quantity, position.quantity)
    if sell_quantity <= 0:
        raise ValueError("매도 수량은 1주 이상이어야 합니다.")

    sell_price = position.last_price_usd or position.entry_price_usd
    if sell_price <= 0:
        raise ValueError(f"{requested_ticker} 현재가를 확인하지 못했습니다.")

    intent = SellIntent(
        ticker=requested_ticker,
        quantity=sell_quantity,
        limit_price_usd=sell_price,
        exit_reason="MANUAL_SELL",
        entry_price_usd=position.entry_price_usd,
    )
    trades = build_mock_sell_executor(kis_settings, repository).execute([intent])
    return {
        "ok": True,
        "ticker": requested_ticker,
        "quantity": sell_quantity,
        "price": sell_price,
        "trades": [item.__dict__ for item in trades],
    }


def submit_manual_mock_sell_all() -> dict[str, Any]:
    """화면에서 요청한 모의투자 보유 종목 전량 매도를 접수한다."""
    settings = load_settings()
    kis_settings = load_kis_settings()
    accounts, _monitor, repository = build_live_exit_poll(settings, kis_settings)
    intents = [_sell_intent_from_position(item, item.quantity) for item in accounts.positions()]
    if not intents:
        raise ValueError("매도할 보유 종목이 없습니다.")
    trades = build_mock_sell_executor(kis_settings, repository).execute(intents)
    return {
        "ok": True,
        "count": len(intents),
        "quantity": sum(item.quantity for item in intents),
        "tickers": [item.ticker for item in intents],
        "trades": [item.__dict__ for item in trades],
    }


def _sell_intent_from_position(position: Any, quantity: int) -> SellIntent:
    sell_quantity = min(quantity, position.quantity)
    if sell_quantity <= 0:
        raise ValueError("매도 수량은 1주 이상이어야 합니다.")
    sell_price = position.last_price_usd or position.entry_price_usd
    if sell_price <= 0:
        raise ValueError(f"{position.ticker} 현재가를 확인하지 못했습니다.")
    return SellIntent(
        ticker=position.ticker.strip().upper(),
        quantity=sell_quantity,
        limit_price_usd=sell_price,
        exit_reason="MANUAL_SELL_ALL",
        entry_price_usd=position.entry_price_usd,
    )
