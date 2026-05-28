from datetime import date

from trading_bot.sql_monitor_state import SqlMonitorStateSource


class Repository:
    def latest_targets(self) -> list[tuple[object, ...]]:
        return [("AAA", "Alpha", 180, 4.2)]

    def latest_scores(self) -> list[tuple[object, ...]]:
        return [("AAA", 95, 80, 87.5, True)]

    def latest_holdings(self) -> list[tuple[object, ...]]:
        return [("AAA", "Alpha", 2, 10.5, 11.1, 11.6, 23.2)]

    def latest_account(self, is_mock: bool = True) -> tuple[object, ...]:
        return (1000.0, 1250.0, 250.0, 1, 1.25, 15.5)

    def latest_orders(self) -> list[tuple[object, ...]]:
        return [("2026-05-22", "22:40:10", "AAA", "Alpha", "BUY", 2, 12.5, 0, "1001")]

    def latest_logs(self) -> list[tuple[object, ...]]:
        return [
            ("22:40:00", "INFO", "Screened 3 targets and selected 0."),
            ("22:41:00", "INFO", "Filter rejects: MISSING_SNAPSHOT=2, PENNY_STOCK=2."),
            ("22:42:00", "WARNING", "Entry blocked: DAILY_ACCOUNT_LOSS"),
        ]

    def latest_trades(self) -> list[tuple[object, ...]]:
        return [
            (
                "2026-05-22",
                "2026-05-22 22:40:11",
                "AAA",
                "Alpha",
                "SELL",
                12.5,
                2,
                "EOD",
                None,
                None,
            )
        ]

    def latest_fills(self) -> list[tuple[object, ...]]:
        return [("2026-05-22", "22:41:10", "AAA", "Alpha", "매수", 2, 12.5, 25.0)]

    def today_realized_profit(self) -> float:
        return 15.5

    def today_realized_profit_rate(self) -> float:
        return 6.2

    def history_targets(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_targets()

    def history_scores(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_scores()

    def history_holdings(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_holdings()

    def history_account(self, trade_date) -> tuple[object, ...]:
        return self.latest_account()

    def history_orders(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_orders()

    def history_fills(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_fills()

    def history_logs(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_logs()

    def history_trades(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_trades()

    def history_run_summaries(self, trade_date) -> list[tuple[object, ...]]:
        return [
            (
                "2026-05-22",
                "hybrid",
                '{"stopLossPercent":5,"takeProfitPercent":10,"minTotalScore":40,'
                '"minPriceUsd":1,"maxPriceUsd":150,"minOpeningPriceChangePercent":0,'
                '"minVolumeRatio":0.5,"maxOpeningGapPercent":50}',
                15.5,
                6.2,
                3,
                1,
                4,
                2,
                "2026-05-23 05:00:00",
            )
        ]

    def history_realized_profit(self, trade_date) -> float:
        return self.today_realized_profit()

    def history_realized_profit_rate(self, trade_date) -> float:
        return self.today_realized_profit_rate()


def test_sql_monitor_state_shapes_dashboard_rows() -> None:
    state = SqlMonitorStateSource(Repository()).read()

    assert state["targets"][0][:7] == ["AAA", "Alpha", "-", "-", "180%", "+4.2%", "88"]
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
    assert state["targets"][0][7]
    assert state["account"] == {
        "cashUsd": "$1,000.00",
        "equityUsd": "$1,250.00",
        "investedUsd": "$250.00",
        "cashKrw": "-",
        "equityKrw": "-",
        "openPositions": "1",
        "dailyProfitRate": "6.20%",
        "realizedProfitUsd": "+$15.50",
    }
    assert state["orders"] == [
        {
            "date": "2026-05-22",
            "time": "22:40:10",
            "ticker": "AAA",
            "name": "Alpha",
            "side": "매수",
            "quantity": "2",
            "price": "$12.50",
            "unfilled": "0",
            "orderNo": "1001",
        }
    ]
    assert state["trades"] == [
        {
            "date": "2026-05-22",
            "time": "22:40:11",
            "orderedAt": "2026-05-22 22:40:11",
            "ticker": "AAA",
            "name": "Alpha",
            "type": "매도",
            "price": "$12.50",
            "quantity": "2",
            "exitReason": "장마감 매도",
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


def test_sql_monitor_history_includes_daily_run_summary() -> None:
    state = SqlMonitorStateSource(Repository()).read_history(date(2026, 5, 22))

    assert state["runSummaries"] == [
        {
            "date": "2026-05-22",
            "updatedAt": "05:00:00",
            "mode": "장초반+15분 새로운 종목 수집",
            "settings": (
                "손절 5% · 익절 10% · 선정점수 40점 · 가격 $1~$150 · "
                "상승률 0% · 거래량 0.5배 · 갭 50%"
            ),
            "profitUsd": "+$15.50",
            "profitRate": "+6.20%",
            "eodSellCount": "3",
            "cancelledOrderCount": "1",
            "buyFillCount": "4",
            "sellFillCount": "2",
        }
    ]


class PendingScoreRepository(Repository):
    def latest_scores(self) -> list[tuple[object, ...]]:
        return []


def test_sql_monitor_state_shows_filter_score_before_total_score_exists() -> None:
    state = SqlMonitorStateSource(PendingScoreRepository()).read()

    assert state["targets"][0][:7] == ["AAA", "Alpha", "-", "-", "180%", "+4.2%", "76"]
    assert state["targets"][0][7] == "점수 계산 전"


def test_sql_monitor_state_marks_unselected_target_decision() -> None:
    class UnselectedScoreRepository(Repository):
        def latest_scores(self) -> list[tuple[object, ...]]:
            return [("AAA", 30, 40, 35, False)]

    state = SqlMonitorStateSource(UnselectedScoreRepository()).read()

    assert state["targets"][0][7] == "선정점수/순위 미달"


def test_sql_monitor_state_translates_exit_reasons() -> None:
    class ExitRepository(Repository):
        def latest_trades(self) -> list[tuple[object, ...]]:
            return [
                ("AAA", "SELL", 10, 1, "STOP_LOSS"),
                ("BBB", "SELL", 10, 1, "TAKE_PROFIT"),
                ("CCC", "SELL", 10, 1, "TRAILING_STOP"),
                ("DDD", "SELL", 10, 1, "MANUAL_SELL"),
                ("EEE", "SELL", 10, 1, "MANUAL_SELL_ALL"),
            ]

    state = SqlMonitorStateSource(ExitRepository()).read()

    assert [item["exitReason"] for item in state["trades"]] == [
        "손절",
        "익절",
        "트레일링 스탑",
        "수동 매도",
        "전량 수동 매도",
    ]
