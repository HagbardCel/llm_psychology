"""TherapyApplication chat acceptance and generation tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from jung.domain.commands import EndSession, SendMessage, StartSession, UpdateProfile
from jung.domain.errors import Busy, StoredWorkFailure
from jung.domain.models import ChatTurn, ChatTurnStatus, MessageRole, Profile, Stage
from jung.events import ChatTokenGenerated, ChatTurnAccepted, ChatTurnCompleted
from jung.llm.errors import LLMTimeout
from jung.llm.fake import (
    FailureExpectation,
    FakeLLM,
    StreamExpectation,
    StructuredExpectation,
)
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.intake.models import IntakeRecordPatch

from .application_fixtures import (
    ScriptedTaskSupervisor,
    build_test_application,
    intake_message_expectations,
    post_session_expectations,
    wait_for_chat_turn,
)
from .scenarios import advance_to_ready

pytestmark = pytest.mark.asyncio


async def test_submit_message_completes_intake_turn(store: SQLiteStore) -> None:
    fake = FakeLLM(
        intake_message_expectations("Welcome. Tell me what brings you here.")
    )
    async with build_test_application(store, fake) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session_id = (await runtime.application.get_snapshot()).active_session
        assert session_id is not None
        turn = await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session_id.id,
                client_message_id=uuid4(),
                content="I feel anxious.",
            )
        )
        completed = await wait_for_chat_turn(
            runtime.application,
            turn.id,
            ChatTurnStatus.COMPLETE,
        )
        snapshot = await runtime.application.get_snapshot()
    assert completed.status is ChatTurnStatus.COMPLETE
    assert snapshot.stage is Stage.INTAKE
    fake.assert_exhausted()


async def test_duplicate_client_message_id_returns_same_turn(store: SQLiteStore) -> None:
    fake = FakeLLM(intake_message_expectations("Welcome."))
    client_message_id = uuid4()
    async with build_test_application(store, fake) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session_id = (await runtime.application.get_snapshot()).active_session
        assert session_id is not None
        first = await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session_id.id,
                client_message_id=client_message_id,
                content="hello",
            )
        )
        duplicate = await runtime.application.submit_message(
            SendMessage(
                expected_revision=99,
                session_id=session_id.id,
                client_message_id=client_message_id,
                content="ignored",
            )
        )
        assert duplicate.id == first.id
        messages_before_completion = runtime.store.list_messages(session_id.id)
        await wait_for_chat_turn(
            runtime.application,
            first.id,
            ChatTurnStatus.COMPLETE,
        )
        messages = runtime.store.list_messages(session_id.id)
    assert len(messages_before_completion) == 1
    assert len(messages) == 2
    fake.assert_exhausted()


async def test_second_message_while_pending_raises_busy(store: SQLiteStore) -> None:
    gate = asyncio.Event()

    class HoldingFakeLLM(FakeLLM):
        async def stream_text(self, messages, policy):
            await gate.wait()
            async for chunk in super().stream_text(messages, policy):
                yield chunk

    fake = HoldingFakeLLM(intake_message_expectations("Welcome."))
    async with build_test_application(store, fake) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session_id = (await runtime.application.get_snapshot()).active_session
        assert session_id is not None
        await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session_id.id,
                client_message_id=uuid4(),
                content="first",
            )
        )
        with pytest.raises(Busy, match="another chat generation is active"):
            await runtime.application.submit_message(
                SendMessage(
                    expected_revision=(await runtime.application.get_snapshot()).revision,
                    session_id=session_id.id,
                    client_message_id=uuid4(),
                    content="second",
                )
            )
        gate.set()
        snapshot = await runtime.application.get_snapshot()
        assert snapshot.active_chat_turn is not None


async def test_chat_tokens_are_published_during_generation(store: SQLiteStore) -> None:
    fake = FakeLLM(
        [
            StreamExpectation(
                task=LLMTask.THERAPY_RESPONSE,
                chunks=("One ", "moment."),
            )
        ]
    )
    advance_to_ready(store)
    async with build_test_application(store, fake) as runtime:
        revision = (await runtime.application.get_snapshot()).revision
        session = await runtime.application.start_session(
            StartSession(expected_revision=revision)
        )
        collected: list[object] = []
        async with runtime.events.subscribe() as events:
            turn = await runtime.application.submit_message(
                SendMessage(
                    expected_revision=(await runtime.application.get_snapshot()).revision,
                    session_id=session.id,
                    client_message_id=uuid4(),
                    content="I need help sleeping.",
                )
            )

            async def _collect_until_complete() -> None:
                while True:
                    event = await asyncio.wait_for(events.__anext__(), timeout=1.0)
                    collected.append(event)
                    if isinstance(event, ChatTurnCompleted):
                        return

            await asyncio.wait_for(_collect_until_complete(), timeout=2.0)
        await wait_for_chat_turn(
            runtime.application,
            turn.id,
            ChatTurnStatus.COMPLETE,
        )
    accepted = next(item for item in collected if isinstance(item, ChatTurnAccepted))
    tokens = [item for item in collected if isinstance(item, ChatTokenGenerated)]
    completed = next(item for item in collected if isinstance(item, ChatTurnCompleted))
    assert accepted.turn_id == turn.id
    assert [token.sequence for token in tokens] == [1, 2]
    assert completed.turn_id == turn.id
    fake.assert_exhausted()


async def test_failed_chat_retry_uses_persisted_original_content(store: SQLiteStore) -> None:
    fake = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.INTAKE_PATCH,
                output_type=IntakeRecordPatch,
                response=IntakeRecordPatch(),
            ),
            FailureExpectation(task=LLMTask.INTAKE_RESPONSE, error=LLMTimeout("timeout")),
            *intake_message_expectations("Retry response."),
        ]
    )
    async with build_test_application(store, fake) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        active = (await runtime.application.get_snapshot()).active_session
        assert active is not None
        session_id = active.id
        client_message_id = uuid4()
        original_content = "original content"
        turn = await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session_id,
                client_message_id=client_message_id,
                content=original_content,
            )
        )
        await wait_for_chat_turn(
            runtime.application,
            turn.id,
            ChatTurnStatus.FAILED,
        )
        retried = await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session_id,
                client_message_id=client_message_id,
                content="retry",
            )
        )
        assert retried.id == turn.id
        completed = await wait_for_chat_turn(
            runtime.application,
            retried.id,
            ChatTurnStatus.COMPLETE,
        )
        messages = runtime.store.list_messages(session_id)
        user_messages = [message for message in messages if message.role is MessageRole.USER]
        assert len(user_messages) == 1
        assert user_messages[0].content == original_content
        assert completed.status is ChatTurnStatus.COMPLETE
    fake.assert_exhausted()


async def test_failed_chat_retry_after_closed_session_raises_stored_work_failure(
    store: SQLiteStore,
) -> None:
    advance_to_ready(store)
    fake = FakeLLM(
        [
            FailureExpectation(task=LLMTask.THERAPY_RESPONSE, error=LLMTimeout("timeout")),
            *post_session_expectations(),
        ]
    )
    async with build_test_application(store, fake) as runtime:
        revision = (await runtime.application.get_snapshot()).revision
        session = await runtime.application.start_session(
            StartSession(expected_revision=revision)
        )
        client_message_id = uuid4()
        turn = await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session.id,
                client_message_id=client_message_id,
                content="therapy original",
            )
        )
        await wait_for_chat_turn(
            runtime.application,
            turn.id,
            ChatTurnStatus.FAILED,
        )
        await runtime.application.end_session(
            EndSession(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session.id,
            )
        )
        with pytest.raises(StoredWorkFailure):
            await runtime.application.submit_message(
                SendMessage(
                    expected_revision=(await runtime.application.get_snapshot()).revision,
                    session_id=session.id,
                    client_message_id=client_message_id,
                    content="retry",
                )
            )
    fake.assert_exhausted()


async def test_failed_chat_retry_while_distinct_turn_pending_raises_busy(
    store: SQLiteStore,
) -> None:
    stream_gate = asyncio.Event()

    class HoldingFakeLLM(FakeLLM):
        def __init__(self, expectations: list[object]) -> None:
            super().__init__(expectations)
            self._stream_calls = 0

        async def stream_text(self, messages, policy):
            self._stream_calls += 1
            if self._stream_calls > 1:
                await stream_gate.wait()
            async for chunk in super().stream_text(messages, policy):
                yield chunk

    fake = HoldingFakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.INTAKE_PATCH,
                output_type=IntakeRecordPatch,
                response=IntakeRecordPatch(),
            ),
            FailureExpectation(task=LLMTask.INTAKE_RESPONSE, error=LLMTimeout("timeout")),
            StructuredExpectation(
                task=LLMTask.INTAKE_PATCH,
                output_type=IntakeRecordPatch,
                response=IntakeRecordPatch(),
            ),
            StreamExpectation(
                task=LLMTask.INTAKE_RESPONSE,
                chunks=("Second turn.",),
            ),
            *intake_message_expectations("Retry response."),
        ]
    )
    async with build_test_application(store, fake) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        active = (await runtime.application.get_snapshot()).active_session
        assert active is not None
        session_id = active.id
        failed_client_id = uuid4()
        turn_a = await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session_id,
                client_message_id=failed_client_id,
                content="failed turn",
            )
        )
        await wait_for_chat_turn(
            runtime.application,
            turn_a.id,
            ChatTurnStatus.FAILED,
        )
        await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session_id,
                client_message_id=uuid4(),
                content="distinct pending turn",
            )
        )
        snapshot = await runtime.application.get_snapshot()
        assert snapshot.active_chat_turn is not None
        with pytest.raises(Busy, match="another chat generation is active"):
            await runtime.application.submit_message(
                SendMessage(
                    expected_revision=snapshot.revision,
                    session_id=session_id,
                    client_message_id=failed_client_id,
                    content="retry failed turn",
                )
            )
        stream_gate.set()
        await wait_for_chat_turn(
            runtime.application,
            snapshot.active_chat_turn.id,
            ChatTurnStatus.COMPLETE,
        )


async def test_submit_message_cancel_during_store_call_drains_and_releases_lock(
    store: SQLiteStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    gate = threading.Event()
    release = threading.Event()
    original_accept = store.accept_chat_message

    def gated_accept(*args, **kwargs):
        gate.set()
        release.wait()
        return original_accept(*args, **kwargs)

    monkeypatch.setattr(store, "accept_chat_message", gated_accept)
    fake = FakeLLM(intake_message_expectations("Welcome."))
    async with build_test_application(store, fake) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session_id = (await runtime.application.get_snapshot()).active_session
        assert session_id is not None
        submit_task: asyncio.Task[ChatTurn] | None = None
        try:
            submit_task = asyncio.create_task(
                runtime.application.submit_message(
                    SendMessage(
                        expected_revision=(
                            await runtime.application.get_snapshot()
                        ).revision,
                        session_id=session_id.id,
                        client_message_id=uuid4(),
                        content="hello",
                    )
                )
            )
            assert await asyncio.to_thread(gate.wait, 2.0)
            submit_task.cancel()
            await asyncio.sleep(0)
            assert not submit_task.done()

            submit_task.cancel()
            await asyncio.sleep(0)
            assert not submit_task.done()

            release.set()
            with pytest.raises(asyncio.CancelledError):
                await submit_task
            assert not runtime.application._generation_lock.locked()
            active_turn = runtime.store.get_active_chat_turn()
            assert active_turn is not None
            assert active_turn.status is ChatTurnStatus.PENDING
        finally:
            release.set()
            if submit_task is not None:
                if not submit_task.done():
                    submit_task.cancel()
                await asyncio.gather(submit_task, return_exceptions=True)


async def test_submit_message_cancel_after_turn_assigned_worker_completes_and_releases_lock(
    store: SQLiteStore,
) -> None:
    assemble_entered = asyncio.Event()
    release_assemble = asyncio.Event()
    processor_entered = asyncio.Event()
    llm_gate = asyncio.Event()
    gate_next_assemble = False

    class GatedFakeLLM(FakeLLM):
        async def stream_text(self, messages, policy):
            processor_entered.set()
            await llm_gate.wait()
            async for chunk in super().stream_text(messages, policy):
                yield chunk

    fake = GatedFakeLLM(intake_message_expectations("Welcome."))
    async with build_test_application(store, fake) as runtime:
        original_assemble = runtime.application._assemble_snapshot_locked

        async def gated_assemble():
            nonlocal gate_next_assemble
            result = await original_assemble()
            if gate_next_assemble:
                gate_next_assemble = False
                assemble_entered.set()
                await release_assemble.wait()
            return result

        runtime.application._assemble_snapshot_locked = gated_assemble
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session_id = (await runtime.application.get_snapshot()).active_session
        assert session_id is not None
        revision = (await runtime.application.get_snapshot()).revision
        gate_next_assemble = True
        submit_task: asyncio.Task[ChatTurn] | None = None
        try:
            submit_task = asyncio.create_task(
                runtime.application.submit_message(
                    SendMessage(
                        expected_revision=revision,
                        session_id=session_id.id,
                        client_message_id=uuid4(),
                        content="hello",
                    )
                )
            )
            await asyncio.wait_for(assemble_entered.wait(), timeout=2.0)
            submit_task.cancel()
            release_assemble.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(submit_task, timeout=2.0)
            await asyncio.wait_for(processor_entered.wait(), timeout=2.0)
            active_turn = runtime.store.get_active_chat_turn()
            assert active_turn is not None
            llm_gate.set()
            completed = await wait_for_chat_turn(
                runtime.application,
                active_turn.id,
                ChatTurnStatus.COMPLETE,
            )
            assert completed.status is ChatTurnStatus.COMPLETE
            assert not runtime.application._generation_lock.locked()
        finally:
            release_assemble.set()
            llm_gate.set()
            if submit_task is not None:
                if not submit_task.done():
                    submit_task.cancel()
                await asyncio.gather(submit_task, return_exceptions=True)
    fake.assert_exhausted()


async def test_submit_message_cancel_during_accepted_event_publication(
    store: SQLiteStore,
) -> None:
    fake = FakeLLM(intake_message_expectations("Welcome."))
    publish_gate = asyncio.Event()
    release_publish = asyncio.Event()

    class GatedPublishEventStream:
        def __init__(self, inner) -> None:
            self._inner = inner

        async def publish(self, event) -> None:
            if isinstance(event, ChatTurnAccepted):
                publish_gate.set()
                await release_publish.wait()
            await self._inner.publish(event)

        def subscribe(self):
            return self._inner.subscribe()

    async with build_test_application(store, fake) as runtime:
        runtime.events = GatedPublishEventStream(runtime.events)
        runtime.application._events = runtime.events
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session_id = (await runtime.application.get_snapshot()).active_session
        assert session_id is not None
        submit_task = asyncio.create_task(
            runtime.application.submit_message(
                SendMessage(
                    expected_revision=(await runtime.application.get_snapshot()).revision,
                    session_id=session_id.id,
                    client_message_id=uuid4(),
                    content="hello",
                )
            )
        )
        await asyncio.wait_for(publish_gate.wait(), timeout=2.0)
        submit_task.cancel()
        release_publish.set()
        with pytest.raises(asyncio.CancelledError):
            await submit_task
        active_turn = runtime.store.get_active_chat_turn()
        assert active_turn is not None
        await wait_for_chat_turn(
            runtime.application,
            active_turn.id,
            ChatTurnStatus.COMPLETE,
        )
    fake.assert_exhausted()


async def test_chat_schedule_failure_returns_failed_turn(store: SQLiteStore) -> None:
    supervisor = ScriptedTaskSupervisor(by_name={"chat:*": [False]})
    fake = FakeLLM(intake_message_expectations("Welcome."))
    async with build_test_application(store, fake, supervisor=supervisor) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session_id = (await runtime.application.get_snapshot()).active_session
        assert session_id is not None
        turn = await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session_id.id,
                client_message_id=uuid4(),
                content="hello",
            )
        )
        assert turn.status is ChatTurnStatus.FAILED
        assert turn.retryable is True
        assert turn.error_code == "internal_error"
        snapshot = await runtime.application.get_snapshot()
        assert snapshot.active_chat_turn is None


async def test_publication_exception_still_schedules_chat(store: SQLiteStore) -> None:
    fake = FakeLLM(intake_message_expectations("Welcome."))

    class FailingPublishEventStream:
        def __init__(self, inner) -> None:
            self._inner = inner
            self._fail_once = True

        async def publish(self, event) -> None:
            if self._fail_once and isinstance(event, ChatTurnAccepted):
                self._fail_once = False
                raise RuntimeError("publish failed")
            await self._inner.publish(event)

        def subscribe(self):
            return self._inner.subscribe()

    async with build_test_application(store, fake) as runtime:
        runtime.events = FailingPublishEventStream(runtime.events)
        runtime.application._events = runtime.events
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session_id = (await runtime.application.get_snapshot()).active_session
        assert session_id is not None
        turn = await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session_id.id,
                client_message_id=uuid4(),
                content="hello",
            )
        )
        completed = await wait_for_chat_turn(
            runtime.application,
            turn.id,
            ChatTurnStatus.COMPLETE,
        )
    assert completed.status is ChatTurnStatus.COMPLETE
    fake.assert_exhausted()
