"""Internal cancellation-safe draining for application and stream cleanup."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any


async def drain_cancelled_task(
    task: asyncio.Future[Any],
) -> BaseException | None:
    """Drain an owned task despite repeated caller cancellation.

    Return the task's ordinary failure or a CancelledError when the owned task
    itself was cancelled. KeyboardInterrupt and SystemExit are not suppressed.
    """
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # Preserve the caller's original cancellation, but continue draining.
            continue
        except Exception:
            # Shield propagates the owned task's failure once it completes;
            # inspect via task.result() below.
            break

    if task.cancelled():
        return asyncio.CancelledError()

    try:
        task.result()
    except Exception as exc:
        return exc

    return None


async def close_awaitable_safely(
    close: Callable[[], object],
    *,
    record_failure: Callable[[BaseException], None],
    preserve_existing_cancellation: bool = False,
) -> None:
    """Close an awaitable resource without losing or swapping cancellations.

    ``ensure_future`` may adopt an existing Future/Task returned by ``close()``;
    this helper assumes drain ownership of that awaitable for the close request.
    """
    try:
        result = close()
    except asyncio.CancelledError as exc:
        record_failure(exc)
        return
    except Exception as exc:
        record_failure(exc)
        return

    if not inspect.isawaitable(result):
        return

    close_task = asyncio.ensure_future(result)
    caller = asyncio.current_task()
    cancels_before = caller.cancelling() if caller is not None else 0

    try:
        await asyncio.shield(close_task)
    except asyncio.CancelledError as cancellation:
        cancels_after = caller.cancelling() if caller is not None else 0

        if cancels_after > cancels_before:
            failure = await drain_cancelled_task(close_task)
            if failure is not None:
                record_failure(failure)

            if preserve_existing_cancellation:
                # Original cancellation remains active outside this finally block.
                return

            raise cancellation

        # The close task itself raised or was cancelled.
        record_failure(cancellation)
    except Exception as exc:
        record_failure(exc)
