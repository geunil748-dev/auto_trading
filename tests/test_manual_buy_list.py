import json
import sys

import pytest

from trading_bot.cli import main
from trading_bot.config import TradingSettings
from trading_bot.manual_buy_list import (
    FileManualBuyListSource,
    add_manual_buy_ticker,
    clear_manual_buy_tickers,
    list_manual_buy_tickers,
    normalize_ticker,
    read_manual_buy_list,
    remove_manual_buy_ticker,
    set_manual_buy_ticker_enabled,
)


def test_manual_buy_list_add_list_disable_enable_remove_clear(tmp_path) -> None:
    path = tmp_path / "manual_buy_list.json"

    assert add_manual_buy_ticker(path, " tsla ", note="watch")["count"] == 1
    assert add_manual_buy_ticker(path, "TSLA", note="updated")["count"] == 1
    assert add_manual_buy_ticker(path, "brk.b")["ticker"] == "BRK.B"
    assert [item.ticker for item in read_manual_buy_list(path)] == ["TSLA", "BRK.B"]
    assert list_manual_buy_tickers(path)["count"] == 2

    set_manual_buy_ticker_enabled(path, "TSLA", False)
    assert FileManualBuyListSource(path).enabled_tickers() == ("BRK.B",)
    set_manual_buy_ticker_enabled(path, "TSLA", True)
    assert FileManualBuyListSource(path).enabled_tickers() == ("TSLA", "BRK.B")

    remove_manual_buy_ticker(path, "BRK.B")
    assert [item.ticker for item in read_manual_buy_list(path)] == ["TSLA"]
    clear_manual_buy_tickers(path)
    assert read_manual_buy_list(path) == []


def test_manual_buy_list_rejects_invalid_tickers_and_limit(tmp_path) -> None:
    path = tmp_path / "manual_buy_list.json"

    with pytest.raises(ValueError):
        normalize_ticker("../TSLA")
    with pytest.raises(ValueError):
        normalize_ticker("AAPL/MSFT")

    add_manual_buy_ticker(path, "AAPL", max_tickers=1)
    with pytest.raises(ValueError, match="MAX_MANUAL_BUY_TICKERS"):
        add_manual_buy_ticker(path, "TSLA", max_tickers=1)


def test_manual_buy_list_missing_or_corrupt_file_is_safe_empty(tmp_path) -> None:
    path = tmp_path / "manual_buy_list.json"
    assert read_manual_buy_list(path) == []
    path.write_text("{", encoding="utf-8")
    assert read_manual_buy_list(path) == []


def test_manual_buy_list_cli_does_not_call_order_or_schema_paths(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    path = tmp_path / "manual_buy_list.json"
    submitter_calls: list[str] = []
    db_schema_calls: list[str] = []

    monkeypatch.setattr(sys, "argv", [
        "trading-bot",
        "manual-buy-list",
        "add",
        "tsla",
        "--note",
        "watch",
        "--path",
        str(path),
    ])
    monkeypatch.setattr(
        "trading_bot.cli.load_settings",
        lambda: TradingSettings(
            manual_buy_list_path=str(path),
            max_manual_buy_tickers=20,
        ),
    )
    monkeypatch.setattr(
        "trading_bot.cli.build_mock_buy_executor",
        lambda *args, **kwargs: submitter_calls.append("buy"),
    )
    monkeypatch.setattr(
        "trading_bot.cli.ensure_mssql_database_exists",
        lambda *args, **kwargs: db_schema_calls.append("ensure"),
    )
    monkeypatch.setattr(
        "trading_bot.cli.initialize_database",
        lambda *args, **kwargs: db_schema_calls.append("init"),
    )
    monkeypatch.setattr(
        "trading_bot.cli.repair_database_schema",
        lambda *args, **kwargs: db_schema_calls.append("repair"),
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["ticker"] == "TSLA"
    assert submitter_calls == []
    assert db_schema_calls == []
