from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

from trading_bot.performance_digest_format import (
    format_strategy_review_digest,
    save_strategy_review_digest,
)
from trading_bot.performance_digest_stats import collect_strategy_review_digest_stats

AUTO_TRADING_DATA_DIGEST_MARKER = "[AUTO_TRADING_DATA_DIGEST]"
DEFAULT_DATA_DIGEST_MAX_CHARS = 3500


def build_strategy_review_digest(
    sheet_results: Sequence[object],
    *,
    report_date: date | str,
    date_from: date | str,
    date_to: date | str,
    source_xlsx: Path | str,
    failures: Sequence[tuple[str, str]] | None = None,
    max_chars: int = DEFAULT_DATA_DIGEST_MAX_CHARS,
) -> str:
    stats = collect_strategy_review_digest_stats(sheet_results, failures)
    return format_strategy_review_digest(
        stats,
        marker=AUTO_TRADING_DATA_DIGEST_MARKER,
        report_date=report_date,
        date_from=date_from,
        date_to=date_to,
        source_xlsx=source_xlsx,
        max_chars=max_chars,
        default_max_chars=DEFAULT_DATA_DIGEST_MAX_CHARS,
    )


__all__ = [
    "AUTO_TRADING_DATA_DIGEST_MARKER",
    "DEFAULT_DATA_DIGEST_MAX_CHARS",
    "build_strategy_review_digest",
    "save_strategy_review_digest",
]
