"""Deterministic console E2E workflow probes."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import socket
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest

from jung.api.server import running_local_api
from jung.client.api_client import ClientSettings, JungApiClient
from jung.client.console import ConsoleApp, ConsoleExitRequested
from jung.client.terminal import TerminalConsoleOutput, run_console
from jung.domain.models import OperationKind, OperationStatus, SessionKind
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult
from jung.phases.intake.extraction import IntakeExtraction
from tests.e2e.support import (
    ProbeRecorder,
    ScriptedInputProvider,
    assert_setup_timeline,
    assert_therapy_timeline,
)
from tests.integration.application.application_fixtures import (
    assessment_result,
    completing_intake_extraction,
    post_session_expectations,
)
from tests.support.api import application_factory, run_uvicorn_api
from tests.support.fake_llm import FakeLLM, StreamExpectation, StructuredExpectation

pytestmark = pytest.mark.asyncio

SCENARIO_TIMEOUT = 120.0
TURN_MESSAGES = ("first turn", "second turn", "third turn")
STYLE_ID = "cbt"


@pytest.fixture
def probe_root(tmp_path: Path) -> Path:
    configured = os.environ.get("PROBE_OUTPUT_DIR")
    if configured:
        return Path(configured)
    return tmp_path / "console-v1"


def _intake_expectations() -> list[StructuredExpectation | StreamExpectation]:
    expectations: list[StructuredExpectation | StreamExpectation] = []
    for index, content in enumerate(TURN_MESSAGES, start=1):
        if index < len(TURN_MESSAGES):
            expectations.extend(
                [
                    StructuredExpectation(
                        task=LLMTask.INTAKE_PATCH,
                        output_type=IntakeExtraction,
                        response=IntakeExtraction(),
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
                        output_type=IntakeExtraction,
                        response=completing_intake_extraction(
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


async def _assert_setup_ready_api(http_base: str) -> None:
    settings = ClientSettings(base_url=http_base)
    async with JungApiClient(settings) as client:
        snapshot = await client.get_state()
        assert snapshot.stage == "ready"
        assert snapshot.operation is None

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


def _assert_setup_ready_store(store: SQLiteStore) -> None:
    assessment_op = store.get_latest_completed_operation(OperationKind.ASSESSMENT)
    assert assessment_op is not None
    assert assessment_op.status is OperationStatus.COMPLETE


async def _assert_therapy_ready_api(
    http_base: str,
    *,
    recorder: ProbeRecorder,
) -> None:
    settings = ClientSettings(base_url=http_base)
    async with JungApiClient(settings) as client:
        snapshot = await client.get_state()
        assert snapshot.stage == "ready"
        assert snapshot.operation is None

        sessions = await client.list_sessions()
        therapy_sessions = [item for item in sessions if item.kind == "therapy"]
        assert len(therapy_sessions) == 1
        therapy_session = therapy_sessions[0]
        assert therapy_session.ended_at is not None

        history = await client.get_session(therapy_session.id)
        assert history.session.summary == "Patient explored sleep difficulties."
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

        pair = next(iter(grouped.values()))
        assert len(pair) == 2

        user_message, assistant_message = pair

        assert user_message.role == "user"
        assert assistant_message.role == "assistant"
        assert user_message.sequence < assistant_message.sequence
        assert user_message.content == "I slept badly again."
        assert assistant_message.content == "Let's explore that."

        intake_sessions = [item for item in sessions if item.kind == "intake"]
        assert intake_sessions

        recorder.set_transcript_from_histories(
            await client.get_session(intake_sessions[-1].id),
            history,
        )


def _assert_therapy_ready_store(store: SQLiteStore) -> None:
    therapy_sessions = [
        session
        for session in store.list_sessions()
        if session.kind is SessionKind.THERAPY
    ]
    assert len(therapy_sessions) == 1
    therapy_session = therapy_sessions[0]

    plans = store.list_plans_for_session(therapy_session.id)
    assert [plan.version for plan in plans] == [1, 2]

    initial_plan, revised_plan = plans

    assert revised_plan.supersedes_plan_id == initial_plan.id
    assert revised_plan.source_session_id == therapy_session.id
    assert revised_plan.current_progress == "some progress"

    current_plan = store.get_current_plan()
    assert current_plan is not None
    assert current_plan.id == revised_plan.id

    post_session_op = store.get_latest_completed_operation(OperationKind.POST_SESSION)
    assert post_session_op is not None
    assert post_session_op.status is OperationStatus.COMPLETE

    profile = store.get_profile()
    assert profile is not None

    grounded = store.list_grounded_patient_messages()
    assert grounded == [] or all(message.role.value == "user" for message in grounded)


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
    assert_api: Callable,
    assert_store: Callable[[], None],
    assert_timeline: Callable[[list], None],
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
            async with run_uvicorn_api(api_app) as http_base:
                try:
                    await _run_console(http_base, inputs, recorder)
                except ConsoleExitRequested:
                    pass

                await assert_api(http_base, recorder)

            assert_store()
            fake_llm.assert_exhausted()
            assert_timeline(recorder.timeline)
            assert recorder.durable_transcript
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
        await _assert_setup_ready_api(http_base)
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
        assert_store=lambda: _assert_setup_ready_store(store),
        assert_timeline=assert_setup_timeline,
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
        await _assert_therapy_ready_api(http_base, recorder=recorder)

    await _run_scenario(
        api_app=api_app,
        fake_llm=fake_llm,
        scenario_id="therapy_to_ready",
        inputs=_therapy_to_ready_inputs(),
        assert_api=assert_api,
        assert_store=lambda: _assert_therapy_ready_store(store),
        assert_timeline=assert_therapy_timeline,
        probe_root=probe_root,
    )


@pytest.mark.asyncio
async def test_managed_local_launcher_runs_console_over_http(
    store: SQLiteStore,
    fake_llm: FakeLLM,
    api_settings,
) -> None:
    """Managed path uses running_local_api + run_console over real HTTP."""
    async with running_local_api(
        api_settings,
        application_factory=application_factory(store, fake_llm),
    ) as base_url:
        exit_code = await run_console(
            ClientSettings(base_url=base_url),
            input_provider=ScriptedInputProvider.from_lines("/exit"),
        )
        assert exit_code == 0

        async with JungApiClient(ClientSettings(base_url=base_url)) as client:
            health = await client.get_health()
        assert health.status == "healthy"

    host, port_text = base_url.removeprefix("http://").split(":", 1)
    port = int(port_text)
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.2)
    try:
        assert probe.connect_ex((host, port)) != 0
    finally:
        probe.close()
