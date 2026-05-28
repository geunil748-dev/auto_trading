from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from trading_bot.adapters.kis_account import KisAccountReader
from trading_bot.adapters.kis_http import KisJsonClient
from trading_bot.adapters.kis_orders import KisMockOrderCanceller
from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.composition import (
    build_live_dry_run,
    build_live_exit_poll,
    build_mock_buy_executor,
    build_mock_sell_executor,
)
from trading_bot.config import KisSettings, TradingSettings, load_settings
from trading_bot.daily_report import write_daily_report
from trading_bot.database import pyodbc_connect_factory
from trading_bot.fill_persistence import fill_records_from_monitor_rows
from trading_bot.intraday_entries import limited_intraday_buy_intents
from trading_bot.live_monitor_state import live_kis_monitor_state
from trading_bot.market_calendar import (
    current_us_market_date,
    is_current_us_regular_session,
    is_current_us_trading_day,
)
from trading_bot.models import PositionState
from trading_bot.monitor_state import state_from_dry_run
from trading_bot.order_cancellation import cancel_unfilled_orders
from trading_bot.entry_planner import plan_buy_intents
from trading_bot.repositories import SqlServerDailyRepository, SqlServerMonitorRepository
from trading_bot.runtime import DryRunResult
from trading_bot.schedule import DailyTasks
from trading_bot.scheduled_messages import log_row, recheck_message, watch_message
from trading_bot.trading_date import current_trade_date


def live_mock_tasks(
    settings: TradingSettings | Callable[[], TradingSettings],
    kis_settings: KisSettings,
    monitor_state: Path,
    trading_day: Callable[[], bool] = is_current_us_trading_day,
    regular_session: Callable[[], bool] = is_current_us_regular_session,
) -> DailyTasks:
    # 스케줄러 안에서는 가장 최근 수집 결과를 들고 있다가 매수/감시 단계에서 재사용한다.
    latest = _LatestRunState()

    def prepare_day() -> str:
        KisJsonClient(kis_settings).access_token()
        return "KIS token prepared."

    def dry_run() -> str:
        if not trading_day():
            # 미국 휴장일에는 주문뿐 아니라 후보 수집도 멈춰 화면에 스킵 상태를 남긴다.
            _write_closed_state(monitor_state)
            return "Skipped screening because the US market is closed."
        current_settings = _current_settings(settings)
        runtime, repository = build_live_dry_run(current_settings, kis_settings)
        latest.result = runtime.run()
        latest.repository = repository
        latest.opening_result = latest.result
        latest.opening_trade_date = current_trade_date()
        latest.opening_fixed_mode = _candidate_mode(current_settings) in {"fixed", "hybrid"}
        monitor_state.write_text(
            json.dumps(state_from_dry_run(latest.result), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return f"Dry run selected {len(latest.result.scoring.selected)} scores."

    def mock_buy() -> str:
        if not trading_day():
            _write_closed_state(monitor_state)
            return "Skipped mock buys because the US market is closed."
        if latest.result is None or latest.repository is None:
            dry_run()
        if latest.result is None or latest.repository is None:
            return "Skipped mock buys because screening did not run."
        trades = build_mock_buy_executor(kis_settings, latest.repository).execute(
            latest.result.buy_intents
        )
        latest.buy_tickers.update(item.ticker for item in latest.result.buy_intents)
        _write_live_state(monitor_state, kis_settings)
        return f"Submitted {len(trades)} mock buy orders."

    def refresh_orders() -> str:
        if not trading_day():
            _write_closed_state(monitor_state)
            return "Skipped order refresh because the US market is closed."
        _write_live_state(monitor_state, kis_settings)
        return "Refreshed mock order, fill, and holding monitor state."

    def intraday_watch() -> str:
        if not regular_session():
            return "Skipped intraday watch outside the regular US session."
        current_settings = _current_settings(settings)
        accounts, monitor, repository = build_live_exit_poll(current_settings, kis_settings)
        positions = _remembered_highs(accounts.positions(), latest.highs)
        refreshed, exits = monitor.poll(positions)
        latest.highs.update({item.ticker: item.high_price_usd for item in refreshed})
        latest.pending_exits.intersection_update(item.ticker for item in refreshed)
        # 같은 보유 종목에 미체결 매도 주문을 중복 제출하지 않도록 보호한다.
        executable = [item for item in exits if item.ticker not in latest.pending_exits]
        trades = build_mock_sell_executor(kis_settings, repository).execute(executable)
        latest.pending_exits.update(item.ticker for item in executable)
        _write_live_state(
            monitor_state,
            kis_settings,
            extra_logs=[
                log_row(
                    "1분 감시",
                    watch_message(refreshed, exits, executable, latest.pending_exits),
                )
            ],
        )
        return f"Intraday watch submitted {len(trades)} mock sell orders."

    def intraday_recheck() -> str:
        if not regular_session():
            return "Skipped intraday recheck outside the regular US session."
        current_settings = _current_settings(settings)
        runtime, repository = build_live_dry_run(current_settings, kis_settings)
        fixed_opening = _fixed_opening_result(latest, current_settings)
        mode = _candidate_mode(current_settings)
        if mode == "fixed" and fixed_opening is not None:
            # 장초반 고정 모드에서는 기존 후보만 최신 가격 기준으로 재평가한다.
            latest.result = _recheck_fixed_watchlist(runtime, fixed_opening, current_settings)
        elif mode == "hybrid" and fixed_opening is not None:
            # 하이브리드는 장초반 고정 후보와 15분 신규 후보 상위권을 합쳐 감시한다.
            latest.result = _hybrid_recheck(runtime, fixed_opening, current_settings)
        else:
            # 15분 재수집 모드에서는 매번 새 후보를 수집해 점수를 다시 계산한다.
            latest.result = runtime.run()
        latest.repository = repository
        positions = runtime.accounts.positions()
        unfilled = _unfilled_order_tickers(kis_settings)
        # 재평가 매수는 미체결/이미 진입한 종목/일일 라운드 제한을 한 번 더 통과해야 한다.
        intents = limited_intraday_buy_intents(
            latest.result.buy_intents,
            positions,
            latest.buy_tickers,
            latest.add_on_tickers,
            unfilled,
            latest.intraday_entry_rounds,
            current_settings,
        )
        trades = build_mock_buy_executor(kis_settings, repository).execute(intents)
        if trades:
            latest.intraday_entry_rounds += 1
            latest.buy_tickers.update(item.ticker for item in intents)
            held = {_ticker(position.ticker) for position in positions}
            latest.add_on_tickers.update(
                item.ticker for item in intents if _ticker(item.ticker) in held
            )
        _write_live_state(
            monitor_state,
            kis_settings,
            screening_state=state_from_dry_run(latest.result),
            extra_logs=[
                log_row(
                    "15분 재평가",
                    recheck_message(
                        latest.result.buy_intents,
                        intents,
                        positions,
                        unfilled,
                        latest.intraday_entry_rounds,
                        current_settings,
                    ),
                )
            ],
        )
        return (
            f"Intraday recheck selected {len(latest.result.scoring.selected)} scores "
            f"and submitted {len(trades)} mock buy orders."
        )

    def cancel_unfilled() -> str:
        if not trading_day():
            _write_closed_state(monitor_state)
            return "Skipped unfilled order cancellation because the US market is closed."
        cancelled = _cancel_unfilled_orders(kis_settings)
        latest.cancelled_orders.extend(cancelled)
        _write_live_state(monitor_state, kis_settings)
        return f"Cancelled {len(cancelled)} unfilled mock orders."

    def close_session() -> str:
        if not trading_day():
            _write_closed_state(monitor_state)
            return "Skipped session close because the US market is closed."
        if not regular_session():
            return "Skipped session close outside the regular US session."
        cancelled = _cancel_unfilled_orders(kis_settings)
        latest.cancelled_orders.extend(cancelled)
        current_settings = _current_settings(settings)
        accounts, monitor, repository = build_live_exit_poll(current_settings, kis_settings)
        _, exits = monitor.poll(accounts.positions(), end_of_day=True)
        trades = build_mock_sell_executor(kis_settings, repository).execute(exits)
        state = _write_live_state(monitor_state, kis_settings)
        _save_daily_run_summary(
            current_settings,
            len(trades),
            len(latest.cancelled_orders),
        )
        report_path = write_daily_report(
            monitor_state.parent / "reports",
            current_us_market_date().strftime("%Y%m%d"),
            state,
            latest.cancelled_orders,
            len(trades),
        )
        return (
            f"Submitted {len(trades)} end-of-day mock sell orders "
            f"and wrote {report_path}."
        )

    return DailyTasks(
        prepare_day,
        dry_run,
        mock_buy,
        refresh_orders,
        intraday_watch,
        intraday_recheck,
        cancel_unfilled,
        close_session,
    )


def _save_daily_run_summary(
    settings: TradingSettings,
    eod_sell_count: int | None,
    cancelled_order_count: int | None,
) -> None:
    try:
        connect = pyodbc_connect_factory()
        monitor_repository = SqlServerMonitorRepository(connect)
        daily_repository = SqlServerDailyRepository(connect)
        trade_date = current_trade_date()
        buy_count, sell_count = monitor_repository.history_fill_counts(trade_date)
        daily_repository.save_daily_run_summary(
            trade_date,
            settings,
            monitor_repository.history_realized_profit(trade_date),
            monitor_repository.history_realized_profit_rate(trade_date),
            eod_sell_count,
            cancelled_order_count,
            buy_count,
            sell_count,
        )
    except Exception:
        return


def _candidate_mode(settings: TradingSettings) -> str:
    if settings.candidate_selection_mode != "refresh":
        return settings.candidate_selection_mode
    return "refresh" if settings.refresh_intraday_candidates else "fixed"


class _LatestRunState:
    def __init__(self) -> None:
        self.result = None
        self.repository = None
        self.highs: dict[str, float] = {}
        self.pending_exits: set[str] = set()
        self.buy_tickers: set[str] = set()
        self.add_on_tickers: set[str] = set()
        self.intraday_entry_rounds = 0
        self.cancelled_orders: list[dict[str, object]] = []
        self.opening_result = None
        self.opening_trade_date = None
        self.opening_fixed_mode = False


def _fixed_opening_result(
    latest: _LatestRunState,
    settings: TradingSettings,
) -> DryRunResult | None:
    if _candidate_mode(settings) not in {"fixed", "hybrid"}:
        return None
    if not latest.opening_fixed_mode:
        return None
    if latest.opening_trade_date != current_trade_date():
        return None
    # 장초반 고정 모드는 22:35~22:40에 수집한 후보만 장중에 계속 감시한다.
    return latest.opening_result


def _recheck_fixed_watchlist(runtime, latest_result: DryRunResult, settings: TradingSettings) -> DryRunResult:
    account = runtime.accounts.current_account()
    selected = latest_result.scoring.selected[: settings.opening_fixed_candidate_limit]
    breakout_inputs = {
        item.ticker: runtime.breakout.breakout_input(item.ticker)
        for item in selected
    }
    intents = plan_buy_intents(
        selected,
        breakout_inputs,
        account,
        settings,
    )
    return DryRunResult(account, latest_result.scoring, tuple(intents))


def _hybrid_recheck(
    runtime,
    opening_result: DryRunResult,
    settings: TradingSettings,
) -> DryRunResult:
    refreshed = runtime.run()
    account = runtime.accounts.current_account()
    selected = _hybrid_selected_scores(opening_result, refreshed, settings)
    breakout_inputs = {
        item.ticker: runtime.breakout.breakout_input(item.ticker)
        for item in selected
    }
    intents = plan_buy_intents(selected, breakout_inputs, account, settings)
    return DryRunResult(account, refreshed.scoring, tuple(intents))


def _hybrid_selected_scores(
    opening_result: DryRunResult,
    refreshed: DryRunResult,
    settings: TradingSettings,
) -> tuple:
    combined = {}
    for score in opening_result.scoring.selected[: settings.opening_fixed_candidate_limit]:
        combined[score.ticker] = score
    intraday_ranked = sorted(
        refreshed.scoring.selected,
        key=lambda item: (-item.total_score, item.ticker),
    )
    for score in intraday_ranked[: settings.intraday_refresh_candidate_limit]:
        combined[score.ticker] = score
    ranked = sorted(combined.values(), key=lambda item: (-item.total_score, item.ticker))
    return tuple(ranked[: settings.hybrid_candidate_limit])


def _write_live_state(
    monitor_state: Path,
    kis_settings: KisSettings,
    screening_state: dict[str, object] | None = None,
    extra_logs: list[list[str]] | None = None,
) -> dict[str, object]:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    accounts = KisAccountReader(kis, kis_settings)
    live_state = live_kis_monitor_state(kis, accounts, kis_settings)
    if screening_state is not None:
        live_state["targets"] = screening_state["targets"]
        live_state["gates"] = screening_state["gates"] + live_state["gates"]
        live_state["logs"] = screening_state["logs"] + live_state["logs"]
    if extra_logs:
        live_state["logs"] = extra_logs + live_state["logs"]
    persist_error = _persist_live_snapshot(live_state)
    if persist_error:
        live_state["logs"] = [log_row("DB", persist_error)] + live_state["logs"]
    monitor_state.write_text(
        json.dumps(live_state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return live_state


def _persist_live_snapshot(live_state: dict[str, object]) -> str:
    account = live_state.get("account", {})
    fills = live_state.get("fills", [])
    holdings = live_state.get("holdings", [])
    orders = live_state.get("orders", [])
    try:
        repository = SqlServerDailyRepository(pyodbc_connect_factory())
        trade_date = current_trade_date()
        if isinstance(account, dict):
            repository.save_account_snapshot(account, trade_date)
        if isinstance(orders, list):
            repository.save_order_snapshot(orders, trade_date)
        if isinstance(holdings, list):
            repository.save_holdings(holdings, trade_date)
        if isinstance(fills, list):
            entry_prices = repository.sell_entry_prices(trade_date)
            records = fill_records_from_monitor_rows(fills, entry_prices)
            if records:
                repository.save_fills(records)
                if any(item.profit_usd is not None for item in records):
                    _save_daily_run_summary(load_settings(), None, None)
    except ValueError:
        return ""
    except Exception as exc:
        return f"모니터 DB 저장 실패: {exc}"
    return ""


def _write_closed_state(monitor_state: Path) -> None:
    monitor_state.write_text(
        json.dumps(
            {
                "targets": [],
                "holdings": [],
                "orders": [],
                "fills": [],
                "gates": [["\ubbf8\uad6d \uac70\ub798\uc77c", "\ud734\uc7a5"]],
                "logs": [
                    [
                        "\uc2a4\ucf00\uc904",
                        "INFO",
                        "\ubbf8\uad6d \uc2dc\uc7a5 \ud734\uc7a5\uc73c\ub85c "
                        "\ub9e4\ub9e4\ub97c \uac74\ub108\ub6f0\uc5c8\uc2b5\ub2c8\ub2e4.",
                    ]
                ],
                "trades": [],
                "chart": {"closes": [], "movingAverage": []},
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _unfilled_order_tickers(kis_settings: KisSettings) -> set[str]:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    rows = kis.mock_order_history(
        kis_settings.account_no,
        kis_settings.account_product,
        current_us_market_date().strftime("%Y%m%d"),
    )
    return {
        ticker
        for row in rows
        if _int(row, "nccs_qty") > 0
        if (ticker := _ticker(str(row.get("pdno", ""))))
    }


def _cancel_unfilled_orders(kis_settings: KisSettings) -> list[dict[str, object]]:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    rows = kis.mock_order_history(
        kis_settings.account_no,
        kis_settings.account_product,
        current_us_market_date().strftime("%Y%m%d"),
    )
    return cancel_unfilled_orders(rows, KisMockOrderCanceller(kis, kis_settings).cancel)


def _remembered_highs(
    positions: list[PositionState],
    highs: dict[str, float],
) -> list[PositionState]:
    return [
        PositionState(
            item.ticker,
            item.entry_price_usd,
            item.quantity,
            item.last_price_usd,
            max(item.high_price_usd, highs.get(item.ticker, item.high_price_usd)),
        )
        for item in positions
    ]


def _ticker(value: str) -> str:
    return value.strip().upper()


def _int(row: dict[str, object], field: str) -> int:
    return int(float(str(row.get(field, 0)).replace(",", "") or 0))


def _current_settings(
    settings: TradingSettings | Callable[[], TradingSettings],
) -> TradingSettings:
    return settings() if callable(settings) else settings
