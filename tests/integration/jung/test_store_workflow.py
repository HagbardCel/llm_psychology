"""Workflow-oriented store transaction tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.domain.errors import InvariantViolation, RevisionConflict
from jung.domain.models import (
    OperationKind,
    OperationStatus,
    Profile,
    SessionKind,
    Stage,
)
from jung.persistence.sqlite_store import SQLiteStore


def _complete_profile(store: SQLiteStore) -> tuple:
    intake_id = uuid4()
    profile = Profile(name="Alex", primary_language="English")
    now = datetime.now(UTC)
    state, session = store.complete_profile_and_open_intake(
        profile,
        expected_revision=store.get_app_state().revision,
        intake_session_id=intake_id,
        now=now,
    )
    return state, session, intake_id, now


def test_incomplete_profile_does_not_create_session(store: SQLiteStore) -> None:
    store.replace_profile(
        Profile(name="", primary_language="English"),
        expected_revision=0,
        now=datetime.now(UTC),
    )
    assert store.get_app_state().stage == Stage.SETUP
    assert store.get_active_session() is None


def test_complete_profile_creates_one_open_intake_session(store: SQLiteStore) -> None:
    _, session, _, _ = _complete_profile(store)
    assert session.kind == SessionKind.INTAKE
    assert session.ended_at is None
    assert store.get_app_state().stage == Stage.INTAKE
    assert store.get_app_state().revision == 1


def test_intake_profile_edit_reuses_session(store: SQLiteStore) -> None:
    _, session, _, now = _complete_profile(store)
    revision = store.get_app_state().revision
    store.replace_profile(
        Profile(name="Alexandra", primary_language="English"),
        expected_revision=revision,
        now=now,
    )
    active = store.get_active_session()
    assert active is not None
    assert active.id == session.id


def test_intake_profile_edit_cannot_make_profile_incomplete(store: SQLiteStore) -> None:
    _complete_profile(store)
    with pytest.raises(InvariantViolation):
        store.replace_profile(
            Profile(name=" ", primary_language="English"),
            expected_revision=store.get_app_state().revision,
            now=datetime.now(UTC),
        )


def test_finish_intake_closes_session_and_creates_assessment(store: SQLiteStore) -> None:
    _, session, intake_id, now = _complete_profile(store)
    revision = store.get_app_state().revision
    operation_id = uuid4()
    state, operation = store.finish_intake_and_create_assessment(
        expected_revision=revision,
        intake_session_id=intake_id,
        operation_id=operation_id,
        now=now,
    )
    assert state.stage == Stage.ASSESSMENT
    closed = store.get_session(session.id)
    assert closed is not None
    assert closed.ended_at is not None
    assert operation.kind == OperationKind.ASSESSMENT
    assert operation.status == OperationStatus.PENDING
    assert store.get_active_session() is None


def test_assessment_completion_advances_to_style_selection(store: SQLiteStore) -> None:
    _, _, intake_id, now = _complete_profile(store)
    operation_id = uuid4()
    store.finish_intake_and_create_assessment(
        expected_revision=store.get_app_state().revision,
        intake_session_id=intake_id,
        operation_id=operation_id,
        now=now,
    )
    store.mark_operation_running(operation_id, now=now)
    state = store.complete_assessment(
        operation_id,
        result={"initial_plan": {"focus": "anxiety"}},
        now=now,
    )
    assert state.stage == Stage.STYLE_SELECTION


def test_initial_plan_uses_intake_session_source(store: SQLiteStore) -> None:
    _, _, intake_id, now = _complete_profile(store)
    operation_id = uuid4()
    store.finish_intake_and_create_assessment(
        expected_revision=store.get_app_state().revision,
        intake_session_id=intake_id,
        operation_id=operation_id,
        now=now,
    )
    store.mark_operation_running(operation_id, now=now)
    store.complete_assessment(
        operation_id,
        result={"initial_plan": {"focus": "anxiety"}},
        now=now,
    )
    plan_id = uuid4()
    store.select_style_and_create_initial_plan(
        expected_revision=store.get_app_state().revision,
        style_id="cbt",
        plan_id=plan_id,
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=["track sleep"],
        intake_session_id=intake_id,
        now=now,
    )
    plan = store.get_current_plan()
    assert plan is not None
    assert plan.source_session_id == intake_id


def test_operation_failure_preserves_stage(store: SQLiteStore) -> None:
    _, _, intake_id, now = _complete_profile(store)
    operation_id = uuid4()
    store.finish_intake_and_create_assessment(
        expected_revision=store.get_app_state().revision,
        intake_session_id=intake_id,
        operation_id=operation_id,
        now=now,
    )
    store.mark_operation_running(operation_id, now=now)
    store.fail_operation(
        operation_id,
        error_code="llm_timeout",
        error_message="timeout",
        retryable=True,
        now=now,
    )
    assert store.get_app_state().stage == Stage.ASSESSMENT


def test_operation_retry_reuses_row_and_clears_errors(store: SQLiteStore) -> None:
    _, _, intake_id, now = _complete_profile(store)
    operation_id = uuid4()
    store.finish_intake_and_create_assessment(
        expected_revision=store.get_app_state().revision,
        intake_session_id=intake_id,
        operation_id=operation_id,
        now=now,
    )
    store.mark_operation_running(operation_id, now=now)
    failed = store.fail_operation(
        operation_id,
        error_code="llm_timeout",
        error_message="timeout",
        retryable=True,
        now=now,
    )
    assert failed.attempt == 1
    retried = store.retry_operation(
        operation_id,
        expected_revision=store.get_app_state().revision,
        now=now,
    )
    assert retried.status == OperationStatus.PENDING
    assert retried.error_code is None
    assert retried.attempt == 1
    running = store.mark_operation_running(operation_id, now=now)
    assert running.attempt == 2


def test_post_session_completion_is_atomic(store: SQLiteStore) -> None:
    _, _, intake_id, now = _complete_profile(store)
    operation_id = uuid4()
    store.finish_intake_and_create_assessment(
        expected_revision=store.get_app_state().revision,
        intake_session_id=intake_id,
        operation_id=operation_id,
        now=now,
    )
    store.mark_operation_running(operation_id, now=now)
    store.complete_assessment(
        operation_id,
        result={"initial_plan": {"focus": "anxiety"}},
        now=now,
    )
    plan_id = uuid4()
    store.select_style_and_create_initial_plan(
        expected_revision=store.get_app_state().revision,
        style_id="cbt",
        plan_id=plan_id,
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=["track sleep"],
        intake_session_id=intake_id,
        now=now,
    )
    therapy_id = uuid4()
    store.start_therapy_session(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        now=now,
    )
    post_op_id = uuid4()
    store.end_therapy_session(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        operation_id=post_op_id,
        now=now,
    )
    new_plan_id = uuid4()
    briefing = {"summary": "session notes"}
    store.mark_operation_running(post_op_id, now=now)
    state = store.complete_post_session(
        post_op_id,
        summary="good session",
        briefing=briefing,
        derived_profile={"insight": "progress"},
        plan_id=new_plan_id,
        plan_version=2,
        selected_style="cbt",
        focus="anxiety",
        themes=["worry"],
        goals=["sleep better"],
        current_progress="improved",
        planned_interventions=["homework"],
        revision_recommendations=["continue tracking"],
        now=now,
    )
    assert state.stage == Stage.READY
    session = store.get_session(therapy_id)
    assert session is not None
    assert session.summary == "good session"
    assert session.briefing == briefing
    plan = store.get_current_plan()
    assert plan is not None
    assert plan.id == new_plan_id
    assert plan.session_briefing == briefing
    assert plan.source_session_id == therapy_id


def test_stale_revision_leaves_database_unchanged(store: SQLiteStore) -> None:
    _complete_profile(store)
    revision = store.get_app_state().revision
    with pytest.raises(RevisionConflict):
        store.finish_intake_and_create_assessment(
            expected_revision=revision - 1,
            intake_session_id=uuid4(),
            operation_id=uuid4(),
            now=datetime.now(UTC),
        )
    assert store.get_app_state().revision == revision
    assert store.get_app_state().stage == Stage.INTAKE
