from __future__ import annotations

import json
from datetime import date
from typing import Any

from trading_bot.performance_analysis import (
    ClosedTradeAnalysis,
    aggregate_exit_reason_stats,
    aggregate_strategy_stats,
    closed_trade_from_row,
    exit_label,
    strategy_label,
    tag_label,
)
from trading_bot.monitor_runner_profile import target_runner_profiles
from trading_bot.repositories import SqlServerMonitorRepository
from trading_bot.trading_date import current_trade_date


_GLOBAL_ENTRY_GATE_REASONS = {
    "MARKET_BELOW_MA20",
    "FX_VOLATILITY",
    "DAILY_ACCOUNT_LOSS",
    "OPEN_POSITION_LIMIT",
    "INVALID_ACCOUNT_EQUITY",
    "ACCOUNT_EXPOSURE_LIMIT",
}


class SqlMonitorStateSource:
    def __init__(self, repository: SqlServerMonitorRepository) -> None:
        self.repository = repository

    def read(self) -> dict[str, object]:
        scores = {row[0]: row for row in self.repository.latest_scores()}
        recheck_evaluations = _latest_recheck_evaluations(
            self.repository,
            current_trade_date(),
        )
        entry_block_reason = _latest_entry_block_reason(
            self.repository,
            current_trade_date(),
        )
        global_entry_gate = _latest_global_entry_gate_status(
            self.repository,
            current_trade_date(),
        )
        logs = self.repository.latest_logs()
        missing_score_decision = _missing_score_decision(logs)
        target_rows = self.repository.latest_targets()
        account = self.repository.latest_account(is_mock=True)
        real_account = self.repository.latest_account(is_mock=False)
        realized_profit = self.repository.today_realized_profit()
        realized_profit_rate = self.repository.today_realized_profit_rate()
        closed_trades = _closed_trade_analysis(self.repository.closed_trade_analysis())
        entry_profit_snapshots = [
            _entry_profit_snapshot(row)
            for row in self.repository.latest_entry_profit_snapshots()
        ]
        return {
            "date": current_trade_date().isoformat(),
            "account": _account(account, realized_profit, realized_profit_rate),
            "realAccount": _account(real_account, 0.0),
            "candidateSnapshot": _candidate_snapshot_status(
                self.repository.candidate_snapshot_status()
            ),
            "globalEntryGate": _global_entry_gate_status(global_entry_gate),
            "trading_stats": _trading_stats(self.repository.recent_trading_stats()),
            "targetRunnerProfiles": target_runner_profiles(
                target_rows,
                scores,
                recheck_evaluations,
            ),
            "targets": [
                _target(
                    row,
                    scores.get(row[0]),
                    missing_score_decision,
                    recheck_evaluations.get(str(row[0])),
                    entry_block_reason,
                )
                for row in target_rows
            ],
            "positions": [],
            "holdings": [_holding(row) for row in self.repository.latest_holdings()],
            "orders": [_order(row) for row in self.repository.latest_orders()],
            "fills": [_fill(row) for row in self.repository.latest_fills()],
            "gates": [
                ["저장소", "MSSQL"],
                ["점수 기록", str(len(scores))],
            ],
            "logs": [_log(row) for row in logs],
            "trades": [_trade(row) for row in self.repository.latest_trades()],
            "entryReasonStats": [
                _entry_reason_stat(row)
                for row in self.repository.entry_reason_performance()
            ],
            "strategyStats": _strategy_stats(closed_trades),
            "exitReasonStats": _exit_reason_stats(closed_trades),
            "recentTrades": [_recent_trade(row) for row in closed_trades[:30]],
            "entryProfitSnapshots": entry_profit_snapshots,
            "entryProfitSnapshotStats": _entry_profit_snapshot_stats(entry_profit_snapshots),
            "summary": _summary(realized_profit),
            "chart": {"closes": [], "movingAverage": []},
        }

    def read_history(self, trade_date: date) -> dict[str, object]:
        scores = {row[0]: row for row in self.repository.history_scores(trade_date)}
        recheck_evaluations = _latest_recheck_evaluations(self.repository, trade_date)
        entry_block_reason = _latest_entry_block_reason(self.repository, trade_date)
        global_entry_gate = _latest_global_entry_gate_status(self.repository, trade_date)
        logs = self.repository.history_logs(trade_date)
        missing_score_decision = _missing_score_decision(logs)
        target_rows = self.repository.history_targets(trade_date)
        account = self.repository.history_account(trade_date)
        realized_profit = self.repository.history_realized_profit(trade_date)
        realized_profit_rate = self.repository.history_realized_profit_rate(trade_date)
        closed_trades = _closed_trade_analysis(self.repository.closed_trade_analysis())
        entry_profit_snapshots = [
            _entry_profit_snapshot(row)
            for row in self.repository.history_entry_profit_snapshots(trade_date)
        ]
        return {
            "date": trade_date.isoformat(),
            "account": _account(account, realized_profit, realized_profit_rate),
            "globalEntryGate": _global_entry_gate_status(global_entry_gate),
            "targetRunnerProfiles": target_runner_profiles(
                target_rows,
                scores,
                recheck_evaluations,
            ),
            "targets": [
                _target(
                    row,
                    scores.get(row[0]),
                    missing_score_decision,
                    recheck_evaluations.get(str(row[0])),
                    entry_block_reason,
                )
                for row in target_rows
            ],
            "holdings": [_holding(row) for row in self.repository.history_holdings(trade_date)],
            "orders": [_order(row) for row in self.repository.history_orders(trade_date)],
            "fills": [_fill(row) for row in self.repository.history_fills(trade_date)],
            "logs": [_log(row) for row in logs],
            "trades": [_trade(row) for row in self.repository.history_trades(trade_date)],
            "runSummaries": [
                _run_summary(row)
                for row in self.repository.history_run_summaries(trade_date)
            ],
            "entryReasonStats": [
                _entry_reason_stat(row)
                for row in self.repository.entry_reason_performance()
            ],
            "strategyStats": _strategy_stats(closed_trades),
            "exitReasonStats": _exit_reason_stats(closed_trades),
            "recentTrades": [_recent_trade(row) for row in closed_trades[:30]],
            "entryProfitSnapshots": entry_profit_snapshots,
            "entryProfitSnapshotStats": _entry_profit_snapshot_stats(entry_profit_snapshots),
            "summary": _summary(realized_profit),
        }

    def read_daily_summaries(
        self,
        mode: str | None = None,
        limit: int = 30,
    ) -> dict[str, object]:
        return {
            "summaries": [
                _daily_summary_report(row)
                for row in self.repository.daily_trade_summary_reports(mode, limit)
            ]
        }

    def read_daily_summary_detail(
        self,
        trade_date: date,
        mode: str,
    ) -> dict[str, object]:
        row = self.repository.daily_trade_summary_report_detail(trade_date, mode)
        return {"summary": None if row is None else _daily_summary_report_detail(row)}


def _target(
    row: tuple[Any, ...],
    score: tuple[Any, ...] | None,
    missing_score_decision: str = "점수 계산 전",
    recheck: tuple[Any, ...] | None = None,
    entry_block_reason: tuple[Any, ...] | None = None,
) -> list[str]:
    if len(row) >= 6:
        ticker, ticker_name, price_usd, opening_volume, volume_ratio, price_change = row[:6]
        price_text = _usd_or_dash(price_usd)
    elif len(row) >= 5:
        ticker, ticker_name, price_usd, volume_ratio, price_change = row[:5]
        opening_volume = None
        price_text = _usd_or_dash(price_usd)
    elif len(row) >= 4:
        ticker, ticker_name, volume_ratio, price_change = row[:4]
        opening_volume = None
        price_text = "-"
    else:
        ticker, volume_ratio, price_change = row
        ticker_name = "-"
        opening_volume = None
        price_text = "-"
    score_value = (
        str(round(_fallback_filter_score(volume_ratio, price_change)))
        if score is None
        else str(round(_number(score[3])))
    )
    state = _target_decision(score, missing_score_decision)
    return [
        str(ticker),
        str(ticker_name or "-"),
        price_text,
        _volume_text(opening_volume),
        f"{_number(volume_ratio):.0f}%",
        f"{_number(price_change):+.1f}%",
        score_value,
        state,
        *_recheck_target_fields(recheck, entry_block_reason),
    ]


def _latest_recheck_evaluations(
    repository: object,
    trade_date: date,
) -> dict[str, tuple[Any, ...]]:
    if not hasattr(repository, "latest_recheck_evaluations"):
        return {}
    try:
        rows = repository.latest_recheck_evaluations(trade_date)  # type: ignore[attr-defined]
    except Exception:
        return {}
    return {str(row[0]): row for row in rows if row}


def _latest_entry_block_reason(
    repository: object,
    trade_date: date,
) -> tuple[Any, ...] | None:
    if not hasattr(repository, "latest_entry_block_reason"):
        return None
    try:
        return repository.latest_entry_block_reason(trade_date)  # type: ignore[attr-defined]
    except Exception:
        return None


def _latest_global_entry_gate_status(
    repository: object,
    trade_date: date,
) -> tuple[Any, ...] | None:
    if hasattr(repository, "latest_global_entry_gate_status"):
        try:
            return repository.latest_global_entry_gate_status(trade_date)  # type: ignore[attr-defined]
        except Exception:
            return None
    return _latest_entry_block_reason(repository, trade_date)


def _global_entry_gate_status(row: tuple[Any, ...] | None) -> dict[str, str | None]:
    if row is None:
        return {
            "status": "UNKNOWN",
            "reason": None,
            "label": "-",
            "effect": "최근 전역 진입 상태 확인 필요",
            "source": "-",
            "updatedAt": "-",
            "message": "",
        }
    if _global_entry_gate_bypassed(row):
        reason = _global_entry_gate_reason(row)
        return {
            "status": "BYPASSED",
            "reason": reason or None,
            "label": (
                f"{_reason_text(reason)} - 모의투자 예외"
                if reason
                else "모의투자 예외 진행"
            ),
            "effect": "모의투자 예외로 신규 매수 평가 진행",
            "source": _row_text(row, 2) or "pipeline",
            "updatedAt": _datetime_text(_row_value(row, 0)),
            "message": _row_text(row, 3) or _row_text(row, 1),
        }
    if _global_entry_gate_allowed(row):
        return {
            "status": "ALLOW",
            "reason": None,
            "label": "진입 가능",
            "effect": "신규 매수 가능",
            "source": _row_text(row, 2) or "pipeline",
            "updatedAt": _datetime_text(_row_value(row, 0)),
            "message": _row_text(row, 3) or _row_text(row, 1),
        }
    reason = _global_entry_gate_reason(row)
    if not reason:
        return {
            "status": "UNKNOWN",
            "reason": None,
            "label": "-",
            "effect": "최근 전역 진입 상태 확인 필요",
            "source": _row_text(row, 2) or "-",
            "updatedAt": _datetime_text(_row_value(row, 0)),
            "message": _row_text(row, 3) or _row_text(row, 1),
        }
    return {
        "status": "BLOCKED",
        "reason": reason,
        "label": _reason_text(reason),
        "effect": "신규 매수 주문 차단",
        "source": _row_text(row, 2) or "pipeline",
        "updatedAt": _datetime_text(_row_value(row, 0)),
        "message": _row_text(row, 3) or _row_text(row, 1),
    }


def _global_entry_gate_allowed(row: tuple[Any, ...]) -> bool:
    message = _row_text(row, 3) or _row_text(row, 1)
    return message.startswith("[SAVE_SCORES]")


def _global_entry_gate_bypassed(row: tuple[Any, ...]) -> bool:
    message = _row_text(row, 3) or _row_text(row, 1)
    return message.startswith("Entry bypassed:")


def _global_entry_gate_reason(row: tuple[Any, ...]) -> str:
    reject_reason = _row_text(row, 4)
    if reject_reason in _GLOBAL_ENTRY_GATE_REASONS:
        return reject_reason
    message = _row_text(row, 3) or _row_text(row, 1)
    if message.startswith("Entry blocked:"):
        reason = message.removeprefix("Entry blocked:").strip()
        if reason in _GLOBAL_ENTRY_GATE_REASONS:
            return reason
    if message.startswith("Entry bypassed:"):
        reason = message.removeprefix("Entry bypassed:").strip().split()[0]
        if reason in _GLOBAL_ENTRY_GATE_REASONS:
            return reason
    return ""


def _recheck_target_fields(
    row: tuple[Any, ...] | None,
    entry_block_reason: tuple[Any, ...] | None = None,
) -> list[str]:
    if row is None:
        if entry_block_reason is not None:
            return [
                "-",
                "GLOBAL_ENTRY_BLOCKED",
                _entry_block_reason_text(entry_block_reason),
                "pipeline",
                _datetime_text(_row_value(entry_block_reason, 0)),
            ]
        return ["-", "RECHECK_NOT_AVAILABLE", "RECHECK_NOT_AVAILABLE", "-", "-"]
    source = _row_text(row, 1)
    final_score = _score_text(_row_value(row, 5))
    buy_allowed = _truthy(_row_value(row, 6))
    order_submitted = _truthy(_row_value(row, 7))
    buy_block_reason = _row_text(row, 8)
    final_decision = _row_text(row, 10)
    if buy_allowed and order_submitted:
        status = "ORDER_SUBMITTED"
        reason = "ORDER_SUBMITTED"
    elif buy_allowed:
        status = "BUY_ALLOWED"
        reason = "BUY_ALLOWED"
    else:
        status = "BLOCKED"
        reason = buy_block_reason or final_decision or "UNKNOWN_BLOCK_REASON"
    return [
        final_score,
        status,
        reason,
        source or "-",
        _datetime_text(_row_value(row, 2)),
    ]


def _entry_block_reason_text(row: tuple[Any, ...]) -> str:
    message = _row_text(row, 1)
    if message.startswith("Entry blocked:"):
        reason = message.removeprefix("Entry blocked:").strip()
        return reason or "GLOBAL_ENTRY_BLOCKED"
    return message or "GLOBAL_ENTRY_BLOCKED"


def _row_value(row: tuple[Any, ...], index: int) -> Any:
    return row[index] if len(row) > index else None


def _row_text(row: tuple[Any, ...], index: int) -> str:
    value = _row_value(row, index)
    return "" if value is None else str(value).strip()


def _score_text(value: Any) -> str:
    if value is None:
        return "-"
    raw = str(value).strip()
    number = _number(value)
    if number == 0 and raw not in {"0", "0.0", "0.00", "0.0000"}:
        return "-"
    if float(number).is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _candidate_snapshot_status(row: tuple[Any, ...]) -> dict[str, object]:
    days = int(_number(row[0])) if len(row) > 0 else 0
    latest_date = "" if len(row) <= 1 or row[1] is None else str(row[1])
    latest_count = int(_number(row[2])) if len(row) > 2 else 0
    status = "" if len(row) <= 3 or row[3] is None else str(row[3])
    message = "" if len(row) <= 4 or row[4] is None else str(row[4])
    sample_sufficient = days >= 10
    sample_warning = ""
    if not sample_sufficient:
        sample_warning = (
            "INSUFFICIENT_SAMPLE_FOR_STRATEGY_DECISION: "
            "후보 기준일 또는 거래 수가 부족하여 전략 성과 판단에 사용할 수 없습니다. "
            "최소 후보 기준일 10일 이상, 거래 수 30건 이상을 권장합니다."
        )
    return {
        "candidate_snapshot_days": days,
        "latest_candidate_snapshot_date": latest_date,
        "latest_candidate_snapshot_count": latest_count,
        "sample_sufficient": sample_sufficient,
        "minimum_required_candidate_days": 10,
        "minimum_required_trade_count": 30,
        "last_candidate_snapshot_status": _level_text(status),
        "last_candidate_snapshot_message": _message_text(message),
        "sample_warning": sample_warning,
    }


def _trading_stats(row: tuple[Any, ...]) -> dict[str, object]:
    total_days = int(_number(row[0])) if len(row) > 0 else 0
    candidate_days = int(_number(row[1])) if len(row) > 1 else 0
    scoring_days = int(_number(row[2])) if len(row) > 2 else 0
    strict_filter_days = int(_number(row[3])) if len(row) > 3 else 0
    selected_days = int(_number(row[4])) if len(row) > 4 else 0
    return {
        "lookback_days": 30,
        "total_trading_days": total_days,
        "candidate_days": candidate_days,
        "candidate_rate": _rate_percent(candidate_days, total_days),
        "scoring_days": scoring_days,
        "scoring_rate": _rate_percent(scoring_days, total_days),
        "strict_filter_days": strict_filter_days,
        "strict_filter_rate": _rate_percent(strict_filter_days, total_days),
        "selected_days": selected_days,
        "selected_rate": _rate_percent(selected_days, total_days),
    }


def _rate_percent(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(value / total * 100, 1)


def _target_decision(
    score: tuple[Any, ...] | None,
    missing_score_decision: str = "점수 계산 전",
) -> str:
    if score is None:
        return missing_score_decision
    if bool(score[4]):
        return "최종 선정"
    return "선정점수/순위 미달"


def _missing_score_decision(logs: list[tuple[Any, ...]]) -> str:
    messages = [str(row[2]) for row in logs if len(row) >= 3]
    if any("STRICT_FILTER_NO_CANDIDATES" in message for message in messages):
        return "최소 후보 수 미달로 점수 계산 생략"
    if any(
        "[PIPELINE]" in message
        and "risk_pass_count=0" in message
        and "scoring_pass_count=0" in message
        for message in messages
    ):
        return "점수 계산 대상 없음"
    if any("[FILTER]" in message and "final_count=0" in message for message in messages):
        return "점수 계산 대상 없음"
    return "점수 계산 전"


def _holding(row: tuple[Any, ...]) -> dict[str, str]:
    ticker, ticker_name, quantity, average_price, open_price, close_price, total_price = row[:7]
    return {
        "ticker": str(ticker),
        "name": str(ticker_name or ""),
        "quantity": str(quantity),
        "averagePrice": _usd(_number(average_price)),
        "openPrice": _usd_or_dash(open_price),
        "closePrice": _usd_or_dash(close_price),
        "totalPrice": _usd(_number(total_price)),
    }


def _account(
    row: tuple[Any, ...] | None,
    realized_profit_usd: float,
    realized_profit_rate: float | None = None,
) -> dict[str, str]:
    if row is None:
        return {
            "cashUsd": "-",
            "equityUsd": "-",
            "investedUsd": "-",
            "cashKrw": "-",
            "equityKrw": "-",
            "openPositions": "-",
            "dailyProfitRate": "-" if realized_profit_rate is None else f"{realized_profit_rate:.2f}%",
            "realizedProfitUsd": _signed_usd(realized_profit_usd),
        }
    cash, equity, invested, open_positions, daily_profit_rate, realized = row[:6]
    cash_krw = row[6] if len(row) > 6 else None
    equity_krw = row[7] if len(row) > 7 else None
    realized_value = realized_profit_usd if realized_profit_usd else _number(realized)
    rate_value = _number(daily_profit_rate) if realized_profit_rate is None else realized_profit_rate
    return {
        "cashUsd": _usd(_number(cash)),
        "equityUsd": _usd(_number(equity)),
        "investedUsd": _usd(_number(invested)),
        "cashKrw": _krw_or_dash(cash_krw),
        "equityKrw": _krw_or_dash(equity_krw),
        "openPositions": str(int(_number(open_positions))),
        "dailyProfitRate": f"{rate_value:.2f}%",
        "realizedProfitUsd": _signed_usd(realized_value),
    }


def _order(row: tuple[Any, ...]) -> dict[str, str]:
    order_date, order_time, ticker, ticker_name, side, quantity, price, unfilled, order_no = row[:9]
    return {
        "date": _date_text(order_date),
        "time": "" if order_time is None else str(order_time),
        "ticker": str(ticker),
        "name": str(ticker_name or ""),
        "side": _side_text(side),
        "quantity": str(quantity),
        "price": _usd(_number(price)),
        "unfilled": str(unfilled),
        "orderNo": "" if order_no is None else str(order_no),
    }


def _log(row: tuple[Any, ...]) -> list[str]:
    created_at, level, message = row
    timestamp = created_at.strftime("%H:%M:%S") if hasattr(created_at, "strftime") else str(created_at)
    return [timestamp, _level_text(level), _message_text(message)]


def _trade(row: tuple[Any, ...]) -> dict[str, str]:
    strategy_version = row[12] if len(row) >= 13 else ""
    if len(row) >= 12:
        trade_date, created_at, ticker, ticker_name, order_type, order_price, quantity, exit_reason = row[:8]
        profit_usd = row[8]
        profit_rate = row[9]
        entry_reason = row[10]
        entry_reason_detail = row[11]
    elif len(row) >= 10:
        trade_date, created_at, ticker, ticker_name, order_type, order_price, quantity, exit_reason = row[:8]
        profit_usd = row[8]
        profit_rate = row[9]
        entry_reason = None
        entry_reason_detail = None
    elif len(row) >= 9:
        trade_date, created_at, ticker, order_type, order_price, quantity, exit_reason = row[:7]
        ticker_name = ""
        profit_usd = row[7]
        profit_rate = row[8]
        entry_reason = None
        entry_reason_detail = None
    else:
        trade_date, created_at = None, None
        ticker, order_type, order_price, quantity, exit_reason = row[:5]
        ticker_name = ""
        profit_usd = row[5] if len(row) > 5 else None
        profit_rate = row[6] if len(row) > 6 else None
        entry_reason = None
        entry_reason_detail = None
    date_text = _date_text(trade_date) if trade_date is not None else ""
    time_text = _time_text(created_at)
    reason = entry_reason if _side_text(order_type) == "매수" else exit_reason
    return {
        "date": date_text,
        "time": time_text,
        "orderedAt": f"{date_text} {time_text}".strip(),
        "ticker": str(ticker),
        "name": str(ticker_name or ""),
        "type": _side_text(order_type),
        "price": f"${_number(order_price):.2f}",
        "quantity": str(quantity),
        "exitReason": "" if reason is None else _reason_text(str(reason)),
        "entryReason": "" if entry_reason is None else _reason_text(str(entry_reason)),
        "entryReasonDetail": "" if entry_reason_detail is None else str(entry_reason_detail),
        "profitUsd": "" if profit_usd is None else _signed_usd(_number(profit_usd)),
        "profitRate": "" if profit_rate is None else f"{_number(profit_rate) * 100:+.2f}%",
        "strategyVersion": "" if strategy_version is None else str(strategy_version),
    }


def _fill(row: tuple[Any, ...]) -> dict[str, str]:
    fill_date, fill_time, ticker, ticker_name, side, quantity, fill_price, fill_amount = row[:8]
    profit_usd = row[8] if len(row) > 8 else None
    profit_rate = row[9] if len(row) > 9 else None
    entry_reason = row[10] if len(row) > 10 else None
    entry_reason_detail = row[11] if len(row) > 11 else None
    strategy_version = row[12] if len(row) > 12 else None
    date_text = _date_text(fill_date)
    time_text = "" if fill_time is None else str(fill_time)
    return {
        "date": date_text,
        "time": time_text,
        "filledAt": f"{date_text} {time_text}".strip(),
        "ticker": str(ticker),
        "name": str(ticker_name or ""),
        "side": _side_text(side),
        "quantity": str(quantity),
        "price": f"${_number(fill_price):,.2f}",
        "total": f"${_number(fill_amount):,.2f}",
        "profitUsd": "" if profit_usd is None else _signed_usd(_number(profit_usd)),
        "profitRate": "" if profit_rate is None else f"{_number(profit_rate) * 100:+.2f}%",
        "entryReason": "" if entry_reason is None else _reason_text(str(entry_reason)),
        "entryReasonDetail": "" if entry_reason_detail is None else str(entry_reason_detail),
        "strategyVersion": "" if strategy_version is None else str(strategy_version),
    }


def _entry_profit_snapshot(row: tuple[Any, ...]) -> dict[str, str]:
    (
        trade_date,
        ticker,
        ticker_name,
        entry_time,
        entry_price,
        profit_after_5m,
        profit_after_10m,
        profit_after_15m,
        profit_after_20m,
        profit_after_30m,
        profit_after_60m,
        final_exit_reason,
        final_profit_rate,
        strategy_version,
    ) = row[:14]
    return {
        "ticker": str(ticker),
        "ticker_name": str(ticker_name or ""),
        "entry_date": _date_text(trade_date),
        "entry_time": "" if entry_time is None else str(entry_time),
        "entry_price": _usd(_number(entry_price)),
        "profit_after_5m": _rate_or_dash(profit_after_5m),
        "profit_after_10m": _rate_or_dash(profit_after_10m),
        "profit_after_15m": _rate_or_dash(profit_after_15m),
        "profit_after_20m": _rate_or_dash(profit_after_20m),
        "profit_after_30m": _rate_or_dash(profit_after_30m),
        "profit_after_60m": _rate_or_dash(profit_after_60m),
        "final_exit_reason": "" if final_exit_reason is None else _reason_text(str(final_exit_reason)),
        "final_profit_rate": _rate_or_dash(final_profit_rate),
        "strategy_version": "" if strategy_version is None else str(strategy_version),
    }


def _entry_profit_snapshot_stats(rows: list[dict[str, str]]) -> dict[str, object]:
    finished = [row for row in rows if row.get("final_profit_rate") not in ("", "-")]
    stats: dict[str, object] = {
        "sampleCount": len(finished),
        "sampleSufficient": len(finished) >= 30,
        "sampleWarning": "" if len(finished) >= 30 else "표본 부족: 전략 판단 금지",
        "negativeStats": [],
    }
    negative_stats = []
    for minutes in (5, 10, 15, 20):
        key = f"profit_after_{minutes}m"
        negative_rows = [
            row
            for row in finished
            if _percent_text_number(row.get(key)) < 0
        ]
        wins = [
            row
            for row in negative_rows
            if _percent_text_number(row.get("final_profit_rate")) > 0
        ]
        count = len(negative_rows)
        negative_stats.append(
            {
                "minutes": str(minutes),
                "negativeCount": str(count),
                "finalWinRate": "-" if count == 0 else f"{len(wins) / count * 100:.1f}%",
            }
        )
    stats["negativeStats"] = negative_stats
    return stats


def _run_summary(row: tuple[Any, ...]) -> dict[str, str]:
    trade_date = row[0]
    mode = row[1]
    settings_json = row[2]
    realized_profit = row[3]
    realized_rate = row[4]
    eod_sell_count = row[5]
    cancelled_count = row[6]
    buy_fill_count = row[7] if len(row) > 8 else 0
    sell_fill_count = row[8] if len(row) > 8 else 0
    updated_at = row[9] if len(row) > 8 else row[7]
    settings = _settings_summary(settings_json)
    return {
        "date": _date_text(trade_date),
        "updatedAt": _time_text(updated_at),
        "mode": _mode_text(mode),
        "settings": settings["text"],
        "stopLossPercent": settings["stopLossPercent"],
        "takeProfitPercent": settings["takeProfitPercent"],
        "partialTakeProfit": settings["partialTakeProfit"],
        "minTotalScore": settings["minTotalScore"],
        "priceRange": settings["priceRange"],
        "minOpeningPriceChangePercent": settings["minOpeningPriceChangePercent"],
        "minVolumeRatio": settings["minVolumeRatio"],
        "maxOpeningGapPercent": settings["maxOpeningGapPercent"],
        "profitUsd": _signed_usd(_number(realized_profit)),
        "profitRate": f"{_number(realized_rate):+.2f}%",
        "eodSellCount": str(int(_number(eod_sell_count))),
        "cancelledOrderCount": str(int(_number(cancelled_count))),
        "buyFillCount": str(int(_number(buy_fill_count))),
        "sellFillCount": str(int(_number(sell_fill_count))),
    }


def _daily_summary_report(row: tuple[Any, ...]) -> dict[str, object]:
    summary_json = _summary_json(row[15])
    return {
        "tradeDate": _date_text(row[0]),
        "mode": str(row[1] or ""),
        "strategyVersion": str(row[2] or ""),
        "totalProfitUsd": _number(row[3]),
        "totalProfitRate": _number(row[4]),
        "tradeCount": int(_number(row[5])),
        "buyCount": int(_number(row[6])),
        "sellCount": int(_number(row[7])),
        "winRate": _number(row[8]),
        "stopLossCount": int(_number(row[9])),
        "takeProfitCount": int(_number(row[10])),
        "partialTakeProfitCount": _partial_take_profit_count(row[11], summary_json),
        "trailingStopCount": int(_number(row[12])),
        "eodCount": int(_number(row[13])),
        "sampleSufficient": _bool_value(row[14]),
        "summaryJson": summary_json,
        "summaryJsonParseFailed": _summary_json_parse_failed(row[15]),
        "updatedAt": _datetime_text(row[16]),
    }


def _daily_summary_report_detail(row: tuple[Any, ...]) -> dict[str, object]:
    summary_json = _summary_json(row[4])
    return {
        "tradeDate": _date_text(row[0]),
        "mode": str(row[1] or ""),
        "strategyVersion": str(row[2] or ""),
        "settingsSnapshotHash": str(row[3] or ""),
        "summaryJson": summary_json,
        "summaryJsonParseFailed": _summary_json_parse_failed(row[4]),
        "summaryText": str(row[5] or ""),
        "totalProfitUsd": _number(row[6]),
        "totalProfitRate": _number(row[7]),
        "tradeCount": int(_number(row[8])),
        "buyCount": int(_number(row[9])),
        "sellCount": int(_number(row[10])),
        "winRate": _number(row[11]),
        "stopLossCount": int(_number(row[12])),
        "takeProfitCount": int(_number(row[13])),
        "partialTakeProfitCount": _partial_take_profit_count(row[14], summary_json),
        "trailingStopCount": int(_number(row[15])),
        "eodCount": int(_number(row[16])),
        "sampleSufficient": _bool_value(row[17]),
        "createdAt": _datetime_text(row[18]),
        "updatedAt": _datetime_text(row[19]),
    }


def _summary_json(value: Any) -> dict[str, object]:
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _summary_json_parse_failed(value: Any) -> bool:
    text = str(value or "")
    if not text:
        return False
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return True
    return False


def _partial_take_profit_count(value: Any, summary_json: dict[str, object]) -> int:
    if value is not None:
        return int(_number(value))
    stats = summary_json.get("exitReasonStats", [])
    if not isinstance(stats, list):
        return 0
    for item in stats:
        if not isinstance(item, dict):
            continue
        if item.get("reason") == "PARTIAL_TAKE_PROFIT":
            return int(_number(item.get("count")))
    return 0


def _entry_reason_stat(row: tuple[Any, ...]) -> dict[str, str]:
    reason, count, total_profit, average_rate, win_rate = row[:5]
    return {
        "reason": _reason_text(str(reason)),
        "count": str(int(_number(count))),
        "totalProfitUsd": _signed_usd(_number(total_profit)),
        "averageProfitRate": f"{_number(average_rate) * 100:+.2f}%",
        "winRate": f"{_number(win_rate) * 100:.1f}%",
    }


def _closed_trade_analysis(rows: list[tuple[Any, ...]]) -> list[ClosedTradeAnalysis]:
    trades: list[ClosedTradeAnalysis] = []
    for row in rows:
        try:
            trades.append(closed_trade_from_row(row))
        except Exception:
            continue
    return trades


def _strategy_stats(trades: list[ClosedTradeAnalysis]) -> list[dict[str, str]]:
    return [
        {
            "strategy": str(row["strategy"]),
            "strategyText": str(row["strategyText"]),
            "count": str(int(_number(row["count"]))),
            "winRate": f"{_number(row['winRate']) * 100:.1f}%",
            "averageProfitRate": f"{_number(row['averageProfitRate']) * 100:+.2f}%",
            "totalProfitUsd": _signed_usd(_number(row["totalProfitUsd"])),
            "averageHoldingMinutes": _duration_text(_number(row["averageHoldingMinutes"])),
            "maxDrawdown": f"{_number(row['maxDrawdown']) * 100:+.2f}%",
        }
        for row in aggregate_strategy_stats(trades)
    ]


def _exit_reason_stats(trades: list[ClosedTradeAnalysis]) -> list[dict[str, str]]:
    return [
        {
            "exitReason": str(row["exitReason"]),
            "exitReasonText": str(row["exitReasonText"]),
            "count": str(int(_number(row["count"]))),
            "winRate": f"{_number(row['winRate']) * 100:.1f}%",
            "averageProfitRate": f"{_number(row['averageProfitRate']) * 100:+.2f}%",
            "totalProfitUsd": _signed_usd(_number(row["totalProfitUsd"])),
        }
        for row in aggregate_exit_reason_stats(trades)
    ]


def _recent_trade(trade: ClosedTradeAnalysis) -> dict[str, str]:
    tag_text = ", ".join(tag_label(tag) for tag in trade.entry_tags)
    return {
        "entryAt": _datetime_text(trade.entry_at),
        "exitAt": _datetime_text(trade.exit_at),
        "ticker": trade.ticker,
        "name": trade.ticker_name,
        "entryStrategy": trade.entry_strategy,
        "entryStrategyText": strategy_label(trade.entry_strategy),
        "entryTags": tag_text or "-",
        "exitReason": trade.exit_reason,
        "exitReasonText": exit_label(trade.exit_reason),
        "holdingTime": _duration_text(trade.holding_minutes),
        "profitRate": f"{trade.profit_rate * 100:+.2f}%",
        "profitUsd": _signed_usd(trade.profit_usd),
        "strategyVersion": trade.strategy_version or "-",
    }


def _datetime_text(value: Any) -> str:
    if value is None:
        return "-"
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return str(value)


def _duration_text(minutes: float) -> str:
    total = max(0, int(round(minutes)))
    hours, mins = divmod(total, 60)
    if hours:
        return f"{hours}시간 {mins}분"
    return f"{mins}분"


def _settings_summary(settings_json: Any) -> dict[str, str]:
    try:
        settings = json.loads(str(settings_json or "{}"))
    except json.JSONDecodeError:
        return _empty_settings_summary()
    labels = [
        ("손절", "stopLossPercent", "%"),
        ("익절", "takeProfitPercent", "%"),
        ("선정점수", "minTotalScore", "점"),
        ("가격", "minPriceUsd", ""),
        ("최고가", "maxPriceUsd", ""),
        ("상승률", "minOpeningPriceChangePercent", "%"),
        ("거래량", "minVolumeRatio", "배"),
        ("갭", "maxOpeningGapPercent", "%"),
    ]
    parts = []
    for label, key, suffix in labels:
        if key not in settings:
            continue
        value = settings[key]
        if key == "minPriceUsd":
            max_value = settings.get("maxPriceUsd")
            parts.append(f"가격 ${_compact_number(value)}~${_compact_number(max_value)}")
        elif key == "maxPriceUsd":
            continue
        else:
            parts.append(f"{label} {_compact_number(value)}{suffix}")
    if "partialTakeProfitEnabled" in settings:
        state = "사용" if settings["partialTakeProfitEnabled"] else "미사용"
        parts.append(f"분할익절 {state}")
    return {
        "text": " · ".join(parts) or "-",
        "stopLossPercent": _setting_value(settings, "stopLossPercent", "%"),
        "takeProfitPercent": _setting_value(settings, "takeProfitPercent", "%"),
        "partialTakeProfit": _partial_take_profit_text(settings),
        "minTotalScore": _setting_value(settings, "minTotalScore", "점"),
        "priceRange": _price_range_text(settings),
        "minOpeningPriceChangePercent": _setting_value(
            settings,
            "minOpeningPriceChangePercent",
            "%",
        ),
        "minVolumeRatio": _setting_value(settings, "minVolumeRatio", "배"),
        "maxOpeningGapPercent": _setting_value(settings, "maxOpeningGapPercent", "%"),
    }


def _empty_settings_summary() -> dict[str, str]:
    return {
        "text": "-",
        "stopLossPercent": "-",
        "takeProfitPercent": "-",
        "partialTakeProfit": "-",
        "minTotalScore": "-",
        "priceRange": "-",
        "minOpeningPriceChangePercent": "-",
        "minVolumeRatio": "-",
        "maxOpeningGapPercent": "-",
    }


def _setting_value(settings: dict[str, Any], key: str, suffix: str) -> str:
    if key not in settings:
        return "-"
    return f"{_compact_number(settings[key])}{suffix}"


def _price_range_text(settings: dict[str, Any]) -> str:
    if "minPriceUsd" not in settings:
        return "-"
    return f"${_compact_number(settings['minPriceUsd'])}~${_compact_number(settings.get('maxPriceUsd'))}"


def _partial_take_profit_text(settings: dict[str, Any]) -> str:
    if "partialTakeProfitEnabled" not in settings:
        return "-"
    return "사용" if settings["partialTakeProfitEnabled"] else "미사용"


def _compact_number(value: Any) -> str:
    number = _number(value)
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _date_text(value: Any) -> str:
    if all(hasattr(value, field) for field in ("Year", "Month", "Day")):
        return f"{value.Year:04d}-{value.Month:02d}-{value.Day:02d}"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _time_text(value: Any) -> str:
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%H:%M:%S")
        except Exception:
            # .NET/ODBC 시간 객체가 strftime을 흉내 내다 실패하면 필드 조합 방식으로 처리한다.
            pass
    if all(hasattr(value, field) for field in ("Hour", "Minute", "Second")):
        return f"{value.Hour:02d}:{value.Minute:02d}:{value.Second:02d}"
    raw = str(value or "")
    return raw[11:19] if len(raw) >= 19 and raw[10] == " " else raw


def _summary(realized_profit_usd: float) -> dict[str, str]:
    return {"realizedProfitUsd": _signed_usd(realized_profit_usd)}


def _signed_usd(value: float) -> str:
    if value > 0:
        return f"+${value:,.2f}"
    if value < 0:
        return f"-${abs(value):,.2f}"
    return "$0.00"


def _rate_or_dash(value: Any) -> str:
    if value is None:
        return "-"
    return f"{_number(value) * 100:+.2f}%"


def _percent_text_number(value: Any) -> float:
    text = str(value or "").replace("%", "").replace("+", "").strip()
    if text in ("", "-"):
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _usd(value: float) -> str:
    return f"${value:,.2f}"


def _usd_or_dash(value: Any) -> str:
    number = _number(value)
    return "-" if number <= 0 else _usd(number)


def _volume_text(value: Any) -> str:
    volume = _number(value)
    if volume <= 0:
        return "-"
    if volume >= 100_000_000:
        return f"{volume / 100_000_000:.1f}억주"
    if volume >= 10_000:
        return f"{volume / 10_000:.0f}만주"
    return f"{volume:,.0f}주"


def _krw_or_dash(value: Any) -> str:
    number = _number(value)
    return "-" if number <= 0 else f"{number:,.0f}원"


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except TypeError:
        return float(str(value))


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        return bool(int(float(str(value))))
    except ValueError:
        return str(value).strip().lower() in {"true", "yes", "y"}


def _fallback_filter_score(volume_ratio: Any, price_change: Any) -> float:
    volume = max(0.0, _number(volume_ratio))
    change = max(0.0, _number(price_change))
    volume_score = min(volume / 3.0 * 50.0, 50.0)
    change_score = min(change / 8.0 * 50.0, 50.0)
    return volume_score + change_score


def _level_text(level: Any) -> str:
    mapping = {
        "INFO": "정보",
        "WARNING": "주의",
        "WARN": "주의",
        "ERROR": "오류",
    }
    return mapping.get(str(level).upper(), str(level))


def _side_text(value: Any) -> str:
    raw = str(value or "").strip()
    normalized = raw.upper()
    if normalized in {"BUY", "B"} or "매수" in raw:
        return "매수"
    if normalized in {"SELL", "S"} or "매도" in raw:
        return "매도"
    return raw


def _message_text(message: Any) -> str:
    text = str(message)
    if text.startswith("candidate_evaluation_saved "):
        return _candidate_evaluation_saved_text(text)
    if text.startswith("vwap_ma20_skipped_no_data "):
        return _vwap_ma20_skipped_log_text(text)
    if text.startswith("vwap_ma20_evaluated "):
        return _vwap_ma20_evaluated_log_text(text)
    if text.startswith("[PIPELINE] "):
        return _structured_log_text("후보 생성 단계", text, "[PIPELINE] ", _PIPELINE_LOG_LABELS)
    if text.startswith("[FILTER] "):
        return _structured_log_text("필터 제외 현황", text, "[FILTER] ", _FILTER_LOG_LABELS)
    if text.startswith("[PIPELINE_SUMMARY] "):
        return _structured_log_text(
            "후보 생성 요약",
            text,
            "[PIPELINE_SUMMARY] ",
            _PIPELINE_SUMMARY_LOG_LABELS,
        )
    if text.startswith("[SAVE_TARGETS] "):
        return _structured_log_text("후보 저장", text, "[SAVE_TARGETS] ", _SAVE_TARGETS_LOG_LABELS)
    if text.startswith("[SAVE_SCORES] "):
        return _structured_log_text("점수 저장", text, "[SAVE_SCORES] ", _SAVE_SCORES_LOG_LABELS)
    if text.startswith("[MISSING_SNAPSHOT] "):
        return _structured_log_text(
            "시세 스냅샷 누락",
            text,
            "[MISSING_SNAPSHOT] ",
            _MISSING_SNAPSHOT_LOG_LABELS,
        )
    if text.startswith("Screened ") and " targets and selected " in text:
        parts = text.rstrip(".").split()
        if len(parts) >= 6:
            return f"후보 {parts[1]}개를 점검했고, 최종 {parts[5]}개를 선정했습니다."
    if text.startswith("Expanded screening universe to top "):
        parts = text.rstrip(".").split()
        if len(parts) >= 7:
            rank = parts[5]
            count = parts[6].strip("()")
            return f"후보 수집 범위를 상위 {rank}위까지 확대했습니다. ({count}종목)"
    if text.startswith("Filter rejects: "):
        raw = text.removeprefix("Filter rejects: ").rstrip(".")
        if raw == "none":
            return "필터에서 제외된 종목은 없습니다."
        return "필터 제외 사유: " + ", ".join(_reason_count(part) for part in raw.split(", "))
    if text.startswith("Entry blocked: "):
        return "진입 차단: " + _reason_text(text.removeprefix("Entry blocked: ").strip())
    if text.startswith("Entry bypassed: "):
        reason = text.removeprefix("Entry bypassed: ").strip().split()[0]
        return "모의투자 예외 진행: " + _reason_text(reason)
    return _replace_known_tokens(text)


def _candidate_evaluation_saved_text(text: str) -> str:
    pairs = dict(_key_value_pairs(text.removeprefix("candidate_evaluation_saved ")))
    return (
        "후보평가 저장: "
        f"종목={pairs.get('symbol', '-')} "
        f"최종점수={pairs.get('final_score', '-')} "
        f"매수허용={_yes_no_text(pairs.get('buy_allowed'))} "
        f"주문제출={_yes_no_text(pairs.get('order_submitted'))} "
        f"매수판정={_candidate_reason_text(pairs.get('buy_block_reason'))} "
        f"하드필터탈락={pairs.get('hard_filter_failed_count', '-')} "
        f"소프트조건탈락={pairs.get('soft_condition_failed_count', '-')} "
        f"VWAP/MA20상태={_candidate_status_text(pairs.get('vwap_ma20_status'))}"
    )


def _vwap_ma20_skipped_log_text(text: str) -> str:
    pairs = dict(_key_value_pairs(text.removeprefix("vwap_ma20_skipped_no_data ")))
    return (
        "VWAP/MA20 데이터 부족: "
        f"종목={pairs.get('symbol', '-')} "
        f"현재가={pairs.get('current_price', '-')} "
        f"조건유형={_candidate_condition_type_text(pairs.get('condition_type'))} "
        f"조건모드={_candidate_condition_mode_text(pairs.get('condition_mode'))} "
        f"VWAP데이터={_yes_no_text(pairs.get('has_vwap'))} "
        f"장중MA20데이터={_yes_no_text(pairs.get('has_intraday_ma20'))} "
        f"사유={_candidate_reason_text(pairs.get('reason'))}"
    )


def _vwap_ma20_evaluated_log_text(text: str) -> str:
    pairs = dict(_key_value_pairs(text.removeprefix("vwap_ma20_evaluated ")))
    return (
        "VWAP/MA20 평가: "
        f"종목={pairs.get('symbol', '-')} "
        f"현재가={pairs.get('current_price', '-')} "
        f"VWAP={pairs.get('vwap_usd', '-')} "
        f"장중MA20={pairs.get('intraday_ma20_usd', '-')} "
        f"조건유형={_candidate_condition_type_text(pairs.get('condition_type'))} "
        f"조건모드={_candidate_condition_mode_text(pairs.get('condition_mode'))} "
        f"VWAP통과={_yes_no_text(pairs.get('vwap_pass'))} "
        f"MA20통과={_yes_no_text(pairs.get('ma20_pass'))} "
        f"종합통과={_yes_no_text(pairs.get('vwap_ma20_pass'))}"
    )


def _candidate_reason_text(reason: str | None) -> str:
    raw = str(reason or "").strip()
    if not raw:
        return "-"
    return _CANDIDATE_REASON_TEXT.get(raw, _reason_text(raw))


def _candidate_status_text(status: str | None) -> str:
    raw = str(status or "").strip()
    if not raw:
        return "-"
    return _CANDIDATE_STATUS_TEXT.get(raw, raw)


def _candidate_condition_mode_text(mode: str | None) -> str:
    raw = str(mode or "").strip()
    if not raw:
        return "-"
    return _CANDIDATE_CONDITION_MODE_TEXT.get(raw, raw)


def _candidate_condition_type_text(condition_type: str | None) -> str:
    raw = str(condition_type or "").strip()
    if not raw:
        return "-"
    return _CANDIDATE_CONDITION_TYPE_TEXT.get(raw, raw)


def _yes_no_text(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw == "true":
        return "예"
    if raw == "false":
        return "아니오"
    if raw in {"none", "null", ""}:
        return "-"
    return str(value)


def _structured_log_text(
    title: str,
    text: str,
    prefix: str,
    labels: dict[str, str],
) -> str:
    parts = [
        _display_log_pair(key, value, labels)
        for key, value in _key_value_pairs(text.removeprefix(prefix))
    ]
    return f"{title}: " + (", ".join(parts) if parts else text)


def _key_value_pairs(text: str) -> list[tuple[str, str]]:
    pairs = []
    for chunk in text.split():
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        pairs.append((key.strip(), value.strip()))
    return pairs


def _display_log_pair(key: str, value: str, labels: dict[str, str]) -> str:
    label = labels.get(key, key)
    if key == "reason":
        return f"{label} {_snapshot_reason_text(value)}"
    if key == "candidate_eval_stopped_reason":
        return f"{label} {_candidate_eval_stopped_reason_text(value)}"
    if key in _COUNT_LOG_KEYS:
        return f"{label} {value}건"
    if key in {"candidate_eval_elapsed_ms", "duration_ms"}:
        return f"{label} {value}ms"
    return f"{label} {value}"


def _candidate_eval_stopped_reason_text(reason: str) -> str:
    return {
        "target_reached": "목표 후보 수 도달",
        "max_evaluation_candidates_reached": "최대 평가 후보 수 도달",
        "timeout_budget_exceeded": "평가 시간 예산 초과",
        "no_more_candidates": "평가할 후보 없음",
    }.get(reason, reason)


def _snapshot_reason_text(reason: str) -> str:
    if reason in _SNAPSHOT_REASON_TEXT:
        return _SNAPSHOT_REASON_TEXT[reason]
    if reason.startswith("quote_http_error_"):
        return f"호가 조회 HTTP 오류 {reason.removeprefix('quote_http_error_')}"
    if reason.startswith("daily_prices_http_error_"):
        return f"일봉 조회 HTTP 오류 {reason.removeprefix('daily_prices_http_error_')}"
    if reason.startswith("quote_"):
        suffix = reason.removeprefix("quote_")
        return "호가 조회 실패: " + _SNAPSHOT_REASON_TEXT.get(suffix, suffix)
    if reason.startswith("daily_prices_"):
        suffix = reason.removeprefix("daily_prices_")
        return "일봉 조회 실패: " + _SNAPSHOT_REASON_TEXT.get(suffix, suffix)
    return _SNAPSHOT_REASON_TEXT.get(reason, _reason_text(reason))


def _reason_count(part: str) -> str:
    if "=" not in part:
        return _reason_text(part)
    reason, count = part.split("=", 1)
    return f"{_reason_text(reason)} {count}건"


def _replace_known_tokens(text: str) -> str:
    for token, label in _REASON_TEXT.items():
        text = text.replace(token, label)
    return text


def _reason_text(reason: str) -> str:
    raw = reason.strip()
    if "+" in raw:
        return " + ".join(_reason_text(part) for part in raw.split("+") if part.strip())
    return _REASON_TEXT.get(raw, raw)


def _mode_text(mode: Any) -> str:
    mapping = {
        "refresh": "15분마다 새 후보 수집",
        "fixed": "장초반 후보 고정 감시",
        "hybrid": "장초반+15분 새로운 종목 수집",
    }
    return mapping.get(str(mode or "").strip().lower(), str(mode or "-"))


_REASON_TEXT = {
    "ACCOUNT_EXPOSURE_LIMIT": "계좌 투자비중 초과",
    "API_ERROR": "API 오류",
    "CANDIDATE_SNAPSHOT_EMPTY": "후보 스냅샷 없음",
    "CANDIDATE_SNAPSHOT_SAVE_FAILED": "후보 스냅샷 저장 실패",
    "CANDIDATE_SNAPSHOT_SAVED": "후보 스냅샷 저장 완료",
    "DAILY_ACCOUNT_LOSS": "일일 손실 제한 도달",
    "EOD": "장마감 매도",
    "FX_VOLATILITY": "환율 변동성 초과",
    "INSUFFICIENT_SAMPLE_FOR_STRATEGY_DECISION": "전략 판단 표본 부족",
    "INVALID_ACCOUNT_EQUITY": "계좌 평가금액 확인 불가",
    "INVALID_ORDER_VALUE": "주문 금액 오류",
    "CHART_POSITIVE": "차트 조건 양호",
    "HYBRID_CANDIDATE": "장초반+15분 후보",
    "INTRADAY_RECHECK": "15분 재평가",
    "LOW_OPENING_CHANGE": "장초반 상승률 부족",
    "LOW_OPENING_VOLUME": "장초반 거래량 부족",
    "MARKET_BELOW_MA20": "나스닥 20일선 하회",
    "MANUAL_SELL": "수동 매도",
    "MANUAL_SELL_ALL": "전량 수동 매도",
    "MISSING_SNAPSHOT": "시세 스냅샷 없음",
    "NEWS_POSITIVE": "뉴스 긍정",
    "OPENING_BREAKOUT": "장초반 돌파",
    "OPENING_FIXED": "장초반 고정 후보",
    "OPENING_GAP": "시가 갭 과다",
    "PARTIAL_TAKE_PROFIT": "분할 익절",
    "OPEN_POSITION_LIMIT": "최대 보유 종목 수 초과",
    "PENNY_STOCK": "가격 하한 미달",
    "POSITION_EXPOSURE_LIMIT": "종목별 투자비중 초과",
    "PRICE_CAP": "가격 상한 초과",
    "PYRAMIDING": "불타기 추가매수",
    "RANKING_FETCH_FAILED": "랭킹 조회 실패",
    "RANKED_LIST": "랭킹 후보",
    "REFRESH_CANDIDATE": "15분 신규 후보",
    "RETRY": "재시도",
    "ORDER_FAILED": "주문 실패",
    "QUOTE_LOOKUP_FAILED": "호가 조회 실패",
    "STRICT_FILTER_NO_CANDIDATES": "엄격 필터 후보 부족",
    "STOP_LOSS": "손절",
    "TAKE_PROFIT": "익절",
    "TRAILING_STOP": "트레일링 스탑",
}

_CANDIDATE_REASON_TEXT = {
    **_REASON_TEXT,
    "BUY_ALLOWED": "매수 허용",
    "BREAKOUT_NOT_TRIGGERED": "돌파 미발생",
    "BREAKOUT_CLOSE_FAILED": "5분봉 종가 돌파 미충족",
    "FINAL_SCORE_BELOW_THRESHOLD": "최종 점수 기준 미달",
    "ORDER_NOT_SUBMITTED": "주문 미제출",
    "OVERHEAT_LIMIT_EXCEEDED": "과열 제한 초과",
    "VOLUME_INCREASE_FAILED": "5분 거래량 증가 미충족",
    "VWAP_MA20_FAILED": "VWAP/MA20 조건 미충족",
    "VWAP_MA20_DATA_MISSING": "VWAP/MA20 데이터 없음",
    "PULLBACK_REBREAK_FAILED": "눌림 후 재돌파 미충족",
}

_CANDIDATE_STATUS_TEXT = {
    "DISABLED": "비활성화",
    "SKIPPED_NO_DATA": "데이터 없음으로 건너뜀",
    "PASS": "통과",
    "FAIL": "실패",
}

_CANDIDATE_CONDITION_MODE_TEXT = {
    "HARD_FILTER": "하드필터",
    "SOFT_SCORE": "소프트점수",
    "OFF": "꺼짐",
}

_CANDIDATE_CONDITION_TYPE_TEXT = {
    "AND": "VWAP와 MA20 모두",
    "OR": "VWAP 또는 MA20",
    "VWAP_ONLY": "VWAP만",
    "MA20_ONLY": "MA20만",
    "OFF": "꺼짐",
}

_PIPELINE_LOG_LABELS = {
    "requested_gainer_limit": "상승률 요청",
    "received_gainer_count": "상승률 수신",
    "requested_turnover_limit": "거래량 요청",
    "received_turnover_count": "거래량 수신",
    "requested_trade_value_limit": "거래대금 요청",
    "received_trade_value_count": "거래대금 수신",
    "gainers_count": "상승률 랭킹",
    "volume_count": "거래량 랭킹",
    "trade_value_count": "거래대금 랭킹",
    "intersection_count": "교집합",
    "ranking_union_count": "합집합",
    "ranked_evaluation_limit": "랭킹 평가 한도",
    "evaluated_candidate_count": "평가한 후보",
    "quote_requested_count": "현재가 요청",
    "daily_requested_count": "일봉 요청",
    "snapshot_success_count": "시세 조회 성공",
    "snapshot_fail_count": "시세 조회 실패",
    "risk_pass_count": "필터 통과 후보",
    "filtered_candidate_count": "필터 통과 후보",
    "scoring_pass_count": "점수 통과 후보",
    "final_selected_count": "최종 선정 후보",
    "selected_candidate_count": "최종 선정 후보",
    "candidate_eval_elapsed_ms": "후보 평가 시간",
    "candidate_eval_stopped_reason": "후보 평가 중단 사유",
}

_FILTER_LOG_LABELS = {
    "removed_by_price": "가격 조건 제외",
    "removed_by_gap": "갭 조건 제외",
    "removed_by_volume_ratio": "거래량 비율 제외",
    "removed_by_opening_change": "장초반 상승률 제외",
    "removed_by_score": "점수 기준 제외",
    "final_count": "최종 후보",
}

_PIPELINE_SUMMARY_LOG_LABELS = {
    "requested_gainer_limit": "상승률 요청",
    "received_gainer_count": "상승률 수신",
    "requested_turnover_limit": "거래량 요청",
    "received_turnover_count": "거래량 수신",
    "requested_trade_value_limit": "거래대금 요청",
    "received_trade_value_count": "거래대금 수신",
    "gainers": "상승률 랭킹",
    "volume": "거래량 랭킹",
    "trade_value": "거래대금 랭킹",
    "intersection": "교집합",
    "ranking_union": "합집합",
    "ranked_evaluation_limit": "랭킹 평가 한도",
    "evaluated_candidate_count": "평가한 후보",
    "quote_requested_count": "현재가 요청",
    "daily_requested_count": "일봉 요청",
    "snapshot_success": "시세 조회 성공",
    "snapshot_fail": "시세 조회 실패",
    "risk_pass": "필터 통과 후보",
    "filtered_candidate_count": "필터 통과 후보",
    "score_pass": "점수 통과 후보",
    "selected_candidate_count": "최종 선정 후보",
    "saved": "DB 저장 후보",
    "candidate_eval_elapsed_ms": "후보 평가 시간",
    "candidate_eval_stopped_reason": "후보 평가 중단 사유",
    "duration_ms": "소요 시간",
}

_SAVE_TARGETS_LOG_LABELS = {
    "candidate_count": "후보 수",
    "trade_date": "거래일",
}

_SAVE_SCORES_LOG_LABELS = {
    "score_count": "점수 수",
    "trade_date": "거래일",
}

_MISSING_SNAPSHOT_LOG_LABELS = {
    "ticker": "종목",
    "reason": "사유",
}

_COUNT_LOG_KEYS = {
    "candidate_count",
    "final_count",
    "final_selected_count",
    "filtered_candidate_count",
    "gainers",
    "gainers_count",
    "intersection",
    "intersection_count",
    "daily_requested_count",
    "evaluated_candidate_count",
    "ranking_union",
    "ranking_union_count",
    "ranked_evaluation_limit",
    "quote_requested_count",
    "received_gainer_count",
    "received_turnover_count",
    "received_trade_value_count",
    "removed_by_gap",
    "removed_by_opening_change",
    "removed_by_price",
    "removed_by_score",
    "removed_by_volume_ratio",
    "risk_pass",
    "risk_pass_count",
    "saved",
    "score_count",
    "score_pass",
    "scoring_pass_count",
    "selected_candidate_count",
    "snapshot_fail",
    "snapshot_fail_count",
    "snapshot_success",
    "snapshot_success_count",
    "volume",
    "volume_count",
    "requested_gainer_limit",
    "requested_turnover_limit",
    "requested_trade_value_limit",
    "trade_value",
    "trade_value_count",
}

_SNAPSHOT_REASON_TEXT = {
    "empty": "응답 없음",
    "insufficient": "데이터 부족",
    "missing_field": "필수 숫자 필드 누락",
    "timeout": "시간 초과",
    "daily_prices_empty": "일봉 데이터 없음",
    "daily_prices_insufficient": "일봉 데이터 부족",
}
