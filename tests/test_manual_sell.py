from trading_bot.manual_sell import submit_manual_mock_sell, submit_manual_mock_sell_all
from trading_bot.models import PositionState, SellIntent


class Accounts:
    def positions(self) -> list[PositionState]:
        return [PositionState("AAA", 10.0, 3, 12.5, 12.5)]


class Executor:
    def __init__(self) -> None:
        self.intents: list[SellIntent] = []

    def execute(self, intents: list[SellIntent]):
        self.intents.extend(intents)
        return []


def test_submit_manual_mock_sell_uses_current_position(monkeypatch) -> None:
    executor = Executor()
    monkeypatch.setattr("trading_bot.manual_sell.load_settings", lambda: object())
    monkeypatch.setattr("trading_bot.manual_sell.load_kis_settings", lambda: object())
    monkeypatch.setattr(
        "trading_bot.manual_sell.build_live_exit_poll",
        lambda settings, kis_settings: (Accounts(), object(), object()),
    )
    monkeypatch.setattr(
        "trading_bot.manual_sell.build_mock_sell_executor",
        lambda kis_settings, repository: executor,
    )

    result = submit_manual_mock_sell(" aaa ", 2)

    assert result["ok"] is True
    assert result["ticker"] == "AAA"
    assert executor.intents == [SellIntent("AAA", 2, 12.5, "MANUAL_SELL", 10.0)]


def test_submit_manual_mock_sell_all_sells_every_position(monkeypatch) -> None:
    class ManyAccounts:
        def positions(self) -> list[PositionState]:
            return [
                PositionState("AAA", 10.0, 3, 12.5, 12.5),
                PositionState("BBB", 20.0, 1, 21.0, 21.0),
            ]

    executor = Executor()
    monkeypatch.setattr("trading_bot.manual_sell.load_settings", lambda: object())
    monkeypatch.setattr("trading_bot.manual_sell.load_kis_settings", lambda: object())
    monkeypatch.setattr(
        "trading_bot.manual_sell.build_live_exit_poll",
        lambda settings, kis_settings: (ManyAccounts(), object(), object()),
    )
    monkeypatch.setattr(
        "trading_bot.manual_sell.build_mock_sell_executor",
        lambda kis_settings, repository: executor,
    )

    result = submit_manual_mock_sell_all()

    assert result["count"] == 2
    assert result["quantity"] == 4
    assert executor.intents == [
        SellIntent("AAA", 3, 12.5, "MANUAL_SELL_ALL", 10.0),
        SellIntent("BBB", 1, 21.0, "MANUAL_SELL_ALL", 20.0),
    ]
