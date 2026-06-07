from trading_bot.scheduler_logging import safe_exception_summary, safe_scheduler_log


def test_safe_exception_summary_returns_type_name_without_message() -> None:
    exc = RuntimeError("MSSQL_PASSWORD=secret")

    assert safe_exception_summary(exc) == "RuntimeError"
    assert "secret" not in safe_exception_summary(exc)


def test_safe_scheduler_log_ignores_db_log_failure(monkeypatch) -> None:
    def fail_repository(connect):
        raise RuntimeError("MSSQL_PASSWORD=secret")

    monkeypatch.setattr("trading_bot.scheduler_logging.SqlServerDailyRepository", fail_repository)
    monkeypatch.setattr("trading_bot.scheduler_logging.pyodbc_connect_factory", lambda: object)

    safe_scheduler_log(
        "WARNING",
        "scheduler",
        "TEST_FAILED: RuntimeError",
        reject_reason="TEST_FAILED",
    )
