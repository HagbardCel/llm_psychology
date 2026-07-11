"""Reset and startup recovery tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from jung.domain.models import ChatTurnStatus, OperationStatus, Profile, Stage
from jung.persistence.sqlite_store import SQLiteStore


def test_reset_recreates_clean_database(store_path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    store.complete_profile_and_open_intake(
        Profile(name="Alex", primary_language="English"),
        expected_revision=0,
        intake_session_id=uuid4(),
        now=datetime.now(UTC),
    )
    store.reset_database()
    state = store.get_app_state()
    assert state.stage == Stage.SETUP
    assert state.revision == 0
    assert store.get_active_session() is None


def test_recover_stale_operations_is_idempotent(store: SQLiteStore) -> None:
    intake_id = uuid4()
    now = datetime.now(UTC)
    store.complete_profile_and_open_intake(
        Profile(name="Alex", primary_language="English"),
        expected_revision=0,
        intake_session_id=intake_id,
        now=now,
    )
    operation_id = uuid4()
    store.finish_intake_and_create_assessment(
        expected_revision=store.get_app_state().revision,
        intake_session_id=intake_id,
        operation_id=operation_id,
        now=now,
    )
    store.mark_operation_running(operation_id, now=now)
    revision = store.get_app_state().revision
    recovered = store.recover_stale_operations(now=now)
    assert len(recovered) == 1
    assert recovered[0].status == OperationStatus.PENDING
    assert store.get_app_state().revision == revision + 1
    again = store.recover_stale_operations(now=now)
    assert again == []
    assert store.get_app_state().revision == revision + 1


def test_recover_stale_chat_turns_is_idempotent(store: SQLiteStore) -> None:
    intake_id = uuid4()
    now = datetime.now(UTC)
    store.complete_profile_and_open_intake(
        Profile(name="Alex", primary_language="English"),
        expected_revision=0,
        intake_session_id=intake_id,
        now=now,
    )
    turn_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=intake_id,
        client_message_id=uuid4(),
        turn_id=turn_id,
        user_message_id=uuid4(),
        content="hello",
        now=now,
    )
    revision = store.get_app_state().revision
    recovered = store.recover_stale_chat_turns(now=now)
    assert len(recovered) == 1
    assert recovered[0].status == ChatTurnStatus.FAILED
    assert recovered[0].retryable is True
    assert store.get_app_state().revision == revision + 1
    again = store.recover_stale_chat_turns(now=now)
    assert again == []
    assert len(store.list_messages(intake_id)) == 1
