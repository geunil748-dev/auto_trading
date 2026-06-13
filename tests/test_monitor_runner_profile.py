from trading_bot.monitor_runner_profile import (
    NO_RECHECK_EVALUATION,
    clamp_score,
    runner_noise_flags,
    runner_lifecycle,
    runner_profile,
)


def test_runner_profile_scores_lase_like_runner_as_a_grade() -> None:
    profile = runner_profile(
        ("LASE", "Laser Photonics", 1.40, 12_345, 4071.35, 151.21),
        ("LASE", 0.0, 65.0, 58.5, True),
    )

    assert profile["runnerGrade"] == "A"
    assert profile["runnerScore"] >= 75
    assert profile["noiseFlags"] == []
    assert profile["dataQuality"] == "PARTIAL"
    assert NO_RECHECK_EVALUATION in profile["notes"]


def test_runner_profile_does_not_overpromote_volume_only_candidate() -> None:
    profile = runner_profile(
        ("MRLN", "Marine", 0.53, 20_000, 3293.0, 29.94),
        ("MRLN", 0.0, 65.0, 65.25, True),
    )

    assert profile["runnerGrade"] == "B"
    assert 60 <= profile["runnerScore"] < 75


def test_runner_profile_includes_latest_recheck_lifecycle() -> None:
    profile = runner_profile(
        ("LASE", "Laser Photonics", 1.40, 12_345, 4071.35, 151.21),
        ("LASE", 0.0, 65.0, 58.5, True),
        (
            "LASE",
            "intraday_recheck",
            "2026-06-10 22:45:00",
            1,
            1,
            82.0,
            0,
            0,
            "BUY_ALLOWED",
            "[]",
            "ORDER_SUBMITTED",
        ),
    )

    assert profile["dataQuality"] == "FULL"
    assert profile["components"]["recheckQuality"] == 82.0
    assert profile["lifecycle"] == {
        "stage": "ORDER_SUBMITTED",
        "source": "intraday_recheck",
        "evaluatedAt": "2026-06-10 22:45:00",
        "buyAllowed": True,
        "orderSubmitted": True,
        "finalScore": 82.0,
        "hardFilterFailedCount": 0,
        "softConditionFailedCount": 0,
        "buyBlockReason": "BUY_ALLOWED",
        "finalDecision": "ORDER_SUBMITTED",
    }


def test_runner_lifecycle_marks_blocked_recheck_reason() -> None:
    lifecycle = runner_lifecycle(
        (
            "MRLN",
            "intraday_recheck",
            "2026-06-10 22:45:00",
            0,
            0,
            61.5,
            1,
            2,
            "OVERHEAT_LIMIT_EXCEEDED",
            '["OVERHEAT_LIMIT_EXCEEDED"]',
            "OVERHEAT_LIMIT_EXCEEDED",
        )
    )

    assert lifecycle["stage"] == "BLOCKED"
    assert lifecycle["buyBlockReason"] == "OVERHEAT_LIMIT_EXCEEDED"
    assert lifecycle["finalScore"] == 61.5


def test_runner_noise_flags_classify_structured_products() -> None:
    assert "BOND_ETF" in runner_noise_flags(
        "IUSB",
        "iShares Core Total USD Bond Market ETF",
    )
    tqqq_flags = runner_noise_flags("TQQQ", "ProShares UltraPro QQQ")
    assert "ETF_OR_ETN" in tqqq_flags
    assert "LEVERAGED_ETF" in tqqq_flags
    sqqq_flags = runner_noise_flags("SQQQ", "ProShares UltraPro Short QQQ")
    assert "INVERSE_ETF" in sqqq_flags
    assert "WARRANT_OR_RIGHT" in runner_noise_flags("EUDAW", "EUDA Health Warrant")
    assert "UNIT" in runner_noise_flags("MLACU", "Mountain Lake Acquisition Unit")


def test_runner_noise_flags_avoid_plain_r_suffix_false_positive() -> None:
    assert runner_noise_flags("MSTR", "Strategy Inc") == []


def test_runner_noise_flags_marks_extreme_price_change() -> None:
    assert "EXTREME_PRICE_CHANGE" in runner_noise_flags("INHD", "Inno Holdings", 350.0)


def test_clamp_score_bounds_values() -> None:
    assert clamp_score(-1) == 0.0
    assert clamp_score(50) == 50.0
    assert clamp_score(101) == 100.0
