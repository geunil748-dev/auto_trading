from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from trading_bot.config import load_notification_settings
from trading_bot.models import DailyScore, DailyTarget, MarketContext
from trading_bot.notifications import send_alert_telegram_message


MAX_CANDIDATE_NOTIFICATION_ROWS = 10


def candidate_list_message(
    trade_date: date,
    targets: Sequence[DailyTarget],
    scores: Sequence[DailyScore],
    market_context: MarketContext | None = None,
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
    ]
    lines.extend(_market_context_lines(market_context))
    lines.extend(["", "후보:"])
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


def send_candidate_list_notification(
    trade_date: date,
    targets: Sequence[DailyTarget],
    scores: Sequence[DailyScore],
    market_context: MarketContext | None = None,
) -> bool:
    return send_alert_telegram_message(
        candidate_list_message(trade_date, targets, scores, market_context),
        load_notification_settings(),
    )


def _market_context_lines(market_context: MarketContext | None) -> list[str]:
    if market_context is None:
        return []
    source = market_context.source or "fresh"
    status = (market_context.status or "ok").upper()
    symbol = market_context.symbol or "^IXIC"
    basis = symbol
    if source == "proxy" and market_context.proxy_for:
        basis = f"{symbol} proxy for {market_context.proxy_for}"
    lines = [
        "",
        "[시장]",
        f"상태: {status}",
        f"기준: {basis}",
        f"기간: {market_context.period or '-'} / 종가 {market_context.close_count}개",
    ]
    if market_context.as_of:
        lines.append(f"기준시각: {market_context.as_of}")
    warning = _market_context_warning(market_context)
    if warning:
        lines.append(f"경고: {warning}")
    return lines


def _market_context_warning(market_context: MarketContext) -> str:
    source = (market_context.source or "fresh").lower()
    status = (market_context.status or "ok").lower()
    if status in {"degraded", "unknown"}:
        return "나스닥 MA20 판단 불가. 후보 수집은 진행됐지만 자동매수는 제한됩니다."
    if source == "last_good_cache":
        return "실시간 나스닥 데이터 부족으로 최근 정상 시장 컨텍스트를 사용했습니다."
    if source == "proxy":
        return f"{market_context.proxy_for or '^IXIC'} 데이터 부족으로 proxy 기준 추세를 사용했습니다."
    return ""
