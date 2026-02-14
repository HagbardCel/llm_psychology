"""Payload/formatting helpers for assessment recommendations."""

from __future__ import annotations

from typing import Any

from psychoanalyst_app.orchestration.models import TherapyStyleRecommendation

from .scoring import resolve_recommendation_score
from .topic_extraction import extract_key_topics


def build_structured_recommendations(
    recommendations: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> list[TherapyStyleRecommendation]:
    """Convert recommendation dicts into typed payloads used by orchestration."""
    structured: list[TherapyStyleRecommendation] = []
    for rank, rec in enumerate(recommendations[:limit]):
        structured.append(
            TherapyStyleRecommendation(
                style_name=rec["style_id"],
                score=resolve_recommendation_score(rec, rank),
                explanation=rec["assessment"],
                key_topics=extract_key_topics(rec),
            )
        )
    return structured


def build_recommendation_metadata(
    recommendations: list[TherapyStyleRecommendation],
) -> list[dict[str, Any]]:
    """Serialize recommendation payload for websocket/http metadata."""
    return [
        {
            "style_id": rec.style_name,
            "explanation": rec.explanation,
            "score": rec.score,
        }
        for rec in recommendations
    ]


def format_recommendations(recommendations: list[TherapyStyleRecommendation]) -> str:
    """Render recommendation payloads into the user-facing selection message."""
    parts = [
        "Based on our intake session, I'd like to recommend the "
        "following therapy approaches:\n"
    ]
    for index, recommendation in enumerate(recommendations, 1):
        parts.append(f"\n{index}. {recommendation.style_name.upper()} Therapy")
        parts.append(f"   {recommendation.explanation}\n")

    parts.append("\nWhich approach resonates most with you?")
    return "\n".join(parts)
