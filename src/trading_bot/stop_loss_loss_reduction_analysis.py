from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any

STOP_LOSS_EXIT_REASON = "STOP_LOSS"
MIN_COMPLETED_SAMPLE_SIZE = 30
PROFIT_PROTECTION_REVIEW_THRESHOLD = 0.02
EARLY_WEAKNESS_REVIEW_THRESHOLD = 0.0
WIDE_SPREAD_REVIEW_THRESHOLD = 0.01
OPENING_GAP_REVIEW_THRESHOLD = 0.03
ACTION_BOUNDARY = (
    "analysis_only: this payload is evidence for human review and must not change "
    "trading, risk, order, scheduler, DB, or API behavior by itself"
)
EVIDENCE_CHECKLIST = ("Confirm STOP_LOSS rows are completed sells.", "Review snapshots and source/reason/version buckets.", "Treat outputs as analysis-only until separate approval exists.")


@dataclass(frozen=True)
class StopLossLossReductionRow:
    trade_date: str
    ticker: str
    final_exit_reason: str
    final_profit_rate: float | None
    snapshots: Mapping[int, float] | None = None
    entry_reason: str = ""
    candidate_source: str = ""
    ranking_selection_mode: str = ""
    strategy_version: str = ""
    opening_gap: float | None = None
    bid_ask_spread_rate: float | None = None

    def snapshot_profits(self) -> dict[int, float]:
        return dict(self.snapshots or {})


def stop_loss_row_from_mapping(row: Mapping[str, Any]) -> StopLossLossReductionRow:
    return StopLossLossReductionRow(
        trade_date=str(_first_present(row, "trade_date", "tradeDate") or ""),
        ticker=str(_first_present(row, "ticker", "symbol") or ""),
        final_exit_reason=str(_first_present(row, "final_exit_reason", "finalExitReason", "exit_reason") or ""),
        final_profit_rate=_rate(_first_present(row, "final_profit_rate", "finalProfitRate", "profit_rate")),
        snapshots=_snapshots(row),
        entry_reason=str(_first_present(row, "entry_reason", "entryReason") or ""),
        candidate_source=str(_first_present(row, "candidate_source", "candidateSource") or ""),
        ranking_selection_mode=str(_first_present(row, "ranking_selection_mode", "rankingSelectionMode") or ""),
        strategy_version=str(_first_present(row, "strategy_version", "strategyVersion") or ""),
        opening_gap=_rate(_first_present(row, "opening_gap", "openingGap")),
        bid_ask_spread_rate=_rate(_first_present(row, "bid_ask_spread_rate", "bidAskSpreadRate")),
    )


def analyze_stop_loss_loss_reduction(
    rows: Iterable[StopLossLossReductionRow | Mapping[str, Any]],
    *,
    generated_at: datetime | None = None,
    warnings: Iterable[str] = (),
) -> dict[str, Any]:
    row_list = [_coerce_row(row) for row in rows]
    completed = [row for row in row_list if row.final_profit_rate is not None]
    stop_loss_rows = [row for row in completed if _normalized_reason(row.final_exit_reason) == STOP_LOSS_EXIT_REASON]
    details = [_detail(row) for row in stop_loss_rows]
    output_warnings = list(warnings)
    if len(completed) < MIN_COMPLETED_SAMPLE_SIZE:
        output_warnings.append(
            f"completed sample is below {MIN_COMPLETED_SAMPLE_SIZE}; use as review evidence only"
        )
    if not stop_loss_rows:
        output_warnings.append("no STOP_LOSS rows found")
    return {
        "generatedAt": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "actionBoundary": ACTION_BOUNDARY,
        "dataScope": _data_scope(row_list, completed, stop_loss_rows),
        "baseline": _baseline(completed, stop_loss_rows),
        "opportunitySignals": _opportunity_signals(details),
        "groups": {
            "byEntryReason": _group(details, "entryReason"),
            "byCandidateSource": _group(details, "candidateSource"),
            "byRankingSelectionMode": _group(details, "rankingSelectionMode"),
            "byStrategyVersion": _group(details, "strategyVersion"),
            "byEarlyPath": _group(details, "earlyPathBucket"),
            "byPrimaryReviewSignal": _group(details, "primaryReviewSignal"),
        },
        "details": details,
        "evidenceChecklist": list(EVIDENCE_CHECKLIST),
        "warnings": output_warnings,
    }


def _coerce_row(row: StopLossLossReductionRow | Mapping[str, Any]) -> StopLossLossReductionRow:
    return row if isinstance(row, StopLossLossReductionRow) else stop_loss_row_from_mapping(row)


def _detail(row: StopLossLossReductionRow) -> dict[str, Any]:
    snapshots = row.snapshot_profits()
    values = list(snapshots.values())
    max_snapshot = max(values) if values else None
    min_snapshot = min(values) if values else None
    early_values = [snapshots[minute] for minute in (5, 10) if minute in snapshots]
    signals = _review_signals(row, max_snapshot, early_values)
    return {
        "tradeDate": row.trade_date,
        "ticker": row.ticker,
        "entryReason": _bucket(row.entry_reason),
        "candidateSource": _bucket(row.candidate_source),
        "rankingSelectionMode": _bucket(row.ranking_selection_mode),
        "strategyVersion": _bucket(row.strategy_version),
        "finalExitReason": _normalized_reason(row.final_exit_reason),
        "finalProfitRate": row.final_profit_rate,
        "stopLossLossRate": abs(row.final_profit_rate or 0.0),
        "snapshotProfits": {str(key): value for key, value in sorted(snapshots.items())},
        "maxSnapshotProfitRate": max_snapshot,
        "minSnapshotProfitRate": min_snapshot,
        "earlyPathBucket": _early_path_bucket(early_values),
        "openingGap": row.opening_gap,
        "bidAskSpreadRate": row.bid_ask_spread_rate,
        "reviewSignals": signals,
        "primaryReviewSignal": signals[0] if signals else "needs_more_context",
    }


def _review_signals(row: StopLossLossReductionRow, max_snapshot: float | None, early_values: list[float]) -> list[str]:
    signals: list[str] = []
    if max_snapshot is not None and max_snapshot >= PROFIT_PROTECTION_REVIEW_THRESHOLD:
        signals.append("profit_giveback_review")
    if any(value < EARLY_WEAKNESS_REVIEW_THRESHOLD for value in early_values):
        signals.append("early_weakness_review")
    if row.bid_ask_spread_rate is not None and row.bid_ask_spread_rate >= WIDE_SPREAD_REVIEW_THRESHOLD:
        signals.append("liquidity_spread_review")
    if row.opening_gap is not None and row.opening_gap >= OPENING_GAP_REVIEW_THRESHOLD:
        signals.append("opening_gap_review")
    return signals


def _opportunity_signals(details: list[dict[str, Any]]) -> dict[str, Any]:
    by_signal: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "totalStopLossLossRate": 0.0}
    )
    for detail in details:
        for signal in detail["reviewSignals"] or ["needs_more_context"]:
            stats = by_signal[signal]
            stats["count"] += 1
            stats["totalStopLossLossRate"] += detail["stopLossLossRate"]
    return {
        signal: {
            "count": stats["count"],
            "totalStopLossLossRate": _round(stats["totalStopLossLossRate"]),
        }
        for signal, stats in sorted(
            by_signal.items(),
            key=lambda item: (-item[1]["totalStopLossLossRate"], item[0]),
        )
    }


def _group(details: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for detail in details:
        groups[_bucket(detail.get(key))].append(detail)
    return {
        name: _stats(items)
        for name, items in sorted(
            groups.items(),
            key=lambda item: (-sum(detail["stopLossLossRate"] for detail in item[1]), item[0]),
        )
    }


def _stats(details: list[dict[str, Any]]) -> dict[str, Any]:
    losses = [detail["stopLossLossRate"] for detail in details]
    return {
        "stopLossCount": len(details),
        "totalStopLossLossRate": _round(sum(losses)),
        "avgStopLossLossRate": _round(sum(losses) / len(losses)) if losses else 0.0,
        "medianStopLossLossRate": _round(median(losses)) if losses else 0.0,
        "profitGivebackReviewCount": _signal_count(details, "profit_giveback_review"),
        "earlyWeaknessReviewCount": _signal_count(details, "early_weakness_review"),
        "liquiditySpreadReviewCount": _signal_count(details, "liquidity_spread_review"),
        "openingGapReviewCount": _signal_count(details, "opening_gap_review"),
        "tickers": sorted({str(detail["ticker"]) for detail in details if detail.get("ticker")}),
    }


def _baseline(completed: list[StopLossLossReductionRow], stop_loss_rows: list[StopLossLossReductionRow]) -> dict[str, Any]:
    completed_losses = [abs(row.final_profit_rate) for row in completed if row.final_profit_rate is not None and row.final_profit_rate < 0]
    stop_losses = [abs(row.final_profit_rate or 0.0) for row in stop_loss_rows]
    completed_loss_sum = sum(completed_losses)
    stop_loss_sum = sum(stop_losses)
    return {
        "completedCount": len(completed),
        "stopLossCount": len(stop_loss_rows),
        "stopLossRate": _round(len(stop_loss_rows) / len(completed)) if completed else 0.0,
        "totalCompletedLossRate": _round(completed_loss_sum),
        "totalStopLossLossRate": _round(stop_loss_sum),
        "stopLossShareOfLossRate": _round(stop_loss_sum / completed_loss_sum) if completed_loss_sum else 0.0,
        "avgStopLossLossRate": _round(stop_loss_sum / len(stop_losses)) if stop_losses else 0.0,
    }


def _data_scope(rows: list[StopLossLossReductionRow], completed: list[StopLossLossReductionRow], stop_loss_rows: list[StopLossLossReductionRow]) -> dict[str, Any]:
    dates = sorted({row.trade_date for row in rows if row.trade_date})
    tickers = sorted({row.ticker for row in rows if row.ticker})
    return {
        "rowCount": len(rows),
        "completedCount": len(completed),
        "stopLossCount": len(stop_loss_rows),
        "tickerCount": len(tickers),
        "dateRange": {"from": dates[0] if dates else None, "to": dates[-1] if dates else None},
    }


def _snapshots(row: Mapping[str, Any]) -> dict[int, float]:
    snapshots: dict[int, float] = {}
    raw = row.get("snapshots") or row.get("snapshotProfits") or {}
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            _set_snapshot(snapshots, key, value)
    for minute in (5, 10, 15, 20, 30, 60):
        for key in (f"profit_after_{minute}m", f"profitAfter{minute}m", f"profit_rate_{minute}m", f"profitRate{minute}m"):
            if key in row:
                _set_snapshot(snapshots, minute, row.get(key))
    return snapshots


def _set_snapshot(snapshots: dict[int, float], key: Any, value: Any) -> None:
    minute = _minute_key(key)
    rate = _rate(value)
    if minute is not None and rate is not None:
        snapshots[minute] = rate


def _minute_key(value: Any) -> int | None:
    text = str(value).strip().lower()
    for token in ("profit_after_", "profitrate", "profit_rate_", "m"):
        text = text.replace(token, "")
    try:
        return int(text)
    except ValueError:
        return None


def _rate(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return number / 100 if str(value).strip().endswith("%") or abs(number) > 1 else number


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in {"", "-"}:
        return None
    if text.startswith("+"):
        text = text[1:]
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _signal_count(details: list[dict[str, Any]], signal: str) -> int:
    return sum(1 for detail in details if signal in detail.get("reviewSignals", []))


def _early_path_bucket(values: list[float]) -> str:
    if not values:
        return "missing_early_snapshots"
    if any(value < 0 for value in values):
        return "early_negative"
    if any(value > 0 for value in values):
        return "early_positive"
    return "early_flat"


def _normalized_reason(value: str) -> str:
    return str(value or "").strip().upper()


def _first_present(row: Mapping[str, Any], *keys: str) -> Any:
    return next((row.get(key) for key in keys if key in row and row.get(key) not in (None, "")), None)


def _bucket(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else "unknown"


def _round(value: float) -> float:
    return round(float(value), 6)
