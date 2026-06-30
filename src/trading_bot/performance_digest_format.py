from __future__ import annotations

import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

from trading_bot.performance_digest_buckets import (
    EXIT_REASON_BUCKETS,
    SCORE_BUCKETS,
    SOURCE_BUCKETS,
    BucketStats,
)


def format_strategy_review_digest(
    stats: dict[str, Any],
    *,
    marker: str,
    report_date: date | str,
    date_from: date | str,
    date_to: date | str,
    source_xlsx: Path | str,
    max_chars: int,
    default_max_chars: int,
) -> str:
    overall = stats["overall"]
    reconciliation = stats["reconciliation"]
    interpretation = stats["interpretation"]
    lines = [
        marker,
        f"report_date: {_date_text(report_date)}",
        f"date_range: {_date_text(date_from)}..{_date_text(date_to)}",
        f"source_xlsx: {Path(source_xlsx)}",
        f"data_status: {stats['data_status']}",
        "",
        "overall:",
        f"- buy_count: {overall['buy_count']}",
        f"- sell_count: {overall['sell_count']}",
        f"- realized_pnl: {_money(overall['realized_pnl'])}",
        f"- realized_return: {_pct(overall['realized_return'])}",
        f"- win_rate: {_pct(overall['win_rate'])}",
        f"- avg_win: {_money(overall['avg_win'])}",
        f"- avg_loss: {_money(overall['avg_loss'])}",
        f"- profit_factor: {_ratio(overall['profit_factor'])}",
        f"- largest_win: {_money(overall['largest_win'])}",
        f"- largest_loss: {_money(overall['largest_loss'])}",
        "",
        "pnl_by_exit_reason:",
        *_bucket_lines(stats["exit_stats"], EXIT_REASON_BUCKETS),
        "",
        "pnl_by_score_bucket:",
        *_bucket_lines(stats["score_stats"], SCORE_BUCKETS),
        "",
        "pnl_by_source:",
        *_bucket_lines(stats["source_stats"], SOURCE_BUCKETS),
        "",
        "data_quality:",
        f"- duplicate_suspects_count: {stats['duplicate_count']}",
        f"- summary_reconciliation_status: {reconciliation['status']}",
        f"- fill_history_sell_rows: {stats['fill_history_sell_rows']}",
        f"- daily_summary_realized_pnl: {_money(reconciliation['daily_summary_realized_pnl'])}",
        f"- reconciliation_gap: {_money(reconciliation['reconciliation_gap'])}",
        f"- missing_or_limited_fields: {_join_notes(stats['missing_or_limited'])}",
        "",
        "interpretation:",
        f"- main_loss_driver: {interpretation['main_loss_driver']}",
        f"- main_profit_driver: {interpretation['main_profit_driver']}",
        f"- strategy_change_signal: {interpretation['strategy_change_signal']}",
        f"- recommended_review_focus: {interpretation['recommended_review_focus']}",
    ]
    return _truncate_digest("\n".join(lines), max_chars, default_max_chars)


def save_strategy_review_digest(text: str, strategy_review_path: Path | str) -> Path:
    xlsx_path = Path(strategy_review_path)
    digest_path = xlsx_path.with_name(
        xlsx_path.name.replace("strategy_review_", "strategy_digest_").removesuffix(".xlsx")
        + ".txt"
    )
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    digest_path.write_text(text, encoding="utf-8", newline="\n")
    return digest_path


def _bucket_lines(stats: dict[str, BucketStats], buckets: tuple[str, ...]) -> list[str]:
    return [
        (
            f"- {bucket}: sell_count={stats.get(bucket, BucketStats()).sell_count}, "
            f"pnl={_money(stats.get(bucket, BucketStats()).total_profit_usd)}, "
            f"win_rate={_pct(stats.get(bucket, BucketStats()).win_rate)}"
        )
        for bucket in buckets
    ]


def _date_text(value: date | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _money(value: object) -> str:
    return f"{float(value or 0):.2f}"


def _pct(value: object) -> str:
    return f"{float(value or 0) * 100:.2f}%"


def _ratio(value: object) -> str:
    if isinstance(value, (int, float)) and math.isinf(float(value)):
        return "inf"
    return f"{float(value or 0):.2f}"


def _join_notes(notes: list[str]) -> str:
    return ", ".join(notes) if notes else "none"


def _truncate_digest(text: str, max_chars: int, default_max_chars: int) -> str:
    if max_chars <= 0:
        max_chars = default_max_chars
    if len(text) <= max_chars:
        return text
    suffix = "\n[truncated: max_chars]"
    return text[: max_chars - len(suffix)].rstrip() + suffix
