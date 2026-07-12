from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from trading_bot.performance_digest_buckets import is_sell, num


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
    ambiguous_exit = [
        row for row in sells
        if _truthy(row.get("match_ambiguous"))
        or str(row.get("exit_reason") or "").upper() == "AMBIGUOUS"
    ]
    assignable = [row for row in sells if row not in ambiguous_exit]
    stop = [
        row for row in assignable
        if str(row.get("exit_reason") or "").upper() == "STOP_LOSS"
    ]
    stop_profit = sum(num(row.get("normalized_profit_usd")) for row in stop)
    return {
        "basis": basis,
        "sell_count": len(sells), "total_profit_usd": sum(profits),
        "win_rate": len(wins) / len(sells) if sells else 0.0,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (math.inf if gross_profit else 0.0),
        "gross_profit": gross_profit, "gross_loss": gross_loss,
        "max_win": max(wins, default=0.0), "max_loss": min(losses, default=0.0),
        "stop_loss_count": len(stop), "stop_loss_total_profit_usd": stop_profit,
        "stop_loss_average_profit_usd": stop_profit / len(stop) if stop else 0.0,
        "stop_loss_share_of_sell_count": len(stop) / len(sells) if sells else 0.0,
        "stop_loss_share_of_gross_loss": abs(sum(
            min(0.0, num(row.get("normalized_profit_usd"))) for row in stop
        )) / gross_loss if gross_loss else 0.0,
        "ambiguous_exit_count": len(ambiguous_exit),
        "other_exit_reasons": sorted({
            str(row.get("exit_reason") or "UNKNOWN").upper()
            for row in assignable
            if str(row.get("exit_reason") or "").upper() != "STOP_LOSS"
        }),
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
