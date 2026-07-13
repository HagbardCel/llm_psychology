"""Unit tests for TaskSupervisor lifecycle."""

from __future__ import annotations

import asyncio

import pytest

from jung.supervisor import SupervisorClosed, TaskSupervisor

pytestmark = pytest.mark.asyncio


async def test_start_runs_task_to_completion() -> None:
    completed = asyncio.Event()
    async with TaskSupervisor() as supervisor:
        assert supervisor.start(name="work", run=completed.wait) is True
        completed.set()
        await asyncio.sleep(0.05)


async def test_duplicate_name_returns_false() -> None:
    gate = asyncio.Event()
    async with TaskSupervisor() as supervisor:
        assert supervisor.start(name="work", run=gate.wait) is True
        assert supervisor.start(name="work", run=gate.wait) is False
        gate.set()
        await asyncio.sleep(0.05)


async def test_start_before_enter_raises_supervisor_closed() -> None:
    supervisor = TaskSupervisor()
    with pytest.raises(SupervisorClosed):
        supervisor.start(name="work", run=lambda: asyncio.sleep(0))


async def test_failed_task_does_not_cancel_sibling() -> None:
    sibling_done = asyncio.Event()

    async def fail() -> None:
        raise RuntimeError("boom")

    async def succeed() -> None:
        sibling_done.set()

    async with TaskSupervisor() as supervisor:
        assert supervisor.start(name="fail", run=fail) is True
        assert supervisor.start(name="ok", run=succeed) is True
        await asyncio.wait_for(sibling_done.wait(), timeout=1.0)


async def test_shutdown_rejects_new_tasks() -> None:
    gate = asyncio.Event()
    async with TaskSupervisor() as supervisor:
        await supervisor.shutdown(timeout_seconds=1.0)
        with pytest.raises(SupervisorClosed):
            supervisor.start(name="late", run=gate.wait)
