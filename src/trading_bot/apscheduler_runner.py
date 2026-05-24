from __future__ import annotations

from pathlib import Path

from trading_bot.config import load_kis_settings, load_settings
from trading_bot.schedule import register_daily_timeline
from trading_bot.scheduled_tasks import live_mock_tasks


def run_scheduler(monitor_state: Path) -> None:
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError as error:  # pragma: no cover - depends on optional install.
        raise RuntimeError("Install the integrations extra to run APScheduler") from error

    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    register_daily_timeline(
        scheduler,
        live_mock_tasks(load_settings(), load_kis_settings(), monitor_state),
    )
    scheduler.start()
