from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date

from trading_bot.models import BotLog, SellIntent, TradeRecord
from trading_bot.ports import DailyRepository

SellSubmitter = Callable[[SellIntent], dict[str, object]]


class SellIntentExecutor:
    def __init__(
        self,
        submit_order: SellSubmitter,
        repository: DailyRepository,
        today: Callable[[], date],
        mock: bool = True,
    ) -> None:
        self.submit_order = submit_order
        self.repository = repository
        self.today = today
        self.mock = mock

    def execute(self, intents: Iterable[SellIntent]) -> list[TradeRecord]:
        submitted = list(intents)
        successful: list[SellIntent] = []
        trades: list[TradeRecord] = []
        for intent in submitted:
            try:
                self.submit_order(intent)
            except Exception as error:
                self.repository.save_log(
                    BotLog(
                        "ERROR",
                        "execution",
                        f"매도 주문 실패: {intent.ticker} {intent.quantity}주 "
                        f"@ ${intent.limit_price_usd:,.2f} ({error})",
                    )
                )
                continue
            successful.append(intent)
            # 체결 확인 전에는 주문 접수만 기록하고, 실제 보유 수량은 KIS 잔고 조회로 동기화한다.
            trades.append(
                TradeRecord(
                    trade_date=self.today(),
                    ticker=intent.ticker,
                    order_type="SELL",
                    order_price_usd=intent.limit_price_usd,
                    exec_price_usd=None,
                    quantity=intent.quantity,
                    exit_reason=intent.exit_reason,
                    is_mock=self.mock,
                )
            )
        self.repository.save_trades(trades)
        self.repository.save_log(BotLog("INFO", "execution", _sell_log(successful)))
        return trades


def _sell_log(intents: list[SellIntent]) -> str:
    if not intents:
        return "매도 주문 0건: 매도 조건을 만족한 보유 종목이 없습니다."
    details = [
        (
            f"{item.ticker} {item.quantity}주 @ ${item.limit_price_usd:,.2f} "
            f"(사유 {item.exit_reason})"
        )
        for item in intents
    ]
    return f"매도 주문 {len(intents)}건: " + "; ".join(details)
