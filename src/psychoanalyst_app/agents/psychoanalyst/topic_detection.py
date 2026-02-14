"""Topic-depth detection helpers for session timing policy."""

from __future__ import annotations


def is_in_deep_topic(context) -> bool:
    """Return whether the current exchange appears to be in a deep topic.

    Current behavior is an explicit fallback: return False until
    topic-depth heuristics are introduced.
    """
    _ = context
    return False
