import sys

from trading_bot.cli import main
from trading_bot.config import TradingSettings


class Executor:
    def execute(self, intents):
        assert list(intents) == []
        return []


def test_mock_buy_cli_passes_resolved_settings_to_executor(monkeypatch) -> None:
    current = TradingSettings(intraday_missing_data_policy="BLOCK")
    kis_settings = object()
    repository = object()
    captured = []

    monkeypatch.setattr(sys, "argv", ["trading-bot", "mock-buy-list"])
    monkeypatch.setattr("trading_bot.cli.load_settings", lambda: current)
    monkeypatch.setattr("trading_bot.cli.load_kis_settings", lambda: kis_settings)
    monkeypatch.setattr(
        "trading_bot.cli.collect_mock_list_intents",
        lambda settings, kis, limit: ([], repository),
    )
    monkeypatch.setattr(
        "trading_bot.cli.build_mock_buy_executor",
        lambda kis, repo, settings: captured.append((kis, repo, settings)) or Executor(),
    )

    main()

    assert captured == [(kis_settings, repository, current)]


def test_mock_sell_cli_passes_resolved_settings_to_executor(monkeypatch) -> None:
    current = TradingSettings(intraday_missing_data_policy="BLOCK")
    kis_settings = object()
    repository = object()
    captured = []

    class Accounts:
        def positions(self):
            return []

    class Monitor:
        def poll(self, positions):
            assert positions == []
            return [], []

    monkeypatch.setattr(sys, "argv", ["trading-bot", "mock-sell-exits-live"])
    monkeypatch.setattr("trading_bot.cli.load_settings", lambda: current)
    monkeypatch.setattr("trading_bot.cli.load_kis_settings", lambda: kis_settings)
    monkeypatch.setattr(
        "trading_bot.cli.build_live_exit_poll",
        lambda settings, kis: (Accounts(), Monitor(), repository),
    )
    monkeypatch.setattr(
        "trading_bot.cli.build_mock_sell_executor",
        lambda kis, repo, settings: captured.append((kis, repo, settings)) or Executor(),
    )

    main()

    assert captured == [(kis_settings, repository, current)]
