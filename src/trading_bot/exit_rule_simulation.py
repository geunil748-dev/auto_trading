from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from trading_bot.database import pyodbc_connect_factory


SNAPSHOT_MINUTES = (5, 10, 15, 20, 30, 60)
SIMULATION_WARNING_TEXT = "이 결과는 가상 시뮬레이션이며 실제 매매 적용 전 모의매매 검증 필요"


@dataclass(frozen=True)
class ExitRuleSimulationParams:
    early_negative_minutes: int = 10
    early_negative_threshold: float = 0.0
    early_loss_5m_threshold: float = -0.02
    time_stop_minutes: int = 30
    time_stop_threshold: float = 0.0
    low_profit_30m_threshold: float = 0.003
    low_profit_60m_threshold: float = 0.01
    profit_protection_trigger: float = 0.02
    profit_protection_floor: float = -0.003
    partial_take_profit_trigger: float = 0.03
    partial_take_profit_fraction: float = 0.5


@dataclass(frozen=True)
class EntryProfitSnapshotRow:
    trade_date: str
    ticker: str
    entry_time: str = ""
    snapshots: dict[int, float] | None = None
    final_profit_rate: float | None = None
    final_exit_reason: str = ""
    strategy_version: str = ""
    entry_reason: str = ""
    candidate_source: str = ""
    ranking_selection_mode: str = ""
    order_id: str = ""
    run_id: str = ""

    def snapshot_profits(self) -> dict[int, float]:
        return dict(self.snapshots or {})


@dataclass(frozen=True)
class _RuleOutcome:
    triggered: bool
    simulated_profit_rate: float | None
    simulated_exit_minute: int | None = None
    skipped_reason: str = ""


def load_entry_profit_snapshots_from_csv(path: Path) -> tuple[list[EntryProfitSnapshotRow], list[str]]:
    warnings: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return _normalize_rows(rows, warnings), warnings


def load_entry_profit_snapshots_from_mssql(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    connect_factory: Callable[[], Any] | None = None,
) -> tuple[list[EntryProfitSnapshotRow], list[str]]:
    connect = connect_factory or pyodbc_connect_factory()
    sql = """
        SELECT trade_date, ticker, ticker_name, entry_time, entry_price,
               profit_after_5m, profit_after_10m, profit_after_15m,
               profit_after_20m, profit_after_30m, profit_after_60m,
               final_exit_reason, final_profit_rate, strategy_version
        FROM entry_profit_snapshot
    """
    where: list[str] = []
    params: list[Any] = []
    if date_from is not None:
        where.append("trade_date >= ?")
        params.append(date_from)
    if date_to is not None:
        where.append("trade_date <= ?")
        params.append(date_to)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY trade_date ASC, entry_time ASC"

    with closing(connect()) as connection:
        cursor = connection.cursor()
        rows = cursor.execute(sql, tuple(params)).fetchall()

    keys = (
        "trade_date",
        "ticker",
        "ticker_name",
        "entry_time",
        "entry_price",
        "profit_after_5m",
        "profit_after_10m",
        "profit_after_15m",
        "profit_after_20m",
        "profit_after_30m",
        "profit_after_60m",
        "final_exit_reason",
        "final_profit_rate",
        "strategy_version",
    )
    warnings: list[str] = []
    mapped = [dict(zip(keys, row, strict=False)) for row in rows]
    return _normalize_rows(mapped, warnings), warnings


def simulate_exit_rules(
    rows: Iterable[EntryProfitSnapshotRow],
    *,
    params: ExitRuleSimulationParams | None = None,
    source: str = "",
    generated_at: datetime | None = None,
    warnings: Iterable[str] = (),
) -> dict[str, Any]:
    settings = params or ExitRuleSimulationParams()
    row_list = list(rows)
    generated = generated_at or datetime.now(timezone.utc)
    completed = [row for row in row_list if row.final_profit_rate is not None]
    baseline_rates = [row.final_profit_rate for row in completed if row.final_profit_rate is not None]
    details: list[dict[str, Any]] = []
    output_warnings = list(warnings)
    rules = _rule_definitions(settings)
    summaries: dict[str, dict[str, Any]] = {}

    for rule_name, evaluator in rules.items():
        summary = _empty_rule_summary(rule_name, settings)
        skipped_reasons: dict[str, int] = defaultdict(int)
        actual_rates: list[float] = []
        simulated_rates: list[float] = []
        for row in row_list:
            outcome = evaluator(row)
            if outcome.skipped_reason:
                summary["skippedCount"] += 1
                skipped_reasons[outcome.skipped_reason] += 1
                details.append(_detail(row, rule_name, outcome, "skipped"))
                continue
            if row.final_profit_rate is None or outcome.simulated_profit_rate is None:
                summary["skippedCount"] += 1
                skipped_reasons["missing_final_profit_rate"] += 1
                details.append(
                    _detail(
                        row,
                        rule_name,
                        _RuleOutcome(False, None, skipped_reason="missing_final_profit_rate"),
                        "skipped",
                    )
                )
                continue
            summary["eligibleCount"] += 1
            actual_rates.append(row.final_profit_rate)
            simulated_rates.append(outcome.simulated_profit_rate)
            delta = outcome.simulated_profit_rate - row.final_profit_rate
            verdict = _verdict(delta)
            if outcome.triggered:
                summary["triggeredCount"] += 1
                details.append(_detail(row, rule_name, outcome, verdict))
            if verdict == "helped":
                summary["helpedCount"] += 1
            elif verdict == "hurt":
                summary["hurtCount"] += 1
            else:
                summary["unchangedCount"] += 1
            summary["netDeltaProfitRate"] += delta
        _finish_rule_summary(summary, actual_rates, simulated_rates)
        for reason, count in sorted(skipped_reasons.items()):
            output_warnings.append(f"{rule_name}: skipped {count} rows ({reason})")
        summaries[rule_name] = summary

    return {
        "generatedAt": generated.isoformat(),
        "source": source,
        "dataScope": _data_scope(row_list),
        "baseline": _baseline_summary(baseline_rates, len(row_list) - len(completed)),
        "rules": summaries,
        "details": details,
        "warnings": output_warnings,
    }


def write_exit_rule_simulation_output(
    payload: Mapping[str, Any],
    *,
    output: Path | None = None,
    output_format: str = "json",
) -> str:
    rendered = (
        render_exit_rule_simulation_text(payload)
        if output_format == "text"
        else json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return rendered


def summarize_exit_rule_simulation_archive(
    input_dir: Path,
    *,
    days: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=days) if days is not None else None
    warnings: list[str] = []
    payloads: list[tuple[Path, dict[str, Any], datetime | None]] = []

    if not input_dir.exists():
        return {
            "inputDir": str(input_dir),
            "fileCount": 0,
            "dateRange": {"from": None, "to": None},
            "rules": {},
            "topHelpedTrades": [],
            "topHurtTrades": [],
            "warnings": [f"input directory not found: {input_dir}"],
        }

    for path in sorted(input_dir.glob("exit_rule_simulation*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            warnings.append(f"{path.name}: skipped unreadable json ({type(exc).__name__})")
            continue
        generated = _generated_at(payload.get("generatedAt"))
        if generated is None:
            generated = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            warnings.append(f"{path.name}: generatedAt missing, file mtime used")
        if cutoff is not None and generated < cutoff:
            continue
        payloads.append((path, payload, generated))

    rule_totals: dict[str, dict[str, Any]] = {}
    helped: list[dict[str, Any]] = []
    hurt: list[dict[str, Any]] = []
    generated_dates = [item[2] for item in payloads if item[2] is not None]
    for path, payload, _generated in payloads:
        for rule_name, summary in (payload.get("rules") or {}).items():
            total = rule_totals.setdefault(rule_name, _empty_archive_rule_summary(rule_name))
            total["eligibleCount"] += int(summary.get("eligibleCount") or 0)
            total["triggeredCount"] += int(summary.get("triggeredCount") or 0)
            total["helpedCount"] += int(summary.get("helpedCount") or 0)
            total["hurtCount"] += int(summary.get("hurtCount") or 0)
            total["unchangedCount"] += int(summary.get("unchangedCount") or 0)
            total["netDeltaProfitRate"] += float(summary.get("netDeltaProfitRate") or 0.0)
            total["files"].append(path.name)
        for detail in payload.get("details") or []:
            delta = detail.get("deltaProfitRate")
            if not isinstance(delta, (int, float)):
                continue
            record = dict(detail)
            record["file"] = path.name
            if delta > 0:
                helped.append(record)
            elif delta < 0:
                hurt.append(record)

    for summary in rule_totals.values():
        triggered = summary["triggeredCount"]
        summary["averageDeltaPerTrigger"] = (
            summary["netDeltaProfitRate"] / triggered if triggered else 0.0
        )
        summary["recommendedAction"] = _recommended_action(summary)
        summary["files"] = sorted(set(summary["files"]))
    if not payloads:
        warnings.append(f"no exit_rule_simulation*.json files found in {input_dir}")

    helped.sort(key=lambda item: float(item.get("deltaProfitRate") or 0.0), reverse=True)
    hurt.sort(key=lambda item: float(item.get("deltaProfitRate") or 0.0))
    return {
        "inputDir": str(input_dir),
        "fileCount": len(payloads),
        "dateRange": {
            "from": min(generated_dates).isoformat() if generated_dates else None,
            "to": max(generated_dates).isoformat() if generated_dates else None,
        },
        "rules": rule_totals,
        "topHelpedTrades": helped[:10],
        "topHurtTrades": hurt[:10],
        "warnings": warnings,
    }


def write_exit_rule_archive_summary(
    payload: Mapping[str, Any],
    *,
    output: Path | None = None,
    output_format: str = "json",
) -> str:
    rendered = (
        render_exit_rule_archive_summary_text(payload)
        if output_format == "text"
        else json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return rendered


def render_exit_rule_simulation_text(payload: Mapping[str, Any]) -> str:
    baseline = payload.get("baseline") or {}
    lines = [
        "Exit Rule Simulation",
        f"source: {payload.get('source', '')}",
        (
            "baseline: "
            f"completed={baseline.get('completedCount', 0)}, "
            f"avg={_pct(baseline.get('averageProfitRate'))}, "
            f"win={_pct(baseline.get('winRate'))}"
        ),
        "",
    ]
    for rule, summary in (payload.get("rules") or {}).items():
        lines.append(
            f"{rule}: triggered={summary.get('triggeredCount', 0)}, "
            f"helped={summary.get('helpedCount', 0)}, hurt={summary.get('hurtCount', 0)}, "
            f"netDelta={_pct(summary.get('netDeltaProfitRate'))}"
        )
    if payload.get("warnings"):
        lines.append("")
        lines.append("warnings:")
        lines.extend(f"- {item}" for item in payload.get("warnings") or [])
    return "\n".join(lines)


def render_exit_rule_archive_summary_text(payload: Mapping[str, Any]) -> str:
    lines = [
        "Exit Rule Simulation Archive Summary",
        SIMULATION_WARNING_TEXT,
        f"inputDir: {payload.get('inputDir', '')}",
        f"fileCount: {payload.get('fileCount', 0)}",
        "",
    ]
    for rule, summary in (payload.get("rules") or {}).items():
        lines.append(
            f"{rule}: triggered={summary.get('triggeredCount', 0)}, "
            f"helped={summary.get('helpedCount', 0)}, hurt={summary.get('hurtCount', 0)}, "
            f"netDelta={_pct(summary.get('netDeltaProfitRate'))}, "
            f"action={summary.get('recommendedAction')}"
        )
    warnings = payload.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("warnings:")
        lines.extend(f"- {item}" for item in warnings)
    return "\n".join(lines)


def _normalize_rows(rows: Iterable[Mapping[str, Any]], warnings: list[str]) -> list[EntryProfitSnapshotRow]:
    normalized: list[EntryProfitSnapshotRow] = []
    for index, raw in enumerate(rows, start=1):
        lower = {str(key).strip().lower(): value for key, value in raw.items()}
        ticker = _text(_first(lower, "ticker", "symbol"))
        if not ticker:
            warnings.append(f"row {index}: skipped missing ticker")
            continue
        snapshots = {
            minute: value
            for minute in SNAPSHOT_MINUTES
            if (value := parse_profit_rate(_first(
                lower,
                f"profit_rate_{minute}m",
                f"profit_after_{minute}m",
                f"profit_{minute}m",
            ))) is not None
        }
        normalized.append(
            EntryProfitSnapshotRow(
                trade_date=_date_text(_first(lower, "trade_date", "entry_date", "tradedate")),
                ticker=ticker.upper(),
                entry_time=_text(_first(lower, "entry_time", "entrytime")),
                snapshots=snapshots,
                final_profit_rate=parse_profit_rate(
                    _first(lower, "final_profit_rate", "actual_final_profit_rate")
                ),
                final_exit_reason=_text(_first(lower, "final_exit_reason", "actual_exit_reason")),
                strategy_version=_text(_first(lower, "strategy_version")),
                entry_reason=_text(_first(lower, "entry_reason")),
                candidate_source=_text(_first(lower, "candidate_source")),
                ranking_selection_mode=_text(_first(lower, "ranking_selection_mode")),
                order_id=_text(_first(lower, "order_id", "order_no")),
                run_id=_text(_first(lower, "run_id")),
            )
        )
    return normalized


def parse_profit_rate(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "-"}:
        return None
    is_percent = text.endswith("%")
    if is_percent:
        text = text[:-1]
    text = text.replace(",", "").replace("+", "").strip()
    if not text:
        return None
    number = float(text)
    return number / 100.0 if is_percent else number


def _rule_definitions(
    params: ExitRuleSimulationParams,
) -> dict[str, Callable[[EntryProfitSnapshotRow], _RuleOutcome]]:
    return {
        "early_negative_10m": lambda row: _single_snapshot_rule(
            row,
            params.early_negative_minutes,
            params.early_negative_threshold,
            lambda value, threshold: value < threshold,
        ),
        "early_loss_5m": lambda row: _single_snapshot_rule(
            row,
            5,
            params.early_loss_5m_threshold,
            lambda value, threshold: value <= threshold,
        ),
        "time_stop_30m_negative": lambda row: _single_snapshot_rule(
            row,
            params.time_stop_minutes,
            params.time_stop_threshold,
            lambda value, threshold: value < threshold,
        ),
        "time_stop_30m_low_profit": lambda row: _single_snapshot_rule(
            row,
            30,
            params.low_profit_30m_threshold,
            lambda value, threshold: value < threshold,
        ),
        "time_stop_60m_low_profit": lambda row: _single_snapshot_rule(
            row,
            60,
            params.low_profit_60m_threshold,
            lambda value, threshold: value < threshold,
        ),
        "profit_protection_2pct": lambda row: _profit_protection(row, params),
        "partial_take_profit_3pct": lambda row: _partial_take_profit(row, params),
    }


def _single_snapshot_rule(
    row: EntryProfitSnapshotRow,
    minute: int,
    threshold: float,
    predicate: Callable[[float, float], bool],
) -> _RuleOutcome:
    if row.final_profit_rate is None:
        return _RuleOutcome(False, None, skipped_reason="missing_final_profit_rate")
    snapshots = row.snapshot_profits()
    if minute not in snapshots:
        return _RuleOutcome(False, None, skipped_reason=f"missing_{minute}m_profit_rate")
    value = snapshots[minute]
    if predicate(value, threshold):
        return _RuleOutcome(True, value, minute)
    return _RuleOutcome(False, row.final_profit_rate)


def _profit_protection(
    row: EntryProfitSnapshotRow,
    params: ExitRuleSimulationParams,
) -> _RuleOutcome:
    if row.final_profit_rate is None:
        return _RuleOutcome(False, None, skipped_reason="missing_final_profit_rate")
    snapshots = row.snapshot_profits()
    if not snapshots:
        return _RuleOutcome(False, None, skipped_reason="missing_snapshot_profit_rate")
    trigger_minute = _first_trigger_minute(snapshots, params.profit_protection_trigger)
    if trigger_minute is None:
        return _RuleOutcome(False, row.final_profit_rate)
    simulated = max(row.final_profit_rate, params.profit_protection_floor)
    return _RuleOutcome(True, simulated, trigger_minute)


def _partial_take_profit(
    row: EntryProfitSnapshotRow,
    params: ExitRuleSimulationParams,
) -> _RuleOutcome:
    if row.final_profit_rate is None:
        return _RuleOutcome(False, None, skipped_reason="missing_final_profit_rate")
    snapshots = row.snapshot_profits()
    if not snapshots:
        return _RuleOutcome(False, None, skipped_reason="missing_snapshot_profit_rate")
    trigger_minute = _first_trigger_minute(snapshots, params.partial_take_profit_trigger)
    if trigger_minute is None:
        return _RuleOutcome(False, row.final_profit_rate)
    fraction = params.partial_take_profit_fraction
    simulated = (
        fraction * params.partial_take_profit_trigger
        + (1.0 - fraction) * row.final_profit_rate
    )
    return _RuleOutcome(True, simulated, trigger_minute)


def _first_trigger_minute(snapshots: Mapping[int, float], trigger: float) -> int | None:
    for minute in sorted(snapshots):
        if snapshots[minute] >= trigger:
            return minute
    return None


def _empty_rule_summary(rule_name: str, params: ExitRuleSimulationParams) -> dict[str, Any]:
    return {
        "rule": rule_name,
        "config": _rule_config(rule_name, params),
        "eligibleCount": 0,
        "skippedCount": 0,
        "triggeredCount": 0,
        "helpedCount": 0,
        "hurtCount": 0,
        "unchangedCount": 0,
        "netDeltaProfitRate": 0.0,
        "averageDeltaProfitRate": 0.0,
        "averageActualProfitRate": None,
        "averageSimulatedProfitRate": None,
        "winRateBefore": None,
        "winRateAfter": None,
    }


def _empty_archive_rule_summary(rule_name: str) -> dict[str, Any]:
    return {
        "rule": rule_name,
        "eligibleCount": 0,
        "triggeredCount": 0,
        "helpedCount": 0,
        "hurtCount": 0,
        "unchangedCount": 0,
        "netDeltaProfitRate": 0.0,
        "averageDeltaPerTrigger": 0.0,
        "recommendedAction": "keep_observing",
        "files": [],
    }


def _finish_rule_summary(
    summary: dict[str, Any],
    actual_rates: list[float],
    simulated_rates: list[float],
) -> None:
    eligible = int(summary["eligibleCount"])
    if not eligible:
        return
    summary["averageDeltaProfitRate"] = summary["netDeltaProfitRate"] / eligible
    summary["averageActualProfitRate"] = sum(actual_rates) / len(actual_rates)
    summary["averageSimulatedProfitRate"] = sum(simulated_rates) / len(simulated_rates)
    summary["winRateBefore"] = _win_rate(actual_rates)
    summary["winRateAfter"] = _win_rate(simulated_rates)


def _rule_config(rule_name: str, params: ExitRuleSimulationParams) -> dict[str, Any]:
    configs = {
        "early_negative_10m": {
            "minutes": params.early_negative_minutes,
            "threshold": params.early_negative_threshold,
        },
        "early_loss_5m": {"minutes": 5, "threshold": params.early_loss_5m_threshold},
        "time_stop_30m_negative": {
            "minutes": params.time_stop_minutes,
            "threshold": params.time_stop_threshold,
        },
        "time_stop_30m_low_profit": {"minutes": 30, "threshold": params.low_profit_30m_threshold},
        "time_stop_60m_low_profit": {"minutes": 60, "threshold": params.low_profit_60m_threshold},
        "profit_protection_2pct": {
            "trigger": params.profit_protection_trigger,
            "floor": params.profit_protection_floor,
        },
        "partial_take_profit_3pct": {
            "trigger": params.partial_take_profit_trigger,
            "fraction": params.partial_take_profit_fraction,
        },
    }
    return configs[rule_name]


def _detail(
    row: EntryProfitSnapshotRow,
    rule_name: str,
    outcome: _RuleOutcome,
    verdict: str,
) -> dict[str, Any]:
    final = row.final_profit_rate
    simulated = outcome.simulated_profit_rate
    delta = simulated - final if simulated is not None and final is not None else None
    payload: dict[str, Any] = {
        "tradeDate": row.trade_date,
        "entryTime": row.entry_time,
        "ticker": row.ticker,
        "rule": rule_name,
        "wouldTrigger": outcome.triggered,
        "actualFinalProfitRate": final,
        "actualExitReason": row.final_exit_reason,
        "simulatedExitMinute": outcome.simulated_exit_minute,
        "simulatedProfitRate": simulated,
        "deltaProfitRate": delta,
        "verdict": verdict,
        "snapshotProfits": {str(key): value for key, value in sorted(row.snapshot_profits().items())},
    }
    if outcome.skipped_reason:
        payload["skippedReason"] = outcome.skipped_reason
    for key, value in {
        "strategyVersion": row.strategy_version,
        "entryReason": row.entry_reason,
        "candidateSource": row.candidate_source,
        "rankingSelectionMode": row.ranking_selection_mode,
        "orderId": row.order_id,
        "runId": row.run_id,
    }.items():
        if value:
            payload[key] = value
    return payload


def _baseline_summary(rates: list[float], open_count: int) -> dict[str, Any]:
    return {
        "completedCount": len(rates),
        "openCount": open_count,
        "averageProfitRate": sum(rates) / len(rates) if rates else None,
        "medianProfitRate": median(rates) if rates else None,
        "winRate": _win_rate(rates),
        "totalProfitRate": sum(rates),
    }


def _data_scope(rows: list[EntryProfitSnapshotRow]) -> dict[str, Any]:
    dates = sorted({row.trade_date for row in rows if row.trade_date})
    tickers = sorted({row.ticker for row in rows if row.ticker})
    return {
        "inputRowCount": len(rows),
        "dateFrom": dates[0] if dates else None,
        "dateTo": dates[-1] if dates else None,
        "tickerCount": len(tickers),
        "tickers": tickers,
    }


def _recommended_action(summary: Mapping[str, Any]) -> str:
    triggered = int(summary.get("triggeredCount") or 0)
    helped = int(summary.get("helpedCount") or 0)
    hurt = int(summary.get("hurtCount") or 0)
    net_delta = float(summary.get("netDeltaProfitRate") or 0.0)
    if triggered < 10:
        return "keep_observing"
    if net_delta <= 0:
        return "reject"
    if helped <= hurt:
        return "keep_observing"
    return "candidate_for_mock_enable"


def _generated_at(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _win_rate(rates: list[float]) -> float | None:
    if not rates:
        return None
    return sum(1 for item in rates if item > 0) / len(rates)


def _verdict(delta: float) -> str:
    if delta > 0.0001:
        return "helped"
    if delta < -0.0001:
        return "hurt"
    return "unchanged"


def _pct(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value * 100:.2f}%"


def _first(row: Mapping[str, Any], *aliases: str) -> Any:
    for alias in aliases:
        if alias.lower() in row:
            return row[alias.lower()]
    return None


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return _text(value)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
