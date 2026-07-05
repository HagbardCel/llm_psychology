"""Session summary and briefing generation for clinical notes."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import trio
from pydantic import ValidationError

from psychoanalyst_app.agents.reflection.prompts import (
    SESSION_SUMMARY_PROMPT,
    build_session_briefing_prompt,
)
from psychoanalyst_app.config import Settings
from psychoanalyst_app.models.domain import Session, TherapyPlan
from psychoanalyst_app.models.llm_outputs import SessionBriefing
from psychoanalyst_app.services.llm_phases import SESSION_ENRICHMENT, SESSION_SUMMARY
from psychoanalyst_app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

OVERCLAIM_PHRASES = (
    "agreed to try",
    "readily accepting",
    "completed the",
    "accepted the",
    "practiced the",
    "implemented the",
    "successfully used",
    "made progress",
    "session advanced",
    "client engaged with",
    "patient engaged with",
)


async def generate_session_summary(llm_service: LLMService, session: Session) -> str:
    """Generate a traditional session summary using blocking LLM call."""
    session_text = "\n".join(f"{msg.role}: {msg.content}" for msg in session.transcript)
    summary_prompt = SESSION_SUMMARY_PROMPT.format(session_text=session_text)
    return await trio.to_thread.run_sync(
        lambda: llm_service.generate_response(
            summary_prompt,
            phase=SESSION_SUMMARY,
        )
    )


async def generate_session_summary_payload(
    llm_service: LLMService,
    session: Session,
) -> dict[str, Any]:
    """Generate backward-compatible simple session summary payload."""
    summary = await generate_session_summary(llm_service, session)
    return {
        "session_id": session.session_id,
        "summary": summary,
        "timestamp": session.timestamp.isoformat(),
    }


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
                f"{evidence.evidence_level} intervention evidence "
                "requires a patient citation"
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


async def extract_session_briefing(
    llm_service: LLMService, prompt: str, *, session_count: int, session_id: str
) -> dict[str, Any]:
    """Generate a validated SessionBriefing payload."""
    briefing = await llm_service.generate_structured_output_async(
        prompt,
        SessionBriefing,
        method="json_schema",
        phase=SESSION_ENRICHMENT,
    )
    if not isinstance(briefing, SessionBriefing):
        raise TypeError("Unexpected SessionBriefing type")

    now = datetime.now().isoformat()
    payload = briefing.model_dump()
    payload.update(
        {
            "generated_at": now,
            "session_count": session_count,
            "last_session_id": session_id,
        }
    )
    return payload


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
