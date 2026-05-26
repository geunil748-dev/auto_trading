from trading_bot.sql_monitor_state import SqlMonitorStateSource


class Repository:
    def latest_targets(self) -> list[tuple[object, ...]]:
        return [("AAA", "Alpha", 180, 4.2)]

    def latest_scores(self) -> list[tuple[object, ...]]:
        return [("AAA", 95, 80, 87.5, True)]

    def latest_logs(self) -> list[tuple[object, ...]]:
        return [("22:40:00", "INFO", "stored")]

    def latest_trades(self) -> list[tuple[object, ...]]:
        return [("AAA", "BUY", 12.5, 2, None)]


def test_sql_monitor_state_shapes_dashboard_rows() -> None:
    state = SqlMonitorStateSource(Repository()).read()

    assert state["targets"][0][:6] == ["AAA", "Alpha", "-", "180%", "+4.2%", "88"]
    assert state["targets"][0][6]
    assert state["trades"] == [
        {"ticker": "AAA", "type": "BUY", "price": "$12.50", "quantity": "2", "exitReason": ""}
    ]
    assert state["logs"] == [["22:40:00", "INFO", "stored"]]
