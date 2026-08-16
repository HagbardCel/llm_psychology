"""Bounded ordered async map for independent eval jobs.

Ordinary child exceptions are captured inside workers so TaskGroup never
sees them as ExceptionGroup members. That keeps cancellation portable on
Python 3.11+ without relying on Task.cancelling() or ExceptionGroup unwrap.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar, cast

T = TypeVar("T")

_UNSET = object()


async def bounded_ordered_map(
    jobs: Sequence[Callable[[], Awaitable[T]]],
    *,
    concurrency: int,
) -> list[T]:
    """Run lazy jobs with a concurrency bound; return results in input order.

    ``concurrency == 1`` uses a plain sequential loop. For ``concurrency > 1``,
    workers capture ordinary ``Exception`` values, cancel siblings, and let
    ``TaskGroup`` drain before the lowest-index recorded failure is raised.
    Parent ``CancelledError`` is never caught or translated.
    """
    if concurrency < 1:
        raise ValueError(f"concurrency must be >= 1, got {concurrency}")

    if concurrency == 1:
        return [await job() for job in jobs]

    semaphore = asyncio.Semaphore(concurrency)
    results: list[object] = [_UNSET] * len(jobs)
    failures: dict[int, Exception] = {}
    tasks: list[asyncio.Task[None]] = []

    async def run_one(index: int, job: Callable[[], Awaitable[T]]) -> None:
        try:
            async with semaphore:
                results[index] = await job()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failures[index] = exc
            current = asyncio.current_task()
            for task in tasks:
                if task is not current:
                    task.cancel()
            # Do not re-raise. Failure is selected after TaskGroup drains.

    async with asyncio.TaskGroup() as group:
        for index, job in enumerate(jobs):
            tasks.append(group.create_task(run_one(index, job)))

    if failures:
        raise failures[min(failures)] from None

    if any(value is _UNSET for value in results):
        raise asyncio.CancelledError

    assert all(value is not _UNSET for value in results)
    return cast(list[T], results)
