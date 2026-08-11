"""Domain/results → wire DTO mapping for /api/v1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast, get_args
from uuid import UUID

from jung.api.contracts import (
    AppSnapshotResponse,
    Command,
    ErrorCode,
    ErrorEnvelope,
    ErrorEvent,
    MessageResponse,
    OperationSummaryResponse,
    PlanDetailResponse,
    PlanSummaryResponse,
    ProfileResponse,
    ProfileWire,
    SessionDetailResponse,
    SessionHistoryResponse,
    SessionSummaryResponse,
    StartSessionResponse,
    StyleOptionsResponse,
    StyleRecommendationSummaryResponse,
    StyleSummaryResponse,
)
from jung.domain.models import (
    AppSnapshot,
    CommandName,
    Message,
    Operation,
    Plan,
    Profile,
    Session,
)
from jung.domain.results import (
    ProfileView,
    SessionHistory,
    StartedSession,
    StyleOptions,
)

COMMAND_ORDER: tuple[CommandName, ...] = (
    CommandName.UPDATE_PROFILE,
    CommandName.SEND_MESSAGE,
    CommandName.SELECT_STYLE,
    CommandName.START_SESSION,
    CommandName.END_SESSION,
    CommandName.RETRY_OPERATION,
)

_PUBLIC_ERROR_CODES: frozenset[str] = frozenset(get_args(ErrorCode))


@dataclass(frozen=True, slots=True)
class MappingContext:
    request_id: UUID


def normalize_public_error_code(stored_code: str) -> ErrorCode:
    if stored_code in _PUBLIC_ERROR_CODES:
        return cast(ErrorCode, stored_code)
    return "operation_failed"


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
    )


def build_error_event(
    envelope: ErrorEnvelope,
    *,
    context: MappingContext,
    session_id: UUID | None = None,
    client_message_id: UUID | None = None,
) -> ErrorEvent:
    if envelope.request_id != context.request_id:
        envelope = envelope.model_copy(update={"request_id": context.request_id})
    return ErrorEvent(
        type="error",
        error=envelope,
        request_id=context.request_id,
        session_id=session_id,
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


def to_start_session_response(
    started: StartedSession,
    *,
    context: MappingContext,
) -> StartSessionResponse:
    return StartSessionResponse(
        session=to_session_summary(started.session),
        snapshot=to_snapshot_response(started.snapshot, context=context),
    )
