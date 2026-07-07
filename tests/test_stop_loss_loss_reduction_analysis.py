from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_bot.stop_loss_loss_reduction_analysis import (
    ACTION_BOUNDARY,
    analyze_stop_loss_loss_reduction,
)


FIXTURE = Path(__file__).parent / "fixtures" / "stop_loss_loss_reduction_rows.json"


def test_stop_loss_loss_reduction_analysis_groups_fixture_rows() -> None:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))

    payload = analyze_stop_loss_loss_reduction(
        rows,
        generated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
    )

    assert payload["actionBoundary"] == ACTION_BOUNDARY
    assert payload["dataScope"]["rowCount"] == 4
    assert payload["dataScope"]["completedCount"] == 4
    assert payload["dataScope"]["stopLossCount"] == 2
    assert payload["baseline"]["stopLossRate"] == 0.5
    assert payload["baseline"]["totalStopLossLossRate"] == pytest.approx(0.1022)
    assert payload["baseline"]["stopLossShareOfLossRate"] == 1.0

    by_entry = payload["groups"]["byEntryReason"]["OPENING_BREAKOUT"]
    assert by_entry["stopLossCount"] == 2
    assert by_entry["totalStopLossLossRate"] == pytest.approx(0.1022)
    assert by_entry["profitGivebackReviewCount"] == 1
    assert by_entry["earlyWeaknessReviewCount"] == 1
    assert by_entry["liquiditySpreadReviewCount"] == 1
    assert by_entry["openingGapReviewCount"] == 1

    signals = payload["opportunitySignals"]
    assert signals["profit_giveback_review"]["count"] == 1
    assert signals["early_weakness_review"]["count"] == 1
    assert signals["liquidity_spread_review"]["count"] == 1
    assert signals["opening_gap_review"]["count"] == 1

    pull = next(item for item in payload["details"] if item["ticker"] == "PULL")
    assert pull["reviewSignals"] == ["profit_giveback_review"]
    assert pull["maxSnapshotProfitRate"] == pytest.approx(0.0225)
    assert pull["snapshotProfits"]["5"] == pytest.approx(0.0225)

    weak = next(item for item in payload["details"] if item["ticker"] == "WEAK")
    assert weak["primaryReviewSignal"] == "early_weakness_review"
    assert weak["bidAskSpreadRate"] == pytest.approx(0.012)
    assert weak["openingGap"] == pytest.approx(0.035)
    assert "analysis_only" in payload["actionBoundary"]
    assert "trading, risk, order, scheduler, DB, or API behavior" in payload["actionBoundary"]
    assert payload["warnings"]


def test_stop_loss_loss_reduction_analysis_handles_no_stop_loss_rows() -> None:
    payload = analyze_stop_loss_loss_reduction(
        [
            {
                "trade_date": "2026-06-18",
                "ticker": "WINR",
                "final_exit_reason": "TAKE_PROFIT",
                "final_profit_rate": "3.00%",
            }
        ],
        generated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
    )

    assert payload["dataScope"]["stopLossCount"] == 0
    assert payload["baseline"]["totalStopLossLossRate"] == 0.0
    assert payload["groups"]["byEntryReason"] == {}
    assert "no STOP_LOSS rows found" in payload["warnings"]
