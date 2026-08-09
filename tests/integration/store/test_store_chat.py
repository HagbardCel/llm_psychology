"""Message persistence tests for intake and therapy chat."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.domain.errors import InvariantViolation, NotFound
from jung.domain.models import Message, MessageRole
from jung.persistence.sqlite_store import SQLiteStore
from tests.integration.application.scenarios import advance_to_ready, open_intake


def _therapy_ready(store: SQLiteStore):
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(
        session_id=therapy_id,
        now=ready.now,
    )
    return therapy_id, ready.now


@pytest.mark.parametrize("stage_setup", ["intake", "therapy"])
def test_append_user_and_complete_chat_response_happy_path(
    store: SQLiteStore, stage_setup: str
) -> None:
    now = datetime.now(UTC)
    if stage_setup == "intake":
        session_id, now = open_intake(store)
    else:
        session_id, now = _therapy_ready(store)

    client_message_id = uuid4()
    user_message_id = uuid4()
    user = store.append_user_message(
        session_id=session_id,
        client_message_id=client_message_id,
        user_message_id=user_message_id,
        content="hello",
        now=now,
    )
    assert user.role is MessageRole.USER
    assert user.client_message_id == client_message_id
    messages = store.list_messages(session_id)
    assert len(messages) == 1
    assert messages[0] == user

    assistant_message_id = uuid4()
    assistant = store.complete_chat_response(
        session_id=session_id,
        client_message_id=client_message_id,
        assistant_message_id=assistant_message_id,
        content="hi there",
        now=now,
    )
    assert assistant.role is MessageRole.ASSISTANT
    assert assistant.client_message_id == client_message_id
    messages = store.list_messages(session_id)
    assert len(messages) == 2
    assert messages[0] == user
    assert messages[1] == assistant


def test_unanswered_user_blocks_second_append(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    store.append_user_message(
        session_id=intake_id,
        client_message_id=uuid4(),
        user_message_id=uuid4(),
        content="first",
        now=now,
    )
    with pytest.raises(
        InvariantViolation,
        match="unanswered user message must be retried",
    ):
        store.append_user_message(
            session_id=intake_id,
            client_message_id=uuid4(),
            user_message_id=uuid4(),
            content="second",
            now=now,
        )


def test_complete_without_matching_user_raises(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    with pytest.raises(NotFound, match="user message"):
        store.complete_chat_response(
            session_id=intake_id,
            client_message_id=uuid4(),
            assistant_message_id=uuid4(),
            content="orphan reply",
            now=now,
        )


def test_get_messages_by_client_id_returns_user_and_assistant(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    client_message_id = uuid4()
    user = store.append_user_message(
        session_id=intake_id,
        client_message_id=client_message_id,
        user_message_id=uuid4(),
        content="hello",
        now=now,
    )
    loaded_user, loaded_assistant = store.get_messages_by_client_id(
        intake_id, client_message_id
    )
    assert loaded_user == user
    assert loaded_assistant is None

    assistant = store.complete_chat_response(
        session_id=intake_id,
        client_message_id=client_message_id,
        assistant_message_id=uuid4(),
        content="hi",
        now=now,
    )
    loaded_user, loaded_assistant = store.get_messages_by_client_id(
        intake_id, client_message_id
    )
    assert loaded_user == user
    assert loaded_assistant == assistant


def test_message_role_and_client_message_id_required() -> None:
    with pytest.raises(ValidationError):
        Message(
            id=uuid4(),
            session_id=uuid4(),
            sequence=1,
            role="system",  # type: ignore[arg-type]
            content="nope",
            client_message_id=uuid4(),
            created_at=datetime.now(UTC),
        )
    with pytest.raises(ValidationError):
        Message(
            id=uuid4(),
            session_id=uuid4(),
            sequence=1,
            role=MessageRole.USER,
            content="nope",
            created_at=datetime.now(UTC),
        )


def test_returned_messages_match_database(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    client_message_id = uuid4()
    user = store.append_user_message(
        session_id=intake_id,
        client_message_id=client_message_id,
        user_message_id=uuid4(),
        content="persisted user",
        now=now,
    )
    assert store.list_messages(intake_id) == [user]

    assistant = store.complete_chat_response(
        session_id=intake_id,
        client_message_id=client_message_id,
        assistant_message_id=uuid4(),
        content="persisted assistant",
        now=now,
    )
    assert store.list_messages(intake_id) == [user, assistant]
    by_client = store.get_messages_by_client_id(intake_id, client_message_id)
    assert by_client == (user, assistant)


def test_complete_chat_response_persists_intake_record(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    client_message_id = uuid4()
    store.append_user_message(
        session_id=intake_id,
        client_message_id=client_message_id,
        user_message_id=uuid4(),
        content="I feel anxious",
        now=now,
    )
    intake_record = {"schema_version": 1, "presenting_problem": {"summary": "anxiety"}}
    store.complete_chat_response(
        session_id=intake_id,
        client_message_id=client_message_id,
        assistant_message_id=uuid4(),
        content="thank you for sharing",
        intake_record=intake_record,
        now=now,
    )
    session = store.get_session(intake_id)
    assert session is not None
    assert session.intake_record == intake_record


def test_intake_record_on_therapy_session_raises_invariant(
    store: SQLiteStore,
) -> None:
    therapy_id, now = _therapy_ready(store)
    client_message_id = uuid4()
    store.append_user_message(
        session_id=therapy_id,
        client_message_id=client_message_id,
        user_message_id=uuid4(),
        content="hello",
        now=now,
    )
    with pytest.raises(InvariantViolation):
        store.complete_chat_response(
            session_id=therapy_id,
            client_message_id=client_message_id,
            assistant_message_id=uuid4(),
            content="hi",
            intake_record={"schema_version": 1},
            now=now,
        )
    user, assistant = store.get_messages_by_client_id(therapy_id, client_message_id)
    assert user is not None
    assert assistant is None


def test_duplicate_assistant_completion_raises(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    client_message_id = uuid4()
    store.append_user_message(
        session_id=intake_id,
        client_message_id=client_message_id,
        user_message_id=uuid4(),
        content="hello",
        now=now,
    )
    store.complete_chat_response(
        session_id=intake_id,
        client_message_id=client_message_id,
        assistant_message_id=uuid4(),
        content="hi",
        now=now,
    )
    with pytest.raises(
        InvariantViolation,
        match="assistant message already exists",
    ):
        store.complete_chat_response(
            session_id=intake_id,
            client_message_id=client_message_id,
            assistant_message_id=uuid4(),
            content="hi again",
            now=now,
        )


def test_assistant_sequence_follows_user(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    client_message_id = uuid4()
    user = store.append_user_message(
        session_id=intake_id,
        client_message_id=client_message_id,
        user_message_id=uuid4(),
        content="hello",
        now=now,
    )
    assistant = store.complete_chat_response(
        session_id=intake_id,
        client_message_id=client_message_id,
        assistant_message_id=uuid4(),
        content="hi",
        now=now,
    )
    assert assistant.sequence == user.sequence + 1
