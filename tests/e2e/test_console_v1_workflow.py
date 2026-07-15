"""Deterministic end-to-end console workflow probes for Phase 5 PR E."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from collections import defaultdict
from pathlib import Path
from uuid import UUID

import pytest

from jung.client.api_client import ClientSettings, JungApiClient
from jung.client.console import ConsoleApp, ConsoleExitRequested, TerminalConsoleOutput
from jung.domain.models import OperationKind, OperationStatus
from jung.llm.fake import FakeLLM, StreamExpectation, StructuredExpectation
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult
from jung.phases.intake.models import IntakeRecordPatch
from tests.console_probe_support import (
    ProbeRecorder,
    ScriptedInputProvider,
    assert_successful_timeline,
)
from tests.integration.jung.application_fixtures import (
    assessment_result,
    completing_intake_patch,
    post_session_expectations,
)
from tests.jung_api_fixtures import run_uvicorn_api

pytestmark = pytest.mark.asyncio

SCENARIO_TIMEOUT = 120.0
TURN_MESSAGES = ("first turn", "second turn", "third turn")
FINAL_MESSAGE_SEQUENCE = 5
STYLE_ID = "cbt"


@pytest.fixture
def probe_root(tmp_path: Path) -> Path:
    configured = os.environ.get("PROBE_OUTPUT_DIR")
    if configured:
        return Path(configured)
    return tmp_path / "phase-5-v1"


def _intake_expectations() -> list[StructuredExpectation | StreamExpectation]:
    expectations: list[StructuredExpectation | StreamExpectation] = []
    for index, content in enumerate(TURN_MESSAGES, start=1):
        if index < len(TURN_MESSAGES):
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
                            message_sequence=FINAL_MESSAGE_SEQUENCE,
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
    return expectations


def _setup_to_ready_inputs() -> list[str]:
    return [
        "Alex",
        "English",
        *TURN_MESSAGES,
        STYLE_ID,
        "/exit",
    ]


def _therapy_to_ready_inputs() -> list[str]:
    return [
        "Alex",
        "English",
        *TURN_MESSAGES,
        STYLE_ID,
        "start",
        "I slept badly again.",
        "/quit",
    ]


def _therapy_expectations() -> list[StructuredExpectation | StreamExpectation]:
    return [
        *_intake_expectations(),
        StreamExpectation(
            task=LLMTask.THERAPY_RESPONSE,
            chunks=("Let's explore that.",),
        ),
        *post_session_expectations(),
    ]


def _group_messages_by_client_id(messages: list) -> dict[UUID, list]:
    grouped: dict[UUID, list] = defaultdict(list)
    for message in messages:
        if message.client_message_id is not None:
            grouped[message.client_message_id].append(message)
    return grouped


async def _assert_setup_ready_api(http_base: str, store: SQLiteStore) -> None:
    settings = ClientSettings(base_url=http_base)
    async with JungApiClient(settings) as client:
        snapshot = await client.get_state()
        assert snapshot.stage == "ready"
        assert snapshot.operation is None
        assert snapshot.active_chat_turn is None

        profile = await client.get_profile()
        assert profile.profile.name == "Alex"
        assert profile.profile.primary_language == "English"
        assert profile.current_plan is not None
        plan = profile.current_plan
        assert plan.selected_style == STYLE_ID
        assert plan.focus == "anxiety"
        assert plan.themes == ["worry"]
        assert plan.goals == ["sleep"]
        assert plan.current_progress == "baseline"

        styles = await client.get_styles()
        assert styles.recommendations

        sessions = await client.list_sessions()
        intake_sessions = [item for item in sessions if item.kind == "intake"]
        assert intake_sessions
        intake_session = intake_sessions[-1]
        history = await client.get_session(intake_session.id)
        assert history.session.ended_at is not None

        grouped = _group_messages_by_client_id(history.messages)
        assert len(grouped) == len(TURN_MESSAGES)
        for client_message_id, messages in grouped.items():
            assert [message.role for message in messages] == ["user", "assistant"]
            assert messages[0].sequence < messages[1].sequence
            del client_message_id

        user_messages = [
            message for message in history.messages if message.role == "user"
        ]
        assert len(user_messages) == len(TURN_MESSAGES)
        assert {message.content for message in user_messages} == set(TURN_MESSAGES)
        client_ids = [message.client_message_id for message in user_messages]
        assert len(client_ids) == len(set(client_ids))

    assessment_op = store.get_latest_completed_operation(OperationKind.ASSESSMENT)
    assert assessment_op is not None
    assert assessment_op.status is OperationStatus.COMPLETE


async def _assert_therapy_ready_api(
    http_base: str,
    store: SQLiteStore,
    *,
    recorder: ProbeRecorder,
) -> None:
    settings = ClientSettings(base_url=http_base)
    async with JungApiClient(settings) as client:
        snapshot = await client.get_state()
        assert snapshot.stage == "ready"
        assert snapshot.operation is None
        assert snapshot.active_chat_turn is None

        profile = await client.get_profile()
        assert profile.current_plan is not None
        plan = profile.current_plan
        assert plan.current_progress == "some progress"
        assert plan.version >= 2

        sessions = await client.list_sessions()
        therapy_sessions = [item for item in sessions if item.kind == "therapy"]
        assert len(therapy_sessions) == 1
        therapy_session = therapy_sessions[0]
        assert therapy_session.ended_at is not None

        history = await client.get_session(therapy_session.id)
        assert history.session.summary == "Sleep remained difficult."
        assert history.session.briefing is not None
        assert (
            history.session.briefing.get("narrative_handoff")
            == "Session focused on sleep."
        )

        therapy_messages = [
            message
            for message in history.messages
            if message.client_message_id is not None
        ]
        grouped = _group_messages_by_client_id(therapy_messages)
        assert len(grouped) == 1
        for client_message_id, messages in grouped.items():
            assert [message.role for message in messages] == ["user", "assistant"]
            assert messages[0].sequence < messages[1].sequence
            assert messages[0].content == "I slept badly again."
            del client_message_id

        intake_sessions = [item for item in sessions if item.kind == "intake"]
        assert intake_sessions
        assert plan.supersedes_plan_id is not None
        assert plan.source_session_id == therapy_session.id

        recorder.set_transcript_from_histories(
            await client.get_session(intake_sessions[-1].id),
            history,
        )

    post_session_op = store.get_latest_completed_operation(
        OperationKind.POST_SESSION
    )
    assert post_session_op is not None
    assert post_session_op.status is OperationStatus.COMPLETE

    profile = store.get_profile()
    assert profile is not None
    assert profile.derived_profile is not None
    assert profile.derived_profile.get("observations") == ["reports poor sleep"]


async def _run_console(
    http_base: str,
    inputs: list[str],
    recorder: ProbeRecorder,
) -> None:
    settings = ClientSettings(base_url=http_base)
    async with JungApiClient(settings) as client:
        await ConsoleApp(
            client=client,
            input=ScriptedInputProvider.from_lines(*inputs),
            output=TerminalConsoleOutput(),
            observer=recorder,
        ).run()


async def _run_scenario(
    *,
    api_app,
    fake_llm: FakeLLM,
    scenario_id: str,
    inputs: list[str],
    assert_api,
    probe_root: Path,
) -> ProbeRecorder:
    scenario_dir = probe_root / scenario_id
    if scenario_dir.exists():
        shutil.rmtree(scenario_dir)
    recorder = ProbeRecorder(scenario_id)
    recorder.attach_server_logging()
    failure: BaseException | None = None
    try:
        async with asyncio.timeout(SCENARIO_TIMEOUT):
            async with run_uvicorn_api(api_app) as (http_base, _ws_url):
                try:
                    await _run_console(http_base, inputs, recorder)
                except ConsoleExitRequested:
                    pass
                await assert_api(http_base, recorder)
        fake_llm.assert_exhausted()
        assert_successful_timeline(recorder.timeline)
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            recorder.write_artifacts(scenario_dir, failure=failure)
        except Exception:
            logging.exception("Failed to write probe artifacts")
            if failure is None:
                raise
        finally:
            recorder.detach_server_logging()
    assert failure is None
    assert not (scenario_dir / ProbeRecorder.FAILURE_ARTIFACT).exists()
    transcript = (scenario_dir / "transcript.md").read_text(encoding="utf-8")
    assert "_No transcript captured._" not in transcript
    return recorder


@pytest.mark.parametrize(
    "fake_llm_expectations",
    [_intake_expectations()],
    indirect=True,
)
async def test_setup_to_ready_deterministic(
    api_app,
    fake_llm: FakeLLM,
    store: SQLiteStore,
    probe_root: Path,
) -> None:
    async def assert_api(http_base: str, recorder: ProbeRecorder) -> None:
        await _assert_setup_ready_api(http_base, store)
        async with JungApiClient(ClientSettings(base_url=http_base)) as client:
            sessions = await client.list_sessions()
            intake_sessions = [item for item in sessions if item.kind == "intake"]
            history = await client.get_session(intake_sessions[-1].id)
        recorder.set_transcript_from_histories(history)

    await _run_scenario(
        api_app=api_app,
        fake_llm=fake_llm,
        scenario_id="setup_to_ready",
        inputs=_setup_to_ready_inputs(),
        assert_api=assert_api,
        probe_root=probe_root,
    )


@pytest.mark.parametrize(
    "fake_llm_expectations",
    [_therapy_expectations()],
    indirect=True,
)
async def test_therapy_to_ready_deterministic(
    api_app,
    fake_llm: FakeLLM,
    store: SQLiteStore,
    probe_root: Path,
) -> None:
    async def assert_api(http_base: str, recorder: ProbeRecorder) -> None:
        await _assert_therapy_ready_api(http_base, store, recorder=recorder)

    await _run_scenario(
        api_app=api_app,
        fake_llm=fake_llm,
        scenario_id="therapy_to_ready",
        inputs=_therapy_to_ready_inputs(),
        assert_api=assert_api,
        probe_root=probe_root,
    )
