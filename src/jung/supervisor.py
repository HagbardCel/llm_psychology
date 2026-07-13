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
        if not self._accepting:
            raise SupervisorClosed("supervisor is closed to new tasks")
        if self._task_group is None:
            raise SupervisorClosed("supervisor is not running")
        if name in self._active:
            return False
        self._active.add(name)
        self._task_group.create_task(self._run_wrapper(name, run))
        return True

    async def shutdown(self, *, timeout_seconds: float) -> None:
        self._accepting = False
        if self._task_group is None:
            return
        current = asyncio.current_task()
        tasks = [
            task
            for task in asyncio.all_tasks()
            if task is not current and not task.done()
        ]
        if not tasks:
            return
        try:
            async with asyncio.timeout(timeout_seconds):
                await asyncio.gather(*tasks, return_exceptions=True)
        except TimeoutError:
            for task in tasks:
                task.cancel()

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
