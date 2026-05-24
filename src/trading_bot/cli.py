from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from trading_bot.adapters.kis_http import KisJsonClient
from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.adapters.kis_account import KisAccountReader
from trading_bot.apscheduler_runner import run_scheduler
from trading_bot.composition import (
    build_live_dry_run,
    build_live_exit_poll,
    build_mock_buy_executor,
    build_mock_sell_executor,
    collect_mock_list_intents,
)
from trading_bot.config import load_kis_settings, load_real_kis_settings, load_settings
from trading_bot.database import (
    ensure_mssql_database_exists,
    initialize_database,
    pyodbc_connect_factory,
)
from trading_bot.monitor_state import state_from_dry_run
from trading_bot.live_monitor_state import live_kis_monitor_state
from trading_bot.monitor_server import serve_monitor
from trading_bot.readiness import mock_trading_readiness


def main() -> None:
    parser = argparse.ArgumentParser(prog="trading-bot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("show-settings")
    subparsers.add_parser("init-db")
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--monitor-state", type=Path, default=Path("monitor/state.json"))
    preflight.add_argument("--us-date", type=date.fromisoformat)

    ranking = subparsers.add_parser("kis-rankings")
    ranking.add_argument("--exchange", default="NAS")
    ranking.add_argument("--limit", type=int, default=20)
    account = subparsers.add_parser("kis-account")
    account.add_argument("--real", action="store_true")
    dry_run = subparsers.add_parser("dry-run-live")
    dry_run.add_argument("--monitor-state", type=Path)
    mock_buy = subparsers.add_parser("mock-buy-live")
    mock_buy.add_argument("--monitor-state", type=Path)
    mock_list = subparsers.add_parser("mock-buy-list")
    mock_list.add_argument("--limit", type=int, default=3)
    refresh_monitor = subparsers.add_parser("refresh-monitor-live")
    refresh_monitor.add_argument("--monitor-state", type=Path, default=Path("monitor/state.json"))
    scheduler = subparsers.add_parser("run-scheduler")
    scheduler.add_argument("--monitor-state", type=Path, default=Path("monitor/state.json"))
    monitor_server = subparsers.add_parser("serve-monitor")
    monitor_server.add_argument("--host", default="127.0.0.1")
    monitor_server.add_argument("--port", type=int, default=8000)
    subparsers.add_parser("poll-exits-live")
    subparsers.add_parser("mock-sell-exits-live")

    args = parser.parse_args()
    if args.command == "show-settings":
        settings = load_settings()
        print(json.dumps(settings.__dict__, indent=2))
        return

    if args.command == "init-db":
        ensure_mssql_database_exists()
        initialize_database(pyodbc_connect_factory())
        print("SQL Server schema is ready.")
        return

    if args.command == "preflight":
        print(
            json.dumps(
                mock_trading_readiness(args.monitor_state, market_date=args.us_date),
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
        return

    if args.command == "kis-rankings":
        client = KisOverseasClient(KisJsonClient(load_kis_settings()), args.exchange)
        rows = {
            "gainers": [item.__dict__ for item in client.ranked_gainers(args.limit)],
            "trade_volume": [
                item.__dict__ for item in client.ranked_trade_volume(args.limit)
            ],
        }
        print(json.dumps(rows, indent=2))
        return

    if args.command == "kis-account":
        kis_settings = load_real_kis_settings() if args.real else load_kis_settings()
        account = KisAccountReader(
            KisOverseasClient(KisJsonClient(kis_settings)),
            kis_settings,
            mock=not args.real,
        ).current_account()
        print(json.dumps(account.__dict__, indent=2))
        return

    if args.command in {"dry-run-live", "mock-buy-live"}:
        settings = load_settings()
        kis_settings = load_kis_settings()
        runtime, repository = build_live_dry_run(settings, kis_settings)
        result = runtime.run()
        state = state_from_dry_run(result)
        if args.monitor_state:
            args.monitor_state.write_text(
                json.dumps(state, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        trades = []
        if args.command == "mock-buy-live":
            trades = build_mock_buy_executor(kis_settings, repository).execute(
                result.buy_intents
            )
        print(
            json.dumps(
                {
                    "blocked_reason": result.scoring.blocked_reason,
                    "targets": len(result.scoring.targets),
                    "selected": len(result.scoring.selected),
                    "buy_intents": [item.__dict__ for item in result.buy_intents],
                    "submitted_mock_orders": [item.__dict__ for item in trades],
                },
                indent=2,
                default=str,
            )
        )
        return

    if args.command == "mock-buy-list":
        settings = load_settings()
        kis_settings = load_kis_settings()
        intents, repository = collect_mock_list_intents(settings, kis_settings, args.limit)
        trades = build_mock_buy_executor(kis_settings, repository).execute(intents)
        print(
            json.dumps(
                {
                    "collected_buy_intents": [item.__dict__ for item in intents],
                    "submitted_mock_orders": [item.__dict__ for item in trades],
                },
                indent=2,
                default=str,
            )
        )
        return

    if args.command == "refresh-monitor-live":
        kis_settings = load_kis_settings()
        kis = KisOverseasClient(KisJsonClient(kis_settings))
        accounts = KisAccountReader(kis, kis_settings)
        state = live_kis_monitor_state(kis, accounts, kis_settings)
        args.monitor_state.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Live mock monitor state written to {args.monitor_state}.")
        return

    if args.command == "run-scheduler":
        run_scheduler(args.monitor_state)
        return

    if args.command == "serve-monitor":
        serve_monitor(args.host, args.port)
        return

    if args.command in {"poll-exits-live", "mock-sell-exits-live"}:
        settings = load_settings()
        kis_settings = load_kis_settings()
        accounts, monitor, repository = build_live_exit_poll(settings, kis_settings)
        positions, exits = monitor.poll(accounts.positions())
        trades = []
        if args.command == "mock-sell-exits-live":
            trades = build_mock_sell_executor(kis_settings, repository).execute(exits)
        print(
            json.dumps(
                {
                    "positions": [item.__dict__ for item in positions],
                    "sell_intents": [item.__dict__ for item in exits],
                    "submitted_mock_sells": [item.__dict__ for item in trades],
                },
                indent=2,
                default=str,
            )
        )
