"""TherapyApplication session history consistency tests."""

from __future__ import annotations

import asyncio
import threading
from uuid import uuid4

import pytest

from jung.domain.commands import SendMessage
from jung.domain.models import MessageRole
from jung.llm.fake import FakeLLM, StreamExpectation
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore

from .application_fixtures import build_test_application
from .scenarios import advance_to_ready

pytestmark = pytest.mark.asyncio


async def test_get_session_history_is_consistent_under_concurrent_mutation(
    store: SQLiteStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        now=ready.now,
    )
    fake = FakeLLM(
        [
            StreamExpectation(
                task=LLMTask.THERAPY_RESPONSE,
                chunks=("Hello there.",),
            )
        ]
    )
    gate = threading.Event()
    proceed = threading.Event()
    original_list_messages = store.list_messages

    def gated_list_messages(session_id):
        gate.set()
        proceed.wait(timeout=2.0)
        return original_list_messages(session_id)

    monkeypatch.setattr(store, "list_messages", gated_list_messages)

    new_client_message_id = uuid4()
    new_content = "new message"

    async with build_test_application(store, fake) as runtime:
        mutation_started = asyncio.Event()

        async def mutate() -> None:
            mutation_started.set()
            await runtime.application.submit_message(
                SendMessage(
                    expected_revision=(await runtime.application.get_snapshot()).revision,
                    session_id=therapy_id,
                    client_message_id=new_client_message_id,
                    content=new_content,
                )
            )

        history_task = asyncio.create_task(
            runtime.application.get_session_history(therapy_id)
        )
        await asyncio.to_thread(gate.wait, 2.0)
        mutation_task = asyncio.create_task(mutate())
        await asyncio.wait_for(mutation_started.wait(), timeout=2.0)
        assert not mutation_task.done()
        assert not history_task.done()
        proceed.set()
        history = await history_task
        await mutation_task

        message_ids = {message.id for message in history.messages}
        assert len(message_ids) == len(history.messages)
        roles = {message.role for message in history.messages}
        assert roles <= {MessageRole.USER, MessageRole.ASSISTANT}
        assert all(message.content != new_content for message in history.messages)

        follow_up_history = await runtime.application.get_session_history(therapy_id)
        assert any(message.content == new_content for message in follow_up_history.messages)
