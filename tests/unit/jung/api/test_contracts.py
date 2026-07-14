"""Unit tests for jung.api.contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from jung.api.contracts import (
    COMMAND_ORDER,
    ErrorEnvelope,
    ErrorEvent,
    MappingContext,
    ProfileUpdateRequest,
    SendMessageCommand,
    ServerEvent,
    build_error_event,
    stored_error_envelope,
    to_operation_changed_event,
    to_snapshot_response,
    to_style_options_response,
)
from jung.domain.models import (
    AppSnapshot,
    CommandName,
    Operation,
    OperationKind,
    OperationStatus,
    Stage,
)
from jung.domain.results import StyleOptions, StyleRecommendationView, StyleSummary
from jung.llm.errors import LLMUnavailable


def test_profile_update_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProfileUpdateRequest.model_validate(
            {
                "expected_revision": 0,
                "profile": {
                    "name": "Alex",
                    "primary_language": "English",
                },
                "user_id": "legacy",
            }
        )


def test_send_message_command_requires_all_fields() -> None:
    command = SendMessageCommand.model_validate(
        {
            "type": "send_message",
            "session_id": str(uuid4()),
            "client_message_id": str(uuid4()),
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "content": "hello",
        }
    )
    assert command.type == "send_message"


def test_snapshot_mapper_maps_current_operation_to_operation() -> None:
    now = datetime.now(UTC)
    operation_id = uuid4()
    session_id = uuid4()
    context = MappingContext(request_id=uuid4())
    snapshot = AppSnapshot(
        revision=3,
        stage=Stage.ASSESSMENT,
        profile_complete=True,
        current_operation=Operation(
            id=operation_id,
            kind=OperationKind.ASSESSMENT,
            status=OperationStatus.RUNNING,
            source_session_id=session_id,
            attempt=1,
            retryable=True,
            created_at=now,
            updated_at=now,
        ),
        available_commands=frozenset({CommandName.RETRY_OPERATION, CommandName.UPDATE_PROFILE}),
    )
    response = to_snapshot_response(snapshot, context=context)
    assert response.operation is not None
    assert response.operation.id == operation_id
    assert response.available_commands == [
        "update_profile",
        "retry_operation",
    ]


def test_command_order_is_canonical() -> None:
    assert [command.value for command in COMMAND_ORDER] == [
        "update_profile",
        "send_message",
        "select_style",
        "start_session",
        "end_session",
        "retry_operation",
    ]


def test_style_options_mapper_redacts_assessment_internals() -> None:
    options = StyleOptions(
        styles=(
            StyleSummary(id="cbt", name="CBT", description="desc"),
        ),
        recommendations=(
            StyleRecommendationView(
                style_id="cbt",
                score=0.9,
                rationale="fit",
                key_topics=("anxiety",),
            ),
        ),
    )
    payload = to_style_options_response(options).model_dump(mode="json")
    dumped = json.dumps(payload)
    for forbidden in (
        "initial_plan",
        "formulation",
        "presenting_concerns",
        "user_id",
    ):
        assert forbidden not in dumped


def test_stored_error_envelope_uses_mapping_context_request_id() -> None:
    request_id = uuid4()
    context = MappingContext(request_id=request_id)
    envelope = stored_error_envelope(
        "llm_unavailable",
        "The language model is currently unavailable.",
        True,
        context=context,
    )
    assert envelope is not None
    assert envelope.request_id == request_id


def test_error_event_request_id_invariant() -> None:
    context = MappingContext(request_id=uuid4())
    envelope = ErrorEnvelope(
        code="invalid_command",
        message="not allowed",
        request_id=context.request_id,
        retryable=False,
    )
    event = build_error_event(envelope, context=context)
    assert event.request_id == event.error.request_id == context.request_id
    serialized = event.model_dump(mode="json")
    assert serialized["request_id"] == str(context.request_id)
    assert serialized["error"]["request_id"] == str(context.request_id)


def test_operation_changed_event_shares_error_request_id() -> None:
    now = datetime.now(UTC)
    request_id = uuid4()
    context = MappingContext(request_id=request_id)
    operation = Operation(
        id=uuid4(),
        kind=OperationKind.ASSESSMENT,
        status=OperationStatus.FAILED,
        source_session_id=uuid4(),
        attempt=1,
        error_code="llm_timeout",
        error_message="The language model request timed out.",
        retryable=True,
        created_at=now,
        updated_at=now,
    )
    snapshot = AppSnapshot(
        revision=2,
        stage=Stage.ASSESSMENT,
        profile_complete=True,
        current_operation=operation,
        available_commands=frozenset(),
    )
    event = to_operation_changed_event(operation, snapshot, context=context)
    assert event.operation.error is not None
    assert event.snapshot.operation is not None
    assert event.operation.error.request_id == request_id
    assert event.snapshot.operation.error.request_id == request_id


def test_server_event_union_validates_discriminator() -> None:
    adapter = TypeAdapter(ServerEvent)
    event = adapter.validate_python(
        {
            "type": "error",
            "request_id": str(uuid4()),
            "error": {
                "code": "validation_error",
                "message": "bad",
                "request_id": str(uuid4()),
            },
        }
    )
    assert isinstance(event, ErrorEvent)


def test_llm_error_message_not_used_in_stored_mapper() -> None:
    exc = LLMUnavailable("secret-marker https://api.example.com sk-test")
    from jung.application import _classify_worker_error

    code, message, _retryable = _classify_worker_error(exc)
    context = MappingContext(request_id=uuid4())
    envelope = stored_error_envelope(code, message, True, context=context)
    assert envelope is not None
    assert "secret-marker" not in envelope.message
