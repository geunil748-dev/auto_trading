from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from datetime import date

from trading_bot.config import TradingSettings
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
        settings: TradingSettings | None = None,
        retry_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.submit_order = submit_order
        self.repository = repository
        self.today = today
        self.mock = mock
        self.settings = settings or TradingSettings()
        self.retry_sleep = retry_sleep

    def execute(self, intents: Iterable[SellIntent]) -> list[TradeRecord]:
        submitted = list(intents)
        successful: list[SellIntent] = []
        trades: list[TradeRecord] = []
        for intent in submitted:
            retry_count = self._submit_with_retry(intent)
            if retry_count is None:
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
                    entry_price_usd=intent.entry_price_usd,
                    exit_reason=intent.exit_reason,
                    is_mock=self.mock,
                    order_status="SUCCESS",
                    retry_count=retry_count,
                    order_qty=intent.quantity,
                    filled_qty=0,
                    remaining_qty=intent.quantity,
                )
            )
        self.repository.save_trades(trades)
        self.repository.save_log(BotLog("INFO", "execution", _sell_log(successful)))
        return trades

    def _submit_with_retry(self, intent: SellIntent) -> int | None:
        max_retries = max(0, int(self.settings.max_order_retry_count))
        for attempt in range(max_retries + 1):
            try:
                self.submit_order(intent)
                return attempt
            except Exception as error:
                self.repository.save_log(
                    BotLog(
                        "ERROR",
                        "execution",
                        f"매도 주문 API 오류: {intent.ticker} {intent.quantity}주 "
                        f"@ ${intent.limit_price_usd:,.2f} ({error})",
                        symbol=intent.ticker,
                        reject_reason="API_ERROR",
                        actual_value=float(attempt),
                        threshold_value=float(max_retries),
                    )
                )
                if attempt >= max_retries:
                    self.repository.save_log(
                        BotLog(
                            "ERROR",
                            "execution",
                            f"매도 주문 실패: {intent.ticker} 최대 재시도 {max_retries}회 초과",
                            symbol=intent.ticker,
                            reject_reason="ORDER_FAILED",
                            actual_value=float(attempt),
                            threshold_value=float(max_retries),
                        )
                    )
                    return None
                self.repository.save_log(
                    BotLog(
                        "WARNING",
                        "execution",
                        f"매도 주문 재시도: {intent.ticker} {attempt + 1}/{max_retries}",
                        symbol=intent.ticker,
                        reject_reason="RETRY",
                        actual_value=float(attempt + 1),
                        threshold_value=float(max_retries),
                    )
                )
                self.retry_sleep(max(0, self.settings.order_retry_delay_seconds))
        return None


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
