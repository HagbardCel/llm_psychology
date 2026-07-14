"""HTTP route handlers for /api/v1."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from jung.api.contracts import (
    COMMON_ERROR_RESPONSES,
    CONFLICT_RESPONSES,
    NOT_FOUND_RESPONSES,
    EndSessionRequest,
    HealthResponse,
    MappingContext,
    ProfileResponse,
    ProfileUpdateRequest,
    RetryOperationRequest,
    SelectStyleRequest,
    SessionHistoryResponse,
    SessionListResponse,
    StartSessionRequest,
    StartSessionResponse,
    StyleOptionsResponse,
    to_profile_response,
    to_session_history_response,
    to_snapshot_response,
    to_start_session_response,
    to_style_options_response,
)
from jung.api.deps import ApiRuntime, build_error_response, get_runtime
from jung.api.errors import not_ready_error_response
from jung.domain.commands import (
    EndSession,
    RetryOperation,
    SelectStyle,
    StartSession,
    UpdateProfile,
)
from jung.domain.errors import InvalidCommand
from jung.domain.models import OperationStatus, Profile

router = APIRouter(prefix="/api/v1")


def _context(request: Request) -> MappingContext:
    return MappingContext(request_id=request.state.request_id)


@router.get(
    "/state",
    response_model_exclude_none=True,
    responses=COMMON_ERROR_RESPONSES,
)
async def get_state(
    request: Request,
    runtime: ApiRuntime = Depends(get_runtime),
):
    context = _context(request)
    snapshot = await runtime.application.get_snapshot()
    return to_snapshot_response(snapshot, context=context)


@router.get(
    "/profile",
    response_model=ProfileResponse,
    responses=NOT_FOUND_RESPONSES,
)
async def get_profile(
    request: Request,
    runtime: ApiRuntime = Depends(get_runtime),
) -> ProfileResponse:
    context = _context(request)
    view = await runtime.application.get_profile()
    return to_profile_response(view, context=context)


@router.put(
    "/profile",
    response_model_exclude_none=True,
    responses=CONFLICT_RESPONSES,
)
async def update_profile(
    body: ProfileUpdateRequest,
    request: Request,
    runtime: ApiRuntime = Depends(get_runtime),
):
    context = _context(request)
    profile = Profile(
        name=body.profile.name,
        primary_language=body.profile.primary_language,
        date_of_birth=body.profile.date_of_birth,
        notes=body.profile.notes,
    )
    snapshot = await runtime.application.update_profile(
        UpdateProfile(expected_revision=body.expected_revision, profile=profile)
    )
    return to_snapshot_response(snapshot, context=context)


@router.get(
    "/styles",
    response_model=StyleOptionsResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def get_styles(
    runtime: ApiRuntime = Depends(get_runtime),
) -> StyleOptionsResponse:
    options = await runtime.application.get_style_options()
    return to_style_options_response(options)


@router.put(
    "/style",
    response_model_exclude_none=True,
    responses=CONFLICT_RESPONSES,
)
async def select_style(
    body: SelectStyleRequest,
    request: Request,
    runtime: ApiRuntime = Depends(get_runtime),
):
    context = _context(request)
    snapshot = await runtime.application.select_style(
        SelectStyle(expected_revision=body.expected_revision, style_id=body.style_id)
    )
    return to_snapshot_response(snapshot, context=context)


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def list_sessions(
    runtime: ApiRuntime = Depends(get_runtime),
) -> SessionListResponse:
    from jung.api.contracts import to_session_summary

    sessions = await runtime.application.list_sessions()
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
    runtime: ApiRuntime = Depends(get_runtime),
) -> SessionHistoryResponse:
    history = await runtime.application.get_session_history(session_id)
    return to_session_history_response(history)


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=StartSessionResponse,
    responses=CONFLICT_RESPONSES,
)
async def start_session(
    body: StartSessionRequest,
    request: Request,
    runtime: ApiRuntime = Depends(get_runtime),
) -> StartSessionResponse:
    context = _context(request)
    started = await runtime.application.start_session(
        StartSession(expected_revision=body.expected_revision)
    )
    return to_start_session_response(started, context=context)


@router.post(
    "/sessions/{session_id}/end",
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
    responses={**NOT_FOUND_RESPONSES, **CONFLICT_RESPONSES},
)
async def end_session(
    session_id: UUID,
    body: EndSessionRequest,
    request: Request,
    runtime: ApiRuntime = Depends(get_runtime),
):
    context = _context(request)
    snapshot = await runtime.application.end_session(
        EndSession(expected_revision=body.expected_revision, session_id=session_id)
    )
    return to_snapshot_response(snapshot, context=context)


@router.post(
    "/operations/current/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
    responses=CONFLICT_RESPONSES,
)
async def retry_operation(
    body: RetryOperationRequest,
    request: Request,
    runtime: ApiRuntime = Depends(get_runtime),
):
    context = _context(request)
    snapshot = await runtime.application.get_snapshot()
    operation = snapshot.current_operation
    if (
        operation is None
        or operation.status is not OperationStatus.FAILED
        or not operation.retryable
    ):
        raise InvalidCommand("operation is not the current failed operation")
    snapshot = await runtime.application.retry_operation(
        RetryOperation(
            expected_revision=body.expected_revision,
            operation_id=operation.id,
        )
    )
    return to_snapshot_response(snapshot, context=context)


@router.get(
    "/health",
    response_model=HealthResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def health(request: Request):
    state = request.app.state.api
    if not state.ready:
        body = not_ready_error_response(request_id=request.state.request_id)
        return build_error_response(status=503, body=body)
    return HealthResponse(status="healthy")
