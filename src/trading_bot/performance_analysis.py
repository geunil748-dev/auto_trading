from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PRIMARY_STRATEGY_PRIORITY = (
    "PYRAMIDING",
    "INTRADAY_RECHECK",
    "OPENING_BREAKOUT",
    "OPENING_FIXED",
    "RANKED_LIST",
)

STRATEGY_LABELS = {
    "OPENING_BREAKOUT": "장초반 돌파",
    "INTRADAY_RECHECK": "15분 재평가",
    "PYRAMIDING": "불타기 추가매수",
    "OPENING_FIXED": "장초반 고정 후보",
    "RANKED_LIST": "랭킹 후보",
    "UNKNOWN": "미분류",
}

TAG_LABELS = {
    "NEWS_POSITIVE": "뉴스 긍정",
    "CHART_POSITIVE": "차트 조건 양호",
    "VWAP_ABOVE": "VWAP 상단",
    "VOLUME_SURGE": "거래량 급증",
    "HYBRID_CANDIDATE": "하이브리드 후보",
    "REFRESH_CANDIDATE": "15분 신규 후보",
    "MARKET_BELOW_MA20_BYPASSED": "나스닥 20일선 우회",
}

EXIT_LABELS = {
    "STOP_LOSS": "손절",
    "TAKE_PROFIT": "익절",
    "PARTIAL_TAKE_PROFIT": "분할 익절",
    "TRAILING_STOP": "트레일링 스탑",
    "EOD": "장마감 매도",
    "MANUAL_SELL": "수동 매도",
    "MANUAL_SELL_ALL": "전량 수동 매도",
}


@dataclass(frozen=True)
class ClosedTradeAnalysis:
    entry_at: Any
    exit_at: Any
    ticker: str
    ticker_name: str
    entry_strategy: str
    entry_tags: tuple[str, ...]
    exit_reason: str
    holding_minutes: float
    profit_rate: float
    profit_usd: float
    strategy_version: str = ""


def split_entry_reason(reason: Any) -> tuple[str, tuple[str, ...]]:
    tokens = _reason_tokens(reason)
    strategy = next((token for token in PRIMARY_STRATEGY_PRIORITY if token in tokens), "")
    if not strategy:
        strategy = tokens[0] if tokens else "UNKNOWN"
    tags = tuple(token for token in tokens if token != strategy)
    return strategy, tags


def strategy_label(strategy: str) -> str:
    return STRATEGY_LABELS.get(strategy, strategy or STRATEGY_LABELS["UNKNOWN"])


def tag_label(tag: str) -> str:
    return TAG_LABELS.get(tag, tag)


def exit_label(reason: str) -> str:
    return EXIT_LABELS.get(reason, reason or "-")


def aggregate_strategy_stats(trades: list[ClosedTradeAnalysis]) -> list[dict[str, Any]]:
    grouped: dict[str, list[ClosedTradeAnalysis]] = {}
    for trade in trades:
        grouped.setdefault(trade.entry_strategy, []).append(trade)
    rows = []
    for strategy, items in grouped.items():
        chronological = sorted(items, key=lambda item: str(item.exit_at))
        rows.append(
            {
                "strategy": strategy,
                "strategyText": strategy_label(strategy),
                "count": len(items),
                "winRate": _win_rate(items),
                "averageProfitRate": _average(item.profit_rate for item in items),
                "totalProfitUsd": sum(item.profit_usd for item in items),
                "averageHoldingMinutes": _average(item.holding_minutes for item in items),
                "maxDrawdown": _max_drawdown([item.profit_rate for item in chronological]),
            }
        )
    return sorted(rows, key=lambda row: row["totalProfitUsd"], reverse=True)


def aggregate_exit_reason_stats(trades: list[ClosedTradeAnalysis]) -> list[dict[str, Any]]:
    grouped: dict[str, list[ClosedTradeAnalysis]] = {}
    for trade in trades:
        grouped.setdefault(trade.exit_reason or "UNKNOWN", []).append(trade)
    rows = []
    for reason, items in grouped.items():
        rows.append(
            {
                "exitReason": reason,
                "exitReasonText": exit_label(reason),
                "count": len(items),
                "winRate": _win_rate(items),
                "averageProfitRate": _average(item.profit_rate for item in items),
                "totalProfitUsd": sum(item.profit_usd for item in items),
            }
        )
    return sorted(rows, key=lambda row: row["totalProfitUsd"])


def closed_trade_from_row(row: tuple[Any, ...]) -> ClosedTradeAnalysis:
    (
        entry_at,
        exit_at,
        ticker,
        ticker_name,
        entry_reason,
        _entry_reason_detail,
        exit_reason,
        holding_minutes,
        profit_rate,
        profit_usd,
    ) = row[:10]
    strategy_version = row[10] if len(row) > 10 else ""
    strategy, tags = split_entry_reason(entry_reason)
    return ClosedTradeAnalysis(
        entry_at=entry_at,
        exit_at=exit_at,
        ticker=str(ticker),
        ticker_name=str(ticker_name or ""),
        entry_strategy=strategy,
        entry_tags=tags,
        exit_reason=str(exit_reason or "UNKNOWN"),
        holding_minutes=_number(holding_minutes),
        profit_rate=_number(profit_rate),
        profit_usd=_number(profit_usd),
        strategy_version=str(strategy_version or ""),
    )


def _reason_tokens(reason: Any) -> list[str]:
    raw = str(reason or "").strip()
    if not raw:
        return []
    tokens = raw.replace(",", "+").replace(";", "+").split("+")
    return [token.strip().upper() for token in tokens if token.strip()]


def _win_rate(items: list[ClosedTradeAnalysis]) -> float:
    if not items:
        return 0.0
    return sum(1 for item in items if item.profit_usd > 0) / len(items)


def _average(values: Any) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def _max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for rate in returns:
        equity *= 1.0 + rate
        peak = max(peak, equity)
        if peak > 0:
            worst = min(worst, equity / peak - 1.0)
    return worst


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
