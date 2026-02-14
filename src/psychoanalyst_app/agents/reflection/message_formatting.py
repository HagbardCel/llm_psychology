"""Message formatting helpers for reflection output."""

from __future__ import annotations

from typing import Any


def format_reflection_summary(reflection: dict[str, Any]) -> str:
    """Format reflection payload into human-readable markdown summary."""
    summary_parts: list[str] = []

    if "session_context" in reflection:
        context = reflection["session_context"]
        summary_parts.append("## Session Reflection\n")
        summary_parts.append(f"Key themes: {', '.join(context.get('key_themes', []))}")
        summary_parts.append(f"Emotional state: {context.get('emotional_state', 'N/A')}")

    if "therapeutic_memory" in reflection:
        memory = reflection["therapeutic_memory"]
        summary_parts.append("\n## Progress Overview")
        summary_parts.append(f"Total sessions: {memory.get('total_sessions', 0)}")
        summary_parts.append(
            "Relationship quality: "
            + memory.get("relationship_quality", "developing")
        )

    if "plan_recommendations" in reflection and reflection["plan_recommendations"]:
        summary_parts.append("\n## Recommendations")
        for recommendation in reflection["plan_recommendations"][:3]:
            summary_parts.append(f"- {recommendation.get('description', '')}")

    return "\n".join(summary_parts)
