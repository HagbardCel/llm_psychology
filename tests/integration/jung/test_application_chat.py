"""TherapyApplication chat acceptance and generation tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from jung.domain.commands import SendMessage, StartSession, UpdateProfile
from jung.domain.errors import InvalidCommand
from jung.domain.models import ChatTurnStatus, Profile, Stage
from jung.events import ChatTokenGenerated, ChatTurnAccepted, ChatTurnCompleted
from jung.llm.fake import FakeLLM, StreamExpectation, StructuredExpectation
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.intake.models import IntakeRecordPatch

from .application_fixtures import build_test_application, wait_for_chat_turn
from .scenarios import advance_to_ready

pytestmark = pytest.mark.asyncio


def _intake_message_expectations(response: str) -> list[StructuredExpectation | StreamExpectation]:
    return [
        StructuredExpectation(
            task=LLMTask.INTAKE_PATCH,
            output_type=IntakeRecordPatch,
            response=IntakeRecordPatch(),
        ),
        StreamExpectation(
            task=LLMTask.INTAKE_RESPONSE,
            chunks=(response,),
        ),
    ]


async def test_submit_message_completes_intake_turn(store: SQLiteStore) -> None:
    fake = FakeLLM(
        _intake_message_expectations("Welcome. Tell me what brings you here.")
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
    fake = FakeLLM(_intake_message_expectations("Welcome."))
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


async def test_second_message_while_pending_is_rejected(store: SQLiteStore) -> None:
    gate = asyncio.Event()

    class HoldingFakeLLM(FakeLLM):
        async def stream_text(self, messages, policy):
            await gate.wait()
            async for chunk in super().stream_text(messages, policy):
                yield chunk

    fake = HoldingFakeLLM(_intake_message_expectations("Welcome."))
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
        with pytest.raises(InvalidCommand, match="send_message is not allowed"):
            await runtime.application.submit_message(
                SendMessage(
                    expected_revision=(await runtime.application.get_snapshot()).revision,
                    session_id=session_id.id,
                    client_message_id=uuid4(),
                    content="second",
                )
            )
        gate.set()
        await asyncio.sleep(0.05)


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
