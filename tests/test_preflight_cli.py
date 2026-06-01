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
