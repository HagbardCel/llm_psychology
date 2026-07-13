"""Async cancellation helpers shared across LLM modules."""

from __future__ import annotations


def is_async_cancellation(exc: BaseException) -> bool:
    return type(exc).__name__ in {"CancelledError", "Cancelled"}
