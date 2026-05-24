from trading_bot.schedule import DailyTasks, register_daily_timeline


class Scheduler:
    def __init__(self) -> None:
        self.jobs: list[tuple[object, str, dict[str, object]]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append((func, trigger, kwargs))


def test_daily_timeline_registers_planning_document_times_in_kst() -> None:
    scheduler = Scheduler()
    tasks = DailyTasks(
        prepare_day=lambda: None,
        dry_run=lambda: None,
        mock_buy=lambda: None,
        refresh_orders=lambda: None,
        intraday_watch=lambda: None,
        intraday_recheck=lambda: None,
        cancel_unfilled=lambda: None,
        close_session=lambda: None,
    )

    register_daily_timeline(scheduler, tasks)

    assert [
        (job[2]["id"], job[1], job[2]["hour"], job[2]["minute"], job[2]["timezone"])
        for job in scheduler.jobs
        if job[1] == "cron"
    ] == [
        ("prepare_day", "cron", 9, 0, "Asia/Seoul"),
        ("screen_and_score", "cron", 22, 35, "Asia/Seoul"),
        ("mock_buy", "cron", 22, 45, "Asia/Seoul"),
        ("refresh_orders", "cron", 22, 50, "Asia/Seoul"),
        ("cancel_unfilled", "cron", 15, 55, "America/New_York"),
        ("close_session", "cron", 16, 0, "America/New_York"),
    ]
    assert scheduler.jobs[4][1:] == (
        "interval",
        {
            "minutes": 1,
            "id": "intraday_watch",
            "replace_existing": True,
            "max_instances": 1,
            "coalesce": True,
        },
    )
    assert scheduler.jobs[5][1:] == (
        "interval",
        {
            "minutes": 15,
            "id": "intraday_recheck",
            "replace_existing": True,
            "max_instances": 1,
            "coalesce": True,
        },
    )
    assert all(job[2]["replace_existing"] for job in scheduler.jobs)
