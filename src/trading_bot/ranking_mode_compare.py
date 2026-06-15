from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from trading_bot.adapters.breakout_history import KisBreakoutHistory
from trading_bot.adapters.chart_history import YahooChartScorer
from trading_bot.adapters.context import YahooMarketContextSource
from trading_bot.adapters.kis_account import KisAccountReader
from trading_bot.adapters.kis_http import KisJsonClient
from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.adapters.market_data import KisDailyVolumeHistory, KisScreeningMarketData
from trading_bot.adapters.news_sentiment import YahooNewsSentimentSource
from trading_bot.adapters.scoring import NewsChartScoringProvider
from trading_bot.adapters.yahoo_news import YahooFinanceNewsSource
from trading_bot.clocks import SystemClock
from trading_bot.config import (
    RANKING_SELECTION_COMPOSITE,
    RANKING_SELECTION_INTERSECTION,
    KisSettings,
    TradingSettings,
)
from trading_bot.in_memory import InMemoryDailyRepository
from trading_bot.manual_buy_list import FileManualBuyListSource
from trading_bot.models import (
    BotLog,
    CandidateEvaluation,
    DailyScore,
    DailyTarget,
    RankedStock,
    ScoreRecord,
)
from trading_bot.pipeline import ScoringRun, ScreeningScoringPipeline
from trading_bot.runtime import DryRunResult, DryRunRuntime
from trading_bot.sentiment import KeywordHeadlineSentiment

RuntimeFactory = Callable[[TradingSettings, KisSettings], tuple[DryRunRuntime, object]]
RANKING_SOURCE_ORDER = ("gainers", "turnover", "trade_value")


def compare_ranking_modes(
    settings: TradingSettings,
    kis_settings: KisSettings,
    *,
    runtime_factory: RuntimeFactory | None = None,
    include_manual: bool = False,
) -> dict[str, Any]:
    factory = runtime_factory or (
        lambda mode_settings, mode_kis_settings: build_read_only_live_dry_run(
            mode_settings,
            mode_kis_settings,
            include_manual=include_manual,
        )
    )
    intersection = _run_mode(factory, settings, kis_settings, RANKING_SELECTION_INTERSECTION)
    composite = _run_mode(factory, settings, kis_settings, RANKING_SELECTION_COMPOSITE)
    return _compare_payload(intersection, composite)


def write_compare_payload(payload: dict[str, Any], output: Path | None) -> None:
    if output is None:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_json_file(output, payload)


def archive_compare_payload(
    payload: dict[str, Any],
    archive_dir: Path | None,
) -> Path | None:
    if archive_dir is None:
        return None
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        path = _archive_path(archive_dir, payload)
        _write_json_file(path, payload)
        return path
    except Exception as exc:
        warning = f"archive_write_failed:{type(exc).__name__}"
        _payload_warnings(payload)["archive"] = warning
        print(warning, file=sys.stderr)
        return None


def summarize_ranking_mode_archive(
    archive_dir: Path,
    *,
    days: int | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    rows = _load_archive_rows(archive_dir, days=days, warnings=warnings)
    generated_at = [_parse_datetime(row.get("generatedAt")) for row in rows]
    generated_at = [item for item in generated_at if item is not None]
    return {
        "archiveDir": str(archive_dir),
        "fileCount": len(rows),
        "dateRange": {
            "from": min(generated_at).isoformat() if generated_at else None,
            "to": max(generated_at).isoformat() if generated_at else None,
        },
        "summary": _archive_summary(rows),
        "topCompositeOnlySelectedTickers": _top_composite_only(rows, "selected"),
        "topCompositeOnlyBuyIntentTickers": _top_composite_only(rows, "buyIntentTickers"),
        "warnings": warnings,
    }


def format_ranking_mode_archive_summary(summary: dict[str, Any]) -> str:
    metrics = summary.get("summary", {})
    date_range = summary.get("dateRange", {})
    lines = [
        "Ranking mode archive summary",
        f"Files: {summary.get('fileCount', 0)}",
        f"Date range: {date_range.get('from') or '-'} to {date_range.get('to') or '-'}",
        (
            "Average targets: "
            f"intersection={metrics.get('avgIntersectionTargetCount', 0)} "
            f"composite={metrics.get('avgCompositeTargetCount', 0)}"
        ),
        (
            "Average selected: "
            f"intersection={metrics.get('avgIntersectionSelectedCount', 0)} "
            f"composite={metrics.get('avgCompositeSelectedCount', 0)}"
        ),
        (
            "Average buy intents: "
            f"intersection={metrics.get('avgIntersectionBuyIntentCount', 0)} "
            f"composite={metrics.get('avgCompositeBuyIntentCount', 0)}"
        ),
        "Top composite-only selected tickers:",
        *_top_lines(summary.get("topCompositeOnlySelectedTickers", [])),
        "Top composite-only buy-intent tickers:",
        *_top_lines(summary.get("topCompositeOnlyBuyIntentTickers", [])),
        (
            "Note: this summary is for candidate comparison only and is not "
            "real-trading performance validation."
        ),
    ]
    warnings = summary.get("warnings") or []
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in warnings)
    return "\n".join(lines)


def build_read_only_live_dry_run(
    settings: TradingSettings,
    kis_settings: KisSettings,
    *,
    include_manual: bool = False,
) -> tuple[DryRunRuntime, InMemoryDailyRepository]:
    kis = KisOverseasClient(KisJsonClient(kis_settings))
    accounts = KisAccountReader(kis, kis_settings)
    repository = InMemoryDailyRepository()
    scoring = NewsChartScoringProvider(
        YahooNewsSentimentSource(
            YahooFinanceNewsSource(),
            KeywordHeadlineSentiment(),
            cache=None,
            cache_ttl_minutes=settings.news_cache_ttl_minutes,
        ).sentiments,
        YahooChartScorer().score,
    )
    market_data = RankTrackingScreeningMarketData(
        kis,
        YahooMarketContextSource(),
        KisDailyVolumeHistory(kis),
        on_snapshot_error=_snapshot_error_logger(repository),
    )
    repository.ranking_rank_maps = market_data.ranking_rank_maps
    pipeline = ScreeningScoringPipeline(
        market_data,
        scoring,
        accounts,
        repository,
        SystemClock(),
        settings,
        manual_source=(
            FileManualBuyListSource(
                settings.manual_buy_list_path,
                enabled=settings.manual_buy_list_enabled,
                max_tickers=settings.max_manual_buy_tickers,
            )
            if include_manual
            else None
        ),
    )
    return (
        DryRunRuntime(pipeline, accounts, KisBreakoutHistory(kis), settings),
        repository,
    )


def _run_mode(
    factory: RuntimeFactory,
    settings: TradingSettings,
    kis_settings: KisSettings,
    mode: str,
) -> dict[str, Any]:
    mode_settings = replace(settings, ranking_selection_mode=mode)
    runtime, repository = factory(mode_settings, kis_settings)
    result = runtime.run()
    return {
        "mode": mode,
        "result": result,
        "repository": repository,
        "rankMaps": _ranking_rank_maps(repository),
        "rankingFailures": _ranking_failures(repository),
    }


def _compare_payload(
    intersection: dict[str, Any],
    composite: dict[str, Any],
) -> dict[str, Any]:
    intersection_payload = _mode_payload(intersection)
    composite_payload = _mode_payload(composite)
    trade_date = (
        intersection["result"].scoring.trade_date
        or composite["result"].scoring.trade_date
    )
    diff = _diff_payload(intersection_payload, composite_payload)
    return {
        "tradeDate": trade_date.isoformat(),
        "generatedAt": datetime.now(UTC).isoformat(),
        "intersection": intersection_payload,
        "composite": composite_payload,
        "diff": diff,
        "summary": {
            "intersectionTargetCount": len(intersection_payload["targets"]),
            "compositeTargetCount": len(composite_payload["targets"]),
            "intersectionSelectedCount": len(intersection_payload["selected"]),
            "compositeSelectedCount": len(composite_payload["selected"]),
            "intersectionBuyIntentCount": len(intersection_payload["buyIntentTickers"]),
            "compositeBuyIntentCount": len(composite_payload["buyIntentTickers"]),
        },
        "warnings": {
            "snapshot": (
                "Ranking mode comparison runs each mode sequentially. Live prices may "
                "move between runs, so this is a near-same-time comparison rather than "
                "a perfectly identical snapshot."
            )
        },
    }


def _mode_payload(run: dict[str, Any]) -> dict[str, Any]:
    result: DryRunResult = run["result"]
    repository = run["repository"]
    rank_maps = run["rankMaps"]
    scores = {item.score.ticker: item.score for item in result.scoring.scores}
    evaluations = _latest_evaluations(repository)
    target_payloads = [
        _target_payload(item, scores.get(item.candidate.ticker), evaluations, rank_maps)
        for item in result.scoring.targets
    ]
    target_by_ticker = {item["ticker"]: item for item in target_payloads}
    return {
        "targets": target_payloads,
        "selected": [
            _score_payload(
                item,
                evaluations.get(item.ticker),
                target_by_ticker.get(item.ticker),
                rank_maps,
            )
            for item in result.scoring.selected
        ],
        "buyIntentTickers": [item.ticker for item in result.buy_intents],
        "blockedReason": result.scoring.blocked_reason,
        "rankDiagnostics": _rank_diagnostics(rank_maps),
        "rankingFailures": run["rankingFailures"],
    }


def _target_payload(
    target: DailyTarget,
    score: ScoreRecord | None,
    evaluations: dict[str, CandidateEvaluation],
    rank_maps: Mapping[str, Mapping[str, int]],
) -> dict[str, Any]:
    candidate = target.candidate
    evaluation = evaluations.get(candidate.ticker)
    rank_payload = _rank_payload(candidate.ticker, rank_maps)
    payload = {
        "ticker": candidate.ticker,
        "name": candidate.name,
        "price_usd": candidate.price_usd,
        "opening_price_change": candidate.opening_price_change,
        "opening_volume_ratio": candidate.opening_volume_ratio,
        "gain_rank": rank_payload["gain_rank"] or candidate.gain_rank,
        "turnover_rank": rank_payload["turnover_rank"] or candidate.turnover_rank,
        "trade_value_rank": rank_payload["trade_value_rank"],
        "ranking_presence_count": rank_payload["ranking_presence_count"],
        "ranking_sources": rank_payload["ranking_sources"],
        "total_score": score.total_score if score is not None else None,
        "chart_score": score.chart_score if score is not None else None,
        "news_score": score.news_score if score is not None else None,
        "buy_block_reason": _evaluation_reason(evaluation),
        "blocked_reason": _evaluation_reason(evaluation),
    }
    if evaluation is not None and evaluation.current_price is not None:
        payload["price_usd"] = evaluation.current_price
    return payload


def _score_payload(
    score: ScoreRecord,
    evaluation: CandidateEvaluation | None,
    target: dict[str, Any] | None,
    rank_maps: Mapping[str, Mapping[str, int]],
) -> dict[str, Any]:
    base = dict(target or {})
    rank_payload = _rank_payload(score.ticker, rank_maps)
    base.update({
        "ticker": score.ticker,
        "gain_rank": rank_payload["gain_rank"] or base.get("gain_rank"),
        "turnover_rank": rank_payload["turnover_rank"] or base.get("turnover_rank"),
        "trade_value_rank": rank_payload["trade_value_rank"],
        "ranking_presence_count": rank_payload["ranking_presence_count"],
        "ranking_sources": rank_payload["ranking_sources"],
        "total_score": score.total_score,
        "chart_score": score.chart_score,
        "news_score": score.news_score,
        "buy_block_reason": _evaluation_reason(evaluation),
        "blocked_reason": _evaluation_reason(evaluation),
    })
    if evaluation is not None:
        base["name"] = evaluation.symbol_name or base.get("name", "")
        base["price_usd"] = evaluation.current_price or base.get("price_usd")
        base["gain_rank"] = rank_payload["gain_rank"] or evaluation.price_rank or base.get("gain_rank")
        base["turnover_rank"] = (
            rank_payload["turnover_rank"] or evaluation.volume_rank or base.get("turnover_rank")
        )
    return base


class RankTrackingScreeningMarketData(KisScreeningMarketData):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.ranking_rank_maps: dict[str, dict[str, int]] = {
            "gainers": {},
            "turnover": {},
            "trade_value": {},
        }

    def ranked_gainers(self, limit: int | None = None) -> list[RankedStock]:
        rows = super().ranked_gainers(limit)
        self.ranking_rank_maps["gainers"] = _rank_map(rows)
        return rows

    def ranked_turnover(self, limit: int | None = None) -> list[RankedStock]:
        rows = super().ranked_turnover(limit)
        self.ranking_rank_maps["turnover"] = _rank_map(rows)
        return rows

    def ranked_trade_value(self, limit: int | None = None) -> list[RankedStock]:
        rows = super().ranked_trade_value(limit)
        self.ranking_rank_maps["trade_value"] = _rank_map(rows)
        return rows


def _rank_map(rows: list[RankedStock]) -> dict[str, int]:
    return {item.ticker: item.rank for item in rows}


def _rank_payload(ticker: str, rank_maps: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
    sources = [source for source in RANKING_SOURCE_ORDER if ticker in rank_maps.get(source, {})]
    return {
        "gain_rank": rank_maps.get("gainers", {}).get(ticker),
        "turnover_rank": rank_maps.get("turnover", {}).get(ticker),
        "trade_value_rank": rank_maps.get("trade_value", {}).get(ticker),
        "ranking_presence_count": len(sources),
        "ranking_sources": sources,
    }


def _rank_diagnostics(rank_maps: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
    union = set().union(*(set(rank_maps.get(source, {})) for source in RANKING_SOURCE_ORDER))
    return {
        "gainersCount": len(rank_maps.get("gainers", {})),
        "turnoverCount": len(rank_maps.get("turnover", {})),
        "tradeValueCount": len(rank_maps.get("trade_value", {})),
        "rankingUnionCount": len(union),
    }


def _ranking_rank_maps(repository: object) -> dict[str, dict[str, int]]:
    raw = getattr(repository, "ranking_rank_maps", None)
    if not isinstance(raw, Mapping):
        return {source: {} for source in RANKING_SOURCE_ORDER}
    return {
        source: dict(raw.get(source, {}))
        for source in RANKING_SOURCE_ORDER
    }


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _archive_path(archive_dir: Path, payload: dict[str, Any]) -> Path:
    timestamp = _archive_timestamp(payload)
    path = archive_dir / f"ranking_mode_compare_{timestamp}.json"
    if not path.exists():
        return path
    for index in range(1, 100):
        candidate = archive_dir / f"ranking_mode_compare_{timestamp}_{index:02d}.json"
        if not candidate.exists():
            return candidate
    return archive_dir / f"ranking_mode_compare_{timestamp}_{datetime.now(UTC).microsecond}.json"


def _archive_timestamp(payload: dict[str, Any]) -> str:
    generated_at = _parse_datetime(payload.get("generatedAt"))
    if generated_at is None:
        generated_at = datetime.now(UTC)
    return generated_at.astimezone(UTC).strftime("%Y%m%d_%H%M%S")


def _payload_warnings(payload: dict[str, Any]) -> dict[str, Any]:
    warnings = payload.get("warnings")
    if not isinstance(warnings, dict):
        warnings = {}
        payload["warnings"] = warnings
    return warnings


def _load_archive_rows(
    archive_dir: Path,
    *,
    days: int | None,
    warnings: list[str],
) -> list[dict[str, Any]]:
    if not archive_dir.exists():
        return []
    cutoff = None
    if days is not None and days > 0:
        cutoff = datetime.now(UTC) - timedelta(days=days)
    rows: list[dict[str, Any]] = []
    for path in sorted(archive_dir.glob("ranking_mode_compare_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            warnings.append(f"{path.name}:read_failed:{type(exc).__name__}")
            continue
        if not isinstance(payload, dict):
            warnings.append(f"{path.name}:invalid_payload")
            continue
        generated_at = _parse_datetime(payload.get("generatedAt"))
        if cutoff is not None and generated_at is not None and generated_at < cutoff:
            continue
        rows.append(payload)
    return rows


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _archive_summary(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    composite_only_selected = set()
    intersection_only_selected = set()
    composite_only_intents = set()
    intersection_only_intents = set()
    for row in rows:
        diff = row.get("diff") if isinstance(row.get("diff"), dict) else {}
        composite_only_selected.update(diff.get("selectedOnlyInComposite") or [])
        intersection_only_selected.update(diff.get("selectedOnlyInIntersection") or [])
        composite_only_intents.update(diff.get("buyIntentsOnlyInComposite") or [])
        intersection_only_intents.update(diff.get("buyIntentsOnlyInIntersection") or [])
    return {
        "avgIntersectionTargetCount": _avg_summary(rows, "intersectionTargetCount"),
        "avgCompositeTargetCount": _avg_summary(rows, "compositeTargetCount"),
        "avgIntersectionSelectedCount": _avg_summary(rows, "intersectionSelectedCount"),
        "avgCompositeSelectedCount": _avg_summary(rows, "compositeSelectedCount"),
        "avgIntersectionBuyIntentCount": _avg_summary(rows, "intersectionBuyIntentCount"),
        "avgCompositeBuyIntentCount": _avg_summary(rows, "compositeBuyIntentCount"),
        "compositeOnlySelectedTickerCount": len(composite_only_selected),
        "intersectionOnlySelectedTickerCount": len(intersection_only_selected),
        "compositeOnlyBuyIntentTickerCount": len(composite_only_intents),
        "intersectionOnlyBuyIntentTickerCount": len(intersection_only_intents),
    }


def _avg_summary(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0
    total = 0.0
    for row in rows:
        summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        total += float(summary.get(key) or 0)
    return total / len(rows)


def _top_composite_only(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    diff_key = {
        "selected": "selectedOnlyInComposite",
        "buyIntentTickers": "buyIntentsOnlyInComposite",
    }[field]
    counts: Counter[str] = Counter()
    presence_sum: defaultdict[str, int] = defaultdict(int)
    source_sets: defaultdict[str, set[str]] = defaultdict(set)
    for row in rows:
        diff = row.get("diff") if isinstance(row.get("diff"), dict) else {}
        tickers = [str(ticker) for ticker in diff.get(diff_key) or []]
        composite = row.get("composite") if isinstance(row.get("composite"), dict) else {}
        for ticker in tickers:
            counts[ticker] += 1
            detail = _ticker_detail(composite, ticker)
            presence_sum[ticker] += int(detail.get("ranking_presence_count") or 0)
            source_sets[ticker].update(str(source) for source in detail.get("ranking_sources") or [])
    result = []
    for ticker, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        sources = [source for source in RANKING_SOURCE_ORDER if source in source_sets[ticker]]
        result.append({
            "ticker": ticker,
            "count": count,
            "avgRankingPresenceCount": presence_sum[ticker] / count if count else 0,
            "sources": sources,
        })
    return result


def _ticker_detail(mode_payload: Mapping[str, Any], ticker: str) -> Mapping[str, Any]:
    for key in ("selected", "targets"):
        rows = mode_payload.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, Mapping) and row.get("ticker") == ticker:
                return row
    return {}


def _top_lines(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["- none"]
    return [
        (
            f"- {row.get('ticker')}: count={row.get('count')} "
            f"avgPresence={row.get('avgRankingPresenceCount')} "
            f"sources={','.join(row.get('sources') or []) or '-'}"
        )
        for row in rows[:10]
    ]


def _diff_payload(
    intersection: dict[str, Any],
    composite: dict[str, Any],
) -> dict[str, list[str]]:
    intersection_targets = _tickers(intersection["targets"])
    composite_targets = _tickers(composite["targets"])
    intersection_selected = _tickers(intersection["selected"])
    composite_selected = _tickers(composite["selected"])
    intersection_intents = set(intersection["buyIntentTickers"])
    composite_intents = set(composite["buyIntentTickers"])
    return {
        "targetsOnlyInIntersection": sorted(intersection_targets - composite_targets),
        "targetsOnlyInComposite": sorted(composite_targets - intersection_targets),
        "selectedOnlyInIntersection": sorted(intersection_selected - composite_selected),
        "selectedOnlyInComposite": sorted(composite_selected - intersection_selected),
        "buyIntentsOnlyInIntersection": sorted(intersection_intents - composite_intents),
        "buyIntentsOnlyInComposite": sorted(composite_intents - intersection_intents),
    }


def _tickers(rows: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("ticker", "")) for item in rows if item.get("ticker")}


def _latest_evaluations(repository: object) -> dict[str, CandidateEvaluation]:
    rows = getattr(repository, "candidate_evaluations", ())
    latest: dict[str, CandidateEvaluation] = {}
    for item in rows:
        latest[item.symbol] = item
    return latest


def _evaluation_reason(evaluation: CandidateEvaluation | None) -> str | None:
    if evaluation is None:
        return None
    return evaluation.buy_block_reason or evaluation.final_decision


def _ranking_failures(repository: object) -> list[dict[str, str]]:
    failures = []
    for log in getattr(repository, "logs", ()):
        if isinstance(log, BotLog) and log.reject_reason == "RANKING_FETCH_FAILED":
            failures.append({
                "level": log.level,
                "module": log.module,
                "message": log.message,
                "reason": log.reject_reason,
            })
    return failures


def _snapshot_error_logger(repository: InMemoryDailyRepository):
    def log_missing_snapshot(ticker: str, reason: str) -> None:
        repository.save_log(
            BotLog(
                "WARNING",
                "screening",
                f"[MISSING_SNAPSHOT] ticker={ticker} reason={reason}",
                symbol=ticker,
                reject_reason="MISSING_SNAPSHOT",
            )
        )

    return log_missing_snapshot
