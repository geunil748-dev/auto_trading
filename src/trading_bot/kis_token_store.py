from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from trading_bot.adapters.kis_http import AccessToken


class Cursor(Protocol):
    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any: ...

    def fetchall(self) -> list[Any]: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...

    def commit(self) -> None: ...

    def close(self) -> None: ...


class SqlServerKisTokenStore:
    """KIS access token cache shared by all servers through MSSQL."""

    def __init__(
        self,
        connect: Callable[[], Connection],
        sleep: Callable[[float], None],
        lock_timeout_ms: int = 10000,
    ) -> None:
        self.connect = connect
        self.sleep = sleep
        self.lock_timeout_ms = lock_timeout_ms

    def read_valid(
        self,
        environment: str,
        app_key_hash: str,
        now: datetime,
        refresh_margin_seconds: int,
    ) -> AccessToken | None:
        self._ensure_table()
        with closing(self.connect()) as connection:
            token = self._read_valid(connection, environment, app_key_hash, now, refresh_margin_seconds)
            if token is not None:
                self._touch_last_used(connection, environment, app_key_hash)
                connection.commit()
            return token

    def refresh_with_lock(
        self,
        environment: str,
        app_key_hash: str,
        now: datetime,
        refresh_margin_seconds: int,
        refresh: Callable[[], AccessToken],
    ) -> AccessToken:
        self._ensure_table()
        lock_name = f"kis_token_refresh:{environment}:{app_key_hash[:16]}"
        with closing(self.connect()) as connection:
            if not self._acquire_lock(connection, lock_name):
                self.sleep(1)
                token = self._read_valid(
                    connection,
                    environment,
                    app_key_hash,
                    now,
                    refresh_margin_seconds,
                )
                if token is not None:
                    self._touch_last_used(connection, environment, app_key_hash)
                    connection.commit()
                    return token
                raise RuntimeError("KIS 토큰 갱신 락을 획득하지 못했습니다.")

            try:
                token = self._read_valid(
                    connection,
                    environment,
                    app_key_hash,
                    now,
                    refresh_margin_seconds,
                )
                if token is None:
                    token = refresh()
                    self._upsert(connection, environment, app_key_hash, token)
                else:
                    self._touch_last_used(connection, environment, app_key_hash)
                connection.commit()
                return token
            finally:
                self._release_lock(connection, lock_name)

    def _ensure_table(self) -> None:
        with closing(self.connect()) as connection:
            connection.cursor().execute(KIS_TOKEN_CACHE_SCHEMA)
            connection.commit()

    def _read_valid(
        self,
        connection: Connection,
        environment: str,
        app_key_hash: str,
        now: datetime,
        refresh_margin_seconds: int,
    ) -> AccessToken | None:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT access_token, token_type, expires_at
            FROM dbo.KisTokenCache
            WHERE environment = ? AND app_key_hash = ?
            """,
            (environment, app_key_hash),
        )
        row = _fetchone(cursor)
        if row is None:
            return None
        access_token, token_type, expires_at = row[0], row[1], row[2]
        expires_at_utc = _as_utc(expires_at)
        if now + timedelta(seconds=refresh_margin_seconds) >= expires_at_utc:
            return None
        return AccessToken(str(access_token), expires_at_utc, str(token_type or "Bearer"))

    def _touch_last_used(
        self,
        connection: Connection,
        environment: str,
        app_key_hash: str,
    ) -> None:
        connection.cursor().execute(
            """
            UPDATE dbo.KisTokenCache
            SET last_used_at = SYSUTCDATETIME(), updated_at = SYSUTCDATETIME()
            WHERE environment = ? AND app_key_hash = ?
            """,
            (environment, app_key_hash),
        )

    def _upsert(
        self,
        connection: Connection,
        environment: str,
        app_key_hash: str,
        token: AccessToken,
    ) -> None:
        connection.cursor().execute(
            """
            IF EXISTS (
                SELECT 1 FROM dbo.KisTokenCache
                WHERE environment = ? AND app_key_hash = ?
            )
            BEGIN
                UPDATE dbo.KisTokenCache
                SET access_token = ?,
                    token_type = ?,
                    expires_at = ?,
                    issued_at = SYSUTCDATETIME(),
                    last_used_at = SYSUTCDATETIME(),
                    updated_at = SYSUTCDATETIME()
                WHERE environment = ? AND app_key_hash = ?
            END
            ELSE
            BEGIN
                INSERT INTO dbo.KisTokenCache (
                    environment,
                    app_key_hash,
                    access_token,
                    token_type,
                    expires_at,
                    issued_at,
                    last_used_at
                )
                VALUES (?, ?, ?, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME())
            END
            """,
            (
                environment,
                app_key_hash,
                token.value,
                token.token_type,
                _to_db_datetime(token.expires_at),
                environment,
                app_key_hash,
                environment,
                app_key_hash,
                token.value,
                token.token_type,
                _to_db_datetime(token.expires_at),
            ),
        )

    def _acquire_lock(self, connection: Connection, lock_name: str) -> bool:
        cursor = connection.cursor()
        cursor.execute(
            """
            DECLARE @result INT;
            EXEC @result = sp_getapplock
                @Resource = ?,
                @LockMode = 'Exclusive',
                @LockOwner = 'Session',
                @LockTimeout = ?;
            SELECT @result;
            """,
            (lock_name, self.lock_timeout_ms),
        )
        row = _fetchone(cursor)
        return row is not None and int(row[0]) >= 0

    def _release_lock(self, connection: Connection, lock_name: str) -> None:
        connection.cursor().execute(
            """
            EXEC sp_releaseapplock @Resource = ?, @LockOwner = 'Session';
            """,
            (lock_name,),
        )


KIS_TOKEN_CACHE_SCHEMA = """
IF OBJECT_ID(N'dbo.KisTokenCache', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.KisTokenCache (
        id INT IDENTITY PRIMARY KEY,
        environment VARCHAR(10) NOT NULL,
        app_key_hash VARCHAR(64) NOT NULL,
        access_token NVARCHAR(2048) NOT NULL,
        token_type VARCHAR(20) NOT NULL DEFAULT 'Bearer',
        expires_at DATETIME2(0) NOT NULL,
        issued_at DATETIME2(0) NOT NULL DEFAULT SYSUTCDATETIME(),
        last_used_at DATETIME2(0) NULL,
        created_at DATETIME2(0) NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at DATETIME2(0) NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_KisTokenCache_environment_app_key_hash
            UNIQUE (environment, app_key_hash)
    );
END;
"""


def _as_utc(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif all(hasattr(value, item) for item in ("Year", "Month", "Day", "Hour", "Minute", "Second")):
        parsed = datetime(
            int(value.Year),
            int(value.Month),
            int(value.Day),
            int(value.Hour),
            int(value.Minute),
            int(value.Second),
        )
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_db_datetime(value: datetime) -> datetime:
    normalized = value.astimezone(timezone.utc) if value.tzinfo else value
    return normalized.replace(tzinfo=None, microsecond=0)


def _fetchone(cursor: Cursor) -> Any | None:
    fetchone = getattr(cursor, "fetchone", None)
    if callable(fetchone):
        return fetchone()
    rows = cursor.fetchall()
    return rows[0] if rows else None
