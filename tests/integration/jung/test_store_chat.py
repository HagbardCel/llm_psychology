"""Shared ChatTurn persistence tests for intake and therapy."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from jung.domain.errors import Busy, InvariantViolation, PersistenceFailure
from jung.domain.models import ChatTurnStatus
from jung.persistence.sqlite_store import SQLiteStore

from .scenarios import advance_to_ready, open_intake


def _therapy_ready(store: SQLiteStore):
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        now=ready.now,
    )
    return therapy_id, ready.now


@pytest.mark.parametrize("stage_setup", ["intake", "therapy"])
def test_chat_turn_acceptance_and_completion(store: SQLiteStore, stage_setup: str) -> None:
    now = datetime.now(UTC)
    if stage_setup == "intake":
        session_id, now = open_intake(store)
    else:
        session_id, now = _therapy_ready(store)

    turn_id = uuid4()
    user_message_id = uuid4()
    client_message_id = uuid4()
    revision = store.get_app_state().revision
    state, turn = store.accept_chat_message(
        expected_revision=revision,
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=turn_id,
        user_message_id=user_message_id,
        content="hello",
        now=now,
    )
    assert state is not None
    assert turn.status == ChatTurnStatus.PENDING
    messages = store.list_messages(session_id)
    assert len(messages) == 1
    assert messages[0].client_message_id == client_message_id

    completed = store.complete_chat_turn(
        turn_id,
        assistant_message_id=uuid4(),
        content="hi there",
        now=now,
    )
    assert completed.status == ChatTurnStatus.COMPLETE
    messages = store.list_messages(session_id)
    assert len(messages) == 2
    assert messages[0].client_message_id == client_message_id
    assert messages[1].client_message_id == client_message_id


def test_duplicate_client_message_id_returns_existing_before_revision_check(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    client_message_id = uuid4()
    turn_id = uuid4()
    user_message_id = uuid4()
    revision = store.get_app_state().revision
    store.accept_chat_message(
        expected_revision=revision,
        session_id=intake_id,
        client_message_id=client_message_id,
        turn_id=turn_id,
        user_message_id=user_message_id,
        content="hello",
        now=now,
    )
    state, duplicate = store.accept_chat_message(
        expected_revision=99,
        session_id=intake_id,
        client_message_id=client_message_id,
        turn_id=uuid4(),
        user_message_id=uuid4(),
        content="ignored",
        now=now,
    )
    assert state is None
    assert duplicate.id == turn_id
    assert store.get_app_state().revision == revision + 1
    messages = store.list_messages(intake_id)
    assert len(messages) == 1
    assert messages[0].content == "hello"
    assert messages[0].client_message_id == client_message_id


def test_one_pending_turn_blocks_second_acceptance(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=intake_id,
        client_message_id=uuid4(),
        turn_id=uuid4(),
        user_message_id=uuid4(),
        content="first",
        now=now,
    )
    with pytest.raises(Busy):
        store.accept_chat_message(
            expected_revision=store.get_app_state().revision,
            session_id=intake_id,
            client_message_id=uuid4(),
            turn_id=uuid4(),
            user_message_id=uuid4(),
            content="second",
            now=now,
        )


def test_failed_chat_turn_preserves_user_message(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    turn_id = uuid4()
    user_message_id = uuid4()
    client_message_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=intake_id,
        client_message_id=client_message_id,
        turn_id=turn_id,
        user_message_id=user_message_id,
        content="hello",
        now=now,
    )
    failed = store.fail_chat_turn(
        turn_id,
        error_code="llm_timeout",
        error_message="timeout",
        retryable=True,
        now=now,
    )
    assert failed.status == ChatTurnStatus.FAILED
    messages = store.list_messages(intake_id)
    assert len(messages) == 1
    assert messages[0].id == user_message_id
    assert messages[0].client_message_id == client_message_id


def test_failed_non_retryable_u1_does_not_associate_later_assistant_with_u1(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    u1_client_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=intake_id,
        client_message_id=u1_client_id,
        turn_id=uuid4(),
        user_message_id=uuid4(),
        content="first",
        now=now,
    )
    store.fail_chat_turn(
        store.get_chat_turn_by_client_id(intake_id, u1_client_id).id,
        error_code="invalid_llm_output",
        error_message="bad output",
        retryable=False,
        now=now,
    )
    u2_client_id = uuid4()
    turn_two = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=intake_id,
        client_message_id=u2_client_id,
        turn_id=turn_two,
        user_message_id=uuid4(),
        content="second",
        now=now,
    )
    store.complete_chat_turn(
        turn_two,
        assistant_message_id=uuid4(),
        content="reply two",
        now=now,
    )
    messages = store.list_messages(intake_id)
    assert len(messages) == 3
    assert messages[0].client_message_id == u1_client_id
    assert messages[1].client_message_id == u2_client_id
    assert messages[2].client_message_id == u2_client_id
    assert messages[2].client_message_id != u1_client_id


def test_duplicate_user_message_id_rejected_on_second_accept(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    user_message_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=intake_id,
        client_message_id=uuid4(),
        turn_id=uuid4(),
        user_message_id=user_message_id,
        content="hello",
        now=now,
    )
    store.fail_chat_turn(
        store.get_active_chat_turn().id,
        error_code="llm_timeout",
        error_message="timeout",
        retryable=True,
        now=now,
    )
    with pytest.raises(PersistenceFailure):
        store.accept_chat_message(
            expected_revision=store.get_app_state().revision,
            session_id=intake_id,
            client_message_id=uuid4(),
            turn_id=uuid4(),
            user_message_id=user_message_id,
            content="duplicate user message",
            now=now,
        )


def test_duplicate_assistant_message_id_rejected_on_complete(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    turn_one = uuid4()
    assistant_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=intake_id,
        client_message_id=uuid4(),
        turn_id=turn_one,
        user_message_id=uuid4(),
        content="one",
        now=now,
    )
    store.complete_chat_turn(
        turn_one,
        assistant_message_id=assistant_id,
        content="reply one",
        now=now,
    )
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=intake_id,
        client_message_id=uuid4(),
        turn_id=uuid4(),
        user_message_id=uuid4(),
        content="two",
        now=now,
    )
    with pytest.raises(PersistenceFailure):
        store.complete_chat_turn(
            store.get_active_chat_turn().id,
            assistant_message_id=assistant_id,
            content="duplicate assistant",
            now=now,
        )


@pytest.mark.parametrize("action", ["complete", "fail"])
def test_late_chat_callback_rejected(store: SQLiteStore, action: str) -> None:
    intake_id, now = open_intake(store)
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
    store.complete_chat_turn(
        turn_id,
        assistant_message_id=uuid4(),
        content="done",
        now=now,
    )
    if action == "complete":
        with pytest.raises(InvariantViolation):
            store.complete_chat_turn(
                turn_id,
                assistant_message_id=uuid4(),
                content="late",
                now=now,
            )
    else:
        with pytest.raises(InvariantViolation):
            store.fail_chat_turn(
                turn_id,
                error_code="late",
                error_message="too late",
                retryable=False,
                now=now,
            )


def test_concurrent_duplicate_client_message_id_is_idempotent(
    store_path,
) -> None:
    store_a = SQLiteStore(store_path)
    store_a.initialize()
    intake_id, now = open_intake(store_a)
    revision = store_a.get_app_state().revision
    client_message_id = uuid4()
    turn_a_id = uuid4()
    turn_b_id = uuid4()
    user_message_a_id = uuid4()
    user_message_b_id = uuid4()
    store_b = SQLiteStore(store_path)

    barrier = threading.Barrier(2)
    results: list[tuple] = []
    errors: list[BaseException] = []

    def accept(store: SQLiteStore, turn: UUID, user_msg: UUID) -> None:
        barrier.wait()
        try:
            results.append(
                store.accept_chat_message(
                    expected_revision=revision,
                    session_id=intake_id,
                    client_message_id=client_message_id,
                    turn_id=turn,
                    user_message_id=user_msg,
                    content="hello",
                    now=now,
                )
            )
        except BaseException as exc:
            errors.append(exc)

    thread_a = threading.Thread(
        target=accept, args=(store_a, turn_a_id, user_message_a_id)
    )
    thread_b = threading.Thread(
        target=accept, args=(store_b, turn_b_id, user_message_b_id)
    )
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=10)
    thread_b.join(timeout=10)

    assert not thread_a.is_alive()
    assert not thread_b.is_alive()
    assert not errors
    assert len(results) == 2
    states = [result[0] for result in results]
    turns = [result[1] for result in results]
    assert sum(state is None for state in states) == 1
    assert sum(state is not None for state in states) == 1
    assert turns[0].id == turns[1].id
    assert turns[0].id in {turn_a_id, turn_b_id}
    assert store_a.get_app_state().revision == revision + 1
    messages = store_a.list_messages(intake_id)
    assert len(messages) == 1
    assert messages[0].id in {user_message_a_id, user_message_b_id}


def test_complete_chat_turn_persists_intake_record_atomically(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    turn_id = uuid4()
    user_message_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=intake_id,
        client_message_id=uuid4(),
        turn_id=turn_id,
        user_message_id=user_message_id,
        content="I feel anxious",
        now=now,
    )
    intake_record = {"schema_version": 1, "presenting_problem": {"summary": "anxiety"}}
    store.complete_chat_turn(
        turn_id,
        assistant_message_id=uuid4(),
        content="thank you for sharing",
        intake_record=intake_record,
        now=now,
    )
    session = store.get_session(intake_id)
    assert session is not None
    assert session.intake_record == intake_record


def test_failed_chat_turn_preserves_intake_record_then_retry_updates(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    first_turn_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=intake_id,
        client_message_id=uuid4(),
        turn_id=first_turn_id,
        user_message_id=uuid4(),
        content="first message",
        now=now,
    )
    first_record = {"schema_version": 1, "presenting_problem": {"summary": "first"}}
    store.complete_chat_turn(
        first_turn_id,
        assistant_message_id=uuid4(),
        content="response one",
        intake_record=first_record,
        now=now,
    )

    retry_turn_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=intake_id,
        client_message_id=uuid4(),
        turn_id=retry_turn_id,
        user_message_id=uuid4(),
        content="second message",
        now=now,
    )
    store.fail_chat_turn(
        retry_turn_id,
        error_code="llm_timeout",
        error_message="stream failed",
        retryable=True,
        now=now,
    )
    session = store.get_session(intake_id)
    assert session is not None
    assert session.intake_record == first_record

    store.retry_chat_turn(
        retry_turn_id,
        expected_revision=store.get_app_state().revision,
        now=now,
    )
    store.complete_chat_turn(
        retry_turn_id,
        assistant_message_id=uuid4(),
        content="response two",
        intake_record={"schema_version": 1, "presenting_problem": {"summary": "updated"}},
        now=now,
    )
    session = store.get_session(intake_id)
    assert session is not None
    assert session.intake_record == {
        "schema_version": 1,
        "presenting_problem": {"summary": "updated"},
    }


def test_intake_record_on_therapy_session_raises_invariant(
    store: SQLiteStore,
) -> None:
    therapy_id, now = _therapy_ready(store)
    turn_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        client_message_id=uuid4(),
        turn_id=turn_id,
        user_message_id=uuid4(),
        content="hello",
        now=now,
    )
    with pytest.raises(InvariantViolation):
        store.complete_chat_turn(
            turn_id,
            assistant_message_id=uuid4(),
            content="hi",
            intake_record={"schema_version": 1},
            now=now,
        )
