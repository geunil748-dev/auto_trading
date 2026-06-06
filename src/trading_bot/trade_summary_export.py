from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from trading_bot.trading_date import current_trade_date

DEFAULT_TRADE_SUMMARY_OUTPUT_DIR = Path("monitor/reports")
ENTRY_PROFIT_SAMPLE_MINIMUM = 30
EXIT_REASON_ORDER = (
    "STOP_LOSS",
    "TAKE_PROFIT",
    "TRAILING_STOP",
    "PARTIAL_TAKE_PROFIT",
    "EOD",
)
SENSITIVE_PATTERNS = (
    (re.compile(r"(?i)\bBearer\s+[^\s,;]+"), "Bearer [REDACTED]"),
    (
        re.compile(
            r"(?i)\b([A-Z_]*(TOKEN|SECRET|PASSWORD|API_KEY|APP_KEY|"
            r"ACCOUNT_NO|DB_PASSWORD|MSSQL_PASSWORD)[A-Z_]*)\s*[:=]\s*[^\s,;]+"
        ),
        r"\1=[REDACTED]",
    ),
    (re.compile(r"(?i)\bauthorization\s*[:=]\s*[^\s,;]+"), "authorization=[REDACTED]"),
)


class TradeSummaryDataSource(Protocol):
    def account_summary(self, trade_date: date, is_mock: bool) -> tuple[Any, ...] | None: ...

    def run_summary(self, trade_date: date, is_mock: bool) -> tuple[Any, ...] | None: ...

    def fill_rows(self, trade_date: date, is_mock: bool) -> list[tuple[Any, ...]]: ...

    def trade_rows(self, trade_date: date, is_mock: bool) -> list[tuple[Any, ...]]: ...

    def entry_profit_snapshots(self, trade_date: date) -> list[tuple[Any, ...]]: ...

    def candidate_counts(self, trade_date: date) -> tuple[Any, ...]: ...

    def log_rows(self, trade_date: date) -> list[tuple[Any, ...]]: ...


@dataclass(frozen=True)
class TradeSummaryExportResult:
    trade_date: date
    mode: str
    path: Path


class SqlTradeSummaryDataSource:
    def __init__(self, connect: Callable[[], Any]) -> None:
        self.connect = connect

    def account_summary(self, trade_date: date, is_mock: bool) -> tuple[Any, ...] | None:
        rows = self._query(
            """
            SELECT TOP (1) cash_usd, equity_usd, invested_usd, open_positions,
                   daily_profit_rate, realized_profit_usd
            FROM account_snapshot
            WHERE trade_date = ?
              AND is_mock = ?
            ORDER BY created_at DESC, id DESC
            """,
            (trade_date, is_mock),
        )
        return rows[0] if rows else None

    def run_summary(self, trade_date: date, is_mock: bool) -> tuple[Any, ...] | None:
        rows = self._query(
            """
            SELECT TOP (1) strategy_version, settings_snapshot_hash,
                   realized_profit_usd, realized_profit_rate
            FROM daily_run_summary
            WHERE trade_date = ?
              AND is_mock = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (trade_date, is_mock),
        )
        return rows[0] if rows else None

    def fill_rows(self, trade_date: date, is_mock: bool) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT TOP (200) fill_date, fill_time, ticker, ticker_name, side,
                   quantity, fill_price, fill_amount, profit_usd, profit_rate,
                   entry_reason, entry_reason_detail, strategy_version,
                   settings_snapshot_hash
            FROM fill_history
            WHERE trade_date = ?
              AND is_mock = ?
            ORDER BY fill_date ASC, fill_time ASC, created_at ASC, id ASC
            """,
            (trade_date, is_mock),
        )

    def trade_rows(self, trade_date: date, is_mock: bool) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT TOP (200) trade_date, created_at, ticker, ticker_name,
                   order_type, order_price, quantity, exit_reason,
                   profit_usd, profit_rate, entry_reason, entry_reason_detail,
                   strategy_version, settings_snapshot_hash
            FROM trade_history
            WHERE trade_date = ?
              AND is_mock = ?
            ORDER BY created_at ASC, id ASC
            """,
            (trade_date, is_mock),
        )

    def entry_profit_snapshots(self, trade_date: date) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT TOP (500) ticker, ticker_name, profit_after_5m,
                   profit_after_10m, profit_after_15m, profit_after_20m,
                   profit_after_30m, final_exit_reason, final_profit_rate,
                   strategy_version
            FROM entry_profit_snapshot
            WHERE trade_date = ?
            ORDER BY entry_time ASC, id ASC
            """,
            (trade_date,),
        )

    def candidate_counts(self, trade_date: date) -> tuple[Any, ...]:
        rows = self._query(
            """
            SELECT
                (SELECT COUNT(DISTINCT ticker) FROM daily_target WHERE trade_date = ?),
                (SELECT COUNT(DISTINCT ticker) FROM scoring WHERE trade_date = ?),
                (
                    SELECT COUNT(DISTINCT ticker)
                    FROM scoring
                    WHERE trade_date = ?
                      AND is_selected = 1
                )
            """,
            (trade_date, trade_date, trade_date),
        )
        return rows[0] if rows else (0, 0, 0)

    def log_rows(self, trade_date: date) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT created_at, log_level, module, message, reject_reason, symbol,
                   actual_value, threshold_value
            FROM bot_log
            WHERE trade_date = ?
            ORDER BY created_at ASC, id ASC
            """,
            (trade_date,),
        )

    def _query(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        with closing(self.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(sql, params)
            return list(cursor.fetchall())


def export_trade_summary(
    trade_date: date | None = None,
    mode: str = "mock",
    output_dir: Path | str = DEFAULT_TRADE_SUMMARY_OUTPUT_DIR,
    data_source: TradeSummaryDataSource | None = None,
    generated_at: datetime | None = None,
) -> TradeSummaryExportResult:
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"mock", "real"}:
        raise ValueError("mode must be mock or real")
    target_date = trade_date or current_trade_date()
    source = data_source or _default_data_source()
    generated_time = generated_at or datetime.now().astimezone()
    content = render_trade_summary(
        source,
        target_date,
        normalized_mode,
        generated_time,
    )
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{target_date.isoformat()}_{normalized_mode}_trade_summary.txt"
    path.write_text(content, encoding="utf-8")
    return TradeSummaryExportResult(target_date, normalized_mode, path)


def render_trade_summary(
    data_source: TradeSummaryDataSource,
    trade_date: date,
    mode: str,
    generated_at: datetime,
) -> str:
    is_mock = mode == "mock"
    account = data_source.account_summary(trade_date, is_mock)
    run_summary = data_source.run_summary(trade_date, is_mock)
    fills = data_source.fill_rows(trade_date, is_mock)
    trades = data_source.trade_rows(trade_date, is_mock)
    snapshots = data_source.entry_profit_snapshots(trade_date)
    candidate_counts = data_source.candidate_counts(trade_date)
    logs = data_source.log_rows(trade_date)

    fill_lines, fill_stats, exit_stats, strategy_stats = _fill_sections(fills, trades)
    strategy_version = _first_text(
        _value(run_summary, 0),
        *(str(_value(row, 12, "")) for row in fills),
        *(str(_value(row, 12, "")) for row in trades),
        *(str(_value(row, 9, "")) for row in snapshots),
    )
    settings_hash = _first_text(
        _value(run_summary, 1),
        *(str(_value(row, 13, "")) for row in fills),
        *(str(_value(row, 13, "")) for row in trades),
    )
    candidate_section = _candidate_section(candidate_counts, logs)
    log_section = _log_section(logs)

    lines = [
        "# 일일 체결 요약",
        "",
        "## 1. 기본 정보",
        f"- 기준일: {trade_date.isoformat()}",
        f"- 모드: {mode}",
        f"- 생성시각: {generated_at.isoformat(timespec='seconds')}",
        f"- strategy_version: {strategy_version or '-'}",
        f"- settings_snapshot_hash: {settings_hash or '-'}",
        "",
        "## 2. 계좌 요약",
        *_account_lines(account, _number(_value(run_summary, 2))),
        "",
        "## 3. 체결 요약",
        *fill_stats,
        "",
        "## 4. 최근 체결 목록",
        *fill_lines,
        "",
        "## 5. 청산 사유별 요약",
        *_stats_table(exit_stats, key_title="청산 사유"),
        "",
        "## 6. 전략 버전별 요약",
        *_stats_table(strategy_stats, key_title="전략 버전"),
        "",
        "## 7. 진입 후 수익률 스냅샷 요약",
        *_entry_profit_snapshot_lines(snapshots),
        "",
        "## 8. 후보/선정 요약",
        *candidate_section,
        "",
        "## 9. 로그 요약",
        *log_section,
        "",
    ]
    return "\n".join(lines)


def _fill_sections(
    fills: list[tuple[Any, ...]],
    trades: list[tuple[Any, ...]],
) -> tuple[list[str], list[str], dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    exit_reasons = _sell_exit_reasons(trades)
    enriched: list[tuple[tuple[Any, ...], str]] = []
    for row in fills:
        exit_reason = ""
        if _is_sell_side(_value(row, 4)):
            ticker = _text(_value(row, 2)).upper()
            exit_reason = exit_reasons[ticker].popleft() if exit_reasons[ticker] else ""
        enriched.append((row, exit_reason))

    buy_rows = [row for row, _ in enriched if _is_buy_side(_value(row, 4))]
    sell_rows = [row for row, _ in enriched if _is_sell_side(_value(row, 4))]
    sell_profit_rows = [row for row in sell_rows if _value(row, 8) is not None]
    realized_profit = sum(_number(_value(row, 8)) for row in sell_rows)
    average_return = _average(_number(_value(row, 9)) for row in sell_profit_rows)
    win_rate = _win_rate(_number(_value(row, 8)) for row in sell_profit_rows)
    stats = [
        f"- 매수 체결 수: {len(buy_rows)}",
        f"- 매도 체결 수: {len(sell_rows)}",
        f"- 총 체결 수: {len(fills)}",
        f"- 총 매수 금액: {_money(sum(_number(_value(row, 7)) for row in buy_rows))}",
        f"- 총 매도 금액: {_money(sum(_number(_value(row, 7)) for row in sell_rows))}",
        f"- 실현 손익: {_money(realized_profit)}",
        f"- 평균 수익률: {_percent_from_fraction(average_return)}",
        f"- 승률: {_percent(win_rate)}",
    ]
    if not enriched:
        return ["- 체결 없음"], stats, _default_exit_stats(), {}

    fill_header = (
        "| 시간 | 종목 | 매수/매도 | 수량 | 체결가 | 체결금액 | 수익률 | "
        "손익 | entry_reason | exit_reason | strategy_version |"
    )
    fill_lines = [
        fill_header,
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    exit_stats = _default_exit_stats()
    strategy_stats: dict[str, dict[str, float]] = {}
    for row, exit_reason in enriched:
        side = _side_label(_value(row, 4))
        profit = _number(_value(row, 8))
        rate = _number(_value(row, 9))
        strategy_version = _text(_value(row, 12)) or "UNKNOWN"
        if _is_sell_side(_value(row, 4)):
            reason_key = exit_reason or "UNKNOWN"
            _add_stat(exit_stats.setdefault(reason_key, _empty_stat()), profit, rate)
            _add_stat(strategy_stats.setdefault(strategy_version, _empty_stat()), profit, rate)
        fill_lines.append(
            "| "
            + " | ".join(
                [
                    _safe(_value(row, 1)),
                    _safe(_value(row, 2)),
                    side,
                    str(int(_number(_value(row, 5)))),
                    _money(_number(_value(row, 6))),
                    _money(_number(_value(row, 7))),
                    _percent_from_fraction(rate),
                    _money(profit),
                    _safe(_value(row, 10)),
                    _safe(exit_reason),
                    _safe(strategy_version),
                ]
            )
            + " |"
        )
    return fill_lines, stats, exit_stats, strategy_stats


def _account_lines(account: tuple[Any, ...] | None, run_realized_profit: float) -> list[str]:
    cash = _number(_value(account, 0))
    equity = _number(_value(account, 1))
    invested = _number(_value(account, 2))
    holdings = int(_number(_value(account, 3)))
    daily_profit_rate = _number(_value(account, 4))
    realized_profit = _number(_value(account, 5)) or run_realized_profit
    return [
        f"- 현금: {_money(cash)}",
        f"- 평가금액: {_money(equity)}",
        f"- 투자금액: {_money(invested)}",
        f"- 일일 손익: {_percent(daily_profit_rate)}",
        f"- 실현 손익: {_money(realized_profit)}",
        f"- 보유 종목 수: {holdings}",
    ]


def _entry_profit_snapshot_lines(rows: list[tuple[Any, ...]]) -> list[str]:
    lines = [f"- 표본 수: {len(rows)}"]
    if len(rows) < ENTRY_PROFIT_SAMPLE_MINIMUM:
        lines.append("- 표본 부족: 전략 판단 금지")
    for label, index in (("5분", 2), ("10분", 3), ("15분", 4), ("20분", 5), ("30분", 6)):
        negative_rows = _negative_snapshot_rows(rows, index)
        lines.append(f"- {label} 후 음수 거래 수: {len(negative_rows)}")
    for label, index in (("5분", 2), ("10분", 3), ("15분", 4), ("20분", 5)):
        negative_rows = _negative_snapshot_rows(rows, index)
        final_rows = [row for row in negative_rows if _value(row, 8) is not None]
        win_rate = _win_rate(_number(_value(row, 8)) for row in final_rows)
        lines.append(f"- {label} 후 음수 거래 최종 승률: {_percent(win_rate)}")
    return lines


def _negative_snapshot_rows(rows: list[tuple[Any, ...]], index: int) -> list[tuple[Any, ...]]:
    return [
        row
        for row in rows
        if _value(row, index) is not None and _number(_value(row, index)) < 0
    ]


def _candidate_section(counts: tuple[Any, ...], logs: list[tuple[Any, ...]]) -> list[str]:
    candidate_count = int(_number(_value(counts, 0)))
    scoring_count = int(_number(_value(counts, 1)))
    selected_count = int(_number(_value(counts, 2)))
    reject_reasons = _reject_reasons(logs)
    messages = [_text(_value(row, 3)) for row in logs]
    strict_filter = _contains(messages, "STRICT_FILTER_NO_CANDIDATES")
    snapshot_saved = _contains(messages, "CANDIDATE_SNAPSHOT_SAVED")
    snapshot_empty = _contains(messages, "CANDIDATE_SNAPSHOT_EMPTY")
    return [
        f"- 후보 수: {candidate_count}",
        f"- 점수 계산 후보 수: {scoring_count}",
        f"- 선정 수: {selected_count}",
        f"- 주요 탈락 사유: {reject_reasons or '없음'}",
        f"- STRICT_FILTER_NO_CANDIDATES 발생 여부: {_yes_no(strict_filter)}",
        f"- CANDIDATE_SNAPSHOT_SAVED 발생 여부: {_yes_no(snapshot_saved)}",
        f"- CANDIDATE_SNAPSHOT_EMPTY 발생 여부: {_yes_no(snapshot_empty)}",
    ]


def _log_section(rows: list[tuple[Any, ...]]) -> list[str]:
    important = [row for row in rows if _important_log(row)]
    if not important:
        return ["- 중요 오류 없음"]
    lines = [
        "| 시간 | 수준 | 모듈 | 내용 |",
        "| --- | --- | --- | --- |",
    ]
    for row in important[:100]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _safe(_value(row, 0)),
                    _safe(_value(row, 1)),
                    _safe(_value(row, 2)),
                    _safe(_value(row, 3)),
                ]
            )
            + " |"
        )
    return lines


def _stats_table(stats: dict[str, dict[str, float]], key_title: str) -> list[str]:
    lines = [
        f"| {key_title} | 건수 | 총 손익 | 평균 수익률 | 승률 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for key in EXIT_REASON_ORDER if key_title == "청산 사유" else sorted(stats):
        item = stats.get(key, _empty_stat())
        count = int(item["count"])
        lines.append(
            f"| {_safe(key)} | {count} | {_money(item['profit'])} | "
            f"{_percent_from_fraction(item['rate'] / count if count else 0.0)} | "
            f"{_percent(item['wins'] / count * 100 if count else 0.0)} |"
        )
    if key_title == "청산 사유":
        for key in sorted(set(stats) - set(EXIT_REASON_ORDER)):
            item = stats[key]
            count = int(item["count"])
            lines.append(
                f"| {_safe(key)} | {count} | {_money(item['profit'])} | "
                f"{_percent_from_fraction(item['rate'] / count if count else 0.0)} | "
                f"{_percent(item['wins'] / count * 100 if count else 0.0)} |"
            )
    return lines


def _sell_exit_reasons(trades: list[tuple[Any, ...]]) -> dict[str, deque[str]]:
    reasons: dict[str, deque[str]] = defaultdict(deque)
    for row in trades:
        if _is_sell_side(_value(row, 4)):
            reasons[_text(_value(row, 2)).upper()].append(_text(_value(row, 7)))
    return reasons


def _default_exit_stats() -> dict[str, dict[str, float]]:
    return {key: _empty_stat() for key in EXIT_REASON_ORDER}


def _empty_stat() -> dict[str, float]:
    return {"count": 0.0, "profit": 0.0, "rate": 0.0, "wins": 0.0}


def _add_stat(item: dict[str, float], profit: float, rate: float) -> None:
    item["count"] += 1
    item["profit"] += profit
    item["rate"] += rate
    if profit > 0:
        item["wins"] += 1


def _important_log(row: tuple[Any, ...]) -> bool:
    level = _text(_value(row, 1)).upper()
    message = _text(_value(row, 3))
    upper_message = message.upper()
    keywords = (
        "ORDER_FAILED",
        "CANDIDATE_SNAPSHOT_SAVE_FAILED",
        "API_FAILED",
        "PREFLIGHT",
        "ERROR",
        "FAILED",
        "주문 실패",
        "후보 저장 실패",
        "API 실패",
    )
    return level in {"ERROR", "WARNING", "WARN"} or any(
        item in upper_message or item in message for item in keywords
    )


def _reject_reasons(rows: list[tuple[Any, ...]]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        message = _text(_value(row, 3))
        if "Filter rejects" not in message and "[FILTER]" not in message:
            continue
        for key, value in re.findall(r"([A-Za-z_]+)=([0-9]+)", message):
            counts[key] = counts.get(key, 0) + int(value)
    if not counts:
        return ""
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return ", ".join(f"{key}={value}" for key, value in ranked)


def _default_data_source() -> TradeSummaryDataSource:
    from trading_bot.database import pyodbc_connect_factory

    return SqlTradeSummaryDataSource(pyodbc_connect_factory())


_LEGACY_MOJIBAKE_BUY_SIDE_MARKERS = ("\uf9cd\u317c\ub2d4",)
_LEGACY_MOJIBAKE_SELL_SIDE_MARKERS = ("\uf9cd\u317b\ub8c4",)


def _is_buy_side(value: Any) -> bool:
    text = _text(value)
    # Some old DB rows were saved with mojibake side labels; keep them readable.
    return (
        "매수" in text
        or any(marker in text for marker in _LEGACY_MOJIBAKE_BUY_SIDE_MARKERS)
        or text.strip().upper() in {"BUY", "B"}
    )


def _is_sell_side(value: Any) -> bool:
    text = _text(value)
    # Some old DB rows were saved with mojibake side labels; keep them readable.
    return (
        "매도" in text
        or any(marker in text for marker in _LEGACY_MOJIBAKE_SELL_SIDE_MARKERS)
        or text.strip().upper() in {"SELL", "S"}
    )


def _side_label(value: Any) -> str:
    if _is_buy_side(value):
        return "매수"
    if _is_sell_side(value):
        return "매도"
    return _safe(value) or "-"


def _contains(messages: list[str], needle: str) -> bool:
    return any(needle in message for message in messages)


def _yes_no(value: bool) -> str:
    return "예" if value else "아니오"


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _percent(value: float) -> str:
    return f"{value:.2f}%"


def _percent_from_fraction(value: float) -> str:
    return _percent(value * 100)


def _average(values: Any) -> float:
    items = [float(item) for item in values]
    return sum(items) / len(items) if items else 0.0


def _win_rate(values: Any) -> float:
    items = [float(item) for item in values]
    if not items:
        return 0.0
    return sum(1 for item in items if item > 0) / len(items) * 100


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(str(value).replace("$", "").replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _safe(value: Any) -> str:
    text = _text(value).replace("|", "/")
    for pattern, replacement in SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return _safe(text)
    return ""


def _value(row: tuple[Any, ...] | None, index: int, default: Any = None) -> Any:
    if row is None or index >= len(row):
        return default
    return row[index]
