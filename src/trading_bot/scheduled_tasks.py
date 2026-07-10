from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from trading_bot.adapters.kis_http import KisJsonClient
from trading_bot.composition import (
    build_live_dry_run,
    build_live_exit_poll,
    build_mock_buy_executor,
    build_mock_sell_executor,
)
from trading_bot.candidate_notifications import send_candidate_list_notification
from trading_bot.config import (
    KisSettings,
    TradingSettings,
    load_notification_settings,
    load_settings,
)
from trading_bot.daily_report import write_daily_report
from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory
from trading_bot.exit_rule_diagnostics import build_exit_rule_diagnostics
from trading_bot.intraday_entries import (
    NoOrderDiagnostic,
    limited_intraday_buy_intents_with_diagnostics,
)
from trading_bot.market_calendar import (
    current_us_market_date,
    is_current_us_regular_session,
    is_current_us_trading_day,
)
from trading_bot.models import BotLog, FillRecord, PositionState
from trading_bot.monitor_state import state_from_dry_run
from trading_bot.notifications import send_alert_telegram_message
from trading_bot.schedule import DailyTasks
from trading_bot.scheduler_logging import safe_exception_summary, safe_scheduler_log
from trading_bot.scheduler_market_close import (
    save_daily_run_summary,
    save_daily_trade_summary_report,
    save_strategy_review_export,
    send_market_close_notice,
    send_market_close_report,
)
from trading_bot.scheduler_market_close_skip_notice import (
    send_auto_trading_data_packet_skipped_notice,
)
from trading_bot.scheduler_recheck import (
    fixed_opening_result,
    hybrid_recheck,
    recheck_fixed_watchlist,
    tag_mode_intents,
)
from trading_bot.scheduler_risk import (
    apply_stop_loss_entry_guards,
    saved_partial_take_profit_tickers,
)
from trading_bot.scheduler_orders import (
    cancel_logs,
    cancel_stale_mock_buy_orders,
    cancel_unfilled_orders_for_scheduler,
    release_cancelled_buy_tickers,
    retry_stale_mock_buy_orders,
    ticker,
    unfilled_cancel_seconds,
    unfilled_order_tickers,
)
from trading_bot.scheduler_state import (
    write_closed_state,
    write_live_state,
    write_state_file,
)
from trading_bot.scheduled_messages import log_row, recheck_message, watch_message
from trading_bot.trade_fill_notifications import (
    send_fill_notifications,
)
from trading_bot.trading_event_logger import record_buy_not_submitted
from trading_bot.trading_date import current_trade_date


NO_ORDER_RISK_GUARD = "NO_ORDER_RISK_GUARD"
MARKET_CLOSE_FILL_CONFIRM_TIMEOUT_SECONDS = 20.0
MARKET_CLOSE_FILL_CONFIRM_POLL_SECONDS = 2.0
SCREEN_AND_SCORE_JOB_ID = "screen_and_score"
PIPELINE_FAILURE_TELEGRAM_SENT = "PIPELINE_FAILURE_TELEGRAM_SENT"
PIPELINE_FAILURE_TELEGRAM_FAILED = "PIPELINE_FAILURE_TELEGRAM_FAILED"
MOCK_BUY_BLOCKED_MARKET_CONTEXT_UNRELIABLE = "MOCK_BUY_BLOCKED_MARKET_CONTEXT_UNRELIABLE"


def live_mock_tasks(
    settings: TradingSettings | Callable[[], TradingSettings],
    kis_settings: KisSettings,
    monitor_state: Path,
    trading_day: Callable[[], bool] = is_current_us_trading_day,
    regular_session: Callable[[], bool] = is_current_us_regular_session,
    trading_guard: Callable[[], str | None] | None = None,
    market_close_fill_confirm_timeout_seconds: float = MARKET_CLOSE_FILL_CONFIRM_TIMEOUT_SECONDS,
    market_close_fill_confirm_poll_seconds: float = MARKET_CLOSE_FILL_CONFIRM_POLL_SECONDS,
    market_close_fill_confirm_sleep: Callable[[float], None] = time.sleep,
) -> DailyTasks:
    # 스케줄러 안에서는 가장 최근 수집 결과를 들고 있다가 매수/감시 단계에서 재사용한다.
    latest = _LatestRunState()
    cycle_lock = Lock()

    def prepare_day() -> str:
        KisJsonClient(kis_settings).access_token()
        return "KIS 토큰 준비 완료."

    def dry_run() -> str:
        if not trading_day():
            # 미국 휴장일에는 주문뿐 아니라 후보 수집도 멈춰 화면에 스킵 상태를 남긴다.
            _write_closed_state(monitor_state)
            return "미국 휴장일이라 후보 점검을 건너뜁니다."
        current_settings = _current_settings(settings)
        runtime, repository = build_live_dry_run(
            current_settings,
            kis_settings,
            candidate_notification_sender=_daily_candidate_notification_sender(latest),
        )
        try:
            latest.result = runtime.run()
        except Exception as exc:
            _handle_screen_and_score_failure(monitor_state, SCREEN_AND_SCORE_JOB_ID, exc)
            raise
        latest.repository = repository
        latest.opening_result = latest.result
        latest.opening_trade_date = current_trade_date()
        latest.opening_fixed_mode = _candidate_mode(current_settings) in {"fixed", "hybrid"}
        _write_state_file(monitor_state, state_from_dry_run(latest.result))
        return f"후보 점검 완료: 선정 점수 {len(latest.result.scoring.selected)}건."

    def mock_buy() -> str:
        if not trading_day():
            _write_closed_state(monitor_state)
            return "미국 휴장일이라 모의 매수를 건너뜁니다."
        guarded = _guarded_trading_skip(trading_guard)
        if guarded is not None:
            return guarded
        if latest.result is None or latest.repository is None:
            dry_run()
        if latest.result is None or latest.repository is None:
            return "후보 점검이 실행되지 않아 모의 매수를 건너뜁니다."
        if getattr(latest.result.scoring, "blocked_reason", None) == "MARKET_CONTEXT_UNRELIABLE":
            safe_scheduler_log(
                "WARNING",
                "orders",
                f"{MOCK_BUY_BLOCKED_MARKET_CONTEXT_UNRELIABLE}: 시장 컨텍스트 신뢰 불가로 모의 매수를 건너뜁니다.",
                reject_reason=MOCK_BUY_BLOCKED_MARKET_CONTEXT_UNRELIABLE,
            )
            return f"{MOCK_BUY_BLOCKED_MARKET_CONTEXT_UNRELIABLE}: 시장 컨텍스트 신뢰 불가로 모의 매수를 건너뜁니다."
        current_settings = _current_settings(settings)
        intents = apply_stop_loss_entry_guards(
            list(latest.result.buy_intents),
            latest.repository,
            current_settings,
        )
        trades = build_mock_buy_executor(kis_settings, latest.repository, current_settings).execute(intents)
        latest.buy_tickers.update(item.ticker for item in intents)
        _write_live_state(monitor_state, kis_settings)
        return f"모의 매수 주문 {len(trades)}건 제출."

    def refresh_orders() -> str:
        if not trading_day():
            _write_closed_state(monitor_state)
            return "미국 휴장일이라 주문/체결 상태 갱신을 건너뜁니다."
        _write_live_state(monitor_state, kis_settings)
        return "모의 주문/체결/보유 상태를 갱신했습니다."

    def intraday_watch() -> str:
        if not regular_session():
            return "미국 정규장 시간이 아니라 1분 감시를 건너뜁니다."
        market_close_skip = _market_close_started_skip(latest, "1분 감시")
        if market_close_skip is not None:
            return market_close_skip
        if not cycle_lock.acquire(blocking=False):
            return _cycle_lock_busy_skip(latest, "1분 감시")
        try:
            market_close_skip = _market_close_started_skip(latest, "1분 감시")
            if market_close_skip is not None:
                return market_close_skip
            guarded = _guarded_trading_skip(trading_guard)
            if guarded is not None:
                return guarded
            current_settings = _current_settings(settings)
            accounts, monitor, repository = build_live_exit_poll(current_settings, kis_settings)
            positions = _with_entry_times(
                _remembered_highs(accounts.positions(), latest.highs),
                repository,
            )
            partial_done = latest.partial_take_profit_tickers | saved_partial_take_profit_tickers(repository)
            refreshed, exits = monitor.poll(
                positions,
                partial_take_profit_tickers=partial_done,
            )
            latest.highs.update({item.ticker: item.high_price_usd for item in refreshed})
            _save_exit_rule_diagnostics(repository, refreshed, current_settings)
            latest.pending_exits.intersection_update(item.ticker for item in refreshed)
            # 같은 보유 종목에 미체결 매도 주문을 중복 제출하지 않도록 보호한다.
            executable = [item for item in exits if item.ticker not in latest.pending_exits]
            trades = build_mock_sell_executor(kis_settings, repository, current_settings).execute(executable)
            latest.partial_take_profit_tickers.update(
                item.ticker for item in executable if item.exit_reason == "PARTIAL_TAKE_PROFIT"
            )
            latest.pending_exits.update(
                item.ticker for item in executable if item.exit_reason != "PARTIAL_TAKE_PROFIT"
            )
            retry_state, retry_logs = retry_stale_mock_buy_orders(
                current_settings,
                kis_settings,
                latest,
                build_live_dry_run_func=build_live_dry_run,
                build_mock_buy_executor_func=build_mock_buy_executor,
                apply_stop_loss_entry_guards_func=apply_stop_loss_entry_guards,
            )
            _write_live_state(
                monitor_state,
                kis_settings,
                screening_state=retry_state,
                extra_logs=[
                    log_row(
                        "1분 감시",
                        watch_message(refreshed, exits, executable, latest.pending_exits),
                    )
                ] + retry_logs,
            )
            return f"1분 감시 완료: 모의 매도 주문 {len(trades)}건 제출."
        finally:
            cycle_lock.release()

    def intraday_recheck() -> str:
        if not regular_session():
            return "미국 정규장 시간이 아니라 15분 재평가를 건너뜁니다."
        market_close_skip = _market_close_started_skip(latest, "15분 재평가")
        if market_close_skip is not None:
            return market_close_skip
        if not cycle_lock.acquire(blocking=False):
            return _cycle_lock_busy_skip(latest, "15분 재평가")
        try:
            market_close_skip = _market_close_started_skip(latest, "15분 재평가")
            if market_close_skip is not None:
                return market_close_skip
            guarded = _guarded_trading_skip(trading_guard)
            if guarded is not None:
                return guarded
            current_settings = _current_settings(settings)
            runtime, repository = build_live_dry_run(current_settings, kis_settings)
            fixed_opening = fixed_opening_result(latest, current_settings)
            mode = _candidate_mode(current_settings)
            if mode == "fixed" and fixed_opening is not None:
                # 장초반 고정 모드에서는 기존 후보만 최신 가격 기준으로 재평가한다.
                latest.result = recheck_fixed_watchlist(
                    runtime,
                    fixed_opening,
                    current_settings,
                    repository,
                )
            elif mode == "hybrid" and fixed_opening is not None:
                # 하이브리드는 장초반 고정 후보와 15분 신규 후보 상위권을 합쳐 감시한다.
                latest.result = hybrid_recheck(runtime, fixed_opening, current_settings, repository)
            else:
                # 15분 재수집 모드에서는 매번 새 후보를 수집해 점수를 다시 계산한다.
                latest.result = runtime.run()
            latest.repository = repository
            positions = runtime.accounts.positions()
            cancelled = cancel_stale_mock_buy_orders(
                kis_settings,
                current_settings.mock_unfilled_reorder_minutes,
                latest.retried_buy_tickers,
                current_settings.mock_unfilled_reorder_limit,
                unfilled_cancel_seconds(current_settings),
            )
            latest.cancelled_orders.extend(cancelled)
            release_cancelled_buy_tickers(latest, cancelled)
            unfilled = unfilled_order_tickers(kis_settings) - {
                ticker(str(item.get("ticker", ""))) for item in cancelled
            }
            # 재평가 매수는 미체결/이미 진입한 종목/일일 라운드 제한을 한 번 더 통과해야 한다.
            intents, no_order_diagnostics = limited_intraday_buy_intents_with_diagnostics(
                latest.result.buy_intents,
                positions,
                latest.buy_tickers,
                latest.add_on_tickers,
                unfilled,
                latest.intraday_entry_rounds,
                current_settings,
            )
            _mark_candidate_no_order_diagnostics(repository, no_order_diagnostics)
            intents = tag_mode_intents(intents, mode)
            pre_risk_intents = intents
            intents = apply_stop_loss_entry_guards(intents, repository, current_settings)
            _mark_candidate_no_order_diagnostics(
                repository,
                _risk_guard_no_order_diagnostics(pre_risk_intents, intents),
            )
            trades = build_mock_buy_executor(kis_settings, repository, current_settings).execute(intents)
            if trades:
                latest.intraday_entry_rounds += 1
                latest.buy_tickers.update(item.ticker for item in intents)
                held = {ticker(position.ticker) for position in positions}
                latest.add_on_tickers.update(
                    item.ticker for item in intents if ticker(item.ticker) in held
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
                ] + cancel_logs(cancelled, current_settings.mock_unfilled_reorder_minutes),
            )
            return (
                f"15분 재평가 완료: 선정 점수 {len(latest.result.scoring.selected)}건, "
                f"모의 매수 주문 {len(trades)}건 제출."
            )
        finally:
            cycle_lock.release()

    def cancel_unfilled() -> str:
        if not trading_day():
            _write_closed_state(monitor_state)
            return "미국 휴장일이라 미체결 주문 취소를 건너뜁니다."
        guarded = _guarded_trading_skip(trading_guard)
        if guarded is not None:
            return guarded
        cancelled = cancel_unfilled_orders_for_scheduler(kis_settings)
        latest.cancelled_orders.extend(cancelled)
        _write_live_state(monitor_state, kis_settings)
        return f"미체결 모의 주문 {len(cancelled)}건 취소."

    def close_session() -> str:
        if not trading_day():
            send_auto_trading_data_packet_skipped_notice(current_us_market_date())
            _write_closed_state(monitor_state)
            return "미국 휴장일이라 장마감 처리를 건너뜁니다."
        if not regular_session():
            return "미국 정규장 시간이 아니라 장마감 처리를 건너뜁니다."
        guarded = _guarded_trading_skip(trading_guard)
        if guarded is not None:
            return guarded
        latest.market_close_trade_date = current_trade_date()
        with cycle_lock:
            cancelled = _cancel_unfilled_orders_for_market_close(kis_settings)
            latest.cancelled_orders.extend(cancelled)
            current_settings = _current_settings(settings)
            accounts, monitor, repository = build_live_exit_poll(current_settings, kis_settings)
            baseline_state = _write_live_state(monitor_state, kis_settings)
            _, exits = monitor.poll(accounts.positions(), end_of_day=True)
            trades = build_mock_sell_executor(kis_settings, repository, current_settings).execute(exits)
            state = _wait_for_market_close_settlement(
                monitor_state,
                kis_settings,
                trades,
                baseline_state,
                timeout_seconds=market_close_fill_confirm_timeout_seconds,
                poll_seconds=market_close_fill_confirm_poll_seconds,
                sleep=market_close_fill_confirm_sleep,
            )
            save_daily_run_summary(
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
            save_daily_trade_summary_report()
            send_market_close_report(state)
            _save_strategy_review_export_safely()
            return (
                f"장마감 모의 매도 주문 {len(trades)}건 제출 및 "
                f"보고서 작성 완료: {report_path}"
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


def _handle_screen_and_score_failure(
    monitor_state: Path,
    job_id: str,
    exc: Exception,
) -> None:
    stage = _screen_and_score_failure_stage(exc)
    _write_screen_and_score_failure_status(monitor_state, job_id, stage, exc)
    marker = _send_pipeline_failure_notice(job_id, stage, exc)
    safe_scheduler_log(
        "WARNING",
        "notification",
        f"{marker}: job={job_id} stage={stage} exception={type(exc).__name__}",
        reject_reason=marker,
    )


def _send_pipeline_failure_notice(job_id: str, stage: str, exc: Exception) -> str:
    try:
        sent = send_alert_telegram_message(
            _pipeline_failure_message(job_id, stage, exc),
            load_notification_settings(),
        )
    except Exception:
        return PIPELINE_FAILURE_TELEGRAM_FAILED
    return PIPELINE_FAILURE_TELEGRAM_SENT if sent else PIPELINE_FAILURE_TELEGRAM_FAILED


def _pipeline_failure_message(job_id: str, stage: str, exc: Exception) -> str:
    return "\n".join(
        [
            "[자동매매 장애 알림]",
            f"발생시각(KST): {_kst_now_text()}",
            f"job: {job_id}",
            f"stage: {stage}",
            f"exception: {type(exc).__name__}",
            f"message: {_safe_exception_message(exc)}",
            f"후보 저장 전 실패: {_candidate_save_before_failure_text(stage)}",
            "monitor/state.json의 targets가 갱신되지 않았을 수 있습니다.",
        ]
    )


def _write_screen_and_score_failure_status(
    monitor_state: Path,
    job_id: str,
    stage: str,
    exc: Exception,
) -> None:
    try:
        status_path = monitor_state.with_name("screen_and_score_status.json")
        status_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = status_path.with_name(f"{status_path.name}.tmp")
        temp_path.write_text(
            json.dumps(
                {
                    "last_screen_and_score_status": "failed",
                    "last_screen_and_score_at": _kst_now_iso(),
                    "last_error": {
                        "job": job_id,
                        "stage": stage,
                        "exception_class": type(exc).__name__,
                        "exception_message": _safe_exception_message(exc),
                        "candidate_saved_before_failure": (
                            stage in {"market_context", "screening"}
                        ),
                    },
                    "state_targets_may_be_stale": True,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temp_path.replace(status_path)
    except Exception as status_exc:
        safe_scheduler_log(
            "WARNING",
            "scheduler",
            f"SCREEN_AND_SCORE_STATUS_WRITE_FAILED: {safe_exception_summary(status_exc)}",
            reject_reason="SCREEN_AND_SCORE_STATUS_WRITE_FAILED",
        )


def _screen_and_score_failure_stage(exc: Exception) -> str:
    message = str(exc)
    if "Nasdaq history" in message or "USD/KRW" in message:
        return "market_context"
    if "market_context" in message:
        return "market_context"
    if "save_daily" in message or "CANDIDATE_SNAPSHOT_SAVE_FAILED" in message:
        return "saving"
    if "score" in message.lower():
        return "scoring"
    return "screening"


def _candidate_save_before_failure_text(stage: str) -> str:
    if stage in {"market_context", "screening"}:
        return "예"
    return "확인 필요"


def _safe_exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return "-"
    upper = message.upper()
    sensitive_markers = (
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "APPKEY",
        "APP_KEY",
        "APPSECRET",
        "APP_SECRET",
        "CHAT_ID",
        "ACCOUNT",
        "KIS_",
        "TELEGRAM",
    )
    if any(marker in upper for marker in sensitive_markers):
        return type(exc).__name__
    return message[:200]


def _kst_now_text() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")


def _kst_now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _mark_candidate_no_order_diagnostics(
    repository,
    diagnostics: list[NoOrderDiagnostic],
) -> None:
    if not diagnostics:
        return
    trade_date = current_trade_date()
    for diagnostic in diagnostics:
        record_buy_not_submitted(
            repository,
            ticker=diagnostic.ticker,
            trade_date=trade_date,
            reason_code=diagnostic.reason,
            stage="INTRADAY_RECHECK",
            details={"detail": diagnostic.detail},
        )


def _risk_guard_no_order_diagnostics(
    before: list,
    after: list,
) -> list[NoOrderDiagnostic]:
    allowed = {ticker(intent.ticker) for intent in after}
    return [
        NoOrderDiagnostic(ticker(intent.ticker), NO_ORDER_RISK_GUARD, "risk guard filtered")
        for intent in before
        if ticker(intent.ticker) not in allowed
    ]


def _save_strategy_review_export_safely() -> Path | None:
    try:
        return save_strategy_review_export()
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "summary",
            f"STRATEGY_REVIEW_EXPORT_FAILED: {safe_exception_summary(exc)}",
            reject_reason="STRATEGY_REVIEW_EXPORT_FAILED",
        )
        return None


def _send_fill_notifications(records: list[FillRecord], holdings: list[object]) -> int:
    try:
        return send_fill_notifications(records, holdings)
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "notification",
            f"FILL_NOTIFICATION_FAILED: {safe_exception_summary(exc)}",
            reject_reason="FILL_NOTIFICATION_FAILED",
        )
        # 체결 알림 실패는 주문/DB 저장 흐름과 분리한다.
        return 0


def _cancel_unfilled_orders_for_market_close(kis_settings: KisSettings) -> list[dict[str, object]]:
    try:
        return cancel_unfilled_orders_for_scheduler(kis_settings)
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "orders",
            f"MARKET_CLOSE_UNFILLED_CANCEL_FAILED: {safe_exception_summary(exc)}",
            reject_reason="MARKET_CLOSE_UNFILLED_CANCEL_FAILED",
        )
        return []


@dataclass(frozen=True)
class _MarketCloseExpectation:
    ticker: str
    quantity: int
    baseline_sell_quantity: int
    baseline_holding_quantity: int


@dataclass(frozen=True)
class _MarketCloseSettlementStatus:
    completed: bool
    pending_quantities: dict[str, int]
    sources_ready: bool


def _wait_for_market_close_settlement(
    monitor_state: Path,
    kis_settings: KisSettings,
    trades: list[object],
    baseline_state: dict[str, object],
    *,
    timeout_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None],
) -> dict[str, object]:
    expectations = _market_close_expectations(trades, baseline_state)
    if not expectations:
        return baseline_state
    attempts = _market_close_poll_attempts(timeout_seconds, poll_seconds)
    baseline_sources_ready = _state_sources_ready(baseline_state)
    last_state = baseline_state
    last_status = _market_close_settlement_status(
        last_state,
        expectations,
        baseline_sources_ready=baseline_sources_ready,
    )
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            state = _write_live_state(monitor_state, kis_settings)
        except Exception as exc:
            last_error = exc
        else:
            last_state = state
            last_status = _market_close_settlement_status(
                state,
                expectations,
                baseline_sources_ready=baseline_sources_ready,
            )
            if last_status.completed:
                return state
        if attempt < attempts:
            sleep(max(0.0, poll_seconds))
    _log_market_close_confirmation_timeout(last_status, attempts, last_error)
    return last_state


def _market_close_expectations(
    trades: list[object],
    baseline_state: dict[str, object],
) -> list[_MarketCloseExpectation]:
    submitted = _submitted_sell_quantities(trades)
    if not submitted:
        return []
    baseline_sells = _sell_fill_quantities(baseline_state)
    baseline_holdings = _holding_quantities(baseline_state)
    return [
        _MarketCloseExpectation(
            ticker=symbol,
            quantity=quantity,
            baseline_sell_quantity=baseline_sells.get(symbol, 0),
            baseline_holding_quantity=baseline_holdings.get(symbol, 0),
        )
        for symbol, quantity in sorted(submitted.items())
        if quantity > 0
    ]


def _submitted_sell_quantities(trades: list[object]) -> dict[str, int]:
    quantities: dict[str, int] = {}
    for trade in trades:
        symbol = ticker(str(getattr(trade, "ticker", "")))
        quantity = _safe_int(getattr(trade, "quantity", 0))
        if symbol and quantity > 0:
            quantities[symbol] = quantities.get(symbol, 0) + quantity
    return quantities


def _market_close_settlement_status(
    state: dict[str, object],
    expectations: list[_MarketCloseExpectation],
    *,
    baseline_sources_ready: bool,
) -> _MarketCloseSettlementStatus:
    sources_ready = baseline_sources_ready and _state_sources_ready(state)
    if not sources_ready:
        return _MarketCloseSettlementStatus(
            completed=False,
            pending_quantities={item.ticker: item.quantity for item in expectations},
            sources_ready=False,
        )
    sells = _sell_fill_quantities(state)
    holdings = _holding_quantities(state)
    pending: dict[str, int] = {}
    for item in expectations:
        sell_delta = max(0, sells.get(item.ticker, 0) - item.baseline_sell_quantity)
        expected_holding = max(0, item.baseline_holding_quantity - item.quantity)
        current_holding = holdings.get(item.ticker, 0)
        if sell_delta < item.quantity or current_holding > expected_holding:
            pending[item.ticker] = max(item.quantity - sell_delta, 0)
    return _MarketCloseSettlementStatus(
        completed=not pending,
        pending_quantities=pending,
        sources_ready=True,
    )


def _market_close_poll_attempts(timeout_seconds: float, poll_seconds: float) -> int:
    if timeout_seconds <= 0 or poll_seconds <= 0:
        return 1
    return max(1, int(timeout_seconds / poll_seconds) + 1)


def _state_sources_ready(state: dict[str, object]) -> bool:
    health = state.get("dataHealth")
    if not isinstance(health, dict):
        return True
    return _source_ok(health.get("orders")) and _source_ok(health.get("holdings"))


def _source_ok(value: object) -> bool:
    if isinstance(value, dict):
        return bool(value.get("ok"))
    if isinstance(value, bool):
        return value
    return False


def _sell_fill_quantities(state: dict[str, object]) -> dict[str, int]:
    quantities: dict[str, int] = {}
    fills = state.get("fills", [])
    if not isinstance(fills, list):
        return quantities
    for item in fills:
        if not isinstance(item, dict) or not _is_sell_side(item.get("side")):
            continue
        symbol = ticker(str(item.get("ticker", "")))
        quantity = _safe_int(item.get("quantity"))
        if symbol and quantity > 0:
            quantities[symbol] = quantities.get(symbol, 0) + quantity
    return quantities


def _holding_quantities(state: dict[str, object]) -> dict[str, int]:
    quantities: dict[str, int] = {}
    holdings = state.get("holdings", [])
    if not isinstance(holdings, list):
        return quantities
    for item in holdings:
        if not isinstance(item, dict):
            continue
        symbol = ticker(str(item.get("ticker", "")))
        quantity = _safe_int(item.get("quantity"))
        if symbol:
            quantities[symbol] = quantity
    return quantities


def _is_sell_side(value: object) -> bool:
    side = str(value or "").strip().upper()
    return side in {"SELL", "SLL", "매도"} or "SELL" in side or "매도" in side


def _safe_int(value: object) -> int:
    try:
        return int(float(str(value or "0").replace(",", "").replace("주", "").strip() or 0))
    except (TypeError, ValueError):
        return 0


def _log_market_close_confirmation_timeout(
    status: _MarketCloseSettlementStatus,
    attempts: int,
    error: Exception | None,
) -> None:
    pending = _pending_summary(status.pending_quantities)
    suffix = ""
    if error is not None:
        suffix = f" last_error={safe_exception_summary(error)}"
    safe_scheduler_log(
        "WARNING",
        "orders",
        (
            "MARKET_CLOSE_FILL_CONFIRMATION_TIMEOUT: "
            f"pending={pending} attempts={attempts} sources_ready={status.sources_ready}{suffix}"
        ),
        reject_reason="MARKET_CLOSE_FILL_CONFIRMATION_TIMEOUT",
        actual_value=float(sum(status.pending_quantities.values())),
        threshold_value=0.0,
    )


def _pending_summary(pending_quantities: dict[str, int]) -> str:
    if not pending_quantities:
        return "-"
    return ",".join(f"{symbol}:{quantity}" for symbol, quantity in sorted(pending_quantities.items()))


def _market_close_started_skip(latest: "_LatestRunState", job_label: str) -> str | None:
    if latest.market_close_trade_date != current_trade_date():
        return None
    if job_label == "1분 감시":
        return "장마감 처리 중이라 1분 감시를 건너뜁니다."
    return f"오늘 장마감 처리가 시작되어 {job_label}를 건너뜁니다."


def _cycle_lock_busy_skip(latest: "_LatestRunState", job_label: str) -> str:
    if latest.market_close_trade_date == current_trade_date():
        return f"장마감 처리 중이라 {job_label}를 건너뜁니다."
    return f"다른 거래 작업 실행 중이라 {job_label}를 건너뜁니다."


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
        self.partial_take_profit_tickers: set[str] = set()
        self.buy_tickers: set[str] = set()
        self.add_on_tickers: set[str] = set()
        self.retried_buy_tickers: set[str] = set()
        self.intraday_entry_rounds = 0
        self.cancelled_orders: list[dict[str, object]] = []
        self.opening_result = None
        self.opening_trade_date = None
        self.opening_fixed_mode = False
        self.candidate_notification_dates: set[object] = set()
        self.market_close_trade_date = None


def _daily_candidate_notification_sender(latest: _LatestRunState):
    def send_once(trade_date, targets, scores, market_context=None) -> bool:
        if trade_date in latest.candidate_notification_dates:
            return False
        if market_context is None:
            sent = send_candidate_list_notification(trade_date, targets, scores)
        else:
            sent = send_candidate_list_notification(
                trade_date,
                targets,
                scores,
                market_context=market_context,
            )
        if sent:
            latest.candidate_notification_dates.add(trade_date)
        return sent

    return send_once


def _write_live_state(
    monitor_state: Path,
    kis_settings: KisSettings,
    screening_state: dict[str, object] | None = None,
    extra_logs: list[list[str]] | None = None,
) -> dict[str, object]:
    return write_live_state(
        monitor_state,
        kis_settings,
        screening_state=screening_state,
        extra_logs=extra_logs,
        send_fill_notifications_func=_send_fill_notifications,
    )


_write_closed_state = write_closed_state
_write_state_file = write_state_file


def trading_cycle_skip_reason(monitor_state: Path) -> str | None:
    reasons: list[str] = []
    try:
        import clr  # noqa: F401
    except Exception:
        reasons.append("clr_import=fail")
    if not mssql_dsn_from_env():
        reasons.append("db_configured=false")
    else:
        try:
            with closing(pyodbc_connect_factory()()) as connection:
                cursor = connection.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchall()
        except Exception:
            reasons.append("db_connected=false")
    freshness = _state_freshness(monitor_state)
    age_seconds = freshness["age_seconds"]
    if age_seconds is None:
        reasons.append("state=missing")
    elif age_seconds > 600:
        reasons.append(
            f"state=stale age_seconds={age_seconds} "
            f"state_freshness_source={freshness['source']} "
            f"state_last_updated={freshness['last_updated'] or '-'} "
            f"state_file_mtime={freshness['file_mtime'] or '-'} "
            "stale_threshold_seconds=600 state_fresh=false "
            "recovery=inspect_scheduler_state_write"
        )
    if not reasons:
        return None
    return "SKIP trading cycle: monitor degraded reason=" + ",".join(reasons)


def _guarded_trading_skip(
    trading_guard: Callable[[], str | None] | None,
) -> str | None:
    if trading_guard is None:
        return None
    return trading_guard()


def _state_age_seconds(path: Path) -> int | None:
    return _state_freshness(path)["age_seconds"]


def _state_freshness(
    path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    if not path.exists():
        return {
            "source": "missing",
            "last_updated": None,
            "file_mtime": None,
            "age_seconds": None,
        }
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    file_mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    last_updated_text: str | None = None
    timestamp = file_mtime
    source = "file_mtime"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_last_updated = payload.get("last_updated") if isinstance(payload, dict) else None
        if raw_last_updated not in (None, ""):
            last_updated_text = str(raw_last_updated)
            parsed = datetime.fromisoformat(last_updated_text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
                source = "last_updated_naive_utc"
            else:
                source = "last_updated"
            timestamp = parsed.astimezone(timezone.utc)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logging.getLogger(__name__).warning(
            "state_last_updated_parse_failed path=%s error=%s fallback=file_mtime",
            path,
            type(exc).__name__,
        )
    return {
        "source": source,
        "last_updated": last_updated_text,
        "file_mtime": file_mtime.isoformat(),
        "age_seconds": max(int((current - timestamp).total_seconds()), 0),
    }


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
            item.entry_time,
        )
        for item in positions
    ]


def _with_entry_times(
    positions: list[PositionState],
    repository: object,
) -> list[PositionState]:
    if not hasattr(repository, "position_entry_times"):
        return positions
    try:
        entry_times = repository.position_entry_times(current_trade_date())
    except Exception:
        return positions
    if not entry_times:
        return positions
    return [
        PositionState(
            item.ticker,
            item.entry_price_usd,
            item.quantity,
            item.last_price_usd,
            item.high_price_usd,
            item.entry_time or entry_times.get(ticker(item.ticker)),
        )
        for item in positions
    ]


def _save_exit_rule_diagnostics(
    repository: object,
    positions: list[PositionState],
    settings: TradingSettings,
) -> int:
    try:
        logs = build_exit_rule_diagnostics(positions, settings)
        for log in logs:
            repository.save_log(log)
        return len(logs)
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "scheduler",
            f"EXIT_RULE_DIAGNOSTICS_FAILED {safe_exception_summary(exc)}",
            reject_reason="EXIT_RULE_DIAGNOSTICS_FAILED",
        )
        return 0


def _current_settings(
    settings: TradingSettings | Callable[[], TradingSettings],
) -> TradingSettings:
    return settings() if callable(settings) else settings
