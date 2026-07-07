import json
import sys
from types import SimpleNamespace

from trading_bot import cli
from trading_bot.config import APP_MODE_REAL, KisSettings, TradingSettings
from trading_bot.models import BuyIntent, SellIntent


class Runtime:
    def run(self):
        scoring = SimpleNamespace(
            blocked_reason=None,
            targets=(),
            selected=(),
        )
        return SimpleNamespace(
            scoring=scoring,
            buy_intents=(BuyIntent("AAA", 1, 10.0, 10.0, 0.01),),
        )


def _kis_settings() -> KisSettings:
    return KisSettings("app", "secret", "12345678", "01", "https://kis.example")


def test_mock_buy_live_uses_mock_path_even_when_app_mode_real(monkeypatch, capsys) -> None:
    calls = []

    class Executor:
        def execute(self, intents):
            calls.append(("mock_execute", list(intents)))
            return []

    monkeypatch.setattr(sys, "argv", ["trading-bot", "mock-buy-live"])
    monkeypatch.setattr(cli, "load_settings", lambda: TradingSettings(app_mode=APP_MODE_REAL))
    monkeypatch.setattr(cli, "load_kis_settings", lambda: _kis_settings())
    monkeypatch.setattr(
        cli,
        "load_real_kis_settings",
        lambda: (_ for _ in ()).throw(AssertionError("real settings must not load")),
    )
    monkeypatch.setattr(cli, "build_live_dry_run", lambda settings, kis: (Runtime(), object()))
    monkeypatch.setattr(cli, "state_from_dry_run", lambda result: {})
    monkeypatch.setattr(cli, "build_mock_buy_executor", lambda kis, repository: Executor())

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["submitted_mock_orders"] == []
    assert calls and calls[0][0] == "mock_execute"


def test_real_buy_live_is_plan_only_and_does_not_submit(monkeypatch, capsys, tmp_path) -> None:
    state = tmp_path / "real_state.json"
    monkeypatch.setattr(sys, "argv", ["trading-bot", "real-buy-live", "--monitor-state", str(state)])
    monkeypatch.setattr(cli, "load_settings", lambda: TradingSettings(app_mode=APP_MODE_REAL))
    monkeypatch.setattr(cli, "load_real_kis_settings", lambda: _kis_settings())
    monkeypatch.setattr(cli, "build_real_live_dry_run", lambda settings, kis: (Runtime(), object()))
    monkeypatch.setattr(cli, "state_from_dry_run", lambda result: {})

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["submitted_real_orders"] == []
    assert payload["order_submission"] == "blocked"
    assert state.exists()


def test_real_dry_run_live_defaults_to_real_state_path(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["trading-bot", "real-dry-run-live"])
    monkeypatch.setattr(cli, "load_settings", lambda: TradingSettings(app_mode=APP_MODE_REAL))
    monkeypatch.setattr(cli, "load_real_kis_settings", lambda: _kis_settings())
    monkeypatch.setattr(cli, "build_real_live_dry_run", lambda settings, kis: (Runtime(), object()))
    monkeypatch.setattr(cli, "state_from_dry_run", lambda result: {"ok": True})

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["order_submission"] == "read_only"
    assert (tmp_path / "monitor" / "real_state.json").exists()
    assert not (tmp_path / "monitor" / "state.json").exists()


def test_real_sell_exits_live_is_plan_only_and_does_not_submit(monkeypatch, capsys) -> None:
    accounts = SimpleNamespace(positions=lambda: [SimpleNamespace(ticker="AAA")])
    monitor = SimpleNamespace(
        poll=lambda positions: (positions, [SellIntent("AAA", 1, 10.0, "EOD")])
    )
    monkeypatch.setattr(sys, "argv", ["trading-bot", "real-sell-exits-live"])
    monkeypatch.setattr(cli, "load_settings", lambda: TradingSettings(app_mode=APP_MODE_REAL))
    monkeypatch.setattr(cli, "load_real_kis_settings", lambda: _kis_settings())
    monkeypatch.setattr(
        cli,
        "build_real_live_exit_poll",
        lambda settings, kis: (accounts, monitor, object()),
    )

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["submitted_real_sells"] == []
    assert payload["order_submission"] == "blocked"


def test_run_real_scheduler_uses_real_scheduler_skeleton(monkeypatch, tmp_path) -> None:
    calls = []
    state = tmp_path / "state.json"
    monkeypatch.setattr(sys, "argv", ["trading-bot", "run-real-scheduler", "--monitor-state", str(state)])
    monkeypatch.setattr(cli, "run_real_scheduler", lambda monitor_state: calls.append(monitor_state))

    cli.main()

    assert calls == [state]


def test_run_real_scheduler_defaults_to_real_state_path(monkeypatch, tmp_path) -> None:
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["trading-bot", "run-real-scheduler"])
    monkeypatch.setattr(cli, "run_real_scheduler", lambda monitor_state: calls.append(monitor_state))

    cli.main()

    assert calls == [cli.REAL_MONITOR_STATE_PATH]


def test_real_preflight_cli_prints_read_only_payload(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(sys, "argv", [
        "trading-bot",
        "real-preflight",
        "--real-monitor-state",
        str(tmp_path / "real_state.json"),
        "--mock-monitor-state",
        str(tmp_path / "state.json"),
    ])
    monkeypatch.setattr(
        cli,
        "real_preflight",
        lambda **kwargs: {
            "ok": False,
            "appMode": "test",
            "ordersUnlocked": False,
            "blockingReasons": ["APP_MODE_NOT_REAL"],
            "kwargs": {key: str(value) for key, value in kwargs.items()},
        },
    )

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["ordersUnlocked"] is False
    assert payload["blockingReasons"] == ["APP_MODE_NOT_REAL"]
    assert payload["kwargs"]["check_account"] == "False"
