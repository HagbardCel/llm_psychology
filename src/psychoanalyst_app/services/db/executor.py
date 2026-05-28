"""Shared Trio-friendly SQLite executor and connection pool."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import asynccontextmanager
from typing import Any, Callable

import trio

from psychoanalyst_app.services.db.sqlite_config import (
    configure_connection,
    is_locked_database_error,
)

logger = logging.getLogger(__name__)


class TrioSQLiteExecutor:
    """Manages a Trio-compatible SQLite connection pool."""

    def __init__(
        self,
        db_path: str,
        *,
        pool_size: int = 5,
        connect_timeout_seconds: float = 30.0,
        pool_acquire_timeout_seconds: float = 30.0,
        locked_retry_attempts: int = 3,
        locked_retry_initial_delay_seconds: float = 0.05,
    ):
        self.db_path = db_path
        self.pool_size = pool_size
        self.connect_timeout_seconds = connect_timeout_seconds
        self.pool_acquire_timeout_seconds = pool_acquire_timeout_seconds
        self.busy_timeout_ms = int(connect_timeout_seconds * 1000)
        self.locked_retry_attempts = locked_retry_attempts
        self.locked_retry_initial_delay_seconds = locked_retry_initial_delay_seconds
        self._is_uri = db_path.startswith("file:")
        self._pool_send, self._pool_recv = trio.open_memory_channel(pool_size)
        self._connections: list[sqlite3.Connection] = []
        self._initialized = False

    def _create_connection(self, row_factory=None) -> sqlite3.Connection:
        """Create a new sqlite3 connection."""
        if self._is_uri:
            conn = sqlite3.connect(
                self.db_path,
                timeout=self.connect_timeout_seconds,
                uri=True,
                check_same_thread=False,
            )
        else:
            conn = sqlite3.connect(
                self.db_path,
                timeout=self.connect_timeout_seconds,
                check_same_thread=False,
            )

        configure_connection(
            conn,
            db_path=self.db_path,
            busy_timeout_ms=self.busy_timeout_ms,
        )
        if row_factory:
            conn.row_factory = row_factory
        return conn

    def create_connection(self, row_factory=None) -> sqlite3.Connection:
        """Public helper for tests/tools that need a direct connection."""
        return self._create_connection(row_factory=row_factory)

    async def initialize(self) -> None:
        """Initialize the connection pool."""
        if self._initialized:
            return

        logger.info(
            "Initializing SQLite executor pool (%s connections)", self.pool_size
        )
        for _ in range(self.pool_size):
            conn = await trio.to_thread.run_sync(self._create_connection)
            self._connections.append(conn)
            await self._pool_send.send(conn)
        self._initialized = True

    @asynccontextmanager
    async def connection(self, row_factory=None):
        """Async context manager that yields a pooled connection."""
        with trio.move_on_after(self.pool_acquire_timeout_seconds) as cancel_scope:
            conn = await self._pool_recv.receive()

        if cancel_scope.cancelled_caught:
            raise TimeoutError(
                f"Timed out acquiring DB connection after "
                f"{self.pool_acquire_timeout_seconds:.2f}s"
            )

        original_row_factory = conn.row_factory
        try:
            if row_factory is not None:
                conn.row_factory = row_factory
            yield conn
        finally:
            conn.row_factory = original_row_factory
            await self._pool_send.send(conn)

    async def run_sync(self, func: Callable[..., Any], *args: Any) -> Any:
        """Run blocking SQLite work in a worker thread."""
        attempt = 0
        delay = self.locked_retry_initial_delay_seconds

        while True:
            try:
                return await trio.to_thread.run_sync(func, *args)
            except sqlite3.OperationalError as exc:
                if (
                    not is_locked_database_error(exc)
                    or attempt >= self.locked_retry_attempts
                ):
                    raise
                _rollback_if_connection(args)
                attempt += 1
                logger.warning(
                    "SQLite database locked; retrying operation "
                    "(attempt %s/%s)",
                    attempt,
                    self.locked_retry_attempts,
                )
                await trio.sleep(delay)
                delay *= 2

    def close(self) -> None:
        """Close all pooled connections."""
        logger.info("Closing SQLite executor pool")
        try:
            self._pool_send.close()
            self._pool_recv.close()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Error closing executor channels: %s", exc, exc_info=True)

        while self._connections:
            conn = self._connections.pop()
            try:
                conn.close()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Error closing SQLite connection: %s", exc)


def _rollback_if_connection(args: tuple[Any, ...]) -> None:
    if not args or not isinstance(args[0], sqlite3.Connection):
        return
    try:
        args[0].rollback()
    except sqlite3.Error:
        logger.debug("SQLite rollback after locked error failed", exc_info=True)
