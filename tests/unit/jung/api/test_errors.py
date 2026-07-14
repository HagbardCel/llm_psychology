"""Unit tests for jung.api.errors."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from jung.api.contracts import (
    AppSnapshotResponse,
    MappingContext,
    to_snapshot_response,
)
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
    InvalidCommand,
    NotFound,
    RevisionConflict,
    StoredWorkFailure,
)
from jung.domain.models import AppSnapshot, Stage


def test_parse_request_id_header_generates_when_absent() -> None:
    request_id = parse_request_id_header(None)
    assert isinstance(request_id, UUID)


def test_parse_request_id_header_accepts_valid_uuid() -> None:
    value = uuid4()
    assert parse_request_id_header(str(value)) == value


def test_parse_request_id_header_rejects_malformed() -> None:
    with pytest.raises(RequestIdError):
        parse_request_id_header("not-a-uuid")


def test_to_error_envelope_maps_domain_errors() -> None:
    request_id = uuid4()
    envelope = to_error_envelope(InvalidCommand(), request_id=request_id)
    assert envelope.code == "invalid_command"
    assert envelope.request_id == request_id
    assert "revision" not in envelope.message.lower()


def test_http_status_for_stored_work_failure_is_409() -> None:
    exc = StoredWorkFailure(
        code="llm_timeout",
        message="The language model request timed out.",
        retryable=True,
    )
    assert http_status_for_exception(exc) == 409


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
    assert isinstance(envelope.current_snapshot, AppSnapshotResponse)
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
    ("exc", "status"),
    [
        (NotFound(), 404),
        (InvalidCommand(), 409),
        (Busy(), 409),
        (RevisionConflict(1, 2), 409),
    ],
)
def test_http_status_mapping(exc: Exception, status: int) -> None:
    assert http_status_for_exception(exc) == status
