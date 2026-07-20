"""Package-private durable chat message inspection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from jung.api.contracts import MessageResponse, SessionHistoryResponse


@dataclass(frozen=True, slots=True)
class DurableChatMessages:
    user: MessageResponse | None
    assistant: MessageResponse | None


class DurableChatViolation(ValueError):
    def __init__(self, expected_model: str) -> None:
        super().__init__(expected_model)
        self.expected_model = expected_model


def inspect_durable_chat_messages(
    history: SessionHistoryResponse,
    *,
    expected_session_id: UUID,
    client_message_id: UUID,
) -> DurableChatMessages:
    if history.session.id != expected_session_id:
        raise DurableChatViolation("SessionHistoryResponse")

    users = [
        message
        for message in history.messages
        if message.client_message_id == client_message_id and message.role == "user"
    ]
    assistants = [
        message
        for message in history.messages
        if message.client_message_id == client_message_id
        and message.role == "assistant"
    ]

    if any(
        message.session_id != expected_session_id for message in (*users, *assistants)
    ):
        raise DurableChatViolation("SessionHistoryResponse")

    if len(users) > 1 or len(assistants) > 1 or (assistants and not users):
        raise DurableChatViolation("SessionHistoryResponse")

    return DurableChatMessages(
        user=users[0] if users else None,
        assistant=assistants[0] if assistants else None,
    )
