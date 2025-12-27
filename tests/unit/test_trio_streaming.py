from __future__ import annotations

import time
from contextlib import aclosing

import pytest
import trio

from psychoanalyst_app.utils.trio_streaming import iter_in_thread


@pytest.mark.trio
async def test_iter_in_thread_streams_incrementally():
    def iterator():
        yield "first"
        time.sleep(0.1)
        yield "second"

    timestamps: list[tuple[str, float]] = []
    start_time = trio.current_time()

    async for chunk in iter_in_thread(iterator, buffer_size=2):
        timestamps.append((chunk, trio.current_time() - start_time))

    assert [chunk for chunk, _ in timestamps] == ["first", "second"]
    # First chunk should arrive almost immediately.
    assert timestamps[0][1] < 0.1
    # Second chunk should reflect the blocking sleep.
    assert timestamps[1][1] >= 0.08


@pytest.mark.trio
async def test_iter_in_thread_handles_consumer_stop():
    produced = []

    def iterator():
        for value in ("one", "two", "three"):
            yield value

    async with aclosing(iter_in_thread(iterator)) as gen:
        async for chunk in gen:
            produced.append(chunk)
            if len(produced) == 1:
                break

    # Give a tiny bit of time for the background pump to recognize the stop
    await trio.sleep(0.01)
    assert produced == ["one"]
