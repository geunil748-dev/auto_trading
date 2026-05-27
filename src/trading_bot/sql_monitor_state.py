from __future__ import annotations

from datetime import date
from typing import Any

from trading_bot.repositories import SqlServerMonitorRepository


class SqlMonitorStateSource:
    def __init__(self, repository: SqlServerMonitorRepository) -> None:
        self.repository = repository

    def read(self) -> dict[str, object]:
        scores = {row[0]: row for row in self.repository.latest_scores()}
        return {
            "targets": [
                _target(row, scores.get(row[0]))
                for row in self.repository.latest_targets()
            ],
            "positions": [],
            "holdings": [_holding(row) for row in self.repository.latest_holdings()],
            "orders": [],
            "fills": [_fill(row) for row in self.repository.latest_fills()],
            "gates": [
                ["저장소", "MSSQL"],
                ["점수 기록", str(len(scores))],
            ],
            "logs": [_log(row) for row in self.repository.latest_logs()],
            "trades": [_trade(row) for row in self.repository.latest_trades()],
            "summary": _summary(self.repository.today_realized_profit()),
            "chart": {"closes": [], "movingAverage": []},
        }

    def read_history(self, trade_date: date) -> dict[str, object]:
        scores = {row[0]: row for row in self.repository.history_scores(trade_date)}
        return {
            "date": trade_date.isoformat(),
            "targets": [
                _target(row, scores.get(row[0]))
                for row in self.repository.history_targets(trade_date)
            ],
            "holdings": [_holding(row) for row in self.repository.history_holdings(trade_date)],
            "orders": [],
            "fills": [_fill(row) for row in self.repository.history_fills(trade_date)],
            "logs": [_log(row) for row in self.repository.history_logs(trade_date)],
            "trades": [_trade(row) for row in self.repository.history_trades(trade_date)],
            "summary": _summary(self.repository.history_realized_profit(trade_date)),
        }


def _target(row: tuple[Any, ...], score: tuple[Any, ...] | None) -> list[str]:
    if len(row) >= 5:
        ticker, ticker_name, price_usd, volume_ratio, price_change = row[:5]
        price_text = _usd(_number(price_usd))
    elif len(row) >= 4:
        ticker, ticker_name, volume_ratio, price_change = row[:4]
        price_text = "-"
    else:
        ticker, volume_ratio, price_change = row
        ticker_name = "-"
        price_text = "-"
    score_value = (
        str(round(_fallback_filter_score(volume_ratio, price_change)))
        if score is None
        else str(round(_number(score[3])))
    )
    state = "필터점수" if score is None else ("선정" if score[4] else "제외")
    return [
        str(ticker),
        str(ticker_name or "-"),
        price_text,
        f"{_number(volume_ratio):.0f}%",
        f"{_number(price_change):+.1f}%",
        score_value,
        state,
    ]


def _holding(row: tuple[Any, ...]) -> dict[str, str]:
    ticker, ticker_name, quantity, average_price, open_price, close_price, total_price = row[:7]
    return {
        "ticker": str(ticker),
        "name": str(ticker_name or ""),
        "quantity": str(quantity),
        "averagePrice": _usd(_number(average_price)),
        "openPrice": _usd_or_dash(open_price),
        "closePrice": _usd_or_dash(close_price),
        "totalPrice": _usd(_number(total_price)),
    }


def _log(row: tuple[Any, ...]) -> list[str]:
    created_at, level, message = row
    timestamp = created_at.strftime("%H:%M:%S") if hasattr(created_at, "strftime") else str(created_at)
    return [timestamp, _level_text(level), _message_text(message)]


def _trade(row: tuple[Any, ...]) -> dict[str, str]:
    ticker, order_type, order_price, quantity, exit_reason = row[:5]
    profit_usd = row[5] if len(row) > 5 else None
    profit_rate = row[6] if len(row) > 6 else None
    return {
        "ticker": str(ticker),
        "type": _side_text(order_type),
        "price": f"${_number(order_price):.2f}",
        "quantity": str(quantity),
        "exitReason": "" if exit_reason is None else _reason_text(str(exit_reason)),
        "profitUsd": "" if profit_usd is None else _signed_usd(_number(profit_usd)),
        "profitRate": "" if profit_rate is None else f"{_number(profit_rate) * 100:+.2f}%",
    }


def _fill(row: tuple[Any, ...]) -> dict[str, str]:
    fill_date, fill_time, ticker, ticker_name, side, quantity, fill_price, fill_amount = row[:8]
    profit_usd = row[8] if len(row) > 8 else None
    profit_rate = row[9] if len(row) > 9 else None
    date_text = _date_text(fill_date)
    time_text = "" if fill_time is None else str(fill_time)
    return {
        "date": date_text,
        "time": time_text,
        "filledAt": f"{date_text} {time_text}".strip(),
        "ticker": str(ticker),
        "name": str(ticker_name or ""),
        "side": _side_text(side),
        "quantity": str(quantity),
        "price": f"${_number(fill_price):,.2f}",
        "total": f"${_number(fill_amount):,.2f}",
        "profitUsd": "" if profit_usd is None else _signed_usd(_number(profit_usd)),
        "profitRate": "" if profit_rate is None else f"{_number(profit_rate) * 100:+.2f}%",
    }


def _date_text(value: Any) -> str:
    if all(hasattr(value, field) for field in ("Year", "Month", "Day")):
        return f"{value.Year:04d}-{value.Month:02d}-{value.Day:02d}"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _summary(realized_profit_usd: float) -> dict[str, str]:
    return {"realizedProfitUsd": _signed_usd(realized_profit_usd)}


def _signed_usd(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}${value:,.2f}"


def _usd(value: float) -> str:
    return f"${value:,.2f}"


def _usd_or_dash(value: Any) -> str:
    number = _number(value)
    return "-" if number <= 0 else _usd(number)


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except TypeError:
        return float(str(value))


def _fallback_filter_score(volume_ratio: Any, price_change: Any) -> float:
    volume = max(0.0, _number(volume_ratio))
    change = max(0.0, _number(price_change))
    volume_score = min(volume / 3.0 * 50.0, 50.0)
    change_score = min(change / 8.0 * 50.0, 50.0)
    return volume_score + change_score


def _level_text(level: Any) -> str:
    mapping = {
        "INFO": "정보",
        "WARNING": "주의",
        "WARN": "주의",
        "ERROR": "오류",
    }
    return mapping.get(str(level).upper(), str(level))


def _side_text(value: Any) -> str:
    raw = str(value or "").strip()
    normalized = raw.upper()
    if normalized in {"BUY", "B"} or "매수" in raw:
        return "매수"
    if normalized in {"SELL", "S"} or "매도" in raw:
        return "매도"
    return raw


def _message_text(message: Any) -> str:
    text = str(message)
    if text.startswith("Screened ") and " targets and selected " in text:
        parts = text.rstrip(".").split()
        if len(parts) >= 6:
            return f"후보 {parts[1]}개를 점검했고, 최종 {parts[5]}개를 선정했습니다."
    if text.startswith("Filter rejects: "):
        raw = text.removeprefix("Filter rejects: ").rstrip(".")
        if raw == "none":
            return "필터에서 제외된 종목은 없습니다."
        return "필터 제외 사유: " + ", ".join(_reason_count(part) for part in raw.split(", "))
    if text.startswith("Entry blocked: "):
        return "진입 차단: " + _reason_text(text.removeprefix("Entry blocked: ").strip())
    return _replace_known_tokens(text)


def _reason_count(part: str) -> str:
    if "=" not in part:
        return _reason_text(part)
    reason, count = part.split("=", 1)
    return f"{_reason_text(reason)} {count}건"


def _replace_known_tokens(text: str) -> str:
    for token, label in _REASON_TEXT.items():
        text = text.replace(token, label)
    return text


def _reason_text(reason: str) -> str:
    return _REASON_TEXT.get(reason.strip(), reason.strip())


_REASON_TEXT = {
    "ACCOUNT_EXPOSURE_LIMIT": "계좌 투자비중 초과",
    "DAILY_ACCOUNT_LOSS": "일일 손실 제한 도달",
    "FX_VOLATILITY": "환율 변동성 초과",
    "INVALID_ACCOUNT_EQUITY": "계좌 평가금액 확인 불가",
    "INVALID_ORDER_VALUE": "주문 금액 오류",
    "LOW_OPENING_CHANGE": "장초반 상승률 부족",
    "LOW_OPENING_VOLUME": "장초반 거래량 부족",
    "MARKET_BELOW_MA20": "나스닥 20일선 하회",
    "MISSING_SNAPSHOT": "시세 스냅샷 없음",
    "OPENING_GAP": "시가 갭 과다",
    "OPEN_POSITION_LIMIT": "최대 보유 종목 수 초과",
    "PENNY_STOCK": "가격 하한 미달",
    "POSITION_EXPOSURE_LIMIT": "종목별 투자비중 초과",
    "PRICE_CAP": "가격 상한 초과",
}
