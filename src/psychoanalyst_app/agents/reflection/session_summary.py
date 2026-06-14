"""Session summary, briefing, plan snapshot, and reflection formatting helpers."""

from __future__ import annotations

import logging
import uuid
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
from psychoanalyst_app.models.llm_outputs import (
    SessionBriefing,
    StructuredTherapyPlanOutput,
)
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
