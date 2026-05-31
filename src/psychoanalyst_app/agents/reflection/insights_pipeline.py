"""Higher-level reflection/insights pipelines for TrioReflectionAgent."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from psychoanalyst_app.agents.reflection.helpers import maybe_update_tier1_profile
from psychoanalyst_app.agents.reflection.session_summary_pipeline import (
    generate_session_summary_payload,
)
from psychoanalyst_app.agents.reflection.tier2_pipeline import (
    load_or_enrich_session_record,
)
from psychoanalyst_app.agents.reflection.tier3_pipeline import (
    prepare_tier3_update_payload,
)
from psychoanalyst_app.agents.reflection.tier4_pipeline import (
    apply_tier4_updates,
    generate_combined_recommendations,
)
from psychoanalyst_app.models.structured_output_models import StructuredUserProfileOutput

logger = logging.getLogger(__name__)


async def generate_comprehensive_reflection_data(
    *,
    db_service,
    llm_service,
    memory_agent,
    planning_agent,
    user_id: str,
    session,
    current_plan,
) -> tuple[
    dict[str, Any],
    StructuredUserProfileOutput | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    """Generate comprehensive reflection payload and tier update metadata."""
    session_context = await memory_agent.analyze_session_context(session)
    memory = await memory_agent.get_therapeutic_memory()
    patterns = await memory_agent.identify_patterns()
    continuity_context = await memory_agent.get_continuity_context(
        [topic.name for topic in session.topics]
    )

    session_record, tier2_enrichment = await load_or_enrich_session_record(
        db_service,
        llm_service,
        session,
    )

    tier1_profile_output = None
    current_profile = await db_service.get_user_profile(user_id)
    if current_profile:
        tier1_profile_output = await maybe_update_tier1_profile(
            llm_service,
            current_profile,
            session_record,
        )

    (
        tier3_updated,
        tier3_version,
        tier3_update,
        tier3_change_summary,
    ) = await prepare_tier3_update_payload(
        db_service,
        llm_service,
        user_id,
        session_record,
    )

    plan_assessment = None
    plan_recommendations: list[dict[str, Any]] = []
    if current_plan:
        plan_assessment = await planning_agent.assess_plan_effectiveness(current_plan)
        plan_recommendations = await planning_agent.recommend_plan_adjustments(
            current_plan
        )

    tier4_updated = False
    session_summary_payload = await generate_session_summary_payload(
        llm_service,
        session_record,
    )
    session_summary = session_summary_payload["summary"]

    if current_plan:
        tier4_updated = await apply_tier4_updates(
            db_service,
            planning_agent,
            user_id,
            current_plan,
            session_context,
            plan_assessment,
            plan_recommendations,
            session_summary,
            tier3_updated,
        )

    reflection = {
        "session_id": session.session_id,
        "timestamp": session.timestamp.isoformat(),
        "user_id": user_id,
        "session_context": {
            "key_themes": session_context.key_themes,
            "emotional_state": session_context.emotional_state,
            "insights": session_context.insights,
            "progress_indicators": session_context.progress_indicators,
        },
        "therapeutic_memory": {
            "total_sessions": len(memory.session_contexts),
            "relationship_quality": memory.relationship_quality,
            "dominant_themes": list(memory.recurring_themes.keys())[:5],
            "emotional_progression": (
                memory.emotional_patterns[-5:] if memory.emotional_patterns else []
            ),
        },
        "patterns": patterns,
        "continuity_context": continuity_context,
        "plan_assessment": plan_assessment,
        "plan_recommendations": plan_recommendations,
        "session_summary": session_summary,
        "reflection_generated_at": datetime.now().isoformat(),
        "agents_used": [
            "TrioMemoryAgent",
            "TrioPlanningAgent",
            "TrioReflectionAgent",
        ],
        "tier3_updated": tier3_updated,
        "tier3_version": tier3_version,
        "tier3_change_summary": tier3_change_summary,
        "tier4_updated": tier4_updated,
        "tier1_updated": bool(tier1_profile_output),
    }

    logger.info("Comprehensive reflection generated for session %s", session.session_id)
    return (
        reflection,
        tier1_profile_output,
        tier2_enrichment,
        tier3_update,
    )


async def gather_therapeutic_insights(
    *,
    db_service,
    memory_agent,
    planning_agent,
    user_id: str,
) -> dict[str, Any]:
    """Gather cross-session therapeutic insights payload."""
    logger.info(
        "TrioReflectionAgent: Gathering therapeutic insights for user %s",
        user_id,
    )

    try:
        memory = await memory_agent.get_therapeutic_memory()
        patterns = await memory_agent.identify_patterns()
        recent_context = await memory_agent.get_recent_context(num_sessions=5)

        current_plan = await db_service.get_current_therapy_plan(user_id)
        plan_evolution = planning_agent.get_plan_evolution_summary()

        plan_assessment = None
        if current_plan:
            plan_assessment = await planning_agent.assess_plan_effectiveness(
                current_plan
            )

        recommendations = await generate_combined_recommendations(
            planning_agent,
            memory,
            patterns,
            current_plan,
        )

        return {
            "user_id": user_id,
            "insights_generated_at": datetime.now().isoformat(),
            "memory_insights": {
                "total_sessions": len(memory.session_contexts),
                "relationship_quality": memory.relationship_quality,
                "recurring_themes": dict(memory.recurring_themes),
                "emotional_patterns": memory.emotional_patterns,
                "recent_progress": recent_context.get("insights", []),
                "patterns": patterns,
            },
            "planning_insights": {
                "current_plan_id": current_plan.plan_id if current_plan else None,
                "current_plan_version": current_plan.version if current_plan else None,
                "plan_effectiveness": plan_assessment,
                "plan_evolution": plan_evolution,
            },
            "recommendations": recommendations,
        }
    except Exception as exc:
        logger.error("Failed to gather therapeutic insights: %s", exc, exc_info=True)
        return {
            "user_id": user_id,
            "error": str(exc),
            "insights_generated_at": datetime.now().isoformat(),
        }
