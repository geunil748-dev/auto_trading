from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_bot.adapters.kis_account import KisAccountReader
from trading_bot.adapters.kis_http import KisJsonClient
from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.config import KisSettings, load_settings
from trading_bot.database import pyodbc_connect_factory
from trading_bot.fill_persistence import (
    fill_records_from_monitor_rows,
    valid_fill_monitor_row_count,
)
from trading_bot.live_monitor_state import live_kis_monitor_state
from trading_bot.models import EntryProfitSnapshot, FillRecord
from trading_bot.repositories import SqlServerDailyRepository
from trading_bot.scheduled_messages import log_row
from trading_bot.scheduler_logging import safe_exception_summary
from trading_bot.scheduler_market_close import save_daily_run_summary
from trading_bot.trading_date import current_trade_date
from trading_bot.trading_event_logger import (
    record_data_quality_event,
    record_fill_saved_event,
    record_notification_event,
)


FillNotificationCallback = Callable[[list[FillRecord], list[object]], int | None]


def write_live_state(
    monitor_state: Path,
    kis_settings: KisSettings,
    screening_state: dict[str, object] | None = None,
    extra_logs: list[list[str]] | None = None,
    *,
    send_fill_notifications_func: FillNotificationCallback | None = None,
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
    persist_error = persist_live_snapshot(
        live_state,
        send_fill_notifications_func=send_fill_notifications_func,
    )
    if persist_error:
        live_state["logs"] = [log_row("DB", persist_error)] + live_state["logs"]
    write_state_file(monitor_state, live_state)
    return live_state


def persist_live_snapshot(
    live_state: dict[str, object],
    *,
    send_fill_notifications_func: FillNotificationCallback | None = None,
) -> str:
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
            settings = load_settings()
            entry_prices = repository.sell_entry_prices(trade_date)
            entry_reasons = repository.entry_reasons(trade_date)
            existing_cumulative_quantities = (
                repository.fill_cumulative_quantities(trade_date)
                if hasattr(repository, "fill_cumulative_quantities")
                else {}
            )
            records = fill_records_from_monitor_rows(
                fills,
                entry_prices,
                entry_reasons,
                settings=settings,
                existing_cumulative_quantities=existing_cumulative_quantities,
            )
            valid_fill_count = valid_fill_monitor_row_count(fills)
            if valid_fill_count != len(fills):
                record_data_quality_event(
                    repository,
                    reason_code="FILL_MONITOR_ROWS_SKIPPED",
                    stage="ORDER_FILL",
                    trade_date=trade_date,
                    message="fill_monitor_rows_skipped",
                    details={
                        "raw_fill_count": len(fills),
                        "valid_fill_count": valid_fill_count,
                        "skipped_count": len(fills) - valid_fill_count,
                    },
                    fallback_bot_log=False,
                )
            if records:
                repository.save_fills(records)
                for record in records:
                    record_fill_saved_event(repository, record, fallback_bot_log=False)
                repository.save_entry_profit_snapshots(
                    entry_profit_snapshots_from_fills(records)
                )
                if any(item.profit_usd is not None for item in records):
                    save_daily_run_summary(settings, None, None)
            pending_notifications = repository.pending_fill_notifications(records)
            pending_ids = {id(item) for item in pending_notifications}
            for record in records:
                if id(record) not in pending_ids:
                    record_notification_event(
                        repository,
                        event_type="FILL_NOTIFICATION_SKIPPED_DUPLICATE",
                        severity="INFO",
                        reason_code="FILL_NOTIFICATION_SKIPPED_DUPLICATE",
                        ticker=record.ticker,
                        details={"side": record.side, "order_no": record.order_no},
                        fallback_bot_log=False,
                    )
            if pending_notifications and send_fill_notifications_func is not None:
                sent_count = send_fill_notifications_func(
                    pending_notifications,
                    holdings if isinstance(holdings, list) else [],
                )
                if sent_count is None:
                    sent_count = len(pending_notifications)
                if sent_count > 0:
                    repository.mark_fill_notifications_sent(
                        pending_notifications[:sent_count]
                    )
                    for record in pending_notifications[:sent_count]:
                        record_notification_event(
                            repository,
                            event_type="FILL_NOTIFICATION_SENT",
                            severity="INFO",
                            reason_code="FILL_NOTIFICATION_SENT",
                            ticker=record.ticker,
                            details={"side": record.side, "order_no": record.order_no},
                            fallback_bot_log=False,
                        )
                for record in pending_notifications[sent_count:]:
                    record_notification_event(
                        repository,
                        event_type="FILL_NOTIFICATION_FAILED",
                        severity="WARNING",
                        reason_code="FILL_NOTIFICATION_FAILED",
                        ticker=record.ticker,
                        details={"side": record.side, "order_no": record.order_no},
                        fallback_bot_log=False,
                    )
            elif pending_notifications and send_fill_notifications_func is None:
                for record in pending_notifications:
                    record_notification_event(
                        repository,
                        event_type="FILL_NOTIFICATION_SKIPPED_NO_SENDER",
                        severity="WARNING",
                        reason_code="FILL_NOTIFICATION_SKIPPED_NO_SENDER",
                        ticker=record.ticker,
                        details={"side": record.side, "order_no": record.order_no},
                        fallback_bot_log=False,
                    )
        if isinstance(holdings, list):
            repository.update_entry_profit_snapshots(
                trade_date,
                holding_prices(holdings),
                korea_time_text(),
            )
        repository.update_entry_profit_snapshot_finals(trade_date)
    except ValueError:
        return ""
    except Exception as exc:
        return f"모니터 DB 저장 실패: {safe_exception_summary(exc)}"
    return ""


def entry_profit_snapshots_from_fills(
    records: list[FillRecord],
) -> list[EntryProfitSnapshot]:
    return [
        EntryProfitSnapshot(
            trade_date=item.trade_date,
            ticker=item.ticker,
            ticker_name=item.ticker_name,
            entry_time=item.fill_time,
            entry_price_usd=item.fill_price_usd,
            strategy_version=item.strategy_version,
        )
        for item in records
        if is_buy_side(item.side) and item.fill_time and item.fill_price_usd > 0
    ]


def holding_prices(holdings: list[object]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for item in holdings:
        if not isinstance(item, dict):
            continue
        ticker = _ticker(str(item.get("ticker", "")))
        price = float_text(
            item.get("closePrice")
            or item.get("lastPrice")
            or item.get("currentPrice")
            or item.get("price")
        )
        if ticker and price > 0:
            prices[ticker] = price
    return prices


def korea_time_text() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M:%S")


def is_buy_side(side: str) -> bool:
    normalized = side.strip().upper()
    return "매수" in side or normalized in {"BUY", "B"}


def float_text(value: object) -> float:
    try:
        return float(str(value or "0").replace("$", "").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def write_closed_state(monitor_state: Path) -> None:
    write_state_file(
        monitor_state,
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
    )


def write_state_file(monitor_state: Path, payload: dict[str, object]) -> None:
    state = dict(payload)
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    monitor_state.parent.mkdir(parents=True, exist_ok=True)
    temp_path = monitor_state.with_name(f"{monitor_state.name}.tmp")
    temp_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temp_path.replace(monitor_state)


def _ticker(value: str) -> str:
    return value.strip().upper()
