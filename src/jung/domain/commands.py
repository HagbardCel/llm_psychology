"""Typed command models for the target core."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from jung.domain.models import Profile


class UpdateProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: Profile


class SelectStyle(BaseModel):
    model_config = ConfigDict(frozen=True)

    style_id: str


class EndSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: UUID


class SendMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: UUID
    client_message_id: UUID
    content: str
    request_id: UUID | None = None
