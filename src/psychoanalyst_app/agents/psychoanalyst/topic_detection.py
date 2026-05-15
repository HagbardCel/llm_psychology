"""Topic-depth detection helpers for session timing policy."""

from __future__ import annotations


def is_in_deep_topic(context) -> bool:
    """Conservative fallback used when deep-topic classification is unavailable."""
    _ = context
    return False
