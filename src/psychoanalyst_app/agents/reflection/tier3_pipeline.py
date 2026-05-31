"""Tier 3 clinical formulation update pipeline helpers."""

from __future__ import annotations

import logging
from typing import Any

from psychoanalyst_app.agents.reflection.prompts import (
    build_tier3_detection_prompt,
    build_tier3_update_prompt,
)
from psychoanalyst_app.models.domain import (
    PatientAnalysis,
    PatientAnalysisVersion,
    Session,
)
from psychoanalyst_app.models.llm_outputs import ChangeDetectionDecision
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


async def extract_tier3_change_decision(
    llm_service: LLMService, prompt: str
) -> ChangeDetectionDecision | None:
    """Call the Tier 3 change detection schema."""
    decision = await llm_service.generate_structured_output_async(
        prompt,
        ChangeDetectionDecision,
        method="json_schema",
        phase="post_session_update",
    )
    if not isinstance(decision, ChangeDetectionDecision):
        logger.error(
            "Tier 3 change detection returned unexpected type %s", type(decision)
        )
        return None
    return decision


async def extract_updated_tier3_analysis(
    llm_service: LLMService, prompt: str
) -> PatientAnalysis | None:
    """Call the Tier 3 update schema."""
    analysis = await llm_service.generate_structured_output_async(
        prompt,
        PatientAnalysis,
        method="json_schema",
        phase="post_session_update",
    )
    if not isinstance(analysis, PatientAnalysis):
        logger.error("Tier 3 update returned unexpected type %s", type(analysis))
        return None
    return analysis


async def evaluate_tier3_update_necessity(
    llm_service: LLMService,
    current_analysis: PatientAnalysisVersion,
    session: Session,
) -> tuple[bool, str | None]:
    """Evaluate whether a Tier 3 formulation update is needed."""
    try:
        detection_prompt = build_tier3_detection_prompt(current_analysis, session)
        logger.info(
            "Evaluating Tier 3 update necessity for session %s",
            session.session_id,
        )

        decision = await extract_tier3_change_decision(llm_service, detection_prompt)
        if not decision:
            return (False, None)

        logger.info(
            "Tier 3 update decision: update_needed=%s, summary=%s",
            decision.update_needed,
            decision.change_summary,
        )
        return (decision.update_needed, decision.change_summary)
    except Exception as exc:
        logger.error(
            "Error evaluating Tier 3 update necessity: %s",
            exc,
            exc_info=True,
        )
        return (False, None)


async def generate_updated_tier3_analysis(
    llm_service: LLMService,
    current_analysis: PatientAnalysisVersion,
    session: Session,
    change_summary: str,
) -> PatientAnalysis | None:
    """Generate an updated Tier 3 formulation."""
    try:
        update_prompt = build_tier3_update_prompt(
            current_analysis, session, change_summary
        )
        logger.info(
            "Generating updated Tier 3 analysis for session %s",
            session.session_id,
        )
        updated_analysis = await extract_updated_tier3_analysis(
            llm_service, update_prompt
        )
        if not updated_analysis:
            return None

        logger.info(
            "Successfully generated updated Tier 3 analysis for user %s",
            current_analysis.user_id,
        )
        return updated_analysis
    except Exception as exc:
        logger.error(
            "Error generating updated Tier 3 analysis: %s",
            exc,
            exc_info=True,
        )
        return None


async def prepare_tier3_update_payload(
    db_service: TrioDatabaseService,
    llm_service: LLMService,
    user_id: str,
    session: Session,
) -> tuple[bool, int | None, dict[str, Any] | None, str | None]:
    """Prepare Tier 3 update payload and metadata for persistence."""
    tier3_updated = False
    tier3_version = None
    tier3_update = None
    tier3_change_summary = None

    current_tier3 = await db_service.get_latest_patient_analysis(user_id)
    if not current_tier3:
        logger.info("No Tier 3 analysis exists yet (created during assessment)")
        return (tier3_updated, tier3_version, tier3_update, tier3_change_summary)

    update_needed, change_summary = await evaluate_tier3_update_necessity(
        llm_service, current_tier3, session
    )
    if not (update_needed and change_summary):
        logger.info("Tier 3 update not needed - formulation remains stable")
        return (tier3_updated, tier3_version, tier3_update, tier3_change_summary)

    logger.info("Tier 3 update needed: %s", change_summary)
    updated_analysis = await generate_updated_tier3_analysis(
        llm_service, current_tier3, session, change_summary
    )
    if not updated_analysis:
        logger.warning("Failed to generate Tier 3 update")
        return (tier3_updated, tier3_version, tier3_update, tier3_change_summary)

    tier3_update = {
        "analysis_data": updated_analysis,
        "change_summary": change_summary,
        "supersede_analysis_id": current_tier3.analysis_id,
    }
    tier3_change_summary = change_summary
    tier3_updated = True
    tier3_version = current_tier3.version + 1
    logger.info(
        "Prepared Tier 3 update payload for user %s: %s",
        user_id,
        change_summary,
    )
    return (tier3_updated, tier3_version, tier3_update, tier3_change_summary)
