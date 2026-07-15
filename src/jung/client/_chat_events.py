"""Package-private WebSocket event correlation helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID

from jung.api.contracts import (
    ErrorEvent,
    MessageCompletedEvent,
    MessageInProgressEvent,
    OperationChangedEvent,
    ServerEvent,
    SnapshotChangedEvent,
    TokenEvent,
)


@dataclass(frozen=True)
class ChatEventViolation(ValueError):
    expected_model: str


class ErrorCorrelation(StrEnum):
    UNRELATED = "unrelated"
    COMMAND_REJECTED = "command_rejected"
    DURABLE_FAILURE = "durable_failure"


@dataclass(frozen=True)
class ChatEventIdentity:
    session_id: UUID
    client_message_id: UUID
    request_id: UUID
    turn_id: UUID | None = None


class ChatOutcomeKind(StrEnum):
    PROGRESS = "progress"
    COMPLETION = "completion"
    COMMAND_ERROR = "command_error"
    DURABLE_ERROR = "durable_error"


@dataclass(frozen=True)
class ChatEventOutcome:
    kind: ChatOutcomeKind
    identity: ChatEventIdentity
    event: MessageInProgressEvent | MessageCompletedEvent | ErrorEvent


def matches_progress(
    event: MessageInProgressEvent,
    identity: ChatEventIdentity,
) -> bool:
    if event.session_id != event.turn.session_id:
        raise ChatEventViolation(
            expected_model="internally consistent MessageInProgressEvent",
        )
    return (
        event.turn.session_id == identity.session_id
        and event.turn.client_message_id == identity.client_message_id
    )


def identity_after_progress(
    event: MessageInProgressEvent,
    identity: ChatEventIdentity,
) -> ChatEventIdentity:
    if identity.turn_id is not None and identity.turn_id != event.turn.id:
        raise ChatEventViolation(
            expected_model="consistent turn_id across progress events",
        )
    return replace(identity, turn_id=event.turn.id)


def matches_token(event: TokenEvent, identity: ChatEventIdentity) -> bool:
    if identity.turn_id is None:
        return event.request_id == identity.request_id
    return (
        event.session_id == identity.session_id
        and event.turn_id == identity.turn_id
    )


def matches_completion(
    event: MessageCompletedEvent,
    identity: ChatEventIdentity,
) -> bool:
    if (
        event.session_id != event.turn.session_id
        or event.session_id != event.message.session_id
        or event.turn.client_message_id != event.message.client_message_id
    ):
        raise ChatEventViolation(
            expected_model="internally consistent MessageCompletedEvent",
        )
    if identity.turn_id is not None and event.turn.id != identity.turn_id:
        raise ChatEventViolation(
            expected_model="MessageCompletedEvent matching captured turn_id",
        )
    return (
        event.session_id == identity.session_id
        and event.turn.client_message_id == identity.client_message_id
    )


def classify_error(
    event: ErrorEvent,
    identity: ChatEventIdentity,
) -> ErrorCorrelation:
    if event.turn_id is not None:
        if event.session_id is None or event.client_message_id is None:
            raise ChatEventViolation(expected_model="durable ErrorEvent")
        if (
            event.session_id != identity.session_id
            or event.client_message_id != identity.client_message_id
        ):
            return ErrorCorrelation.UNRELATED
        if identity.turn_id is not None and event.turn_id != identity.turn_id:
            raise ChatEventViolation(
                expected_model="durable ErrorEvent matching captured turn_id",
            )
        return ErrorCorrelation.DURABLE_FAILURE

    if event.request_id != identity.request_id:
        return ErrorCorrelation.UNRELATED
    if (
        event.session_id != identity.session_id
        or event.client_message_id != identity.client_message_id
    ):
        raise ChatEventViolation(expected_model="correlated command ErrorEvent")
    return ErrorCorrelation.COMMAND_REJECTED


def is_ignorable_event(event: ServerEvent) -> bool:
    return isinstance(
        event,
        (SnapshotChangedEvent, OperationChangedEvent),
    )


def matches_decisive_event(
    event: ServerEvent,
    *,
    identity: ChatEventIdentity,
) -> tuple[bool, ErrorEvent | None]:
    if isinstance(event, MessageInProgressEvent):
        return matches_progress(event, identity), None
    if isinstance(event, MessageCompletedEvent):
        return matches_completion(event, identity), None
    if isinstance(event, TokenEvent):
        return False, None
    if is_ignorable_event(event):
        return False, None
    if not isinstance(event, ErrorEvent):
        return False, None

    correlation = classify_error(event, identity)
    if correlation is ErrorCorrelation.UNRELATED:
        return False, None
    if correlation is ErrorCorrelation.COMMAND_REJECTED:
        return True, event
    return True, event
