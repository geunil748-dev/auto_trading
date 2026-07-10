from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from trading_bot.config import TradingSettings
from trading_bot.entry_planner import plan_buy_intents
from trading_bot.models import BuyIntent
from trading_bot.runtime import DryRunResult
from trading_bot.trading_date import current_trade_date


def fixed_opening_result(
    latest,
    settings: TradingSettings,
) -> DryRunResult | None:
    if _candidate_mode(settings) not in {"fixed", "hybrid"}:
        return None
    if not latest.opening_fixed_mode:
        return None
    if latest.opening_trade_date != current_trade_date():
        return None
    # 장초반 고정 모드로 수집한 후보만 장중에 계속 감시한다.
    return latest.opening_result


def recheck_fixed_watchlist(
    runtime,
    latest_result: DryRunResult,
    settings: TradingSettings,
    repository,
) -> DryRunResult:
    account = runtime.accounts.current_account()
    fixed_settings = _fixed_recheck_settings(settings)
    selected = fixed_recheck_selected_scores(latest_result, fixed_settings)
    breakout_inputs = {
        item.ticker: runtime.breakout.breakout_input(item.ticker)
        for item in selected
    }
    intents = plan_buy_intents_with_evaluation(
        selected,
        breakout_inputs,
        account,
        fixed_settings,
        repository=repository,
        trade_date=scoring_trade_date(latest_result.scoring),
        source="fixed_recheck",
        source_by_ticker=_source_by_ticker(latest_result.scoring, selected, "fixed_recheck"),
        run_id=uuid4().hex,
        entry_reason_tags=_bypass_tags(latest_result.scoring),
    )
    return DryRunResult(account, latest_result.scoring, tuple(intents))


def hybrid_recheck(
    runtime,
    opening_result: DryRunResult,
    settings: TradingSettings,
    repository,
) -> DryRunResult:
    refreshed = runtime.run()
    account = runtime.accounts.current_account()
    selected = hybrid_selected_scores(opening_result, refreshed, settings)
    breakout_inputs = {
        item.ticker: runtime.breakout.breakout_input(item.ticker)
        for item in selected
    }
    intents = plan_buy_intents_with_evaluation(
        selected,
        breakout_inputs,
        account,
        settings,
        repository=repository,
        trade_date=scoring_trade_date(refreshed.scoring),
        source="hybrid_recheck",
        source_by_ticker=_hybrid_source_by_ticker(
            opening_result.scoring,
            refreshed.scoring,
            selected,
            "hybrid_recheck",
        ),
        run_id=uuid4().hex,
        entry_reason_tags=(
            _bypass_tags(refreshed.scoring) or _bypass_tags(opening_result.scoring)
        ),
    )
    return DryRunResult(account, refreshed.scoring, tuple(intents))


def fixed_recheck_selected_scores(
    latest_result: DryRunResult,
    settings: TradingSettings,
) -> tuple:
    auto = [
        score
        for score in latest_result.scoring.selected
        if _candidate_source(latest_result.scoring, score.ticker) not in {"manual_buy_list", "both"}
    ][: settings.opening_fixed_candidate_limit]
    selected = {score.ticker: score for score in auto}
    manual = [
        score
        for score in latest_result.scoring.selected
        if _candidate_source(latest_result.scoring, score.ticker) in {"manual_buy_list", "both"}
    ][: settings.max_manual_selected_candidates]
    for score in manual:
        selected.setdefault(score.ticker, score)
    return tuple(selected.values())


def _fixed_recheck_settings(settings: TradingSettings) -> TradingSettings:
    return replace(
        settings,
        min_total_score=max(settings.min_total_score, 60.0),
    )


def hybrid_selected_scores(
    opening_result: DryRunResult,
    refreshed: DryRunResult,
    settings: TradingSettings,
) -> tuple:
    combined = {}
    for score in fixed_recheck_selected_scores(opening_result, settings):
        combined[score.ticker] = score
    intraday_ranked = sorted(
        refreshed.scoring.selected,
        key=lambda item: (-item.total_score, item.ticker),
    )
    for score in intraday_ranked[: settings.intraday_refresh_candidate_limit]:
        combined[score.ticker] = score
    ranked = sorted(combined.values(), key=lambda item: (-item.total_score, item.ticker))
    return tuple(ranked[: settings.hybrid_candidate_limit])


def plan_buy_intents_with_evaluation(
    selected,
    breakout_inputs,
    account,
    settings,
    *,
    repository,
    trade_date,
    source: str,
    source_by_ticker=None,
    run_id: str | None = None,
    entry_reason_tags: tuple[str, ...] = (),
) -> list[BuyIntent]:
    try:
        return plan_buy_intents(
            selected,
            breakout_inputs,
            account,
            settings,
            repository=repository,
            trade_date=trade_date,
            source=source,
            source_by_ticker=source_by_ticker,
            run_id=run_id,
            entry_reason_tags=entry_reason_tags,
        )
    except TypeError as exc:
        if "unexpected keyword" not in str(exc):
            raise
        return plan_buy_intents(selected, breakout_inputs, account, settings)


def _bypass_tags(scoring) -> tuple[str, ...]:
    reason = getattr(scoring, "bypass_reason", None)
    return (reason,) if reason else ()


def _source_by_ticker(scoring, selected, default: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for score in selected:
        source = _candidate_source(scoring, score.ticker)
        result[score.ticker] = source if source in {"manual_buy_list", "both"} else default
    return result


def _hybrid_source_by_ticker(opening_scoring, refreshed_scoring, selected, default: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for score in selected:
        source = _candidate_source(refreshed_scoring, score.ticker)
        if source not in {"manual_buy_list", "both"}:
            source = _candidate_source(opening_scoring, score.ticker)
        result[score.ticker] = source if source in {"manual_buy_list", "both"} else default
    return result


def _candidate_source(scoring, ticker: str) -> str:
    if hasattr(scoring, "candidate_source"):
        return scoring.candidate_source(ticker)
    return "auto"


def scoring_trade_date(scoring) -> object:
    return getattr(scoring, "trade_date", current_trade_date())


def tag_mode_intents(intents: list[BuyIntent], mode: str) -> list[BuyIntent]:
    reason = {
        "fixed": "OPENING_FIXED",
        "hybrid": "HYBRID_CANDIDATE",
    }.get(mode, "REFRESH_CANDIDATE")
    detail = {
        "fixed": "장초반 고정 후보 재평가",
        "hybrid": "장초반 고정 후보와 15분 신규 후보 결합",
    }.get(mode, "15분마다 신규 후보 재수집")
    return [append_entry_reason(intent, reason, detail) for intent in intents]


def append_entry_reason(intent: BuyIntent, reason: str, detail: str) -> BuyIntent:
    reasons = [item for item in intent.entry_reason.split("+") if item]
    if reason not in reasons:
        reasons.append(reason)
    detail_text = "; ".join(item for item in (intent.entry_reason_detail, detail) if item)
    return replace(intent, entry_reason="+".join(reasons), entry_reason_detail=detail_text)


def _candidate_mode(settings: TradingSettings) -> str:
    if settings.candidate_selection_mode != "refresh":
        return settings.candidate_selection_mode
    return "refresh" if settings.refresh_intraday_candidates else "fixed"
