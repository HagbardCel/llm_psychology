"""Transport error mapping for /api/v1."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from jung.api.contracts import (
    AppSnapshotResponse,
    ErrorCode,
    ErrorEnvelope,
    ErrorResponse,
    normalize_public_error_code,
)
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


@dataclass(frozen=True, slots=True)
class _ErrorSpec:
    code: ErrorCode
    message: str
    status: int
    retryable: bool | None = False


_ERROR_SPECS: tuple[tuple[type[Exception], _ErrorSpec], ...] = (
    (
        RequestIdError,
        _ErrorSpec(
            "validation_error",
            "The request ID header is malformed.",
            422,
            False,
        ),
    ),
    (
        InvalidCommand,
        _ErrorSpec(
            "invalid_command",
            "Command is not permitted in the current workflow state.",
            409,
            False,
        ),
    ),
    (
        RevisionConflict,
        _ErrorSpec(
            "state_conflict",
            "The request used a stale revision.",
            409,
            False,
        ),
    ),
    (
        Busy,
        _ErrorSpec(
            "busy",
            "The application is busy with conflicting work.",
            409,
            False,
        ),
    ),
    (
        NotFound,
        _ErrorSpec(
            "not_found",
            "The requested resource was not found.",
            404,
            False,
        ),
    ),
    (
        InvariantViolation,
        _ErrorSpec(
            "internal_error",
            "An unexpected error occurred.",
            500,
            False,
        ),
    ),
    (
        PersistenceFailure,
        _ErrorSpec(
            "internal_error",
            "An unexpected error occurred.",
            500,
            False,
        ),
    ),
    (
        DomainError,
        _ErrorSpec(
            "internal_error",
            "An unexpected error occurred.",
            500,
            False,
        ),
    ),
)

_DEFAULT_ERROR_SPEC = _ErrorSpec(
    "internal_error",
    "An unexpected error occurred.",
    500,
    False,
)


def _error_spec(exc: Exception) -> _ErrorSpec:
    for exc_type, spec in _ERROR_SPECS:
        if isinstance(exc, exc_type):
            return spec
    return _DEFAULT_ERROR_SPEC


def parse_request_id_header(value: str | None) -> UUID:
    """Return a valid request ID or raise RequestIdError."""
    if value is None:
        return uuid4()
    stripped = value.strip()
    if not stripped:
        raise RequestIdError(value)
    try:
        return UUID(stripped)
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
            code=normalize_public_error_code(exc.code),
            message=str(exc),
            request_id=request_id,
            retryable=exc.retryable,
            current_snapshot=None,
        )
    spec = _error_spec(exc)
    snapshot = current_snapshot if isinstance(exc, RevisionConflict) else None
    return ErrorEnvelope(
        code=spec.code,
        message=spec.message,
        request_id=request_id,
        retryable=spec.retryable,
        current_snapshot=snapshot,
    )


def http_status_for_exception(exc: Exception) -> int:
    if isinstance(exc, StoredWorkFailure):
        return 409
    return _error_spec(exc).status


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
    return ErrorResponse.model_validate(envelope.model_dump())


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
