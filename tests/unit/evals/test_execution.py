"""Deterministic tests for bounded ordered async map."""

from __future__ import annotations

import asyncio

import pytest

from evals.execution import bounded_ordered_map


@pytest.mark.asyncio
async def test_concurrency_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="concurrency must be >= 1"):
        await bounded_ordered_map([lambda: _const(1)], concurrency=0)
    with pytest.raises(ValueError, match="concurrency must be >= 1"):
        await bounded_ordered_map([lambda: _const(1)], concurrency=-1)


@pytest.mark.asyncio
async def test_concurrency_accepts_1_2_4() -> None:
    for n in (1, 2, 4):
        result = await bounded_ordered_map(
            [lambda: _const(1), lambda: _const(2)],
            concurrency=n,
        )
        assert result == [1, 2]


@pytest.mark.asyncio
async def test_empty_jobs_returns_empty_list() -> None:
    assert await bounded_ordered_map([], concurrency=1) == []
    assert await bounded_ordered_map([], concurrency=4) == []


@pytest.mark.asyncio
async def test_concurrency_1_starts_and_finishes_in_order() -> None:
    events: list[str] = []

    async def job(label: str) -> str:
        events.append(f"start:{label}")
        await asyncio.sleep(0)
        events.append(f"finish:{label}")
        return label

    result = await bounded_ordered_map(
        [(lambda label=label: job(label)) for label in ("a", "b", "c")],
        concurrency=1,
    )
    assert result == ["a", "b", "c"]
    assert events == [
        "start:a",
        "finish:a",
        "start:b",
        "finish:b",
        "start:c",
        "finish:c",
    ]


@pytest.mark.asyncio
async def test_active_jobs_never_exceed_concurrency() -> None:
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def job(index: int) -> int:
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.02)
        async with lock:
            active -= 1
        return index

    result = await bounded_ordered_map(
        [(lambda i=i: job(i)) for i in range(8)],
        concurrency=3,
    )
    assert result == list(range(8))
    assert peak <= 3


@pytest.mark.asyncio
async def test_two_jobs_overlap_at_concurrency_2() -> None:
    """Handshake would deadlock if jobs ran strictly serially."""
    first_entered = asyncio.Event()
    second_entered = asyncio.Event()

    async def job_a() -> str:
        first_entered.set()
        await second_entered.wait()
        return "a"

    async def job_b() -> str:
        await first_entered.wait()
        second_entered.set()
        return "b"

    result = await bounded_ordered_map(
        [job_a, job_b],
        concurrency=2,
    )
    assert result == ["a", "b"]


@pytest.mark.asyncio
async def test_slower_first_job_still_returns_input_order() -> None:
    async def slow() -> str:
        await asyncio.sleep(0.05)
        return "first"

    async def fast() -> str:
        return "second"

    result = await bounded_ordered_map([slow, fast], concurrency=2)
    assert result == ["first", "second"]


class ErrorA(Exception):
    pass


class ErrorB(Exception):
    pass


@pytest.mark.asyncio
async def test_lowest_index_recorded_failure_is_raised() -> None:
    """Force both workers to record ordinary failures (not scheduler-dependent)."""
    job1_raised = asyncio.Event()

    async def job_0() -> str:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise ErrorA("from job 0 cleanup") from None
        return "unreachable"

    async def job_1() -> str:
        job1_raised.set()
        raise ErrorB("from job 1")

    # Ensure job 0 has acquired the semaphore before job 1 fails.
    started_0 = asyncio.Event()

    async def job_0_gated() -> str:
        started_0.set()
        return await job_0()

    async def job_1_gated() -> str:
        await started_0.wait()
        return await job_1()

    with pytest.raises(ErrorA, match="from job 0 cleanup"):
        await bounded_ordered_map([job_0_gated, job_1_gated], concurrency=2)


@pytest.mark.asyncio
async def test_sibling_cancelled_after_ordinary_failure() -> None:
    cancelled = asyncio.Event()
    sibling_started = asyncio.Event()

    async def waiting() -> str:
        sibling_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "unreachable"

    async def failing() -> str:
        await sibling_started.wait()
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await bounded_ordered_map([waiting, failing], concurrency=2)
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_independently_cancelled_child_raises_cancelled_error() -> None:
    """Self-cancelled child leaves its slot unset; executor raises CancelledError."""
    started = asyncio.Event()

    async def self_cancel() -> str:
        started.set()
        task = asyncio.current_task()
        assert task is not None
        task.cancel()
        await asyncio.sleep(0)  # allow cancel to deliver
        return "never"

    async def peer() -> str:
        await started.wait()
        await asyncio.sleep(0.02)
        return "peer"

    with pytest.raises(asyncio.CancelledError):
        await bounded_ordered_map([self_cancel, peer], concurrency=2)


@pytest.mark.asyncio
async def test_external_cancellation_propagates_and_drains_children() -> None:
    children_running = 0
    children_cleaned = 0
    lock = asyncio.Lock()
    all_started = asyncio.Event()

    async def job(_index: int) -> str:
        nonlocal children_running, children_cleaned
        async with lock:
            children_running += 1
            if children_running == 2:
                all_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            async with lock:
                children_cleaned += 1
            raise
        return "never"

    async def run_map() -> list[str]:
        return await bounded_ordered_map(
            [(lambda i=i: job(i)) for i in range(2)],
            concurrency=2,
        )

    task = asyncio.create_task(run_map())
    await all_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert children_cleaned == 2
    assert children_running == 2


@pytest.mark.asyncio
async def test_structured_drain_before_exposing_failure() -> None:
    """ValueError is not raised until the cancelled sibling's finally completes."""
    finally_done = asyncio.Event()
    sibling_started = asyncio.Event()
    failure_exposed = False

    async def waiting() -> str:
        sibling_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.02)
            finally_done.set()
            raise
        return "unreachable"

    async def failing() -> str:
        await sibling_started.wait()
        raise ValueError("structured-drain")

    with pytest.raises(ValueError, match="structured-drain"):
        await bounded_ordered_map([waiting, failing], concurrency=2)
        failure_exposed = True

    assert finally_done.is_set()
    assert failure_exposed is False


async def _const(value: int) -> int:
    return value
