from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from datetime import date

from trading_bot.config import TradingSettings
from trading_bot.models import BotLog, BuyIntent, TradeRecord
from trading_bot.order_protection import QuoteReader, buy_order_protection_log
from trading_bot.ports import DailyRepository
from trading_bot.strategy_metadata import strategy_metadata_from_settings

OrderSubmitter = Callable[[BuyIntent], dict[str, object]]


class BuyIntentExecutor:
    def __init__(
        self,
        submit_order: OrderSubmitter,
        repository: DailyRepository,
        today: Callable[[], date],
        mock: bool = True,
        settings: TradingSettings | None = None,
        quote_reader: QuoteReader | None = None,
        retry_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.submit_order = submit_order
        self.repository = repository
        self.today = today
        self.mock = mock
        self.settings = settings or TradingSettings()
        self.quote_reader = quote_reader
        self.retry_sleep = retry_sleep

    def execute(self, intents: Iterable[BuyIntent]) -> list[TradeRecord]:
        submitted = list(intents)
        successful: list[BuyIntent] = []
        trades: list[TradeRecord] = []
        strategy_metadata = strategy_metadata_from_settings(self.settings)
        for intent in submitted:
            protection_log = buy_order_protection_log(intent, self.settings, self.quote_reader)
            if protection_log is not None and protection_log.reject_reason != "QUOTE_LOOKUP_FAILED":
                self.repository.save_log(protection_log)
                continue
            if protection_log is not None:
                self.repository.save_log(protection_log)
            submitted_result = self._submit_with_retry(intent)
            if submitted_result is None:
                continue
            retry_count, response = submitted_result
            _mark_candidate_evaluation_order_submitted(
                self.repository,
                intent,
                self.today(),
                _order_id(response),
            )
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
                    order_status="SUCCESS",
                    retry_count=retry_count,
                    order_qty=intent.quantity,
                    filled_qty=0,
                    remaining_qty=intent.quantity,
                    strategy_version=strategy_metadata.strategy_version,
                    settings_snapshot_hash=strategy_metadata.settings_snapshot_hash,
                    settings_snapshot_json=strategy_metadata.settings_snapshot_json,
                )
            )
        self.repository.save_trades(trades)
        self.repository.save_log(BotLog("INFO", "execution", _buy_log(successful)))
        return trades

    def _submit_with_retry(self, intent: BuyIntent) -> tuple[int, dict[str, object]] | None:
        max_retries = max(0, int(self.settings.max_order_retry_count))
        for attempt in range(max_retries + 1):
            try:
                response = self.submit_order(intent)
                return attempt, response
            except Exception as error:
                self.repository.save_log(
                    BotLog(
                        "ERROR",
                        "execution",
                        f"매수 주문 API 오류: {intent.ticker} {intent.quantity}주 "
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
                            f"매수 주문 실패: {intent.ticker} 최대 재시도 {max_retries}회 초과",
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
                        f"매수 주문 재시도: {intent.ticker} {attempt + 1}/{max_retries}",
                        symbol=intent.ticker,
                        reject_reason="RETRY",
                        actual_value=float(attempt + 1),
                        threshold_value=float(max_retries),
                    )
                )
                self.retry_sleep(max(0, self.settings.order_retry_delay_seconds))
        return None


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


def _mark_candidate_evaluation_order_submitted(
    repository: DailyRepository,
    intent: BuyIntent,
    trade_date: date,
    order_id: str | None,
) -> None:
    if not hasattr(repository, "mark_candidate_evaluation_order_submitted"):
        return
    try:
        repository.mark_candidate_evaluation_order_submitted(intent.ticker, trade_date, order_id)
    except Exception as exc:
        try:
            repository.save_log(
                BotLog(
                    "ERROR",
                    "candidate_evaluation",
                    f"candidate_evaluation_save_failed symbol={intent.ticker} error={exc}",
                    symbol=intent.ticker,
                    reject_reason="CANDIDATE_EVALUATION_SAVE_FAILED",
                )
            )
        except Exception:
            pass


def _order_id(response: dict[str, object]) -> str | None:
    output = response.get("output")
    if isinstance(output, dict):
        for key in ("ODNO", "odno", "order_no", "orderNo"):
            value = output.get(key)
            if value:
                return str(value)
    for key in ("ODNO", "odno", "order_no", "orderNo"):
        value = response.get(key)
        if value:
            return str(value)
    return None
