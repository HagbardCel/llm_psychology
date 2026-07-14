"""Transport error mapping for /api/v1."""

from __future__ import annotations

from uuid import UUID, uuid4

from jung.api.contracts import AppSnapshotResponse, ErrorEnvelope, ErrorResponse
from jung.domain.errors import (
    Busy,
    DomainError,
    InvalidCommand,
    InvariantViolation,
    NotFound,
    PersistenceFailure,
    RevisionConflict,
    StoredWorkFailure,
)


class RequestIdError(ValueError):
    """Raised when a supplied request ID header is malformed."""


def parse_request_id_header(value: str | None) -> UUID:
    """Return a valid request ID or raise RequestIdError."""
    if value is None or not value.strip():
        return uuid4()
    try:
        return UUID(value.strip())
    except ValueError as exc:
        raise RequestIdError(value) from exc


def new_request_id() -> UUID:
    return uuid4()


def to_error_envelope(
    exc: Exception,
    *,
    request_id: UUID,
    current_snapshot: AppSnapshotResponse | None = None,
) -> ErrorEnvelope:
    if isinstance(exc, StoredWorkFailure):
        return ErrorEnvelope(
            code=exc.code,
            message=str(exc),
            request_id=request_id,
            retryable=exc.retryable,
            current_snapshot=current_snapshot,
        )
    if isinstance(exc, InvalidCommand):
        return ErrorEnvelope(
            code="invalid_command",
            message="Command is not permitted in the current workflow state.",
            request_id=request_id,
            retryable=False,
            current_snapshot=current_snapshot,
        )
    if isinstance(exc, RevisionConflict):
        return ErrorEnvelope(
            code="state_conflict",
            message="The request used a stale revision.",
            request_id=request_id,
            retryable=False,
            current_snapshot=current_snapshot,
        )
    if isinstance(exc, Busy):
        return ErrorEnvelope(
            code="busy",
            message="The application is busy with conflicting work.",
            request_id=request_id,
            retryable=False,
            current_snapshot=current_snapshot,
        )
    if isinstance(exc, NotFound):
        return ErrorEnvelope(
            code="not_found",
            message="The requested resource was not found.",
            request_id=request_id,
            retryable=False,
            current_snapshot=current_snapshot,
        )
    if isinstance(exc, InvariantViolation):
        return ErrorEnvelope(
            code="internal_error",
            message="An unexpected error occurred.",
            request_id=request_id,
            retryable=False,
            current_snapshot=current_snapshot,
        )
    if isinstance(exc, PersistenceFailure):
        return ErrorEnvelope(
            code="internal_error",
            message="An unexpected error occurred.",
            request_id=request_id,
            retryable=False,
            current_snapshot=current_snapshot,
        )
    if isinstance(exc, DomainError):
        return ErrorEnvelope(
            code="internal_error",
            message="An unexpected error occurred.",
            request_id=request_id,
            retryable=False,
            current_snapshot=current_snapshot,
        )
    return ErrorEnvelope(
        code="internal_error",
        message="An unexpected error occurred.",
        request_id=request_id,
        retryable=False,
        current_snapshot=current_snapshot,
    )


def http_status_for_exception(exc: Exception) -> int:
    if isinstance(exc, NotFound):
        return 404
    if isinstance(exc, StoredWorkFailure):
        return 409
    if isinstance(exc, (InvalidCommand, Busy, RevisionConflict)):
        return 409
    if isinstance(exc, (InvariantViolation, PersistenceFailure)):
        return 500
    return 500


def to_error_response(
    exc: Exception,
    *,
    request_id: UUID,
    current_snapshot: AppSnapshotResponse | None = None,
) -> ErrorResponse:
    envelope = to_error_envelope(
        exc,
        request_id=request_id,
        current_snapshot=current_snapshot,
    )
    return ErrorResponse(
        code=envelope.code,
        message=envelope.message,
        request_id=envelope.request_id,
        current_snapshot=envelope.current_snapshot,
        retryable=envelope.retryable,
    )


def validation_error_response(*, request_id: UUID) -> ErrorResponse:
    return ErrorResponse(
        code="validation_error",
        message="Request validation failed.",
        request_id=request_id,
        retryable=False,
        current_snapshot=None,
    )


def not_ready_error_response(*, request_id: UUID) -> ErrorResponse:
    return ErrorResponse(
        code="not_ready",
        message="Service is not ready",
        request_id=request_id,
        retryable=True,
        current_snapshot=None,
    )
