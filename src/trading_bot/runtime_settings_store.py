from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import closing
from typing import Any, Protocol


class Cursor(Protocol):
    def execute(self, sql: str, row: tuple[Any, ...] = ()) -> Any: ...

    def fetchall(self) -> list[Any]: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...

    def commit(self) -> None: ...

    def close(self) -> None: ...


class RuntimeSettingsStore:
    """화면에서 바꾼 운용 설정을 DB에 저장하고 다시 읽어오는 저장소."""

    def __init__(self, connect: Callable[[], Connection]) -> None:
        self.connect = connect

    def read(self, keys: Iterable[str]) -> dict[str, float]:
        key_items = tuple(keys)
        if not key_items:
            return {}
        self._ensure_table()
        placeholders = ", ".join("?" for _ in key_items)
        rows = self._query(
            f"""
            SELECT setting_key, setting_value
            FROM runtime_setting
            WHERE setting_key IN ({placeholders})
            """,
            key_items,
        )
        return {str(key): float(value) for key, value in rows}

    def save(self, values: dict[str, float]) -> None:
        if not values:
            return
        self._ensure_table()
        # 설정은 키별 최신값만 유지한다. 화면 저장 시 INSERT/UPDATE를 한 번에 처리한다.
        for key, value in values.items():
            self._execute(
                """
                IF EXISTS (SELECT 1 FROM runtime_setting WHERE setting_key = ?)
                BEGIN
                    UPDATE runtime_setting
                    SET setting_value = ?, updated_at = GETDATE()
                    WHERE setting_key = ?
                END
                ELSE
                BEGIN
                    INSERT INTO runtime_setting (setting_key, setting_value)
                    VALUES (?, ?)
                END
                """,
                (key, float(value), key, key, float(value)),
            )

    def _ensure_table(self) -> None:
        self._execute(
            """
            IF OBJECT_ID(N'dbo.runtime_setting', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.runtime_setting (
                    setting_key VARCHAR(80) NOT NULL PRIMARY KEY,
                    setting_value FLOAT NOT NULL,
                    updated_at DATETIME DEFAULT GETDATE()
                );
            END
            """,
            (),
        )

    def _query(self, sql: str, row: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        with closing(self.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(sql, row)
            return list(cursor.fetchall())

    def _execute(self, sql: str, row: tuple[Any, ...]) -> None:
        with closing(self.connect()) as connection:
            connection.cursor().execute(sql, row)
            connection.commit()
