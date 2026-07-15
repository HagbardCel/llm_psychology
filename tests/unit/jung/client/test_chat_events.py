"""Unit tests for jung.client._chat_events correlation helpers."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from jung.api.contracts import (
    ChatTurnSummaryResponse,
    ErrorEnvelope,
    ErrorEvent,
    MessageCompletedEvent,
    MessageInProgressEvent,
    TokenEvent,
)
from jung.client._chat_events import (
    ChatEventIdentity,
    ChatEventViolation,
    classify_error,
    identity_after_progress,
    matches_completion,
    matches_token,
)

ROOT = Path(__file__).resolve().parents[4]
CHAT_EVENTS_PATH = ROOT / "src" / "jung" / "client" / "_chat_events.py"


def _turn(
    *,
    session_id: UUID,
    client_message_id: UUID,
    status: str = "pending",
    turn_id: UUID | None = None,
) -> ChatTurnSummaryResponse:
    return ChatTurnSummaryResponse(
        id=turn_id or uuid4(),
        session_id=session_id,
        client_message_id=client_message_id,
        status=status,  # type: ignore[arg-type]
        user_message_id=uuid4(),
    )


def _progress_event(
    *,
    session_id: UUID,
    client_message_id: UUID,
    turn_id: UUID | None = None,
) -> MessageInProgressEvent:
    turn_id = turn_id or uuid4()
    return MessageInProgressEvent(
        type="message_in_progress",
        session_id=session_id,
        turn=_turn(
            session_id=session_id,
            client_message_id=client_message_id,
            turn_id=turn_id,
        ),
    )


def _completion_event(
    *,
    session_id: UUID,
    client_message_id: UUID,
    turn_id: UUID,
) -> MessageCompletedEvent:
    from jung.api.contracts import MessageResponse

    turn = _turn(
        session_id=session_id,
        client_message_id=client_message_id,
        status="complete",
        turn_id=turn_id,
    )
    return MessageCompletedEvent(
        type="message_completed",
        session_id=session_id,
        turn=turn,
        message=MessageResponse(
            id=uuid4(),
            session_id=session_id,
            sequence=2,
            role="assistant",
            content="reply",
            created_at=datetime.now(UTC),
            client_message_id=client_message_id,
        ),
    )


def test_identity_after_progress_establishes_turn_id() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=client_message_id,
        request_id=uuid4(),
    )
    progress = _progress_event(
        session_id=session_id,
        client_message_id=client_message_id,
    )
    updated = identity_after_progress(progress, identity)
    assert updated.turn_id == progress.turn.id


def test_completion_rejects_wrong_turn_id() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=client_message_id,
        request_id=uuid4(),
        turn_id=uuid4(),
    )
    wrong_turn = _completion_event(
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=uuid4(),
    )
    with pytest.raises(ChatEventViolation):
        matches_completion(wrong_turn, identity)


def test_classify_error_durable_before_turn_id_matches_session_client() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=client_message_id,
        request_id=uuid4(),
    )
    durable_request_id = uuid4()
    event = ErrorEvent(
        type="error",
        request_id=durable_request_id,
        error=ErrorEnvelope(
            code="llm_unavailable",
            message="x",
            request_id=durable_request_id,
            retryable=False,
        ),
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=uuid4(),
    )
    assert classify_error(event, identity) is not None


def test_token_matches_request_id_before_turn_id() -> None:
    session_id = uuid4()
    request_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=uuid4(),
        request_id=request_id,
    )
    token = TokenEvent(
        type="token",
        session_id=session_id,
        turn_id=uuid4(),
        request_id=request_id,
        sequence=1,
        text="hi",
    )
    assert matches_token(token, identity) is True


def test_token_wrong_session_before_progress_raises() -> None:
    session_id = uuid4()
    request_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=uuid4(),
        request_id=request_id,
    )
    token = TokenEvent(
        type="token",
        session_id=uuid4(),
        turn_id=uuid4(),
        request_id=request_id,
        sequence=1,
        text="hi",
    )
    with pytest.raises(ChatEventViolation):
        matches_token(token, identity)


def test_token_wrong_session_after_turn_id_raises() -> None:
    session_id = uuid4()
    turn_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=uuid4(),
        request_id=uuid4(),
        turn_id=turn_id,
    )
    token = TokenEvent(
        type="token",
        session_id=uuid4(),
        turn_id=turn_id,
        request_id=uuid4(),
        sequence=1,
        text="hi",
    )
    with pytest.raises(ChatEventViolation):
        matches_token(token, identity)


def test_token_unrelated_request_id_ignored() -> None:
    session_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=uuid4(),
        request_id=uuid4(),
    )
    token = TokenEvent(
        type="token",
        session_id=session_id,
        turn_id=uuid4(),
        request_id=uuid4(),
        sequence=1,
        text="hi",
    )
    assert matches_token(token, identity) is False


def test_token_matching_captured_turn_rejects_wrong_request_id() -> None:
    session_id = uuid4()
    turn_id = uuid4()
    request_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=uuid4(),
        request_id=request_id,
        turn_id=turn_id,
    )
    token = TokenEvent(
        type="token",
        session_id=session_id,
        turn_id=turn_id,
        request_id=uuid4(),
        sequence=1,
        text="hi",
    )
    with pytest.raises(ChatEventViolation) as exc_info:
        matches_token(token, identity)
    assert (
        exc_info.value.expected_model
        == "TokenEvent matching correlated request_id"
    )


def test_token_unrelated_turn_id_ignored() -> None:
    session_id = uuid4()
    turn_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=uuid4(),
        request_id=uuid4(),
        turn_id=turn_id,
    )
    token = TokenEvent(
        type="token",
        session_id=session_id,
        turn_id=uuid4(),
        request_id=uuid4(),
        sequence=1,
        text="hi",
    )
    assert matches_token(token, identity) is False


def test_duplicate_progress_turn_id_raises_violation() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=client_message_id,
        request_id=uuid4(),
        turn_id=uuid4(),
    )
    progress = _progress_event(
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=uuid4(),
    )
    with pytest.raises(ChatEventViolation):
        identity_after_progress(progress, identity)


def test_repeated_progress_same_turn_id_is_harmless() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    turn_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=client_message_id,
        request_id=uuid4(),
        turn_id=turn_id,
    )
    progress = _progress_event(
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=turn_id,
    )
    updated = identity_after_progress(progress, identity)
    assert updated.turn_id == turn_id


def test_chat_events_module_has_no_api_client_import() -> None:
    tree = ast.parse(CHAT_EVENTS_PATH.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    assert "jung.client.api_client" not in imports
