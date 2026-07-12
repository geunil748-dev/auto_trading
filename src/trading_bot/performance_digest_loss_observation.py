from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from trading_bot.performance_digest_buckets import UNKNOWN, is_sell, num

OBSERVED_EXIT_REASONS = (
    "STOP_LOSS", "TRAILING_STOP", "EOD", "TIME_STOP_EXIT",
    "EARLY_NEGATIVE_EXIT", "PROFIT_PROTECTION", "TAKE_PROFIT",
    "PARTIAL_TAKE_PROFIT", "UNKNOWN", "AMBIGUOUS",
)


def collect_loss_observation(
    rows: Sequence[Mapping[str, Any]], *, basis: str
) -> dict[str, Any]:
    sells = [
        row for row in rows
        if is_sell(row.get("normalized_side") or row.get("side"))
        and row.get("normalized_profit_usd") is not None
    ]
    profits = [num(row.get("normalized_profit_usd")) for row in sells]
    wins, losses = [value for value in profits if value > 0], [value for value in profits if value < 0]
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    by_exit = {reason: [] for reason in OBSERVED_EXIT_REASONS}
    for row in sells:
        by_exit[_exit_reason(row)].append(row)
    stop = by_exit["STOP_LOSS"]
    stop_profit = sum(num(row.get("normalized_profit_usd")) for row in stop)
    exit_metrics = {
        reason: {
            "count": len(reason_rows),
            "total_profit_usd": sum(
                num(row.get("normalized_profit_usd")) for row in reason_rows
            ),
        }
        for reason, reason_rows in by_exit.items()
    }
    return {
        "basis": basis,
        "sell_count": len(sells), "total_profit_usd": sum(profits),
        "trusted_sell_count": len(sells),
        "trusted_total_profit_usd": sum(profits),
        "win_rate": len(wins) / len(sells) if sells else 0.0,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (math.inf if gross_profit else 0.0),
        "gross_profit": gross_profit, "gross_loss": gross_loss,
        "gross_profit_usd": gross_profit, "gross_loss_usd": gross_loss,
        "max_win": max(wins, default=0.0), "max_loss": min(losses, default=0.0),
        "max_drawdown": UNKNOWN,
        "stop_loss_count": len(stop), "stop_loss_total_profit_usd": stop_profit,
        "stop_loss_average_profit_usd": stop_profit / len(stop) if stop else 0.0,
        "stop_loss_share_of_sell_count": len(stop) / len(sells) if sells else 0.0,
        "stop_loss_share_of_gross_loss": abs(sum(
            min(0.0, num(row.get("normalized_profit_usd"))) for row in stop
        )) / gross_loss if gross_loss else 0.0,
        "ambiguous_exit_count": len(by_exit["AMBIGUOUS"]),
        "exit_reason_metrics": exit_metrics,
        "other_exit_reasons": [
            reason for reason in OBSERVED_EXIT_REASONS
            if reason not in {"STOP_LOSS", "AMBIGUOUS"} and by_exit[reason]
        ],
    }


def raw_loss_rows(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    ledgers = raw.get("execution_ledger_compact", {})
    sell_rows = ledgers.get("sell_rows", []) if isinstance(ledgers, Mapping) else []
    return [
        {
            "side": "SELL", "normalized_profit_usd": row.get("realized_pnl"),
            "exit_reason": row.get("exit_reason"),
            "match_ambiguous": row.get("match_confidence") in {"LOW", "NONE"},
        }
        for row in sell_rows
        if isinstance(row, Mapping) and row.get("realized_pnl") is not None
    ]


def _truthy(value: object) -> bool:
    return value is True or str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _exit_reason(row: Mapping[str, Any]) -> str:
    if _truthy(row.get("match_ambiguous")):
        return "AMBIGUOUS"
    reason = str(row.get("exit_reason") or "UNKNOWN").strip().upper()
    return reason if reason in OBSERVED_EXIT_REASONS else "UNKNOWN"
