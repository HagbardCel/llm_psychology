"""Client-boundary resilience integration tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from jung.api.contracts import (
    MessageCompletedEvent,
    ProfileUpdateRequest,
    ProfileWire,
    TokenEvent,
)
from jung.client.api_client import ClientSettings, JungApiClient
from jung.llm.fake import FakeLLM
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from tests.integration.application.application_fixtures import (
    intake_message_expectations,
)
from tests.integration.resilience_support import wait_for_health
from tests.support.api import (
    HoldingFakeLLM,
    RecordingFakeLLM,
    create_test_api_app,
    run_uvicorn_api,
)

pytestmark = pytest.mark.asyncio

EXPECTED_ASSISTANT_TEXT = "Welcome."


async def test_disconnect_during_generation_leaves_unanswered_user_for_retry(
    store: SQLiteStore,
) -> None:
    holding_fake = HoldingFakeLLM(
        intake_message_expectations(EXPECTED_ASSISTANT_TEXT),
    )
    recording_fake = RecordingFakeLLM(holding_fake)
    test_app = create_test_api_app(store=store, fake_llm=recording_fake)

    async with run_uvicorn_api(test_app.app) as http_base:
        async with JungApiClient(ClientSettings(http_base)) as client:
            await wait_for_health(client)
            state = await client.update_profile(
                ProfileUpdateRequest(
                    profile=ProfileWire(
                        name="Alex",
                        primary_language="English",
                    ),
                )
            )
            assert state.active_session is not None
            session_id = state.active_session.id
            client_message_id = uuid4()
            request_id = uuid4()

            async with client.stream_message(
                session_id,
                "hello",
                client_message_id=client_message_id,
                request_id=request_id,
            ) as events:
                token = await anext(events)
                assert isinstance(token, TokenEvent)
                assert token.request_id == request_id
                await asyncio.wait_for(
                    holding_fake.first_chunk_emitted.wait(),
                    timeout=5.0,
                )
            # Client disconnect cancels generation; wait before releasing the hold.
            await asyncio.wait_for(holding_fake.stream_closed.wait(), timeout=5.0)
            holding_fake.release()

            await asyncio.sleep(0.2)
            session = await client.get_session(session_id)
            assert [message.role for message in session.messages] == ["user"]
            assert session.messages[0].client_message_id == client_message_id

            recording_fake._delegate = FakeLLM(
                list(intake_message_expectations(EXPECTED_ASSISTANT_TEXT))
            )
            async with client.stream_message(
                session_id,
                "hello",
                client_message_id=client_message_id,
                request_id=uuid4(),
            ) as events:
                collected = [event async for event in events]
            assert isinstance(collected[-1], MessageCompletedEvent)
            assert collected[-1].assistant_message.content == EXPECTED_ASSISTANT_TEXT

            final = await client.get_session(session_id)
            assert [message.role for message in final.messages] == ["user", "assistant"]
            assert (
                len(
                    [
                        message
                        for message in final.messages
                        if message.client_message_id == client_message_id
                    ]
                )
                == 2
            )

    assert recording_fake.recorded_tasks.count(LLMTask.INTAKE_RESPONSE) >= 1
    recording_fake.assert_exhausted()
