from datetime import datetime
from zoneinfo import ZoneInfo

from trading_bot.order_cancellation import (
    cancel_unfilled_orders,
    stale_unfilled_buy_cancel_requests,
    unfilled_cancel_requests,
)


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


def test_stale_unfilled_buy_cancel_requests_waits_for_age_and_retry_limit() -> None:
    now = datetime(2026, 5, 29, 23, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    rows = [
        {
            "pdno": "AAA",
            "odno": "111",
            "nccs_qty": "2",
            "ord_tmd": "230700",
            "sll_buy_dvsn_cd_name": "매수",
        },
        {
            "pdno": "BBB",
            "odno": "222",
            "nccs_qty": "1",
            "ord_tmd": "230930",
            "sll_buy_dvsn_cd_name": "매수",
        },
        {
            "pdno": "CCC",
            "odno": "333",
            "nccs_qty": "1",
            "ord_tmd": "230100",
            "sll_buy_dvsn_cd_name": "매도",
        },
        {
            "pdno": "DDD",
            "odno": "444",
            "nccs_qty": "1",
            "ord_tmd": "230100",
            "sll_buy_dvsn_cd_name": "매수",
        },
    ]

    assert stale_unfilled_buy_cancel_requests(
        rows,
        max_age_minutes=2,
        retried_tickers={"DDD"},
        now=now,
    ) == [
        {
            "ticker": "AAA",
            "order_no": "111",
            "quantity": 2,
            "appointed_order_no": "",
        }
    ]


def test_stale_unfilled_buy_cancel_requests_can_use_seconds_policy() -> None:
    now = datetime(2026, 5, 29, 23, 10, 30, tzinfo=ZoneInfo("Asia/Seoul"))
    rows = [
        {
            "pdno": "AAA",
            "odno": "111",
            "nccs_qty": "2",
            "ord_tmd": "230000",
            "sll_buy_dvsn_cd_name": "매수",
        },
        {
            "pdno": "BBB",
            "odno": "222",
            "nccs_qty": "1",
            "ord_tmd": "231000",
            "sll_buy_dvsn_cd_name": "매수",
        },
    ]

    requests = stale_unfilled_buy_cancel_requests(
        rows,
        max_age_minutes=99,
        max_age_seconds=60,
        now=now,
    )

    assert [item["ticker"] for item in requests] == ["AAA"]
