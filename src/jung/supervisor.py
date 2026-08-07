"""Supervised background task lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from jung.diagnostics import _safe_exception_message, diagnostic_context

if TYPE_CHECKING:
    from jung.diagnostics import DiagnosticRecorder

logger = logging.getLogger(__name__)


class SupervisorClosed(Exception):
    """Supervisor no longer accepts new tasks."""


class TaskSupervisor:
    def __init__(self, *, recorder: DiagnosticRecorder | None = None) -> None:
        self._task_group: asyncio.TaskGroup | None = None
        self._active: set[str] = set()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._accepting = True
        self._recorder = recorder

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
        coro = self._run_wrapper(name, run)
        try:
            task = self._task_group.create_task(coro, name=name)
        except BaseException:
            coro.close()
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
            self._record(
                "task.shutdown_timeout",
                {
                    "pending_count": len(pending),
                    "timeout_seconds": timeout_seconds,
                    "pending_names": [
                        task.get_name() for task in pending if hasattr(task, "get_name")
                    ],
                },
            )
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run_wrapper(
        self,
        name: str,
        run: Callable[[], Awaitable[None]],
    ) -> None:
        with diagnostic_context(task=name):
            self._record("task.started", {"name": name})
            try:
                await run()
            except asyncio.CancelledError:
                self._record("task.cancelled", {"name": name})
                raise
            except Exception as exc:
                self._record(
                    "task.failed",
                    {
                        "name": name,
                        "error_type": type(exc).__name__,
                        "error_message": _safe_exception_message(exc),
                    },
                )
                logger.exception("supervised task failed: %s", name)
            else:
                self._record("task.completed", {"name": name})
            finally:
                self._active.discard(name)
                self._tasks.pop(name, None)

    def _record(self, kind: str, data: dict[str, object]) -> None:
        if self._recorder is None:
            return
        self._recorder.record(kind, data)
