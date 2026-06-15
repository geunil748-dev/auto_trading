from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

from trading_bot.backtest import BacktestResult, run_chart_backtest
from trading_bot.backtest_data import YahooBacktestPriceSource, load_history
from trading_bot.intraday_backtest import (
    IntradayBacktestResult,
    IntradayBar,
    intraday_result_payload,
    run_intraday_backtest_compare,
    run_fixed_intraday_backtest,
)
from trading_bot.intraday_backtest_data import (
    YahooIntradayPriceSource,
    load_intraday_history,
)
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
from trading_bot.config import (
    CANDIDATE_MODE_FIXED,
    CANDIDATE_MODE_HYBRID,
    CANDIDATE_MODE_REFRESH,
    STRATEGY_PRESET_BALANCED_INTRADAY,
    STRATEGY_PRESET_CURRENT,
    TradingSettings,
    load_kis_settings,
    load_real_kis_settings,
    load_settings,
    save_runtime_risk_settings,
)
from trading_bot.database import (
    ensure_mssql_database_exists,
    initialize_database,
    pyodbc_connect_factory,
    repair_database_schema,
)
from trading_bot.daily_trade_summary import generate_daily_trade_summary
from trading_bot.monitor_state import state_from_dry_run
from trading_bot.live_monitor_state import live_kis_monitor_state
from trading_bot.monitor_server import serve_monitor
from trading_bot.readiness import mock_trading_readiness
from trading_bot.ranking_mode_compare import (
    archive_compare_payload,
    compare_ranking_modes,
    format_ranking_mode_archive_summary,
    summarize_ranking_mode_archive,
    write_compare_payload,
)
from trading_bot.trade_summary_export import export_trade_summary


def main() -> None:
    parser = argparse.ArgumentParser(prog="trading-bot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("show-settings")
    subparsers.add_parser("init-db")
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--monitor-state", type=Path, default=Path("monitor/state.json"))
    preflight.add_argument("--us-date", type=date.fromisoformat)
    repair_schema = subparsers.add_parser("repair-db-schema")
    repair_schema.add_argument("--monitor-state", type=Path, default=Path("monitor/state.json"))
    repair_schema.add_argument("--us-date", type=date.fromisoformat)

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
    backtest_compare = subparsers.add_parser("backtest-compare")
    backtest_compare.add_argument("--years", type=int, default=10)
    backtest_compare.add_argument("--initial-equity", type=float, default=10000.0)
    backtest_compare.add_argument("--use-runtime-settings", action="store_true")
    intraday_backtest = subparsers.add_parser("intraday-backtest-compare")
    intraday_backtest.add_argument("--interval", default="5m")
    intraday_backtest.add_argument("--period-days", type=int, default=60)
    intraday_backtest.add_argument("--initial-equity", type=float, default=10000.0)
    intraday_backtest.add_argument("--recent-candidate-days", type=int, default=1)
    reset_runtime = subparsers.add_parser("reset-runtime-settings")
    reset_runtime.add_argument("--profile", choices=("strict_baseline",), required=True)
    trade_summary = subparsers.add_parser("export-trade-summary")
    trade_summary.add_argument("--date", dest="trade_date", type=date.fromisoformat)
    trade_summary.add_argument("--mode", choices=("mock", "real"), default="mock")
    trade_summary.add_argument(
        "--output-dir",
        type=Path,
        default=Path("monitor/reports"),
    )
    daily_summary = subparsers.add_parser("generate-daily-summary")
    daily_summary.add_argument("--date", dest="trade_date", type=date.fromisoformat)
    daily_summary.add_argument("--mode", choices=("mock", "real"), default="mock")
    ranking_compare = subparsers.add_parser("compare-ranking-modes")
    ranking_compare.add_argument("--output", type=Path)
    ranking_compare.add_argument("--archive-dir", type=Path)
    ranking_summary = subparsers.add_parser("summarize-ranking-mode-archive")
    ranking_summary.add_argument("--archive-dir", type=Path, required=True)
    ranking_summary.add_argument("--days", type=int)
    ranking_summary.add_argument("--format", choices=("json", "text"), default="json")

    args = parser.parse_args()
    if args.command == "show-settings":
        settings = load_settings()
        print(json.dumps(settings.__dict__, indent=2))
        return

    if args.command == "backtest-compare":
        print(
            json.dumps(
                _run_backtest_compare(
                    args.years,
                    args.initial_equity,
                    use_runtime_settings=args.use_runtime_settings,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if args.command == "intraday-backtest-compare":
        print(
            json.dumps(
                _run_intraday_backtest_compare(
                    args.interval,
                    args.period_days,
                    args.initial_equity,
                    args.recent_candidate_days,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if args.command == "reset-runtime-settings":
        print(
            json.dumps(
                _reset_runtime_settings(args.profile),
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if args.command == "export-trade-summary":
        result = export_trade_summary(
            trade_date=args.trade_date,
            mode=args.mode,
            output_dir=args.output_dir,
        )
        print(
            json.dumps(
                {
                    "trade_date": result.trade_date.isoformat(),
                    "mode": result.mode,
                    "output_path": str(result.path),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if args.command == "generate-daily-summary":
        result = generate_daily_trade_summary(
            trade_date=args.trade_date,
            mode=args.mode,
        )
        print(
            json.dumps(
                {
                    "trade_date": result.report.trade_date.isoformat(),
                    "mode": result.report.mode,
                    "trade_count": result.report.trade_count,
                    "total_profit_usd": result.report.total_profit_usd,
                    "sample_sufficient": result.report.sample_sufficient,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if args.command == "compare-ranking-modes":
        payload = compare_ranking_modes(load_settings(), load_kis_settings())
        archive_compare_payload(payload, args.archive_dir)
        write_compare_payload(payload, args.output)
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return

    if args.command == "summarize-ranking-mode-archive":
        payload = summarize_ranking_mode_archive(args.archive_dir, days=args.days)
        if args.format == "text":
            print(format_ranking_mode_archive_summary(payload))
        else:
            print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return

    if args.command == "init-db":
        ensure_mssql_database_exists()
        initialize_database(pyodbc_connect_factory())
        print("SQL Server schema is ready.")
        return

    if args.command == "preflight":
        readiness = mock_trading_readiness(
            args.monitor_state,
            market_date=args.us_date,
            repair_schema=False,
        )
        print(
            json.dumps(
                readiness,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
        if not _preflight_ready(readiness):
            raise SystemExit(1)
        return

    if args.command == "repair-db-schema":
        repair_actions = repair_database_schema(pyodbc_connect_factory())
        readiness = mock_trading_readiness(
            args.monitor_state,
            market_date=args.us_date,
            repair_schema=True,
        )
        readiness["repair"] = {
            "mode": "explicit",
            "init_db_executed": False,
            "actions": repair_actions,
        }
        print(
            json.dumps(
                readiness,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
        if not _preflight_ready(readiness):
            raise SystemExit(1)
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
        return


def _run_intraday_backtest_compare(
    interval: str,
    period_days: int,
    initial_equity: float,
    recent_candidate_days: int = 1,
) -> dict[str, object]:
    if recent_candidate_days > 1:
        return _run_recent_intraday_fixed_backtests(
            interval,
            period_days,
            initial_equity,
            recent_candidate_days,
        )
    trade_date, tickers = _latest_candidate_tickers()
    _prepare_yfinance_cache()
    history, failed = load_intraday_history(
        tickers,
        YahooIntradayPriceSource(),
        interval=interval,
        period_days=period_days,
    )
    settings = replace(
        _backtest_base_settings(),
        candidate_selection_mode=CANDIDATE_MODE_FIXED,
        refresh_intraday_candidates=False,
        allow_relaxed_candidate_filter=False,
        enable_pyramiding=False,
    )
    results = run_intraday_backtest_compare(
        tickers,
        history,
        settings,
        interval=interval,
        period_days=period_days,
        initial_equity_usd=initial_equity,
        failed_tickers=failed,
    )
    return {
        "candidateDate": trade_date,
        "queriedTickers": tickers,
        "settings": _backtest_settings_payload(settings),
        "modes": {
            mode: intraday_result_payload(result)
            for mode, result in results.items()
        },
    }


def _run_recent_intraday_fixed_backtests(
    interval: str,
    period_days: int,
    initial_equity: float,
    recent_candidate_days: int,
) -> dict[str, object]:
    candidate_sets = _recent_candidate_tickers(recent_candidate_days)
    all_tickers = sorted({ticker for _, tickers in candidate_sets for ticker in tickers})
    _prepare_yfinance_cache()
    history, failed_tickers = load_intraday_history(
        all_tickers,
        YahooIntradayPriceSource(),
        interval=interval,
        period_days=period_days,
    )
    settings = replace(
        _backtest_base_settings(),
        candidate_selection_mode=CANDIDATE_MODE_FIXED,
        refresh_intraday_candidates=False,
        allow_relaxed_candidate_filter=False,
        enable_pyramiding=False,
    )
    daily_results: list[dict[str, object]] = []
    failed_dates: list[str] = []
    results: list[IntradayBacktestResult] = []
    for candidate_date, tickers in candidate_sets:
        day_history = _candidate_date_history(tickers, history, candidate_date)
        result = run_fixed_intraday_backtest(
            tickers,
            day_history,
            settings,
            interval=interval,
            period_days=period_days,
            initial_equity_usd=initial_equity,
            failed_tickers=[ticker for ticker in tickers if ticker in failed_tickers],
            trade_dates={date.fromisoformat(candidate_date)},
        )
        if not _has_candidate_date_bars(day_history, candidate_date):
            failed_dates.append(candidate_date)
        results.append(result)
        daily_results.append(
            {
                "candidate_date": candidate_date,
                "ticker_count": result.ticker_count,
                "failed_tickers": list(result.failed_tickers),
                "total_return": result.total_return,
                "average_trade_return": result.average_trade_return,
                "win_rate": result.win_rate,
                "max_drawdown": result.max_drawdown,
                "trade_count": result.trade_count,
                "stop_loss_count": result.stop_loss_count,
                "take_profit_count": result.take_profit_count,
                "trailing_stop_count": result.trailing_stop_count,
                "eod_count": result.eod_count,
            }
        )
    return {
        "settings": _backtest_settings_payload(settings),
        "interval": interval,
        "period_days": period_days,
        "requested_candidate_days": recent_candidate_days,
        "queriedTickers": all_tickers,
        "failedTickers": failed_tickers,
        "failedCandidateDates": failed_dates,
        "dailyResults": daily_results,
        "aggregate": _aggregate_intraday_results(results),
    }


def _candidate_date_history(
    tickers: list[str],
    history: dict[str, list[IntradayBar]],
    candidate_date: str,
) -> dict[str, list[IntradayBar]]:
    target = date.fromisoformat(candidate_date)
    filtered: dict[str, list[IntradayBar]] = {}
    for ticker in tickers:
        bars = history.get(ticker.upper(), [])
        previous = _previous_available_intraday_date(bars, target)
        filtered[ticker.upper()] = [
            bar
            for bar in bars
            if bar.bar_time.date() == target
            or (previous is not None and bar.bar_time.date() == previous)
        ]
    return filtered


def _previous_available_intraday_date(
    bars: list[IntradayBar],
    target: date,
) -> date | None:
    previous_dates = sorted({bar.bar_time.date() for bar in bars if bar.bar_time.date() < target})
    return previous_dates[-1] if previous_dates else None


def _has_candidate_date_bars(
    history: dict[str, list[IntradayBar]],
    candidate_date: str,
) -> bool:
    target = date.fromisoformat(candidate_date)
    return any(bar.bar_time.date() == target for bars in history.values() for bar in bars)


def _aggregate_intraday_results(
    results: list[IntradayBacktestResult],
) -> dict[str, float | int]:
    trades = [trade for result in results for trade in result.trades]
    total_trade_count = len(trades)
    aggregate_return = 1.0
    for result in results:
        aggregate_return *= 1 + result.total_return
    wins = sum(1 for trade in trades if trade.return_rate > 0)
    mdds = [result.max_drawdown for result in results]
    tested_days = len(results)
    sample_sufficient = tested_days >= 10 and total_trade_count >= 30
    sample_warning = ""
    if not sample_sufficient:
        sample_warning = (
            "INSUFFICIENT_SAMPLE_FOR_STRATEGY_DECISION: "
            "후보 기준일 또는 거래 수가 부족하여 전략 성과 판단에 사용할 수 없습니다. "
            "최소 후보 기준일 10일 이상, 거래 수 30건 이상을 권장합니다."
        )
    return {
        "sample_sufficient": sample_sufficient,
        "tested_candidate_days": tested_days,
        "minimum_required_candidate_days": 10,
        "total_ticker_count": sum(result.ticker_count for result in results),
        "total_trade_count": total_trade_count,
        "minimum_required_trade_count": 30,
        "sample_warning": sample_warning,
        "aggregate_return": aggregate_return - 1,
        "average_trade_return": (
            sum(trade.return_rate for trade in trades) / total_trade_count
            if total_trade_count
            else 0.0
        ),
        "win_rate": wins / total_trade_count if total_trade_count else 0.0,
        "average_mdd": sum(mdds) / len(mdds) if mdds else 0.0,
        "worst_mdd": min(mdds, default=0.0),
        "profitable_days": sum(1 for result in results if result.total_return > 0),
        "losing_days": sum(1 for result in results if result.total_return < 0),
        "zero_trade_days": sum(result.zero_trade_days for result in results),
    }


def _run_backtest_compare(
    years: int,
    initial_equity: float,
    use_runtime_settings: bool = False,
) -> dict[str, object]:
    trade_date, tickers = _latest_candidate_tickers()
    _prepare_yfinance_cache()
    history = load_history(tickers, YahooBacktestPriceSource(), years)
    failed = [ticker for ticker in tickers if not history.get(ticker)]
    base = _backtest_base_settings(use_runtime_settings)
    settings_source = "runtime" if use_runtime_settings else "fixed_baseline"
    strategies = {
        "strict_filter": _comparison_settings(
            base,
            STRATEGY_PRESET_CURRENT,
            relax_opening_change_only=False,
        ),
        "strict_balanced": _comparison_settings(
            base,
            STRATEGY_PRESET_BALANCED_INTRADAY,
            relax_opening_change_only=False,
        ),
        "strict_relax_opening_change": _comparison_settings(
            base,
            STRATEGY_PRESET_CURRENT,
            relax_opening_change_only=True,
        ),
        "strict_balanced_relax_opening_change": _comparison_settings(
            base,
            STRATEGY_PRESET_BALANCED_INTRADAY,
            relax_opening_change_only=True,
        ),
    }
    candidate_modes = {
        mode: _candidate_mode_settings(base, mode)
        for mode in (CANDIDATE_MODE_FIXED, CANDIDATE_MODE_REFRESH, CANDIDATE_MODE_HYBRID)
    }
    return {
        "candidateDate": trade_date,
        "period": f"{years}y daily OHLCV",
        "initialEquityUsd": initial_equity,
        "settings_source": settings_source,
        "baseline_settings": _backtest_settings_payload(base),
        "queriedTickers": tickers,
        "failedTickers": failed,
        "strategies": {
            name: _backtest_compare_payload(
                run_chart_backtest(
                    tickers,
                    history,
                    settings,
                    max_years=years,
                    initial_equity_usd=initial_equity,
                )[-1],
                settings,
            )
            for name, settings in strategies.items()
        },
        "candidateModeComparison": {
            mode: _backtest_compare_payload(
                run_chart_backtest(
                    tickers,
                    history,
                    settings,
                    max_years=years,
                    initial_equity_usd=initial_equity,
                )[-1],
                settings,
            )
            for mode, settings in candidate_modes.items()
        },
        "candidateModeNote": (
            "현재 일봉 백테스트는 후보 선정 방식의 스케줄 차이를 시뮬레이션하지 않고, "
            "동일 후보 티커 풀을 같은 조건으로 재평가합니다."
        ),
    }


def _backtest_base_settings(use_runtime_settings: bool = False) -> TradingSettings:
    if use_runtime_settings:
        return load_settings()
    return TradingSettings(
        min_price_usd=10.0,
        max_price_usd=50.0,
        min_opening_price_change=0.03,
        min_volume_ratio=1.5,
        max_opening_gap=0.20,
        min_total_score=40.0,
        max_position_loss=-0.05,
        take_profit_rate=0.05,
        trailing_stop_activation_rate=0.03,
        trailing_stop_drop=0.03,
        allow_relaxed_candidate_filter=False,
        relax_opening_change_only=False,
        strategy_preset=STRATEGY_PRESET_CURRENT,
        enable_pyramiding=False,
    )


def _reset_runtime_settings(profile: str) -> dict[str, object]:
    if profile != "strict_baseline":
        raise ValueError("지원하지 않는 런타임 설정 프로필입니다.")
    before = _backtest_settings_payload(load_settings())
    baseline = _backtest_base_settings()
    saved = save_runtime_risk_settings(
        stop_loss_percent=abs(baseline.max_position_loss * 100),
        take_profit_percent=baseline.take_profit_rate * 100,
        min_total_score=baseline.min_total_score,
        min_price_usd=baseline.min_price_usd,
        max_price_usd=baseline.max_price_usd,
        min_opening_price_change_percent=baseline.min_opening_price_change * 100,
        min_volume_ratio=baseline.min_volume_ratio,
        max_opening_gap_percent=baseline.max_opening_gap * 100,
        trailing_stop_activation_percent=baseline.trailing_stop_activation_rate * 100,
        strategy_preset=baseline.strategy_preset,
        allow_relaxed_candidate_filter=baseline.allow_relaxed_candidate_filter,
        relax_opening_change_only=baseline.relax_opening_change_only,
        enable_pyramiding=baseline.enable_pyramiding,
    )
    after = _backtest_settings_payload(load_settings())
    return {
        "ok": True,
        "profile": profile,
        "before": before,
        "after": after,
        "runtimePayload": saved,
        "note": "주문 실행 없이 런타임 설정만 strict baseline 기준으로 저장했습니다.",
    }


def _latest_candidate_tickers() -> tuple[str, list[str]]:
    recent = _recent_candidate_tickers(1)
    if not recent:
        return "", []
    return recent[0]


def _preflight_ready(readiness: dict[str, object]) -> bool:
    mssql = readiness.get("mssql")
    if not isinstance(mssql, dict):
        return False
    return (
        mssql.get("connected") is True
        and mssql.get("required_tables_ready") is True
        and mssql.get("required_columns_ready") is True
    )


def _recent_candidate_tickers(limit: int) -> list[tuple[str, list[str]]]:
    connection = pyodbc_connect_factory()()
    try:
        cursor = connection.cursor()
        rows = cursor.execute(
            """
            SELECT TOP (?) CONVERT(varchar(10), trade_date, 23) AS trade_date
              FROM (
                    SELECT trade_date FROM listed_target_snapshot
                    UNION ALL
                    SELECT trade_date FROM daily_target
              ) candidate_dates
             WHERE trade_date IS NOT NULL
             GROUP BY CONVERT(varchar(10), trade_date, 23), trade_date
             ORDER BY trade_date DESC
            """,
            (max(1, limit),),
        ).fetchall()
        dates = [date.fromisoformat(str(row[0])).isoformat() for row in rows if row and row[0]]
        result = [
            (candidate_date, _candidate_tickers_for_date(cursor, candidate_date))
            for candidate_date in dates
        ]
    finally:
        connection.close()
    return result


def _candidate_tickers_for_date(cursor: object, candidate_date: str) -> list[str]:
    rows = cursor.execute(
        f"""
            SELECT DISTINCT ticker
              FROM (
                    SELECT ticker, trade_date FROM listed_target_snapshot
                    UNION ALL
                    SELECT ticker, trade_date FROM daily_target
              ) candidates
             WHERE CONVERT(varchar(10), trade_date, 23) = '{candidate_date}'
               AND ticker IS NOT NULL
             ORDER BY ticker
            """,
    ).fetchall()
    return [str(row[0]).upper() for row in rows if row and row[0]]


def _prepare_yfinance_cache() -> None:
    try:
        import yfinance as yf
    except ImportError:
        return
    if hasattr(yf, "set_tz_cache_location"):
        yf.set_tz_cache_location(str(Path(".yfinance-cache").resolve()))


def _comparison_settings(
    base: TradingSettings,
    strategy_preset: str,
    relax_opening_change_only: bool,
) -> TradingSettings:
    settings = replace(
        base,
        allow_relaxed_candidate_filter=False,
        relax_opening_change_only=relax_opening_change_only,
        strategy_preset=strategy_preset,
        enable_pyramiding=False,
    )
    if strategy_preset == STRATEGY_PRESET_BALANCED_INTRADAY:
        return replace(
            settings,
            max_position_loss=-0.035,
            take_profit_rate=0.04,
            trailing_stop_activation_rate=0.025,
            trailing_stop_drop=0.02,
        )
    return settings


def _candidate_mode_settings(base: TradingSettings, mode: str) -> TradingSettings:
    return replace(
        _comparison_settings(
            base,
            STRATEGY_PRESET_CURRENT,
            relax_opening_change_only=False,
        ),
        candidate_selection_mode=mode,
        refresh_intraday_candidates=mode != CANDIDATE_MODE_FIXED,
    )


def _backtest_compare_payload(
    result: BacktestResult,
    settings: TradingSettings,
) -> dict[str, int | float | bool | str | dict[str, float | bool | str]]:
    return {
        "settings": _backtest_settings_payload(settings),
        "totalReturn": result.return_rate,
        "averageTradeReturn": result.average_trade_return,
        "winRate": result.win_rate,
        "maxDrawdown": result.max_drawdown,
        "trades": result.trades,
        "zeroEntryDays": result.zero_entry_days,
        "stopLossCount": result.stop_loss_count,
        "takeProfitCount": result.take_profit_count,
        "trailingStopCount": result.trailing_stop_count,
        "eodCount": result.eod_count,
        "eodRate": result.eod_rate,
        "dataSufficient": result.data_sufficient,
    }


def _backtest_settings_payload(
    settings: TradingSettings,
) -> dict[str, float | bool | str]:
    return {
        "allow_relaxed_candidate_filter": settings.allow_relaxed_candidate_filter,
        "relax_opening_change_only": settings.relax_opening_change_only,
        "strategy_preset": settings.strategy_preset,
        "enable_pyramiding": settings.enable_pyramiding,
        "refresh_intraday_candidates": settings.refresh_intraday_candidates,
        "candidate_selection_mode": settings.candidate_selection_mode,
        "min_price_usd": settings.min_price_usd,
        "max_price_usd": settings.max_price_usd,
        "min_opening_price_change": settings.min_opening_price_change,
        "min_volume_ratio": settings.min_volume_ratio,
        "max_opening_gap": settings.max_opening_gap,
        "min_total_score": settings.min_total_score,
        "max_position_loss": settings.max_position_loss,
        "take_profit_rate": settings.take_profit_rate,
        "trailing_stop_activation_rate": settings.trailing_stop_activation_rate,
        "trailing_stop_drop": settings.trailing_stop_drop,
    }
