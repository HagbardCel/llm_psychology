"""Deterministic end-to-end console workflow probes for Phase 5 PR E."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path

import httpx
import pytest

from jung.client.api_client import ClientSettings, JungApiClient
from jung.client.console import ConsoleApp, ConsoleExitRequested, TerminalConsoleOutput
from jung.llm.fake import FakeLLM, StreamExpectation, StructuredExpectation
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult
from jung.phases.intake.models import IntakeRecordPatch
from tests.console_probe_support import ProbeRecorder, ScriptedInputProvider
from tests.integration.jung.application_fixtures import (
    assessment_result,
    completing_intake_patch,
    post_session_expectations,
)
from tests.jung_api_fixtures import run_uvicorn_api

pytestmark = pytest.mark.asyncio

SCENARIO_TIMEOUT = 120.0
PROBE_ROOT = Path(os.environ.get("PROBE_OUTPUT_DIR", "logs/workflow-probes")) / "phase-5-v1"
TURN_MESSAGES = ("first turn", "second turn", "third turn")
FINAL_MESSAGE_SEQUENCE = 5
STYLE_ID = "cbt"


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


async def _assert_setup_ready_api(http_base: str) -> None:
    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        state = (await client.get("/api/v1/state")).json()
        assert state["stage"] == "ready"
        styles = (await client.get("/api/v1/styles")).json()
        assert styles["styles"]
        profile = (await client.get("/api/v1/profile")).json()
        assert profile["profile"]["name"] == "Alex"
        sessions = (await client.get("/api/v1/sessions")).json()["sessions"]
        assert sessions


async def _assert_therapy_ready_api(http_base: str) -> None:
    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        state = (await client.get("/api/v1/state")).json()
        assert state["stage"] == "ready"
        assert state.get("operation") is None
        sessions = (await client.get("/api/v1/sessions")).json()["sessions"]
        therapy_sessions = [item for item in sessions if item["kind"] == "therapy"]
        assert therapy_sessions
        session_id = therapy_sessions[-1]["id"]
        detail = (await client.get(f"/api/v1/sessions/{session_id}")).json()
        assert detail["messages"]
        assert detail["session"].get("summary")
        assert detail["session"].get("briefing")
        profile = (await client.get("/api/v1/profile")).json()
        assert profile["current_plan"] is not None


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
) -> None:
    scenario_dir = PROBE_ROOT / scenario_id
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
                await assert_api(http_base)
        fake_llm.assert_exhausted()
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
        recorder.detach_server_logging()


@pytest.mark.parametrize(
    "fake_llm_expectations",
    [_intake_expectations()],
    indirect=True,
)
async def test_setup_to_ready_deterministic(
    api_app,
    fake_llm: FakeLLM,
) -> None:
    await _run_scenario(
        api_app=api_app,
        fake_llm=fake_llm,
        scenario_id="setup_to_ready",
        inputs=_setup_to_ready_inputs(),
        assert_api=_assert_setup_ready_api,
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
) -> None:
    await _run_scenario(
        api_app=api_app,
        fake_llm=fake_llm,
        scenario_id="therapy_to_ready",
        inputs=_therapy_to_ready_inputs(),
        assert_api=_assert_therapy_ready_api,
    )
    profile = store.get_profile()
    assert profile is not None
    assert profile.derived_profile is not None
    assert profile.derived_profile.get("observations")
