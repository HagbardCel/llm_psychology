"""Cancellation-safe bridge from asyncio application code to sync SQLite calls."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from jung._application import diagnostics as diag
from jung._async_cleanup import drain_cancelled_task
from jung.diagnostics import DiagnosticRecorder

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


async def run_store_call(
    fn: Callable[..., _T],
    /,
    *args: Any,
    recorder: DiagnosticRecorder | None = None,
    **kwargs: Any,
) -> _T:
    # Bounded shutdown applies around LLM/background work; an already-running
    # local SQLite call is allowed to finish before the mutation lock releases.
    method_name = getattr(fn, "__name__", None) or type(fn).__name__

    task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as cancellation:
        failure = await drain_cancelled_task(task)
        if failure is not None:
            logger.error(
                "store call failed after caller cancellation function=%s error_type=%s",
                method_name,
                type(failure).__name__,
                exc_info=failure,
            )
            diag.record_runtime_error(
                recorder,
                phase="store_drained",
                exc=failure,
                function=method_name,
            )

        raise cancellation
