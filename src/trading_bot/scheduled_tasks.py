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
from trading_bot.config import KisSettings, TradingSettings
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
from trading_bot.repositories import SqlServerDailyRepository
from trading_bot.schedule import DailyTasks
from trading_bot.scheduled_messages import log_row, recheck_message, watch_message


def live_mock_tasks(
    settings: TradingSettings | Callable[[], TradingSettings],
    kis_settings: KisSettings,
    monitor_state: Path,
    trading_day: Callable[[], bool] = is_current_us_trading_day,
    regular_session: Callable[[], bool] = is_current_us_regular_session,
) -> DailyTasks:
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
    persist_error = _persist_live_fills(live_state)
    if persist_error:
        live_state["logs"] = [log_row("DB", persist_error)] + live_state["logs"]
    monitor_state.write_text(
        json.dumps(live_state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return live_state


def _persist_live_fills(live_state: dict[str, object]) -> str:
    fills = live_state.get("fills", [])
    if not isinstance(fills, list):
        return ""
    try:
        repository = SqlServerDailyRepository(pyodbc_connect_factory())
        entry_prices = repository.sell_entry_prices(current_us_market_date())
        records = fill_records_from_monitor_rows(fills, entry_prices)
        if not records:
            return ""
        repository.save_fills(records)
    except ValueError:
        return ""
    except Exception as exc:
        return f"체결 DB 저장 실패: {exc}"
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
