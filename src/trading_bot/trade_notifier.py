from __future__ import annotations

from collections.abc import Callable

from trading_bot.trade_notifier_messages import (
    MoneyFormatter,
    buy_success_message,
    fmt_won,
    holding_line,
    invalid_fill_message,
    market_close_report_message,
    missing_position_message,
    now_kst,
    order_fail_message,
    sell_success_message,
)


PriceFunc = Callable[[str], float | int | str | None]
MessageSender = Callable[[str], bool]
Position = dict[str, str | int | float]
DailyStats = dict[str, int | float]


class TradeNotifier:
    def __init__(
        self,
        current_price_func: PriceFunc,
        *,
        message_sender: MessageSender | None = None,
        money_formatter: MoneyFormatter = fmt_won,
        sell_fee_tax_rate: float = 0.0,
    ) -> None:
        if message_sender is None:
            from trading_bot.notifications import send_telegram_message

            message_sender = send_telegram_message
        self.current_price_func = current_price_func
        self.message_sender = message_sender
        self.money_formatter = money_formatter
        self.sell_fee_tax_rate = max(0.0, sell_fee_tax_rate)
        self.positions: dict[str, Position] = {}
        self.daily: DailyStats = _empty_daily_stats()
        self._daily_date = now_kst().date()

    def on_buy_success(
        self,
        code: str,
        name: str,
        qty: int,
        filled_price: float,
        order_no: str | None = None,
    ) -> bool:
        self._ensure_daily_date()
        filled_qty = int(qty)
        price = float(filled_price)
        if filled_qty <= 0 or price <= 0:
            return self.message_sender(
                invalid_fill_message("매수", code, name, qty, filled_price, order_no)
            )

        position = self.positions.get(code)
        if position:
            prev_qty = int(position["qty"])
            prev_avg = float(position["avg_price"])
            new_qty = prev_qty + filled_qty
            new_avg = ((prev_avg * prev_qty) + (price * filled_qty)) / new_qty
        else:
            new_qty = filled_qty
            new_avg = price

        self.positions[code] = {"name": name, "qty": new_qty, "avg_price": new_avg}
        self.daily["buy_count"] = int(self.daily["buy_count"]) + 1
        self.daily["buy_amount"] = float(self.daily["buy_amount"]) + (price * filled_qty)

        return self.message_sender(
            buy_success_message(
                code,
                name,
                filled_qty,
                price,
                self._current_price_or(code, price),
                new_qty,
                new_avg,
                order_no,
                self.money_formatter,
            )
        )

    def on_sell_success(
        self,
        code: str,
        name: str,
        qty: int,
        filled_price: float,
        order_no: str | None = None,
    ) -> bool:
        self._ensure_daily_date()
        filled_qty = int(qty)
        price = float(filled_price)
        if filled_qty <= 0 or price <= 0:
            return self.message_sender(
                invalid_fill_message("매도", code, name, qty, filled_price, order_no)
            )

        self.daily["sell_count"] = int(self.daily["sell_count"]) + 1
        self.daily["sell_amount"] = float(self.daily["sell_amount"]) + (price * filled_qty)
        position = self.positions.get(code)
        if not position:
            current_price = self._current_price_or(code, price)
            return self.message_sender(
                missing_position_message(
                    code, name, filled_qty, price, current_price, order_no
                )
            )

        held_qty = int(position["qty"])
        avg_price = float(position["avg_price"])
        sell_qty = min(filled_qty, held_qty)
        cost = avg_price * sell_qty
        fee_tax = price * sell_qty * self.sell_fee_tax_rate
        realized_pnl = (price * sell_qty) - cost - fee_tax
        realized_rate = (realized_pnl / cost * 100) if cost else 0.0
        self.daily["realized_pnl"] = float(self.daily["realized_pnl"]) + realized_pnl
        self.daily["realized_cost"] = float(self.daily["realized_cost"]) + cost
        self._reduce_position(code, position, held_qty - sell_qty)

        warning = ""
        if filled_qty > held_qty:
            warning = f"\n주의: 보유수량 {held_qty}주 기준으로 손익을 계산했습니다."
        return self.message_sender(
            sell_success_message(
                code,
                name,
                filled_qty,
                avg_price,
                price,
                self._current_price_or(code, price),
                realized_pnl,
                realized_rate,
                order_no,
                warning,
                self.money_formatter,
            )
        )

    def on_order_fail(
        self,
        side: str,
        code: str,
        name: str,
        qty: int,
        order_price: float | None = None,
        reason: str | None = None,
        order_no: str | None = None,
    ) -> bool:
        return self.message_sender(
            order_fail_message(
                side,
                code,
                name,
                qty,
                order_price,
                reason,
                order_no,
                self.money_formatter,
            )
        )

    def send_market_close_report(self) -> bool:
        self._ensure_daily_date()
        realized_pnl = float(self.daily["realized_pnl"])
        realized_cost = float(self.daily["realized_cost"])
        realized_rate = (realized_pnl / realized_cost * 100) if realized_cost else 0.0
        holding_lines, evaluation_pnl, evaluation_cost = self._holding_summary()
        evaluation_rate = (
            evaluation_pnl / evaluation_cost * 100
            if evaluation_cost
            else 0.0
        )
        total_pnl = realized_pnl + evaluation_pnl
        total_cost = realized_cost + evaluation_cost
        total_rate = (total_pnl / total_cost * 100) if total_cost else 0.0
        return self.message_sender(
            market_close_report_message(
                self.daily,
                realized_rate,
                evaluation_pnl,
                evaluation_rate,
                total_pnl,
                total_rate,
                holding_lines,
                self.money_formatter,
            )
        )

    def _holding_summary(self) -> tuple[list[str], float, float]:
        lines: list[str] = []
        evaluation_pnl = 0.0
        evaluation_cost = 0.0
        for code, position in sorted(self.positions.items()):
            qty = int(position["qty"])
            avg_price = float(position["avg_price"])
            current_price = self._current_price_or(code, avg_price)
            cost = avg_price * qty
            pnl = (current_price * qty) - cost
            rate = (pnl / cost * 100) if cost else 0.0
            evaluation_cost += cost
            evaluation_pnl += pnl
            lines.append(
                holding_line(
                    code,
                    str(position["name"]),
                    qty,
                    avg_price,
                    current_price,
                    rate,
                    self.money_formatter,
                )
            )
        return lines, evaluation_pnl, evaluation_cost

    def _ensure_daily_date(self) -> None:
        today = now_kst().date()
        if today != self._daily_date:
            self.daily = _empty_daily_stats()
            self._daily_date = today

    def _current_price_or(self, code: str, fallback: float) -> float:
        try:
            price = self.current_price_func(code)
        except Exception:
            return fallback
        parsed = _to_positive_float(price)
        return parsed if parsed is not None else fallback

    def _reduce_position(self, code: str, position: Position, remaining_qty: int) -> None:
        if remaining_qty <= 0:
            self.positions.pop(code, None)
        else:
            position["qty"] = remaining_qty


def get_current_price(code: str) -> float | None:
    # 실제 적용 시 broker_api_get_current_price(code) 같은 현재가 API로 교체한다.
    return None


def _empty_daily_stats() -> DailyStats:
    return {
        "buy_count": 0,
        "sell_count": 0,
        "buy_amount": 0.0,
        "sell_amount": 0.0,
        "realized_pnl": 0.0,
        "realized_cost": 0.0,
    }


def _to_positive_float(value: float | int | str | None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
