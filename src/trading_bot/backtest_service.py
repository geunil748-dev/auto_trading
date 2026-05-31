from __future__ import annotations

from typing import Any

from trading_bot.backtest import BacktestResult, run_chart_backtest
from trading_bot.backtest_data import BacktestPriceSource, YahooBacktestPriceSource, load_history
from trading_bot.config import load_settings


def run_backtest_from_monitor_state(
    state: dict[str, object],
    price_source: BacktestPriceSource | None = None,
    years: int = 10,
    selected_tickers: list[str] | None = None,
) -> dict[str, object]:
    available = _current_candidates(state)
    tickers = _selected_tickers(available, selected_tickers)
    if not tickers:
        return {
            "ok": False,
            "message": "백테스트할 후보 종목이 없습니다. 후보 리스트를 먼저 수집해 주세요.",
            "tickers": [],
            "candidates": _candidate_payloads(available),
            "results": [],
        }
    source = price_source or YahooBacktestPriceSource()
    settings = load_settings()
    try:
        history = load_history(tickers, source, years)
    except Exception:
        history = {ticker: [] for ticker in tickers}
    results = run_chart_backtest(tickers, history, settings, years)
    return {
        "ok": True,
        "message": f"{len(tickers)}개 후보 종목으로 뉴스 제외 차트 백테스트를 완료했습니다.",
        "tickers": tickers,
        "candidates": _candidate_payloads(available),
        "results": [_result_payload(item) for item in results],
    }


def _current_candidates(state: dict[str, object]) -> list[dict[str, str]]:
    rows = _candidate_rows(state)
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        ticker = _ticker_from_row(row)
        if not ticker or ticker in seen:
            continue
        candidates.append({"ticker": ticker, "name": _name_from_row(row)})
        seen.add(ticker)
    return candidates


def _selected_tickers(
    candidates: list[dict[str, str]],
    selected_tickers: list[str] | None,
) -> list[str]:
    if not selected_tickers:
        return [item["ticker"] for item in candidates]
    return _unique_tickers(selected_tickers)


def _unique_tickers(values: list[str]) -> list[str]:
    tickers: list[str] = []
    for value in values:
        ticker = _clean_ticker(value)
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def _candidate_payloads(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{"ticker": item["ticker"], "name": item.get("name", "")} for item in candidates]


def _candidate_rows(state: dict[str, object]) -> list[Any]:
    accounts = state.get("accounts")
    if isinstance(accounts, dict):
        mock = accounts.get("mock")
        if isinstance(mock, dict) and isinstance(mock.get("targets"), list):
            return mock["targets"]
    targets = state.get("targets")
    return targets if isinstance(targets, list) else []


def _ticker_from_row(row: Any) -> str:
    if isinstance(row, dict):
        return _clean_ticker(row.get("ticker", ""))
    if isinstance(row, (list, tuple)) and row:
        # 화면용 후보 행은 [종목, 종목명, 가격, ...] 형태로 전달된다.
        return _clean_ticker(row[0])
    return ""


def _name_from_row(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("name", "") or "").strip()
    if isinstance(row, (list, tuple)) and len(row) > 1:
        return str(row[1] or "").strip()
    return ""


def _clean_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def _result_payload(result: BacktestResult) -> dict[str, str | int]:
    if not result.data_sufficient:
        return {
            "years": result.years,
            "tickers": result.tickers,
            "trades": 0,
            "wins": 0,
            "winRate": "데이터 부족",
            "returnRate": "데이터 부족",
            "profitUsd": "데이터 부족",
            "endingEquityUsd": "-",
            "averageTradeReturn": "-",
            "maxDrawdown": "-",
            "zeroEntryDays": 0,
            "stopLossCount": 0,
            "takeProfitCount": 0,
            "trailingStopCount": 0,
            "eodCount": 0,
            "eodRate": "-",
        }
    return {
        "years": result.years,
        "tickers": result.tickers,
        "trades": result.trades,
        "wins": result.wins,
        "winRate": _percent(result.win_rate),
        "returnRate": _signed_percent(result.return_rate),
        "profitUsd": _signed_usd(result.profit_usd),
        "endingEquityUsd": _usd(result.ending_equity_usd),
        "averageTradeReturn": _signed_percent(result.average_trade_return),
        "maxDrawdown": _signed_percent(result.max_drawdown),
        "zeroEntryDays": result.zero_entry_days,
        "stopLossCount": result.stop_loss_count,
        "takeProfitCount": result.take_profit_count,
        "trailingStopCount": result.trailing_stop_count,
        "eodCount": result.eod_count,
        "eodRate": _percent(result.eod_rate),
    }


def _usd(value: float) -> str:
    return f"${value:,.2f}"


def _signed_usd(value: float) -> str:
    if value < 0:
        return f"-${abs(value):,.2f}"
    sign = "+" if value > 0 else ""
    return f"{sign}${value:,.2f}"


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _signed_percent(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value * 100:.2f}%"
