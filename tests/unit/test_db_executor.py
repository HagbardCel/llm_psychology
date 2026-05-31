"""Unit tests for TrioSQLiteExecutor behavior."""

import sqlite3

import pytest

from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor
from psychoanalyst_app.services.db.sqlite_config import reraise_locked_database_error

pytestmark = [pytest.mark.trio, pytest.mark.unit]


async def test_connection_row_factory_is_restored(tmp_path):
    db_path = str(tmp_path / "executor_row_factory.db")
    executor = TrioSQLiteExecutor(db_path, pool_size=1)
    await executor.initialize()

    async with executor.connection(row_factory=sqlite3.Row) as conn:
        assert conn.row_factory is sqlite3.Row

    async with executor.connection() as conn:
        assert conn.row_factory is None

    executor.close()


async def test_connection_acquire_timeout_raises(tmp_path):
    db_path = str(tmp_path / "executor_timeout.db")
    executor = TrioSQLiteExecutor(
        db_path,
        pool_size=1,
        pool_acquire_timeout_seconds=0.01,
    )
    await executor.initialize()

    async with executor.connection():
        with pytest.raises(TimeoutError, match="Timed out acquiring DB connection"):
            async with executor.connection():
                pass

    executor.close()


async def test_file_backed_connections_enable_wal_and_busy_timeout(tmp_path):
    db_path = str(tmp_path / "executor_pragmas.db")
    executor = TrioSQLiteExecutor(db_path, pool_size=1, connect_timeout_seconds=7)
    await executor.initialize()

    async with executor.connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

    assert journal_mode == "wal"
    assert synchronous == 1
    assert busy_timeout == 7000

    executor.close()


async def test_run_sync_retries_locked_database_errors(tmp_path):
    db_path = str(tmp_path / "executor_retry.db")
    executor = TrioSQLiteExecutor(
        db_path,
        pool_size=1,
        locked_retry_attempts=2,
        locked_retry_initial_delay_seconds=0,
    )
    await executor.initialize()
    calls = 0

    def flaky_write(conn):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    async with executor.connection() as conn:
        result = await executor.run_sync(flaky_write, conn)

    assert result == "ok"
    assert calls == 2

    executor.close()


async def test_run_sync_retries_locked_errors_reraised_from_broad_catch(tmp_path):
    db_path = str(tmp_path / "executor_reraised_retry.db")
    executor = TrioSQLiteExecutor(
        db_path,
        pool_size=1,
        locked_retry_attempts=2,
        locked_retry_initial_delay_seconds=0,
    )
    await executor.initialize()
    calls = 0

    def broad_catch_write(conn):
        nonlocal calls
        calls += 1
        try:
            if calls == 1:
                raise sqlite3.OperationalError("database is locked")
        except Exception as exc:
            reraise_locked_database_error(exc)
            return False
        return True

    async with executor.connection() as conn:
        result = await executor.run_sync(broad_catch_write, conn)

    assert result is True
    assert calls == 2

    executor.close()


async def test_run_sync_does_not_retry_non_lock_operational_errors(tmp_path):
    db_path = str(tmp_path / "executor_no_retry.db")
    executor = TrioSQLiteExecutor(
        db_path,
        pool_size=1,
        locked_retry_attempts=2,
        locked_retry_initial_delay_seconds=0,
    )
    await executor.initialize()
    calls = 0

    def invalid_query():
        nonlocal calls
        calls += 1
        raise sqlite3.OperationalError("no such table: missing")

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        await executor.run_sync(invalid_query)

    assert calls == 1

    executor.close()
