"""Scoring, topic extraction, and payload helpers for assessment recommendations."""

from __future__ import annotations

from typing import Any

from psychoanalyst_app.orchestration.models import TherapyStyleRecommendation


def resolve_recommendation_score(recommendation: dict[str, Any]) -> float:
    """Resolve recommendation score from LLM payload with safe normalization."""
    raw_score = recommendation.get("score")
    if isinstance(raw_score, (int, float)):
        return max(0.0, min(1.0, float(raw_score)))
    return 0.5


def extract_key_topics(recommendation: dict[str, Any]) -> list[str]:
    """Extract key topics from recommendation payload with safe normalization."""
    for key in ("key_topics", "topics"):
        value = recommendation.get(key)
        if isinstance(value, list):
            topics = [str(item).strip() for item in value if str(item).strip()]
            if topics:
                return topics[:5]
    return []


def build_structured_recommendations(
    recommendations: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> list[TherapyStyleRecommendation]:
    """Convert recommendation dicts into typed payloads used by orchestration."""
    structured: list[TherapyStyleRecommendation] = []
    for rec in recommendations[:limit]:
        structured.append(
            TherapyStyleRecommendation(
                style_name=rec["style_id"],
                score=resolve_recommendation_score(rec),
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
