from __future__ import annotations

from uuid import uuid4

import pytest

from jung.api.contracts import (
    AppSnapshotResponse,
    MessageCompletedEvent,
    ProfileUpdateRequest,
    ProfileWire,
    SelectStyleRequest,
    TokenEvent,
)
from jung.client.api_client import (
    ClientSettings,
    JungApiClient,
    JungApiError,
)
from jung.llm.fake import FakeLLM
from jung.persistence.sqlite_store import SQLiteStore
from tests.integration.application.application_fixtures import (
    intake_message_expectations,
)
from tests.integration.application.assessment_test_data import assessment_result_data
from tests.integration.application.scenarios import (
    complete_intake_for_assessment,
    open_intake,
)

pytestmark = pytest.mark.asyncio


async def test_typed_reads_profile_update_and_session_history(
    uvicorn_api_url,
) -> None:
    http_base = uvicorn_api_url
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
    uvicorn_api_url,
) -> None:
    http_base = uvicorn_api_url
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
        await client.get_state()
        ready = await client.select_style(
            SelectStyleRequest(
                style_id="cbt",
            )
        )
        assert ready.stage == "ready"

        started = await client.start_session()
        assert started.snapshot.stage == "therapy"
        assert started.snapshot.active_session is not None

        ended = await client.end_session(
            started.session.id,
        )
        assert ended.stage == "post_session"


async def test_retry_current_operation_and_typed_not_found(
    store: SQLiteStore,
    uvicorn_api_url,
) -> None:
    http_base = uvicorn_api_url
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
        await client.get_state()
        retried = await client.retry_current_operation()
        assert retried.operation is not None
        assert retried.operation.id == operation_id

        with pytest.raises(JungApiError) as raised:
            await client.get_session(uuid4())
        assert raised.value.status == 404
        assert raised.value.code == "not_found"


async def test_one_shot_chat_stream_decodes_typed_events(
    uvicorn_api_url,
    fake_llm: FakeLLM,
) -> None:
    http_base = uvicorn_api_url
    fake_llm._expectations = list(intake_message_expectations("assistant reply"))

    async with JungApiClient(ClientSettings(http_base)) as client:
        state = await client.update_profile(
            ProfileUpdateRequest(
                profile=ProfileWire(name="Alex", primary_language="English"),
            )
        )
        assert state.active_session is not None
        session_id = state.active_session.id
        client_message_id = uuid4()
        request_id = uuid4()

        saw_token = False
        async with client.stream_message(
            session_id,
            "hello",
            client_message_id=client_message_id,
            request_id=request_id,
        ) as events:
            async for event in events:
                if isinstance(event, TokenEvent):
                    saw_token = True
                    assert event.session_id == session_id
                    assert event.client_message_id == client_message_id
                    assert event.request_id == request_id
                    continue
                if isinstance(event, MessageCompletedEvent):
                    assert event.assistant_message.content == "assistant reply"
                    assert event.client_message_id == client_message_id
                    break
            else:
                pytest.fail("expected MessageCompletedEvent")
        assert saw_token

        async with client.stream_message(
            session_id,
            "hello",
            client_message_id=client_message_id,
            request_id=uuid4(),
        ) as events:
            async for event in events:
                if isinstance(event, MessageCompletedEvent):
                    break
            else:
                pytest.fail("expected idempotent MessageCompletedEvent")
