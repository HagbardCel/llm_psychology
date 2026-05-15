"""Topic extraction helpers for assessment recommendations."""

from __future__ import annotations

from typing import Any


def extract_key_topics(recommendation: dict[str, Any]) -> list[str]:
    """Extract key topics from recommendation payload with safe normalization."""
    for key in ("key_topics", "topics"):
        value = recommendation.get(key)
        if isinstance(value, list):
            topics = [str(item).strip() for item in value if str(item).strip()]
            if topics:
                return topics[:5]
    # Conservative fallback for malformed model output.
    return []
