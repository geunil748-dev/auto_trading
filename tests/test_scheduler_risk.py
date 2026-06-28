from datetime import datetime, timedelta, timezone

from trading_bot.config import TradingSettings
from trading_bot.models import BuyIntent
from trading_bot.scheduler_risk import (
    apply_stop_loss_entry_guards,
    consecutive_stop_loss_count,
    cooldown_active,
    last_stop_loss_at,
    saved_partial_take_profit_tickers,
)


class RiskRepository:
    def __init__(
        self,
        *,
        last_value=None,
        consecutive_count: int = 0,
        partial_tickers=None,
    ) -> None:
        self.last_value = last_value
        self.count = consecutive_count
        self.partial_tickers = partial_tickers or set()
        self.logs = []
        self.calls = []
        self.trading_events = []

    def last_stop_loss_at(self, trade_date, ticker):
        self.calls.append(("last_stop_loss_at", trade_date, ticker))
        return self.last_value

    def consecutive_stop_loss_count(self, trade_date):
        self.calls.append(("consecutive_stop_loss_count", trade_date))
        return self.count

    def partial_take_profit_tickers(self, trade_date):
        self.calls.append(("partial_take_profit_tickers", trade_date))
        return self.partial_tickers

    def save_log(self, log):
        self.logs.append(log)

    def save_trading_events(self, events):
        self.trading_events.extend(events)


def test_apply_stop_loss_entry_guards_returns_empty_for_no_intents() -> None:
    assert apply_stop_loss_entry_guards([], RiskRepository(), TradingSettings()) == []


def test_apply_stop_loss_entry_guards_blocks_when_consecutive_stop_loss_limit_reached() -> None:
    repository = RiskRepository(consecutive_count=3)

    intents = apply_stop_loss_entry_guards(
        [BuyIntent("AAA", 1, 10, 10, 0.01)],
        repository,
        TradingSettings(max_consecutive_stop_loss_count=3),
    )

    assert intents == []
    assert repository.logs[0].reject_reason == "CONSECUTIVE_STOP_LOSS_LIMIT"
    assert repository.logs[0].actual_value == 3.0
    assert repository.trading_events[0].event_type == "BUY_NOT_SUBMITTED"
    assert repository.trading_events[0].reason_code == "CONSECUTIVE_STOP_LOSS_LIMIT"


def test_apply_stop_loss_entry_guards_keeps_intent_when_consecutive_count_is_below_limit() -> None:
    intent = BuyIntent("AAA", 1, 10, 10, 0.01)
    repository = RiskRepository(consecutive_count=2)

    assert apply_stop_loss_entry_guards(
        [intent],
        repository,
        TradingSettings(max_consecutive_stop_loss_count=3),
    ) == [intent]
    assert repository.logs == []


def test_apply_stop_loss_entry_guards_blocks_ticker_inside_cooldown() -> None:
    repository = RiskRepository(last_value=datetime.now() - timedelta(minutes=5))

    intents = apply_stop_loss_entry_guards(
        [BuyIntent("AAA", 1, 10, 10, 0.01)],
        repository,
        TradingSettings(stop_loss_cooldown_minutes=30),
    )

    assert intents == []
    assert repository.logs[0].reject_reason == "NO_ORDER_RECENT_STOP_LOSS"
    assert repository.logs[0].symbol == "AAA"
    assert repository.trading_events[0].reason_code == "NO_ORDER_RECENT_STOP_LOSS"


def test_apply_stop_loss_entry_guards_blocks_same_day_stop_loss_outside_cooldown() -> None:
    intent = BuyIntent("AAA", 1, 10, 10, 0.01)
    repository = RiskRepository(last_value=datetime.now() - timedelta(minutes=60))

    assert (
        apply_stop_loss_entry_guards(
            [intent],
            repository,
            TradingSettings(stop_loss_cooldown_minutes=30),
        )
        == []
    )
    assert repository.logs[0].reject_reason == "NO_ORDER_RECENT_STOP_LOSS"


def test_apply_stop_loss_entry_guards_keeps_ticker_without_same_day_stop_loss() -> None:
    intent = BuyIntent("AAA", 1, 10, 10, 0.01)
    repository = RiskRepository(last_value=None)

    assert apply_stop_loss_entry_guards(
        [intent],
        repository,
        TradingSettings(stop_loss_cooldown_minutes=30),
    ) == [intent]


def test_cooldown_active_handles_invalid_string_and_disabled_cooldown() -> None:
    assert cooldown_active("not-a-datetime", 30) is False
    assert cooldown_active(datetime.now().isoformat(), 0) is False


def test_cooldown_active_handles_timezone_aware_datetime() -> None:
    assert cooldown_active(datetime.now(timezone.utc) - timedelta(minutes=5), 30) is True


def test_consecutive_stop_loss_count_failure_logs_safe_warning(monkeypatch) -> None:
    logs = []

    class FailingRepository:
        def consecutive_stop_loss_count(self, trade_date):
            raise RuntimeError("MSSQL_PASSWORD=secret")

    monkeypatch.setattr(
        "trading_bot.scheduler_risk.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    assert consecutive_stop_loss_count(FailingRepository()) == 0
    assert logs[0][2] == "STOP_LOSS_COUNT_LOOKUP_FAILED: RuntimeError"
    assert logs[0][3]["reject_reason"] == "STOP_LOSS_COUNT_LOOKUP_FAILED"
    assert "secret" not in logs[0][2]


def test_last_stop_loss_at_failure_logs_safe_warning(monkeypatch) -> None:
    logs = []

    class FailingRepository:
        def last_stop_loss_at(self, trade_date, ticker):
            raise RuntimeError("KIS_APP_SECRET=secret")

    monkeypatch.setattr(
        "trading_bot.scheduler_risk.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    assert last_stop_loss_at(FailingRepository(), "AAA") is None
    assert logs[0][2] == "STOP_LOSS_COOLDOWN_LOOKUP_FAILED: RuntimeError"
    assert logs[0][3]["symbol"] == "AAA"
    assert logs[0][3]["reject_reason"] == "STOP_LOSS_COOLDOWN_LOOKUP_FAILED"
    assert "secret" not in logs[0][2]


def test_saved_partial_take_profit_tickers_returns_saved_set() -> None:
    repository = RiskRepository(partial_tickers={"AAA", "BBB"})

    assert saved_partial_take_profit_tickers(repository) == {"AAA", "BBB"}


def test_saved_partial_take_profit_tickers_failure_logs_safe_warning(monkeypatch) -> None:
    logs = []

    class FailingRepository:
        def partial_take_profit_tickers(self, trade_date):
            raise RuntimeError("MONITOR_BEARER_TOKEN=secret")

    monkeypatch.setattr(
        "trading_bot.scheduler_risk.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    assert saved_partial_take_profit_tickers(FailingRepository()) == set()
    assert logs[0][2] == "PARTIAL_TAKE_PROFIT_LOOKUP_FAILED: RuntimeError"
    assert logs[0][3]["reject_reason"] == "PARTIAL_TAKE_PROFIT_LOOKUP_FAILED"
    assert "secret" not in logs[0][2]


def test_missing_repository_methods_keep_safe_defaults() -> None:
    repository = object()

    assert consecutive_stop_loss_count(repository) == 0
    assert last_stop_loss_at(repository, "AAA") is None
    assert saved_partial_take_profit_tickers(repository) == set()
