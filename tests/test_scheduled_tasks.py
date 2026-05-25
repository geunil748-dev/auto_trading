from trading_bot.config import KisSettings, TradingSettings
from trading_bot.models import BuyIntent, PositionState, SellIntent
from trading_bot.scheduled_tasks import live_mock_tasks


class Accounts:
    def positions(self) -> list[str]:
        return ["holding"]


class Monitor:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], bool]] = []

    def poll(self, positions: list[str], end_of_day: bool = False):
        self.calls.append((positions, end_of_day))
        return positions, [SellIntent("AAA", 2, 10.5, "EOD")]


class Executor:
    def __init__(self) -> None:
        self.intents: list[SellIntent] = []

    def execute(self, intents: list[SellIntent]) -> list[object]:
        self.intents = intents
        return [object()]


class IntradayAccounts:
    def positions(self) -> list[PositionState]:
        return [PositionState("AAA", 10, 2, 9.7, 10.0)]


class IntradayMonitor:
    def __init__(self) -> None:
        self.highs: list[float] = []

    def poll(self, positions: list[PositionState], end_of_day: bool = False):
        self.highs.append(positions[0].high_price_usd)
        refreshed = [PositionState("AAA", 10, 2, 9.6, 10.5)]
        return refreshed, [SellIntent("AAA", 2, 9.6, "STOP_LOSS")]


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[list[SellIntent]] = []

    def execute(self, intents: list[SellIntent]) -> list[object]:
        self.calls.append(intents)
        return [object() for _ in intents]


class RecheckAccounts:
    def positions(self) -> list[PositionState]:
        return [PositionState("AAA", 10, 1, 10.31, 10.31)]


class RecheckScoring:
    selected = ("AAA", "BBB")


class RecheckResult:
    scoring = RecheckScoring()
    buy_intents = (
        BuyIntent("AAA", 1, 10, 10, 0.01),
        BuyIntent("BBB", 1, 10, 10, 0.01),
    )


class RecheckRuntime:
    def __init__(self) -> None:
        self.accounts = RecheckAccounts()

    def run(self) -> RecheckResult:
        return RecheckResult()


def test_close_session_submits_end_of_day_mock_sells(monkeypatch, tmp_path) -> None:
    monitor = Monitor()
    executor = Executor()
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_live_exit_poll",
        lambda settings, kis_settings: (Accounts(), monitor, "repository"),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_mock_sell_executor",
        lambda kis_settings, repository: executor,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._write_live_state",
        lambda monitor_state, kis_settings: {"orders": [], "fills": [], "holdings": []},
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._cancel_unfilled_orders",
        lambda kis_settings: [{"ticker": "OLD", "order_no": "1", "quantity": 1}],
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.write_daily_report",
        lambda report_dir, trade_day, state, cancelled_orders, eod_sell_count: tmp_path
        / "report.json",
    )

    tasks = live_mock_tasks(
        TradingSettings(),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        trading_day=lambda: True,
    )

    assert "Submitted 1 end-of-day mock sell orders" in tasks.close_session()
    assert monitor.calls == [(["holding"], True)]
    assert executor.intents == [SellIntent("AAA", 2, 10.5, "EOD")]


def test_cancel_unfilled_submits_cancellations_and_refreshes_monitor(
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._cancel_unfilled_orders",
        lambda kis_settings: [{"ticker": "AAA", "order_no": "111", "quantity": 2}],
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._write_live_state",
        lambda monitor_state, kis_settings: calls.append("refresh") or {},
    )
    tasks = live_mock_tasks(
        TradingSettings(),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        trading_day=lambda: True,
    )

    assert tasks.cancel_unfilled() == "Cancelled 1 unfilled mock orders."
    assert calls == ["refresh"]


def test_market_closed_skips_scheduled_trading_and_writes_monitor_state(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    tasks = live_mock_tasks(
        TradingSettings(),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        state_path,
        trading_day=lambda: False,
    )

    assert tasks.dry_run() == "Skipped screening because the US market is closed."
    assert "\ubbf8\uad6d \uac70\ub798\uc77c" in state_path.read_text(encoding="utf-8")


def test_intraday_watch_submits_one_exit_and_remembers_pending_sells(
    monkeypatch,
    tmp_path,
) -> None:
    monitor = IntradayMonitor()
    executor = RecordingExecutor()
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_live_exit_poll",
        lambda settings, kis_settings: (IntradayAccounts(), monitor, "repository"),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_mock_sell_executor",
        lambda kis_settings, repository: executor,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._write_live_state",
        lambda monitor_state, kis_settings, **kwargs: None,
    )
    tasks = live_mock_tasks(
        TradingSettings(),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        regular_session=lambda: True,
    )

    assert tasks.intraday_watch() == "Intraday watch submitted 1 mock sell orders."
    assert tasks.intraday_watch() == "Intraday watch submitted 0 mock sell orders."
    assert monitor.highs == [10.0, 10.5]
    assert executor.calls == [[SellIntent("AAA", 2, 9.6, "STOP_LOSS")], []]


def test_intraday_recheck_screens_and_limits_additional_buys(monkeypatch, tmp_path) -> None:
    executor = RecordingExecutor()
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_live_dry_run",
        lambda settings, kis_settings: (RecheckRuntime(), "repository"),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_mock_buy_executor",
        lambda kis_settings, repository: executor,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._unfilled_order_tickers",
        lambda kis_settings: set(),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.state_from_dry_run",
        lambda result: {"targets": [["BBB"]], "gates": [], "logs": []},
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._write_live_state",
        lambda monitor_state, kis_settings, screening_state=None, **kwargs: None,
    )
    tasks = live_mock_tasks(
        TradingSettings(max_intraday_entry_rounds=1),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        regular_session=lambda: True,
    )

    assert "submitted 1 mock buy orders" in tasks.intraday_recheck()
    assert "submitted 0 mock buy orders" in tasks.intraday_recheck()
    assert executor.calls == [[BuyIntent("AAA", 1, 10, 10, 0.01)], []]


def test_intraday_recheck_blocks_add_on_when_order_is_unfilled(
    monkeypatch,
    tmp_path,
) -> None:
    executor = RecordingExecutor()
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_live_dry_run",
        lambda settings, kis_settings: (RecheckRuntime(), "repository"),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_mock_buy_executor",
        lambda kis_settings, repository: executor,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.state_from_dry_run",
        lambda result: {"targets": [["AAA"]], "gates": [], "logs": []},
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._write_live_state",
        lambda monitor_state, kis_settings, screening_state=None, **kwargs: None,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._unfilled_order_tickers",
        lambda kis_settings: {"AAA", "BBB"},
    )
    tasks = live_mock_tasks(
        TradingSettings(),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        regular_session=lambda: True,
    )

    assert "submitted 0 mock buy orders" in tasks.intraday_recheck()
    assert executor.calls == [[]]
