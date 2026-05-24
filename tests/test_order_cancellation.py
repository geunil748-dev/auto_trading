from trading_bot.order_cancellation import cancel_unfilled_orders, unfilled_cancel_requests


def test_unfilled_cancel_requests_require_order_number_and_quantity() -> None:
    rows = [
        {"pdno": "AAA", "odno": "111", "nccs_qty": "2"},
        {"pdno": "BBB", "odno": "222", "nccs_qty": "0"},
        {"pdno": "CCC", "nccs_qty": "3"},
    ]

    assert unfilled_cancel_requests(rows) == [
        {
            "ticker": "AAA",
            "order_no": "111",
            "quantity": 2,
            "appointed_order_no": "",
        }
    ]


def test_cancel_unfilled_orders_submits_each_request() -> None:
    calls: list[dict[str, object]] = []

    cancelled = cancel_unfilled_orders(
        [{"PDNO": "AAA", "ODNO": "111", "NCCS_QTY": "2"}],
        lambda request: calls.append(request) or {"ok": True},
    )

    assert cancelled == calls
    assert cancelled[0]["ticker"] == "AAA"
