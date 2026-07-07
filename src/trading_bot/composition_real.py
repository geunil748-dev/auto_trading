from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from trading_bot.adapters.kis_account import KisAccountReader
from trading_bot.adapters.kis_http import KisJsonClient
from trading_bot.adapters.kis_orders_real import KisRealBuySubmitter, KisRealSellSubmitter
from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.clocks import SystemClock
from trading_bot.composition_shared import build_kis_live_dry_run, build_kis_live_exit_poll
from trading_bot.config import KisSettings, TradingSettings
from trading_bot.models import (
    BotLog,
    CandidateEvaluation,
    DailyScore,
    DailyTarget,
    FillRecord,
    TradeRecord,
    TradingEvent,
)
from trading_bot.order_execution import BuyIntentExecutor
from trading_bot.pipeline import CandidateNotificationSender
from trading_bot.ports import DailyRepository
from trading_bot.real_trading_control import load_real_trading_control
from trading_bot.sell_execution import SellIntentExecutor


def build_real_live_dry_run(
    settings: TradingSettings,
    kis_settings: KisSettings,
    *,
    candidate_notification_sender: CandidateNotificationSender | None = None,
):
    repository = ReadOnlyDailyRepository()
    return build_kis_live_dry_run(
        settings,
        kis_settings,
        account_mock=False,
        repository=repository,
        candidate_notification_sender=candidate_notification_sender,
    )


def build_real_live_exit_poll(
    settings: TradingSettings,
    kis_settings: KisSettings,
):
    return build_kis_live_exit_poll(settings, kis_settings, account_mock=False)


def build_real_readonly_account(kis_settings: KisSettings) -> KisAccountReader:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    return KisAccountReader(kis, kis_settings, mock=False)


def build_real_buy_executor(
    kis_settings: KisSettings,
    repository: DailyRepository,
    settings: TradingSettings,
) -> BuyIntentExecutor:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    control = load_real_trading_control(settings)
    submitter = KisRealBuySubmitter(
        kis,
        kis_settings,
        settings,
        manual_enabled=control.manual_enabled,
        allow_real_api_call=False,
    )
    clock = SystemClock()
    return BuyIntentExecutor(
        submitter.submit,
        repository,
        clock.today,
        mock=False,
        settings=settings,
        quote_reader=kis.quote,
    )


def build_real_sell_executor(
    kis_settings: KisSettings,
    repository: DailyRepository,
    settings: TradingSettings,
) -> SellIntentExecutor:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    control = load_real_trading_control(settings)
    submitter = KisRealSellSubmitter(
        kis,
        kis_settings,
        settings,
        manual_enabled=control.manual_enabled,
        allow_real_api_call=False,
    )
    clock = SystemClock()
    return SellIntentExecutor(
        submitter.submit,
        repository,
        clock.today,
        mock=False,
        settings=settings,
    )


class ReadOnlyDailyRepository:
    def save_daily_targets(self, targets: Iterable[DailyTarget]) -> None:
        return None

    def save_daily_scores(self, scores: Iterable[DailyScore]) -> None:
        return None

    def save_candidate_evaluations(self, evaluations: Iterable[CandidateEvaluation]) -> None:
        return None

    def mark_candidate_evaluation_order_submitted(
        self,
        ticker: str,
        trade_date: date,
        order_id: str | None = None,
    ) -> None:
        return None

    def mark_candidate_evaluation_order_not_submitted(
        self,
        ticker: str,
        trade_date: date,
        reason: str,
    ) -> None:
        return None

    def save_log(self, log: BotLog) -> None:
        return None

    def save_trading_events(self, events: Iterable[TradingEvent]) -> None:
        return None

    def save_trades(self, trades: Iterable[TradeRecord]) -> None:
        return None

    def save_fills(self, fills: Iterable[FillRecord]) -> None:
        return None

    def fill_cumulative_quantities(
        self,
        trade_date: date,
        is_mock: bool = True,
    ) -> dict[tuple[str, str, str, bool], int]:
        return {}

    def history_fills(self, trade_date: date, limit: int = 200) -> list[tuple[object, ...]]:
        return []

    def pending_fill_notifications(self, fills: Iterable[FillRecord]) -> list[FillRecord]:
        return []

    def mark_fill_notifications_sent(self, fills: Iterable[FillRecord]) -> None:
        return None

    def last_stop_loss_at(self, trade_date: date, ticker: str):
        return None

    def consecutive_stop_loss_count(self, trade_date: date) -> int:
        return 0

    def position_entry_times(self, trade_date: date) -> dict[str, str]:
        return {}
