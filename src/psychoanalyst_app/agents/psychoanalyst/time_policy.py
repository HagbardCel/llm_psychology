"""Time-window policy helpers for psychoanalyst response flow."""

from __future__ import annotations


def should_offer_extension(context, *, in_deep_topic: bool) -> bool:
    """Check if session extension should be offered."""
    return (
        context.time_remaining_minutes <= 5
        and context.can_extend
        and context.time_remaining_minutes > 0
        and not in_deep_topic
    )
