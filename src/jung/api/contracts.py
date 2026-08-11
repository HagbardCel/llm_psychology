"""Wire DTOs for /api/v1 (client/server shared contract)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UtcDateTime = Annotated[AwareDatetime, AfterValidator(_as_utc)]

Command = Literal[
    "update_profile",
    "send_message",
    "select_style",
    "start_session",
    "end_session",
    "retry_operation",
]

ErrorCode = Literal[
    "invalid_command",
    "busy",
    "not_found",
    "validation_error",
    "llm_unavailable",
    "llm_timeout",
    "invalid_llm_output",
    "operation_failed",
    "internal_error",
    "not_ready",
]

SessionKindWire = Literal["intake", "therapy"]
MessageRoleWire = Literal["user", "assistant"]
OperationKindWire = Literal["assessment", "post_session"]
OperationStatusWire = Literal["pending", "running", "complete", "failed"]
StageWire = Literal[
    "setup",
    "intake",
    "assessment",
    "style_selection",
    "ready",
    "therapy",
    "post_session",
]


# --- Shared wire shapes ---


class ProfileWire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    primary_language: str
    date_of_birth: date | None = None
    notes: str | None = None


# --- Requests (extra=forbid) ---


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: ProfileWire


class SelectStyleRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    style_id: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID
    client_message_id: UUID
    content: str


class StyleSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    description: str


class StyleRecommendationSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    style_id: str
    score: float = Field(ge=0.0, le=1.0)
    rationale: str
    key_topics: list[str]


class StyleOptionsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    styles: list[StyleSummaryResponse]
    recommendations: list[StyleRecommendationSummaryResponse]


class SessionSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    kind: SessionKindWire
    started_at: UtcDateTime
    ended_at: UtcDateTime | None = None
    plan_id: UUID | None = None


class SessionDetailResponse(SessionSummaryResponse):
    model_config = ConfigDict(frozen=True)

    summary: str | None = None
    briefing: dict[str, Any] | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    session_id: UUID
    sequence: int
    role: MessageRoleWire
    content: str
    created_at: UtcDateTime
    client_message_id: UUID


class PlanSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    version: int
    source_session_id: UUID | None = None
    supersedes_plan_id: UUID | None = None
    created_at: UtcDateTime


class PlanDetailResponse(BaseModel):
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
    created_at: UtcDateTime


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: ErrorCode
    message: str
    request_id: UUID
    retryable: bool | None = None


class OperationSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    kind: OperationKindWire
    status: OperationStatusWire
    source_session_id: UUID | None = None
    error: ErrorEnvelope | None = None


class AppSnapshotResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: StageWire
    profile_complete: bool
    selected_style: str | None = None
    active_session: SessionSummaryResponse | None = None
    operation: OperationSummaryResponse | None = None
    available_commands: list[Command]


class ProfileResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: ProfileWire
    current_plan: PlanDetailResponse | None = None
    snapshot: AppSnapshotResponse


class SessionHistoryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    session: SessionDetailResponse
    messages: list[MessageResponse]
    plans: list[PlanSummaryResponse]


class StartSessionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    session: SessionSummaryResponse
    snapshot: AppSnapshotResponse


class SessionListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    sessions: list[SessionSummaryResponse]


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["healthy"]


class ErrorResponse(ErrorEnvelope):
    pass


# --- Chat server events ---


class TokenEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["token"]
    text: str
    request_id: UUID
    session_id: UUID
    client_message_id: UUID


class MessageCompletedEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["message_completed"]
    request_id: UUID
    session_id: UUID
    client_message_id: UUID
    user_message: MessageResponse
    assistant_message: MessageResponse

    @model_validator(mode="after")
    def messages_match_event_identity(self) -> Self:
        if self.user_message.role != "user":
            raise ValueError("user_message.role must be user")
        if self.assistant_message.role != "assistant":
            raise ValueError("assistant_message.role must be assistant")
        if self.user_message.session_id != self.session_id:
            raise ValueError("user_message.session_id must match session_id")
        if self.assistant_message.session_id != self.session_id:
            raise ValueError("assistant_message.session_id must match session_id")
        if self.user_message.client_message_id != self.client_message_id:
            raise ValueError(
                "user_message.client_message_id must match client_message_id"
            )
        if self.assistant_message.client_message_id != self.client_message_id:
            raise ValueError(
                "assistant_message.client_message_id must match client_message_id"
            )
        if self.assistant_message.sequence != self.user_message.sequence + 1:
            raise ValueError(
                "assistant_message.sequence must equal user_message.sequence + 1"
            )
        return self


class MessageFailedEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["message_failed"]
    request_id: UUID
    session_id: UUID
    client_message_id: UUID
    error: ErrorEnvelope

    @model_validator(mode="after")
    def request_ids_match(self) -> Self:
        if self.request_id != self.error.request_id:
            raise ValueError("error.request_id must match request_id")
        return self


class ErrorEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["error"]
    error: ErrorEnvelope
    request_id: UUID
    session_id: UUID
    client_message_id: UUID

    @model_validator(mode="after")
    def request_ids_match(self) -> Self:
        if self.request_id != self.error.request_id:
            raise ValueError("error.request_id must match request_id")
        return self


ServerEvent = Annotated[
    TokenEvent | MessageCompletedEvent | MessageFailedEvent | ErrorEvent,
    Field(discriminator="type"),
]
