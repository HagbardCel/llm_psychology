"""Tier 1 extraction helpers for intake."""

from __future__ import annotations

import logging

from psychoanalyst_app.agents.intake.prompts import TIER1_EXTRACTION_PROMPT
from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.models.llm_outputs import PatientProfileExtract
from psychoanalyst_app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


async def extract_tier1_data(
    llm_service: LLMService,
    conversation_history: list[Message],
) -> dict[str, object] | None:
    """Extract Tier 1 patient profile data from intake conversation using LLM."""
    try:
        transcript_lines = []
        for msg in conversation_history:
            role = "Therapist" if msg.role == "assistant" else "Patient"
            transcript_lines.append(f"{role}: {msg.content}")

        transcript = "\n".join(transcript_lines)
        extraction_prompt = TIER1_EXTRACTION_PROMPT.format(
            conversation_transcript=transcript
        )

        logger.info("Extracting Tier 1 patient data from intake conversation...")

        extracted = await llm_service.generate_structured_output_async(
            extraction_prompt,
            PatientProfileExtract,
            method="json_schema",
        )
        if not isinstance(extracted, PatientProfileExtract):
            logger.error("Tier 1 extraction returned unexpected type")
            return None

        tier1_updates = {
            "alias": extracted.basic_info.alias,
            "date_of_birth": extracted.basic_info.date_of_birth,
            "gender": extracted.basic_info.gender,
            "cultural_background": extracted.basic_info.cultural_background,
            "primary_language": extracted.basic_info.primary_language,
            "parents": extracted.family.parents,
            "siblings": extracted.family.siblings,
            "family_atmosphere": extracted.family.family_atmosphere,
            "significant_events": extracted.family.significant_events,
            "education": extracted.history.education,
            "work_history": extracted.history.work_history,
            "relationship_to_work": extracted.history.relationship_to_work,
            "relationships": extracted.context.relationships,
            "social_context": extracted.context.social_context,
            "current_situation": extracted.context.current_situation,
            "preferred_school": extracted.frame.preferred_school,
            "boundary_notes": extracted.frame.boundary_notes,
            "frame_notes": extracted.frame.frame_notes,
        }

        logger.info(
            f"Successfully extracted Tier 1 data for patient: {extracted.basic_info.alias}"
        )

        return tier1_updates

    except Exception as exc:
        logger.error(f"Error extracting Tier 1 data: {exc}", exc_info=True)
        return None
