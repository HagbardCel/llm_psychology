"""TherapyApplication workflow integration tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jung.domain.commands import (
    EndSession,
    SelectStyle,
    SendMessage,
    UpdateProfile,
)
from jung.domain.errors import InvalidCommand, NotFound
from jung.domain.models import (
    Profile,
    Stage,
)
from jung.domain.results import ChatCompleted
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult
from jung.phases.intake.models import IntakeRecordPatch
from tests.support.fake_llm import FakeLLM, StreamExpectation, StructuredExpectation

from .application_fixtures import (
    assessment_result,
    build_test_application,
    collect_stream,
    completing_intake_patch,
    post_session_expectations,
    wait_for_stage,
)
from .scenarios import advance_to_ready

pytestmark = pytest.mark.asyncio


async def test_start_session_returns_active_session_snapshot(
    store: SQLiteStore,
) -> None:
    advance_to_ready(store)
    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        started = await runtime.application.start_session()
        snapshot = await runtime.application.get_snapshot()

    assert started.snapshot == snapshot
    assert started.snapshot.active_session is not None
    assert started.snapshot.active_session.id == started.session.id
    assert started.snapshot.stage is Stage.THERAPY


async def test_start_session_when_not_ready_raises_invalid_command(
    store: SQLiteStore,
) -> None:
    async with build_test_application(store, FakeLLM([]), recover=False) as runtime:
        with pytest.raises(InvalidCommand, match="start_session is not allowed"):
            await runtime.application.start_session()
        snapshot = await runtime.application.get_snapshot()
        assert snapshot.stage is Stage.SETUP


async def test_sequential_profile_updates_latter_wins(store: SQLiteStore) -> None:
    async with build_test_application(store, FakeLLM([]), recover=False) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        await runtime.application.update_profile(
            UpdateProfile(
                profile=Profile(
                    name="Alexandra",
                    primary_language="English",
                    notes="updated",
                ),
            )
        )
        view = await runtime.application.get_profile()

    assert view.profile.name == "Alexandra"
    assert view.profile.notes == "updated"
    assert view.snapshot.stage is Stage.INTAKE


async def test_end_session_unknown_session_raises_not_found(store: SQLiteStore) -> None:
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(
        session_id=therapy_id,
        now=ready.now,
    )
    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        with pytest.raises(NotFound):
            await runtime.application.end_session(EndSession(session_id=uuid4()))


async def test_full_intake_lifecycle_through_application(store: SQLiteStore) -> None:
    turn_messages = ("first turn", "second turn", "third turn")
    final_message_sequence = 5
    expectations: list[StructuredExpectation | StreamExpectation] = []
    for index, content in enumerate(turn_messages, start=1):
        if index < len(turn_messages):
            expectations.extend(
                [
                    StructuredExpectation(
                        task=LLMTask.INTAKE_PATCH,
                        output_type=IntakeRecordPatch,
                        response=IntakeRecordPatch(),
                    ),
                    StreamExpectation(
                        task=LLMTask.INTAKE_RESPONSE,
                        chunks=(f"Response {index}.",),
                    ),
                ]
            )
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
    expectations.append(
        StructuredExpectation(
            task=LLMTask.ASSESSMENT,
            output_type=AssessmentResult,
            response=assessment_result(),
        )
    )
    fake = FakeLLM(expectations)
    async with build_test_application(store, fake) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session = (await runtime.application.get_snapshot()).active_session
        assert session is not None
        for content in turn_messages:
            items = await collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=uuid4(),
                    content=content,
                ),
            )
            assert isinstance(items[-1], ChatCompleted)
        await wait_for_stage(runtime.application, Stage.STYLE_SELECTION)
        snapshot = await runtime.application.select_style(SelectStyle(style_id="cbt"))
    assert snapshot.stage is Stage.READY
    fake.assert_exhausted()


async def test_therapy_to_post_session_application_journey(store: SQLiteStore) -> None:
    advance_to_ready(store)
    fake = FakeLLM(
        [
            StreamExpectation(
                task=LLMTask.THERAPY_RESPONSE,
                chunks=("Let's explore that.",),
            ),
            *post_session_expectations(),
        ]
    )
    async with build_test_application(store, fake) as runtime:
        started = await runtime.application.start_session()
        session = started.session
        items = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session.id,
                client_message_id=uuid4(),
                content="I slept badly again.",
            ),
        )
        assert isinstance(items[-1], ChatCompleted)
        snapshot = await runtime.application.end_session(
            EndSession(
                session_id=session.id,
            )
        )
        assert snapshot.stage is Stage.POST_SESSION
        assert snapshot.current_operation is not None
        await wait_for_stage(runtime.application, Stage.READY)
    fake.assert_exhausted()
