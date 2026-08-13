"""Authoritative application data → typed phase inputs."""

from __future__ import annotations

from types import MappingProxyType
from uuid import UUID

from jung._application.store_calls import run_store_call
from jung.diagnostics import DiagnosticRecorder
from jung.domain.errors import InvariantViolation, NotFound
from jung.domain.models import (
    Message,
    MessageRole,
    Operation,
    Plan,
    Session,
    SessionKind,
)
from jung.domain.session_artifacts import SessionReview
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentInput
from jung.phases.intake.models import IntakeRecord, IntakeTurnInput
from jung.phases.post_session.models import PostSessionInput
from jung.phases.therapy.models import TherapyTurnInput
from jung.phases.transcript import messages_to_transcript
from jung.styles import StyleDefinition


class PhaseInputs:
    def __init__(
        self,
        *,
        store: SQLiteStore,
        styles: MappingProxyType[str, StyleDefinition],
        recorder: DiagnosticRecorder | None = None,
    ) -> None:
        self._store = store
        self._styles = styles
        self._recorder = recorder

    async def _run_store(self, fn, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        return await run_store_call(fn, *args, recorder=self._recorder, **kwargs)

    async def build_intake_turn_input(self, session_id: UUID) -> IntakeTurnInput:
        stored = await self._run_store(self._store.get_profile)
        session = await self._run_store(self._store.get_session, session_id)
        if stored is None or session is None:
            raise NotFound(f"session {session_id}")
        messages = await self._run_store(self._store.list_messages, session_id)
        transcript = messages_to_transcript(messages)
        latest_user = _latest_user_message_content(messages)
        previous_assistant = _previous_assistant_message_content(messages)
        record = _load_intake_record(session)
        patient_turn_count = sum(
            1 for message in messages if message.role is MessageRole.USER
        )
        return IntakeTurnInput(
            profile=stored.profile,
            current_record=record,
            transcript=transcript,
            latest_user_message=latest_user,
            previous_assistant_message=previous_assistant,
            patient_turn_count=patient_turn_count,
        )

    async def build_therapy_turn_input(self, session_id: UUID) -> TherapyTurnInput:
        stored = await self._run_store(self._store.get_profile)
        session = await self._run_store(self._store.get_session, session_id)
        if stored is None or session is None or session.plan_id is None:
            raise NotFound(f"session {session_id}")
        plan = await self.load_plan_for_session(session_id, session.plan_id)
        style = self._styles.get(plan.selected_style)
        if style is None:
            raise InvariantViolation(f"unknown style: {plan.selected_style}")
        messages = await self._run_store(self._store.list_messages, session_id)
        transcript = messages_to_transcript(messages)
        latest_user = _latest_user_message_content(messages)
        if latest_user is None:
            raise InvariantViolation("therapy turn requires a user message")
        all_sessions = await self._run_store(self._store.list_sessions)
        grounded = await self._run_store(self._store.list_grounded_patient_messages)
        prior_reviews = _prior_therapy_reviews(
            all_sessions,
            exclude_session_id=session_id,
        )
        return TherapyTurnInput(
            profile=stored.profile,
            grounded_patient_messages=tuple(grounded),
            current_plan=plan,
            latest_supervisor_briefing=(
                prior_reviews[-1].briefing if prior_reviews else None
            ),
            transcript=transcript,
            latest_user_message=latest_user,
            is_opening_turn=False,
            selected_style=style,
        )

    async def build_assessment_input(self, operation: Operation) -> AssessmentInput:
        session = await self._run_store(
            self._store.get_session,
            operation.source_session_id,
        )
        stored = await self._run_store(self._store.get_profile)
        if session is None or stored is None:
            raise NotFound(f"session {operation.source_session_id}")
        messages = await self._run_store(
            self._store.list_messages,
            operation.source_session_id,
        )
        return AssessmentInput(
            intake_record=_load_intake_record(session),
            transcript=messages_to_transcript(messages),
            profile=stored.profile,
            available_styles=tuple(self._styles.values()),
        )

    async def build_post_session_input(self, operation: Operation) -> PostSessionInput:
        session = await self._run_store(
            self._store.get_session,
            operation.source_session_id,
        )
        if session is None or session.plan_id is None:
            raise NotFound(f"session {operation.source_session_id}")
        plan = await self.load_plan_for_session(
            operation.source_session_id,
            session.plan_id,
        )
        style = self._styles.get(plan.selected_style)
        if style is None:
            raise InvariantViolation(f"unknown style: {plan.selected_style}")
        messages = await self._run_store(
            self._store.list_messages,
            operation.source_session_id,
        )
        sessions = await self._run_store(self._store.list_sessions)
        grounded = await self._run_store(self._store.list_grounded_patient_messages)
        return PostSessionInput(
            transcript=messages_to_transcript(messages),
            current_plan=plan,
            grounded_patient_messages=tuple(grounded),
            prior_reviews=_prior_therapy_reviews(
                sessions,
                exclude_session_id=operation.source_session_id,
            ),
            selected_style=style,
        )

    async def load_plan_for_session(self, session_id: UUID, plan_id: UUID) -> Plan:
        plans = await self._run_store(
            self._store.list_plans_for_session,
            session_id,
        )
        for plan in plans:
            if plan.id == plan_id:
                return plan
        raise NotFound(f"plan {plan_id}")


def _latest_user_message_content(messages: list[Message]) -> str | None:
    for message in reversed(messages):
        if message.role is MessageRole.USER:
            return message.content
    return None


def _previous_assistant_message_content(messages: list[Message]) -> str | None:
    seen_latest_user = False
    for message in reversed(messages):
        if message.role is MessageRole.USER:
            if seen_latest_user:
                break
            seen_latest_user = True
            continue
        if message.role is MessageRole.ASSISTANT and seen_latest_user:
            return message.content
    return None


def _load_intake_record(session: Session) -> IntakeRecord:
    if session.intake_record:
        return IntakeRecord.model_validate(session.intake_record)
    return IntakeRecord()


def _prior_therapy_reviews(
    sessions: list[Session],
    *,
    exclude_session_id: UUID,
) -> tuple[SessionReview, ...]:
    candidates: list[Session] = []
    for session in sessions:
        if session.id == exclude_session_id:
            continue
        if session.kind is not SessionKind.THERAPY:
            continue
        if session.ended_at is None or session.review is None:
            continue
        candidates.append(session)
    candidates.sort(key=lambda item: (item.started_at, str(item.id)))
    return tuple(session.review for session in candidates if session.review is not None)
