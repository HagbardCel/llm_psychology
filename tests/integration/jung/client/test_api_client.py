from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.api.contracts import (
    AppSnapshotResponse,
    EndSessionRequest,
    ErrorEvent,
    MessageInProgressEvent,
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
    JungConnectionClosed,
    JungTransportError,
)
from jung.llm.errors import LLMUnavailable
from jung.llm.fake import FailureExpectation, FakeLLM, StructuredExpectation
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.intake.models import IntakeRecordPatch
from tests.integration.jung.application_fixtures import intake_message_expectations
from tests.integration.jung.assessment_test_data import assessment_result_data
from tests.integration.jung.scenarios import (
    complete_intake_for_assessment,
    open_intake,
)

pytestmark = pytest.mark.asyncio


async def _wait_for_turn(
    store: SQLiteStore,
    *,
    session_id,
    client_message_id,
    timeout: float = 2.0,
) -> None:
    async with asyncio.timeout(timeout):
        while store.get_chat_turn_by_client_id(session_id, client_message_id) is None:
            await asyncio.sleep(0.01)


async def _wait_for_subscribers(runtime_probe, expected: int) -> None:
    async with asyncio.timeout(2.0):
        while (
            runtime_probe.runtime is None
            or len(runtime_probe.runtime.events._subscribers) < expected
        ):
            await asyncio.sleep(0.01)


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


async def test_reconcile_matches_durable_failure_with_remapped_request_id(
    store: SQLiteStore,
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, _ws_url = uvicorn_api_urls
    fake_llm._expectations = [
        StructuredExpectation(
            task=LLMTask.INTAKE_PATCH,
            output_type=IntakeRecordPatch,
            response=IntakeRecordPatch(),
        ),
        FailureExpectation(
            task=LLMTask.INTAKE_RESPONSE,
            error=LLMUnavailable("simulated unavailable provider"),
        ),
    ]

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
        sent_commands = []
        new_command = client.new_message_command
        real_open_chat = client.open_chat

        def record_command(*args, **kwargs):
            command = new_command(*args, **kwargs)
            sent_commands.append(command)
            return command

        client.new_message_command = record_command

        class FailureOnlyChat:
            def __init__(self, chat) -> None:
                self._chat = chat

            async def send(self, command) -> None:
                await self._chat.send(command)

            async def events(self):
                async for event in self._chat.events():
                    if not isinstance(event, MessageInProgressEvent):
                        yield event

            async def aclose(self) -> None:
                await self._chat.aclose()

        @asynccontextmanager
        async def open_failure_only_chat():
            async with real_open_chat() as chat:
                yield FailureOnlyChat(chat)

        client.open_chat = open_failure_only_chat
        result = await client.reconcile_chat_turn(intent)

    assert result.status is ChatReconciliationStatus.FAILED
    assert result.error_event is not None
    assert len(sent_commands) == 1
    assert result.error_event.request_id != sent_commands[0].request_id
    turn = store.get_chat_turn_by_client_id(
        intent.session_id,
        intent.client_message_id,
    )
    assert turn is not None
    assert result.error_event.turn_id == turn.id


@pytest.mark.parametrize(
    ("complete", "expected_status"),
    (
        (False, ChatReconciliationStatus.IN_PROGRESS),
        (True, ChatReconciliationStatus.COMPLETE),
    ),
)
async def test_reconcile_event_silent_duplicate_uses_final_http_refresh(
    store: SQLiteStore,
    uvicorn_api_urls,
    complete: bool,
    expected_status: ChatReconciliationStatus,
) -> None:
    http_base, _ws_url = uvicorn_api_urls

    async with JungApiClient(
        ClientSettings(http_base, acknowledgement_timeout=0.05)
    ) as client:
        initial = await client.get_state()
        state = await client.update_profile(
            ProfileUpdateRequest(
                expected_revision=initial.revision,
                profile=ProfileWire(name="Alex", primary_language="English"),
            )
        )
        assert state.active_session is not None
        intent = client.new_chat_intent(state.active_session.id, "hello")
        real_open_chat = client.open_chat
        sent_commands = []
        observed_events = []
        decisive_events = []
        acknowledgement_wait_cancelled = False

        class SeedBeforeSend:
            def __init__(self, chat) -> None:
                self._chat = chat
                self._command = None

            async def send(self, command) -> None:
                sent_commands.append(command)
                self._command = command
                turn_id = uuid4()
                user_message_id = uuid4()
                store.accept_chat_message(
                    expected_revision=command.expected_revision,
                    session_id=command.session_id,
                    client_message_id=command.client_message_id,
                    turn_id=turn_id,
                    user_message_id=user_message_id,
                    content=command.content,
                    now=datetime.now(UTC),
                )
                if complete:
                    store.complete_chat_turn(
                        turn_id,
                        assistant_message_id=uuid4(),
                        content="reply",
                        now=datetime.now(UTC),
                    )
                await self._chat.send(command)

            async def events(self):
                nonlocal acknowledgement_wait_cancelled
                try:
                    async for event in self._chat.events():
                        observed_events.append(event)
                        decisive, _error = client._match_decisive_event(
                            event,
                            intent=intent,
                            command=self._command,
                        )
                        if decisive:
                            decisive_events.append(event)
                        yield event
                except asyncio.CancelledError:
                    acknowledgement_wait_cancelled = True
                    raise

            async def aclose(self) -> None:
                await self._chat.aclose()

        @asynccontextmanager
        async def open_seeded_chat():
            async with real_open_chat() as chat:
                yield SeedBeforeSend(chat)

        client.open_chat = open_seeded_chat
        result = await client.reconcile_chat_turn(intent)

    assert result.status is expected_status
    assert len(sent_commands) == 1
    assert acknowledgement_wait_cancelled is True
    assert decisive_events == []
    assert all(event not in decisive_events for event in observed_events)
    matching_users = [
        message
        for message in result.history.messages
        if message.role == "user"
        and message.client_message_id == intent.client_message_id
    ]
    assert len(matching_users) == 1


async def test_reconcile_ignores_queued_unrelated_snapshot_event(
    runtime_probe,
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
        profile = await client.get_profile()
        subscriber_count = len(runtime_probe.runtime.events._subscribers)
        real_open_chat = client.open_chat
        queued_revision = None
        saw_queued_snapshot = False

        class TrackingChat:
            def __init__(self, chat) -> None:
                self._chat = chat

            async def send(self, command) -> None:
                await self._chat.send(command)

            async def events(self):
                nonlocal saw_queued_snapshot
                async for event in self._chat.events():
                    if (
                        event.type == "snapshot_changed"
                        and event.snapshot.revision == queued_revision
                    ):
                        saw_queued_snapshot = True
                    yield event

            async def aclose(self) -> None:
                await self._chat.aclose()

        @asynccontextmanager
        async def open_chat_with_queued_event():
            nonlocal queued_revision
            async with real_open_chat() as chat:
                await _wait_for_subscribers(runtime_probe, subscriber_count + 1)
                queued = await client.update_profile(
                    ProfileUpdateRequest(
                        expected_revision=profile.snapshot.revision,
                        profile=ProfileWire(
                            name=profile.profile.name,
                            primary_language=profile.profile.primary_language,
                            date_of_birth=profile.profile.date_of_birth,
                            notes="unrelated queued update",
                        ),
                    )
                )
                queued_revision = queued.revision
                yield TrackingChat(chat)

        client.open_chat = open_chat_with_queued_event
        result = await client.reconcile_chat_turn(intent)

    assert saw_queued_snapshot is True
    assert result.status in {
        ChatReconciliationStatus.COMPLETE,
        ChatReconciliationStatus.IN_PROGRESS,
    }


@pytest.mark.parametrize("outcome", ("closed", "timeout"))
async def test_reconcile_uses_final_http_refresh_after_confirmed_acceptance(
    outcome: str,
    store: SQLiteStore,
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, _ws_url = uvicorn_api_urls
    fake_llm._expectations = list(intake_message_expectations("assistant reply"))

    async with JungApiClient(
        ClientSettings(http_base, acknowledgement_timeout=0.05)
    ) as client:
        initial = await client.get_state()
        state = await client.update_profile(
            ProfileUpdateRequest(
                expected_revision=initial.revision,
                profile=ProfileWire(name="Alex", primary_language="English"),
            )
        )
        assert state.active_session is not None
        intent = client.new_chat_intent(state.active_session.id, "hello")
        real_open_chat = client.open_chat
        send_count = 0

        class AcceptedThenInterrupted:
            def __init__(self, chat) -> None:
                self._chat = chat

            async def send(self, command) -> None:
                nonlocal send_count
                send_count += 1
                await self._chat.send(command)
                await _wait_for_turn(
                    store,
                    session_id=command.session_id,
                    client_message_id=command.client_message_id,
                )

            async def events(self):
                if outcome == "closed":
                    raise JungConnectionClosed(code=1006, reason=None)
                await asyncio.sleep(1)
                if False:
                    yield None

            async def aclose(self) -> None:
                await self._chat.aclose()

        @asynccontextmanager
        async def open_interrupted_chat():
            async with real_open_chat() as chat:
                yield AcceptedThenInterrupted(chat)

        client.open_chat = open_interrupted_chat
        result = await client.reconcile_chat_turn(intent)

    assert send_count == 1
    assert result.status in {
        ChatReconciliationStatus.COMPLETE,
        ChatReconciliationStatus.IN_PROGRESS,
    }


@pytest.mark.parametrize(
    "failure",
    (
        JungConnectionClosed(code=1006, reason=None),
        JungTransportError("WebSocket send"),
    ),
)
async def test_reconcile_unresolved_when_send_never_delegates(
    failure,
    uvicorn_api_urls,
) -> None:
    http_base, _ws_url = uvicorn_api_urls

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
        real_open_chat = client.open_chat
        send_count = 0

        class FailingSend:
            async def send(self, _command) -> None:
                nonlocal send_count
                send_count += 1
                raise failure

            async def aclose(self) -> None:
                return None

        @asynccontextmanager
        async def open_failing_chat():
            async with real_open_chat():
                yield FailingSend()

        client.open_chat = open_failing_chat
        result = await client.reconcile_chat_turn(intent)

    assert send_count == 1
    assert result.status is ChatReconciliationStatus.UNRESOLVED


@pytest.mark.parametrize("retryable", (True, False))
async def test_reconcile_failed_duplicate_preserves_durable_identity(
    retryable: bool,
    store: SQLiteStore,
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, _ws_url = uvicorn_api_urls
    session_id, now = open_intake(store)
    client_message_id = uuid4()
    turn_id = uuid4()
    user_message_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=turn_id,
        user_message_id=user_message_id,
        content="hello",
        now=now,
    )
    store.fail_chat_turn(
        turn_id,
        error_code="llm_unavailable",
        error_message="stored failure",
        retryable=retryable,
        now=now,
    )
    if retryable:
        fake_llm._expectations = list(intake_message_expectations("recovered"))

    async with JungApiClient(ClientSettings(http_base)) as client:
        intent = client.new_chat_intent(
            session_id,
            "hello",
            client_message_id=client_message_id,
        )
        sent_commands = []
        real_open_chat = client.open_chat

        class TrackingChat:
            def __init__(self, chat) -> None:
                self._chat = chat

            async def send(self, command) -> None:
                sent_commands.append(command)
                await self._chat.send(command)

            def events(self):
                return self._chat.events()

            async def aclose(self) -> None:
                await self._chat.aclose()

        @asynccontextmanager
        async def open_tracking_chat():
            async with real_open_chat() as chat:
                yield TrackingChat(chat)

        client.open_chat = open_tracking_chat
        first = await client.reconcile_chat_turn(intent)
        second = await client.reconcile_chat_turn(intent) if retryable else None

    turn = store.get_chat_turn_by_client_id(session_id, client_message_id)
    assert turn is not None
    assert turn.id == turn_id
    assert turn.user_message_id == user_message_id
    assert len(sent_commands) == 1
    matching_users = [
        message
        for message in first.history.messages
        if message.role == "user" and message.client_message_id == client_message_id
    ]
    assert len(matching_users) == 1
    if retryable:
        assert first.status in {
            ChatReconciliationStatus.COMPLETE,
            ChatReconciliationStatus.IN_PROGRESS,
        }
        assert second is not None
        assert second.status in {
            ChatReconciliationStatus.COMPLETE,
            ChatReconciliationStatus.IN_PROGRESS,
        }
    else:
        assert first.status is ChatReconciliationStatus.FAILED
        assert first.error_event is not None
        assert first.error_event.error.code == "llm_unavailable"
        assert first.error_event.error.retryable is False
