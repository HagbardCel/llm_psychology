"""Typed command models for the target core."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from jung.domain.models import Profile


class UpdateProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int
    profile: Profile


class SelectStyle(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int
    style_id: str


class StartSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int


class EndSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int
    session_id: UUID


class SendMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int
    session_id: UUID
    client_message_id: UUID
    content: str
    request_id: UUID | None = None


class RetryOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int
