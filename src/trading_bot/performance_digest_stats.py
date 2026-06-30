from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from trading_bot.performance_digest_buckets import (
    EXIT_REASON_BUCKETS,
    SCORE_BUCKETS,
    SOURCE_BUCKETS,
    BucketStats,
    exit_reason_bucket,
    fraction,
    is_buy,
    is_sell,
    num,
    score_bucket,
    source_bucket,
)

EXPECTED_SHEETS = (
    "fill_history",
    "pnl_by_day",
    "pnl_by_exit_reason",
    "pnl_by_score_bucket",
    "pnl_by_source",
    "duplicate_suspects",
    "summary_reconciliation",
)


def collect_strategy_review_digest_stats(
    sheet_results: Sequence[object],
    failures: Sequence[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    by_name = _sheet_results_by_name(sheet_results)
    missing = [name for name in EXPECTED_SHEETS if name not in by_name]
    errors = [
        f"{name}:{_sheet_error(result)}"
        for name, result in by_name.items()
        if _sheet_error(result)
    ]
    failure_notes = [f"{sheet}:{error}" for sheet, error in failures or ()]
    fill_rows = _rows(by_name, "fill_history")
    sell_rows = [row for row in fill_rows if is_sell(row.get("side"))]
    buy_rows = [row for row in fill_rows if is_buy(row.get("side"))]
    overall = _overall_metrics(_rows(by_name, "pnl_by_day"), sell_rows, buy_rows)
    exit_stats = _bucket_stats(
        _rows(by_name, "pnl_by_exit_reason"),
        key_name="exit_reason",
        buckets=EXIT_REASON_BUCKETS,
        normalizer=exit_reason_bucket,
    )
    score_stats = _bucket_stats(
        _rows(by_name, "pnl_by_score_bucket"),
        key_name="score_bucket",
        buckets=SCORE_BUCKETS,
        normalizer=score_bucket,
    )
    source_stats = _bucket_stats(
        _rows(by_name, "pnl_by_source"),
        key_name="source",
        buckets=SOURCE_BUCKETS,
        normalizer=source_bucket,
    )
    duplicate_count = len(_rows(by_name, "duplicate_suspects"))
    reconciliation = _reconciliation_metrics(_rows(by_name, "summary_reconciliation"))
    limited = _limited_notes(missing, errors, failure_notes, int(overall["sell_count"]))
    return {
        "overall": overall,
        "exit_stats": exit_stats,
        "score_stats": score_stats,
        "source_stats": source_stats,
        "duplicate_count": duplicate_count,
        "reconciliation": reconciliation,
        "missing_or_limited": limited,
        "data_status": _data_status(limited, reconciliation["status"]),
        "interpretation": _interpretation(exit_stats, source_stats, overall, duplicate_count),
        "fill_history_sell_rows": len(sell_rows),
    }


def _sheet_results_by_name(results: Sequence[object]) -> dict[str, object]:
    by_name: dict[str, object] = {}
    for result in results:
        name = _sheet_name(result)
        if name:
            by_name[name] = result
    return by_name


def _sheet_name(result: object) -> str:
    if isinstance(result, Mapping):
        return str(result.get("name") or "")
    return str(getattr(result, "name", "") or "")


def _sheet_error(result: object) -> str:
    if isinstance(result, Mapping):
        return str(result.get("error") or "")
    return str(getattr(result, "error", "") or "")


def _rows(by_name: Mapping[str, object], name: str) -> list[dict[str, Any]]:
    result = by_name.get(name)
    if result is None:
        return []
    rows = result.get("rows", []) if isinstance(result, Mapping) else getattr(result, "rows", [])
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _overall_metrics(
    pnl_by_day_rows: Sequence[Mapping[str, Any]],
    sell_rows: Sequence[Mapping[str, Any]],
    buy_rows: Sequence[Mapping[str, Any]],
) -> dict[str, float | int]:
    if pnl_by_day_rows:
        sell_count = int(sum(num(row.get("sell_count")) for row in pnl_by_day_rows))
        win_count = int(sum(num(row.get("win_count")) for row in pnl_by_day_rows))
        loss_count = int(sum(num(row.get("loss_count")) for row in pnl_by_day_rows))
        realized_pnl = sum(num(row.get("total_profit_usd")) for row in pnl_by_day_rows)
        total_win = sum(num(row.get("avg_win")) * num(row.get("win_count")) for row in pnl_by_day_rows)
        total_loss = sum(num(row.get("avg_loss")) * num(row.get("loss_count")) for row in pnl_by_day_rows)
        avg_win = total_win / win_count if win_count else 0.0
        avg_loss = total_loss / loss_count if loss_count else 0.0
        profit_factor = total_win / abs(total_loss) if total_loss < 0 else (math.inf if total_win else 0.0)
        return {
            "buy_count": len(buy_rows),
            "sell_count": sell_count,
            "realized_pnl": realized_pnl,
            "realized_return": _realized_return(sell_rows, realized_pnl),
            "win_rate": win_count / sell_count if sell_count else 0.0,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "largest_win": max((num(row.get("max_win")) for row in pnl_by_day_rows), default=0.0),
            "largest_loss": min((num(row.get("max_loss")) for row in pnl_by_day_rows), default=0.0),
        }
    return _overall_from_fill_rows(sell_rows, buy_rows)


def _overall_from_fill_rows(
    sell_rows: Sequence[Mapping[str, Any]],
    buy_rows: Sequence[Mapping[str, Any]],
) -> dict[str, float | int]:
    profits = [num(row.get("profit_usd")) for row in sell_rows]
    wins = [value for value in profits if value > 0]
    losses = [value for value in profits if value < 0]
    realized_pnl = sum(profits)
    sell_count = len(profits)
    return {
        "buy_count": len(buy_rows),
        "sell_count": sell_count,
        "realized_pnl": realized_pnl,
        "realized_return": _realized_return(sell_rows, realized_pnl),
        "win_rate": len(wins) / sell_count if sell_count else 0.0,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else (math.inf if wins else 0.0),
        "largest_win": max(wins, default=0.0),
        "largest_loss": min(losses, default=0.0),
    }


def _bucket_stats(
    rows: Sequence[Mapping[str, Any]],
    *,
    key_name: str,
    buckets: Sequence[str],
    normalizer,
) -> dict[str, BucketStats]:
    aggregate = {bucket: {"sell_count": 0, "profit": 0.0, "weighted_win": 0.0} for bucket in buckets}
    for row in rows:
        bucket = normalizer(row.get(key_name))
        item = aggregate.setdefault(bucket, {"sell_count": 0, "profit": 0.0, "weighted_win": 0.0})
        sell_count = int(num(row.get("sell_count")))
        item["sell_count"] += sell_count
        item["profit"] += num(row.get("total_profit_usd"))
        item["weighted_win"] += fraction(row.get("win_rate")) * sell_count
    return {
        bucket: BucketStats(
            sell_count=int(values["sell_count"]),
            total_profit_usd=float(values["profit"]),
            win_rate=float(values["weighted_win"]) / values["sell_count"]
            if values["sell_count"]
            else 0.0,
        )
        for bucket, values in aggregate.items()
    }


def _reconciliation_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | str]:
    if not rows:
        return {"status": "LIMITED", "daily_summary_realized_pnl": 0.0, "reconciliation_gap": 0.0}
    daily_pnl = sum(num(row.get("daily_run_realized_profit_usd")) for row in rows)
    gaps = [abs(num(row.get("fill_vs_daily_run_diff"))) for row in rows]
    gaps += [abs(num(row.get("fill_vs_trade_summary_diff"))) for row in rows]
    max_gap = max(gaps, default=0.0)
    return {
        "status": "OK" if max_gap <= 0.01 else "WARN",
        "daily_summary_realized_pnl": daily_pnl,
        "reconciliation_gap": max_gap,
    }


def _interpretation(
    exit_stats: Mapping[str, BucketStats],
    source_stats: Mapping[str, BucketStats],
    overall: Mapping[str, float | int],
    duplicate_count: int,
) -> dict[str, str]:
    loss_bucket = _largest_negative(exit_stats)
    loss_source = _largest_negative(source_stats)
    sell_count = int(overall.get("sell_count", 0))
    realized_pnl = float(overall.get("realized_pnl", 0.0))
    if sell_count == 0:
        signal = "no_sell_data"
    elif sell_count < 30:
        signal = "sample_below_30"
    elif realized_pnl < 0:
        signal = "negative_expectancy_review_needed"
    else:
        signal = "monitor_without_rule_change"
    focus = []
    if loss_bucket != "none":
        focus.append(f"exit_reason={loss_bucket}")
    if loss_source != "none":
        focus.append(f"source={loss_source}")
    if duplicate_count:
        focus.append("duplicate_suspects")
    return {
        "main_loss_driver": loss_bucket,
        "main_profit_driver": _largest_positive(exit_stats),
        "strategy_change_signal": signal,
        "recommended_review_focus": ", ".join(focus) if focus else "collect_more_data",
    }


def _limited_notes(missing: Sequence[str], errors: Sequence[str], failures: Sequence[str], sell_count: int) -> list[str]:
    notes = [f"missing_sheet:{name}" for name in missing]
    notes.extend(f"sheet_error:{item}" for item in errors)
    notes.extend(f"export_failure:{item}" for item in failures)
    if sell_count == 0:
        notes.append("no_sell_rows")
    if sell_count < 30:
        notes.append("sell_sample_below_30")
    return notes


def _data_status(notes: Sequence[str], reconciliation_status: object) -> str:
    if any(note.startswith("sheet_error:") or note.startswith("export_failure:") for note in notes):
        return "WARN"
    if reconciliation_status == "WARN":
        return "WARN"
    return "LIMITED" if notes else "OK"


def _largest_negative(stats: Mapping[str, BucketStats]) -> str:
    negatives = [(name, item.total_profit_usd) for name, item in stats.items() if item.total_profit_usd < 0]
    return min(negatives, key=lambda item: item[1])[0] if negatives else "none"


def _largest_positive(stats: Mapping[str, BucketStats]) -> str:
    positives = [(name, item.total_profit_usd) for name, item in stats.items() if item.total_profit_usd > 0]
    return max(positives, key=lambda item: item[1])[0] if positives else "none"


def _realized_return(sell_rows: Sequence[Mapping[str, Any]], realized_pnl: float) -> float:
    amount = sum(abs(num(row.get("fill_amount"))) for row in sell_rows)
    return realized_pnl / amount if amount else 0.0
