"""Workflow-oriented store transaction tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.domain.errors import InvariantViolation, PersistenceFailure
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
from tests.integration.application.scenarios import (
    advance_to_post_session,
    advance_to_ready,
    complete_intake_for_assessment,
    open_intake,
)


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
        intake_session_id=None,
        now=datetime.now(UTC),
    )
    assert store.load_snapshot_facts().stage == Stage.SETUP
    assert store.get_active_session() is None


def test_complete_profile_advances_to_intake(store: SQLiteStore) -> None:
    fixed_now = datetime(2026, 7, 12, 10, 30, tzinfo=UTC)
    store.update_profile(
        Profile(name="Alex", primary_language="English"),
        intake_session_id=uuid4(),
        now=fixed_now,
    )
    assert store.load_snapshot_facts().stage == Stage.INTAKE
    session = store.get_active_session()
    assert session is not None
    assert session.started_at == fixed_now


def test_intake_profile_edit_updates_profile_keeps_intake_stage(
    store: SQLiteStore,
) -> None:
    open_intake(store)
    profile_before = store.get_profile()
    assert profile_before is not None
    edit_now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    store.update_profile(
        Profile(name="Alexandra", primary_language="English"),
        intake_session_id=None,
        now=edit_now,
    )
    profile_after = store.get_profile()
    assert profile_after is not None
    assert profile_after.profile.name == "Alexandra"
    assert profile_after.updated_at == edit_now
    assert profile_after.updated_at != profile_before.updated_at
    assert store.load_snapshot_facts().stage == Stage.INTAKE


def test_complete_profile_creates_one_open_intake_session(store: SQLiteStore) -> None:
    intake_id, _now = open_intake(store)
    session = store.get_active_session()
    assert session is not None
    assert session.id == intake_id
    assert session.kind == SessionKind.INTAKE
    assert session.ended_at is None
    assert store.load_snapshot_facts().stage == Stage.INTAKE


def test_intake_profile_edit_reuses_session(store: SQLiteStore) -> None:
    open_intake(store)
    now = datetime.now(UTC)
    active_before = store.get_active_session()
    assert active_before is not None
    store.update_profile(
        Profile(name="Alexandra", primary_language="English"),
        intake_session_id=None,
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
            intake_session_id=None,
            now=datetime.now(UTC),
        )


def test_setup_complete_profile_requires_intake_session_id(store: SQLiteStore) -> None:
    with pytest.raises(InvariantViolation):
        store.update_profile(
            Profile(name="Alex", primary_language="English"),
            intake_session_id=None,
            now=datetime.now(UTC),
        )


def test_setup_incomplete_profile_rejects_intake_session_id(store: SQLiteStore) -> None:
    with pytest.raises(InvariantViolation):
        store.update_profile(
            Profile(name="", primary_language="English"),
            intake_session_id=uuid4(),
            now=datetime.now(UTC),
        )


def test_intake_profile_edit_rejects_intake_session_id(store: SQLiteStore) -> None:
    open_intake(store)
    with pytest.raises(InvariantViolation):
        store.update_profile(
            Profile(name="Alexandra", primary_language="English"),
            intake_session_id=uuid4(),
            now=datetime.now(UTC),
        )


def test_complete_final_intake_closes_session_and_creates_assessment(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    session = store.get_session(intake_id)
    assert session is not None
    operation_id = uuid4()
    _, _, operation = complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    state = store.load_snapshot_facts()
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
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    stage = store.complete_assessment(
        operation_id,
        result={"initial_plan": {"focus": "anxiety"}},
        now=now,
    )
    assert stage == Stage.STYLE_SELECTION


def test_initial_plan_uses_intake_session_source(store: SQLiteStore) -> None:
    ready = advance_to_ready(store)
    plan = store.get_current_plan()
    assert plan is not None
    assert plan.source_session_id == ready.intake_session_id


def test_initial_plan_stores_sql_null_for_briefing_and_supersedes(
    store: SQLiteStore,
) -> None:
    ready = advance_to_ready(store)
    plan = store.get_current_plan()
    assert plan is not None
    assert plan.session_briefing is None
    assert plan.supersedes_plan_id is None
    with sqlite3.connect(store.database_path) as conn:
        row = conn.execute(
            """
            SELECT session_briefing_json IS NULL, supersedes_plan_id IS NULL
            FROM plans
            WHERE id = ?
            """,
            (str(plan.id),),
        ).fetchone()
    assert row == (1, 1)
    assert ready.intake_session_id is not None


def test_operation_failure_preserves_stage(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    store.fail_operation(
        operation_id,
        error_code="llm_timeout",
        error_message="timeout",
        retryable=True,
        now=now,
    )
    assert store.load_snapshot_facts().stage == Stage.ASSESSMENT


def test_operation_retry_reuses_row_and_clears_errors(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
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
    stage = store.complete_post_session(
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
    assert stage == Stage.READY
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
    stage = store.complete_post_session(
        scenario.post_session_operation_id,
        summary="steady session",
        briefing={"summary": "no plan change"},
        derived_profile={"insight": "progress"},
        new_plan=None,
        now=scenario.now,
    )
    assert stage == Stage.READY
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

    state = store.load_snapshot_facts()
    assert state.stage == Stage.POST_SESSION

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
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
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
    with pytest.raises(ValidationError):
        store.select_style_and_create_initial_plan(
            style_id="cbt",
            plan_id=uuid4(),
            content=_plan_content(goals=["   "]),
            intake_session_id=intake_id,
            now=now,
        )


def test_complete_assessment_requires_running_operation(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    with pytest.raises(InvariantViolation):
        store.complete_assessment(
            operation_id,
            result={"initial_plan": {"focus": "anxiety"}},
            now=now,
        )


@pytest.mark.parametrize("action", ["complete", "fail"])
def test_late_operation_callback_rejected(store: SQLiteStore, action: str) -> None:
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


def test_non_retryable_failed_operation_hides_retry_command(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
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


def test_complete_final_intake_creates_one_assessment_operation(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
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
        session_id=therapy_id,
        now=ready.now,
    )
    post_op_id = uuid4()
    first_operation = store.end_therapy_session(
        session_id=therapy_id,
        operation_id=post_op_id,
        now=ready.now,
    )
    second_operation = store.end_therapy_session(
        session_id=therapy_id,
        operation_id=uuid4(),
        now=ready.now,
    )
    assert second_operation.id == first_operation.id
    assert second_operation.status == first_operation.status
    assert store.load_snapshot_facts().stage == Stage.POST_SESSION
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
                style_id="cbt",
                plan_id=uuid4(),
                content=PlanContent(**content_kwargs),
                intake_session_id=intake_id,
                now=now,
            )
        return

    store.select_style_and_create_initial_plan(
        style_id="cbt",
        plan_id=uuid4(),
        content=PlanContent(**content_kwargs),
        intake_session_id=intake_id,
        now=now,
    )
    therapy_id = uuid4()
    store.start_therapy_session(
        session_id=therapy_id,
        now=now,
    )
    post_op_id = uuid4()
    store.end_therapy_session(
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


def test_complete_post_session_empty_profile_patch_preserves_none(
    store: SQLiteStore,
) -> None:
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


def test_complete_post_session_store_persists_opaque_derived_profile_json(
    store: SQLiteStore,
) -> None:
    """SQLiteStore treats derived_profile as opaque JSON (no shape policy).

    Canonicalization belongs in merge_derived_profile before persistence.
    """
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
        session_id=therapy_id,
        now=scenario.now,
    )
    store.end_therapy_session(
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


def test_complete_final_intake_rolls_back_all_artifacts(store: SQLiteStore) -> None:
    from jung.phases.intake.models import IntakeRecord

    intake_id, now = open_intake(store)
    client_message_id = uuid4()
    store.append_user_message(
        session_id=intake_id,
        client_message_id=client_message_id,
        user_message_id=uuid4(),
        content="hello",
        now=now,
    )
    before = store.get_session(intake_id)
    assert before is not None
    original_intake = before.intake_record

    with sqlite3.connect(store.database_path) as conn:
        conn.execute(
            """
            CREATE TRIGGER abort_final_intake_session_close
            BEFORE UPDATE OF ended_at ON sessions
            BEGIN
                SELECT RAISE(ABORT, 'injected final intake rollback');
            END
            """
        )
        conn.commit()

    try:
        with pytest.raises(PersistenceFailure):
            store.complete_final_intake_response(
                session_id=intake_id,
                client_message_id=client_message_id,
                assistant_message_id=uuid4(),
                content="goodbye",
                intake_record=IntakeRecord().model_dump(mode="json"),
                operation_id=uuid4(),
                now=now,
            )
    finally:
        with sqlite3.connect(store.database_path) as conn:
            conn.execute("DROP TRIGGER IF EXISTS abort_final_intake_session_close")
            conn.commit()

    assert store.load_snapshot_facts().stage == Stage.INTAKE
    session = store.get_session(intake_id)
    assert session is not None
    assert session.ended_at is None
    assert session.intake_record == original_intake
    user, assistant = store.get_messages_by_client_id(intake_id, client_message_id)
    assert user is not None
    assert assistant is None
    assert store.get_current_operation() is None


def test_load_snapshot_facts_rejects_therapy_without_completed_assessment(
    store: SQLiteStore,
) -> None:
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(session_id=therapy_id, now=ready.now)
    with sqlite3.connect(store.database_path) as conn:
        conn.execute(
            "DELETE FROM operations WHERE kind = ?",
            (OperationKind.ASSESSMENT.value,),
        )
        conn.commit()
    with pytest.raises(
        InvariantViolation, match="THERAPY requires a completed assessment"
    ):
        store.load_snapshot_facts()


def test_load_snapshot_facts_rejects_intake_with_completed_assessment(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    stamp = now.isoformat()
    with sqlite3.connect(store.database_path) as conn:
        conn.execute(
            """
            INSERT INTO operations (
                id, kind, status, source_session_id, attempt, result_json,
                error_code, error_message, retryable, created_at, updated_at,
                started_at, completed_at
            ) VALUES (?, 'assessment', 'complete', ?, 1, '{}', NULL, NULL, 0, ?, ?, ?, ?)
            """,
            (str(uuid4()), str(intake_id), stamp, stamp, stamp, stamp),
        )
        conn.commit()
    with pytest.raises(
        InvariantViolation, match="INTAKE cannot coexist with a completed assessment"
    ):
        store.load_snapshot_facts()


def test_load_snapshot_facts_rejects_assessment_without_intake_record(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    with sqlite3.connect(store.database_path) as conn:
        conn.execute(
            "UPDATE sessions SET intake_record_json = NULL WHERE id = ?",
            (str(intake_id),),
        )
        conn.commit()
    with pytest.raises(InvariantViolation, match="intake_record"):
        store.load_snapshot_facts()
