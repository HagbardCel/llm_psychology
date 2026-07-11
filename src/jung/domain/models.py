"""Target single-user domain models."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Stage(StrEnum):
    SETUP = "setup"
    INTAKE = "intake"
    ASSESSMENT = "assessment"
    STYLE_SELECTION = "style_selection"
    READY = "ready"
    THERAPY = "therapy"
    POST_SESSION = "post_session"


class CommandName(StrEnum):
    UPDATE_PROFILE = "update_profile"
    SEND_MESSAGE = "send_message"
    FINISH_INTAKE = "finish_intake"
    SELECT_STYLE = "select_style"
    START_SESSION = "start_session"
    END_SESSION = "end_session"
    RETRY_OPERATION = "retry_operation"


class SessionKind(StrEnum):
    INTAKE = "intake"
    THERAPY = "therapy"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class OperationKind(StrEnum):
    ASSESSMENT = "assessment"
    POST_SESSION = "post_session"


class OperationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ChatTurnStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class Profile(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    primary_language: str
    date_of_birth: date | None = None
    notes: str | None = None


def is_profile_complete(profile: Profile) -> bool:
    """Return whether the profile satisfies completeness policy."""
    return bool(profile.name.strip() and profile.primary_language.strip())


class StoredProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: Profile
    derived_profile: dict[str, Any] | None = None
    current_plan_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class Session(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    kind: SessionKind
    plan_id: UUID | None = None
    started_at: datetime
    ended_at: datetime | None = None
    summary: str | None = None
    briefing: dict[str, Any] | None = None


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    session_id: UUID
    sequence: int
    role: MessageRole
    content: str
    client_message_id: UUID | None = None
    created_at: datetime

    @field_validator("sequence")
    @classmethod
    def sequence_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("sequence must be >= 1")
        return value


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    version: int
    selected_style: str
    focus: str
    themes: list[str]
    goals: list[str]
    current_progress: str
    planned_interventions: list[str]
    revision_recommendations: list[str]
    session_briefing: dict[str, Any] | None = None
    source_session_id: UUID | None = None
    supersedes_plan_id: UUID | None = None
    created_at: datetime

    @field_validator("focus", "current_progress")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be non-empty")
        return value


class Operation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    kind: OperationKind
    status: OperationStatus
    source_session_id: UUID
    attempt: int
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ChatTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    session_id: UUID
    client_message_id: UUID
    status: ChatTurnStatus
    user_message_id: UUID
    assistant_message_id: UUID | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class AppState(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: Stage
    revision: int
    created_at: datetime
    updated_at: datetime

    @field_validator("revision")
    @classmethod
    def revision_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("revision must be >= 0")
        return value


class WorkflowFacts(BaseModel):
    """Compact facts for pure workflow policy."""

    model_config = ConfigDict(frozen=True)

    stage: Stage
    profile_complete: bool
    has_active_session: bool
    operation_kind: OperationKind | None = None
    operation_status: OperationStatus | None = None
    chat_turn_status: ChatTurnStatus | None = None


class AppSnapshot(BaseModel):
    """Derived read model; available_commands come from workflow policy."""

    model_config = ConfigDict(frozen=True)

    revision: int
    stage: Stage
    profile_complete: bool
    selected_style: str | None = None
    active_session: Session | None = None
    current_operation: Operation | None = None
    active_chat_turn: ChatTurn | None = None
    available_commands: frozenset[CommandName] = Field(default_factory=frozenset)
