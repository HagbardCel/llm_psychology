"""Unit tests for jung.client._chat_events correlation helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from jung.api.contracts import (
    AppSnapshotResponse,
    ChatTurnSummaryResponse,
    ErrorEnvelope,
    ErrorEvent,
    MessageCompletedEvent,
    MessageInProgressEvent,
    MessageResponse,
    OperationChangedEvent,
    OperationSummaryResponse,
    SnapshotChangedEvent,
    TokenEvent,
)
from jung.client._chat_events import (
    ChatEventIdentity,
    ChatEventViolation,
    ErrorCorrelation,
    classify_error,
    identity_after_progress,
    matches_completion,
    matches_decisive_event,
    matches_progress,
    matches_token,
)


def _identity(
    *,
    session_id: UUID | None = None,
    client_message_id: UUID | None = None,
    request_id: UUID | None = None,
    turn_id: UUID | None = None,
) -> ChatEventIdentity:
    return ChatEventIdentity(
        session_id=session_id or uuid4(),
        client_message_id=client_message_id or uuid4(),
        request_id=request_id or uuid4(),
        turn_id=turn_id,
    )


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
    event_session_id: UUID | None = None,
) -> MessageInProgressEvent:
    turn_id = turn_id or uuid4()
    return MessageInProgressEvent(
        type="message_in_progress",
        session_id=event_session_id if event_session_id is not None else session_id,
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
    turn_id: UUID | None = None,
    event_session_id: UUID | None = None,
    message_session_id: UUID | None = None,
    message_client_message_id: UUID | None = None,
) -> MessageCompletedEvent:
    turn_id = turn_id or uuid4()
    turn = _turn(
        session_id=session_id,
        client_message_id=client_message_id,
        status="complete",
        turn_id=turn_id,
    )
    return MessageCompletedEvent(
        type="message_completed",
        session_id=event_session_id if event_session_id is not None else session_id,
        turn=turn,
        message=MessageResponse(
            id=uuid4(),
            session_id=(
                message_session_id if message_session_id is not None else session_id
            ),
            sequence=2,
            role="assistant",
            content="reply",
            created_at=datetime.now(UTC),
            client_message_id=(
                message_client_message_id
                if message_client_message_id is not None
                else client_message_id
            ),
        ),
    )


def _error_event(
    *,
    request_id: UUID,
    session_id: UUID | None = None,
    client_message_id: UUID | None = None,
    turn_id: UUID | None = None,
    code: str = "llm_timeout",
) -> ErrorEvent:
    return ErrorEvent(
        type="error",
        request_id=request_id,
        error=ErrorEnvelope(
            code=code,  # type: ignore[arg-type]
            message="x",
            request_id=request_id,
            retryable=True,
        ),
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=turn_id,
    )


# --- identity_after_progress / matches_progress ---


def test_identity_after_progress_establishes_turn_id() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    identity = _identity(session_id=session_id, client_message_id=client_message_id)
    progress = _progress_event(
        session_id=session_id,
        client_message_id=client_message_id,
    )
    updated = identity_after_progress(progress, identity)
    assert updated.turn_id == progress.turn.id


def test_duplicate_progress_turn_id_raises_violation() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    identity = _identity(
        session_id=session_id,
        client_message_id=client_message_id,
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
    identity = _identity(
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=turn_id,
    )
    progress = _progress_event(
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=turn_id,
    )
    updated = identity_after_progress(progress, identity)
    assert updated.turn_id == turn_id


def test_matches_progress_requires_internal_consistency() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    identity = _identity(session_id=session_id, client_message_id=client_message_id)
    exact = _progress_event(session_id=session_id, client_message_id=client_message_id)
    same_session_other = _progress_event(
        session_id=session_id, client_message_id=uuid4()
    )
    other_session = _progress_event(session_id=uuid4(), client_message_id=uuid4())
    inconsistent = _progress_event(
        session_id=uuid4(),
        client_message_id=uuid4(),
        event_session_id=session_id,
    )

    assert matches_progress(exact, identity) is True
    assert matches_progress(same_session_other, identity) is False
    assert matches_progress(other_session, identity) is False
    with pytest.raises(ChatEventViolation):
        matches_progress(inconsistent, identity)


# --- matches_completion ---


def test_completion_rejects_wrong_turn_id() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    identity = _identity(
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=uuid4(),
    )
    wrong_turn = _completion_event(
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=uuid4(),
    )
    with pytest.raises(ChatEventViolation):
        matches_completion(wrong_turn, identity)


def test_matches_completion_requires_internal_consistency() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    identity = _identity(session_id=session_id, client_message_id=client_message_id)
    exact = _completion_event(
        session_id=session_id, client_message_id=client_message_id
    )
    same_session_other = _completion_event(
        session_id=session_id, client_message_id=uuid4()
    )
    other_session = _completion_event(session_id=uuid4(), client_message_id=uuid4())
    wrong_turn_session = _completion_event(
        session_id=session_id,
        client_message_id=client_message_id,
        event_session_id=uuid4(),
    )
    wrong_message_session = _completion_event(
        session_id=session_id,
        client_message_id=client_message_id,
        message_session_id=uuid4(),
    )
    wrong_client_message = _completion_event(
        session_id=session_id,
        client_message_id=client_message_id,
        message_client_message_id=uuid4(),
    )

    assert matches_completion(exact, identity) is True
    assert matches_completion(same_session_other, identity) is False
    assert matches_completion(other_session, identity) is False
    with pytest.raises(ChatEventViolation):
        matches_completion(wrong_turn_session, identity)
    with pytest.raises(ChatEventViolation):
        matches_completion(wrong_message_session, identity)
    with pytest.raises(ChatEventViolation):
        matches_completion(wrong_client_message, identity)


# --- classify_error ---


def test_classify_error_durable_before_turn_id_matches_session_client() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    identity = _identity(session_id=session_id, client_message_id=client_message_id)
    event = _error_event(
        request_id=uuid4(),
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=uuid4(),
        code="llm_unavailable",
    )
    assert classify_error(event, identity) is ErrorCorrelation.DURABLE_FAILURE


def test_classify_error_durable_requires_session_and_client_ids() -> None:
    identity = _identity()
    with pytest.raises(ChatEventViolation):
        classify_error(
            _error_event(request_id=uuid4(), turn_id=uuid4()),
            identity,
        )


@pytest.mark.parametrize(
    ("session_id", "client_message_id"),
    (
        (None, None),
        (None, "retained"),
        ("retained", None),
        ("other", "retained"),
        ("retained", "other"),
    ),
)
def test_classify_error_command_requires_exact_identity(
    session_id: str | None,
    client_message_id: str | None,
) -> None:
    identity = _identity()
    event = _error_event(
        request_id=identity.request_id,
        session_id=(
            identity.session_id
            if session_id == "retained"
            else uuid4()
            if session_id == "other"
            else None
        ),
        client_message_id=(
            identity.client_message_id
            if client_message_id == "retained"
            else uuid4()
            if client_message_id == "other"
            else None
        ),
        code="state_conflict",
    )
    with pytest.raises(ChatEventViolation):
        classify_error(event, identity)


def test_classify_error_command_exact_match_and_unrelated_durable() -> None:
    identity = _identity()
    command_error = _error_event(
        request_id=identity.request_id,
        session_id=identity.session_id,
        client_message_id=identity.client_message_id,
        code="state_conflict",
    )
    other_durable = _error_event(
        request_id=uuid4(),
        session_id=uuid4(),
        client_message_id=uuid4(),
        turn_id=uuid4(),
    )
    assert classify_error(command_error, identity) is ErrorCorrelation.COMMAND_REJECTED
    assert classify_error(other_durable, identity) is ErrorCorrelation.UNRELATED


@pytest.mark.parametrize("matching_identity", (True, False))
def test_classify_error_different_request_id_without_turn_is_unrelated(
    matching_identity: bool,
) -> None:
    identity = _identity()
    event = _error_event(
        request_id=uuid4(),
        session_id=identity.session_id if matching_identity else uuid4(),
        client_message_id=(
            identity.client_message_id if matching_identity else uuid4()
        ),
        code="state_conflict",
    )
    assert classify_error(event, identity) is ErrorCorrelation.UNRELATED


def test_classify_error_durable_respects_captured_turn_id() -> None:
    turn_id = uuid4()
    identity = _identity(turn_id=turn_id)

    matching = _error_event(
        request_id=uuid4(),
        session_id=identity.session_id,
        client_message_id=identity.client_message_id,
        turn_id=turn_id,
    )
    assert classify_error(matching, identity) is ErrorCorrelation.DURABLE_FAILURE

    mismatched = matching.model_copy(update={"turn_id": uuid4()})
    with pytest.raises(ChatEventViolation) as exc_info:
        classify_error(mismatched, identity)

    assert exc_info.value.expected_model == (
        "durable ErrorEvent matching captured turn_id"
    )


# --- matches_token ---


def test_token_matches_request_id_before_turn_id() -> None:
    session_id = uuid4()
    request_id = uuid4()
    identity = _identity(session_id=session_id, request_id=request_id)
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
    request_id = uuid4()
    identity = _identity(request_id=request_id)
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
    turn_id = uuid4()
    identity = _identity(turn_id=turn_id)
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
    identity = _identity(session_id=session_id)
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
    identity = _identity(session_id=session_id, request_id=request_id, turn_id=turn_id)
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
    assert exc_info.value.expected_model == "TokenEvent matching correlated request_id"


def test_token_unrelated_turn_id_ignored() -> None:
    session_id = uuid4()
    turn_id = uuid4()
    identity = _identity(session_id=session_id, turn_id=turn_id)
    token = TokenEvent(
        type="token",
        session_id=session_id,
        turn_id=uuid4(),
        request_id=uuid4(),
        sequence=1,
        text="hi",
    )
    assert matches_token(token, identity) is False


# --- matches_decisive_event dispatch only ---


def test_matches_decisive_event_dispatches_progress_and_completion() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    identity = _identity(session_id=session_id, client_message_id=client_message_id)
    progress = _progress_event(
        session_id=session_id, client_message_id=client_message_id
    )
    completion = _completion_event(
        session_id=session_id, client_message_id=client_message_id
    )
    assert matches_decisive_event(progress, identity=identity) == (True, None)
    assert matches_decisive_event(completion, identity=identity) == (True, None)


def test_matches_decisive_event_ignores_token_and_snapshot_operation() -> None:
    identity = _identity()
    token = TokenEvent(
        type="token",
        session_id=identity.session_id,
        turn_id=uuid4(),
        request_id=identity.request_id,
        sequence=1,
        text="hi",
    )
    snapshot = SnapshotChangedEvent(
        type="snapshot_changed",
        snapshot=AppSnapshotResponse(
            revision=1,
            stage="intake",
            profile_complete=True,
            available_commands=[],
        ),
    )
    operation = OperationChangedEvent(
        type="operation_changed",
        operation=OperationSummaryResponse(
            id=uuid4(),
            kind="assessment",
            status="pending",
        ),
        snapshot=AppSnapshotResponse(
            revision=1,
            stage="intake",
            profile_complete=True,
            available_commands=[],
        ),
    )
    assert matches_decisive_event(token, identity=identity) == (False, None)
    assert matches_decisive_event(snapshot, identity=identity) == (False, None)
    assert matches_decisive_event(operation, identity=identity) == (False, None)


def test_matches_decisive_event_dispatches_correlated_and_unrelated_errors() -> None:
    identity = _identity()
    command_error = _error_event(
        request_id=identity.request_id,
        session_id=identity.session_id,
        client_message_id=identity.client_message_id,
        code="state_conflict",
    )
    durable = _error_event(
        request_id=uuid4(),
        session_id=identity.session_id,
        client_message_id=identity.client_message_id,
        turn_id=uuid4(),
    )
    unrelated = _error_event(
        request_id=uuid4(),
        session_id=uuid4(),
        client_message_id=uuid4(),
        turn_id=uuid4(),
    )
    assert matches_decisive_event(command_error, identity=identity) == (
        True,
        command_error,
    )
    assert matches_decisive_event(durable, identity=identity) == (True, durable)
    assert matches_decisive_event(unrelated, identity=identity) == (False, None)
