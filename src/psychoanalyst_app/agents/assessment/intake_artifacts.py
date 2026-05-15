"""Helpers for extracting intake-derived profile/formulation/plan artifacts."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from psychoanalyst_app.models.data_models import (
    PatientAnalysis,
    PatientAnalysisVersion,
    Session,
)
from psychoanalyst_app.models.structured_output_models import Tier4Extract
from psychoanalyst_app.prompts.assessment_prompts import (
    TIER3_INITIAL_FORMULATION_PROMPT,
    TIER4_INITIAL_PLAN_PROMPT,
)
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


def _format_transcript(intake_session: Session) -> str:
    transcript_lines: list[str] = []
    for msg in intake_session.transcript:
        role = "Therapist" if msg.role == "assistant" else "Patient"
        transcript_lines.append(f"{role}: {msg.content}")
    return "\n".join(transcript_lines)


def _append_if_value(parts: list[str], label: str, value: Any) -> None:
    if value:
        parts.append(f"{label}: {value}")


async def load_user_profile_context(
    db_service: TrioDatabaseService,
    user_id: str,
) -> str | None:
    """Load user profile and render it as Tier 1 context text."""
    try:
        user_profile = await db_service.get_user_profile(user_id)
        if not user_profile:
            logger.warning("No user profile found for user %s", user_id)
            return None

        display_name = user_profile.alias or user_profile.name
        parts = [f"Patient: {display_name}"]

        for label, value in (
            ("DOB", user_profile.data_of_birth),
            ("Gender", user_profile.gender),
            ("Cultural Background", user_profile.cultural_background),
            ("Family - Parents", user_profile.parents),
            ("Family - Siblings", user_profile.siblings),
            ("Family Atmosphere", user_profile.family_atmosphere),
            ("Education", user_profile.education),
            ("Work History", user_profile.work_history),
            ("Relationship to Work", user_profile.relationship_to_work),
            ("Relationships", user_profile.relationships),
            ("Social Context", user_profile.social_context),
            ("Current Situation", user_profile.current_situation),
        ):
            _append_if_value(parts, label, value)

        return "\n".join(parts)
    except Exception as exc:
        logger.error(
            "Error loading patient profile for %s: %s", user_id, exc, exc_info=True
        )
        return None


async def extract_tier3_initial_formulation(
    *,
    llm_service: LLMService,
    intake_session: Session,
    therapy_style: str,
    patient_background: str | None,
) -> PatientAnalysisVersion | None:
    """Extract initial Tier 3 formulation from the intake transcript."""
    try:
        extraction_prompt = TIER3_INITIAL_FORMULATION_PROMPT.format(
            patient_background=patient_background or "No background data",
            intake_transcript=_format_transcript(intake_session),
            therapy_style=therapy_style,
        )

        logger.info("Extracting Tier 3 initial formulation...")
        analysis = await llm_service.generate_structured_output_async(
            extraction_prompt,
            PatientAnalysis,
            method="json_schema",
        )
        if not isinstance(analysis, PatientAnalysis):
            logger.error("Tier 3 extraction returned unexpected type")
            return None

        analysis_version = PatientAnalysisVersion(
            user_id=intake_session.user_id,
            version=1,
            analysis_data=analysis,
            created_at=datetime.now(),
            created_by_session=intake_session.session_id,
            change_summary="Initial formulation created from intake assessment",
        )
        logger.info(
            "Successfully created Tier 3 v1 for user %s", intake_session.user_id
        )
        return analysis_version
    except Exception as exc:
        logger.error("Error extracting Tier 3 formulation: %s", exc, exc_info=True)
        return None


async def extract_tier4_initial_plan(
    *,
    llm_service: LLMService,
    intake_session: Session,
    therapy_style: str,
    patient_background: str | None,
    tier3_formulation: PatientAnalysisVersion | None,
) -> dict[str, Any] | None:
    """Extract initial Tier 4 treatment plan details from intake context."""
    try:
        if tier3_formulation:
            analysis_data = tier3_formulation.analysis_data
            formulation_summary = (
                f"Central Theme: {analysis_data.current_focus.theme}\n"
                "Primary Defenses: "
                f"{', '.join(analysis_data.defenses.primary_defenses)}\n"
                f"Risk Areas: {', '.join(analysis_data.orientation.risk_areas)}"
            )
        else:
            formulation_summary = "No formulation available"

        extraction_prompt = TIER4_INITIAL_PLAN_PROMPT.format(
            patient_background=patient_background or "No background data",
            intake_transcript=_format_transcript(intake_session),
            therapy_style=therapy_style,
            clinical_formulation=formulation_summary,
        )

        logger.info("Extracting Tier 4 initial treatment plan...")
        tier4 = await llm_service.generate_structured_output_async(
            extraction_prompt,
            Tier4Extract,
            method="json_schema",
        )
        if not isinstance(tier4, Tier4Extract):
            logger.error("Tier 4 extraction returned unexpected type")
            return None

        tier4_payload = {
            "initial_goals": tier4.initial_goals,
            "current_progress": tier4.current_progress,
            "planned_interventions": tier4.planned_interventions,
            "status": tier4.status,
        }
        logger.info(
            "Successfully extracted Tier 4 plan details for user %s",
            intake_session.user_id,
        )
        return tier4_payload
    except Exception as exc:
        logger.error("Error extracting Tier 4 treatment plan: %s", exc, exc_info=True)
        return None
