from trading_bot.sql_monitor_state import SqlMonitorStateSource


class Repository:
    def latest_targets(self) -> list[tuple[object, ...]]:
        return [("AAA", "Alpha", 180, 4.2)]

    def latest_scores(self) -> list[tuple[object, ...]]:
        return [("AAA", 95, 80, 87.5, True)]

    def latest_holdings(self) -> list[tuple[object, ...]]:
        return [("AAA", "Alpha", 2, 10.5, 11.1, 11.6, 23.2)]

    def latest_logs(self) -> list[tuple[object, ...]]:
        return [
            ("22:40:00", "INFO", "Screened 3 targets and selected 0."),
            ("22:41:00", "INFO", "Filter rejects: MISSING_SNAPSHOT=2, PENNY_STOCK=2."),
            ("22:42:00", "WARNING", "Entry blocked: DAILY_ACCOUNT_LOSS"),
        ]

    def latest_trades(self) -> list[tuple[object, ...]]:
        return [("AAA", "BUY", 12.5, 2, None)]

    def latest_fills(self) -> list[tuple[object, ...]]:
        return [("2026-05-22", "22:41:10", "AAA", "Alpha", "매수", 2, 12.5, 25.0)]

    def today_realized_profit(self) -> float:
        return 15.5

    def history_targets(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_targets()

    def history_scores(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_scores()

    def history_holdings(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_holdings()

    def history_fills(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_fills()

    def history_logs(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_logs()

    def history_trades(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_trades()

    def history_realized_profit(self, trade_date) -> float:
        return self.today_realized_profit()


def test_sql_monitor_state_shapes_dashboard_rows() -> None:
    state = SqlMonitorStateSource(Repository()).read()

    assert state["targets"][0][:6] == ["AAA", "Alpha", "-", "180%", "+4.2%", "88"]
    assert state["holdings"] == [
        {
            "ticker": "AAA",
            "name": "Alpha",
            "quantity": "2",
            "averagePrice": "$10.50",
            "openPrice": "$11.10",
            "closePrice": "$11.60",
            "totalPrice": "$23.20",
        }
    ]
    assert state["targets"][0][6]
    assert state["trades"] == [
        {
            "ticker": "AAA",
            "type": "매수",
            "price": "$12.50",
            "quantity": "2",
            "exitReason": "",
            "profitUsd": "",
            "profitRate": "",
        }
    ]
    assert state["fills"] == [
        {
            "date": "2026-05-22",
            "time": "22:41:10",
            "filledAt": "2026-05-22 22:41:10",
            "ticker": "AAA",
            "name": "Alpha",
            "side": "매수",
            "quantity": "2",
            "price": "$12.50",
            "total": "$25.00",
            "profitUsd": "",
            "profitRate": "",
        }
    ]
    assert state["logs"] == [
        ["22:40:00", "정보", "후보 3개를 점검했고, 최종 0개를 선정했습니다."],
        ["22:41:00", "정보", "필터 제외 사유: 시세 스냅샷 없음 2건, 가격 하한 미달 2건"],
        ["22:42:00", "주의", "진입 차단: 일일 손실 제한 도달"],
    ]
    assert state["summary"] == {"realizedProfitUsd": "+$15.50"}


class PendingScoreRepository(Repository):
    def latest_scores(self) -> list[tuple[object, ...]]:
        return []


def test_sql_monitor_state_shows_filter_score_before_total_score_exists() -> None:
    state = SqlMonitorStateSource(PendingScoreRepository()).read()

    assert state["targets"][0][:6] == ["AAA", "Alpha", "-", "180%", "+4.2%", "76"]
    assert state["targets"][0][6] == "필터점수"
