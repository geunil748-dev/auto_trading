from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path

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
from trading_bot.schedule import DailyTasks
from trading_bot.scheduler_logging import safe_exception_summary, safe_scheduler_log
from trading_bot.scheduler_market_close import (
    save_daily_run_summary,
    save_daily_trade_summary_report,
    send_market_close_notice,
    send_market_close_report,
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
from trading_bot.trading_date import current_trade_date


NO_ORDER_RISK_GUARD = "NO_ORDER_RISK_GUARD"


def live_mock_tasks(
    settings: TradingSettings | Callable[[], TradingSettings],
    kis_settings: KisSettings,
    monitor_state: Path,
    trading_day: Callable[[], bool] = is_current_us_trading_day,
    regular_session: Callable[[], bool] = is_current_us_regular_session,
    trading_guard: Callable[[], str | None] | None = None,
) -> DailyTasks:
    # 스케줄러 안에서는 가장 최근 수집 결과를 들고 있다가 매수/감시 단계에서 재사용한다.
    latest = _LatestRunState()

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
        latest.result = runtime.run()
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
        guarded = _guarded_trading_skip(trading_guard)
        if guarded is not None:
            return guarded
        current_settings = _current_settings(settings)
        accounts, monitor, repository = build_live_exit_poll(current_settings, kis_settings)
        positions = _remembered_highs(accounts.positions(), latest.highs)
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

    def intraday_recheck() -> str:
        if not regular_session():
            return "미국 정규장 시간이 아니라 15분 재평가를 건너뜁니다."
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
            _write_closed_state(monitor_state)
            return "미국 휴장일이라 장마감 처리를 건너뜁니다."
        if not regular_session():
            return "미국 정규장 시간이 아니라 장마감 처리를 건너뜁니다."
        guarded = _guarded_trading_skip(trading_guard)
        if guarded is not None:
            return guarded
        cancelled = cancel_unfilled_orders_for_scheduler(kis_settings)
        latest.cancelled_orders.extend(cancelled)
        current_settings = _current_settings(settings)
        accounts, monitor, repository = build_live_exit_poll(current_settings, kis_settings)
        _, exits = monitor.poll(accounts.positions(), end_of_day=True)
        trades = build_mock_sell_executor(kis_settings, repository, current_settings).execute(exits)
        state = _write_live_state(monitor_state, kis_settings)
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
        send_market_close_notice()
        send_market_close_report(state)
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


def _mark_candidate_no_order_diagnostics(
    repository,
    diagnostics: list[NoOrderDiagnostic],
) -> None:
    if not diagnostics:
        return
    trade_date = current_trade_date()
    for diagnostic in diagnostics:
        if hasattr(repository, "mark_candidate_evaluation_order_not_submitted"):
            try:
                repository.mark_candidate_evaluation_order_not_submitted(
                    diagnostic.ticker,
                    trade_date,
                    diagnostic.reason,
                )
            except Exception as exc:
                safe_scheduler_log(
                    "WARNING",
                    "candidate_evaluation",
                    "CANDIDATE_NO_ORDER_REASON_SAVE_FAILED: "
                    f"{safe_exception_summary(exc)}",
                    symbol=diagnostic.ticker,
                    reject_reason="CANDIDATE_NO_ORDER_REASON_SAVE_FAILED",
                )
        if hasattr(repository, "save_log"):
            try:
                repository.save_log(
                    BotLog(
                        "INFO",
                        "candidate_evaluation",
                        "candidate_order_not_submitted "
                        f"symbol={diagnostic.ticker} reason={diagnostic.reason}",
                        symbol=diagnostic.ticker,
                        reject_reason=diagnostic.reason,
                    )
                )
            except Exception:
                pass


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


def _daily_candidate_notification_sender(latest: _LatestRunState):
    def send_once(trade_date, targets, scores) -> bool:
        if trade_date in latest.candidate_notification_dates:
            return False
        sent = send_candidate_list_notification(trade_date, targets, scores)
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
    age_seconds = _state_age_seconds(monitor_state)
    if age_seconds is None:
        reasons.append("state=missing")
    elif age_seconds > 600:
        reasons.append(
            f"state=stale age_seconds={age_seconds} "
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
    if not path.exists():
        return None
    return max(int(datetime.now().timestamp() - path.stat().st_mtime), 0)


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
