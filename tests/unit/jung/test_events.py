"""Unit tests for EventStream fan-out."""

from __future__ import annotations

import asyncio

import pytest

from jung.domain.models import AppSnapshot, Stage
from jung.events import EventStream, SnapshotChanged

pytestmark = pytest.mark.asyncio


def _snapshot(*, revision: int = 1) -> AppSnapshot:
    return AppSnapshot(
        revision=revision,
        stage=Stage.SETUP,
        profile_complete=False,
        available_commands=frozenset(),
    )


def _snapshot_event(revision: int) -> SnapshotChanged:
    return SnapshotChanged(_snapshot(revision=revision))


async def test_publish_delivers_event_to_subscriber() -> None:
    stream = EventStream()
    async with stream.subscribe() as events:
        await stream.publish(_snapshot_event(1))
        event = await asyncio.wait_for(events.__anext__(), timeout=1.0)
    assert isinstance(event, SnapshotChanged)
    assert event.snapshot.stage is Stage.SETUP


async def test_multiple_subscribers_receive_same_event() -> None:
    stream = EventStream()
    async with stream.subscribe() as first, stream.subscribe() as second:
        await stream.publish(_snapshot_event(1))
        first_event = await asyncio.wait_for(first.__anext__(), timeout=1.0)
        second_event = await asyncio.wait_for(second.__anext__(), timeout=1.0)
    assert first_event == second_event


async def test_slow_subscriber_is_evicted_without_blocking_publish() -> None:
    stream = EventStream(max_queue_size=4)
    async with stream.subscribe() as events:
        for revision in range(5):
            await stream.publish(_snapshot_event(revision))

        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(events.__anext__(), timeout=1.0)


async def test_stream_continues_serving_new_subscribers_after_eviction() -> None:
    stream = EventStream(max_queue_size=4)

    async with stream.subscribe() as evicted:
        for revision in range(5):
            await stream.publish(_snapshot_event(revision))

        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(evicted.__anext__(), timeout=1.0)

        async with stream.subscribe() as healthy:
            expected = _snapshot_event(6)
            await stream.publish(expected)

            received = await asyncio.wait_for(healthy.__anext__(), timeout=1.0)
            assert received == expected


async def test_publish_without_subscribers_does_not_block() -> None:
    stream = EventStream()
    await stream.publish(_snapshot_event(1))
    async with stream.subscribe() as events:
        await stream.publish(_snapshot_event(2))
        event = await asyncio.wait_for(events.__anext__(), timeout=1.0)
    assert isinstance(event, SnapshotChanged)
