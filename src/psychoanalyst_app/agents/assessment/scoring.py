"""Recommendation scoring helpers for assessment flows."""

from __future__ import annotations

from typing import Any


def resolve_recommendation_score(recommendation: dict[str, Any], rank: int) -> float:
    """Resolve recommendation score with deterministic rank fallback."""
    raw_score = recommendation.get("score")
    if isinstance(raw_score, (int, float)):
        return max(0.0, min(1.0, float(raw_score)))
    return max(0.1, 0.9 - (rank * 0.1))
