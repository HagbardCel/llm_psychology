"""TherapyApplication chat acceptance and generation tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

import pytest

from jung.domain.commands import EndSession, SendMessage, StartSession, UpdateProfile
from jung.domain.errors import Busy, StoredWorkFailure
from jung.domain.models import ChatTurnStatus, MessageRole, Profile, Stage
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


@dataclass(frozen=True)
class _FailedChatRetryCase:
    id: str
    expect_busy: bool = False
    expect_stored_failure: bool = False


_FAILED_CHAT_RETRY_CASES = (
    _FailedChatRetryCase(id="valid_retry"),
    _FailedChatRetryCase(id="closed_session", expect_stored_failure=True),
    _FailedChatRetryCase(id="busy_during_retry", expect_busy=True),
    _FailedChatRetryCase(id="different_content_keeps_original"),
)


@pytest.mark.parametrize("case", _FAILED_CHAT_RETRY_CASES, ids=lambda case: case.id)
async def test_failed_chat_retry_matrix(
    store: SQLiteStore,
    case: _FailedChatRetryCase,
) -> None:
    retry_gate = asyncio.Event()

    class RetryMatrixFakeLLM(FakeLLM):
        def __init__(self, expectations: list[object]) -> None:
            super().__init__(expectations)
            self._stream_calls = 0

        async def stream_text(self, messages, policy):
            self._stream_calls += 1
            if case.id == "busy_during_retry" and self._stream_calls > 1:
                await retry_gate.wait()
            async for chunk in super().stream_text(messages, policy):
                yield chunk

    if case.id == "closed_session":
        advance_to_ready(store)
        expectations = [
            FailureExpectation(task=LLMTask.THERAPY_RESPONSE, error=LLMTimeout("timeout")),
            *post_session_expectations(),
        ]
    else:
        expectations = [
            StructuredExpectation(
                task=LLMTask.INTAKE_PATCH,
                output_type=IntakeRecordPatch,
                response=IntakeRecordPatch(),
            ),
            FailureExpectation(task=LLMTask.INTAKE_RESPONSE, error=LLMTimeout("timeout")),
            *intake_message_expectations("Retry response."),
        ]
    fake = RetryMatrixFakeLLM(expectations)
    async with build_test_application(store, fake) as runtime:
        if case.id == "closed_session":
            revision = (await runtime.application.get_snapshot()).revision
            session = await runtime.application.start_session(
                StartSession(expected_revision=revision)
            )
            session_id = session.id
            original_content = "therapy original"
        else:
            await runtime.application.update_profile(
                UpdateProfile(
                    expected_revision=0,
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
            active = (await runtime.application.get_snapshot()).active_session
            assert active is not None
            session_id = active.id
            original_content = "original content"

        client_message_id = uuid4()
        turn = await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session_id,
                client_message_id=client_message_id,
                content=original_content,
            )
        )
        failed = await wait_for_chat_turn(
            runtime.application,
            turn.id,
            ChatTurnStatus.FAILED,
        )
        assert failed.retryable is True

        if case.id == "closed_session":
            await runtime.application.end_session(
                EndSession(
                    expected_revision=(await runtime.application.get_snapshot()).revision,
                    session_id=session_id,
                )
            )
            with pytest.raises(StoredWorkFailure):
                await runtime.application.submit_message(
                    SendMessage(
                        expected_revision=(
                            await runtime.application.get_snapshot()
                        ).revision,
                        session_id=session_id,
                        client_message_id=client_message_id,
                        content="retry",
                    )
                )
            return

        if case.id == "busy_during_retry":
            retry_task = asyncio.create_task(
                runtime.application.submit_message(
                    SendMessage(
                        expected_revision=(
                            await runtime.application.get_snapshot()
                        ).revision,
                        session_id=session_id,
                        client_message_id=client_message_id,
                        content="retry",
                    )
                )
            )
            await asyncio.sleep(0.01)
            with pytest.raises(Busy, match="another chat generation is active"):
                await runtime.application.submit_message(
                    SendMessage(
                        expected_revision=(
                            await runtime.application.get_snapshot()
                        ).revision,
                        session_id=session_id,
                        client_message_id=uuid4(),
                        content="interrupt",
                    )
                )
            retry_gate.set()
            retried = await retry_task
            await wait_for_chat_turn(
                runtime.application,
                retried.id,
                ChatTurnStatus.COMPLETE,
            )
            return

        retry_content = (
            "different retry content" if case.id == "different_content_keeps_original" else "retry"
        )
        retried = await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session_id,
                client_message_id=client_message_id,
                content=retry_content,
            )
        )
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
