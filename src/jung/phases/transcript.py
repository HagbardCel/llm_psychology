"""Shared transcript types for phase processors."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TranscriptTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: UUID
    sequence: int = Field(ge=1)
    role: Literal["user", "assistant"]
    content: str
