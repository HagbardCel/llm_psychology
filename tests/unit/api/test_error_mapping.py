"""Unit tests for jung.api.errors."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

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
)

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


def test_parse_request_id_header_rejects_blank() -> None:
    with pytest.raises(RequestIdError):
        parse_request_id_header("   ")


def test_parse_request_id_header_rejects_malformed() -> None:
    with pytest.raises(RequestIdError):
        parse_request_id_header("not-a-uuid")


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
