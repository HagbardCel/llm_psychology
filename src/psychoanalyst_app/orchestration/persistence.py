"""Persistence helpers used by orchestration response handling."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from psychoanalyst_app.models.domain import TherapyPlan
from psychoanalyst_app.models.llm_outputs import (
    StructuredTherapyPlanOutput,
)

logger = logging.getLogger(__name__)


async def persist_therapy_plan_from_output(
    *,
    trio_db_service,
    user_id: str,
    plan_output: StructuredTherapyPlanOutput,
    session_briefing: dict[str, Any] | None = None,
) -> TherapyPlan:
    """Persist a therapy plan from structured output data."""
    latest_plan = await trio_db_service.get_current_therapy_plan(user_id)
    selected_style = plan_output.selected_therapy_style
    if not selected_style and latest_plan:
        selected_style = latest_plan.selected_therapy_style

    plan = TherapyPlan(
        plan_id=str(uuid.uuid4()),
        user_id=user_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        version=(latest_plan.version + 1) if latest_plan else 1,
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

    success = await trio_db_service.save_therapy_plan(plan)
    if not success:
        raise ValueError("Failed to save therapy plan to database")

    return plan


async def persist_tier3_update(
    *,
    trio_db_service,
    user_id: str,
    session_id: str,
    tier3_update: dict[str, Any],
) -> bool:
    """Persist a Tier 3 update payload as a new analysis version."""
    analysis_data = tier3_update.get("analysis_data")
    supersede_analysis_id = tier3_update.get("supersede_analysis_id")
    change_summary = tier3_update.get("change_summary")
    if not analysis_data or not supersede_analysis_id:
        return False
    try:
        saved = await trio_db_service.save_patient_analysis_next_version_and_supersede(
            analysis_id=f"analysis_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            analysis_data=analysis_data,
            created_at=datetime.now(),
            created_by_session=session_id,
            change_summary=change_summary,
            supersede_analysis_id=supersede_analysis_id,
        )
        if not saved:
            logger.error("Failed to persist Tier 3 update for user %s", user_id)
            return False
        return True
    except Exception:
        logger.error(
            "Failed to persist Tier 3 update for user %s", user_id, exc_info=True
        )
        return False
