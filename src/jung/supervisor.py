"""Supervised background task lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class SupervisorClosed(Exception):
    """Supervisor no longer accepts new tasks."""


class TaskSupervisor:
    def __init__(self) -> None:
        self._task_group: asyncio.TaskGroup | None = None
        self._active: set[str] = set()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._accepting = True

    async def __aenter__(self) -> TaskSupervisor:
        self._task_group = asyncio.TaskGroup()
        await self._task_group.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._task_group is not None:
            await self._task_group.__aexit__(exc_type, exc, tb)
        self._task_group = None

    def start(
        self,
        *,
        name: str,
        run: Callable[[], Awaitable[None]],
    ) -> bool:
        if not self._accepting or self._task_group is None:
            raise SupervisorClosed("supervisor is closed to new tasks")
        if name in self._active:
            return False
        self._active.add(name)
        try:
            task = self._task_group.create_task(
                self._run_wrapper(name, run),
                name=name,
            )
        except BaseException:
            self._active.discard(name)
            raise
        self._tasks[name] = task
        return True

    async def shutdown(self, *, timeout_seconds: float) -> None:
        self._accepting = False
        owned = list(self._tasks.values())
        if not owned:
            return
        _done, pending = await asyncio.wait(owned, timeout=timeout_seconds)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run_wrapper(
        self,
        name: str,
        run: Callable[[], Awaitable[None]],
    ) -> None:
        try:
            await run()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("supervised task failed: %s", name)
        finally:
            self._active.discard(name)
            self._tasks.pop(name, None)
