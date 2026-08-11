"""HTTP route handlers for /api/v1."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from starlette.responses import StreamingResponse

from jung.api.contracts import (
    AppSnapshotResponse,
    ChatRequest,
    HealthResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    SelectStyleRequest,
    SessionHistoryResponse,
    SessionListResponse,
    StartSessionResponse,
    StyleOptionsResponse,
)
from jung.api.deps import build_error_response, get_application
from jung.api.errors import (
    COMMON_ERROR_RESPONSES,
    CONFLICT_RESPONSES,
    NOT_FOUND_RESPONSES,
    not_ready_error_response,
    to_error_envelope,
)
from jung.api.mapping import (
    MappingContext,
    build_error_event,
    to_profile_response,
    to_server_event,
    to_session_history_response,
    to_session_summary,
    to_snapshot_response,
    to_start_session_response,
    to_style_options_response,
)
from jung.application import TherapyApplication
from jung.diagnostics import diagnostic_context
from jung.domain.commands import (
    EndSession,
    SelectStyle,
    SendMessage,
    UpdateProfile,
)
from jung.domain.errors import DomainError
from jung.domain.models import Profile

logger = logging.getLogger(__name__)

RequestIdHeader = Annotated[
    str | None,
    Header(alias="X-Request-ID"),
]


async def document_request_id_header(
    _request_id: RequestIdHeader = None,
) -> None:
    pass


router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(document_request_id_header)],
)


def _context(request: Request) -> MappingContext:
    return MappingContext(request_id=request.state.request_id)


def _log_safe_exception(
    message: str,
    *,
    request_id: UUID,
    exc: Exception,
) -> None:
    logger.error(
        message,
        extra={
            "request_id": str(request_id),
            "exception_type": type(exc).__name__,
        },
    )


async def _stream_chat(
    application: TherapyApplication,
    command: SendMessage,
    *,
    context: MappingContext,
    session_id: UUID,
    client_message_id: UUID,
) -> AsyncIterator[str]:
    with diagnostic_context(
        request_id=str(context.request_id),
        session_id=str(session_id),
        client_message_id=str(client_message_id),
    ):
        try:
            async for item in application.stream_message(command):
                event = to_server_event(item, context=context)
                yield event.model_dump_json() + "\n"
        except DomainError as exc:
            envelope = to_error_envelope(exc, request_id=context.request_id)
            event = build_error_event(
                envelope,
                context=context,
                session_id=session_id,
                client_message_id=client_message_id,
            )
            yield event.model_dump_json() + "\n"
        except Exception as exc:
            _log_safe_exception(
                "chat stream failed",
                request_id=context.request_id,
                exc=exc,
            )
            envelope = to_error_envelope(exc, request_id=context.request_id)
            event = build_error_event(
                envelope,
                context=context,
                session_id=session_id,
                client_message_id=client_message_id,
            )
            yield event.model_dump_json() + "\n"


@router.get(
    "/state",
    response_model=AppSnapshotResponse,
    response_model_exclude_none=True,
    responses=COMMON_ERROR_RESPONSES,
)
async def get_state(
    request: Request,
    application: TherapyApplication = Depends(get_application),
) -> AppSnapshotResponse:
    context = _context(request)
    snapshot = await application.get_snapshot()
    return to_snapshot_response(snapshot, context=context)


@router.get(
    "/profile",
    response_model=ProfileResponse,
    responses=NOT_FOUND_RESPONSES,
)
async def get_profile(
    request: Request,
    application: TherapyApplication = Depends(get_application),
) -> ProfileResponse:
    context = _context(request)
    view = await application.get_profile()
    return to_profile_response(view, context=context)


@router.put(
    "/profile",
    response_model=AppSnapshotResponse,
    response_model_exclude_none=True,
    responses=CONFLICT_RESPONSES,
)
async def update_profile(
    body: ProfileUpdateRequest,
    request: Request,
    application: TherapyApplication = Depends(get_application),
) -> AppSnapshotResponse:
    context = _context(request)
    profile = Profile(
        name=body.profile.name,
        primary_language=body.profile.primary_language,
        date_of_birth=body.profile.date_of_birth,
        notes=body.profile.notes,
    )
    snapshot = await application.update_profile(UpdateProfile(profile=profile))
    return to_snapshot_response(snapshot, context=context)


@router.get(
    "/styles",
    response_model=StyleOptionsResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def get_styles(
    application: TherapyApplication = Depends(get_application),
) -> StyleOptionsResponse:
    options = await application.get_style_options()
    return to_style_options_response(options)


@router.put(
    "/style",
    response_model=AppSnapshotResponse,
    response_model_exclude_none=True,
    responses=CONFLICT_RESPONSES,
)
async def select_style(
    body: SelectStyleRequest,
    request: Request,
    application: TherapyApplication = Depends(get_application),
) -> AppSnapshotResponse:
    context = _context(request)
    snapshot = await application.select_style(SelectStyle(style_id=body.style_id))
    return to_snapshot_response(snapshot, context=context)


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def list_sessions(
    application: TherapyApplication = Depends(get_application),
) -> SessionListResponse:
    sessions = await application.list_sessions()
    return SessionListResponse(
        sessions=[to_session_summary(session) for session in sessions]
    )


@router.get(
    "/sessions/{session_id}",
    response_model=SessionHistoryResponse,
    responses=NOT_FOUND_RESPONSES,
)
async def get_session(
    session_id: UUID,
    application: TherapyApplication = Depends(get_application),
) -> SessionHistoryResponse:
    history = await application.get_session_history(session_id)
    return to_session_history_response(history)


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=StartSessionResponse,
    responses=CONFLICT_RESPONSES,
)
async def start_session(
    request: Request,
    application: TherapyApplication = Depends(get_application),
) -> StartSessionResponse:
    context = _context(request)
    started = await application.start_session()
    return to_start_session_response(started, context=context)


@router.post(
    "/sessions/{session_id}/end",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AppSnapshotResponse,
    response_model_exclude_none=True,
    responses={**NOT_FOUND_RESPONSES, **CONFLICT_RESPONSES},
)
async def end_session(
    session_id: UUID,
    request: Request,
    application: TherapyApplication = Depends(get_application),
) -> AppSnapshotResponse:
    context = _context(request)
    snapshot = await application.end_session(EndSession(session_id=session_id))
    return to_snapshot_response(snapshot, context=context)


@router.post(
    "/operations/current/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AppSnapshotResponse,
    response_model_exclude_none=True,
    responses=CONFLICT_RESPONSES,
)
async def retry_operation(
    request: Request,
    application: TherapyApplication = Depends(get_application),
) -> AppSnapshotResponse:
    context = _context(request)
    snapshot = await application.retry_operation()
    return to_snapshot_response(snapshot, context=context)


@router.post(
    "/chat",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "NDJSON chat event stream",
            "content": {
                "application/x-ndjson": {
                    "schema": {"type": "string"},
                }
            },
        },
        **COMMON_ERROR_RESPONSES,
    },
)
async def chat(
    body: ChatRequest,
    request: Request,
    application: TherapyApplication = Depends(get_application),
) -> StreamingResponse:
    context = _context(request)
    command = SendMessage(
        session_id=body.session_id,
        client_message_id=body.client_message_id,
        content=body.content,
        request_id=context.request_id,
    )
    return StreamingResponse(
        _stream_chat(
            application,
            command,
            context=context,
            session_id=body.session_id,
            client_message_id=body.client_message_id,
        ),
        media_type="application/x-ndjson",
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def health(request: Request):
    state = request.app.state.api
    if state.application is None:
        body = not_ready_error_response(request_id=request.state.request_id)
        return build_error_response(status=503, body=body)
    return HealthResponse(status="healthy")
