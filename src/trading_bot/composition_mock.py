from __future__ import annotations

from trading_bot.adapters.kis_account import KisAccountReader
from trading_bot.adapters.kis_http import KisJsonClient
from trading_bot.adapters.kis_orders_mock import KisMockBuySubmitter, KisMockSellSubmitter
from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.clocks import SystemClock
from trading_bot.composition_shared import build_kis_live_dry_run, build_kis_live_exit_poll
from trading_bot.config import KisSettings, TradingSettings
from trading_bot.order_execution import BuyIntentExecutor
from trading_bot.persistence import build_daily_repository
from trading_bot.pipeline import CandidateNotificationSender
from trading_bot.ports import DailyRepository
from trading_bot.sell_execution import SellIntentExecutor
from trading_bot.list_buy_planner import collect_ranked_buy_intents


def build_live_dry_run(
    settings: TradingSettings,
    kis_settings: KisSettings,
    *,
    candidate_notification_sender: CandidateNotificationSender | None = None,
):
    return build_kis_live_dry_run(
        settings,
        kis_settings,
        account_mock=True,
        candidate_notification_sender=candidate_notification_sender,
    )


def build_mock_buy_executor(
    kis_settings: KisSettings,
    repository: DailyRepository,
    settings: TradingSettings | None = None,
) -> BuyIntentExecutor:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    submitter = KisMockBuySubmitter(kis, kis_settings)
    clock = SystemClock()
    return BuyIntentExecutor(
        submitter.submit,
        repository,
        clock.today,
        settings=settings,
        quote_reader=kis.quote,
    )


def collect_mock_list_intents(
    settings: TradingSettings,
    kis_settings: KisSettings,
    limit: int,
):
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    accounts = KisAccountReader(kis, kis_settings)
    intents = collect_ranked_buy_intents(
        kis.ranked_trade_volume(),
        kis.quote,
        accounts.current_account(),
        settings,
        limit,
    )
    return intents, build_daily_repository()


def build_live_exit_poll(
    settings: TradingSettings,
    kis_settings: KisSettings,
):
    return build_kis_live_exit_poll(settings, kis_settings, account_mock=True)


def build_mock_sell_executor(
    kis_settings: KisSettings,
    repository: DailyRepository,
    settings: TradingSettings | None = None,
) -> SellIntentExecutor:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    submitter = KisMockSellSubmitter(kis, kis_settings)
    clock = SystemClock()
    return SellIntentExecutor(submitter.submit, repository, clock.today, settings=settings)
