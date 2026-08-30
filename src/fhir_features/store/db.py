"""DuckDB connection management.

DuckDB is single-writer: one connection guarded by a lock serializes all writes
(uvicorn runs with ``workers=1``). This is the documented scaling boundary.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType

import duckdb


class Database:
    """One process-wide DuckDB connection with a write lock."""

    def __init__(self, db_path: Path | str) -> None:
        self._conn = duckdb.connect(str(db_path))
        self._write_lock = threading.Lock()

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        return self._conn

    @contextmanager
    def reader(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """A read cursor for one request/operation.

        ``cursor()`` duplicates the connection, giving the reader its own result set and
        transaction context — concurrent requests cannot corrupt each other's results, and a
        reader never observes a writer's uncommitted state (snapshot isolation).
        """
        cursor = self._conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    @contextmanager
    def transaction(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Serialized write transaction: BEGIN/COMMIT, ROLLBACK on any error."""
        with self._write_lock:
            self._conn.execute("BEGIN TRANSACTION")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
