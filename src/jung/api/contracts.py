"""Wire DTOs and domain-to-wire mappers for /api/v1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal, Self, cast, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jung.domain.models import (
    AppSnapshot,
    ChatTurn,
    CommandName,
    Message,
    Operation,
    Plan,
    Profile,
    Session,
    UtcDateTime,
)
from jung.domain.results import ProfileView, SessionHistory, StyleOptions

# Internal mapper support — not a wire schema or OpenAPI export.
COMMAND_ORDER: tuple[CommandName, ...] = (
    CommandName.UPDATE_PROFILE,
    CommandName.SEND_MESSAGE,
    CommandName.SELECT_STYLE,
    CommandName.START_SESSION,
    CommandName.END_SESSION,
    CommandName.RETRY_OPERATION,
)

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
    "state_conflict",
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

_PUBLIC_ERROR_CODES: frozenset[str] = frozenset(get_args(ErrorCode))


def normalize_public_error_code(stored_code: str) -> ErrorCode:
    if stored_code in _PUBLIC_ERROR_CODES:
        return cast(ErrorCode, stored_code)
    return "operation_failed"

SessionKindWire = Literal["intake", "therapy"]
MessageRoleWire = Literal["user", "assistant", "system"]
OperationKindWire = Literal["assessment", "post_session"]
OperationStatusWire = Literal["pending", "running", "complete", "failed"]
ChatTurnStatusWire = Literal["pending", "complete", "failed"]
StageWire = Literal[
    "setup",
    "intake",
    "assessment",
    "style_selection",
    "ready",
    "therapy",
    "post_session",
]


@dataclass(frozen=True, slots=True)
class MappingContext:
    request_id: UUID


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

    expected_revision: int
    profile: ProfileWire


class SelectStyleRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_revision: int
    style_id: str


class StartSessionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_revision: int


class EndSessionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_revision: int


class RetryOperationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_revision: int


class SendMessageCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["send_message"]
    session_id: UUID
    client_message_id: UUID
    request_id: UUID
    expected_revision: int
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
    client_message_id: UUID | None = None


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
    current_snapshot: AppSnapshotResponse | None = None
    retryable: bool | None = None


class OperationSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    kind: OperationKindWire
    status: OperationStatusWire
    source_session_id: UUID | None = None
    error: ErrorEnvelope | None = None


class ChatTurnSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    session_id: UUID
    client_message_id: UUID
    status: ChatTurnStatusWire
    user_message_id: UUID
    assistant_message_id: UUID | None = None
    error: ErrorEnvelope | None = None


class AppSnapshotResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    revision: int
    stage: StageWire
    profile_complete: bool
    selected_style: str | None = None
    active_session: SessionSummaryResponse | None = None
    operation: OperationSummaryResponse | None = None
    active_chat_turn: ChatTurnSummaryResponse | None = None
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


class ErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: ErrorCode
    message: str
    request_id: UUID
    current_snapshot: AppSnapshotResponse | None = None
    retryable: bool | None = None


# --- WebSocket server events ---


class TokenEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["token"]
    session_id: UUID
    turn_id: UUID
    request_id: UUID
    sequence: int
    text: str


class MessageInProgressEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["message_in_progress"]
    session_id: UUID
    turn: ChatTurnSummaryResponse


class MessageCompletedEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["message_completed"]
    session_id: UUID
    turn: ChatTurnSummaryResponse
    message: MessageResponse


class SnapshotChangedEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["snapshot_changed"]
    snapshot: AppSnapshotResponse


class OperationChangedEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["operation_changed"]
    operation: OperationSummaryResponse
    snapshot: AppSnapshotResponse


class ErrorEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["error"]
    error: ErrorEnvelope
    request_id: UUID
    session_id: UUID | None = None
    turn_id: UUID | None = None
    client_message_id: UUID | None = None

    @model_validator(mode="after")
    def request_ids_match(self) -> Self:
        if self.request_id != self.error.request_id:
            raise ValueError("error.request_id must match request_id")
        return self


ServerEvent = Annotated[
    TokenEvent
    | MessageInProgressEvent
    | MessageCompletedEvent
    | SnapshotChangedEvent
    | OperationChangedEvent
    | ErrorEvent,
    Field(discriminator="type"),
]


# --- Mappers ---


def _ordered_commands(commands: frozenset[CommandName]) -> list[Command]:
    return [command.value for command in COMMAND_ORDER if command in commands]


def _profile_wire(profile: Profile) -> ProfileWire:
    return ProfileWire(
        name=profile.name,
        primary_language=profile.primary_language,
        date_of_birth=profile.date_of_birth,
        notes=profile.notes,
    )


def stored_error_envelope(
    code: str | None,
    message: str | None,
    retryable: bool,
    *,
    context: MappingContext,
) -> ErrorEnvelope | None:
    if code is None:
        return None
    return ErrorEnvelope(
        code=normalize_public_error_code(code),
        message=message or "Request failed",
        request_id=context.request_id,
        retryable=retryable,
        current_snapshot=None,
    )


def build_error_event(
    envelope: ErrorEnvelope,
    *,
    context: MappingContext,
    session_id: UUID | None = None,
    turn_id: UUID | None = None,
    client_message_id: UUID | None = None,
) -> ErrorEvent:
    if envelope.request_id != context.request_id:
        envelope = envelope.model_copy(update={"request_id": context.request_id})
    return ErrorEvent(
        type="error",
        error=envelope,
        request_id=context.request_id,
        session_id=session_id,
        turn_id=turn_id,
        client_message_id=client_message_id,
    )


def to_operation_summary(
    operation: Operation,
    *,
    context: MappingContext,
) -> OperationSummaryResponse:
    return OperationSummaryResponse(
        id=operation.id,
        kind=operation.kind.value,
        status=operation.status.value,
        source_session_id=operation.source_session_id,
        error=stored_error_envelope(
            operation.error_code,
            operation.error_message,
            operation.retryable,
            context=context,
        ),
    )


def to_chat_turn_summary(
    turn: ChatTurn,
    *,
    context: MappingContext,
) -> ChatTurnSummaryResponse:
    return ChatTurnSummaryResponse(
        id=turn.id,
        session_id=turn.session_id,
        client_message_id=turn.client_message_id,
        status=turn.status.value,
        user_message_id=turn.user_message_id,
        assistant_message_id=turn.assistant_message_id,
        error=stored_error_envelope(
            turn.error_code,
            turn.error_message,
            turn.retryable,
            context=context,
        ),
    )


def to_session_summary(session: Session) -> SessionSummaryResponse:
    return SessionSummaryResponse(
        id=session.id,
        kind=session.kind.value,
        started_at=session.started_at,
        ended_at=session.ended_at,
        plan_id=session.plan_id,
    )


def to_session_detail(session: Session) -> SessionDetailResponse:
    return SessionDetailResponse(
        id=session.id,
        kind=session.kind.value,
        started_at=session.started_at,
        ended_at=session.ended_at,
        plan_id=session.plan_id,
        summary=session.summary,
        briefing=session.briefing,
    )


def to_message_response(message: Message) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        session_id=message.session_id,
        sequence=message.sequence,
        role=message.role.value,
        content=message.content,
        created_at=message.created_at,
        client_message_id=message.client_message_id,
    )


def to_plan_summary(plan: Plan) -> PlanSummaryResponse:
    return PlanSummaryResponse(
        id=plan.id,
        version=plan.version,
        source_session_id=plan.source_session_id,
        supersedes_plan_id=plan.supersedes_plan_id,
        created_at=plan.created_at,
    )


def to_plan_detail(plan: Plan) -> PlanDetailResponse:
    return PlanDetailResponse(
        id=plan.id,
        version=plan.version,
        selected_style=plan.selected_style,
        focus=plan.focus,
        themes=list(plan.themes),
        goals=list(plan.goals),
        current_progress=plan.current_progress,
        planned_interventions=list(plan.planned_interventions),
        revision_recommendations=list(plan.revision_recommendations),
        session_briefing=plan.session_briefing,
        source_session_id=plan.source_session_id,
        supersedes_plan_id=plan.supersedes_plan_id,
        created_at=plan.created_at,
    )


def to_snapshot_response(
    snapshot: AppSnapshot,
    *,
    context: MappingContext,
) -> AppSnapshotResponse:
    return AppSnapshotResponse(
        revision=snapshot.revision,
        stage=snapshot.stage.value,
        profile_complete=snapshot.profile_complete,
        selected_style=snapshot.selected_style,
        active_session=(
            to_session_summary(snapshot.active_session)
            if snapshot.active_session is not None
            else None
        ),
        operation=(
            to_operation_summary(snapshot.current_operation, context=context)
            if snapshot.current_operation is not None
            else None
        ),
        active_chat_turn=(
            to_chat_turn_summary(snapshot.active_chat_turn, context=context)
            if snapshot.active_chat_turn is not None
            else None
        ),
        available_commands=_ordered_commands(snapshot.available_commands),
    )


def to_profile_response(
    view: ProfileView,
    *,
    context: MappingContext,
) -> ProfileResponse:
    return ProfileResponse(
        profile=_profile_wire(view.profile),
        current_plan=(
            to_plan_detail(view.current_plan) if view.current_plan is not None else None
        ),
        snapshot=to_snapshot_response(view.snapshot, context=context),
    )


def to_style_options_response(options: StyleOptions) -> StyleOptionsResponse:
    return StyleOptionsResponse(
        styles=[
            StyleSummaryResponse(
                id=style.id,
                name=style.name,
                description=style.description,
            )
            for style in options.styles
        ],
        recommendations=[
            StyleRecommendationSummaryResponse(
                style_id=rec.style_id,
                score=rec.score,
                rationale=rec.rationale,
                key_topics=list(rec.key_topics),
            )
            for rec in options.recommendations
        ],
    )


def to_session_history_response(history: SessionHistory) -> SessionHistoryResponse:
    return SessionHistoryResponse(
        session=to_session_detail(history.session),
        messages=[to_message_response(message) for message in history.messages],
        plans=[to_plan_summary(plan) for plan in history.plans],
    )


def to_operation_changed_event(
    operation: Operation,
    snapshot: AppSnapshot,
    *,
    context: MappingContext,
) -> OperationChangedEvent:
    operation_summary = to_operation_summary(operation, context=context)
    snapshot_response = to_snapshot_response(snapshot, context=context)
    return OperationChangedEvent(
        type="operation_changed",
        operation=operation_summary,
        snapshot=snapshot_response,
    )


ErrorEnvelope.model_rebuild()
AppSnapshotResponse.model_rebuild()
OperationSummaryResponse.model_rebuild()
ChatTurnSummaryResponse.model_rebuild()
ErrorResponse.model_rebuild()
ProfileResponse.model_rebuild()
OperationChangedEvent.model_rebuild()
