from datetime import date

from trading_bot.candidate_notifications import candidate_list_message, entry_gate_blocked_message
from trading_bot.models import CandidateSnapshot, DailyScore, DailyTarget, ScoreRecord


def test_candidate_list_message_summarizes_selected_candidates() -> None:
    targets = (
        DailyTarget(
            date(2026, 6, 8),
            CandidateSnapshot("AAA", 12.34, 12.0, 11.0, 0.05, 1.5, 1, 2, "Alpha"),
        ),
        DailyTarget(
            date(2026, 6, 8),
            CandidateSnapshot("BBB", 23.45, 23.0, 22.0, 0.03, 1.2, 2, 1, "Beta"),
        ),
    )
    scores = (
        DailyScore(date(2026, 6, 8), ScoreRecord("AAA", 80, 70), True),
        DailyScore(date(2026, 6, 8), ScoreRecord("BBB", 60, 55), False),
    )

    message = candidate_list_message(date(2026, 6, 8), targets, scores)

    assert "후보 리스트 확정" in message
    assert "거래일: 2026-06-08" in message
    assert "후보 수: 2" in message
    assert "선정 수: 1" in message
    assert "AAA Alpha (선정, 점수 71.0, 가격 $12.34)" in message
    assert "BBB Beta (후보, 점수 55.5, 가격 $23.45)" in message


def test_candidate_list_message_limits_rows() -> None:
    targets = tuple(
        DailyTarget(
            date(2026, 6, 8),
            CandidateSnapshot(f"T{index:02}", 10 + index, 10, 9, 0.01, 1.0, index, index),
        )
        for index in range(12)
    )

    message = candidate_list_message(date(2026, 6, 8), targets, ())

    assert "T00" in message
    assert "T09" in message
    assert "T10" not in message
    assert "... 외 2건" in message


def test_candidate_list_message_reports_no_candidates() -> None:
    message = candidate_list_message(date(2026, 6, 8), (), ())

    assert "후보 수: 0" in message
    assert "선정 수: 0" in message
    assert "금일 후보리스트가 없습니다." in message


def test_entry_gate_blocked_message_reports_reason() -> None:
    message = entry_gate_blocked_message(date(2026, 6, 8), "MARKET_BELOW_MA20")

    assert "진입 게이트 차단" in message
    assert "거래일: 2026-06-08" in message
    assert "사유: MARKET_BELOW_MA20" in message
