"""Unit tests for EventStream fan-out."""

from __future__ import annotations

import asyncio

import pytest

from jung.domain.models import AppSnapshot, Stage
from jung.events import EventStream, SnapshotChanged

pytestmark = pytest.mark.asyncio


def _snapshot() -> AppSnapshot:
    return AppSnapshot(
        revision=1,
        stage=Stage.SETUP,
        profile_complete=False,
        available_commands=frozenset(),
    )


async def test_publish_delivers_event_to_subscriber() -> None:
    stream = EventStream()
    async with stream.subscribe() as events:
        await stream.publish(SnapshotChanged(_snapshot()))
        event = await asyncio.wait_for(events.__anext__(), timeout=1.0)
    assert isinstance(event, SnapshotChanged)
    assert event.snapshot.stage is Stage.SETUP


async def test_multiple_subscribers_receive_same_event() -> None:
    stream = EventStream()
    async with stream.subscribe() as first, stream.subscribe() as second:
        await stream.publish(SnapshotChanged(_snapshot()))
        first_event = await asyncio.wait_for(first.__anext__(), timeout=1.0)
        second_event = await asyncio.wait_for(second.__anext__(), timeout=1.0)
    assert first_event == second_event


async def test_slow_subscriber_is_evicted_without_blocking_publish() -> None:
    stream = EventStream(max_queue_size=1)
    async with stream.subscribe() as events:
        await stream.publish(SnapshotChanged(_snapshot()))
        await stream.publish(SnapshotChanged(_snapshot()))
        await stream.publish(SnapshotChanged(_snapshot()))
        with pytest.raises(StopAsyncIteration):
            await events.__anext__()


async def test_publish_without_subscribers_does_not_block() -> None:
    stream = EventStream()
    await stream.publish(SnapshotChanged(_snapshot()))
    async with stream.subscribe() as events:
        await stream.publish(SnapshotChanged(_snapshot()))
        event = await asyncio.wait_for(events.__anext__(), timeout=1.0)
    assert isinstance(event, SnapshotChanged)
