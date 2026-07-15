from __future__ import annotations

from uuid import uuid4

import pytest

from jung.api.contracts import (
    AppSnapshotResponse,
    EndSessionRequest,
    ErrorEvent,
    ProfileUpdateRequest,
    ProfileWire,
    RetryOperationRequest,
    SelectStyleRequest,
    StartSessionRequest,
)
from jung.client.api_client import (
    ChatReconciliationStatus,
    ClientSettings,
    JungApiClient,
    JungApiError,
)
from jung.llm.fake import FakeLLM
from jung.persistence.sqlite_store import SQLiteStore
from tests.integration.jung.application_fixtures import intake_message_expectations
from tests.integration.jung.assessment_test_data import assessment_result_data
from tests.integration.jung.scenarios import (
    complete_intake_for_assessment,
    open_intake,
)

pytestmark = pytest.mark.asyncio


async def test_typed_reads_profile_update_and_session_history(
    uvicorn_api_urls,
) -> None:
    http_base, _ws_url = uvicorn_api_urls
    async with JungApiClient(ClientSettings(http_base)) as client:
        initial = await client.get_state()
        profile = await client.get_profile()
        styles = await client.get_styles()
        sessions = await client.list_sessions()
        health = await client.get_health()

        assert initial.stage == "setup"
        assert profile.snapshot == initial
        assert styles.styles
        assert sessions == ()
        assert health.status == "healthy"

        updated = await client.update_profile(
            ProfileUpdateRequest(
                expected_revision=initial.revision,
                profile=ProfileWire(
                    name="Alex",
                    primary_language="English",
                ),
            )
        )
        assert isinstance(updated, AppSnapshotResponse)
        assert updated.stage == "intake"
        assert updated.active_session is not None

        listed = await client.list_sessions()
        history = await client.get_session(updated.active_session.id)
        assert listed[0].id == updated.active_session.id
        assert history.session.id == updated.active_session.id


async def test_select_style_start_and_end_methods_use_exact_contracts(
    store: SQLiteStore,
    uvicorn_api_urls,
) -> None:
    http_base, _ws_url = uvicorn_api_urls
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    store.complete_assessment(
        operation_id,
        result=assessment_result_data(),
        now=now,
    )

    async with JungApiClient(ClientSettings(http_base)) as client:
        selection_state = await client.get_state()
        ready = await client.select_style(
            SelectStyleRequest(
                expected_revision=selection_state.revision,
                style_id="cbt",
            )
        )
        assert ready.stage == "ready"

        started = await client.start_session(
            StartSessionRequest(expected_revision=ready.revision)
        )
        assert started.snapshot.stage == "therapy"
        assert started.snapshot.active_session is not None

        ended = await client.end_session(
            started.session.id,
            EndSessionRequest(expected_revision=started.snapshot.revision),
        )
        assert ended.stage == "post_session"


async def test_retry_current_operation_and_typed_not_found(
    store: SQLiteStore,
    uvicorn_api_urls,
) -> None:
    http_base, _ws_url = uvicorn_api_urls
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    store.fail_operation(
        operation_id,
        error_code="llm_timeout",
        error_message="Generation timed out",
        retryable=True,
        now=now,
    )

    async with JungApiClient(ClientSettings(http_base)) as client:
        failed = await client.get_state()
        retried = await client.retry_current_operation(
            RetryOperationRequest(expected_revision=failed.revision)
        )
        assert retried.operation is not None
        assert retried.operation.id == operation_id

        with pytest.raises(JungApiError) as raised:
            await client.get_session(uuid4())
        assert raised.value.status == 404
        assert raised.value.code == "not_found"


async def test_scoped_chat_decodes_typed_events_and_yields_server_errors(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, _ws_url = uvicorn_api_urls
    fake_llm._expectations = list(intake_message_expectations("assistant reply"))

    async with JungApiClient(ClientSettings(http_base)) as client:
        initial = await client.get_state()
        state = await client.update_profile(
            ProfileUpdateRequest(
                expected_revision=initial.revision,
                profile=ProfileWire(name="Alex", primary_language="English"),
            )
        )
        assert state.active_session is not None
        intent = client.new_chat_intent(state.active_session.id, "hello")
        stale = client.new_message_command(
            intent,
            expected_revision=state.revision - 1,
        )

        async with client.open_chat() as chat:
            await chat.send(stale)
            async for event in chat.events():
                if isinstance(event, ErrorEvent):
                    assert event.error.code == "state_conflict"
                    assert event.client_message_id == intent.client_message_id
                    break


async def test_reconcile_returns_complete_without_retransmission(
    store: SQLiteStore,
    uvicorn_api_urls,
) -> None:
    http_base, _ws_url = uvicorn_api_urls
    session_id, now = open_intake(store)
    client_message_id = uuid4()
    turn_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=turn_id,
        user_message_id=uuid4(),
        content="original",
        now=now,
    )
    store.complete_chat_turn(
        turn_id,
        assistant_message_id=uuid4(),
        content="reply",
        now=now,
    )

    async with JungApiClient(ClientSettings(http_base)) as client:
        intent = client.new_chat_intent(
            session_id,
            "original",
            client_message_id=client_message_id,
        )
        result = await client.reconcile_chat_turn(intent)

    assert result.status is ChatReconciliationStatus.COMPLETE
    assert result.completed_message is not None
    assert result.completed_message.content == "reply"


async def test_reconcile_detects_identity_conflict_before_retransmission(
    store: SQLiteStore,
    uvicorn_api_urls,
) -> None:
    http_base, _ws_url = uvicorn_api_urls
    session_id, now = open_intake(store)
    client_message_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=uuid4(),
        user_message_id=uuid4(),
        content="persisted content",
        now=now,
    )

    async with JungApiClient(ClientSettings(http_base)) as client:
        intent = client.new_chat_intent(
            session_id,
            "different retained content",
            client_message_id=client_message_id,
        )
        result = await client.reconcile_chat_turn(intent)

    assert result.status is ChatReconciliationStatus.IDENTITY_CONFLICT
    assert result.conflicting_user_message is not None
    assert result.conflicting_user_message.content == "persisted content"


async def test_reconcile_retransmits_once_and_refreshes_durable_state(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, _ws_url = uvicorn_api_urls
    fake_llm._expectations = list(intake_message_expectations("assistant reply"))

    async with JungApiClient(ClientSettings(http_base)) as client:
        initial = await client.get_state()
        state = await client.update_profile(
            ProfileUpdateRequest(
                expected_revision=initial.revision,
                profile=ProfileWire(name="Alex", primary_language="English"),
            )
        )
        assert state.active_session is not None
        intent = client.new_chat_intent(state.active_session.id, "hello")
        result = await client.reconcile_chat_turn(intent)

    assert result.status in {
        ChatReconciliationStatus.COMPLETE,
        ChatReconciliationStatus.IN_PROGRESS,
    }
    matching_users = [
        message
        for message in result.history.messages
        if message.role == "user"
        and message.client_message_id == intent.client_message_id
    ]
    assert len(matching_users) == 1
