"""Session summary and briefing generation pipeline helpers."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from psychoanalyst_app.config import Settings
from psychoanalyst_app.models.data_models import Session, TherapyPlan
from psychoanalyst_app.models.briefing_models import SessionBriefing
from psychoanalyst_app.prompts.reflection_prompt_builder import (
    build_session_briefing_prompt,
)
from psychoanalyst_app.services.llm_service import LLMService

from .extractors import extract_session_briefing
from .helpers import generate_session_summary as helper_generate_session_summary

logger = logging.getLogger(__name__)
OVERCLAIM_PHRASES = ("agreed to try", "readily accepting", "completed the")


def validate_session_briefing_evidence(
    briefing: SessionBriefing, session: Session
) -> None:
    """Reject unsupported acceptance, completion, and narrative overclaims."""
    patient_turns = [
        message.content for message in session.transcript if message.role == "user"
    ]
    validated_levels: set[str] = set()
    for evidence in briefing.intervention_evidence:
        if evidence.evidence_level == "proposed":
            continue
        if evidence.patient_turn_index is None or not evidence.patient_evidence:
            raise ValueError(
                f"{evidence.evidence_level} intervention evidence requires a patient citation"
            )
        if not 0 <= evidence.patient_turn_index < len(patient_turns):
            raise ValueError("Intervention evidence patient turn index is out of range")
        cited_turn = patient_turns[evidence.patient_turn_index]
        if evidence.patient_evidence not in cited_turn:
            raise ValueError("Intervention evidence text is not present in cited turn")
        validated_levels.add(evidence.evidence_level)

    narrative = " ".join(
        (
            briefing.narrative_handoff,
            briefing.patient_observations,
            briefing.plan_progression_notes,
        )
    ).lower()
    if any(phrase in narrative for phrase in OVERCLAIM_PHRASES) and not (
        {"accepted", "completed"} & validated_levels
    ):
        raise ValueError("Session briefing contains unsupported agreement language")


async def generate_session_summary_payload(
    llm_service: LLMService,
    session: Session,
) -> dict[str, Any]:
    """Generate backward-compatible simple session summary payload."""
    summary = await helper_generate_session_summary(llm_service, session)
    return {
        "session_id": session.session_id,
        "summary": summary,
        "timestamp": session.timestamp.isoformat(),
    }


async def generate_session_briefing(
    llm_service: LLMService,
    config: Settings,
    session_context: dict[str, Any],
    therapeutic_memory: dict[str, Any],
    plan_assessment: dict[str, Any] | None,
    session: Session,
    therapy_plan: TherapyPlan | None,
) -> dict[str, Any] | None:
    """Generate validated session briefing payload for the next session."""
    logger.info("Generating session briefing for session %s", session.session_id)

    analysis_prompt = build_session_briefing_prompt(
        session_context=session_context,
        therapeutic_memory=therapeutic_memory,
        plan_assessment=plan_assessment,
        session=session,
        therapy_plan=therapy_plan,
        config=config,
    )

    try:
        briefing = await extract_session_briefing(
            llm_service,
            analysis_prompt,
            session_count=therapeutic_memory.get("total_sessions", 0),
            session_id=session.session_id,
        )
        briefing_model = SessionBriefing.model_validate(briefing)
        validate_session_briefing_evidence(briefing_model, session)
        logger.info(
            "Successfully generated session briefing for session %s",
            session.session_id,
        )
        return briefing_model.model_dump(mode="json")
    except ValidationError as exc:
        logger.error("Session briefing failed validation: %s", exc)
        raise
