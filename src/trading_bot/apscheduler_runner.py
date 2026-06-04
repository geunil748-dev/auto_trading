from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_bot.config import load_kis_settings, load_settings
from trading_bot.schedule import register_daily_timeline
from trading_bot.schedule import DailyTasks
from trading_bot.scheduled_tasks import live_mock_tasks, trading_cycle_skip_reason


def run_scheduler(monitor_state: Path) -> None:
    try:
        from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError as error:  # pragma: no cover - depends on optional install.
        raise RuntimeError("Install the integrations extra to run APScheduler") from error

    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    scheduler.add_listener(
        _log_job_event,
        EVENT_JOB_EXECUTED | EVENT_JOB_ERROR,
    )
    tasks = live_mock_tasks(
        load_settings,
        load_kis_settings(),
        monitor_state,
        trading_guard=lambda: trading_cycle_skip_reason(monitor_state),
    )
    register_daily_timeline(
        scheduler,
        tasks,
    )
    _register_heartbeat(scheduler, monitor_state.parent / "scheduler_heartbeat.json")
    _register_startup_recovery(scheduler, tasks)
    scheduler.start()


def _register_heartbeat(scheduler, heartbeat_path: Path) -> None:
    _write_scheduler_heartbeat(heartbeat_path)
    scheduler.add_job(
        _write_scheduler_heartbeat,
        "interval",
        minutes=1,
        args=[heartbeat_path],
        id="scheduler_heartbeat",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


def _write_scheduler_heartbeat(heartbeat_path: Path) -> str:
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {
                "status": "running",
                "pid": os.getpid(),
                "updated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return "Scheduler heartbeat updated."


def _register_startup_recovery(scheduler, tasks: DailyTasks) -> None:
    # PC를 장중에 늦게 켠 경우에도 다음 15분 주기만 기다리지 않고 즉시 상태를 복구한다.
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    scheduler.add_job(
        tasks.intraday_watch,
        "date",
        run_date=now + timedelta(seconds=5),
        id="startup_intraday_watch",
        replace_existing=True,
    )
    scheduler.add_job(
        tasks.intraday_recheck,
        "date",
        run_date=now + timedelta(seconds=10),
        id="startup_intraday_recheck",
        replace_existing=True,
    )


def _log_job_event(event) -> None:
    if event.exception:
        print(f"scheduler job failed: {event.job_id}: {event.exception}", flush=True)
        return
    print(f"scheduler job done: {event.job_id}: {event.retval}", flush=True)
