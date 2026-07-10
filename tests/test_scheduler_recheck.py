from datetime import date

from trading_bot.config import TradingSettings
from trading_bot.models import AccountState, BuyIntent, ScoreRecord
from trading_bot.runtime import DryRunResult
from trading_bot.scheduler_recheck import (
    _fixed_recheck_settings,
    append_entry_reason,
    fixed_recheck_selected_scores,
    fixed_opening_result,
    hybrid_recheck,
    hybrid_selected_scores,
    recheck_fixed_watchlist,
    tag_mode_intents,
)


def test_fixed_recheck_preserves_configured_condition_policies() -> None:
    soft = _fixed_recheck_settings(
        TradingSettings(
            breakout_close_condition_mode="SOFT_SCORE",
            volume_increase_condition_mode="SOFT_SCORE",
            pullback_rebreak_condition_mode="SOFT_SCORE",
        )
    )
    hard = _fixed_recheck_settings(
        TradingSettings(
            breakout_close_condition_mode="HARD_FILTER",
            volume_increase_condition_mode="HARD_FILTER",
            pullback_rebreak_condition_mode="HARD_FILTER",
        )
    )

    assert soft.volume_increase_condition_mode == "SOFT_SCORE"
    assert soft.breakout_close_condition_mode == "SOFT_SCORE"
    assert soft.pullback_rebreak_condition_mode == "SOFT_SCORE"
    assert hard.volume_increase_condition_mode == "HARD_FILTER"
    assert hard.breakout_close_condition_mode == "HARD_FILTER"
    assert hard.pullback_rebreak_condition_mode == "HARD_FILTER"


class Latest:
    def __init__(self) -> None:
        self.opening_fixed_mode = True
        self.opening_trade_date = date(2026, 6, 8)
        self.opening_result = result_with_scores(("AAA", 90), ("BBB", 80))


class Scoring:
    def __init__(self, selected: tuple[ScoreRecord, ...]) -> None:
        self.selected = selected
        self.trade_date = date(2026, 6, 8)


class Accounts:
    def current_account(self) -> AccountState:
        return AccountState(100000, 100000, 0, 0, 0)


class Runtime:
    def __init__(self, refreshed: DryRunResult | None = None) -> None:
        self.accounts = Accounts()
        self.breakout = self
        self.refreshed = refreshed
        self.breakout_tickers: list[str] = []
        self.run_count = 0

    def breakout_input(self, ticker: str):
        self.breakout_tickers.append(ticker)
        return (10, 9, 9.5, 8)

    def run(self) -> DryRunResult:
        self.run_count += 1
        if self.refreshed is None:
            raise AssertionError("refreshed result is required")
        return self.refreshed


class SourceScoring(Scoring):
    def __init__(
        self,
        selected: tuple[ScoreRecord, ...],
        sources: dict[str, str],
    ) -> None:
        super().__init__(selected)
        self.sources = sources

    def candidate_source(self, ticker: str) -> str:
        return self.sources.get(ticker, "auto")


def result_with_scores(*items: tuple[str, float]) -> DryRunResult:
    selected = tuple(ScoreRecord(ticker, score, score) for ticker, score in items)
    return DryRunResult(
        AccountState(100000, 100000, 0, 0, 0),
        Scoring(selected),
        tuple(BuyIntent(item.ticker, 1, 10, 10, 0.01) for item in selected),
    )


def result_with_sources(
    items: tuple[tuple[str, float], ...],
    sources: dict[str, str],
) -> DryRunResult:
    selected = tuple(ScoreRecord(ticker, score, score) for ticker, score in items)
    return DryRunResult(
        AccountState(100000, 100000, 0, 0, 0),
        SourceScoring(selected, sources),
        tuple(BuyIntent(item.ticker, 1, 10, 10, 0.01) for item in selected),
    )


def test_fixed_opening_result_requires_fixed_or_hybrid_mode(monkeypatch) -> None:
    monkeypatch.setattr("trading_bot.scheduler_recheck.current_trade_date", lambda: date(2026, 6, 8))

    assert fixed_opening_result(
        Latest(),
        TradingSettings(candidate_selection_mode="refresh", refresh_intraday_candidates=True),
    ) is None


def test_fixed_opening_result_requires_opening_fixed_mode(monkeypatch) -> None:
    monkeypatch.setattr("trading_bot.scheduler_recheck.current_trade_date", lambda: date(2026, 6, 8))
    latest = Latest()
    latest.opening_fixed_mode = False

    assert fixed_opening_result(latest, TradingSettings(refresh_intraday_candidates=False)) is None


def test_fixed_opening_result_requires_same_trade_date(monkeypatch) -> None:
    monkeypatch.setattr("trading_bot.scheduler_recheck.current_trade_date", lambda: date(2026, 6, 9))

    assert fixed_opening_result(Latest(), TradingSettings(refresh_intraday_candidates=False)) is None


def test_fixed_opening_result_returns_opening_result_when_reusable(monkeypatch) -> None:
    monkeypatch.setattr("trading_bot.scheduler_recheck.current_trade_date", lambda: date(2026, 6, 8))
    latest = Latest()

    assert fixed_opening_result(latest, TradingSettings(refresh_intraday_candidates=False)) is latest.opening_result


def test_recheck_fixed_watchlist_limits_selected_and_uses_fixed_source(monkeypatch) -> None:
    captured = {}

    def fake_plan(selected, breakout_inputs, account, settings, **kwargs):
        captured["selected"] = [item.ticker for item in selected]
        captured["breakout_inputs"] = sorted(breakout_inputs)
        captured["source"] = kwargs["source"]
        captured["trade_date"] = kwargs["trade_date"]
        return [BuyIntent(item.ticker, 1, 10, 10, 0.01) for item in selected]

    monkeypatch.setattr("trading_bot.scheduler_recheck.plan_buy_intents", fake_plan)
    runtime = Runtime()
    latest_result = result_with_scores(("AAA", 90), ("BBB", 80), ("CCC", 70))

    result = recheck_fixed_watchlist(
        runtime,
        latest_result,
        TradingSettings(opening_fixed_candidate_limit=2),
        repository="repository",
    )

    assert [item.ticker for item in result.buy_intents] == ["AAA", "BBB"]
    assert captured == {
        "selected": ["AAA", "BBB"],
        "breakout_inputs": ["AAA", "BBB"],
        "source": "fixed_recheck",
        "trade_date": date(2026, 6, 8),
    }


def test_fixed_recheck_selected_scores_keeps_manual_candidates_separate_from_auto_limit() -> None:
    latest_result = result_with_sources(
        (
            ("AUTO1", 99),
            ("AUTO2", 98),
            ("MAN1", 97),
            ("MAN2", 96),
            ("AUTO3", 95),
        ),
        {"MAN1": "manual_buy_list", "MAN2": "both"},
    )

    selected = fixed_recheck_selected_scores(
        latest_result,
        TradingSettings(
            opening_fixed_candidate_limit=1,
            max_manual_selected_candidates=2,
        ),
    )

    assert [item.ticker for item in selected] == ["AUTO1", "MAN1", "MAN2"]


def test_hybrid_selected_scores_merges_and_ranks_candidates() -> None:
    opening = result_with_scores(
        ("OPEN1", 95),
        ("OPEN2", 94),
        ("OPEN3", 93),
        ("OPEN4", 92),
    )
    refreshed = result_with_scores(
        ("NEW1", 99),
        ("NEW2", 98),
        ("OPEN2", 97),
        ("NEW3", 70),
    )

    selected = hybrid_selected_scores(
        opening,
        refreshed,
        TradingSettings(
            opening_fixed_candidate_limit=3,
            intraday_refresh_candidate_limit=3,
            hybrid_candidate_limit=5,
        ),
    )

    assert [item.ticker for item in selected] == ["NEW1", "NEW2", "OPEN2", "OPEN1", "OPEN3"]


def test_hybrid_recheck_uses_hybrid_source(monkeypatch) -> None:
    captured = {}

    def fake_plan(selected, breakout_inputs, account, settings, **kwargs):
        captured["selected"] = [item.ticker for item in selected]
        captured["source"] = kwargs["source"]
        return [BuyIntent(item.ticker, 1, 10, 10, 0.01) for item in selected]

    monkeypatch.setattr("trading_bot.scheduler_recheck.plan_buy_intents", fake_plan)
    runtime = Runtime(refreshed=result_with_scores(("NEW1", 99), ("OPEN2", 97)))
    opening = result_with_scores(("OPEN1", 95), ("OPEN2", 94))

    result = hybrid_recheck(
        runtime,
        opening,
        TradingSettings(
            opening_fixed_candidate_limit=2,
            intraday_refresh_candidate_limit=2,
            hybrid_candidate_limit=3,
        ),
        repository="repository",
    )

    assert runtime.run_count == 1
    assert [item.ticker for item in result.buy_intents] == ["NEW1", "OPEN2", "OPEN1"]
    assert captured["selected"] == ["NEW1", "OPEN2", "OPEN1"]
    assert captured["source"] == "hybrid_recheck"


def test_tag_mode_intents_adds_mode_reason() -> None:
    intents = tag_mode_intents([BuyIntent("AAA", 1, 10, 10, 0.01)], "hybrid")

    assert intents[0].entry_reason == "OPENING_BREAKOUT+HYBRID_CANDIDATE"
    assert "장초반 고정 후보와 15분 신규 후보 결합" in intents[0].entry_reason_detail


def test_append_entry_reason_does_not_duplicate_reason() -> None:
    intent = append_entry_reason(
        BuyIntent(
            "AAA",
            1,
            10,
            10,
            0.01,
            entry_reason="OPENING_BREAKOUT+OPENING_FIXED",
            entry_reason_detail="기존 상세",
        ),
        "OPENING_FIXED",
        "장초반 고정 후보 재평가",
    )

    assert intent.entry_reason == "OPENING_BREAKOUT+OPENING_FIXED"
    assert intent.entry_reason_detail == "기존 상세; 장초반 고정 후보 재평가"
