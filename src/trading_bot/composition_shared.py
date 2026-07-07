from __future__ import annotations

from trading_bot.adapters.breakout_history import KisBreakoutHistory
from trading_bot.adapters.chart_history import YahooChartScorer
from trading_bot.adapters.context import YahooMarketContextSource
from trading_bot.adapters.kis_account import KisAccountReader
from trading_bot.adapters.kis_http import KisJsonClient
from trading_bot.adapters.kis_quotes import KisLastPriceReader
from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.adapters.market_data import KisDailyVolumeHistory, KisScreeningMarketData
from trading_bot.adapters.news_sentiment import YahooNewsSentimentSource
from trading_bot.adapters.scoring import NewsChartScoringProvider
from trading_bot.adapters.yahoo_news import YahooFinanceNewsSource
from trading_bot.clocks import SystemClock
from trading_bot.config import KisSettings, TradingSettings
from trading_bot.models import BotLog
from trading_bot.persistence import build_daily_repository, build_news_cache_repository
from trading_bot.pipeline import CandidateNotificationSender, ScreeningScoringPipeline
from trading_bot.ports import DailyRepository
from trading_bot.quote_polling import PollingExitMonitor
from trading_bot.runtime import DryRunRuntime
from trading_bot.sentiment import KeywordHeadlineSentiment
from trading_bot.manual_buy_list import FileManualBuyListSource


def build_kis_live_dry_run(
    settings: TradingSettings,
    kis_settings: KisSettings,
    *,
    account_mock: bool,
    repository: DailyRepository | None = None,
    candidate_notification_sender: CandidateNotificationSender | None = None,
) -> tuple[DryRunRuntime, DailyRepository]:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    accounts = KisAccountReader(kis, kis_settings, mock=account_mock)
    repository = repository or build_daily_repository()
    news_cache = build_news_cache_repository()
    scoring = NewsChartScoringProvider(
        YahooNewsSentimentSource(
            YahooFinanceNewsSource(),
            KeywordHeadlineSentiment(),
            cache=news_cache,
            cache_ttl_minutes=settings.news_cache_ttl_minutes,
        ).sentiments,
        YahooChartScorer().score,
    )
    pipeline = ScreeningScoringPipeline(
        KisScreeningMarketData(
            kis,
            YahooMarketContextSource(),
            KisDailyVolumeHistory(kis),
            on_snapshot_error=_snapshot_error_logger(repository),
        ),
        scoring,
        accounts,
        repository,
        SystemClock(),
        settings,
        manual_source=FileManualBuyListSource(
            settings.manual_buy_list_path,
            enabled=settings.manual_buy_list_enabled,
            max_tickers=settings.max_manual_buy_tickers,
        ),
        candidate_notification_sender=candidate_notification_sender,
    )
    return (
        DryRunRuntime(pipeline, accounts, KisBreakoutHistory(kis), settings),
        repository,
    )


def build_kis_live_exit_poll(
    settings: TradingSettings,
    kis_settings: KisSettings,
    *,
    account_mock: bool,
) -> tuple[KisAccountReader, PollingExitMonitor, DailyRepository]:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    accounts = KisAccountReader(kis, kis_settings, mock=account_mock)
    monitor = PollingExitMonitor(KisLastPriceReader(kis).price, settings)
    return accounts, monitor, build_daily_repository()


def _snapshot_error_logger(repository: DailyRepository):
    def log_missing_snapshot(ticker: str, reason: str) -> None:
        try:
            repository.save_log(
                BotLog(
                    "WARNING",
                    "screening",
                    f"[MISSING_SNAPSHOT] ticker={ticker} reason={reason}",
                    symbol=ticker,
                    reject_reason="MISSING_SNAPSHOT",
                )
            )
        except Exception:
            return

    return log_missing_snapshot
