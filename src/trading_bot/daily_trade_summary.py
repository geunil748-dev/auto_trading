from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from trading_bot.models import DailyTradeSummaryReport
from trading_bot.repositories import SqlServerDailyRepository
from trading_bot.trade_summary_export import (
    ENTRY_PROFIT_SAMPLE_MINIMUM,
    EXIT_REASON_ORDER,
    SqlTradeSummaryDataSource,
    TradeSummaryDataSource,
    _is_buy_side,
    _is_sell_side,
    _money,
    _number,
    _percent,
    _safe,
    _text,
    _value,
)
from trading_bot.trading_date import current_trade_date


class DailyTradeSummaryRepository(Protocol):
    def save_daily_trade_summary_report(self, report: DailyTradeSummaryReport) -> None: ...


@dataclass(frozen=True)
class DailyTradeSummaryResult:
    report: DailyTradeSummaryReport
    payload: dict[str, Any]


def generate_daily_trade_summary(
    trade_date: date | None = None,
    mode: str = "mock",
    data_source: TradeSummaryDataSource | None = None,
    repository: DailyTradeSummaryRepository | None = None,
    generated_at: datetime | None = None,
) -> DailyTradeSummaryResult:
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"mock", "real"}:
        raise ValueError("mode must be mock or real")
    target_date = trade_date or current_trade_date()
    source, repo = _default_source_and_repository(data_source, repository)
    generated_time = generated_at or datetime.now().astimezone()
    payload = build_daily_trade_summary_payload(source, target_date, normalized_mode)
    summary_text = build_summary_text(payload, generated_time)
    report = DailyTradeSummaryReport(
        trade_date=target_date,
        mode=normalized_mode,
        strategy_version=_text(payload.get("strategyVersion")),
        settings_snapshot_hash=_text(payload.get("settingsSnapshotHash")),
        summary_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        summary_text=summary_text,
        total_profit_usd=float(payload["totalProfitUsd"]),
        total_profit_rate=float(payload["totalProfitRate"]),
        trade_count=int(payload["tradeCount"]),
        buy_count=int(payload["buyCount"]),
        sell_count=int(payload["sellCount"]),
        win_rate=float(payload["winRate"]),
        stop_loss_count=_exit_count(payload, "STOP_LOSS"),
        take_profit_count=_exit_count(payload, "TAKE_PROFIT"),
        trailing_stop_count=_exit_count(payload, "TRAILING_STOP"),
        eod_count=_exit_count(payload, "EOD"),
        sample_sufficient=bool(payload["sampleSufficient"]),
    )
    repo.save_daily_trade_summary_report(report)
    return DailyTradeSummaryResult(report, payload)


def build_daily_trade_summary_payload(
    data_source: TradeSummaryDataSource,
    trade_date: date,
    mode: str,
) -> dict[str, Any]:
    is_mock = mode == "mock"
    run_summary = data_source.run_summary(trade_date, is_mock)
    fills = data_source.fill_rows(trade_date, is_mock)
    trades = data_source.trade_rows(trade_date, is_mock)
    snapshots = data_source.entry_profit_snapshots(trade_date)
    logs = data_source.log_rows(trade_date)
    enriched_sells = _enriched_sell_fills(fills, trades)
    exit_stats = _group_stats(enriched_sells, key_index="exit_reason")
    strategy_stats = _group_stats(enriched_sells, key_index="strategy_version")
    snapshot_stats = _entry_profit_snapshot_stats(snapshots)
    warnings = []
    if not snapshot_stats["sampleSufficient"]:
        warnings.append("표본 부족: 전략 판단 금지")
    total_profit = sum(item["profitUsd"] for item in enriched_sells)
    cost_basis = sum(
        max(item["fillAmount"] - item["profitUsd"], 0.0) for item in enriched_sells
    )
    total_profit_rate = (
        total_profit / cost_basis * 100 if cost_basis > 0 else _number(_value(run_summary, 3))
    )
    buy_count = sum(1 for row in fills if _is_buy_side(_value(row, 4)))
    sell_count = len(enriched_sells)
    win_rate = _win_rate(item["profitUsd"] for item in enriched_sells)
    return {
        "tradeDate": trade_date.isoformat(),
        "mode": mode,
        "strategyVersion": _strategy_version(run_summary, fills, trades, snapshots),
        "settingsSnapshotHash": _settings_snapshot_hash(run_summary, fills, trades),
        "tradeCount": buy_count + sell_count,
        "buyCount": buy_count,
        "sellCount": sell_count,
        "totalProfitUsd": round(total_profit, 2),
        "totalProfitRate": round(total_profit_rate, 4),
        "winRate": round(win_rate, 4),
        "exitReasonStats": exit_stats,
        "strategyStats": strategy_stats,
        "entryProfitSnapshotStats": snapshot_stats,
        "sampleSufficient": snapshot_stats["sampleSufficient"],
        "warnings": warnings,
        "importantLogs": _important_logs(logs),
    }


def build_summary_text(payload: dict[str, Any], generated_at: datetime) -> str:
    mode_label = "모의투자" if payload["mode"] == "mock" else "실투자"
    lines = [
        f"{payload['tradeDate']} {mode_label} 일일 요약",
        f"생성 시각: {generated_at.isoformat(timespec='seconds')}",
        "",
        f"전략 버전: {payload.get('strategyVersion') or '-'}",
        f"총 손익: {_money(float(payload['totalProfitUsd']))}",
        f"총 수익률: {_percent(float(payload['totalProfitRate']))}",
        f"거래 수: {payload['tradeCount']}",
        f"매수/매도 체결 수: {payload['buyCount']} / {payload['sellCount']}",
        f"승률: {_percent(float(payload['winRate']))}",
        "",
        "청산 사유:",
    ]
    for item in payload["exitReasonStats"]:
        lines.append(f"{item['reason']} {item['count']}건")
    lines.extend(["", "진입 후 수익률:"])
    for warning in payload["warnings"]:
        lines.append(_safe(warning))
    if not payload["warnings"]:
        lines.append("표본 충분")
    if payload["importantLogs"]:
        lines.extend(["", "주요 오류 로그:"])
        lines.extend(_safe(item["message"]) for item in payload["importantLogs"][:10])
    return "\n".join(lines)


def _default_source_and_repository(
    data_source: TradeSummaryDataSource | None,
    repository: DailyTradeSummaryRepository | None,
) -> tuple[TradeSummaryDataSource, DailyTradeSummaryRepository]:
    if data_source is not None and repository is not None:
        return data_source, repository
    from trading_bot.database import pyodbc_connect_factory

    connect = pyodbc_connect_factory()
    return (
        data_source or SqlTradeSummaryDataSource(connect),
        repository or SqlServerDailyRepository(connect),
    )


def _enriched_sell_fills(
    fills: list[tuple[Any, ...]],
    trades: list[tuple[Any, ...]],
) -> list[dict[str, Any]]:
    exit_reasons = _sell_exit_reasons(trades)
    rows: list[dict[str, Any]] = []
    for row in fills:
        if not _is_sell_side(_value(row, 4)):
            continue
        ticker = _text(_value(row, 2)).upper()
        reason = exit_reasons[ticker].popleft() if exit_reasons[ticker] else "UNKNOWN"
        rows.append(
            {
                "ticker": ticker,
                "exit_reason": reason or "UNKNOWN",
                "strategy_version": _text(_value(row, 12)) or "UNKNOWN",
                "profitUsd": _number(_value(row, 8)),
                "profitRate": _number(_value(row, 9)),
                "fillAmount": _number(_value(row, 7)),
            }
        )
    return rows


def _sell_exit_reasons(trades: list[tuple[Any, ...]]) -> dict[str, deque[str]]:
    reasons: dict[str, deque[str]] = defaultdict(deque)
    for row in trades:
        if _is_sell_side(_value(row, 4)):
            reasons[_text(_value(row, 2)).upper()].append(_text(_value(row, 7)))
    return reasons


def _group_stats(rows: list[dict[str, Any]], key_index: str) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, float]] = {}
    for row in rows:
        key = _text(row[key_index]) or "UNKNOWN"
        item = stats.setdefault(key, {"count": 0.0, "profit": 0.0, "rate": 0.0, "wins": 0.0})
        item["count"] += 1
        item["profit"] += float(row["profitUsd"])
        item["rate"] += float(row["profitRate"])
        if float(row["profitUsd"]) > 0:
            item["wins"] += 1
    keys = list(EXIT_REASON_ORDER) if key_index == "exit_reason" else []
    keys.extend(sorted(key for key in stats if key not in keys))
    return [
        {
            "reason" if key_index == "exit_reason" else "strategyVersion": key,
            "count": int(stats.get(key, {}).get("count", 0.0)),
            "totalProfitUsd": round(stats.get(key, {}).get("profit", 0.0), 2),
            "averageProfitRate": round(_average_rate(stats.get(key, {})), 6),
            "winRate": round(_stat_win_rate(stats.get(key, {})), 4),
        }
        for key in keys
    ]


def _entry_profit_snapshot_stats(rows: list[tuple[Any, ...]]) -> dict[str, Any]:
    negative_counts = {
        "5m": _negative_count(rows, 2),
        "10m": _negative_count(rows, 3),
        "15m": _negative_count(rows, 4),
        "20m": _negative_count(rows, 5),
        "30m": _negative_count(rows, 6),
    }
    final_win_rates = {
        "5m": _negative_final_win_rate(rows, 2),
        "10m": _negative_final_win_rate(rows, 3),
        "15m": _negative_final_win_rate(rows, 4),
        "20m": _negative_final_win_rate(rows, 5),
    }
    return {
        "sampleCount": len(rows),
        "sampleSufficient": len(rows) >= ENTRY_PROFIT_SAMPLE_MINIMUM,
        "negativeCounts": negative_counts,
        "negativeFinalWinRates": final_win_rates,
    }


def _important_logs(rows: list[tuple[Any, ...]]) -> list[dict[str, str]]:
    important: list[dict[str, str]] = []
    for row in rows:
        level = _text(_value(row, 1)).upper()
        message = _text(_value(row, 3))
        if level not in {"ERROR", "WARNING", "WARN"} and not _log_keyword(message):
            continue
        important.append(
            {
                "createdAt": _safe(_value(row, 0)),
                "level": _safe(level),
                "module": _safe(_value(row, 2)),
                "message": _safe(message),
            }
        )
    return important[:100]


def _log_keyword(message: str) -> bool:
    upper_message = message.upper()
    return any(
        keyword in upper_message or keyword in message
        for keyword in (
            "ORDER_FAILED",
            "CANDIDATE_SNAPSHOT_SAVE_FAILED",
            "API_FAILED",
            "PREFLIGHT",
            "ERROR",
            "FAILED",
            "주문 실패",
            "후보 저장 실패",
            "API 실패",
        )
    )


def _strategy_version(
    run_summary: tuple[Any, ...] | None,
    fills: list[tuple[Any, ...]],
    trades: list[tuple[Any, ...]],
    snapshots: list[tuple[Any, ...]],
) -> str:
    return _first_text(
        _value(run_summary, 0),
        *(_value(row, 12) for row in fills),
        *(_value(row, 12) for row in trades),
        *(_value(row, 9) for row in snapshots),
    )


def _settings_snapshot_hash(
    run_summary: tuple[Any, ...] | None,
    fills: list[tuple[Any, ...]],
    trades: list[tuple[Any, ...]],
) -> str:
    return _first_text(
        _value(run_summary, 1),
        *(_value(row, 13) for row in fills),
        *(_value(row, 13) for row in trades),
    )


def _first_text(*values: Any) -> str:
    for value in values:
        text = _safe(value)
        if text:
            return text
    return ""


def _exit_count(payload: dict[str, Any], reason: str) -> int:
    for item in payload["exitReasonStats"]:
        if item["reason"] == reason:
            return int(item["count"])
    return 0


def _negative_count(rows: list[tuple[Any, ...]], index: int) -> int:
    return sum(
        1 for row in rows if _value(row, index) is not None and _number(_value(row, index)) < 0
    )


def _negative_final_win_rate(rows: list[tuple[Any, ...]], index: int) -> float:
    final_rates = [
        _number(_value(row, 8))
        for row in rows
        if _value(row, index) is not None
        and _number(_value(row, index)) < 0
        and _value(row, 8) is not None
    ]
    return round(_win_rate(final_rates), 4)


def _win_rate(values: Any) -> float:
    items = [float(item) for item in values]
    if not items:
        return 0.0
    return sum(1 for item in items if item > 0) / len(items) * 100


def _average_rate(item: dict[str, float]) -> float:
    count = item.get("count", 0.0)
    return item.get("rate", 0.0) / count if count else 0.0


def _stat_win_rate(item: dict[str, float]) -> float:
    count = item.get("count", 0.0)
    return item.get("wins", 0.0) / count * 100 if count else 0.0
