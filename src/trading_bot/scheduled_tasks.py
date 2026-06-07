from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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
from trading_bot.config import (
    KisSettings,
    TradingSettings,
    load_notification_settings,
    load_settings,
)
from trading_bot.daily_trade_summary import generate_daily_trade_summary
from trading_bot.daily_report import write_daily_report
from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory
from trading_bot.fill_persistence import fill_records_from_monitor_rows
from trading_bot.intraday_entries import limited_intraday_buy_intents
from trading_bot.live_monitor_state import live_kis_monitor_state
from trading_bot.market_calendar import (
    current_us_market_date,
    is_current_us_regular_session,
    is_current_us_trading_day,
)
from trading_bot.models import BotLog, BuyIntent, EntryProfitSnapshot, FillRecord, PositionState
from trading_bot.monitor_state import state_from_dry_run
from trading_bot.notifications import (
    send_alert_telegram_message,
    send_market_close_done,
)
from trading_bot.order_cancellation import (
    cancel_unfilled_orders,
    stale_unfilled_buy_cancel_requests,
)
from trading_bot.entry_planner import plan_buy_intents
from trading_bot.repositories import SqlServerDailyRepository, SqlServerMonitorRepository
from trading_bot.runtime import DryRunResult
from trading_bot.schedule import DailyTasks
from trading_bot.scheduled_messages import log_row, recheck_message, watch_message
from trading_bot.trade_fill_notifications import (
    fill_keys_from_history,
    new_fill_records,
    send_fill_notifications,
    send_market_close_report_from_records,
)
from trading_bot.trading_date import current_trade_date


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
        runtime, repository = build_live_dry_run(current_settings, kis_settings)
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
        intents = _apply_stop_loss_entry_guards(
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
        partial_done = latest.partial_take_profit_tickers | _saved_partial_take_profit_tickers(repository)
        refreshed, exits = monitor.poll(
            positions,
            partial_take_profit_tickers=partial_done,
        )
        latest.highs.update({item.ticker: item.high_price_usd for item in refreshed})
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
        retry_state, retry_logs = _retry_stale_mock_buy_orders(
            current_settings,
            kis_settings,
            latest,
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
        fixed_opening = _fixed_opening_result(latest, current_settings)
        mode = _candidate_mode(current_settings)
        if mode == "fixed" and fixed_opening is not None:
            # 장초반 고정 모드에서는 기존 후보만 최신 가격 기준으로 재평가한다.
            latest.result = _recheck_fixed_watchlist(
                runtime,
                fixed_opening,
                current_settings,
                repository,
            )
        elif mode == "hybrid" and fixed_opening is not None:
            # 하이브리드는 장초반 고정 후보와 15분 신규 후보 상위권을 합쳐 감시한다.
            latest.result = _hybrid_recheck(runtime, fixed_opening, current_settings, repository)
        else:
            # 15분 재수집 모드에서는 매번 새 후보를 수집해 점수를 다시 계산한다.
            latest.result = runtime.run()
        latest.repository = repository
        positions = runtime.accounts.positions()
        cancelled = _cancel_stale_mock_buy_orders(
            kis_settings,
            current_settings.mock_unfilled_reorder_minutes,
            latest.retried_buy_tickers,
            current_settings.mock_unfilled_reorder_limit,
            _unfilled_cancel_seconds(current_settings),
        )
        latest.cancelled_orders.extend(cancelled)
        _release_cancelled_buy_tickers(latest, cancelled)
        unfilled = _unfilled_order_tickers(kis_settings) - {
            _ticker(str(item.get("ticker", ""))) for item in cancelled
        }
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
        intents = _tag_mode_intents(intents, mode)
        intents = _apply_stop_loss_entry_guards(intents, repository, current_settings)
        trades = build_mock_buy_executor(kis_settings, repository, current_settings).execute(intents)
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
            ] + _cancel_logs(cancelled, current_settings.mock_unfilled_reorder_minutes),
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
        cancelled = _cancel_unfilled_orders(kis_settings)
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
        cancelled = _cancel_unfilled_orders(kis_settings)
        latest.cancelled_orders.extend(cancelled)
        current_settings = _current_settings(settings)
        accounts, monitor, repository = build_live_exit_poll(current_settings, kis_settings)
        _, exits = monitor.poll(accounts.positions(), end_of_day=True)
        trades = build_mock_sell_executor(kis_settings, repository, current_settings).execute(exits)
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
        _save_daily_trade_summary_report()
        _send_market_close_notice()
        _send_market_close_report(state)
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
        # 운용 결과 저장 실패가 장중 주문/감시 루프를 멈추지 않도록 무시한다.
        return


def _save_daily_trade_summary_report() -> None:
    try:
        generate_daily_trade_summary(trade_date=current_trade_date(), mode="mock")
    except Exception as exc:
        _log_daily_trade_summary_failure(exc)


def _log_daily_trade_summary_failure(exc: Exception) -> None:
    try:
        SqlServerDailyRepository(pyodbc_connect_factory()).save_log(
            BotLog(
                "WARNING",
                "summary",
                f"SUMMARY_REPORT_SAVE_FAILED: {type(exc).__name__}",
                reject_reason="SUMMARY_REPORT_SAVE_FAILED",
            )
        )
    except Exception:
        return


def _send_market_close_notice() -> None:
    try:
        send_market_close_done(load_notification_settings())
    except Exception:
        # 알림 실패는 주문/장마감 정산 흐름과 분리한다.
        return


def _send_fill_notifications(records: list[FillRecord], holdings: list[object]) -> None:
    try:
        send_fill_notifications(records, holdings)
    except Exception:
        # 체결 알림 실패는 주문/DB 저장 흐름과 분리한다.
        return


def _send_market_close_report(state: dict[str, object]) -> None:
    fills = state.get("fills", [])
    holdings = state.get("holdings", [])
    if not isinstance(fills, list):
        return
    try:
        notification_settings = load_notification_settings()
        repository = SqlServerDailyRepository(pyodbc_connect_factory())
        trade_date = current_trade_date()
        records = fill_records_from_monitor_rows(
            fills,
            repository.sell_entry_prices(trade_date),
            repository.entry_reasons(trade_date),
            settings=load_settings(),
        )
        send_market_close_report_from_records(
            records,
            holdings if isinstance(holdings, list) else [],
            sender=lambda message: send_alert_telegram_message(
                message,
                notification_settings,
            ),
        )
    except Exception:
        # 장마감 요약 알림 실패는 장마감 처리 결과와 분리한다.
        return


def _apply_stop_loss_entry_guards(
    intents: list[BuyIntent],
    repository,
    settings: TradingSettings,
) -> list[BuyIntent]:
    if not intents:
        return []
    if _consecutive_stop_loss_count(repository) >= settings.max_consecutive_stop_loss_count:
        repository.save_log(
            BotLog(
                "WARNING",
                "risk",
                "연속 손절 제한에 도달해 신규 매수를 중단했습니다.",
                reject_reason="CONSECUTIVE_STOP_LOSS_LIMIT",
                actual_value=float(_consecutive_stop_loss_count(repository)),
                threshold_value=float(settings.max_consecutive_stop_loss_count),
            )
        )
        return []
    allowed: list[BuyIntent] = []
    for intent in intents:
        last_stop_loss_at = _last_stop_loss_at(repository, intent.ticker)
        if _cooldown_active(last_stop_loss_at, settings.stop_loss_cooldown_minutes):
            repository.save_log(
                BotLog(
                    "WARNING",
                    "risk",
                    f"손절 후 쿨다운으로 신규 매수를 차단했습니다: {intent.ticker}",
                    symbol=intent.ticker,
                    reject_reason="STOP_LOSS_COOLDOWN",
                    actual_value=float(settings.stop_loss_cooldown_minutes),
                    threshold_value=float(settings.stop_loss_cooldown_minutes),
                )
            )
            continue
        allowed.append(intent)
    return allowed


def _consecutive_stop_loss_count(repository) -> int:
    try:
        if hasattr(repository, "consecutive_stop_loss_count"):
            return int(repository.consecutive_stop_loss_count(current_trade_date()))
    except Exception:
        return 0
    return 0


def _last_stop_loss_at(repository, ticker: str):
    try:
        if hasattr(repository, "last_stop_loss_at"):
            return repository.last_stop_loss_at(current_trade_date(), ticker)
    except Exception:
        return None
    return None


def _cooldown_active(last_stop_loss_at, cooldown_minutes: int) -> bool:
    if last_stop_loss_at is None or cooldown_minutes <= 0:
        return False
    if isinstance(last_stop_loss_at, str):
        try:
            last_stop_loss_at = datetime.fromisoformat(last_stop_loss_at)
        except ValueError:
            return False
    now = datetime.now(last_stop_loss_at.tzinfo) if last_stop_loss_at.tzinfo else datetime.now()
    return now - last_stop_loss_at < timedelta(minutes=cooldown_minutes)


def _saved_partial_take_profit_tickers(repository) -> set[str]:
    try:
        if hasattr(repository, "partial_take_profit_tickers"):
            return set(repository.partial_take_profit_tickers(current_trade_date()))
    except Exception:
        return set()
    return set()


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


def _recheck_fixed_watchlist(
    runtime,
    latest_result: DryRunResult,
    settings: TradingSettings,
    repository,
) -> DryRunResult:
    account = runtime.accounts.current_account()
    selected = latest_result.scoring.selected[: settings.opening_fixed_candidate_limit]
    breakout_inputs = {
        item.ticker: runtime.breakout.breakout_input(item.ticker)
        for item in selected
    }
    intents = _plan_buy_intents_with_evaluation(
        selected,
        breakout_inputs,
        account,
        settings,
        repository=repository,
        trade_date=_scoring_trade_date(latest_result.scoring),
        source="fixed_recheck",
    )
    return DryRunResult(account, latest_result.scoring, tuple(intents))


def _hybrid_recheck(
    runtime,
    opening_result: DryRunResult,
    settings: TradingSettings,
    repository,
) -> DryRunResult:
    refreshed = runtime.run()
    account = runtime.accounts.current_account()
    selected = _hybrid_selected_scores(opening_result, refreshed, settings)
    breakout_inputs = {
        item.ticker: runtime.breakout.breakout_input(item.ticker)
        for item in selected
    }
    intents = _plan_buy_intents_with_evaluation(
        selected,
        breakout_inputs,
        account,
        settings,
        repository=repository,
        trade_date=_scoring_trade_date(refreshed.scoring),
        source="hybrid_recheck",
    )
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


def _plan_buy_intents_with_evaluation(
    selected,
    breakout_inputs,
    account,
    settings,
    *,
    repository,
    trade_date,
    source: str,
) -> list[BuyIntent]:
    try:
        return plan_buy_intents(
            selected,
            breakout_inputs,
            account,
            settings,
            repository=repository,
            trade_date=trade_date,
            source=source,
        )
    except TypeError as exc:
        if "unexpected keyword" not in str(exc):
            raise
        return plan_buy_intents(selected, breakout_inputs, account, settings)


def _scoring_trade_date(scoring) -> object:
    return getattr(scoring, "trade_date", current_trade_date())


def _tag_mode_intents(intents: list[BuyIntent], mode: str) -> list[BuyIntent]:
    reason = {
        "fixed": "OPENING_FIXED",
        "hybrid": "HYBRID_CANDIDATE",
    }.get(mode, "REFRESH_CANDIDATE")
    detail = {
        "fixed": "장초반 고정 후보 재평가",
        "hybrid": "장초반 고정 후보와 15분 신규 후보 결합",
    }.get(mode, "15분마다 신규 후보 재수집")
    return [_append_entry_reason(intent, reason, detail) for intent in intents]


def _append_entry_reason(intent: BuyIntent, reason: str, detail: str) -> BuyIntent:
    reasons = [item for item in intent.entry_reason.split("+") if item]
    if reason not in reasons:
        reasons.append(reason)
    detail_text = "; ".join(item for item in (intent.entry_reason_detail, detail) if item)
    return replace(intent, entry_reason="+".join(reasons), entry_reason_detail=detail_text)


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
    _write_state_file(monitor_state, live_state)
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
            settings = load_settings()
            entry_prices = repository.sell_entry_prices(trade_date)
            entry_reasons = repository.entry_reasons(trade_date)
            existing_fill_keys = fill_keys_from_history(
                repository.history_fills(trade_date, limit=1000)
            )
            records = fill_records_from_monitor_rows(
                fills,
                entry_prices,
                entry_reasons,
                settings=settings,
            )
            new_records = new_fill_records(records, existing_fill_keys)
            if records:
                repository.save_fills(records)
                repository.save_entry_profit_snapshots(
                    _entry_profit_snapshots_from_fills(records)
                )
                if any(item.profit_usd is not None for item in records):
                    _save_daily_run_summary(settings, None, None)
            if new_records:
                _send_fill_notifications(
                    new_records,
                    holdings if isinstance(holdings, list) else [],
                )
        if isinstance(holdings, list):
            repository.update_entry_profit_snapshots(
                trade_date,
                _holding_prices(holdings),
                _korea_time_text(),
            )
        repository.update_entry_profit_snapshot_finals(trade_date)
    except ValueError:
        return ""
    except Exception as exc:
        return f"모니터 DB 저장 실패: {exc}"
    return ""


def _entry_profit_snapshots_from_fills(
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
        if _is_buy_side(item.side) and item.fill_time and item.fill_price_usd > 0
    ]


def _holding_prices(holdings: list[object]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for item in holdings:
        if not isinstance(item, dict):
            continue
        ticker = _ticker(str(item.get("ticker", "")))
        price = _float_text(
            item.get("closePrice")
            or item.get("lastPrice")
            or item.get("currentPrice")
            or item.get("price")
        )
        if ticker and price > 0:
            prices[ticker] = price
    return prices


def _korea_time_text() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M:%S")


def _is_buy_side(side: str) -> bool:
    normalized = side.strip().upper()
    return "매수" in side or normalized in {"BUY", "B"}


def _float_text(value: object) -> float:
    try:
        return float(str(value or "0").replace("$", "").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def _write_closed_state(monitor_state: Path) -> None:
    _write_state_file(
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


def _write_state_file(monitor_state: Path, payload: dict[str, object]) -> None:
    state = dict(payload)
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    monitor_state.parent.mkdir(parents=True, exist_ok=True)
    temp_path = monitor_state.with_name(f"{monitor_state.name}.tmp")
    temp_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temp_path.replace(monitor_state)


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


def _retry_stale_mock_buy_orders(
    settings: TradingSettings,
    kis_settings: KisSettings,
    latest: _LatestRunState,
) -> tuple[dict[str, object] | None, list[list[str]]]:
    cancelled = _cancel_stale_mock_buy_orders(
        kis_settings,
        settings.mock_unfilled_reorder_minutes,
        latest.retried_buy_tickers,
        settings.mock_unfilled_reorder_limit,
        _unfilled_cancel_seconds(settings),
    )
    if not cancelled:
        return None, []
    latest.cancelled_orders.extend(cancelled)
    _release_cancelled_buy_tickers(latest, cancelled)

    runtime, repository = build_live_dry_run(settings, kis_settings)
    latest.result = runtime.run()
    latest.repository = repository
    positions = runtime.accounts.positions()
    cancelled_tickers = {_ticker(str(item.get("ticker", ""))) for item in cancelled}
    unfilled = _unfilled_order_tickers(kis_settings) - cancelled_tickers
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
        _append_entry_reason(
            intent,
            "UNFILLED_REORDER",
            f"미체결 {settings.mock_unfilled_reorder_minutes}분 경과 후 1회 재주문",
        )
        for intent in intents
    ]
    intents = _apply_stop_loss_entry_guards(intents, repository, settings)
    trades = build_mock_buy_executor(kis_settings, repository, settings).execute(intents)
    if trades:
        latest.intraday_entry_rounds += 1
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


def _cancel_stale_mock_buy_orders(
    kis_settings: KisSettings,
    max_age_minutes: int,
    retried_tickers: set[str],
    retry_limit: int = 1,
    max_age_seconds: int | None = None,
) -> list[dict[str, object]]:
    if retry_limit <= 0:
        return []
    try:
        rows = _mock_order_rows(kis_settings)
    except Exception:
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
    retried_tickers.update(_ticker(str(item.get("ticker", ""))) for item in cancelled)
    return cancelled


def _release_cancelled_buy_tickers(
    latest: _LatestRunState,
    cancelled: list[dict[str, object]],
) -> None:
    for item in cancelled:
        ticker = _ticker(str(item.get("ticker", "")))
        latest.buy_tickers.discard(ticker)
        latest.add_on_tickers.discard(ticker)


def _cancel_logs(
    cancelled: list[dict[str, object]],
    minutes: int,
) -> list[list[str]]:
    if not cancelled:
        return []
    tickers = ", ".join(_ticker(str(item.get("ticker", ""))) for item in cancelled)
    return [log_row("미체결 취소", f"{minutes}분 지난 미체결 매수 취소: {tickers}")]


def _unfilled_cancel_seconds(settings: TradingSettings) -> int | None:
    if settings.partial_fill_policy != "CANCEL_REMAINING":
        return None
    return max(0, settings.unfilled_cancel_after_seconds)


def _unfilled_order_tickers(kis_settings: KisSettings) -> set[str]:
    return _unfilled_order_tickers_from_rows(_mock_order_rows(kis_settings))


def _mock_order_rows(kis_settings: KisSettings) -> list[dict[str, object]]:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    return kis.mock_order_history(
        kis_settings.account_no,
        kis_settings.account_product,
        current_us_market_date().strftime("%Y%m%d"),
    )


def _unfilled_order_tickers_from_rows(rows: list[dict[str, object]]) -> set[str]:
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
