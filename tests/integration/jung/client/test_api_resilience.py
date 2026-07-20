"""Client-boundary resilience integration tests."""

from __future__ import annotations

import asyncio

import pytest

from jung.api.contracts import (
    MessageInProgressEvent,
    ProfileUpdateRequest,
    ProfileWire,
    TokenEvent,
)
from jung.client.api_client import (
    ChatReconciliationStatus,
    ClientSettings,
    JungApiClient,
)
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from tests.integration.jung.application_fixtures import intake_message_expectations
from tests.integration.jung.resilience_support import (
    receive_event,
    wait_for_health,
    wait_for_session_message,
)
from tests.jung_api_fixtures import (
    HoldingFakeLLM,
    RecordingFakeLLM,
    create_test_api_app,
    run_uvicorn_api,
)

pytestmark = pytest.mark.asyncio

EXPECTED_ASSISTANT_TEXT = "Welcome."


async def test_disconnect_during_generation_reconciles_without_duplicate_user_message(
    store: SQLiteStore,
) -> None:
    holding_fake = HoldingFakeLLM(
        intake_message_expectations(EXPECTED_ASSISTANT_TEXT),
    )
    recording_fake = RecordingFakeLLM(holding_fake)
    test_app = create_test_api_app(store=store, fake_llm=recording_fake)

    async with run_uvicorn_api(test_app.app) as (http_base, _ws_url):
        async with JungApiClient(ClientSettings(http_base)) as client:
            await wait_for_health(client)
            initial = await client.get_state()
            state = await client.update_profile(
                ProfileUpdateRequest(
                    expected_revision=initial.revision,
                    profile=ProfileWire(
                        name="Alex",
                        primary_language="English",
                    ),
                )
            )
            assert state.active_session is not None
            intent = client.new_chat_intent(
                state.active_session.id,
                "hello",
            )
            command = client.new_message_command(
                intent,
                expected_revision=state.revision,
            )
            accepted_snapshot = state

            try:
                async with client.open_chat() as connection:
                    event_stream = connection.events()
                    await connection.send(command)

                    acknowledgement = await receive_event(
                        event_stream,
                        MessageInProgressEvent,
                    )
                    assert (
                        acknowledgement.turn.client_message_id
                        == intent.client_message_id
                    )

                    accepted_snapshot = await client.get_state()
                    assert accepted_snapshot.active_chat_turn is not None
                    assert (
                        accepted_snapshot.active_chat_turn.client_message_id
                        == intent.client_message_id
                    )

                    token = await receive_event(
                        event_stream,
                        TokenEvent,
                        predicate=lambda event: event.request_id == command.request_id,
                    )
                    assert token.text

                    await asyncio.wait_for(
                        holding_fake.first_chunk_emitted.wait(),
                        timeout=5.0,
                    )

                in_progress = await client.reconcile_chat_turn(intent)
                assert in_progress.status is ChatReconciliationStatus.IN_PROGRESS

                holding_fake.release()

                assistant_message = await wait_for_session_message(
                    client,
                    session_id=intent.session_id,
                    client_message_id=intent.client_message_id,
                    role="assistant",
                )
                assert assistant_message.content == EXPECTED_ASSISTANT_TEXT

                session = await client.get_session(intent.session_id)
                matching_users = [
                    message
                    for message in session.messages
                    if message.role == "user"
                    and message.client_message_id == intent.client_message_id
                ]
                matching_assistants = [
                    message
                    for message in session.messages
                    if message.role == "assistant"
                    and message.client_message_id == intent.client_message_id
                ]
                assert len(matching_users) == 1
                assert len(matching_assistants) == 1
                assert matching_assistants[0].content == EXPECTED_ASSISTANT_TEXT

                complete = await client.reconcile_chat_turn(intent)
                assert complete.status is ChatReconciliationStatus.COMPLETE

                final_snapshot = await client.get_state()
                assert final_snapshot.active_chat_turn is None
                assert final_snapshot.revision > accepted_snapshot.revision
            finally:
                holding_fake.release()

    assert recording_fake.recorded_tasks == (
        LLMTask.INTAKE_PATCH,
        LLMTask.INTAKE_RESPONSE,
    )
    recording_fake.assert_exhausted()
