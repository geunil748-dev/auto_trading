from __future__ import annotations

from datetime import date

from trading_bot.monitor_runner_profile import target_runner_profiles
from trading_bot.repositories import SqlServerMonitorRepository
from trading_bot.sql_monitor_formatters import (
    _account,
    _candidate_snapshot_status,
    _closed_trade_analysis,
    _daily_summary_report,
    _daily_summary_report_detail,
    _entry_profit_snapshot,
    _entry_profit_snapshot_stats,
    _entry_reason_stat,
    _exit_reason_stats,
    _fill,
    _holding,
    _log,
    _missing_score_decision,
    _order,
    _recent_trade,
    _run_summary,
    _strategy_stats,
    _summary,
    _target,
    _trade,
    _trading_stats,
)
from trading_bot.trading_date import current_trade_date


class SqlMonitorStateSource:
    def __init__(self, repository: SqlServerMonitorRepository) -> None:
        self.repository = repository

    def read(self) -> dict[str, object]:
        scores = {row[0]: row for row in self.repository.latest_scores()}
        evaluations = _evaluations_by_ticker(
            self.repository.latest_candidate_evaluations()
            if hasattr(self.repository, "latest_candidate_evaluations")
            else []
        )
        logs = self.repository.latest_logs()
        missing_score_decision = _missing_score_decision(logs)
        target_rows = self.repository.latest_targets()
        account = self.repository.latest_account(is_mock=True)
        real_account = self.repository.latest_account(is_mock=False)
        realized_profit = self.repository.today_realized_profit()
        realized_profit_rate = self.repository.today_realized_profit_rate()
        closed_trades = _closed_trade_analysis(self.repository.closed_trade_analysis())
        entry_profit_snapshots = [
            _entry_profit_snapshot(row)
            for row in self.repository.latest_entry_profit_snapshots()
        ]
        return {
            "date": current_trade_date().isoformat(),
            "account": _account(account, realized_profit, realized_profit_rate),
            "realAccount": _account(real_account, 0.0),
            "candidateSnapshot": _candidate_snapshot_status(
                self.repository.candidate_snapshot_status()
            ),
            "trading_stats": _trading_stats(self.repository.recent_trading_stats()),
            "targetRunnerProfiles": target_runner_profiles(target_rows, scores, evaluations),
            "targets": [
                _target(row, scores.get(row[0]), missing_score_decision)
                for row in target_rows
            ],
            "positions": [],
            "holdings": [_holding(row) for row in self.repository.latest_holdings()],
            "orders": [_order(row) for row in self.repository.latest_orders()],
            "fills": [_fill(row) for row in self.repository.latest_fills()],
            "gates": [
                ["저장소", "MSSQL"],
                ["점수 기록", str(len(scores))],
            ],
            "logs": [_log(row) for row in logs],
            "trades": [_trade(row) for row in self.repository.latest_trades()],
            "entryReasonStats": [
                _entry_reason_stat(row)
                for row in self.repository.entry_reason_performance()
            ],
            "strategyStats": _strategy_stats(closed_trades),
            "exitReasonStats": _exit_reason_stats(closed_trades),
            "recentTrades": [_recent_trade(row) for row in closed_trades[:30]],
            "entryProfitSnapshots": entry_profit_snapshots,
            "entryProfitSnapshotStats": _entry_profit_snapshot_stats(entry_profit_snapshots),
            "summary": _summary(realized_profit),
            "chart": {"closes": [], "movingAverage": []},
        }

    def read_history(self, trade_date: date) -> dict[str, object]:
        scores = {row[0]: row for row in self.repository.history_scores(trade_date)}
        evaluations = _evaluations_by_ticker(
            self.repository.history_candidate_evaluations(trade_date)
            if hasattr(self.repository, "history_candidate_evaluations")
            else []
        )
        logs = self.repository.history_logs(trade_date)
        missing_score_decision = _missing_score_decision(logs)
        target_rows = self.repository.history_targets(trade_date)
        account = self.repository.history_account(trade_date)
        realized_profit = self.repository.history_realized_profit(trade_date)
        realized_profit_rate = self.repository.history_realized_profit_rate(trade_date)
        closed_trades = _closed_trade_analysis(self.repository.closed_trade_analysis())
        entry_profit_snapshots = [
            _entry_profit_snapshot(row)
            for row in self.repository.history_entry_profit_snapshots(trade_date)
        ]
        return {
            "date": trade_date.isoformat(),
            "account": _account(account, realized_profit, realized_profit_rate),
            "targetRunnerProfiles": target_runner_profiles(target_rows, scores, evaluations),
            "targets": [
                _target(row, scores.get(row[0]), missing_score_decision)
                for row in target_rows
            ],
            "holdings": [_holding(row) for row in self.repository.history_holdings(trade_date)],
            "orders": [_order(row) for row in self.repository.history_orders(trade_date)],
            "fills": [_fill(row) for row in self.repository.history_fills(trade_date)],
            "logs": [_log(row) for row in logs],
            "trades": [_trade(row) for row in self.repository.history_trades(trade_date)],
            "runSummaries": [
                _run_summary(row)
                for row in self.repository.history_run_summaries(trade_date)
            ],
            "entryReasonStats": [
                _entry_reason_stat(row)
                for row in self.repository.entry_reason_performance()
            ],
            "strategyStats": _strategy_stats(closed_trades),
            "exitReasonStats": _exit_reason_stats(closed_trades),
            "recentTrades": [_recent_trade(row) for row in closed_trades[:30]],
            "entryProfitSnapshots": entry_profit_snapshots,
            "entryProfitSnapshotStats": _entry_profit_snapshot_stats(entry_profit_snapshots),
            "summary": _summary(realized_profit),
        }

    def read_daily_summaries(
        self,
        mode: str | None = None,
        limit: int = 30,
    ) -> dict[str, object]:
        return {
            "summaries": [
                _daily_summary_report(row)
                for row in self.repository.daily_trade_summary_reports(mode, limit)
            ]
        }

    def read_daily_summary_detail(
        self,
        trade_date: date,
        mode: str,
    ) -> dict[str, object]:
        row = self.repository.daily_trade_summary_report_detail(trade_date, mode)
        return {"summary": None if row is None else _daily_summary_report_detail(row)}


def _evaluations_by_ticker(rows: list[tuple[object, ...]]) -> dict[str, tuple[object, ...]]:
    return {str(row[0]).strip().upper(): row for row in rows if row and row[0]}
