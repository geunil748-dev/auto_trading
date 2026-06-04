from __future__ import annotations

from trading_bot.trade_notifier import TradeNotifier, now_kst


def is_market_day() -> bool:
    # 실제 적용 시 증권사 휴장일 API나 거래소 캘린더로 교체한다.
    return now_kst().weekday() < 5


def start_market_close_report_scheduler(
    notifier: TradeNotifier,
    scheduler: object | None = None,
) -> object:
    created_scheduler = scheduler is None
    if scheduler is None:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
        except ImportError as error:
            raise RuntimeError("Install the integrations extra to run APScheduler") from error
        scheduler = BackgroundScheduler(timezone="Asia/Seoul")

    def send_report_if_market_day() -> bool:
        if not is_market_day():
            return False
        return notifier.send_market_close_report()

    scheduler.add_job(
        send_report_if_market_day,
        "cron",
        day_of_week="mon-fri",
        hour=15,
        minute=35,
        timezone="Asia/Seoul",
        id="trade_notifier_market_close_report",
        replace_existing=True,
    )
    if created_scheduler:
        scheduler.start()
    return scheduler
