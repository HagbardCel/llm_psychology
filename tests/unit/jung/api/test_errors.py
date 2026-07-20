"""Unit tests for jung.api.errors."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from jung.api.contracts import MappingContext, to_snapshot_response
from jung.api.errors import (
    RequestIdError,
    http_status_for_exception,
    not_ready_error_response,
    parse_request_id_header,
    to_error_envelope,
    to_error_response,
    validation_error_response,
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
from jung.domain.models import AppSnapshot, Stage

_SECRET_MARKER = "secret-marker"
_INTERNAL_MESSAGE = "An unexpected error occurred."


class CustomDomainError(DomainError):
    pass


def test_parse_request_id_header_generates_when_absent() -> None:
    request_id = parse_request_id_header(None)
    assert isinstance(request_id, UUID)


def test_parse_request_id_header_accepts_valid_uuid() -> None:
    value = uuid4()
    assert parse_request_id_header(str(value)) == value


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_parse_request_id_header_rejects_blank(value: str) -> None:
    with pytest.raises(RequestIdError):
        parse_request_id_header(value)


def test_parse_request_id_header_rejects_malformed() -> None:
    with pytest.raises(RequestIdError):
        parse_request_id_header("not-a-uuid")


def test_invalid_command_ignores_current_snapshot() -> None:
    request_id = uuid4()
    snapshot = AppSnapshot(
        revision=4,
        stage=Stage.SETUP,
        profile_complete=False,
        available_commands=frozenset(),
    )
    context = MappingContext(request_id=request_id)
    wire_snapshot = to_snapshot_response(snapshot, context=context)
    envelope = to_error_envelope(
        InvalidCommand(),
        request_id=request_id,
        current_snapshot=wire_snapshot,
    )
    assert envelope.current_snapshot is None


def test_stored_work_failure_preserves_safe_message() -> None:
    request_id = uuid4()
    exc = StoredWorkFailure(
        code="llm_unavailable",
        message="The language model is currently unavailable.",
        retryable=True,
    )
    envelope = to_error_envelope(exc, request_id=request_id)
    assert envelope.code == "llm_unavailable"
    assert envelope.message == "The language model is currently unavailable."
    assert envelope.retryable is True
    assert http_status_for_exception(exc) == 409


def test_stored_work_failure_normalizes_internal_code() -> None:
    request_id = uuid4()
    exc = StoredWorkFailure(
        code="stale_pending",
        message="A pending operation was interrupted.",
        retryable=True,
    )
    envelope = to_error_envelope(exc, request_id=request_id)
    assert envelope.code == "operation_failed"
    assert envelope.message == "A pending operation was interrupted."
    assert envelope.retryable is True


def test_revision_conflict_can_include_snapshot() -> None:
    request_id = uuid4()
    snapshot = AppSnapshot(
        revision=4,
        stage=Stage.SETUP,
        profile_complete=False,
        available_commands=frozenset(),
    )
    context = MappingContext(request_id=request_id)
    wire_snapshot = to_snapshot_response(snapshot, context=context)
    envelope = to_error_envelope(
        RevisionConflict(3, 4),
        request_id=request_id,
        current_snapshot=wire_snapshot,
    )
    assert envelope.code == "state_conflict"
    assert envelope.current_snapshot is not None
    assert envelope.current_snapshot.revision == 4


def test_not_ready_error_response() -> None:
    request_id = uuid4()
    response = not_ready_error_response(request_id=request_id)
    assert response.code == "not_ready"
    assert response.retryable is True
    assert response.request_id == request_id


def test_validation_error_response() -> None:
    request_id = uuid4()
    response = validation_error_response(request_id=request_id)
    assert response.code == "validation_error"
    assert response.request_id == request_id


def test_to_error_response_wraps_envelope() -> None:
    request_id = uuid4()
    response = to_error_response(Busy(), request_id=request_id)
    assert response.code == "busy"
    assert response.request_id == request_id


@pytest.mark.parametrize(
    (
        "exc",
        "expected_code",
        "expected_status",
        "expected_retryable",
        "expected_message",
    ),
    [
        (
            RequestIdError("bad"),
            "validation_error",
            422,
            False,
            "The request ID header is malformed.",
        ),
        (
            InvalidCommand(),
            "invalid_command",
            409,
            False,
            "Command is not permitted in the current workflow state.",
        ),
        (
            RevisionConflict(1, 2),
            "state_conflict",
            409,
            False,
            "The request used a stale revision.",
        ),
        (
            Busy(),
            "busy",
            409,
            False,
            "The application is busy with conflicting work.",
        ),
        (
            NotFound(),
            "not_found",
            404,
            False,
            "The requested resource was not found.",
        ),
        (
            InvariantViolation(_SECRET_MARKER),
            "internal_error",
            500,
            False,
            _INTERNAL_MESSAGE,
        ),
        (
            PersistenceFailure(_SECRET_MARKER),
            "internal_error",
            500,
            False,
            _INTERNAL_MESSAGE,
        ),
        (
            CustomDomainError(_SECRET_MARKER),
            "internal_error",
            500,
            False,
            _INTERNAL_MESSAGE,
        ),
        (
            RuntimeError(_SECRET_MARKER),
            "internal_error",
            500,
            False,
            _INTERNAL_MESSAGE,
        ),
    ],
)
def test_error_mapping_table(
    exc: Exception,
    expected_code: str,
    expected_status: int,
    expected_retryable: bool,
    expected_message: str,
) -> None:
    request_id = uuid4()
    envelope = to_error_envelope(exc, request_id=request_id)
    assert envelope.code == expected_code
    assert envelope.request_id == request_id
    assert envelope.retryable is expected_retryable
    assert envelope.message == expected_message
    assert http_status_for_exception(exc) == expected_status
    assert _SECRET_MARKER not in envelope.message
