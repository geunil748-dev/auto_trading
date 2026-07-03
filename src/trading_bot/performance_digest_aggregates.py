from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from trading_bot.performance_digest_buckets import BucketStats, fraction, num


def overall_metrics(
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
            "realized_return": realized_return(sell_rows, realized_pnl),
            "win_rate": win_count / sell_count if sell_count else 0.0,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "largest_win": max((num(row.get("max_win")) for row in pnl_by_day_rows), default=0.0),
            "largest_loss": min((num(row.get("max_loss")) for row in pnl_by_day_rows), default=0.0),
        }
    return overall_from_fill_rows(sell_rows, buy_rows)


def overall_from_fill_rows(
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
        "realized_return": realized_return(sell_rows, realized_pnl),
        "win_rate": len(wins) / sell_count if sell_count else 0.0,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else (math.inf if wins else 0.0),
        "largest_win": max(wins, default=0.0),
        "largest_loss": min(losses, default=0.0),
    }


def bucket_stats(
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


def realized_return(sell_rows: Sequence[Mapping[str, Any]], realized_pnl: float) -> float:
    amount = sum(abs(num(row.get("fill_amount"))) for row in sell_rows)
    return realized_pnl / amount if amount else 0.0
