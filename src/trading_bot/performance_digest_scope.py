from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from trading_bot.performance_digest_buckets import (
    EXIT_REASON_BUCKETS,
    SCORE_BUCKETS,
    SOURCE_BUCKETS,
    UNKNOWN,
    BucketStats,
    exit_reason_bucket,
    fraction,
    is_buy,
    is_sell,
    num,
    score_bucket,
    source_bucket,
)
from trading_bot.performance_digest_quality import (
    count_consistency_status,
    data_status,
    interpretation,
    limited_notes,
    matched_trade_count,
    realized_exit_count,
    reconciliation_metrics,
    safe_buy_count,
    safe_fill_history_sell_rows,
    unmatched_count,
)


def collect_scope_stats(
    rows_by_name: Mapping[str, list[dict[str, Any]]],
    *,
    missing: Sequence[str],
    errors: Sequence[str],
    failure_notes: Sequence[str],
    fill_sheet_available: bool,
    score_sheet_available: bool,
    source_sheet_available: bool,
) -> dict[str, Any]:
    pnl_by_day_rows = rows_by_name["pnl_by_day"]
    exit_reason_rows = rows_by_name["pnl_by_exit_reason"]
    score_rows = rows_by_name["pnl_by_score_bucket"]
    source_rows = rows_by_name["pnl_by_source"]
    fill_rows = rows_by_name["fill_history"]
    sell_rows = [row for row in fill_rows if is_sell(row.get("side"))]
    buy_rows = [row for row in fill_rows if is_buy(row.get("side"))]
    parseable_fill_rows = len(sell_rows) + len(buy_rows)
    overall = _overall_metrics(pnl_by_day_rows, sell_rows, buy_rows)
    exit_stats = _bucket_stats(
        exit_reason_rows,
        key_name="exit_reason",
        buckets=EXIT_REASON_BUCKETS,
        normalizer=exit_reason_bucket,
    )
    score_stats = _bucket_stats(
        score_rows,
        key_name="score_bucket",
        buckets=SCORE_BUCKETS,
        normalizer=score_bucket,
    )
    source_stats = _bucket_stats(
        source_rows,
        key_name="source",
        buckets=SOURCE_BUCKETS,
        normalizer=source_bucket,
    )
    realized_exit_count_value = realized_exit_count(overall, exit_stats, pnl_by_day_rows, fill_sheet_available)
    matched_trade_count_value = matched_trade_count(
        score_stats,
        source_stats,
        score_rows,
        source_rows,
        score_sheet_available,
        source_sheet_available,
    )
    overall["sell_count"] = realized_exit_count_value
    overall["realized_exit_count"] = realized_exit_count_value
    overall["matched_trade_count"] = matched_trade_count_value
    overall["unmatched_trade_count"] = unmatched_count(realized_exit_count_value, matched_trade_count_value)
    overall["buy_count"] = safe_buy_count(
        buy_rows,
        fill_sheet_available,
        parseable_fill_rows,
        realized_exit_count_value,
    )
    duplicate_count = len(rows_by_name["duplicate_suspects"])
    reconciliation = reconciliation_metrics(
        rows_by_name["summary_reconciliation"],
        overall.get("realized_pnl"),
    )
    fill_history_sell_rows = safe_fill_history_sell_rows(
        sell_rows,
        fill_sheet_available,
        parseable_fill_rows,
        realized_exit_count_value,
    )
    buy_count_status = (
        "missing_or_unparsed" if overall["buy_count"] == UNKNOWN else "computed_from_fill_history"
    )
    count_consistency_status_value = count_consistency_status(
        realized_exit_count_value,
        matched_trade_count_value,
        fill_history_sell_rows,
        overall["buy_count"],
    )
    limited = limited_notes(
        missing,
        errors,
        failure_notes,
        realized_exit_count_value,
        matched_trade_count_value,
        fill_history_sell_rows,
        overall["buy_count"],
        count_consistency_status_value,
    )
    data_status_value = data_status(limited, reconciliation["status"], count_consistency_status_value)
    return {
        "overall": overall,
        "exit_stats": exit_stats,
        "score_stats": score_stats,
        "source_stats": source_stats,
        "duplicate_count": duplicate_count,
        "reconciliation": reconciliation,
        "missing_or_limited": limited,
        "data_status": data_status_value,
        "interpretation": interpretation(
            exit_stats,
            source_stats,
            overall,
            duplicate_count,
            data_status_value,
        ),
        "fill_history_sell_rows": fill_history_sell_rows,
        "buy_count_status": buy_count_status,
        "count_consistency_status": count_consistency_status_value,
    }


def filter_rows_by_date(
    rows: Sequence[Mapping[str, Any]],
    target_date: date | str | None,
) -> list[dict[str, Any]]:
    if target_date is None:
        return []
    expected = _date_key(target_date)
    return [
        dict(row)
        for row in rows
        if _date_key(row.get("trade_date") or row.get("trading_date")) == expected
    ]


def _date_key(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    return text[:10]


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


def _realized_return(sell_rows: Sequence[Mapping[str, Any]], realized_pnl: float) -> float:
    amount = sum(abs(num(row.get("fill_amount"))) for row in sell_rows)
    return realized_pnl / amount if amount else 0.0
