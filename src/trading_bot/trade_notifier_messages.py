from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
MoneyFormatter = Callable[[float | int, bool], str]


def now_kst() -> datetime:
    return datetime.now(KST).replace(microsecond=0)


def fmt_won(value: float | int, signed: bool = False) -> str:
    amount = round(float(value))
    if signed:
        sign = "+" if amount > 0 else "-" if amount < 0 else ""
        return f"{sign}{abs(amount):,}원"
    return f"{amount:,}원"


def fmt_pct(value: float | int, signed: bool = False) -> str:
    rate = float(value)
    if signed:
        sign = "+" if rate > 0 else "-" if rate < 0 else ""
        return f"{sign}{abs(rate):.2f}%"
    return f"{rate:.2f}%"


def fmt_usd(value: float | int, signed: bool = False) -> str:
    amount = float(value)
    if signed:
        sign = "+" if amount > 0 else "-" if amount < 0 else ""
        return f"{sign}${abs(amount):,.2f}"
    return f"${amount:,.2f}"


def buy_success_message(
    code: str,
    name: str,
    qty: int,
    filled_price: float,
    current_price: float,
    holding_qty: int,
    holding_avg: float,
    order_no: str | None,
    money: MoneyFormatter = fmt_won,
) -> str:
    return "\n".join(
        [
            "✅ 매수 성공",
            "",
            f"종목: {name}",
            f"코드: {code}",
            f"수량: {qty}주",
            f"체결가: {money(filled_price, False)}",
            f"현재가: {money(current_price, False)}",
            "",
            f"보유수량: {holding_qty}주",
            f"보유평단: {money(holding_avg, False)}",
            "",
            f"주문번호: {order_no or '-'}",
            f"시간: {_timestamp()}",
        ]
    )


def sell_success_message(
    code: str,
    name: str,
    qty: int,
    avg_price: float,
    filled_price: float,
    current_price: float,
    realized_pnl: float,
    realized_rate: float,
    order_no: str | None,
    warning: str = "",
    money: MoneyFormatter = fmt_won,
) -> str:
    return "\n".join(
        [
            "✅ 매도 성공",
            "",
            f"종목: {name}",
            f"코드: {code}",
            f"수량: {qty}주",
            f"매수평단: {money(avg_price, False)}",
            f"매도체결가: {money(filled_price, False)}",
            f"현재가: {money(current_price, False)}",
            "",
            f"실현손익: {money(realized_pnl, True)}",
            f"수익률: {fmt_pct(realized_rate, signed=True)}",
            "",
            f"주문번호: {order_no or '-'}",
            f"시간: {_timestamp()}",
            warning,
        ]
    ).rstrip()


def order_fail_message(
    side: str,
    code: str,
    name: str,
    qty: int,
    order_price: float | None,
    reason: str | None,
    order_no: str | None,
    money: MoneyFormatter = fmt_won,
) -> str:
    price_line = f"주문가: {money(order_price, False)}" if order_price else "주문가: -"
    return "\n".join(
        [
            f"⚠️ {_side_label(side)} 주문 실패",
            "",
            f"종목: {name}",
            f"코드: {code}",
            f"수량: {qty}주",
            price_line,
            f"사유: {reason or '-'}",
            "",
            f"주문번호: {order_no or '-'}",
            f"시간: {_timestamp()}",
        ]
    )


def invalid_fill_message(
    side: str,
    code: str,
    name: str,
    qty: int,
    filled_price: float,
    order_no: str | None,
) -> str:
    return "\n".join(
        [
            f"⚠️ {side} 체결 알림 실패",
            "",
            f"종목: {name}",
            f"코드: {code}",
            f"수량: {qty}주",
            f"체결가: {filled_price}",
            "사유: 체결수량 또는 체결가가 올바르지 않습니다.",
            "",
            f"주문번호: {order_no or '-'}",
            f"시간: {_timestamp()}",
        ]
    )


def missing_position_message(
    code: str,
    name: str,
    qty: int,
    filled_price: float,
    current_price: float,
    order_no: str | None,
    money: MoneyFormatter = fmt_won,
) -> str:
    return "\n".join(
        [
            "⚠️ 매도 체결 알림",
            "",
            f"종목: {name}",
            f"코드: {code}",
            f"수량: {qty}주",
            f"매도체결가: {money(filled_price, False)}",
            f"현재가: {money(current_price, False)}",
            "",
            "실현손익: 계산 불가",
            "수익률: 계산 불가",
            "사유: 보유정보가 없어 평균단가를 확인할 수 없습니다.",
            "",
            f"주문번호: {order_no or '-'}",
            f"시간: {_timestamp()}",
        ]
    )


def market_close_report_message(
    daily: dict[str, int | float],
    realized_rate: float,
    evaluation_pnl: float,
    evaluation_rate: float,
    total_pnl: float,
    total_rate: float,
    holding_lines: list[str],
    money: MoneyFormatter = fmt_won,
) -> str:
    return "\n".join(
        [
            "📊 장마감 수익률 요약",
            "",
            f"매수 횟수: {int(daily['buy_count'])}회",
            f"매도 횟수: {int(daily['sell_count'])}회",
            "",
            f"오늘 매수금액: {money(float(daily['buy_amount']), False)}",
            f"오늘 매도금액: {money(float(daily['sell_amount']), False)}",
            "",
            f"실현손익: {money(float(daily['realized_pnl']), True)}",
            f"실현수익률: {fmt_pct(realized_rate, signed=True)}",
            "",
            f"평가손익: {money(evaluation_pnl, True)}",
            f"평가수익률: {fmt_pct(evaluation_rate, signed=True)}",
            "",
            f"총손익: {money(total_pnl, True)}",
            f"총수익률: {fmt_pct(total_rate, signed=True)}",
            "",
            "보유 종목",
            "\n".join(holding_lines) if holding_lines else "- 없음",
            "",
            f"시간: {_timestamp()}",
        ]
    )


def holding_line(
    code: str,
    name: str,
    qty: int,
    avg_price: float,
    current_price: float,
    rate: float,
    money: MoneyFormatter = fmt_won,
) -> str:
    return (
        f"- {name}({code}) {qty}주 / 평단 {money(avg_price, False)} / "
        f"현재 {money(current_price, False)} / {fmt_pct(rate, signed=True)}"
    )


def _side_label(side: str) -> str:
    upper = side.upper()
    if upper in {"BUY", "B", "매수"}:
        return "매수"
    if upper in {"SELL", "S", "매도"}:
        return "매도"
    return side


def _timestamp() -> str:
    return now_kst().strftime("%Y-%m-%d %H:%M:%S")
