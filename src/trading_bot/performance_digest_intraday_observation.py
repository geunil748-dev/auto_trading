from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from trading_bot.performance_digest_buckets import UNKNOWN

FEATURES = (
    "BREAKOUT_CLOSE",
    "BREAKOUT_HOLD",
    "VOLUME_INCREASE",
    "VWAP_MA20",
    "PULLBACK_REBREAK",
)
MISSING_CODES = tuple(f"{feature}_DATA_MISSING" for feature in FEATURES) + (
    "REQUIRED_INTRADAY_DATA_MISSING",
)
FAILED_FIELDS = (
    "failed_hard_reasons",
    "failed_soft_reasons",
    "failed_log_reasons",
    "buy_block_reasons",
    "buy_block_reason",
)


def collect_intraday_observation(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    feature_missing: Counter[str] = Counter()
    feature_states: dict[str, Counter[str]] = {
        feature: Counter() for feature in FEATURES
    }
    false_failure_rows: list[dict[str, Any]] = []
    for row in rows:
        details, json_status = _condition_details(row.get("condition_result_json"))
        candidate_mode = _candidate_mode(row, details)
        if candidate_mode == "REAL":
            counts["non_mock_or_unknown_count"] += 1
            counts["real_candidate_count"] += 1
            continue
        if candidate_mode == "UNKNOWN":
            counts["non_mock_or_unknown_count"] += 1
            counts["unknown_mode_candidate_count"] += 1
        counts["candidate_evaluation_count"] += 1
        counts["buy_allowed_count"] += int(_truthy(row.get("buy_allowed")))
        counts["order_submitted_count"] += int(_truthy(row.get("order_submitted")))
        if json_status != "OK":
            counts[f"{json_status.lower()}_condition_json_count"] += 1
            continue
        required = str(details.get("required_data_quality_status") or "").upper()
        raw = str(details.get("data_quality_status") or "").upper()
        counts[f"required_data_{required.lower()}_count"] += int(required in {"COMPLETE", "INCOMPLETE"})
        counts[f"raw_data_{raw.lower()}_count"] += int(raw in {"COMPLETE", "INCOMPLETE"})
        policy = str(details.get("intraday_missing_data_policy") or "UNKNOWN").upper()
        counts[f"policy_{policy.lower()}_count"] += 1
        missing = set(_values(details.get("missing_data_reasons")))
        failed = set()
        for field in FAILED_FIELDS:
            failed.update(_values(details.get(field, row.get(field))))
        false_features: list[str] = []
        for feature in FEATURES:
            code = f"{feature}_DATA_MISSING"
            state = _feature_state(details, feature)
            feature_states[feature][state] += 1
            if code in missing:
                feature_missing[code] += 1
                if f"{feature}_FAILED" in failed:
                    false_features.append(feature)
        if "REQUIRED_INTRADAY_DATA_MISSING" in missing:
            feature_missing["REQUIRED_INTRADAY_DATA_MISSING"] += 1
        if false_features:
            false_failure_rows.append(
                {
                    "id": row.get("id"),
                    "ticker": row.get("ticker") or row.get("symbol"),
                    "features": false_features,
                }
            )
    incomplete = counts["required_data_incomplete_count"]
    complete = counts["required_data_complete_count"]
    known_required = complete + incomplete
    return {
        **{key: counts[key] for key in (
            "candidate_evaluation_count", "buy_allowed_count", "order_submitted_count",
            "required_data_complete_count", "required_data_incomplete_count",
            "raw_data_complete_count", "raw_data_incomplete_count",
            "policy_log_only_count", "policy_block_count",
            "malformed_condition_json_count", "missing_condition_json_count",
            "non_mock_or_unknown_count", "real_candidate_count",
            "unknown_mode_candidate_count",
        )},
        "malformed_json_count": counts["malformed_condition_json_count"],
        "required_data_incomplete_rate": (
            incomplete / known_required if known_required else UNKNOWN
        ),
        "feature_missing_counts": {code: feature_missing[code] for code in MISSING_CODES},
        "condition_state_counts": {
            feature: {state: feature_states[feature][state] for state in ("PASS", "FAIL", "NO_DATA", "DISABLED", "UNKNOWN")}
            for feature in FEATURES
        },
        "false_failure_count": len(false_failure_rows),
        "false_failure_rows": false_failure_rows[:20],
    }


def _condition_details(value: object) -> tuple[dict[str, Any], str]:
    if isinstance(value, Mapping):
        return dict(value), "OK"
    if not str(value or "").strip():
        return {}, "MISSING"
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, "MALFORMED"
    return (dict(parsed), "OK") if isinstance(parsed, Mapping) else ({}, "MALFORMED")


def _candidate_mode(row: Mapping[str, Any], details: Mapping[str, Any]) -> str:
    if "mock_trading" in details:
        return "MOCK" if _truthy(details.get("mock_trading")) else "REAL"
    if "is_mock" in row:
        return "MOCK" if _truthy(row.get("is_mock")) else "REAL"
    mode = str(row.get("mode") or "").strip().upper()
    return mode if mode in {"MOCK", "REAL"} else "UNKNOWN"


def _feature_state(details: Mapping[str, Any], feature: str) -> str:
    states = details.get("condition_states")
    value = states.get(feature) if isinstance(states, Mapping) else None
    if value is None:
        value = details.get(f"{feature.lower()}_state")
    state = str(value or "UNKNOWN").upper()
    return state if state in {"PASS", "FAIL", "NO_DATA", "DISABLED"} else "UNKNOWN"


def _values(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return [part.strip() for part in text.split(",") if part.strip()]


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}
