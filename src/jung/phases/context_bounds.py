"""Shared mechanical context-bounding primitives."""

from __future__ import annotations

from collections.abc import Sequence


def bounded_text(text: str, limit: int) -> str:
    """Return bounded display text. May truncate text."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def newest_within_budget(items: Sequence[str], budget: int) -> list[str]:
    if budget <= 0 or not items:
        return []
    selected: list[str] = []
    used = 0
    for item in reversed(items):
        if not item.strip():
            continue
        addition = len(item) if not selected else len(item) + 1
        if used + addition > budget:
            break
        selected.insert(0, item)
        used += addition
    return selected
