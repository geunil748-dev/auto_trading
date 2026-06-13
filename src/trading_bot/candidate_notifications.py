from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from trading_bot.config import load_notification_settings
from trading_bot.models import DailyScore, DailyTarget
from trading_bot.notifications import send_alert_telegram_message


MAX_CANDIDATE_NOTIFICATION_ROWS = 10


def candidate_list_message(
    trade_date: date,
    targets: Sequence[DailyTarget],
    scores: Sequence[DailyScore],
) -> str:
    score_by_ticker = {item.score.ticker: item for item in scores}
    selected_count = sum(1 for item in scores if item.is_selected)
    lines = [
        "[자동매매]",
        "후보 리스트 확정",
        "",
        f"거래일: {trade_date.isoformat()}",
        f"후보 수: {len(targets)}",
        f"선정 수: {selected_count}",
        "",
        "후보:",
    ]
    if not targets:
        lines.append("금일 후보리스트가 없습니다.")
        return "\n".join(lines)

    for index, target in enumerate(targets[:MAX_CANDIDATE_NOTIFICATION_ROWS], start=1):
        candidate = target.candidate
        score = score_by_ticker.get(candidate.ticker)
        selected = "선정" if score and score.is_selected else "후보"
        total_score = f"{score.score.total_score:.1f}" if score else "-"
        lines.append(
            f"{index}. {candidate.ticker} {candidate.name or '-'} "
            f"({selected}, 점수 {total_score}, 가격 ${candidate.price_usd:.2f})"
        )
    remaining = len(targets) - MAX_CANDIDATE_NOTIFICATION_ROWS
    if remaining > 0:
        lines.append(f"... 외 {remaining}건")
    return "\n".join(lines)


def entry_gate_blocked_message(trade_date: date, reason: str) -> str:
    reason_text = reason or "UNKNOWN"
    return "\n".join(
        [
            "[자동매매]",
            "진입 게이트 차단",
            "",
            f"거래일: {trade_date.isoformat()}",
            f"사유: {reason_text}",
        ]
    )


def send_candidate_list_notification(
    trade_date: date,
    targets: Sequence[DailyTarget],
    scores: Sequence[DailyScore],
) -> bool:
    return send_alert_telegram_message(
        candidate_list_message(trade_date, targets, scores),
        load_notification_settings(),
    )


def send_entry_gate_blocked_notification(trade_date: date, reason: str) -> bool:
    return send_alert_telegram_message(
        entry_gate_blocked_message(trade_date, reason),
        load_notification_settings(),
    )
