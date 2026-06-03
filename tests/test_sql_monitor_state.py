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
            ("22:43:00", "INFO", "Expanded screening universe to top 5 (10 tickers)."),
        ]

    def candidate_snapshot_status(self) -> tuple[object, ...]:
        return (
            4,
            "2026-05-29",
            56,
            "INFO",
            "CANDIDATE_SNAPSHOT_SAVED: 후보 56건을 DB에 저장했습니다.",
        )

    def recent_trading_stats(self, limit: int = 30) -> tuple[object, ...]:
        return (4, 3, 2, 1, 1)

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

    def latest_entry_profit_snapshots(self) -> list[tuple[object, ...]]:
        return [
            (
                "2026-05-22",
                "AAA",
                "Alpha",
                "22:41:10",
                12.5,
                -0.01,
                0.02,
                0.03,
                0.04,
                0.05,
                None,
                "TAKE_PROFIT",
                0.062,
                "STRICT_V1",
            ),
            (
                "2026-05-22",
                "BBB",
                "Beta",
                "22:45:10",
                10.0,
                -0.02,
                -0.01,
                -0.005,
                -0.003,
                None,
                None,
                "STOP_LOSS",
                -0.025,
                "STRICT_V1",
            ),
        ]

    def history_entry_profit_snapshots(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_entry_profit_snapshots()

    def history_logs(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_logs()

    def history_trades(self, trade_date) -> list[tuple[object, ...]]:
        return self.latest_trades()

    def history_run_summaries(self, trade_date) -> list[tuple[object, ...]]:
        return [
            (
                "2026-05-22",
                "hybrid",
                '{"stopLossPercent":5,"takeProfitPercent":10,"partialTakeProfitEnabled":true,'
                '"minTotalScore":40,'
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

    def entry_reason_performance(self) -> list[tuple[object, ...]]:
        return [("OPENING_BREAKOUT+NEWS_POSITIVE", 2, 15.5, 0.062, 0.5)]

    def closed_trade_analysis(self) -> list[tuple[object, ...]]:
        return [
            (
                "2026-05-22 22:40:00",
                "2026-05-22 23:10:00",
                "AAA",
                "Alpha",
                "OPENING_BREAKOUT+NEWS_POSITIVE+CHART_POSITIVE",
                "총점 87.5",
                "TAKE_PROFIT",
                30,
                0.062,
                15.5,
            ),
            (
                "2026-05-23 22:45:00",
                "2026-05-23 23:00:00",
                "BBB",
                "Beta",
                "OPENING_BREAKOUT+INTRADAY_RECHECK+CHART_POSITIVE",
                "15분 재평가 후보",
                "STOP_LOSS",
                15,
                -0.025,
                -5.0,
            ),
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
    assert state["candidateSnapshot"] == {
        "candidate_snapshot_days": 4,
        "latest_candidate_snapshot_date": "2026-05-29",
        "latest_candidate_snapshot_count": 56,
        "sample_sufficient": False,
        "minimum_required_candidate_days": 10,
        "minimum_required_trade_count": 30,
        "last_candidate_snapshot_status": "정보",
        "last_candidate_snapshot_message": "후보 스냅샷 저장 완료: 후보 56건을 DB에 저장했습니다.",
        "sample_warning": (
            "INSUFFICIENT_SAMPLE_FOR_STRATEGY_DECISION: "
            "후보 기준일 또는 거래 수가 부족하여 전략 성과 판단에 사용할 수 없습니다. "
            "최소 후보 기준일 10일 이상, 거래 수 30건 이상을 권장합니다."
        ),
    }
    assert state["trading_stats"] == {
        "lookback_days": 30,
        "total_trading_days": 4,
        "candidate_days": 3,
        "candidate_rate": 75.0,
        "scoring_days": 2,
        "scoring_rate": 50.0,
        "strict_filter_days": 1,
        "strict_filter_rate": 25.0,
        "selected_days": 1,
        "selected_rate": 25.0,
    }
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
                "entryReason": "",
                "entryReasonDetail": "",
                "profitUsd": "",
                "profitRate": "",
                "strategyVersion": "",
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
            "entryReason": "",
            "entryReasonDetail": "",
            "strategyVersion": "",
        }
    ]
    assert state["entryProfitSnapshots"][0] == {
        "ticker": "AAA",
        "ticker_name": "Alpha",
        "entry_date": "2026-05-22",
        "entry_time": "22:41:10",
        "entry_price": "$12.50",
        "profit_after_5m": "-1.00%",
        "profit_after_10m": "+2.00%",
        "profit_after_15m": "+3.00%",
        "profit_after_20m": "+4.00%",
        "profit_after_30m": "+5.00%",
        "profit_after_60m": "-",
        "final_exit_reason": "익절",
        "final_profit_rate": "+6.20%",
        "strategy_version": "STRICT_V1",
    }
    assert state["entryProfitSnapshotStats"] == {
        "sampleCount": 2,
        "sampleSufficient": False,
        "sampleWarning": "표본 부족: 전략 판단 금지",
        "negativeStats": [
            {"minutes": "5", "negativeCount": "2", "finalWinRate": "50.0%"},
            {"minutes": "10", "negativeCount": "1", "finalWinRate": "0.0%"},
            {"minutes": "15", "negativeCount": "1", "finalWinRate": "0.0%"},
            {"minutes": "20", "negativeCount": "1", "finalWinRate": "0.0%"},
        ],
    }
    assert state["logs"] == [
        ["22:40:00", "정보", "후보 3개를 점검했고, 최종 0개를 선정했습니다."],
        ["22:41:00", "정보", "필터 제외 사유: 시세 스냅샷 없음 2건, 가격 하한 미달 2건"],
        ["22:42:00", "주의", "진입 차단: 일일 손실 제한 도달"],
        ["22:43:00", "정보", "후보 수집 범위를 상위 5위까지 확대했습니다. (10종목)"],
    ]
    assert state["summary"] == {"realizedProfitUsd": "+$15.50"}
    assert state["entryReasonStats"] == [
        {
            "reason": "장초반 돌파 + 뉴스 긍정",
            "count": "2",
            "totalProfitUsd": "+$15.50",
            "averageProfitRate": "+6.20%",
            "winRate": "50.0%",
        }
    ]
    assert state["strategyStats"] == [
        {
            "strategy": "OPENING_BREAKOUT",
            "strategyText": "장초반 돌파",
            "count": "1",
            "winRate": "100.0%",
            "averageProfitRate": "+6.20%",
            "totalProfitUsd": "+$15.50",
            "averageHoldingMinutes": "30분",
            "maxDrawdown": "+0.00%",
        },
        {
            "strategy": "INTRADAY_RECHECK",
            "strategyText": "15분 재평가",
            "count": "1",
            "winRate": "0.0%",
            "averageProfitRate": "-2.50%",
            "totalProfitUsd": "-$5.00",
            "averageHoldingMinutes": "15분",
            "maxDrawdown": "-2.50%",
        },
    ]
    assert state["exitReasonStats"] == [
        {
            "exitReason": "STOP_LOSS",
            "exitReasonText": "손절",
            "count": "1",
            "winRate": "0.0%",
            "averageProfitRate": "-2.50%",
            "totalProfitUsd": "-$5.00",
        },
        {
            "exitReason": "TAKE_PROFIT",
            "exitReasonText": "익절",
            "count": "1",
            "winRate": "100.0%",
            "averageProfitRate": "+6.20%",
            "totalProfitUsd": "+$15.50",
        },
    ]
    assert state["recentTrades"][0] == {
        "entryAt": "2026-05-22 22:40:00",
        "exitAt": "2026-05-22 23:10:00",
        "ticker": "AAA",
        "name": "Alpha",
        "entryStrategy": "OPENING_BREAKOUT",
        "entryStrategyText": "장초반 돌파",
        "entryTags": "뉴스 긍정, 차트 조건 양호",
        "exitReason": "TAKE_PROFIT",
        "exitReasonText": "익절",
        "holdingTime": "30분",
        "profitRate": "+6.20%",
        "profitUsd": "+$15.50",
        "strategyVersion": "-",
    }


def test_sql_monitor_state_translates_structured_log_messages() -> None:
    class StructuredLogRepository(Repository):
        def latest_logs(self) -> list[tuple[object, ...]]:
            return [
                (
                    "22:50:00",
                    "INFO",
                    "[PIPELINE] requested_gainer_limit=100 received_gainer_count=100 "
                    "requested_turnover_limit=100 received_turnover_count=100 "
                    "requested_trade_value_limit=100 received_trade_value_count=100 "
                    "gainers_count=100 volume_count=100 intersection_count=5 "
                    "trade_value_count=100 ranking_union_count=260 snapshot_success_count=5 "
                    "snapshot_fail_count=0 risk_pass_count=0 scoring_pass_count=0 "
                    "final_selected_count=0",
                ),
                (
                    "22:50:01",
                    "INFO",
                    "[FILTER] removed_by_price=3 removed_by_gap=1 removed_by_volume_ratio=1 "
                    "removed_by_opening_change=0 removed_by_score=0 final_count=0",
                ),
                (
                    "22:50:02",
                    "INFO",
                    "[PIPELINE_SUMMARY] requested_gainer_limit=100 received_gainer_count=100 "
                    "requested_turnover_limit=100 received_turnover_count=100 "
                    "requested_trade_value_limit=100 received_trade_value_count=100 "
                    "gainers=100 volume=100 trade_value=100 intersection=5 ranking_union=260 "
                    "snapshot_success=5 snapshot_fail=0 risk_pass=0 score_pass=0 "
                    "saved=0 duration_ms=1234",
                ),
                (
                    "22:50:03",
                    "INFO",
                    "[SAVE_TARGETS] candidate_count=5 trade_date=2026-06-01",
                ),
                (
                    "22:50:04",
                    "INFO",
                    "[SAVE_SCORES] score_count=5 trade_date=2026-06-01",
                ),
                (
                    "22:50:05",
                    "WARNING",
                    "[MISSING_SNAPSHOT] ticker=AAPL reason=daily_prices_empty",
                ),
            ]

    state = SqlMonitorStateSource(StructuredLogRepository()).read()

    assert [row[2] for row in state["logs"]] == [
        (
            "후보 생성 단계: 상승률 요청 100건, 상승률 수신 100건, "
            "거래량 요청 100건, 거래량 수신 100건, 거래대금 요청 100건, "
            "거래대금 수신 100건, 상승률 랭킹 100건, 거래량 랭킹 100건, "
            "교집합 5건, 거래대금 랭킹 100건, 합집합 260건, "
            "시세 조회 성공 5건, 시세 조회 실패 0건, 필터 통과 후보 0건, "
            "점수 통과 후보 0건, 최종 선정 후보 0건"
        ),
        (
            "필터 제외 현황: 가격 조건 제외 3건, 갭 조건 제외 1건, "
            "거래량 비율 제외 1건, 장초반 상승률 제외 0건, 점수 기준 제외 0건, "
            "최종 후보 0건"
        ),
        (
            "후보 생성 요약: 상승률 요청 100건, 상승률 수신 100건, "
            "거래량 요청 100건, 거래량 수신 100건, 거래대금 요청 100건, "
            "거래대금 수신 100건, 상승률 랭킹 100건, 거래량 랭킹 100건, "
            "거래대금 랭킹 100건, 교집합 5건, 합집합 260건, "
            "시세 조회 성공 5건, 시세 조회 실패 0건, 필터 통과 후보 0건, "
            "점수 통과 후보 0건, DB 저장 후보 0건, 소요 시간 1234ms"
        ),
        "후보 저장: 후보 수 5건, 거래일 2026-06-01",
        "점수 저장: 점수 수 5건, 거래일 2026-06-01",
        "시세 스냅샷 누락: 종목 AAPL, 사유 일봉 데이터 없음",
    ]


def test_sql_monitor_state_translates_candidate_evaluation_log_messages() -> None:
    class CandidateEvaluationLogRepository(Repository):
        def latest_logs(self) -> list[tuple[object, ...]]:
            return [
                (
                    "01:32:19",
                    "INFO",
                    "candidate_evaluation_saved symbol=NVTS final_score=65.875 "
                    "buy_allowed=True order_submitted=False buy_block_reason=BUY_ALLOWED "
                    "hard_filter_failed_count=0 soft_condition_failed_count=1 "
                    "vwap_ma20_status=DISABLED",
                ),
                (
                    "01:22:56",
                    "INFO",
                    "candidate_evaluation_saved symbol=ANY final_score=55.5 "
                    "buy_allowed=False order_submitted=False "
                    "buy_block_reason=OVERHEAT_LIMIT_EXCEEDED hard_filter_failed_count=1 "
                    "soft_condition_failed_count=1 vwap_ma20_status=DISABLED",
                ),
            ]

    state = SqlMonitorStateSource(CandidateEvaluationLogRepository()).read()

    assert [row[2] for row in state["logs"][:2]] == [
        (
            "후보평가 저장: 종목=NVTS 최종점수=65.875 매수허용=예 주문제출=아니오 "
            "매수판정=매수 허용 하드필터탈락=0 소프트조건탈락=1 VWAP/MA20상태=비활성화"
        ),
        (
            "후보평가 저장: 종목=ANY 최종점수=55.5 매수허용=아니오 주문제출=아니오 "
            "매수판정=과열 제한 초과 하드필터탈락=1 소프트조건탈락=1 VWAP/MA20상태=비활성화"
        ),
    ]


def test_sql_monitor_history_includes_daily_run_summary() -> None:
    state = SqlMonitorStateSource(Repository()).read_history(date(2026, 5, 22))

    assert state["runSummaries"] == [
        {
            "date": "2026-05-22",
            "updatedAt": "05:00:00",
            "mode": "장초반+15분 새로운 종목 수집",
            "settings": (
                "손절 5% · 익절 10% · 선정점수 40점 · 가격 $1~$150 · "
                "상승률 0% · 거래량 0.5배 · 갭 50% · 분할익절 사용"
            ),
            "stopLossPercent": "5%",
            "takeProfitPercent": "10%",
            "partialTakeProfit": "사용",
            "minTotalScore": "40점",
            "priceRange": "$1~$150",
            "minOpeningPriceChangePercent": "0%",
            "minVolumeRatio": "0.5배",
            "maxOpeningGapPercent": "50%",
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


def test_sql_monitor_state_marks_strict_filter_shortfall_without_scores() -> None:
    class StrictFilterRepository(PendingScoreRepository):
        def latest_logs(self) -> list[tuple[object, ...]]:
            return [
                (
                    "22:36:14",
                    "WARNING",
                    "STRICT_FILTER_NO_CANDIDATES: 엄격 필터 기준을 만족한 후보가 부족합니다.",
                ),
                (
                    "22:36:14",
                    "INFO",
                    "[PIPELINE] gainers_count=100 volume_count=100 intersection_count=5 "
                    "snapshot_success_count=5 snapshot_fail_count=0 risk_pass_count=0 "
                    "scoring_pass_count=0 final_selected_count=0",
                ),
            ]

    state = SqlMonitorStateSource(StrictFilterRepository()).read()

    assert state["targets"][0][7] == "최소 후보 수 미달로 점수 계산 생략"


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
                ("FFF", "SELL", 10, 1, "PARTIAL_TAKE_PROFIT"),
            ]

    state = SqlMonitorStateSource(ExitRepository()).read()

    assert [item["exitReason"] for item in state["trades"]] == [
        "손절",
        "익절",
        "트레일링 스탑",
        "수동 매도",
        "전량 수동 매도",
        "분할 익절",
    ]
