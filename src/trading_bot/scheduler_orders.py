from __future__ import annotations

from collections.abc import Callable

from trading_bot.adapters.kis_http import KisJsonClient
from trading_bot.adapters.kis_orders import KisMockOrderCanceller
from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.config import KisSettings, TradingSettings
from trading_bot.intraday_entries import limited_intraday_buy_intents
from trading_bot.models import BuyIntent
from trading_bot.monitor_state import state_from_dry_run
from trading_bot.order_cancellation import (
    cancel_unfilled_orders,
    stale_unfilled_buy_cancel_requests,
)
from trading_bot.scheduled_messages import log_row
from trading_bot.scheduler_logging import safe_exception_summary, safe_scheduler_log
from trading_bot.scheduler_recheck import append_entry_reason
from trading_bot.market_calendar import current_us_market_date


BuildLiveDryRun = Callable[[TradingSettings, KisSettings], tuple[object, object]]
BuildMockBuyExecutor = Callable[[KisSettings, object, TradingSettings], object]
StopLossGuard = Callable[[list[BuyIntent], object, TradingSettings], list[BuyIntent]]


def retry_stale_mock_buy_orders(
    settings: TradingSettings,
    kis_settings: KisSettings,
    latest,
    *,
    build_live_dry_run_func: BuildLiveDryRun,
    build_mock_buy_executor_func: BuildMockBuyExecutor,
    apply_stop_loss_entry_guards_func: StopLossGuard,
) -> tuple[dict[str, object] | None, list[list[str]]]:
    cancelled = cancel_stale_mock_buy_orders(
        kis_settings,
        settings.mock_unfilled_reorder_minutes,
        latest.retried_buy_tickers,
        settings.mock_unfilled_reorder_limit,
        unfilled_cancel_seconds(settings),
    )
    if not cancelled:
        return None, []
    latest.cancelled_orders.extend(cancelled)
    release_cancelled_buy_tickers(latest, cancelled)

    runtime, repository = build_live_dry_run_func(settings, kis_settings)
    latest.result = runtime.run()
    latest.repository = repository
    positions = runtime.accounts.positions()
    cancelled_tickers = {ticker(str(item.get("ticker", ""))) for item in cancelled}
    unfilled = unfilled_order_tickers(kis_settings) - cancelled_tickers
    intents = limited_intraday_buy_intents(
        latest.result.buy_intents,
        positions,
        latest.buy_tickers,
        latest.add_on_tickers,
        unfilled,
        latest.intraday_entry_rounds,
        settings,
    )
    intents = [
        append_entry_reason(
            intent,
            "UNFILLED_REORDER",
            f"미체결 {settings.mock_unfilled_reorder_minutes}분 경과 후 1회 재주문",
        )
        for intent in intents
    ]
    intents = apply_stop_loss_entry_guards_func(intents, repository, settings)
    trades = build_mock_buy_executor_func(kis_settings, repository, settings).execute(intents)
    if trades:
        latest.unfilled_reorder_count = getattr(latest, "unfilled_reorder_count", 0) + 1
        latest.unfilled_reorder_tickers = getattr(latest, "unfilled_reorder_tickers", set())
        latest.unfilled_reorder_tickers.update(item.ticker for item in intents)
        latest.buy_tickers.update(item.ticker for item in intents)
    return (
        state_from_dry_run(latest.result),
        [
            log_row(
                "미체결 재주문",
                f"{settings.mock_unfilled_reorder_minutes}분 지난 미체결 매수 "
                f"{len(cancelled)}건 취소, 재주문 {len(trades)}건",
            )
        ],
    )


def cancel_stale_mock_buy_orders(
    kis_settings: KisSettings,
    max_age_minutes: int,
    retried_tickers: set[str],
    retry_limit: int = 1,
    max_age_seconds: int | None = None,
) -> list[dict[str, object]]:
    if retry_limit <= 0:
        return []
    try:
        rows = mock_order_rows(kis_settings)
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "orders",
            f"STALE_MOCK_BUY_ORDER_LOOKUP_FAILED: {safe_exception_summary(exc)}",
            reject_reason="STALE_MOCK_BUY_ORDER_LOOKUP_FAILED",
        )
        return []
    requests = stale_unfilled_buy_cancel_requests(
        rows,
        max_age_minutes=max_age_minutes,
        retried_tickers=retried_tickers,
        max_age_seconds=max_age_seconds,
    )
    if not requests:
        return []
    canceller = KisMockOrderCanceller(
        KisOverseasClient(KisJsonClient(kis_settings)),
        kis_settings,
    )
    cancelled = []
    for request in requests:
        canceller.cancel(request)
        cancelled.append(request)
    retried_tickers.update(ticker(str(item.get("ticker", ""))) for item in cancelled)
    return cancelled


def release_cancelled_buy_tickers(
    latest,
    cancelled: list[dict[str, object]],
) -> None:
    for item in cancelled:
        cancelled_ticker = ticker(str(item.get("ticker", "")))
        latest.buy_tickers.discard(cancelled_ticker)
        latest.add_on_tickers.discard(cancelled_ticker)


def cancel_logs(
    cancelled: list[dict[str, object]],
    minutes: int,
) -> list[list[str]]:
    if not cancelled:
        return []
    tickers = ", ".join(ticker(str(item.get("ticker", ""))) for item in cancelled)
    return [log_row("미체결 취소", f"{minutes}분 지난 미체결 매수 취소: {tickers}")]


def unfilled_cancel_seconds(settings: TradingSettings) -> int | None:
    if settings.partial_fill_policy != "CANCEL_REMAINING":
        return None
    return max(0, settings.unfilled_cancel_after_seconds)


def unfilled_order_tickers(kis_settings: KisSettings) -> set[str]:
    return unfilled_order_tickers_from_rows(mock_order_rows(kis_settings))


def mock_order_rows(kis_settings: KisSettings) -> list[dict[str, object]]:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    return kis.mock_order_history(
        kis_settings.account_no,
        kis_settings.account_product,
        current_us_market_date().strftime("%Y%m%d"),
    )


def unfilled_order_tickers_from_rows(rows: list[dict[str, object]]) -> set[str]:
    return {
        row_ticker
        for row in rows
        if _int(row, "nccs_qty") > 0
        if (row_ticker := ticker(str(row.get("pdno", ""))))
    }


def cancel_unfilled_orders_for_scheduler(kis_settings: KisSettings) -> list[dict[str, object]]:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    rows = kis.mock_order_history(
        kis_settings.account_no,
        kis_settings.account_product,
        current_us_market_date().strftime("%Y%m%d"),
    )
    return cancel_unfilled_orders(rows, KisMockOrderCanceller(kis, kis_settings).cancel)


def ticker(value: str) -> str:
    return value.strip().upper()


def _int(row: dict[str, object], field: str) -> int:
    return int(float(str(row.get(field, 0)).replace(",", "") or 0))
