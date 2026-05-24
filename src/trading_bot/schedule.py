from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


Job = Callable[[], object]


class CronScheduler(Protocol):
    def add_job(self, func: Job, trigger: str, **kwargs: object) -> object: ...


@dataclass(frozen=True)
class DailyTasks:
    prepare_day: Job
    dry_run: Job
    mock_buy: Job
    refresh_orders: Job
    intraday_watch: Job
    intraday_recheck: Job
    cancel_unfilled: Job
    close_session: Job


def register_daily_timeline(
    scheduler: CronScheduler,
    tasks: DailyTasks,
    timezone: str = "Asia/Seoul",
    close_timezone: str = "America/New_York",
) -> None:
    _daily(scheduler, tasks.prepare_day, "prepare_day", 9, 0, timezone)
    _daily(scheduler, tasks.dry_run, "screen_and_score", 22, 35, timezone)
    _daily(scheduler, tasks.mock_buy, "mock_buy", 22, 45, timezone)
    _daily(scheduler, tasks.refresh_orders, "refresh_orders", 22, 50, timezone)
    _minute(scheduler, tasks.intraday_watch, "intraday_watch")
    _interval(scheduler, tasks.intraday_recheck, "intraday_recheck", 15)
    _daily(scheduler, tasks.cancel_unfilled, "cancel_unfilled", 15, 55, close_timezone)
    _daily(scheduler, tasks.close_session, "close_session", 16, 0, close_timezone)


def _daily(
    scheduler: CronScheduler,
    job: Job,
    job_id: str,
    hour: int,
    minute: int,
    timezone: str,
) -> None:
    scheduler.add_job(
        job,
        "cron",
        hour=hour,
        minute=minute,
        timezone=timezone,
        id=job_id,
        replace_existing=True,
    )


def _minute(scheduler: CronScheduler, job: Job, job_id: str) -> None:
    _interval(scheduler, job, job_id, 1)


def _interval(
    scheduler: CronScheduler,
    job: Job,
    job_id: str,
    minutes: int,
) -> None:
    scheduler.add_job(
        job,
        "interval",
        minutes=minutes,
        id=job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
