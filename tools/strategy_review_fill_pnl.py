from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from decimal import Decimal
from typing import Any

try:
    from tools.strategy_review_fill_normalization_utils import (
        average_decimal,
        candidate_sort_key,
        date_text,
        decimal_value,
        float_value,
        score_bucket,
        text_value,
        ticker_text,
        truthy,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from strategy_review_fill_normalization_utils import (  # type: ignore[no-redef]
        average_decimal, candidate_sort_key, date_text, decimal_value, float_value,
        score_bucket, text_value, ticker_text, truthy,
    )


def candidate_review_rows(
    normalized_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for source in candidate_rows:
        row = deepcopy(dict(source))
        if not (truthy(row.get("buy_allowed")) or truthy(row.get("order_submitted"))):
            continue
        key = (
            date_text(row.get("trade_date", row.get("trading_date"))),
            ticker_text(row.get("ticker", row.get("symbol"))),
        )
        if key not in latest or candidate_sort_key(row) > candidate_sort_key(latest[key]):
            latest[key] = row
    fills_by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in normalized_rows:
        fills_by_key[(date_text(row.get("trade_date")), ticker_text(row.get("ticker")))].append(row)
    result: list[dict[str, Any]] = []
    for key in sorted(latest):
        row = deepcopy(latest[key])
        fills = fills_by_key.get(key, [])
        trusted_buys = _included(fills, "BUY", "excluded_from_trusted_pnl")
        best_buys = _included(fills, "BUY", "excluded_from_best_effort_pnl")
        trusted_sells = _included(fills, "SELL", "excluded_from_trusted_pnl")
        best_sells = _included(fills, "SELL", "excluded_from_best_effort_pnl")
        submitted = truthy(row.get("order_submitted"))
        if not submitted and not trusted_buys:
            trusted_sells = []
        if not submitted and not best_buys:
            best_sells = []
        trusted_profit = _sum_profit(trusted_sells)
        best_profit = _sum_profit(best_sells)
        row.update(
            trade_date=key[0],
            ticker=key[1],
            buy_fill_count=len(trusted_buys),
            sell_count=len(trusted_sells),
            sell_profit_usd=float_value(trusted_profit),
            avg_sell_profit_rate=average_decimal(item.get("profit_rate") for item in trusted_sells),
            trusted_buy_fill_count=len(trusted_buys),
            trusted_sell_count=len(trusted_sells),
            trusted_sell_profit_usd=float_value(trusted_profit),
            best_effort_buy_fill_count=len(best_buys),
            best_effort_sell_count=len(best_sells),
            best_effort_sell_profit_usd=float_value(best_profit),
            exit_reasons=",".join(
                sorted({text_value(item.get("exit_reason")) for item in best_sells if text_value(item.get("exit_reason"))})
            ),
            score_bucket=score_bucket(row.get("final_score")),
        )
        result.append(row)
    return result


def aggregate_fill_pnl(
    normalized_rows: Sequence[Mapping[str, Any]],
    fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in normalized_rows:
        if row.get("side") == "SELL":
            groups[tuple(text_value(row.get(field)) or "UNKNOWN" for field in fields)].append(row)
    result: list[dict[str, Any]] = []
    for key in sorted(groups):
        rows = groups[key]
        trusted = [row for row in rows if not row.get("excluded_from_trusted_pnl")]
        best = [row for row in rows if not row.get("excluded_from_best_effort_pnl")]
        if not trusted and not best:
            continue
        trusted_metrics, best_metrics = _profit_metrics(trusted), _profit_metrics(best)
        output = {field: value for field, value in zip(fields, key)}
        output.update(trusted_metrics)
        output.update({f"trusted_{name}": value for name, value in trusted_metrics.items()})
        output.update({f"best_effort_{name}": value for name, value in best_metrics.items()})
        if fields == ("ticker",):
            output["exit_reasons"] = ",".join(
                sorted({text_value(row.get("exit_reason")) for row in best if text_value(row.get("exit_reason"))})
            )
        result.append(output)
    return result


def aggregate_candidate_pnl(
    candidate_rows: Sequence[Mapping[str, Any]],
    group_name: str,
    group_value: Callable[[Mapping[str, Any]], str],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in candidate_rows:
        groups[(date_text(row.get("trade_date")), group_value(row))].append(row)
    result: list[dict[str, Any]] = []
    for (trade_date_value, label), rows in sorted(groups.items()):
        trusted = _candidate_metrics(rows, "trusted_sell_count", "trusted_sell_profit_usd")
        best = _candidate_metrics(rows, "best_effort_sell_count", "best_effort_sell_profit_usd")
        if trusted["sell_count"] == 0 and best["sell_count"] == 0:
            continue
        output = {"trade_date": trade_date_value, group_name: label, **trusted}
        output.update({f"trusted_{name}": value for name, value in trusted.items()})
        output.update({f"best_effort_{name}": value for name, value in best.items()})
        result.append(output)
    return result


def _included(
    rows: Sequence[Mapping[str, Any]],
    side: str,
    excluded_field: str,
) -> list[Mapping[str, Any]]:
    return [row for row in rows if row.get("side") == side and not row.get(excluded_field)]


def _sum_profit(rows: Sequence[Mapping[str, Any]]) -> Decimal:
    return sum((decimal_value(row.get("normalized_profit_usd")) or Decimal("0") for row in rows), Decimal("0"))


def _profit_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    profits = [decimal_value(row.get("normalized_profit_usd")) for row in rows]
    profits = [value for value in profits if value is not None]
    rates = [decimal_value(row.get("profit_rate")) for row in rows]
    rates = [value for value in rates if value is not None]
    total = sum(profits, Decimal("0"))
    wins, losses = [value for value in profits if value > 0], [value for value in profits if value < 0]
    gross_win, gross_loss = sum(wins, Decimal("0")), abs(sum(losses, Decimal("0")))
    return {
        "sell_count": len(profits),
        "total_profit_usd": float_value(total),
        "avg_profit_usd": float_value(total / len(profits)) if profits else None,
        "win_count": len(wins), "loss_count": len(losses),
        "win_rate": len(wins) / len(profits) if profits else None,
        "avg_win": float_value(gross_win / len(wins)) if wins else None,
        "avg_loss": float_value(-gross_loss / len(losses)) if losses else None,
        "profit_factor": float_value(gross_win / gross_loss) if gross_loss > 0 else None,
        "max_win": float_value(max(wins)) if wins else None,
        "max_loss": float_value(min(losses)) if losses else None,
        "avg_profit_rate": float_value(sum(rates, Decimal("0")) / len(rates)) if rates else None,
    }


def _candidate_metrics(
    rows: Sequence[Mapping[str, Any]],
    count_field: str,
    profit_field: str,
) -> dict[str, Any]:
    active = [row for row in rows if int(row.get(count_field) or 0) > 0]
    sell_count = sum(int(row.get(count_field) or 0) for row in active)
    profits = [decimal_value(row.get(profit_field)) or Decimal("0") for row in active]
    total = sum(profits, Decimal("0"))
    return {
        "sell_count": sell_count,
        "total_profit_usd": float_value(total),
        "avg_profit_usd": float_value(total / sell_count) if sell_count else None,
        "win_rate": sum(1 for value in profits if value > 0) / len(active) if active else None,
    }
