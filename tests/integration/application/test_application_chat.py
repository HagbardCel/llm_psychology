"""TherapyApplication stream_message chat tests."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from jung.domain.commands import SendMessage, UpdateProfile
from jung.domain.errors import Busy, InvalidCommand
from jung.domain.models import CommandName, MessageRole, Profile, Stage
from jung.domain.results import ChatCompleted, ChatFailed, ChatStreamResult, ChatToken
from jung.llm.errors import LLMTimeout
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.intake.models import IntakeRecordPatch
from tests.support.fake_llm import (
    FailureExpectation,
    FakeLLM,
    StreamExpectation,
    StructuredExpectation,
)

from .application_fixtures import (
    build_test_application,
    completing_intake_patch,
    intake_message_expectations,
)

pytestmark = pytest.mark.asyncio


class _ListRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def record(self, kind: str, data: dict[str, Any] | None = None) -> None:
        self.events.append((kind, dict(data or {})))

    def next_id(self, prefix: str) -> str:
        return f"{prefix}-{len(self.events) + 1}"


async def collect_stream(app, command) -> list[ChatStreamResult]:
    items: list[ChatStreamResult] = []
    async for item in app.stream_message(command):
        items.append(item)
    return items


async def _open_intake(runtime) -> object:
    await runtime.application.update_profile(
        UpdateProfile(
            profile=Profile(name="Alex", primary_language="English"),
        )
    )
    session = (await runtime.application.get_snapshot()).active_session
    assert session is not None
    return session


async def test_stream_message_completes_intake_turn(store: SQLiteStore) -> None:
    fake = FakeLLM(
        intake_message_expectations("Welcome. Tell me what brings you here.")
    )
    async with build_test_application(store, fake) as runtime:
        session = await _open_intake(runtime)
        client_message_id = uuid4()
        items = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session.id,
                client_message_id=client_message_id,
                content="I feel anxious.",
            ),
        )
        snapshot = await runtime.application.get_snapshot()
    completed = [item for item in items if isinstance(item, ChatCompleted)]
    assert len(completed) == 1
    assert completed[0].user_message.role is MessageRole.USER
    assert completed[0].assistant_message.role is MessageRole.ASSISTANT
    assert completed[0].user_message.client_message_id == client_message_id
    assert completed[0].assistant_message.client_message_id == client_message_id
    assert snapshot.stage is Stage.INTAKE
    fake.assert_exhausted()


async def test_reuse_completed_pair_skips_llm(store: SQLiteStore) -> None:
    fake = FakeLLM(intake_message_expectations("Welcome."))
    client_message_id = uuid4()
    async with build_test_application(store, fake) as runtime:
        session = await _open_intake(runtime)
        first = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session.id,
                client_message_id=client_message_id,
                content="hello",
            ),
        )
        second = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session.id,
                client_message_id=client_message_id,
                content="hello",
            ),
        )
    assert isinstance(first[-1], ChatCompleted)
    assert isinstance(second[-1], ChatCompleted)
    assert second[-1].user_message.id == first[-1].user_message.id
    assert second[-1].assistant_message.id == first[-1].assistant_message.id
    assert not any(isinstance(item, ChatToken) for item in second)
    fake.assert_exhausted()


async def test_unanswered_user_blocks_different_client_message_id(
    store: SQLiteStore,
) -> None:
    gate = asyncio.Event()

    class HoldingFakeLLM(FakeLLM):
        async def stream_text(self, messages, policy):
            await gate.wait()
            async for chunk in super().stream_text(messages, policy):
                yield chunk

    fake = HoldingFakeLLM(intake_message_expectations("Welcome."))
    async with build_test_application(store, fake) as runtime:
        session = await _open_intake(runtime)
        first_task = asyncio.create_task(
            collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=uuid4(),
                    content="first",
                ),
            )
        )
        for _ in range(200):
            messages = store.list_messages(session.id)
            if messages and messages[-1].role is MessageRole.USER:
                break
            await asyncio.sleep(0.01)
        else:
            gate.set()
            await first_task
            raise AssertionError("user message was never persisted")

        with pytest.raises(
            InvalidCommand,
            match="retry the unanswered message before sending another",
        ):
            await collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=uuid4(),
                    content="second",
                ),
            )
        gate.set()
        await first_task
    fake.assert_exhausted()


async def test_unanswered_user_retry_same_id_and_content(store: SQLiteStore) -> None:
    fake = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.INTAKE_PATCH,
                output_type=IntakeRecordPatch,
                response=IntakeRecordPatch(),
            ),
            FailureExpectation(
                task=LLMTask.INTAKE_RESPONSE,
                error=LLMTimeout("stream failed"),
            ),
            *intake_message_expectations("Retry response."),
        ]
    )
    client_message_id = uuid4()
    content = "original content"
    async with build_test_application(store, fake) as runtime:
        session = await _open_intake(runtime)
        first = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session.id,
                client_message_id=client_message_id,
                content=content,
            ),
        )
        assert isinstance(first[-1], ChatFailed)
        user, assistant = store.get_messages_by_client_id(session.id, client_message_id)
        assert user is not None
        assert assistant is None

        second = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session.id,
                client_message_id=client_message_id,
                content=content,
            ),
        )
        assert isinstance(second[-1], ChatCompleted)
        assert second[-1].user_message.id == user.id
        messages = store.list_messages(session.id)
        assert len([m for m in messages if m.role is MessageRole.USER]) == 1
    fake.assert_exhausted()


async def test_content_mismatch_on_same_client_message_id_raises(
    store: SQLiteStore,
) -> None:
    fake = FakeLLM(intake_message_expectations("Welcome."))
    client_message_id = uuid4()
    async with build_test_application(store, fake) as runtime:
        session = await _open_intake(runtime)
        await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session.id,
                client_message_id=client_message_id,
                content="hello",
            ),
        )
        with pytest.raises(
            InvalidCommand,
            match="client_message_id already used with different content",
        ):
            await collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=client_message_id,
                    content="different",
                ),
            )
    fake.assert_exhausted()


async def test_generation_busy_when_another_stream_holds_lock(
    store: SQLiteStore,
) -> None:
    gate = asyncio.Event()

    class HoldingFakeLLM(FakeLLM):
        async def stream_text(self, messages, policy):
            await gate.wait()
            async for chunk in super().stream_text(messages, policy):
                yield chunk

    fake = HoldingFakeLLM(intake_message_expectations("Welcome."))
    async with build_test_application(store, fake) as runtime:
        session = await _open_intake(runtime)
        client_message_id = uuid4()
        content = "first"
        first_task = asyncio.create_task(
            collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=client_message_id,
                    content=content,
                ),
            )
        )
        for _ in range(200):
            user, assistant = store.get_messages_by_client_id(
                session.id, client_message_id
            )
            if user is not None and assistant is None:
                break
            await asyncio.sleep(0.01)
        else:
            gate.set()
            await first_task
            raise AssertionError("user message was never persisted")

        with pytest.raises(Busy, match="another chat generation is active"):
            await collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=client_message_id,
                    content=content,
                ),
            )
        gate.set()
        await first_task
    fake.assert_exhausted()


async def test_cancel_during_generation_leaves_user_without_assistant(
    store: SQLiteStore,
) -> None:
    gate = asyncio.Event()
    recorder = _ListRecorder()

    class HoldingFakeLLM(FakeLLM):
        async def stream_text(self, messages, policy):
            await gate.wait()
            async for chunk in super().stream_text(messages, policy):
                yield chunk

    fake = HoldingFakeLLM(intake_message_expectations("Welcome."))
    client_message_id = uuid4()
    async with build_test_application(store, fake, recorder=recorder) as runtime:
        session = await _open_intake(runtime)
        stream_task = asyncio.create_task(
            collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=client_message_id,
                    content="hello",
                ),
            )
        )
        for _ in range(200):
            user, _assistant = store.get_messages_by_client_id(
                session.id, client_message_id
            )
            if user is not None:
                break
            await asyncio.sleep(0.01)
        else:
            gate.set()
            await stream_task
            raise AssertionError("user message was never persisted")

        stream_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stream_task

        user, assistant = store.get_messages_by_client_id(session.id, client_message_id)
        assert user is not None
        assert assistant is None
        assert any(kind == "chat.turn.cancelled" for kind, _ in recorder.events)
        gate.set()


async def test_final_intake_advances_to_assessment(store: SQLiteStore) -> None:
    turn_messages = (
        "I have been anxious for months.",
        "Work stress and poor sleep are constant.",
        "I want help rebuilding a sleep routine.",
    )
    final_message_sequence = 5
    expectations: list[object] = []
    for index, content in enumerate(turn_messages, start=1):
        if index < len(turn_messages):
            expectations.extend(intake_message_expectations(f"Response {index}."))
        else:
            expectations.extend(
                [
                    StructuredExpectation(
                        task=LLMTask.INTAKE_PATCH,
                        output_type=IntakeRecordPatch,
                        response=completing_intake_patch(
                            message_sequence=final_message_sequence,
                            quote=content,
                        ),
                    ),
                    StreamExpectation(
                        task=LLMTask.INTAKE_RESPONSE,
                        chunks=("Thank you for sharing.",),
                    ),
                ]
            )
    fake = FakeLLM(expectations)
    async with build_test_application(store, fake) as runtime:
        session = await _open_intake(runtime)
        for content in turn_messages[:-1]:
            items = await collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=uuid4(),
                    content=content,
                ),
            )
            assert isinstance(items[-1], ChatCompleted)
        final_items = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session.id,
                client_message_id=uuid4(),
                content=turn_messages[-1],
            ),
        )
        snapshot = await runtime.application.get_snapshot()
    assert isinstance(final_items[-1], ChatCompleted)
    assert snapshot.stage is Stage.ASSESSMENT
    assert snapshot.current_operation is not None
    fake.assert_exhausted()


async def test_fresh_accept_persist_failure_releases_generation_lock(
    store: SQLiteStore,
) -> None:
    fake = FakeLLM(intake_message_expectations("Welcome after recovery."))
    async with build_test_application(store, fake) as runtime:
        session = await _open_intake(runtime)
        original_append = store.append_user_message

        def failing_append(**kwargs):
            raise RuntimeError("injected append failure")

        store.append_user_message = failing_append  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="injected append failure"):
            await collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=uuid4(),
                    content="hello",
                ),
            )
        assert store.list_messages(session.id) == []

        store.append_user_message = original_append  # type: ignore[method-assign]
        items = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session.id,
                client_message_id=uuid4(),
                content="hello again",
            ),
        )
        assert isinstance(items[-1], ChatCompleted)
    fake.assert_exhausted()


async def test_fresh_accept_cancelled_persist_releases_generation_lock(
    store: SQLiteStore,
) -> None:
    fake = FakeLLM(intake_message_expectations("Welcome after cancel."))
    async with build_test_application(store, fake) as runtime:
        session = await _open_intake(runtime)

        async def cancelled_persist(**kwargs):
            raise asyncio.CancelledError()

        runtime.application._chat._persist_user_message_drained = cancelled_persist  # type: ignore[method-assign]
        with pytest.raises(asyncio.CancelledError):
            await collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=uuid4(),
                    content="hello",
                ),
            )
        assert store.list_messages(session.id) == []

        del runtime.application._chat._persist_user_message_drained
        items = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session.id,
                client_message_id=uuid4(),
                content="hello again",
            ),
        )
        assert isinstance(items[-1], ChatCompleted)
    fake.assert_exhausted()


async def test_post_accept_busy_becomes_chat_failed_internal_error(
    store: SQLiteStore,
) -> None:
    recorder = _ListRecorder()
    fake = FakeLLM(intake_message_expectations("Welcome."))
    async with build_test_application(store, fake, recorder=recorder) as runtime:
        session = await _open_intake(runtime)
        original_complete = store.complete_chat_response

        def busy_complete(**kwargs):
            raise Busy("database is locked")

        store.complete_chat_response = busy_complete  # type: ignore[method-assign]
        client_message_id = uuid4()
        items = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session.id,
                client_message_id=client_message_id,
                content="hello",
            ),
        )
        assert isinstance(items[-1], ChatFailed)
        assert items[-1].code == "internal_error"
        user, assistant = store.get_messages_by_client_id(session.id, client_message_id)
        assert user is not None
        assert assistant is None
        kinds = [kind for kind, _ in recorder.events]
        assert "chat.turn.failed" in kinds
        assert "runtime.error" in kinds
        failed = next(
            data for kind, data in recorder.events if kind == "chat.turn.failed"
        )
        assert failed["source"] == "chat_attempt"
        assert failed["error_code"] == "internal_error"
        runtime_error = next(
            data for kind, data in recorder.events if kind == "runtime.error"
        )
        assert runtime_error["phase"] == "chat_attempt"
        assert "workflow.command.rejected" not in kinds

        store.complete_chat_response = original_complete  # type: ignore[method-assign]
        snapshot = await runtime.application.get_snapshot()
        assert CommandName.SEND_MESSAGE in snapshot.available_commands
