from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


NO_RECHECK_EVALUATION = "NO_RECHECK_EVALUATION"
MISSING_SCORE = "MISSING_SCORE"


def target_runner_profiles(
    target_rows: Sequence[tuple[Any, ...]],
    scores_by_ticker: Mapping[str, tuple[Any, ...]],
    evaluations_by_ticker: Mapping[str, tuple[Any, ...]] | None = None,
) -> dict[str, dict[str, object]]:
    evaluations_by_ticker = evaluations_by_ticker or {}
    return {
        ticker: runner_profile(
            row,
            _lookup(scores_by_ticker, ticker),
            _lookup(evaluations_by_ticker, ticker),
        )
        for row in target_rows
        if (ticker := target_ticker(row))
    }


def runner_profile(
    target_row: tuple[Any, ...],
    score_row: tuple[Any, ...] | None = None,
    evaluation_row: tuple[Any, ...] | None = None,
) -> dict[str, object]:
    ticker = target_ticker(target_row)
    name = target_name(target_row)
    volume_ratio = target_volume_ratio(target_row)
    price_change = target_price_change(target_row)
    total_score = score_total(score_row)
    recheck_score = evaluation_final_score(evaluation_row)
    noise_flags = runner_noise_flags(ticker, name, price_change)
    data_quality, notes = _data_quality(total_score, recheck_score)

    momentum = clamp_score(price_change / 150.0 * 100.0)
    volume_expansion = clamp_score(volume_ratio / 3000.0 * 100.0)
    score_quality = total_score if total_score is not None else 0.0
    recheck_quality = (
        recheck_score
        if recheck_score is not None
        else total_score if total_score is not None else 50.0
    )
    overheat_control = _overheat_control(price_change, evaluation_row)
    noise_penalty = min(45.0, len(noise_flags) * 15.0)
    score = clamp_score(
        momentum * 0.25
        + volume_expansion * 0.25
        + score_quality * 0.20
        + recheck_quality * 0.15
        + overheat_control * 0.15
        - noise_penalty
    )

    return {
        "ticker": ticker,
        "runnerScore": round(score, 1),
        "runnerGrade": runner_grade(score),
        "noiseFlags": noise_flags,
        "dataQuality": data_quality,
        "notes": notes,
        "components": {
            "momentum": round(momentum, 1),
            "volumeExpansion": round(volume_expansion, 1),
            "scoreQuality": round(score_quality, 1) if total_score is not None else None,
            "recheckQuality": round(recheck_quality, 1) if recheck_score is not None else None,
            "overheatControl": round(overheat_control, 1),
            "noisePenalty": round(noise_penalty, 1),
        },
    }


def target_ticker(row: tuple[Any, ...]) -> str:
    return "" if not row else str(row[0] or "").strip().upper()


def target_name(row: tuple[Any, ...]) -> str:
    return str(row[1] or "").strip() if len(row) > 1 else ""


def target_volume_ratio(row: tuple[Any, ...]) -> float:
    if len(row) >= 6:
        return _number(row[4])
    if len(row) >= 5:
        return _number(row[3])
    if len(row) >= 4:
        return _number(row[2])
    return 0.0


def target_price_change(row: tuple[Any, ...]) -> float:
    if len(row) >= 6:
        return _number(row[5])
    if len(row) >= 5:
        return _number(row[4])
    if len(row) >= 4:
        return _number(row[3])
    if len(row) >= 3:
        return _number(row[2])
    return 0.0


def score_total(row: tuple[Any, ...] | None) -> float | None:
    if row is None or len(row) <= 3:
        return None
    return clamp_score(_number(row[3]))


def evaluation_final_score(row: tuple[Any, ...] | None) -> float | None:
    if row is None or len(row) <= 5 or row[5] is None:
        return None
    return clamp_score(_number(row[5]))


def runner_noise_flags(ticker: str, name: str, price_change: float | None = None) -> list[str]:
    upper_ticker = str(ticker or "").strip().upper()
    upper_name = str(name or "").strip().upper()
    flags: list[str] = []

    if any(token in upper_name for token in ("ISHARES", "PROSHARES", "DIREXION", "ETF", "ETN")):
        flags.append("ETF_OR_ETN")
    if any(token in upper_name for token in ("2X", "3X", "ULTRA", "LEVERAGED")):
        flags.append("LEVERAGED_ETF")
    if any(token in upper_name for token in ("INVERSE", "SHORT")):
        flags.append("INVERSE_ETF")
    if any(token in upper_name for token in ("BOND", "TREASURY", "FIXED INCOME")):
        flags.append("BOND_ETF")
    if any(token in upper_name for token in ("FUND", "TRUST")):
        flags.append("FUND_OR_TRUST")
    if _is_warrant_or_right(upper_ticker, upper_name):
        flags.append("WARRANT_OR_RIGHT")
    if _is_unit(upper_ticker, upper_name):
        flags.append("UNIT")
    if price_change is not None and abs(float(price_change)) >= 300.0:
        flags.append("EXTREME_PRICE_CHANGE")

    return flags


def clamp_score(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 100:
        return 100.0
    return float(value)


def runner_grade(score: float) -> str:
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    if score >= 45:
        return "C"
    return "D"


def _lookup(mapping: Mapping[str, tuple[Any, ...]], ticker: str) -> tuple[Any, ...] | None:
    return mapping.get(ticker) or mapping.get(ticker.upper()) or mapping.get(ticker.lower())


def _number(value: Any) -> float:
    try:
        return float(str(value).replace("$", "").replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _data_quality(
    total_score: float | None,
    recheck_score: float | None,
) -> tuple[str, list[str]]:
    notes: list[str] = []
    if total_score is None:
        notes.append(MISSING_SCORE)
    if recheck_score is None:
        notes.append(NO_RECHECK_EVALUATION)
    if not notes:
        return "FULL", []
    if total_score is None and recheck_score is None:
        return "MISSING", notes
    return "PARTIAL", notes


def _overheat_control(price_change: float, evaluation_row: tuple[Any, ...] | None) -> float:
    if evaluation_row is not None:
        reason = str(evaluation_row[8] if len(evaluation_row) > 8 else "")
        decision = str(evaluation_row[10] if len(evaluation_row) > 10 else "")
        if "OVERHEAT_LIMIT_EXCEEDED" in {reason, decision}:
            return 20.0
    if price_change >= 300:
        return 30.0
    if price_change >= 150:
        return 80.0
    return 100.0


def _is_warrant_or_right(ticker: str, name: str) -> bool:
    if any(token in name for token in ("WARRANT", "RIGHT")):
        return True
    return ticker.endswith("W") or ticker.endswith("WS") or ticker.endswith("WT")


def _is_unit(ticker: str, name: str) -> bool:
    if "UNIT" in name:
        return True
    return ticker.endswith("U") and any(token in name for token in ("ACQUISITION", "CORP"))
