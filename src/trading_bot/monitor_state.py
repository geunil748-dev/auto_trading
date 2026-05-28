from __future__ import annotations

from trading_bot.runtime import DryRunResult


def state_from_dry_run(result: DryRunResult) -> dict[str, object]:
    targets = [
        [
            item.candidate.ticker,
            item.candidate.name or "-",
            _usd(item.candidate.price_usd),
            _volume(item.candidate.opening_volume),
            _percent(item.candidate.opening_volume_ratio),
            _signed_percent(item.candidate.opening_gap),
            _score(result, item.candidate.ticker),
            _target_state(result, item.candidate.ticker),
        ]
        for item in result.scoring.targets
    ]
    logs = [
        [
            "Dry run",
            "WARN" if result.scoring.blocked_reason else "INFO",
            _log_message(result),
        ]
    ]
    return {
        "targets": targets,
        "positions": [],
        "holdings": [],
        "orders": [],
        "fills": [],
        "gates": _gates(result),
        "logs": logs,
        "trades": [],
        "chart": {"closes": [], "movingAverage": []},
    }


def _score(result: DryRunResult, ticker: str) -> str:
    for item in result.scoring.scores:
        if item.score.ticker == ticker:
            return str(round(item.score.total_score))
    return "-"


def _target_state(result: DryRunResult, ticker: str) -> str:
    if any(item.ticker == ticker for item in result.buy_intents):
        return "매수 예정"
    if any(item.score.ticker == ticker and item.is_selected for item in result.scoring.scores):
        return "최종 선정"
    if any(item.score.ticker == ticker for item in result.scoring.scores):
        return "선정점수/순위 미달"
    return "점수 계산 전"


def _gates(result: DryRunResult) -> list[list[str]]:
    return [
        ["진입 조건", result.scoring.blocked_reason or "준비"],
        ["수집 종목", str(len(result.scoring.targets))],
        ["선정 점수", str(len(result.scoring.selected))],
        ["매수 예정", str(len(result.buy_intents))],
    ]


def _log_message(result: DryRunResult) -> str:
    if result.scoring.blocked_reason:
        return f"진입 차단: {result.scoring.blocked_reason}"
    return f"모의 판단으로 매수 예정 {len(result.buy_intents)}건을 계산했습니다."


def _usd(value: float) -> str:
    return f"${value:,.2f}"


def _volume(value: float) -> str:
    if value <= 0:
        return "-"
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f}억주"
    if value >= 10_000:
        return f"{value / 10_000:.0f}만주"
    return f"{value:,.0f}주"


def _percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def _signed_percent(value: float) -> str:
    return f"{value:+.1%}"
