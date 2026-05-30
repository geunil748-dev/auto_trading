from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date

from trading_bot.models import BotLog, BuyIntent, TradeRecord
from trading_bot.ports import DailyRepository

OrderSubmitter = Callable[[BuyIntent], dict[str, object]]


class BuyIntentExecutor:
    def __init__(
        self,
        submit_order: OrderSubmitter,
        repository: DailyRepository,
        today: Callable[[], date],
        mock: bool = True,
    ) -> None:
        self.submit_order = submit_order
        self.repository = repository
        self.today = today
        self.mock = mock

    def execute(self, intents: Iterable[BuyIntent]) -> list[TradeRecord]:
        submitted = list(intents)
        successful: list[BuyIntent] = []
        trades: list[TradeRecord] = []
        for intent in submitted:
            try:
                self.submit_order(intent)
            except Exception as error:
                self.repository.save_log(
                    BotLog(
                        "ERROR",
                        "execution",
                        f"매수 주문 실패: {intent.ticker} {intent.quantity}주 "
                        f"@ ${intent.limit_price_usd:,.2f} ({error})",
                    )
                )
                continue
            successful.append(intent)
            trades.append(
                TradeRecord(
                    trade_date=self.today(),
                    ticker=intent.ticker,
                    order_type="BUY",
                    order_price_usd=intent.limit_price_usd,
                    exec_price_usd=None,
                    quantity=intent.quantity,
                    entry_reason=intent.entry_reason,
                    entry_reason_detail=intent.entry_reason_detail,
                    is_mock=self.mock,
                )
            )
        self.repository.save_trades(trades)
        self.repository.save_log(BotLog("INFO", "execution", _buy_log(successful)))
        return trades


def _buy_log(intents: list[BuyIntent]) -> str:
    if not intents:
        return "매수 주문 0건: 실행할 매수 후보가 없습니다."
    details = [
        (
            f"{item.ticker} {item.quantity}주 @ ${item.limit_price_usd:,.2f} "
            f"(주문금액 ${item.order_value_usd:,.2f}, 배분 {item.allocation_fraction:.1%}, "
            f"사유 {item.entry_reason})"
        )
        for item in intents
    ]
    return f"매수 주문 {len(intents)}건: " + "; ".join(details)
