"""Smoke-only correlation context for structured calls."""

from __future__ import annotations

from contextvars import ContextVar

current_smoke_call_id: ContextVar[str | None] = ContextVar(
    "current_smoke_call_id",
    default=None,
)
