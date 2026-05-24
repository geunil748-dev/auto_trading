import json

from trading_bot.daily_report import write_daily_report


def test_write_daily_report_persists_close_summary(tmp_path) -> None:
    path = write_daily_report(
        tmp_path,
        "20260522",
        {"orders": [{"ticker": "AAA"}], "fills": [], "holdings": [], "gates": [], "logs": []},
        [{"ticker": "BBB", "order_no": "1", "quantity": 2}],
        1,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "20260522.json"
    assert payload["cancelledOrders"][0]["ticker"] == "BBB"
    assert payload["eodSellCount"] == 1
