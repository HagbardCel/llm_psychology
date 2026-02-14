"""Plan snapshot utilities used by reflection orchestration."""

from __future__ import annotations

import uuid
from datetime import datetime

from psychoanalyst_app.models.data_models import TherapyPlan
from psychoanalyst_app.models.structured_output_models import StructuredTherapyPlanOutput


def is_noop_plan_update(
    current_plan: TherapyPlan | None,
    plan_output: StructuredTherapyPlanOutput,
) -> bool:
    """Return True when structured plan output would not change persisted fields."""
    if not current_plan:
        return False
    return (
        plan_output.selected_therapy_style == current_plan.selected_therapy_style
        and plan_output.plan_details == current_plan.plan_details
        and plan_output.initial_goals == current_plan.initial_goals
        and plan_output.current_progress == current_plan.current_progress
        and plan_output.planned_interventions == current_plan.planned_interventions
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
        plan_id = current_plan.plan_id
        created_at = current_plan.created_at
        version = current_plan.version if noop else current_plan.version + 1
        session_briefing = current_plan.session_briefing
        selected_style = plan_output.selected_therapy_style or current_plan.selected_therapy_style
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
        plan_details=plan_output.plan_details,
        initial_goals=plan_output.initial_goals,
        current_progress=plan_output.current_progress,
        planned_interventions=plan_output.planned_interventions,
        status=plan_output.status,
        session_briefing=session_briefing,
    )
