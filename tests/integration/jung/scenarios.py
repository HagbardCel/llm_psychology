"""Fixed workflow scenario helpers for jung integration tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from jung.domain.models import (
    Operation,
    OperationStatus,
    PlanContent,
    Profile,
    SessionKind,
    Stage,
)
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.intake.models import IntakeRecord


@dataclass(frozen=True)
class ReadyScenario:
    intake_session_id: UUID
    initial_plan_id: UUID
    now: datetime


@dataclass(frozen=True)
class PostSessionScenario:
    intake_session_id: UUID
    therapy_session_id: UUID
    current_plan_id: UUID
    post_session_operation_id: UUID
    now: datetime


def open_intake(store: SQLiteStore) -> tuple[UUID, datetime]:
    now = datetime.now(UTC)
    store.update_profile(
        Profile(name="Alex", primary_language="English"),
        expected_revision=store.get_app_state().revision,
        now=now,
    )
    intake = store.get_active_session()
    assert intake is not None
    assert intake.kind == SessionKind.INTAKE
    return intake.id, now


def complete_intake_for_assessment(
    store: SQLiteStore,
    *,
    intake_session_id: UUID,
    now: datetime,
    operation_id: UUID | None = None,
) -> tuple[UUID, UUID, Operation]:
    """Accept one intake turn and atomically complete intake plus assessment op."""
    operation_id = operation_id or uuid4()
    turn_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=intake_session_id,
        client_message_id=uuid4(),
        turn_id=turn_id,
        user_message_id=uuid4(),
        content="intake message",
        now=now,
    )
    _, operation, _ = store.complete_final_intake_turn(
        turn_id,
        assistant_message_id=uuid4(),
        content="intake response",
        intake_record=IntakeRecord().model_dump(mode="json"),
        operation_id=operation_id,
        now=now,
    )
    return turn_id, operation_id, operation


def advance_to_ready(store: SQLiteStore) -> ReadyScenario:
    intake_id, now = open_intake(store)

    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    store.complete_assessment(
        operation_id,
        result={"initial_plan": {"focus": "anxiety"}},
        now=now,
    )
    assert store.get_app_state().stage == Stage.STYLE_SELECTION

    plan_id = uuid4()
    store.select_style_and_create_initial_plan(
        expected_revision=store.get_app_state().revision,
        style_id="cbt",
        plan_id=plan_id,
        content=PlanContent(
            focus="anxiety",
            themes=["worry"],
            goals=["sleep"],
            current_progress="baseline",
            planned_interventions=["grounding"],
            revision_recommendations=["track sleep"],
        ),
        intake_session_id=intake_id,
        now=now,
    )
    assert store.get_app_state().stage == Stage.READY
    return ReadyScenario(
        intake_session_id=intake_id,
        initial_plan_id=plan_id,
        now=now,
    )


def advance_to_post_session(store: SQLiteStore) -> PostSessionScenario:
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        now=ready.now,
    )
    assert store.get_app_state().stage == Stage.THERAPY

    post_op_id = uuid4()
    store.end_therapy_session(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        operation_id=post_op_id,
        now=ready.now,
    )
    assert store.get_app_state().stage == Stage.POST_SESSION
    operation = store.get_operation(post_op_id)
    assert operation is not None
    assert operation.status == OperationStatus.PENDING

    return PostSessionScenario(
        intake_session_id=ready.intake_session_id,
        therapy_session_id=therapy_id,
        current_plan_id=ready.initial_plan_id,
        post_session_operation_id=post_op_id,
        now=ready.now,
    )
