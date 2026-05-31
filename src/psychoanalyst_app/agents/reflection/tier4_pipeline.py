"""Tier 4 therapy plan update pipeline helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psychoanalyst_app.agents.planning.agent import TrioPlanningAgent
from psychoanalyst_app.models.domain import TherapyPlan
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService


def update_tier4_fields(
    plan: TherapyPlan | None,
    session_context,
    plan_assessment: dict[str, Any] | None,
    plan_recommendations: list[dict[str, Any]] | None,
    session_summary: str,
) -> bool:
    """Refresh Tier 4 plan fields based on reflection context."""
    if not plan:
        return False

    updated = False
    indicators = getattr(session_context, "progress_indicators", []) or []
    progress_parts: list[str] = []
    if indicators:
        progress_parts.append(
            "Progress indicators: " + "; ".join(indicators[:3])
        )
    if plan_assessment:
        strengths = plan_assessment.get("strengths") or []
        if strengths:
            progress_parts.append(
                "Strengths noted: " + "; ".join(strengths[:2])
            )

    if not progress_parts and session_summary:
        progress_parts.append(session_summary[:300])

    new_progress = " ".join(progress_parts)[:2000]
    if new_progress and new_progress != plan.current_progress:
        plan.current_progress = new_progress
        updated = True

    rec_descriptions: list[str] = []
    for rec in plan_recommendations or []:
        description = rec.get("description")
        if description:
            rec_descriptions.append(description)
        if len(rec_descriptions) == 3:
            break

    if rec_descriptions:
        if plan.revision_recommendations != rec_descriptions:
            plan.revision_recommendations = rec_descriptions
            updated = True

    return updated


def should_update_tier4(
    session_count: int,
    tier3_updated: bool,
    plan_recommendations: list[dict[str, Any]] | None,
) -> bool:
    """Decide if Tier 4 updates should be applied."""
    if tier3_updated:
        return True
    if session_count > 0 and session_count % 5 == 0:
        return True
    for rec in plan_recommendations or []:
        if rec.get("priority") == "high":
            return True
    return False


async def apply_tier4_updates(
    db_service: TrioDatabaseService,
    planning_agent: TrioPlanningAgent,
    user_id: str,
    current_plan: TherapyPlan | None,
    session_context,
    plan_assessment: dict[str, Any] | None,
    plan_recommendations: list[dict[str, Any]],
    session_summary: str,
    tier3_updated: bool,
) -> bool:
    """Apply Tier 4 plan updates when policy indicates an update is warranted."""
    if not current_plan:
        return False

    session_count = await db_service.get_session_count(user_id)
    if not should_update_tier4(session_count, tier3_updated, plan_recommendations):
        return False

    tier4_updated = update_tier4_fields(
        current_plan,
        session_context,
        plan_assessment,
        plan_recommendations,
        session_summary,
    )
    if tier4_updated:
        current_plan.updated_at = datetime.now()
    return tier4_updated


async def generate_combined_recommendations(
    planning_agent: TrioPlanningAgent,
    memory,
    patterns: dict[str, Any],
    current_plan: TherapyPlan | None,
) -> list[dict[str, Any]]:
    """Generate combined recommendations based on memory and planning insights."""
    recommendations: list[dict[str, Any]] = []

    if memory.relationship_quality in ["established", "strong"]:
        recommendations.append(
            {
                "type": "relationship",
                "description": (
                    "Strong therapeutic relationship established - consider "
                    "deeper therapeutic work"
                ),
                "source": "memory_analysis",
                "priority": "medium",
            }
        )

    emotional_trend = patterns.get("emotional_patterns", {}).get(
        "recent_trend", "stable"
    )
    if emotional_trend == "improving":
        recommendations.append(
            {
                "type": "progress",
                "description": (
                    "Positive emotional trend - maintain current approach and build "
                    "on progress"
                ),
                "source": "pattern_analysis",
                "priority": "high",
            }
        )
    elif emotional_trend == "declining":
        recommendations.append(
            {
                "type": "intervention",
                "description": (
                    "Declining emotional trend - consider plan adjustment or "
                    "additional support"
                ),
                "source": "pattern_analysis",
                "priority": "high",
            }
        )

    if current_plan:
        plan_recommendations = await planning_agent.recommend_plan_adjustments(
            current_plan
        )
        for rec in plan_recommendations[:3]:
            rec["source"] = "planning_analysis"
            recommendations.append(rec)

    return recommendations
