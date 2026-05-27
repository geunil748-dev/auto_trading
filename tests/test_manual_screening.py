import time

from trading_bot.manual_screening import ManualScreeningRunner


def test_manual_screening_runner_starts_background_job(tmp_path) -> None:
    calls = []

    def run_screening():
        calls.append("run")
        return {"ok": True, "message": "done", "targets": 3, "selected": 2}

    runner = ManualScreeningRunner(tmp_path / "state.json", run_screening)

    result = runner.start()
    assert result["started"] is True

    for _ in range(50):
        status = runner.status()
        if not status["running"]:
            break
        time.sleep(0.01)

    assert calls == ["run"]
    assert runner.status()["message"] == "done"
    assert runner.status()["targets"] == 3


def test_manual_screening_runner_blocks_duplicate_start(tmp_path) -> None:
    def run_screening():
        time.sleep(0.05)
        return {"ok": True, "message": "done"}

    runner = ManualScreeningRunner(tmp_path / "state.json", run_screening)

    first = runner.start()
    second = runner.start()

    assert first["started"] is True
    assert second["started"] is False
