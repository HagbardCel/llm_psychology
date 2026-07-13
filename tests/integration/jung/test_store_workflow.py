"""Workflow-oriented store transaction tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.domain.errors import InvariantViolation, PersistenceFailure, RevisionConflict
from jung.domain.models import (
    CommandName,
    NewPlanRevision,
    OperationKind,
    OperationStatus,
    PlanContent,
    Profile,
    SessionKind,
    Stage,
)
from jung.persistence.sqlite_store import SQLiteStore
from jung.workflow import available_commands

from .scenarios import advance_to_post_session, advance_to_ready, open_intake


def _plan_content(**overrides: object) -> PlanContent:
    values = {
        "focus": "anxiety",
        "themes": ["worry"],
        "goals": ["sleep"],
        "current_progress": "baseline",
        "planned_interventions": ["grounding"],
        "revision_recommendations": ["track sleep"],
    }
    values.update(overrides)
    return PlanContent(**values)


def test_incomplete_profile_does_not_create_session(store: SQLiteStore) -> None:
    store.update_profile(
        Profile(name="", primary_language="English"),
        expected_revision=0,
        now=datetime.now(UTC),
    )
    assert store.get_app_state().stage == Stage.SETUP
    assert store.get_active_session() is None


def test_write_uses_transaction_now_for_revision_timestamp(store: SQLiteStore) -> None:
    fixed_now = datetime(2026, 7, 12, 10, 30, tzinfo=UTC)
    store.update_profile(
        Profile(name="Alex", primary_language="English"),
        expected_revision=0,
        now=fixed_now,
    )
    state = store.get_app_state()
    assert state.updated_at == fixed_now


def test_complete_profile_creates_one_open_intake_session(store: SQLiteStore) -> None:
    intake_id, _now = open_intake(store)
    session = store.get_active_session()
    assert session is not None
    assert session.id == intake_id
    assert session.kind == SessionKind.INTAKE
    assert session.ended_at is None
    assert store.get_app_state().stage == Stage.INTAKE
    assert store.get_app_state().revision == 1


def test_intake_profile_edit_reuses_session(store: SQLiteStore) -> None:
    open_intake(store)
    revision = store.get_app_state().revision
    now = datetime.now(UTC)
    active_before = store.get_active_session()
    assert active_before is not None
    store.update_profile(
        Profile(name="Alexandra", primary_language="English"),
        expected_revision=revision,
        now=now,
    )
    active_after = store.get_active_session()
    assert active_after is not None
    assert active_after.id == active_before.id


def test_intake_profile_edit_cannot_make_profile_incomplete(store: SQLiteStore) -> None:
    open_intake(store)
    with pytest.raises(InvariantViolation):
        store.update_profile(
            Profile(name=" ", primary_language="English"),
            expected_revision=store.get_app_state().revision,
            now=datetime.now(UTC),
        )


def test_finish_intake_closes_session_and_creates_assessment(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    session = store.get_session(intake_id)
    assert session is not None
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
    intake_id, now = open_intake(store)
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
    ready = advance_to_ready(store)
    plan = store.get_current_plan()
    assert plan is not None
    assert plan.source_session_id == ready.intake_session_id


def test_operation_failure_preserves_stage(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
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
    intake_id, now = open_intake(store)
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


def test_complete_post_session_commits_all_artifacts(store: SQLiteStore) -> None:
    scenario = advance_to_post_session(store)
    new_plan_id = uuid4()
    briefing = {"summary": "session notes"}
    store.mark_operation_running(scenario.post_session_operation_id, now=scenario.now)
    state = store.complete_post_session(
        scenario.post_session_operation_id,
        summary="good session",
        briefing=briefing,
        derived_profile={"insight": "progress"},
        new_plan=NewPlanRevision(
            plan_id=new_plan_id,
            content=_plan_content(
                goals=["sleep better"],
                current_progress="improved",
                planned_interventions=["homework"],
                revision_recommendations=["continue tracking"],
            ),
        ),
        now=scenario.now,
    )
    assert state.stage == Stage.READY
    session = store.get_session(scenario.therapy_session_id)
    assert session is not None
    assert session.summary == "good session"
    assert session.briefing == briefing
    plan = store.get_current_plan()
    assert plan is not None
    assert plan.id == new_plan_id
    assert plan.version == 2
    assert plan.selected_style == "cbt"
    assert plan.supersedes_plan_id == scenario.current_plan_id
    assert plan.session_briefing == briefing
    assert plan.source_session_id == scenario.therapy_session_id


def test_complete_post_session_without_plan_revision(store: SQLiteStore) -> None:
    scenario = advance_to_post_session(store)
    store.mark_operation_running(scenario.post_session_operation_id, now=scenario.now)
    state = store.complete_post_session(
        scenario.post_session_operation_id,
        summary="steady session",
        briefing={"summary": "no plan change"},
        derived_profile={"insight": "progress"},
        new_plan=None,
        now=scenario.now,
    )
    assert state.stage == Stage.READY
    plan = store.get_current_plan()
    assert plan is not None
    assert plan.id == scenario.current_plan_id
    assert plan.version == 1
    operation = store.get_operation(scenario.post_session_operation_id)
    assert operation is not None
    assert operation.result == {
        "plan_id": None,
        "plan_version": None,
        "profile_changed": True,
    }


def test_complete_post_session_rolls_back_all_artifacts(store: SQLiteStore) -> None:
    scenario = advance_to_post_session(store)
    stored_profile = store.get_profile()
    assert stored_profile is not None
    original_derived_profile = stored_profile.derived_profile
    original_plan_id = scenario.current_plan_id

    with sqlite3.connect(store.database_path) as conn:
        original_plan_count = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]

    store.mark_operation_running(scenario.post_session_operation_id, now=scenario.now)
    revision_before = store.get_app_state().revision
    with pytest.raises(PersistenceFailure):
        store.complete_post_session(
            scenario.post_session_operation_id,
            summary="good session",
            briefing={"summary": "session notes"},
            derived_profile={"insight": "changed"},
            new_plan=NewPlanRevision(
                plan_id=scenario.current_plan_id,
                content=_plan_content(
                    goals=["sleep better"],
                    current_progress="improved",
                    planned_interventions=["homework"],
                    revision_recommendations=["continue tracking"],
                ),
            ),
            now=scenario.now,
        )

    state = store.get_app_state()
    assert state.stage == Stage.POST_SESSION
    assert state.revision == revision_before

    session = store.get_session(scenario.therapy_session_id)
    assert session is not None
    assert session.summary is None
    assert session.briefing is None

    stored_profile = store.get_profile()
    assert stored_profile is not None
    assert stored_profile.derived_profile == original_derived_profile
    assert stored_profile.current_plan_id == original_plan_id

    current_plan = store.get_current_plan()
    assert current_plan is not None
    assert current_plan.id == original_plan_id

    operation = store.get_operation(scenario.post_session_operation_id)
    assert operation is not None
    assert operation.status == OperationStatus.RUNNING
    assert operation.result is None

    with sqlite3.connect(store.database_path) as conn:
        plan_count = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
    assert plan_count == original_plan_count


def test_complete_assessment_rejects_invalid_json_before_persistence(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    store.finish_intake_and_create_assessment(
        expected_revision=store.get_app_state().revision,
        intake_session_id=intake_id,
        operation_id=operation_id,
        now=now,
    )
    store.mark_operation_running(operation_id, now=now)
    with pytest.raises(InvariantViolation):
        store.complete_assessment(
            operation_id,
            result={"initial_plan": {"focus": float("nan")}},
            now=now,
        )


def test_select_style_rejects_malformed_plan_list_elements(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
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
    with pytest.raises(ValidationError):
        store.select_style_and_create_initial_plan(
            expected_revision=store.get_app_state().revision,
            style_id="cbt",
            plan_id=uuid4(),
            content=_plan_content(goals=["   "]),
            intake_session_id=intake_id,
            now=now,
        )


def test_complete_assessment_requires_running_operation(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    store.finish_intake_and_create_assessment(
        expected_revision=store.get_app_state().revision,
        intake_session_id=intake_id,
        operation_id=operation_id,
        now=now,
    )
    with pytest.raises(InvariantViolation):
        store.complete_assessment(
            operation_id,
            result={"initial_plan": {"focus": "anxiety"}},
            now=now,
        )


@pytest.mark.parametrize("action", ["complete", "fail"])
def test_late_operation_callback_rejected(
    store: SQLiteStore, action: str
) -> None:
    intake_id, now = open_intake(store)
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
    if action == "complete":
        with pytest.raises(InvariantViolation):
            store.complete_assessment(
                operation_id,
                result={"initial_plan": {"focus": "again"}},
                now=now,
            )
    else:
        with pytest.raises(InvariantViolation):
            store.fail_operation(
                operation_id,
                error_code="late",
                error_message="too late",
                retryable=False,
                now=now,
            )


def test_complete_post_session_requires_running_operation(store: SQLiteStore) -> None:
    scenario = advance_to_post_session(store)
    with pytest.raises(InvariantViolation):
        store.complete_post_session(
            scenario.post_session_operation_id,
            summary="too early",
            briefing={},
            derived_profile={"insight": "x"},
            new_plan=None,
            now=scenario.now,
        )


def test_stale_revision_leaves_database_unchanged(store: SQLiteStore) -> None:
    open_intake(store)
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


def test_non_retryable_failed_operation_hides_retry_command(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
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
        error_code="permanent",
        error_message="cannot retry",
        retryable=False,
        now=now,
    )
    facts = store.load_snapshot_facts()
    assert facts.operation_retryable is False
    assert CommandName.RETRY_OPERATION not in available_commands(facts)


def test_finish_intake_is_idempotent_by_session_key(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    revision = store.get_app_state().revision
    _, first_operation = store.finish_intake_and_create_assessment(
        expected_revision=revision,
        intake_session_id=intake_id,
        operation_id=operation_id,
        now=now,
    )
    first_state = store.get_app_state()
    second_state, second_operation = store.finish_intake_and_create_assessment(
        expected_revision=revision - 1,
        intake_session_id=intake_id,
        operation_id=uuid4(),
        now=now,
    )
    assert second_state == first_state
    assert second_operation.id == first_operation.id
    assert second_operation.status == first_operation.status
    assert store.get_app_state().revision == revision + 1
    with sqlite3.connect(store.database_path) as conn:
        count = conn.execute(
            """
            SELECT COUNT(*) FROM operations
            WHERE kind = ? AND source_session_id = ?
            """,
            (OperationKind.ASSESSMENT.value, str(intake_id)),
        ).fetchone()[0]
    assert count == 1


def test_end_therapy_session_is_idempotent_by_session_key(store: SQLiteStore) -> None:
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        now=ready.now,
    )
    post_op_id = uuid4()
    revision = store.get_app_state().revision
    _, first_operation = store.end_therapy_session(
        expected_revision=revision,
        session_id=therapy_id,
        operation_id=post_op_id,
        now=ready.now,
    )
    first_state = store.get_app_state()
    second_state, second_operation = store.end_therapy_session(
        expected_revision=revision - 1,
        session_id=therapy_id,
        operation_id=uuid4(),
        now=ready.now,
    )
    assert second_state == first_state
    assert second_operation.id == first_operation.id
    assert second_operation.status == first_operation.status
    assert store.get_app_state().revision == revision + 1
    with sqlite3.connect(store.database_path) as conn:
        count = conn.execute(
            """
            SELECT COUNT(*) FROM operations
            WHERE kind = ? AND source_session_id = ?
            """,
            (OperationKind.POST_SESSION.value, str(therapy_id)),
        ).fetchone()[0]
    assert count == 1


@pytest.mark.parametrize(
    ("path", "invalid_field", "invalid_value"),
    [
        ("initial_plan", "focus", " "),
        ("post_session", "current_progress", " "),
    ],
)
def test_invalid_plan_fields_raise_invariant_violation(
    store: SQLiteStore,
    path: str,
    invalid_field: str,
    invalid_value: str,
) -> None:
    intake_id, now = open_intake(store)
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
    content_kwargs = {
        "focus": "anxiety",
        "themes": ["worry"],
        "goals": ["sleep"],
        "current_progress": "baseline",
        "planned_interventions": ["grounding"],
        "revision_recommendations": ["track sleep"],
    }
    if path == "initial_plan":
        content_kwargs[invalid_field] = invalid_value
        with pytest.raises(ValidationError):
            store.select_style_and_create_initial_plan(
                expected_revision=store.get_app_state().revision,
                style_id="cbt",
                plan_id=uuid4(),
                content=PlanContent(**content_kwargs),
                intake_session_id=intake_id,
                now=now,
            )
        return

    store.select_style_and_create_initial_plan(
        expected_revision=store.get_app_state().revision,
        style_id="cbt",
        plan_id=uuid4(),
        content=PlanContent(**content_kwargs),
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
    store.mark_operation_running(post_op_id, now=now)
    post_content_kwargs = {
        "focus": "anxiety",
        "themes": ["worry"],
        "goals": ["sleep better"],
        "current_progress": "improved",
        "planned_interventions": ["homework"],
        "revision_recommendations": ["continue tracking"],
    }
    post_content_kwargs[invalid_field] = invalid_value
    with pytest.raises(ValidationError):
        store.complete_post_session(
            post_op_id,
            summary="good session",
            briefing={"summary": "notes"},
            derived_profile={"insight": "progress"},
            new_plan=NewPlanRevision(
                plan_id=uuid4(),
                content=PlanContent(**post_content_kwargs),
            ),
            now=now,
        )


def test_complete_post_session_empty_profile_patch_preserves_none(store: SQLiteStore) -> None:
    scenario = advance_to_post_session(store)
    stored_before = store.get_profile()
    assert stored_before is not None
    assert stored_before.derived_profile is None
    updated_before = stored_before.updated_at

    store.mark_operation_running(scenario.post_session_operation_id, now=scenario.now)
    store.complete_post_session(
        scenario.post_session_operation_id,
        summary="steady session",
        briefing={"summary": "no profile change"},
        derived_profile=None,
        new_plan=None,
        now=scenario.now,
    )

    stored_after = store.get_profile()
    assert stored_after is not None
    assert stored_after.derived_profile is None
    assert stored_after.updated_at == updated_before
    operation = store.get_operation(scenario.post_session_operation_id)
    assert operation is not None
    assert operation.result == {
        "plan_id": None,
        "plan_version": None,
        "profile_changed": False,
    }


def test_complete_post_session_empty_profile_patch_preserves_sparse_mapping(
    store: SQLiteStore,
) -> None:
    scenario = advance_to_post_session(store)
    sparse = {"custom_observation": "existing"}
    store.mark_operation_running(scenario.post_session_operation_id, now=scenario.now)
    store.complete_post_session(
        scenario.post_session_operation_id,
        summary="first session",
        briefing={"summary": "seed"},
        derived_profile=sparse,
        new_plan=None,
        now=scenario.now,
    )
    stored_before = store.get_profile()
    assert stored_before is not None
    updated_before = stored_before.updated_at

    post_op_id = uuid4()
    therapy_id = uuid4()
    store.start_therapy_session(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        now=scenario.now,
    )
    store.end_therapy_session(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        operation_id=post_op_id,
        now=scenario.now,
    )
    store.mark_operation_running(post_op_id, now=scenario.now)
    store.complete_post_session(
        post_op_id,
        summary="second session",
        briefing={"summary": "no profile change"},
        derived_profile=sparse,
        new_plan=None,
        now=scenario.now,
    )

    stored_after = store.get_profile()
    assert stored_after is not None
    assert stored_after.derived_profile == sparse
    assert "observations" not in (stored_after.derived_profile or {})
    assert stored_after.updated_at == updated_before
