from datetime import date

from trading_bot.fill_persistence import fill_records_from_monitor_rows


def test_fill_records_from_monitor_rows_normalizes_monitor_fill() -> None:
    records = fill_records_from_monitor_rows(
        [
            {
                "date": "2026-05-22",
                "time": "22:41:10",
                "ticker": " aaa ",
                "name": "Alpha",
                "side": "매수",
                "quantity": "2주",
                "price": "$12.50",
                "total": "$25.00",
                "orderNo": "1001",
            },
            {"ticker": "", "quantity": "0"},
        ]
    )

    assert len(records) == 1
    assert records[0].trade_date == date(2026, 5, 22)
    assert records[0].ticker == "AAA"
    assert records[0].quantity == 2
    assert records[0].fill_price_usd == 12.5
    assert records[0].fill_amount_usd == 25.0
    assert records[0].order_no == "1001"


def test_fill_records_from_monitor_rows_calculates_realized_sell_profit() -> None:
    records = fill_records_from_monitor_rows(
        [
            {
                "date": "2026-05-22",
                "time": "22:41:10",
                "ticker": "AAA",
                "side": "SELL",
                "quantity": "3",
                "price": "$12.00",
                "total": "$36.00",
            }
        ],
        entry_prices={"AAA": 10.0},
    )

    assert records[0].profit_usd == 6.0
    assert records[0].profit_rate == 0.2


def test_fill_records_from_monitor_rows_uses_same_day_buy_before_later_sell() -> None:
    records = fill_records_from_monitor_rows(
        [
            {
                "date": "2026-05-22",
                "time": "10:03:00",
                "ticker": "AAA",
                "side": "SELL",
                "quantity": "10",
                "price": "$4.50",
                "total": "$45.00",
            },
            {
                "date": "2026-05-22",
                "time": "10:00:00",
                "ticker": "AAA",
                "side": "BUY",
                "quantity": "10",
                "price": "$2.00",
                "total": "$20.00",
            },
            {
                "date": "2026-05-22",
                "time": "10:01:00",
                "ticker": "AAA",
                "side": "SELL",
                "quantity": "10",
                "price": "$3.00",
                "total": "$30.00",
            },
            {
                "date": "2026-05-22",
                "time": "10:02:00",
                "ticker": "AAA",
                "side": "BUY",
                "quantity": "10",
                "price": "$4.00",
                "total": "$40.00",
            },
        ],
        entry_prices={"AAA": 9.0},
    )

    sell_records = [record for record in records if record.side == "SELL"]

    assert sell_records[0].profit_usd == 10.0
    assert sell_records[0].profit_rate == 0.5
    assert sell_records[1].profit_usd == 5.0
    assert sell_records[1].profit_rate == 0.125


def test_fill_records_from_monitor_rows_sorts_after_midnight_as_same_session_later() -> None:
    records = fill_records_from_monitor_rows(
        [
            {
                "date": "2026-05-22",
                "time": "00:03:00",
                "ticker": "AAA",
                "side": "SELL",
                "quantity": "10",
                "price": "$4.50",
                "total": "$45.00",
            },
            {
                "date": "2026-05-22",
                "time": "22:30:00",
                "ticker": "AAA",
                "side": "BUY",
                "quantity": "10",
                "price": "$2.00",
                "total": "$20.00",
            },
        ],
    )

    sell = [record for record in records if record.side == "SELL"][0]

    assert sell.profit_usd == 25.0
    assert sell.profit_rate == 1.25
