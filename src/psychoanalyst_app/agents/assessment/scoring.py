"""Recommendation scoring helpers for assessment flows."""

from __future__ import annotations

from typing import Any


def resolve_recommendation_score(recommendation: dict[str, Any]) -> float:
    """Resolve recommendation score from LLM payload with safe normalization."""
    raw_score = recommendation.get("score")
    if isinstance(raw_score, (int, float)):
        return max(0.0, min(1.0, float(raw_score)))
    # Conservative explicit fallback for malformed model output.
    return 0.5
