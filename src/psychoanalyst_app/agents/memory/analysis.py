"""Pure helpers for memory pattern analysis."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from psychoanalyst_app.models.domain import Session


def format_knowledge(knowledge_list: list[dict[str, Any]]) -> str:
    """Format knowledge list for prompts."""
    if not knowledge_list:
        return "No relevant knowledge available."

    formatted = []
    for i, knowledge in enumerate(knowledge_list, 1):
        formatted.append(f"{i}. From {knowledge['source']}: {knowledge['content']}")

    return "\n".join(formatted)


def assess_relationship_quality(sessions: list[Session]) -> str:
    """Assess therapeutic relationship quality based on sessions."""
    if not sessions:
        return "new"

    session_count = len(sessions)

    if session_count == 1:
        return "building"
    elif session_count <= 3:
        return "developing"
    elif session_count <= 6:
        return "established"
    else:
        return "strong"


def analyze_theme_patterns(themes: dict[str, int]) -> dict[str, Any]:
    """Analyze patterns in recurring themes."""
    if not themes:
        return {"dominant_themes": [], "emerging_themes": [], "stable_themes": []}

    sorted_themes = sorted(themes.items(), key=lambda x: x[1], reverse=True)
    total_mentions = sum(themes.values())

    return {
        "dominant_themes": [theme for theme, count in sorted_themes[:3]],
        "theme_frequency": dict(sorted_themes),
        "total_theme_mentions": total_mentions,
    }


def analyze_emotional_patterns(emotions: list[str]) -> dict[str, Any]:
    """Analyze patterns in emotional states."""
    if not emotions:
        return {"progression": [], "common_states": [], "recent_trend": "stable"}

    emotion_counts: dict[str, int] = defaultdict(int)
    for emotion in emotions:
        emotion_counts[emotion] += 1

    recent_emotions = emotions[-3:] if len(emotions) >= 3 else emotions
    recent_trend = (
        "improving"
        if any(pos in recent_emotions for pos in ["happy", "hopeful", "confident"])
        else "stable"
    )

    return {
        "progression": emotions,
        "common_states": list(emotion_counts.keys()),
        "recent_trend": recent_trend,
        "emotion_distribution": dict(emotion_counts),
    }


def analyze_progress_patterns(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze patterns in progress indicators."""
    if not timeline:
        return {
            "total_indicators": 0,
            "recent_progress": [],
            "progress_trend": "stable",
        }

    all_indicators: list[str] = []
    for entry in timeline:
        all_indicators.extend(entry.get("indicators", []))

    recent_indicators: list[str] = []
    for entry in timeline[-2:]:
        recent_indicators.extend(entry.get("indicators", []))

    return {
        "total_indicators": len(all_indicators),
        "recent_progress": recent_indicators,
        "progress_trend": "improving" if recent_indicators else "stable",
    }


def generate_context_summary(
    themes: list[str], emotions: list[str], insights: list[str]
) -> str:
    """Generate a summary of recent context."""
    summary_parts: list[str] = []

    if themes:
        unique_themes = list(set(themes))
        summary_parts.append(f"Recent themes: {', '.join(unique_themes[:3])}")

    if emotions:
        recent_emotion = emotions[-1] if emotions else "neutral"
        summary_parts.append(f"Current emotional state: {recent_emotion}")

    if insights:
        summary_parts.append(
            f"Recent insights: {len(insights)} new insights gained"
        )

    return (
        " | ".join(summary_parts)
        if summary_parts
        else "Limited recent context available"
    )
