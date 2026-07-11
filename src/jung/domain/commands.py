"""Typed command models for the target core."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from jung.domain.models import Profile


class UpdateProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int
    profile: Profile


class FinishIntake(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int
    intake_session_id: UUID


class SelectStyle(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int
    style_id: str
    plan_id: UUID
    focus: str
    themes: list[str]
    goals: list[str]
    current_progress: str
    planned_interventions: list[str]
    revision_recommendations: list[str]


class StartSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int
    session_id: UUID


class EndSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int
    session_id: UUID
    operation_id: UUID


class SendMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int
    session_id: UUID
    client_message_id: UUID
    content: str
    turn_id: UUID
    user_message_id: UUID
    request_id: UUID | None = None


class RetryOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int
    operation_id: UUID
