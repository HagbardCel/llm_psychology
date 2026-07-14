"""Unit tests for application-event to WebSocket wire mapping."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.api.contracts import (
    MappingContext,
    map_application_event,
    to_chat_turn_failed_event,
    to_token_event,
)
from jung.domain.models import (
    AppSnapshot,
    ChatTurn,
    ChatTurnStatus,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    OperationStatus,
    Stage,
)
from jung.events import (
    ChatTokenGenerated,
    ChatTurnAccepted,
    ChatTurnCompleted,
    ChatTurnFailed,
    OperationChanged,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _chat_turn(*, status: ChatTurnStatus = ChatTurnStatus.PENDING) -> ChatTurn:
    now = _now()
    session_id = uuid4()
    return ChatTurn(
        id=uuid4(),
        session_id=session_id,
        client_message_id=uuid4(),
        status=status,
        user_message_id=uuid4(),
        assistant_message_id=uuid4() if status is ChatTurnStatus.COMPLETE else None,
        error_code=None,
        error_message=None,
        retryable=False,
        created_at=now,
        updated_at=now,
        completed_at=now if status is ChatTurnStatus.COMPLETE else None,
    )


def test_map_chat_turn_accepted() -> None:
    turn = _chat_turn()
    request_id = uuid4()
    event = ChatTurnAccepted(
        session_id=turn.session_id,
        turn_id=turn.id,
        request_id=request_id,
        turn=turn,
    )
    context = MappingContext(request_id=request_id)
    wire = map_application_event(event, context=context)
    assert wire.type == "message_in_progress"
    assert wire.session_id == turn.session_id
    assert wire.turn.id == turn.id


def test_map_token_preserves_sequence_and_text() -> None:
    request_id = uuid4()
    session_id = uuid4()
    turn_id = uuid4()
    event = ChatTokenGenerated(
        session_id=session_id,
        turn_id=turn_id,
        request_id=request_id,
        sequence=3,
        text="delta",
    )
    context = MappingContext(request_id=request_id)
    wire = to_token_event(event, context=context)
    assert wire.sequence == 3
    assert wire.text == "delta"
    assert wire.request_id == request_id


@pytest.mark.parametrize(
    ("error_code", "error_message"),
    [
        (None, "safe"),
        ("", "safe"),
        ("   ", "safe"),
        ("llm_timeout", None),
        ("llm_timeout", ""),
        ("llm_timeout", "   "),
    ],
)
def test_map_chat_turn_failed_requires_durable_fields(
    error_code: str | None,
    error_message: str | None,
) -> None:
    turn = _chat_turn(status=ChatTurnStatus.FAILED)
    turn = turn.model_copy(
        update={
            "error_code": error_code,
            "error_message": error_message,
        }
    )
    event = ChatTurnFailed(session_id=turn.session_id, turn_id=turn.id, turn=turn)
    context = MappingContext(request_id=uuid4())
    with pytest.raises(ValueError, match="durable error"):
        to_chat_turn_failed_event(event, context=context)


def test_map_chat_turn_failed_uses_sanitized_fields() -> None:
    turn = _chat_turn(status=ChatTurnStatus.FAILED)
    turn = turn.model_copy(
        update={
            "error_code": "llm_timeout",
            "error_message": "The language model request timed out.",
            "retryable": True,
        }
    )
    request_id = uuid4()
    event = ChatTurnFailed(session_id=turn.session_id, turn_id=turn.id, turn=turn)
    wire = to_chat_turn_failed_event(event, context=MappingContext(request_id=request_id))
    assert wire.type == "error"
    assert wire.error.code == "llm_timeout"
    assert wire.error.message == "The language model request timed out."
    assert wire.request_id == request_id
    assert wire.error.request_id == request_id
    dumped = json.dumps(wire.model_dump(mode="json"))
    assert "user_id" not in dumped
    assert "provider" not in dumped


def test_operation_changed_shares_request_id_in_nested_errors() -> None:
    now = _now()
    operation = Operation(
        id=uuid4(),
        kind=OperationKind.ASSESSMENT,
        status=OperationStatus.FAILED,
        source_session_id=uuid4(),
        error_code="operation_failed",
        error_message="failed",
        retryable=True,
        attempt=0,
        created_at=now,
        updated_at=now,
    )
    snapshot = AppSnapshot(
        revision=2,
        stage=Stage.ASSESSMENT,
        profile_complete=True,
        current_operation=operation,
        available_commands=frozenset(),
    )
    request_id = uuid4()
    context = MappingContext(request_id=request_id)
    wire = map_application_event(
        OperationChanged(operation, snapshot),
        context=context,
    )
    assert wire.type == "operation_changed"
    assert wire.operation.error is not None
    assert wire.snapshot.operation is not None
    assert wire.operation.error.request_id == request_id
    assert wire.snapshot.operation.error.request_id == request_id


def test_map_message_completed() -> None:
    turn = _chat_turn(status=ChatTurnStatus.COMPLETE)
    turn = turn.model_copy(update={"assistant_message_id": uuid4()})
    message = Message(
        id=turn.assistant_message_id or uuid4(),
        session_id=turn.session_id,
        sequence=2,
        role=MessageRole.ASSISTANT,
        content="hello",
        created_at=_now(),
        client_message_id=None,
    )
    event = ChatTurnCompleted(
        session_id=turn.session_id,
        turn_id=turn.id,
        turn=turn,
        assistant_message=message,
    )
    context = MappingContext(request_id=uuid4())
    wire = map_application_event(event, context=context)
    assert wire.type == "message_completed"
    assert wire.message.content == "hello"
