"""Unit tests for jung.api.contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from jung.api.contracts import (
    COMMAND_ORDER,
    AppSnapshotResponse,
    ErrorEnvelope,
    ErrorEvent,
    MappingContext,
    MessageResponse,
    PlanDetailResponse,
    PlanSummaryResponse,
    ProfileUpdateRequest,
    ProfileWire,
    SendMessageCommand,
    ServerEvent,
    SessionDetailResponse,
    SessionSummaryResponse,
    build_error_event,
    normalize_public_error_code,
    stored_error_envelope,
    to_operation_changed_event,
    to_plan_detail,
    to_plan_summary,
    to_profile_response,
    to_session_detail,
    to_session_history_response,
    to_session_summary,
    to_snapshot_response,
    to_style_options_response,
)
from jung.domain.models import (
    AppSnapshot,
    CommandName,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    OperationStatus,
    Plan,
    Profile,
    Session,
    SessionKind,
    Stage,
)
from jung.domain.results import (
    ProfileView,
    SessionHistory,
    StyleOptions,
    StyleRecommendationView,
    StyleSummary,
)

_PUBLIC_WIRE_MODELS: tuple[type[BaseModel], ...] = (
    ProfileWire,
    ProfileUpdateRequest,
    SendMessageCommand,
    SessionSummaryResponse,
    SessionDetailResponse,
    MessageResponse,
    PlanSummaryResponse,
    PlanDetailResponse,
    AppSnapshotResponse,
    ErrorEnvelope,
    ErrorEvent,
)


def _assert_datetime_schema(schema: dict[str, object]) -> None:
    if "anyOf" in schema:
        branches = schema["anyOf"]
        datetime_branch = next(
            branch for branch in branches if branch.get("type") == "string"
        )
    else:
        datetime_branch = schema

    assert datetime_branch["type"] == "string"
    assert datetime_branch["format"] == "date-time"


@pytest.fixture
def wire_domain_objects() -> dict[str, Any]:
    now = datetime.now(UTC)
    profile = Profile(
        name="Alex",
        primary_language="English",
    )
    session_id = uuid4()
    plan_id = uuid4()
    operation_id = uuid4()
    message_id = uuid4()
    request_id = uuid4()
    client_message_id = uuid4()
    context = MappingContext(request_id=request_id)

    session = Session(
        id=session_id,
        kind=SessionKind.INTAKE,
        started_at=now,
        ended_at=None,
        plan_id=plan_id,
        summary="summary",
        briefing={"focus": "anxiety"},
    )
    message = Message(
        id=message_id,
        session_id=session_id,
        sequence=1,
        role=MessageRole.USER,
        content="hello",
        created_at=now,
        client_message_id=client_message_id,
    )
    plan = Plan(
        id=plan_id,
        version=1,
        selected_style="cbt",
        focus="anxiety",
        themes=("anxiety",),
        goals=("sleep",),
        current_progress="initial",
        planned_interventions=("breathing",),
        revision_recommendations=(),
        session_briefing={"focus": "anxiety"},
        source_session_id=session_id,
        created_at=now,
    )
    operation = Operation(
        id=operation_id,
        kind=OperationKind.ASSESSMENT,
        status=OperationStatus.FAILED,
        source_session_id=session_id,
        attempt=1,
        error_code="llm_timeout",
        error_message="The language model request timed out.",
        retryable=True,
        created_at=now,
        updated_at=now,
    )
    snapshot = AppSnapshot(
        revision=3,
        stage=Stage.ASSESSMENT,
        profile_complete=True,
        current_operation=operation,
        available_commands=frozenset(
            {CommandName.RETRY_OPERATION, CommandName.UPDATE_PROFILE}
        ),
    )
    profile_view = ProfileView(
        profile=profile,
        current_plan=plan,
        snapshot=snapshot,
    )
    history = SessionHistory(session=session, messages=(message,), plans=(plan,))

    return {
        "now": now,
        "profile": profile,
        "session": session,
        "message": message,
        "plan": plan,
        "operation": operation,
        "snapshot": snapshot,
        "profile_view": profile_view,
        "history": history,
        "context": context,
        "request_id": request_id,
        "client_message_id": client_message_id,
    }


def test_request_and_timestamp_validation(wire_domain_objects: dict[str, Any]) -> None:
    del wire_domain_objects
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

    with pytest.raises(ValidationError):
        ProfileWire.model_validate(
            {
                "name": "Alex",
                "primary_language": "English",
                "derived_profile": {"formulation": "hidden"},
            }
        )

    with pytest.raises(ValidationError):
        ProfileWire.model_validate(
            {
                "name": "Alex",
                "primary_language": "English",
                "user_id": "legacy",
            }
        )

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

    timestamp_fields = (
        (SessionSummaryResponse, "started_at", False),
        (SessionSummaryResponse, "ended_at", True),
        (MessageResponse, "created_at", False),
        (PlanSummaryResponse, "created_at", False),
    )
    for model, field_name, nullable in timestamp_fields:
        del nullable
        schema = model.model_json_schema()["properties"][field_name]
        _assert_datetime_schema(schema)

    naive = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ValidationError):
        SessionSummaryResponse.model_validate(
            {
                "id": str(uuid4()),
                "kind": "intake",
                "started_at": naive,
            }
        )

    with pytest.raises(ValidationError):
        SessionSummaryResponse.model_validate(
            {
                "id": str(uuid4()),
                "kind": "intake",
                "started_at": "not-a-datetime",
            }
        )


def test_snapshot_and_command_mapping(wire_domain_objects: dict[str, Any]) -> None:
    snapshot = wire_domain_objects["snapshot"]
    operation = wire_domain_objects["operation"]
    context = wire_domain_objects["context"]

    response = to_snapshot_response(snapshot, context=context)
    assert response.operation is not None
    assert response.operation.id == operation.id
    assert response.available_commands == [
        "update_profile",
        "retry_operation",
    ]
    assert [command.value for command in COMMAND_ORDER] == [
        "update_profile",
        "send_message",
        "select_style",
        "start_session",
        "end_session",
        "retry_operation",
    ]


def test_summary_detail_mapping_and_redaction(
    wire_domain_objects: dict[str, Any],
) -> None:
    session = wire_domain_objects["session"]
    plan = wire_domain_objects["plan"]
    profile_view = wire_domain_objects["profile_view"]
    history = wire_domain_objects["history"]
    context = wire_domain_objects["context"]

    summary = to_session_summary(session)
    detail = to_session_detail(session)
    assert "summary" not in type(summary).model_fields
    assert detail.summary == "summary"
    assert detail.briefing == {"focus": "anxiety"}

    plan_summary = to_plan_summary(plan)
    plan_detail = to_plan_detail(plan)
    assert "selected_style" not in type(plan_summary).model_fields
    assert plan_detail.selected_style == "cbt"

    profile_response = to_profile_response(profile_view, context=context)
    history_response = to_session_history_response(history)
    assert profile_response.profile.name == "Alex"
    assert history_response.messages[0].content == "hello"

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

    for model in _PUBLIC_WIRE_MODELS:
        properties = model.model_json_schema().get("properties", {})
        assert "user_id" not in properties


def test_error_normalization_and_event_invariants(
    wire_domain_objects: dict[str, Any],
) -> None:
    request_id = wire_domain_objects["request_id"]
    context = wire_domain_objects["context"]
    operation = wire_domain_objects["operation"]
    snapshot = wire_domain_objects["snapshot"]

    assert normalize_public_error_code("stale_pending") == "operation_failed"
    assert normalize_public_error_code("llm_timeout") == "llm_timeout"

    envelope = stored_error_envelope(
        "stale_pending",
        "A pending operation was interrupted.",
        True,
        context=context,
    )
    assert envelope is not None
    assert envelope.code == "operation_failed"
    assert envelope.message == "A pending operation was interrupted."
    assert envelope.retryable is True
    assert envelope.request_id == request_id

    matching_envelope = ErrorEnvelope(
        code="invalid_command",
        message="not allowed",
        request_id=context.request_id,
        retryable=False,
    )
    event = build_error_event(matching_envelope, context=context)
    assert event.request_id == event.error.request_id == context.request_id

    operation_event = to_operation_changed_event(
        operation,
        snapshot,
        context=context,
    )
    assert operation_event.operation.error is not None
    assert operation_event.snapshot.operation is not None
    assert operation_event.operation.error.request_id == request_id
    assert operation_event.snapshot.operation.error.request_id == request_id

    adapter = TypeAdapter(ServerEvent)
    shared_request_id = uuid4()
    validated = adapter.validate_python(
        {
            "type": "error",
            "request_id": str(shared_request_id),
            "error": {
                "code": "validation_error",
                "message": "bad",
                "request_id": str(shared_request_id),
            },
        }
    )
    assert isinstance(validated, ErrorEvent)

    with pytest.raises(ValidationError):
        ErrorEvent.model_validate(
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
