"""
Helpers for bridging blocking iterators into Trio async iterators.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Iterator
from typing import TypeVar

import trio

T = TypeVar("T")

logger = logging.getLogger(__name__)


async def iter_in_thread(
    iterator_factory: Callable[[], Iterator[T]], *, buffer_size: int = 1
) -> AsyncIterator[T]:
    """
    Yield items from a blocking iterator inside Trio.

    The iterator is executed in Trio's worker thread pool. Chunks are sent through
    a bounded MemoryChannel so the async consumer can observe them incrementally.
    """

    send_channel, receive_channel = trio.open_memory_channel[T](max(buffer_size, 1))

    async def _pump():
        try:

            def _run():
                try:
                    iterator = iterator_factory()
                    for item in iterator:
                        try:
                            trio.from_thread.run(send_channel.send, item)
                        except trio.BrokenResourceError:
                            # Consumer stopped reading and closed the receive channel
                            return
                finally:
                    try:
                        trio.from_thread.run(send_channel.aclose)
                    except (trio.ClosedResourceError, trio.BrokenResourceError):
                        pass

            await trio.to_thread.run_sync(_run)
        except Exception:
            logger.error("Error in iter_in_thread pump", exc_info=True)
            raise
        finally:
            # Final safety close
            with trio.move_on_after(0.5) as cleanup_scope:
                cleanup_scope.shield = True
                await send_channel.aclose()

    try:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(_pump)
            try:
                async with receive_channel:
                    async for item in receive_channel:
                        yield item
            finally:
                # If we exit the loop early (break/return), ensure the pump stops
                nursery.cancel_scope.cancel()
    except* GeneratorExit:
        # Handles gen.aclose() which raises GeneratorExit inside the nursery.
        # Trio wraps it in a BaseExceptionGroup; catching it here allows
        # the generator to close cleanly without bubbling an exception group.
        pass
