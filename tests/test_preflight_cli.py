import json
import sys

import pytest

from trading_bot import cli


def _ready_payload(mssql: dict[str, object]) -> dict[str, object]:
    return {
        "us_market_date": "2026-06-01",
        "is_us_trading_day": True,
        "is_regular_session_now": False,
        "next_us_trading_day": "2026-06-01",
        "kis_config": {"configured": True},
        "mssql": mssql,
        "monitor_state_exists": True,
        "ready_for_live_mock_session": True,
    }


def test_preflight_cli_exits_zero_when_mssql_ready(monkeypatch, capsys) -> None:
    payload = _ready_payload(
        {
            "connected": True,
            "required_tables_ready": True,
            "required_columns_ready": True,
        }
    )
    monkeypatch.setattr(sys, "argv", ["trading-bot", "preflight"])
    monkeypatch.setattr(cli, "mock_trading_readiness", lambda *args, **kwargs: payload)

    cli.main()

    assert json.loads(capsys.readouterr().out)["mssql"]["connected"] is True


def test_preflight_cli_uses_read_only_readiness(monkeypatch, capsys) -> None:
    payload = _ready_payload(
        {
            "connected": True,
            "required_tables_ready": True,
            "required_columns_ready": True,
        }
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(sys, "argv", ["trading-bot", "preflight"])

    def fake_readiness(*args, **kwargs):
        calls.append(kwargs)
        return payload

    monkeypatch.setattr(cli, "mock_trading_readiness", fake_readiness)

    cli.main()

    assert json.loads(capsys.readouterr().out)["mssql"]["connected"] is True
    assert calls[0]["repair_schema"] is False


def test_repair_db_schema_cli_runs_explicit_repair(monkeypatch, capsys) -> None:
    payload = _ready_payload(
        {
            "connected": True,
            "required_tables_ready": True,
            "required_columns_ready": True,
        }
    )
    calls: list[str] = []
    readiness_calls: list[dict[str, object]] = []

    monkeypatch.setattr(sys, "argv", ["trading-bot", "repair-db-schema"])
    monkeypatch.setattr(cli, "ensure_mssql_database_exists", lambda: calls.append("ensure-db"))
    monkeypatch.setattr(cli, "initialize_database", lambda *_: calls.append("init-schema"))
    monkeypatch.setattr(
        cli,
        "repair_database_schema",
        lambda *_: calls.append("repair-schema") or [{"name": "sample", "action": "executed"}],
    )
    monkeypatch.setattr(cli, "pyodbc_connect_factory", lambda: lambda: object())

    def fake_readiness(*args, **kwargs):
        readiness_calls.append(kwargs)
        return payload

    monkeypatch.setattr(cli, "mock_trading_readiness", fake_readiness)

    cli.main()

    assert calls == ["repair-schema"]
    assert readiness_calls[0]["repair_schema"] is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["mssql"]["connected"] is True
    assert payload["repair"] == {
        "mode": "explicit",
        "init_db_executed": False,
        "actions": [{"name": "sample", "action": "executed"}],
    }


@pytest.mark.parametrize(
    "mssql",
    [
        {"connected": False},
        {
            "connected": True,
            "required_tables_ready": False,
            "required_columns_ready": True,
        },
        {
            "connected": True,
            "required_tables_ready": True,
            "required_columns_ready": False,
        },
    ],
)
def test_preflight_cli_exits_one_when_mssql_not_ready(monkeypatch, capsys, mssql) -> None:
    monkeypatch.setattr(sys, "argv", ["trading-bot", "preflight"])
    monkeypatch.setattr(
        cli,
        "mock_trading_readiness",
        lambda *args, **kwargs: _ready_payload(mssql),
    )

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 1
    assert json.loads(capsys.readouterr().out)["mssql"] == mssql


def test_preflight_ready_rejects_missing_mssql_payload() -> None:
    assert cli._preflight_ready({}) is False
