"""Shared transcript types for phase processors."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from jung.domain.models import Message, MessageRole


class TranscriptTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: UUID
    sequence: int = Field(ge=1)
    role: Literal["user", "assistant"]
    content: str


def normalize_transcript_content(text: str) -> str:
    return " ".join(text.split())


def messages_to_transcript(messages: list[Message]) -> tuple[TranscriptTurn, ...]:
    turns: list[TranscriptTurn] = []
    for message in messages:
        if message.role is MessageRole.USER:
            role = "user"
        elif message.role is MessageRole.ASSISTANT:
            role = "assistant"
        else:
            continue
        turns.append(
            TranscriptTurn(
                message_id=message.id,
                sequence=message.sequence,
                role=role,
                content=message.content,
            )
        )
    return tuple(turns)
