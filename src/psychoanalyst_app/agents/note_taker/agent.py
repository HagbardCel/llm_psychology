"""NoteTakerAgent: LLM-backed intake patches and session clinical notes."""

from __future__ import annotations

from typing import Any

from psychoanalyst_app.agents.note_taker.intake_patch import (
    IntakePatchExtractionResult,
    extract_intake_record_patch,
)
from psychoanalyst_app.agents.note_taker.session_notes import (
    generate_session_briefing,
    generate_session_summary_payload,
)
from psychoanalyst_app.config import Settings
from psychoanalyst_app.models.domain import Message, Session, TherapyPlan
from psychoanalyst_app.models.intake_record import IntakeRecord
from psychoanalyst_app.services.llm_service import LLMService


class NoteTakerAgent:
    """Stateless agent for note extraction and session note generation."""

    def __init__(
        self,
        *,
        intake_llm_service: LLMService,
        reflection_llm_service: LLMService,
        config: Settings,
    ) -> None:
        self.intake_llm_service = intake_llm_service
        self.reflection_llm_service = reflection_llm_service
        self.config = config

    async def extract_intake_patch(
        self,
        *,
        current_record: IntakeRecord,
        latest_user_message: Message,
        previous_assistant_message: Message | None,
        source_message_index: int,
        timeout_seconds: float,
    ) -> IntakePatchExtractionResult:
        return await extract_intake_record_patch(
            llm_service=self.intake_llm_service,
            current_record=current_record,
            latest_user_message=latest_user_message,
            previous_assistant_message=previous_assistant_message,
            source_message_index=source_message_index,
            timeout_seconds=timeout_seconds,
        )

    async def generate_session_summary_payload(
        self, session: Session
    ) -> dict[str, Any]:
        return await generate_session_summary_payload(
            self.reflection_llm_service,
            session,
        )

    async def generate_session_briefing(
        self,
        *,
        session_context: dict[str, Any],
        therapeutic_memory: dict[str, Any],
        plan_assessment: dict[str, Any] | None,
        session: Session,
        therapy_plan: TherapyPlan | None,
    ) -> dict[str, Any] | None:
        return await generate_session_briefing(
            self.reflection_llm_service,
            self.config,
            session_context,
            therapeutic_memory,
            plan_assessment,
            session,
            therapy_plan,
        )
