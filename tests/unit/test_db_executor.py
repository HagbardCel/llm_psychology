"""Unit tests for TrioSQLiteExecutor behavior."""

import sqlite3

import pytest

from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor


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
