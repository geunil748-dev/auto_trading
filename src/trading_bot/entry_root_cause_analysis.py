from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from trading_bot.database import pyodbc_connect_factory


SNAPSHOT_MINUTES = (5, 10, 15, 20, 30, 60)
ANALYSIS_WARNING_TEXT = "이 분석은 원인 후보를 찾기 위한 것이며 실거래 룰 적용 근거로는 추가 표본이 필요함"
COMPLETED_SAMPLE_WARNING = "완료 거래 수가 30건 미만이므로 전략 변경 판단에는 부족합니다."
ROW_SAMPLE_WARNING = "전체 표본이 작아 그룹별 통계가 불안정할 수 있습니다."


@dataclass(frozen=True)
class CostOptions:
    commission_rate: float = 0.0
    slippage_rate: float = 0.0
    spread_cost_rate: float = 0.0

    @property
    def estimated_cost_rate(self) -> float:
        return self.commission_rate + self.slippage_rate + self.spread_cost_rate


@dataclass(frozen=True)
class EntryRootCauseRow:
    trade_date: str
    ticker: str
    entry_time: str = ""
    entry_price: float | None = None
    current_price: float | None = None
    final_profit_rate: float | None = None
    final_exit_reason: str = ""
    snapshots: dict[int, float] | None = None
    strategy_version: str = ""
    entry_reason: str = ""
    entry_reason_detail: str = ""
    candidate_source: str = ""
    ranking_selection_mode: str = ""
    order_id: str = ""
    gain_rank: int | None = None
    turnover_rank: int | None = None
    trade_value_rank: int | None = None
    ranking_presence_count: int | None = None
    opening_price_change: float | None = None
    opening_volume_ratio: float | None = None
    opening_gap: float | None = None
    selection_score: float | None = None
    chart_score: float | None = None
    news_score: float | None = None
    breakout_threshold: float | None = None
    bid_ask_spread_rate: float | None = None
    expected_fill_price_gap_rate: float | None = None

    def snapshot_profits(self) -> dict[int, float]:
        return dict(self.snapshots or {})


def load_entry_root_cause_rows_from_csv(path: Path) -> tuple[list[EntryRootCauseRow], list[str]]:
    warnings: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return _normalize_rows(rows, warnings), warnings


def load_entry_root_cause_rows_from_mssql(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    connect_factory: Callable[[], Any] | None = None,
) -> tuple[list[EntryRootCauseRow], list[str]]:
    warnings: list[str] = []
    try:
        raw_rows = _query_mssql_rows(date_from, date_to, connect_factory, include_context=True)
    except Exception as exc:
        warnings.append(f"context join query failed, entry_profit_snapshot only used ({type(exc).__name__})")
        raw_rows = _query_mssql_rows(date_from, date_to, connect_factory, include_context=False)
    return _normalize_rows(raw_rows, warnings), warnings


def analyze_entry_root_causes(
    rows: Iterable[EntryRootCauseRow],
    *,
    cost_options: CostOptions | None = None,
    entry_timezone: str = "Asia/Seoul",
    market_timezone: str = "America/New_York",
    source: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
    warnings: Iterable[str] = (),
) -> dict[str, Any]:
    costs = cost_options or CostOptions()
    row_list = list(rows)
    generated = generated_at or datetime.now(timezone.utc)
    details = [
        _detail(row, costs, entry_timezone=entry_timezone, market_timezone=market_timezone)
        for row in row_list
    ]
    data_scope = _data_scope(row_list)
    sample_warnings = _sample_warnings(len(row_list), _completed_count(row_list))
    data_scope["sampleWarning"] = " ".join(sample_warnings) if sample_warnings else ""
    output_warnings = list(warnings) + sample_warnings
    groups = {
        "byEntryTimeBucket": _group_stats(details, "entryTimeBucket"),
        "byPriceBucket": _group_stats(details, "priceBucket"),
        "byCandidateSource": _group_stats(details, "candidateSource"),
        "byRankingSelectionMode": _group_stats(details, "rankingSelectionMode"),
        "byEntryReasonTag": _entry_reason_tag_stats(details),
        "byExitReason": _group_stats(details, "finalExitReasonBucket"),
        "byEarlyBehavior": _early_behavior_stats(details),
        "byBreakoutQuality": _group_stats(details, "breakoutQualityBucket"),
        "byLiquidityQuality": _group_stats(details, "liquidityQualityBucket"),
        "byRankingPresence": _group_stats(details, "rankingPresenceBucket"),
        "byManualAuto": _group_stats(details, "manualAutoBucket"),
    }
    payload = {
        "generatedAt": generated.isoformat(),
        "source": dict(source or {}),
        "dataScope": data_scope,
        "costModel": {
            "commissionRate": costs.commission_rate,
            "slippageRate": costs.slippage_rate,
            "spreadCostRate": costs.spread_cost_rate,
            "estimatedCostRate": costs.estimated_cost_rate,
            "note": "단순 1회 왕복 비용 추정치입니다.",
        },
        "baseline": _stats(details),
        "groups": groups,
        "topLossPatterns": _top_loss_patterns(details),
        "hypotheses": _hypotheses(groups),
        "details": details,
        "warnings": output_warnings,
    }
    return payload


def write_entry_root_cause_output(
    payload: Mapping[str, Any],
    *,
    output: Path | None = None,
    output_format: str = "json",
) -> str:
    rendered = (
        render_entry_root_cause_text(payload)
        if output_format == "text"
        else json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return rendered


def summarize_entry_root_cause_archive(
    input_dir: Path,
    *,
    days: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=days) if days is not None else None
    payloads: list[tuple[Path, dict[str, Any], datetime | None]] = []
    warnings: list[str] = []
    if not input_dir.exists():
        return {
            "inputDir": str(input_dir),
            "fileCount": 0,
            "dateRange": {"from": None, "to": None},
            "repeatedLossPatterns": [],
            "warnings": [f"input directory not found: {input_dir}"],
        }
    for path in sorted(input_dir.glob("entry_root_cause*.json")):
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
    patterns = _repeated_archive_patterns(payloads)
    if not payloads:
        warnings.append(f"no entry_root_cause*.json files found in {input_dir}")
    dates = [generated for _, _, generated in payloads if generated is not None]
    return {
        "inputDir": str(input_dir),
        "fileCount": len(payloads),
        "dateRange": {
            "from": min(dates).isoformat() if dates else None,
            "to": max(dates).isoformat() if dates else None,
        },
        "repeatedLossPatterns": patterns,
        "warnings": warnings,
    }


def write_entry_root_cause_archive_summary(
    payload: Mapping[str, Any],
    *,
    output: Path | None = None,
    output_format: str = "json",
) -> str:
    rendered = (
        render_entry_root_cause_archive_text(payload)
        if output_format == "text"
        else json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return rendered


def render_entry_root_cause_text(payload: Mapping[str, Any]) -> str:
    lines = [
        "Entry Root Cause Analysis",
        ANALYSIS_WARNING_TEXT,
        "",
        _format_stats_line("baseline", payload.get("baseline") or {}),
        "",
        "진입 시간대별 성과",
        *_group_lines(payload, "byEntryTimeBucket"),
        "",
        "후보 source별 성과",
        *_group_lines(payload, "byCandidateSource"),
        "",
        "청산 사유별 성과",
        *_group_lines(payload, "byExitReason"),
        "",
        "초반 흐름별 성과",
        *_group_lines(payload, "byEarlyBehavior"),
        "",
        "Top loss patterns",
    ]
    for pattern in payload.get("topLossPatterns") or []:
        lines.append(
            f"- {pattern.get('pattern')}: count={pattern.get('count')}, "
            f"avg={_pct(pattern.get('avgFinalProfitRate'))}, "
            f"stopLoss={_pct(pattern.get('stopLossRate'))}"
        )
    warnings = payload.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("warnings")
        lines.extend(f"- {item}" for item in warnings)
    return "\n".join(lines)


def render_entry_root_cause_archive_text(payload: Mapping[str, Any]) -> str:
    lines = [
        "Entry Root Cause Archive Summary",
        f"inputDir: {payload.get('inputDir', '')}",
        f"fileCount: {payload.get('fileCount', 0)}",
        "",
    ]
    for pattern in payload.get("repeatedLossPatterns") or []:
        lines.append(
            f"- {pattern.get('group')} / {pattern.get('bucket')}: "
            f"appearances={pattern.get('appearances')}, "
            f"avg={_pct(pattern.get('avgFinalProfitRate'))}, "
            f"stopLoss={_pct(pattern.get('avgStopLossRate'))}, "
            f"recommendation={pattern.get('recommendation')}"
        )
    warnings = payload.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("warnings")
        lines.extend(f"- {item}" for item in warnings)
    return "\n".join(lines)


def _query_mssql_rows(
    date_from: date | None,
    date_to: date | None,
    connect_factory: Callable[[], Any] | None,
    *,
    include_context: bool,
) -> list[dict[str, Any]]:
    connect = connect_factory or pyodbc_connect_factory()
    params: list[Any] = []
    where = []
    if date_from is not None:
        where.append("eps.trade_date >= ?")
        params.append(date_from)
    if date_to is not None:
        where.append("eps.trade_date <= ?")
        params.append(date_to)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    if not include_context:
        sql = _entry_snapshot_sql(where_sql)
        keys = _entry_snapshot_keys()
    else:
        sql = _entry_snapshot_context_sql(where_sql)
        keys = _entry_snapshot_context_keys()
    with closing(connect()) as connection:
        rows = connection.cursor().execute(sql, tuple(params)).fetchall()
    return [dict(zip(keys, row, strict=False)) for row in rows]


def _entry_snapshot_sql(where_sql: str) -> str:
    return f"""
        SELECT eps.trade_date, eps.ticker, eps.entry_time, eps.entry_price,
               eps.profit_after_5m, eps.profit_after_10m, eps.profit_after_15m,
               eps.profit_after_20m, eps.profit_after_30m, eps.profit_after_60m,
               eps.final_exit_reason, eps.final_profit_rate, eps.strategy_version
        FROM entry_profit_snapshot eps
        {where_sql}
        ORDER BY eps.trade_date ASC, eps.entry_time ASC
    """


def _entry_snapshot_context_sql(where_sql: str) -> str:
    return f"""
        SELECT eps.trade_date, eps.ticker, eps.entry_time, eps.entry_price,
               eps.profit_after_5m, eps.profit_after_10m, eps.profit_after_15m,
               eps.profit_after_20m, eps.profit_after_30m, eps.profit_after_60m,
               eps.final_exit_reason, eps.final_profit_rate, eps.strategy_version,
               ce.evaluation_time, ce.source, ce.current_price,
               ce.price_change_percent, ce.opening_gap_percent, ce.price_rank,
               ce.volume_rank, ce.selection_score, ce.final_score,
               ce.settings_snapshot_json, ce.condition_result_json,
               ce.raw_candidate_json, ce.order_id, ce.run_id,
               th.entry_reason, th.entry_reason_detail, CAST(NULL AS NVARCHAR(128)) AS order_no,
               th.avg_fill_price, fh.fill_price, fh.fill_time,
               fh.entry_reason, fh.entry_reason_detail, fh.settings_snapshot_json
        FROM entry_profit_snapshot eps
        OUTER APPLY (
            SELECT TOP (1) *
            FROM candidate_evaluations ce
            WHERE ce.symbol = eps.ticker
              AND (ce.trading_date = eps.trade_date OR ce.trading_date IS NULL)
            ORDER BY CASE WHEN ce.buy_allowed = 1 THEN 0 ELSE 1 END,
                     ce.evaluation_time DESC, ce.id DESC
        ) ce
        OUTER APPLY (
            SELECT TOP (1) *
            FROM trade_history th
            WHERE th.trade_date = eps.trade_date
              AND th.ticker = eps.ticker
              AND th.order_type = 'BUY'
            ORDER BY th.created_at DESC, th.id DESC
        ) th
        OUTER APPLY (
            SELECT TOP (1) *
            FROM fill_history fh
            WHERE fh.trade_date = eps.trade_date
              AND fh.ticker = eps.ticker
              AND (fh.side LIKE N'%매수%' OR UPPER(fh.side) IN ('BUY', 'B'))
            ORDER BY fh.created_at DESC, fh.id DESC
        ) fh
        {where_sql}
        ORDER BY eps.trade_date ASC, eps.entry_time ASC
    """


def _entry_snapshot_keys() -> tuple[str, ...]:
    return (
        "trade_date", "ticker", "entry_time", "entry_price",
        "profit_after_5m", "profit_after_10m", "profit_after_15m",
        "profit_after_20m", "profit_after_30m", "profit_after_60m",
        "final_exit_reason", "final_profit_rate", "strategy_version",
    )


def _entry_snapshot_context_keys() -> tuple[str, ...]:
    return _entry_snapshot_keys() + (
        "evaluation_time", "source", "current_price", "price_change_percent",
        "opening_gap_percent", "price_rank", "volume_rank", "selection_score",
        "final_score", "settings_snapshot_json", "condition_result_json",
        "raw_candidate_json", "order_id", "run_id", "entry_reason",
        "entry_reason_detail", "order_no", "avg_fill_price", "fill_price",
        "fill_time", "fill_entry_reason", "fill_entry_reason_detail",
        "fill_settings_snapshot_json",
    )


def _normalize_rows(rows: Iterable[Mapping[str, Any]], warnings: list[str]) -> list[EntryRootCauseRow]:
    result: list[EntryRootCauseRow] = []
    for index, raw in enumerate(rows, start=1):
        lower = {str(key).strip().lower(): value for key, value in raw.items()}
        json_context = _json_context(lower)
        ticker = _text(_first(lower, "ticker", "symbol"))
        if not ticker:
            warnings.append(f"row {index}: skipped missing ticker")
            continue
        snapshots = {
            minute: value
            for minute in SNAPSHOT_MINUTES
            if (value := _rate(
                _first(lower, f"profit_rate_{minute}m", f"profit_{minute}m",
                       f"return_{minute}m", f"profit_after_{minute}m"),
                percent_hint=True,
                field=f"profit_{minute}m",
                warnings=warnings,
            )) is not None
        }
        entry_price = _number(_first(lower, "entry_price", "entry_price_usd", "avg_fill_price_usd", "avg_fill_price"))
        current_price = _number(_first(lower, "current_price", "current_price_usd"))
        breakout_threshold = _number(
            _first(lower, "breakout_threshold", "breakoutThreshold")
            or _context_value(json_context, "breakout_threshold", "breakoutThreshold")
        )
        gain_rank = _integer(_first(lower, "gain_rank", "price_rank"))
        turnover_rank = _integer(_first(lower, "turnover_rank", "volume_rank"))
        trade_value_rank = _integer(_context_value(json_context, "trade_value_rank", "tradeValueRank"))
        ranking_presence = _integer(
            _first(lower, "ranking_presence_count", "rankingPresenceCount")
            or _context_value(json_context, "ranking_presence_count", "rankingPresenceCount")
        )
        if ranking_presence is None:
            ranking_presence = sum(1 for item in (gain_rank, turnover_rank, trade_value_rank) if item is not None) or None
        result.append(
            EntryRootCauseRow(
                trade_date=_date_text(_first(lower, "trade_date", "entry_date", "date")),
                ticker=ticker.upper(),
                entry_time=_text(_first(lower, "entry_time", "buy_time", "filled_at", "fill_time")),
                entry_price=entry_price,
                current_price=current_price,
                final_profit_rate=_rate(
                    _first(lower, "final_profit_rate", "profit_rate", "final_return"),
                    percent_hint=True,
                    field="final_profit_rate",
                    warnings=warnings,
                ),
                final_exit_reason=_exit_reason(_first(lower, "final_exit_reason", "exit_reason")),
                snapshots=snapshots,
                strategy_version=_text(_first(lower, "strategy_version")),
                entry_reason=_text(_first(lower, "entry_reason", "fill_entry_reason"))
                or _text(_context_value(json_context, "entry_reason", "entryReason")),
                entry_reason_detail=_text(_first(lower, "entry_reason_detail", "fill_entry_reason_detail")),
                candidate_source=_source_bucket(
                    _text(_first(lower, "candidate_source", "source"))
                    or _text(_context_value(json_context, "candidate_source", "candidateSource"))
                ),
                ranking_selection_mode=_ranking_mode(
                    _text(_first(lower, "ranking_selection_mode"))
                    or _text(_context_value(json_context, "ranking_selection_mode", "rankingSelectionMode"))
                ),
                order_id=_text(_first(lower, "order_id", "order_no", "odno")),
                gain_rank=gain_rank,
                turnover_rank=turnover_rank,
                trade_value_rank=trade_value_rank,
                ranking_presence_count=ranking_presence,
                opening_price_change=_rate(
                    _first(lower, "opening_price_change", "price_change_percent"),
                    percent_hint=True,
                    field="opening_price_change",
                    warnings=warnings,
                ),
                opening_volume_ratio=_number(
                    _first(lower, "opening_volume_ratio")
                    or _context_value(json_context, "opening_volume_ratio", "openingVolumeRatio")
                ),
                opening_gap=_rate(
                    _first(lower, "opening_gap", "opening_gap_percent"),
                    percent_hint=True,
                    field="opening_gap",
                    warnings=warnings,
                ),
                selection_score=_number(_first(lower, "selection_score")),
                chart_score=_number(_context_value(json_context, "chart_score", "chartScore")),
                news_score=_number(_context_value(json_context, "news_score", "newsScore")),
                breakout_threshold=breakout_threshold,
                bid_ask_spread_rate=_rate(
                    _first(lower, "bid_ask_spread_rate")
                    or _context_value(json_context, "bid_ask_spread_rate", "bidAskSpreadRate"),
                    percent_hint=True,
                    field="bid_ask_spread_rate",
                    warnings=warnings,
                ),
                expected_fill_price_gap_rate=_rate(
                    _first(lower, "expected_fill_price_gap_rate")
                    or _context_value(json_context, "expected_fill_price_gap_rate", "expectedFillPriceGapRate"),
                    percent_hint=True,
                    field="expected_fill_price_gap_rate",
                    warnings=warnings,
                ),
            )
        )
    return result


def _json_context(row: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for field in (
        "settings_snapshot_json",
        "fill_settings_snapshot_json",
        "condition_result_json",
        "raw_candidate_json",
    ):
        parsed = _json_object(row.get(field))
        merged.update(parsed)
    return merged


def _detail(
    row: EntryRootCauseRow,
    costs: CostOptions,
    *,
    entry_timezone: str,
    market_timezone: str,
) -> dict[str, Any]:
    snapshots = row.snapshot_profits()
    final = row.final_profit_rate
    net = final - costs.estimated_cost_rate if final is not None else None
    breakout_quality = _breakout_quality_bucket(row)
    return {
        "tradeDate": row.trade_date,
        "entryTime": row.entry_time,
        "ticker": row.ticker,
        "entryTimeBucket": _entry_time_bucket(row.trade_date, row.entry_time, entry_timezone, market_timezone),
        "priceBucket": _price_bucket(row.entry_price or row.current_price),
        "candidateSource": row.candidate_source or "unknown",
        "rankingSelectionMode": row.ranking_selection_mode or "unknown",
        "manualAutoBucket": _manual_auto_bucket(row.candidate_source),
        "entryReasonTags": _entry_reason_tags(row.entry_reason),
        "finalProfitRate": final,
        "grossFinalProfitRate": final,
        "estimatedCostRate": costs.estimated_cost_rate,
        "netFinalProfitRate": net,
        "finalExitReason": row.final_exit_reason or "UNKNOWN",
        "finalExitReasonBucket": _exit_reason(row.final_exit_reason),
        "snapshotProfits": {str(key): value for key, value in sorted(snapshots.items())},
        "breakoutQualityBucket": breakout_quality,
        "liquidityQualityBucket": _liquidity_bucket(row.bid_ask_spread_rate),
        "rankingPresenceBucket": _ranking_presence_bucket(row.ranking_presence_count),
        "entryPriceVsBreakout": _entry_price_vs_breakout(row),
        "gainRank": row.gain_rank,
        "turnoverRank": row.turnover_rank,
        "tradeValueRank": row.trade_value_rank,
        "rankingPresenceCount": row.ranking_presence_count,
        "strategyVersion": row.strategy_version,
        "entryReason": row.entry_reason,
        "entryReasonDetail": row.entry_reason_detail,
    }


def _stats(details: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = list(details)
    completed = [item for item in items if isinstance(item.get("finalProfitRate"), (int, float))]
    final_rates = [float(item["finalProfitRate"]) for item in completed]
    net_rates = [float(item["netFinalProfitRate"]) for item in completed if isinstance(item.get("netFinalProfitRate"), (int, float))]
    stats = {
        "rowCount": len(items),
        "completedCount": len(completed),
        "openCount": len(items) - len(completed),
        "avgFinalProfitRate": _average(final_rates),
        "avgNetFinalProfitRate": _average(net_rates),
        "medianFinalProfitRate": median(final_rates) if final_rates else None,
        "medianNetFinalProfitRate": median(net_rates) if net_rates else None,
        "winRate": _win_rate(final_rates),
        "netWinRate": _win_rate(net_rates),
        "stopLossRate": _exit_rate(completed, "STOP_LOSS"),
        "eodRate": _exit_rate(completed, "EOD"),
        "partialTakeProfitRate": _exit_rate(completed, "PARTIAL_TAKE_PROFIT"),
        "trailingStopRate": _exit_rate(completed, "TRAILING_STOP"),
        "minFinalProfitRate": min(final_rates) if final_rates else None,
        "maxFinalProfitRate": max(final_rates) if final_rates else None,
    }
    for minute in SNAPSHOT_MINUTES:
        values = [
            float((item.get("snapshotProfits") or {}).get(str(minute)))
            for item in items
            if isinstance((item.get("snapshotProfits") or {}).get(str(minute)), (int, float))
        ]
        stats[f"avg{minute}m"] = _average(values)
        stats[f"winRate{minute}m"] = _win_rate(values)
    return stats


def _group_stats(details: list[Mapping[str, Any]], field: str) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in details:
        bucket = str(item.get(field) or "unknown")
        grouped[bucket].append(item)
    return {bucket: _stats(rows) for bucket, rows in sorted(grouped.items())}


def _entry_reason_tag_stats(details: list[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in details:
        tags = item.get("entryReasonTags") or ["unknown"]
        for tag in tags:
            grouped[str(tag)].append(item)
    return {bucket: _stats(rows) for bucket, rows in sorted(grouped.items())}


def _early_behavior_stats(details: list[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in details:
        snapshots = item.get("snapshotProfits") or {}
        for minute in (5, 10, 30, 60):
            value = snapshots.get(str(minute))
            if not isinstance(value, (int, float)):
                continue
            grouped[f"{minute}m_positive" if value >= 0 else f"{minute}m_negative"].append(item)
    return {bucket: _stats(rows) for bucket, rows in sorted(grouped.items())}


def _top_loss_patterns(details: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in details:
        if not isinstance(item.get("finalProfitRate"), (int, float)):
            continue
        if float(item["finalProfitRate"]) >= 0:
            continue
        early = _early_label(item, 10)
        pattern = f"{item.get('entryTimeBucket')} + {item.get('finalExitReasonBucket')} + {early}"
        grouped[pattern].append(item)
    patterns = []
    for pattern, rows in grouped.items():
        stats = _stats(rows)
        patterns.append({
            "pattern": pattern,
            "count": stats["completedCount"],
            "avgFinalProfitRate": stats["avgFinalProfitRate"],
            "stopLossRate": stats["stopLossRate"],
            "note": "손실 거래에서 반복된 조합입니다.",
        })
    patterns.sort(key=lambda item: (item["avgFinalProfitRate"] or 0.0, -item["count"]))
    return patterns[:10]


def _hypotheses(groups: Mapping[str, Any]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    time_groups = groups.get("byEntryTimeBucket") or {}
    weak_time = _worst_group(time_groups)
    if weak_time:
        output.append({
            "id": "H001",
            "title": "특정 진입 시간대 손실 가능성",
            "evidence": f"{weak_time[0]} 평균 수익률 {_pct(weak_time[1].get('avgFinalProfitRate'))}",
            "recommendedNextData": "동일 시간대 완료 거래 30건 이상 확보 후 재검증",
        })
    source_groups = groups.get("byCandidateSource") or {}
    weak_source = _worst_group(source_groups)
    if weak_source:
        output.append({
            "id": "H002",
            "title": "후보 source별 품질 차이 가능성",
            "evidence": f"{weak_source[0]} 평균 수익률 {_pct(weak_source[1].get('avgFinalProfitRate'))}",
            "recommendedNextData": "manual/auto/both별 주문 제출 전 조건과 체결 품질 비교",
        })
    liquidity_groups = groups.get("byLiquidityQuality") or {}
    weak_liquidity = _worst_group(liquidity_groups)
    if weak_liquidity and weak_liquidity[0] != "unknown":
        output.append({
            "id": "H003",
            "title": "스프레드/체결 비용 영향 가능성",
            "evidence": f"{weak_liquidity[0]} 평균 수익률 {_pct(weak_liquidity[1].get('avgFinalProfitRate'))}",
            "recommendedNextData": "호가 스프레드와 예상 체결 괴리율을 주문 직전 로그와 함께 누적",
        })
    return output


def _repeated_archive_patterns(payloads: list[tuple[Path, dict[str, Any], datetime | None]]) -> list[dict[str, Any]]:
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    for _path, payload, _generated in payloads:
        groups = payload.get("groups") or {}
        for group_name in ("byEntryTimeBucket", "byCandidateSource", "byExitReason", "byEarlyBehavior"):
            for bucket, stats in (groups.get(group_name) or {}).items():
                avg = stats.get("avgFinalProfitRate")
                stop = stats.get("stopLossRate")
                if not isinstance(avg, (int, float)) and not isinstance(stop, (int, float)):
                    continue
                if (avg is not None and avg < 0) or (stop is not None and stop >= 0.5):
                    item = totals.setdefault(
                        (group_name, bucket),
                        {"group": group_name, "bucket": bucket, "appearances": 0, "avg": 0.0, "stop": 0.0},
                    )
                    item["appearances"] += 1
                    item["avg"] += float(avg or 0.0)
                    item["stop"] += float(stop or 0.0)
    patterns = []
    for item in totals.values():
        appearances = item["appearances"]
        patterns.append({
            "group": item["group"],
            "bucket": item["bucket"],
            "appearances": appearances,
            "avgFinalProfitRate": item["avg"] / appearances,
            "avgStopLossRate": item["stop"] / appearances,
            "recommendation": _archive_recommendation(item["group"], item["bucket"]),
        })
    patterns.sort(key=lambda item: (-item["appearances"], item["avgFinalProfitRate"]))
    return patterns


def _archive_recommendation(group: str, bucket: str) -> str:
    if group == "byEntryTimeBucket":
        return "investigate_entry_timing"
    if group == "byCandidateSource":
        return "investigate_candidate_source"
    if group == "byEarlyBehavior":
        return "investigate_breakout_follow_through"
    return "investigate_exit_reason"


def _data_scope(rows: list[EntryRootCauseRow]) -> dict[str, Any]:
    dates = sorted({row.trade_date for row in rows if row.trade_date})
    completed = _completed_count(rows)
    return {
        "rowCount": len(rows),
        "completedCount": completed,
        "openCount": len(rows) - completed,
        "dateRange": {"from": dates[0] if dates else None, "to": dates[-1] if dates else None},
    }


def _sample_warnings(row_count: int, completed_count: int) -> list[str]:
    warnings = []
    if completed_count < 30:
        warnings.append(COMPLETED_SAMPLE_WARNING)
    if row_count < 50:
        warnings.append(ROW_SAMPLE_WARNING)
    return warnings


def _completed_count(rows: list[EntryRootCauseRow]) -> int:
    return sum(1 for row in rows if row.final_profit_rate is not None)


def _entry_time_bucket(trade_date: str, entry_time: str, entry_timezone: str, market_timezone: str) -> str:
    parsed = _entry_datetime(trade_date, entry_time, entry_timezone)
    if parsed is None:
        return "premarket_or_unknown"
    market_dt = parsed.astimezone(ZoneInfo(market_timezone))
    open_dt = datetime.combine(market_dt.date(), time(9, 30), tzinfo=ZoneInfo(market_timezone))
    close_dt = datetime.combine(market_dt.date(), time(16, 0), tzinfo=ZoneInfo(market_timezone))
    minutes = (market_dt - open_dt).total_seconds() / 60
    if market_dt < open_dt:
        return "premarket_or_unknown"
    if market_dt > close_dt:
        return "after_hours_or_unknown"
    if minutes < 15:
        return "open_0_15m"
    if minutes < 30:
        return "open_15_30m"
    if minutes < 60:
        return "open_30_60m"
    if minutes < 120:
        return "open_1_2h"
    return "open_2h_plus"


def _entry_datetime(trade_date: str, entry_time: str, entry_timezone: str) -> datetime | None:
    if not entry_time:
        return None
    zone = ZoneInfo(entry_timezone)
    text = entry_time.strip()
    try:
        if "T" in text or "-" in text:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            parsed_date = date.fromisoformat(trade_date)
            parsed_time = time.fromisoformat(text[:8])
            parsed = datetime.combine(parsed_date, parsed_time)
    except ValueError:
        return None
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed


def _price_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 5:
        return "under_5"
    if value < 10:
        return "5_10"
    if value < 20:
        return "10_20"
    if value < 50:
        return "20_50"
    if value < 100:
        return "50_100"
    return "100_plus"


def _source_bucket(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"auto", "manual_buy_list", "both", "fixed_recheck", "hybrid_recheck", "refresh_recheck"}:
        return normalized
    if "manual" in normalized and "auto" in normalized:
        return "both"
    if "manual" in normalized:
        return "manual_buy_list"
    if "auto" in normalized:
        return "auto"
    return "unknown"


def _ranking_mode(value: str) -> str:
    normalized = value.strip().lower()
    return normalized if normalized in {"intersection", "composite"} else "unknown"


def _manual_auto_bucket(source: str) -> str:
    if source == "manual_buy_list":
        return "manual only"
    if source == "auto":
        return "auto only"
    if source == "both":
        return "both"
    return "unknown"


def _exit_reason(value: Any) -> str:
    reason = _text(value).upper()
    if reason in {"STOP_LOSS", "EOD", "PARTIAL_TAKE_PROFIT", "TAKE_PROFIT", "TRAILING_STOP"}:
        return reason
    return "UNKNOWN"


def _entry_reason_tags(value: str) -> list[str]:
    tags = [item.strip().upper() for item in (value or "").split("+") if item.strip()]
    return tags or ["unknown"]


def _breakout_quality_bucket(row: EntryRootCauseRow) -> str:
    ratio = _entry_price_vs_breakout(row)
    if ratio is None:
        return "unknown"
    if ratio < 0:
        return "below_breakout"
    if ratio < 0.01:
        return "0_1pct_above_breakout"
    if ratio < 0.03:
        return "1_3pct_above_breakout"
    return "3pct_plus_above_breakout"


def _entry_price_vs_breakout(row: EntryRootCauseRow) -> float | None:
    price = row.entry_price or row.current_price
    if price is None or row.breakout_threshold is None or row.breakout_threshold <= 0:
        return None
    return price / row.breakout_threshold - 1.0


def _liquidity_bucket(spread_rate: float | None) -> str:
    if spread_rate is None:
        return "unknown"
    if spread_rate < 0.003:
        return "spread_under_0_3pct"
    if spread_rate < 0.01:
        return "spread_0_3_to_1pct"
    return "spread_1pct_plus"


def _ranking_presence_bucket(value: int | None) -> str:
    if value == 3:
        return "presence_3"
    if value == 2:
        return "presence_2"
    if value == 1:
        return "presence_1"
    return "unknown"


def _early_label(item: Mapping[str, Any], minute: int) -> str:
    value = (item.get("snapshotProfits") or {}).get(str(minute))
    if not isinstance(value, (int, float)):
        return f"{minute}m_unknown"
    return f"{minute}m_positive" if value >= 0 else f"{minute}m_negative"


def _exit_rate(details: list[Mapping[str, Any]], reason: str) -> float | None:
    if not details:
        return None
    return sum(1 for item in details if item.get("finalExitReasonBucket") == reason) / len(details)


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _win_rate(values: list[float]) -> float | None:
    return sum(1 for value in values if value > 0) / len(values) if values else None


def _worst_group(groups: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]] | None:
    candidates = [
        (name, stats)
        for name, stats in groups.items()
        if isinstance(stats.get("avgFinalProfitRate"), (int, float))
        and int(stats.get("completedCount") or 0) > 0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda pair: float(pair[1].get("avgFinalProfitRate") or 0.0))


def _format_stats_line(name: str, stats: Mapping[str, Any]) -> str:
    return (
        f"{name}: rows={stats.get('rowCount', 0)}, completed={stats.get('completedCount', 0)}, "
        f"avg={_pct(stats.get('avgFinalProfitRate'))}, netAvg={_pct(stats.get('avgNetFinalProfitRate'))}, "
        f"win={_pct(stats.get('winRate'))}, stopLoss={_pct(stats.get('stopLossRate'))}"
    )


def _group_lines(payload: Mapping[str, Any], group_name: str) -> list[str]:
    groups = ((payload.get("groups") or {}).get(group_name) or {})
    return [f"- {_format_stats_line(name, stats)}" for name, stats in groups.items()] or ["- none"]


def _pct(value: Any) -> str:
    return "n/a" if not isinstance(value, (int, float)) else f"{value * 100:.2f}%"


def _json_object(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _context_value(context: Mapping[str, Any], *aliases: str) -> Any:
    lowered = {str(key).lower(): value for key, value in context.items()}
    for alias in aliases:
        if alias in context:
            return context[alias]
        value = lowered.get(alias.lower())
        if value is not None:
            return value
    return None


def _first(row: Mapping[str, Any], *aliases: str) -> Any:
    for alias in aliases:
        value = row.get(alias.lower())
        if value is not None:
            return value
    return None


def _rate(value: Any, *, percent_hint: bool, field: str, warnings: list[str]) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if not text or text.lower() in {"none", "null", "nan", "-"}:
            return None
        has_percent = text.endswith("%")
        text = text.rstrip("%").replace(",", "").replace("+", "").strip()
        try:
            number = float(text)
        except ValueError:
            warnings.append(f"{field}: could not parse rate value {value!r}")
            return None
        if has_percent:
            return number / 100.0
    if percent_hint and abs(number) > 1:
        warnings.append(f"{field}: interpreted {number:g} as percent")
        return number / 100.0
    return number


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


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


def _generated_at(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
