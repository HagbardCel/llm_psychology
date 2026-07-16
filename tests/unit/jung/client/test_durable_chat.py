"""Unit tests for durable chat message inspection."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.api.contracts import (
    MessageResponse,
    SessionDetailResponse,
    SessionHistoryResponse,
)
from jung.client._durable_chat import (
    DurableChatViolation,
    inspect_durable_chat_messages,
)


def _message(
    *,
    session_id,
    client_message_id,
    role: str,
    sequence: int,
) -> MessageResponse:
    return MessageResponse(
        id=uuid4(),
        session_id=session_id,
        sequence=sequence,
        role=role,
        content=f"{role}-{sequence}",
        created_at=datetime.now(UTC),
        client_message_id=client_message_id,
    )


def _history(
    *,
    session_id,
    messages: list[MessageResponse],
) -> SessionHistoryResponse:
    return SessionHistoryResponse(
        session=SessionDetailResponse(
            id=session_id,
            kind="intake",
            started_at=datetime.now(UTC),
        ),
        messages=messages,
        plans=[],
    )


def test_history_session_id_mismatch_raises() -> None:
    session_id = uuid4()
    other_session_id = uuid4()
    client_message_id = uuid4()
    history = _history(
        session_id=other_session_id,
        messages=[
            _message(
                session_id=other_session_id,
                client_message_id=client_message_id,
                role="user",
                sequence=1,
            )
        ],
    )

    with pytest.raises(DurableChatViolation) as raised:
        inspect_durable_chat_messages(
            history,
            expected_session_id=session_id,
            client_message_id=client_message_id,
        )

    assert raised.value.expected_model == "session history for pending turn"


def test_duplicate_user_messages_raise() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    history = _history(
        session_id=session_id,
        messages=[
            _message(
                session_id=session_id,
                client_message_id=client_message_id,
                role="user",
                sequence=1,
            ),
            _message(
                session_id=session_id,
                client_message_id=client_message_id,
                role="user",
                sequence=2,
            ),
        ],
    )

    with pytest.raises(DurableChatViolation) as raised:
        inspect_durable_chat_messages(
            history,
            expected_session_id=session_id,
            client_message_id=client_message_id,
        )

    assert raised.value.expected_model == "SessionHistoryResponse"


def test_duplicate_assistant_messages_raise() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    history = _history(
        session_id=session_id,
        messages=[
            _message(
                session_id=session_id,
                client_message_id=client_message_id,
                role="user",
                sequence=1,
            ),
            _message(
                session_id=session_id,
                client_message_id=client_message_id,
                role="assistant",
                sequence=2,
            ),
            _message(
                session_id=session_id,
                client_message_id=client_message_id,
                role="assistant",
                sequence=3,
            ),
        ],
    )

    with pytest.raises(DurableChatViolation) as raised:
        inspect_durable_chat_messages(
            history,
            expected_session_id=session_id,
            client_message_id=client_message_id,
        )

    assert raised.value.expected_model == "SessionHistoryResponse"


def test_assistant_without_user_raises() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    history = _history(
        session_id=session_id,
        messages=[
            _message(
                session_id=session_id,
                client_message_id=client_message_id,
                role="assistant",
                sequence=1,
            )
        ],
    )

    with pytest.raises(DurableChatViolation) as raised:
        inspect_durable_chat_messages(
            history,
            expected_session_id=session_id,
            client_message_id=client_message_id,
        )

    assert raised.value.expected_model == "SessionHistoryResponse"


def test_matched_message_wrong_session_id_raises() -> None:
    session_id = uuid4()
    other_session_id = uuid4()
    client_message_id = uuid4()
    history = _history(
        session_id=session_id,
        messages=[
            _message(
                session_id=other_session_id,
                client_message_id=client_message_id,
                role="user",
                sequence=1,
            )
        ],
    )

    with pytest.raises(DurableChatViolation) as raised:
        inspect_durable_chat_messages(
            history,
            expected_session_id=session_id,
            client_message_id=client_message_id,
        )

    assert raised.value.expected_model == "SessionHistoryResponse"


def test_neither_message_exists_returns_empty_pair() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    history = _history(session_id=session_id, messages=[])

    durable = inspect_durable_chat_messages(
        history,
        expected_session_id=session_id,
        client_message_id=client_message_id,
    )

    assert durable.user is None
    assert durable.assistant is None


def test_valid_user_only_state() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    user = _message(
        session_id=session_id,
        client_message_id=client_message_id,
        role="user",
        sequence=1,
    )
    history = _history(session_id=session_id, messages=[user])

    durable = inspect_durable_chat_messages(
        history,
        expected_session_id=session_id,
        client_message_id=client_message_id,
    )

    assert durable.user == user
    assert durable.assistant is None


def test_valid_user_assistant_pair() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    user = _message(
        session_id=session_id,
        client_message_id=client_message_id,
        role="user",
        sequence=1,
    )
    assistant = _message(
        session_id=session_id,
        client_message_id=client_message_id,
        role="assistant",
        sequence=2,
    )
    history = _history(session_id=session_id, messages=[user, assistant])

    durable = inspect_durable_chat_messages(
        history,
        expected_session_id=session_id,
        client_message_id=client_message_id,
    )

    assert durable.user == user
    assert durable.assistant == assistant
