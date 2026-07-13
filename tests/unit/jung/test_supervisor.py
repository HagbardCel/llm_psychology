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


async def test_explicit_name_reuse_after_completion() -> None:
    done = asyncio.Event()

    async def finish() -> None:
        done.set()

    async with TaskSupervisor() as supervisor:
        assert supervisor.start(name="work", run=finish) is True
        await asyncio.wait_for(done.wait(), timeout=1.0)
        second_done = asyncio.Event()
        assert supervisor.start(name="work", run=second_done.set) is True
        await asyncio.wait_for(second_done.wait(), timeout=1.0)


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


async def test_shutdown_is_repeatable() -> None:
    async with TaskSupervisor() as supervisor:
        await supervisor.shutdown(timeout_seconds=1.0)
        await supervisor.shutdown(timeout_seconds=1.0)


async def test_shutdown_cancels_only_owned_tasks() -> None:
    unrelated_cancelled = asyncio.Event()
    owned_started = asyncio.Event()

    async def owned() -> None:
        owned_started.set()
        await asyncio.sleep(10)

    unrelated = asyncio.create_task(unrelated_cancelled.wait())
    try:
        async with TaskSupervisor() as supervisor:
            assert supervisor.start(name="owned", run=owned) is True
            await asyncio.wait_for(owned_started.wait(), timeout=1.0)
            await supervisor.shutdown(timeout_seconds=0.1)
        assert not unrelated.done()
        assert not unrelated.cancelled()
        assert not unrelated_cancelled.is_set()
    finally:
        unrelated.cancel()
        with pytest.raises(asyncio.CancelledError):
            await unrelated


async def test_shutdown_timeout_cancels_owned_task() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow() -> None:
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async with TaskSupervisor() as supervisor:
        assert supervisor.start(name="slow", run=slow) is True
        await asyncio.wait_for(started.wait(), timeout=1.0)
        await supervisor.shutdown(timeout_seconds=0.05)
    await asyncio.wait_for(cancelled.wait(), timeout=1.0)


async def test_create_task_failure_rolls_back_active_name_and_closes_coro() -> None:
    from unittest.mock import patch

    captured: list[object] = []

    async with TaskSupervisor() as supervisor:
        assert supervisor._task_group is not None
        def recording_create_task(coro, *, name=None):
            captured.append(coro)
            raise RuntimeError("create failed")

        with patch.object(
            supervisor._task_group,
            "create_task",
            side_effect=recording_create_task,
        ):
            with pytest.raises(RuntimeError, match="create failed"):
                supervisor.start(name="work", run=lambda: asyncio.sleep(0))
        assert "work" not in supervisor._active
        assert len(captured) == 1
        coro = captured[0]
        assert hasattr(coro, "close")
        assert coro.cr_frame is None
