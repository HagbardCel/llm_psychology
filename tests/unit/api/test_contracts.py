"""Unit tests for jung.api.contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import get_args
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from jung.api.contracts import (
    ChatRequest,
    ErrorCode,
    ErrorEnvelope,
    ErrorEvent,
    ErrorResponse,
    MessageCompletedEvent,
    MessageFailedEvent,
    MessageResponse,
    MessageRoleWire,
    PlanDetailResponse,
    PlanSummaryResponse,
    ProfileUpdateRequest,
    ProfileWire,
    ServerEvent,
    SessionDetailResponse,
    SessionSummaryResponse,
    TokenEvent,
)
from jung.api.mapping import (
    COMMAND_ORDER,
    MappingContext,
    build_error_event,
    normalize_public_error_code,
    stored_error_envelope,
    to_operation_summary,
    to_plan_detail,
    to_plan_summary,
    to_profile_response,
    to_session_detail,
    to_session_history_response,
    to_session_summary,
    to_snapshot_response,
    to_start_session_response,
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
    StartedSession,
    StyleOptions,
    StyleRecommendationView,
    StyleSummary,
)
from jung.domain.session_artifacts import (
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
    SessionReview,
)


def _contract_wire_models() -> tuple[type[BaseModel], ...]:
    import jung.api.contracts as contracts_module

    models = (
        obj
        for obj in vars(contracts_module).values()
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseModel)
            and obj.__module__ == contracts_module.__name__
        )
    )
    return tuple(sorted(models, key=lambda model: model.__name__))


def _contains_property(node: object, property_name: str) -> bool:
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict) and property_name in properties:
            return True
        return any(_contains_property(value, property_name) for value in node.values())
    if isinstance(node, list):
        return any(_contains_property(value, property_name) for value in node)
    return False


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


def _now() -> datetime:
    return datetime.now(UTC)


def test_wire_utc_datetime_normalizes_aware_offsets() -> None:
    value = SessionSummaryResponse.model_validate(
        {
            "id": str(uuid4()),
            "kind": "intake",
            "started_at": "2026-01-01T13:00:00+01:00",
            "ended_at": None,
            "plan_id": None,
        }
    )
    assert value.started_at == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _make_review() -> SessionReview:
    return SessionReview(
        analysis=SessionAnalysis(
            summary="summary",
            key_themes=("anxiety",),
        ),
        briefing=SessionBriefing(
            narrative_handoff="Continue with anxiety work.",
            recommended_opening_focus="pace carefully",
        ),
        plan_recommendation=PlanPatch(),
        generation=None,
    )


def _make_session(*, now: datetime | None = None) -> Session:
    timestamp = now or _now()
    return Session(
        id=uuid4(),
        kind=SessionKind.INTAKE,
        started_at=timestamp,
        ended_at=None,
        plan_id=uuid4(),
        review=_make_review(),
    )


def _make_plan(*, session_id: UUID, now: datetime) -> Plan:
    return Plan(
        id=uuid4(),
        version=1,
        selected_style="cbt",
        focus="anxiety",
        themes=("anxiety",),
        goals=("sleep",),
        current_progress="initial",
        planned_interventions=("breathing",),
        revision_recommendations=(),
        source_session_id=session_id,
        created_at=now,
    )


def _make_failed_operation(*, session_id: UUID, now: datetime) -> Operation:
    return Operation(
        id=uuid4(),
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


def _message(
    *,
    session_id: UUID,
    client_message_id: UUID,
    role: MessageRole,
    content: str,
    sequence: int,
    now: datetime,
) -> Message:
    return Message(
        id=uuid4(),
        session_id=session_id,
        sequence=sequence,
        role=role,
        content=content,
        created_at=now,
        client_message_id=client_message_id,
    )


def test_profile_requests_reject_top_level_and_nested_extras() -> None:
    with pytest.raises(ValidationError):
        ProfileUpdateRequest.model_validate(
            {
                "profile": {
                    "name": "Alex",
                    "primary_language": "English",
                },
                "unexpected_field": "x",
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
                "unexpected_field": "x",
            }
        )


def test_chat_request_validates_complete_payload() -> None:
    request = ChatRequest.model_validate(
        {
            "session_id": str(uuid4()),
            "client_message_id": str(uuid4()),
            "content": "hello",
        }
    )
    assert request.content == "hello"


@pytest.mark.parametrize(
    ("model", "field_name"),
    [
        (SessionSummaryResponse, "started_at"),
        (SessionSummaryResponse, "ended_at"),
        (MessageResponse, "created_at"),
        (PlanSummaryResponse, "created_at"),
    ],
)
def test_wire_timestamp_schemas_are_date_time(
    model: type[BaseModel],
    field_name: str,
) -> None:
    schema = model.model_json_schema()["properties"][field_name]
    _assert_datetime_schema(schema)


def test_wire_timestamp_validation_rejects_naive_and_invalid_values() -> None:
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


def test_start_session_response_maps_atomic_result() -> None:
    now = _now()
    session = Session(
        id=uuid4(),
        kind=SessionKind.THERAPY,
        started_at=now,
        ended_at=None,
        plan_id=None,
        review=None,
    )
    context = MappingContext(request_id=uuid4())
    snapshot = AppSnapshot(
        stage=Stage.THERAPY,
        profile_complete=True,
        active_session=session,
        available_commands=frozenset({CommandName.END_SESSION}),
    )
    started = StartedSession(session=session, snapshot=snapshot)
    response = to_start_session_response(started, context=context)
    assert response.session.id == session.id
    assert response.snapshot.active_session is not None
    assert response.snapshot.active_session.id == session.id


def test_snapshot_maps_current_operation_and_command_order() -> None:
    now = _now()
    session = _make_session(now=now)
    operation = _make_failed_operation(session_id=session.id, now=now)
    context = MappingContext(request_id=uuid4())
    snapshot = AppSnapshot(
        stage=Stage.ASSESSMENT,
        profile_complete=True,
        current_operation=operation,
        available_commands=frozenset(
            {CommandName.RETRY_OPERATION, CommandName.UPDATE_PROFILE}
        ),
    )

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


def test_session_and_plan_summary_detail_separation() -> None:
    now = _now()
    session = _make_session(now=now)
    plan = _make_plan(session_id=session.id, now=now)

    summary = to_session_summary(session)
    detail = to_session_detail(session)
    assert "summary" not in type(summary).model_fields
    assert detail.summary == "summary"
    assert detail.briefing == session.review.briefing.model_dump(mode="json")
    assert frozenset(SessionDetailResponse.model_fields) >= {
        "summary",
        "briefing",
    }

    plan_summary = to_plan_summary(plan)
    plan_detail = to_plan_detail(plan)
    assert "selected_style" not in type(plan_summary).model_fields
    assert plan_detail.selected_style == "cbt"
    assert "session_briefing" not in PlanDetailResponse.model_fields


def test_session_detail_without_review_has_null_summary_and_briefing() -> None:
    now = _now()
    session = Session(
        id=uuid4(),
        kind=SessionKind.THERAPY,
        started_at=now,
        ended_at=None,
        plan_id=None,
        review=None,
    )
    detail = to_session_detail(session)
    assert detail.summary is None
    assert detail.briefing is None


def test_profile_history_and_style_mapping() -> None:
    now = _now()
    session = _make_session(now=now)
    plan = _make_plan(session_id=session.id, now=now)
    message = _message(
        session_id=session.id,
        client_message_id=uuid4(),
        role=MessageRole.USER,
        content="hello",
        sequence=1,
        now=now,
    )
    operation = _make_failed_operation(session_id=session.id, now=now)
    context = MappingContext(request_id=uuid4())
    snapshot = AppSnapshot(
        stage=Stage.ASSESSMENT,
        profile_complete=True,
        current_operation=operation,
        available_commands=frozenset(),
    )
    profile_view = ProfileView(
        profile=Profile(name="Alex", primary_language="English"),
        current_plan=plan,
        snapshot=snapshot,
    )
    history = SessionHistory(session=session, messages=(message,), plans=(plan,))

    profile_response = to_profile_response(profile_view, context=context)
    history_response = to_session_history_response(history)
    assert profile_response.profile.name == "Alex"
    assert history_response.messages[0].content == "hello"
    assert history_response.messages[0].client_message_id == message.client_message_id

    options = StyleOptions(
        styles=(StyleSummary(id="cbt", name="CBT", description="desc"),),
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
    assert payload["styles"][0]["id"] == "cbt"
    assert payload["recommendations"][0]["style_id"] == "cbt"


def test_stored_error_envelope_normalizes_internal_codes() -> None:
    request_id = uuid4()
    context = MappingContext(request_id=request_id)

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


def test_error_event_request_id_invariant() -> None:
    context = MappingContext(request_id=uuid4())
    session_id = uuid4()
    client_message_id = uuid4()
    matching_envelope = ErrorEnvelope(
        code="invalid_command",
        message="not allowed",
        request_id=context.request_id,
        retryable=False,
    )
    event = build_error_event(
        matching_envelope,
        context=context,
        session_id=session_id,
        client_message_id=client_message_id,
    )
    assert event.request_id == event.error.request_id == context.request_id
    assert event.session_id == session_id
    assert event.client_message_id == client_message_id

    adapter = TypeAdapter(ServerEvent)
    shared_request_id = uuid4()
    validated = adapter.validate_python(
        {
            "type": "error",
            "request_id": str(shared_request_id),
            "session_id": str(session_id),
            "client_message_id": str(client_message_id),
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
                "session_id": str(session_id),
                "client_message_id": str(client_message_id),
                "error": {
                    "code": "validation_error",
                    "message": "bad",
                    "request_id": str(uuid4()),
                },
            }
        )

    with pytest.raises(ValidationError):
        ErrorEvent.model_validate(
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


def test_operation_summary_shares_mapping_context_request_id() -> None:
    now = _now()
    session = _make_session(now=now)
    operation = _make_failed_operation(session_id=session.id, now=now)
    request_id = uuid4()
    context = MappingContext(request_id=request_id)

    summary = to_operation_summary(operation, context=context)
    assert summary.error is not None
    assert summary.error.request_id == request_id
    assert summary.error.code == "llm_timeout"


def test_server_event_union_is_message_native() -> None:
    adapter = TypeAdapter(ServerEvent)
    now = _now()
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()
    user = MessageResponse(
        id=uuid4(),
        session_id=session_id,
        sequence=1,
        role="user",
        content="hello",
        created_at=now,
        client_message_id=client_message_id,
    )
    assistant = MessageResponse(
        id=uuid4(),
        session_id=session_id,
        sequence=2,
        role="assistant",
        content="hi",
        created_at=now,
        client_message_id=client_message_id,
    )

    token = adapter.validate_python(
        {
            "type": "token",
            "text": "hi",
            "request_id": str(request_id),
            "session_id": str(session_id),
            "client_message_id": str(client_message_id),
        }
    )
    completed = adapter.validate_python(
        {
            "type": "message_completed",
            "request_id": str(request_id),
            "session_id": str(session_id),
            "client_message_id": str(client_message_id),
            "user_message": user.model_dump(mode="json"),
            "assistant_message": assistant.model_dump(mode="json"),
        }
    )
    failed = adapter.validate_python(
        {
            "type": "message_failed",
            "request_id": str(request_id),
            "session_id": str(session_id),
            "client_message_id": str(client_message_id),
            "error": {
                "code": "llm_timeout",
                "message": "timed out",
                "request_id": str(request_id),
                "retryable": True,
            },
        }
    )
    assert isinstance(token, TokenEvent)
    assert isinstance(completed, MessageCompletedEvent)
    assert isinstance(failed, MessageFailedEvent)

    with pytest.raises(ValidationError):
        TokenEvent.model_validate(
            {
                "type": "token",
                "text": "hi",
                "request_id": str(request_id),
                "session_id": str(session_id),
                "client_message_id": str(client_message_id),
                "unexpected_field": "x",
            }
        )


def test_message_role_wire_and_domain_are_user_assistant_only() -> None:
    assert set(get_args(MessageRoleWire)) == {"user", "assistant"}
    assert {role.value for role in MessageRole} == {"user", "assistant"}


def test_message_response_requires_client_message_id() -> None:
    with pytest.raises(ValidationError):
        MessageResponse.model_validate(
            {
                "id": str(uuid4()),
                "session_id": str(uuid4()),
                "sequence": 1,
                "role": "user",
                "content": "hello",
                "created_at": _now().isoformat().replace("+00:00", "Z"),
            }
        )


def test_contract_surface_is_single_user() -> None:
    for model in _contract_wire_models():
        schema = model.model_json_schema()
        assert not _contains_property(schema, "user_id"), model.__name__


def test_contract_wire_surfaces_have_expected_membership() -> None:
    assert frozenset(ChatRequest.model_fields) == {
        "session_id",
        "client_message_id",
        "content",
    }
    assert frozenset(ErrorEnvelope.model_fields) == {
        "code",
        "message",
        "request_id",
        "retryable",
    }
    assert frozenset(ErrorEvent.model_fields) == {
        "type",
        "error",
        "request_id",
        "session_id",
        "client_message_id",
    }
    assert frozenset(get_args(ErrorCode)) == {
        "invalid_command",
        "busy",
        "not_found",
        "validation_error",
        "llm_unavailable",
        "llm_timeout",
        "invalid_llm_output",
        "operation_failed",
        "internal_error",
        "not_ready",
    }

    expected_server_event_fields = {
        TokenEvent: {
            "type",
            "text",
            "request_id",
            "session_id",
            "client_message_id",
        },
        MessageCompletedEvent: {
            "type",
            "request_id",
            "session_id",
            "client_message_id",
            "user_message",
            "assistant_message",
        },
        MessageFailedEvent: {
            "type",
            "request_id",
            "session_id",
            "client_message_id",
            "error",
        },
        ErrorEvent: {
            "type",
            "error",
            "request_id",
            "session_id",
            "client_message_id",
        },
    }
    for model, expected in expected_server_event_fields.items():
        assert frozenset(model.model_fields) == expected

    schema = TypeAdapter(ServerEvent).json_schema()
    assert set(schema["discriminator"]["mapping"]) == {
        "token",
        "message_completed",
        "message_failed",
        "error",
    }


def test_error_response_inherits_error_envelope_fields() -> None:
    assert frozenset(ErrorResponse.model_fields) == frozenset(
        ErrorEnvelope.model_fields
    )
    for name, envelope_field in ErrorEnvelope.model_fields.items():
        assert ErrorResponse.model_fields[name].annotation == envelope_field.annotation


def test_message_completed_event_rejects_inconsistent_nested_messages() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()
    now = datetime.now(UTC)
    user = MessageResponse(
        id=uuid4(),
        session_id=session_id,
        sequence=1,
        role="user",
        content="hello",
        created_at=now,
        client_message_id=client_message_id,
    )
    assistant = MessageResponse(
        id=uuid4(),
        session_id=session_id,
        sequence=2,
        role="assistant",
        content="hi",
        created_at=now,
        client_message_id=client_message_id,
    )
    base = {
        "type": "message_completed",
        "request_id": str(request_id),
        "session_id": str(session_id),
        "client_message_id": str(client_message_id),
        "user_message": user.model_dump(mode="json"),
        "assistant_message": assistant.model_dump(mode="json"),
    }
    assert MessageCompletedEvent.model_validate(base)

    bad_role = dict(base)
    bad_role["user_message"] = {**base["user_message"], "role": "assistant"}
    with pytest.raises(ValidationError):
        MessageCompletedEvent.model_validate(bad_role)

    bad_sequence = dict(base)
    bad_sequence["assistant_message"] = {
        **base["assistant_message"],
        "sequence": 5,
    }
    with pytest.raises(ValidationError):
        MessageCompletedEvent.model_validate(bad_sequence)

    bad_session = dict(base)
    bad_session["assistant_message"] = {
        **base["assistant_message"],
        "session_id": str(uuid4()),
    }
    with pytest.raises(ValidationError):
        MessageCompletedEvent.model_validate(bad_session)
