"""Session summary plan snapshot and reflection formatting helpers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from psychoanalyst_app.models.domain import TherapyPlan
from psychoanalyst_app.models.llm_outputs import StructuredTherapyPlanOutput


def is_noop_plan_update(
    current_plan: TherapyPlan | None,
    plan_output: StructuredTherapyPlanOutput,
) -> bool:
    """Return True when structured plan output would not change persisted fields."""
    if not current_plan:
        return False
    return (
        plan_output.selected_therapy_style == current_plan.selected_therapy_style
        and plan_output.focus == current_plan.focus
        and plan_output.themes == current_plan.themes
        and plan_output.timeline == current_plan.timeline
        and plan_output.initial_goals == current_plan.initial_goals
        and plan_output.current_progress == current_plan.current_progress
        and plan_output.planned_interventions == current_plan.planned_interventions
        and plan_output.revision_recommendations
        == current_plan.revision_recommendations
        and plan_output.status == current_plan.status
    )


def build_plan_snapshot(
    current_plan: TherapyPlan | None,
    plan_output: StructuredTherapyPlanOutput,
    *,
    user_id: str,
) -> TherapyPlan:
    """Build an in-memory plan snapshot from structured output."""
    if current_plan:
        noop = is_noop_plan_update(current_plan, plan_output)
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        created_at = datetime.now()
        version = current_plan.version if noop else current_plan.version + 1
        session_briefing = current_plan.session_briefing
        selected_style = (
            plan_output.selected_therapy_style or current_plan.selected_therapy_style
        )
    else:
        plan_id = f"pending_{uuid.uuid4().hex[:12]}"
        created_at = datetime.now()
        version = 1
        session_briefing = None
        selected_style = plan_output.selected_therapy_style

    return TherapyPlan(
        plan_id=plan_id,
        user_id=user_id,
        created_at=created_at,
        updated_at=datetime.now(),
        version=version,
        selected_therapy_style=selected_style,
        focus=plan_output.focus,
        themes=plan_output.themes,
        timeline=plan_output.timeline,
        initial_goals=plan_output.initial_goals,
        current_progress=plan_output.current_progress,
        planned_interventions=plan_output.planned_interventions,
        revision_recommendations=plan_output.revision_recommendations,
        status=plan_output.status,
        session_briefing=session_briefing,
    )


def format_reflection_summary(reflection: dict[str, Any]) -> str:
    """Format reflection payload into human-readable markdown summary."""
    summary_parts: list[str] = []

    if "session_context" in reflection:
        context = reflection["session_context"]
        summary_parts.append("## Session Reflection\n")
        summary_parts.append(f"Key themes: {', '.join(context.get('key_themes', []))}")
        summary_parts.append(
            f"Emotional state: {context.get('emotional_state', 'N/A')}"
        )

    if "therapeutic_memory" in reflection:
        memory = reflection["therapeutic_memory"]
        summary_parts.append("\n## Progress Overview")
        summary_parts.append(f"Total sessions: {memory.get('total_sessions', 0)}")
        summary_parts.append(
            "Relationship quality: " + memory.get("relationship_quality", "developing")
        )

    if "plan_recommendations" in reflection and reflection["plan_recommendations"]:
        summary_parts.append("\n## Recommendations")
        for recommendation in reflection["plan_recommendations"][:3]:
            summary_parts.append(f"- {recommendation.get('description', '')}")

    return "\n".join(summary_parts)
