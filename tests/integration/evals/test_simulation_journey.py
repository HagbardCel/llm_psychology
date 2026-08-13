"""Deterministic FakeLLM integration for the simulation harness."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from evals.simulation.patient import PatientEvidence, PatientTurnContext
from evals.simulation.runner import SimulationConfig, run_simulation
from evals.simulation.scenarios import get_scenario
from jung.config import JungSettings
from jung.diagnostics import DiagnosticRecorder, snapshot_database
from jung.llm.errors import InvalidLLMOutput
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult
from jung.phases.intake.models import IntakeRecordPatch
from tests.integration.application.application_fixtures import (
    assessment_result,
    build_test_application,
    completing_intake_patch,
    post_session_expectations,
)
from tests.support.fake_llm import (
    FailureExpectation,
    FakeLLM,
    StreamExpectation,
    StructuredExpectation,
)
from tests.support.settings import make_test_settings

pytestmark = pytest.mark.asyncio

INTAKE_MESSAGES = ("first concern", "more detail", "final intake")
THERAPY_MESSAGES = ("I slept badly again.",)


@dataclass
class ScriptedPatient:
    """Deterministic patient actor for FakeLLM journeys."""

    utterances: list[str]

    async def generate(self, context: PatientTurnContext) -> PatientEvidence:
        del context
        if not self.utterances:
            raise AssertionError("ScriptedPatient exhausted")
        text = self.utterances.pop(0)
        return PatientEvidence(
            model="scripted",
            resolved_prompt="scripted",
            visible_history=(),
            raw_provider_text=text,
            submitted_text=text,
            finish_reason="stop",
            prompt_tokens=1,
            completion_tokens=1,
            latency_seconds=0.0,
        )

    async def aclose(self) -> None:
        return None


def _intake_expectations() -> list[StructuredExpectation | StreamExpectation]:
    expectations: list[StructuredExpectation | StreamExpectation] = []
    for index, content in enumerate(INTAKE_MESSAGES, start=1):
        if index < len(INTAKE_MESSAGES):
            expectations.extend(
                [
                    StructuredExpectation(
                        task=LLMTask.INTAKE_PATCH,
                        output_type=IntakeRecordPatch,
                        response=IntakeRecordPatch(),
                    ),
                    StreamExpectation(
                        task=LLMTask.INTAKE_RESPONSE,
                        chunks=(f"Intake response {index}.",),
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
                            message_sequence=5,
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


def _therapy_expectations(
    *,
    fail_post_session: bool = False,
) -> list[Any]:
    expectations: list[Any] = [
        *_intake_expectations(),
        StreamExpectation(
            task=LLMTask.THERAPY_RESPONSE,
            chunks=("Let's explore that.",),
        ),
    ]
    if fail_post_session:
        expectations.append(
            FailureExpectation(
                task=LLMTask.POST_SESSION_ANALYSIS,
                error=InvalidLLMOutput("forced post-session failure"),
            )
        )
    else:
        expectations.extend(post_session_expectations(patient_sequence=1))
    return expectations


def _simulation_application_factory(
    expectations: list[Any],
) -> Callable[[JungSettings], Any]:
    @asynccontextmanager
    async def factory(settings: JungSettings) -> AsyncIterator[Any]:
        assert settings.debug_run_dir is not None
        store = SQLiteStore(settings.database_path)
        store.initialize()
        fake_llm = FakeLLM(expectations)
        with DiagnosticRecorder(
            settings.debug_run_dir,
            secret_values=[],
        ) as recorder:
            async with build_test_application(
                store,
                fake_llm,
                recorder=recorder,
            ) as runtime:
                try:
                    yield runtime.application
                finally:
                    # build_test_application already shuts down the application.
                    pass
            try:
                snapshot_database(
                    store.database_path,
                    Path(settings.debug_run_dir) / "db_snapshot.sqlite",
                )
            except Exception:
                recorder.record(
                    "runtime.error",
                    {
                        "phase": "diagnostic_snapshot",
                        "error_type": "SnapshotError",
                        "error_message": "simulation test snapshot failed",
                    },
                )

    return factory


@pytest.fixture
def sim_settings(tmp_path: Path) -> JungSettings:
    # data_dir/debug_run_dir are overridden by the runner's isolated copy.
    return make_test_settings(
        data_dir=tmp_path / "unused-data",
        llm_base_url="http://fake.test/v1",
        llm_api_key="fake",
        model_name="fake",
    )


async def test_simulation_success_journey(
    tmp_path: Path,
    sim_settings: JungSettings,
) -> None:
    run_dir = tmp_path / "sim-success"
    patient = ScriptedPatient([*INTAKE_MESSAGES, *THERAPY_MESSAGES])
    result = await run_simulation(
        SimulationConfig(
            scenario=get_scenario("anxiety_sleep"),
            sessions=1,
            turns_per_session=1,
            max_intake_turns=5,
            output_dir=run_dir,
            require_provider_trace=False,
            workflow_timeout=30.0,
        ),
        settings=sim_settings,
        application_factory=_simulation_application_factory(_therapy_expectations()),
        patient_actor=patient,
        require_provider_trace=False,
    )
    assert result.status == "complete", (result.error_code, result.error_message)
    assert (run_dir / "run.json").is_file()
    run_payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_payload["status"] == "complete"
    assert run_payload["provider_trace_required"] is False
    journey_text = (run_dir / "journey.jsonl").read_text(encoding="utf-8")
    assert "simulation.completed" in journey_text
    assert "simulation.failed" not in journey_text
    assert (run_dir / "transcript.md").is_file()
    assert (run_dir / "audit.md").is_file()
    assert (run_dir / "runtime" / "trace.jsonl").is_file()
    assert (run_dir / "runtime" / "db_snapshot.sqlite").is_file()
    assert (run_dir / "checkpoints" / "initial-ready.sqlite").is_file()
    assert (run_dir / "checkpoints" / "after-session-001.sqlite").is_file()
    assert patient.utterances == []


async def test_simulation_intake_race_allows_style_selection(
    tmp_path: Path,
    sim_settings: JungSettings,
) -> None:
    """Fast assessment may finish before the first post-intake get_state()."""
    run_dir = tmp_path / "sim-race"
    patient = ScriptedPatient([*INTAKE_MESSAGES, *THERAPY_MESSAGES])
    result = await run_simulation(
        SimulationConfig(
            scenario=get_scenario("anxiety_sleep"),
            sessions=1,
            turns_per_session=1,
            max_intake_turns=5,
            output_dir=run_dir,
            require_provider_trace=False,
            workflow_timeout=30.0,
        ),
        settings=sim_settings,
        application_factory=_simulation_application_factory(_therapy_expectations()),
        patient_actor=patient,
        require_provider_trace=False,
    )
    assert result.status == "complete"
    assert patient.utterances == []


async def test_simulation_post_session_failure_preserves_evidence(
    tmp_path: Path,
    sim_settings: JungSettings,
) -> None:
    run_dir = tmp_path / "sim-fail"
    patient = ScriptedPatient([*INTAKE_MESSAGES, *THERAPY_MESSAGES])
    result = await run_simulation(
        SimulationConfig(
            scenario=get_scenario("anxiety_sleep"),
            sessions=1,
            turns_per_session=1,
            max_intake_turns=5,
            output_dir=run_dir,
            require_provider_trace=False,
            workflow_timeout=30.0,
        ),
        settings=sim_settings,
        application_factory=_simulation_application_factory(
            _therapy_expectations(fail_post_session=True)
        ),
        patient_actor=patient,
        require_provider_trace=False,
    )
    assert result.status == "failed"
    run_payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_payload["status"] == "failed"
    journey_text = (run_dir / "journey.jsonl").read_text(encoding="utf-8")
    assert "simulation.failed" in journey_text
    assert "simulation.completed" not in journey_text
    assert (run_dir / "checkpoints" / "initial-ready.sqlite").is_file()
    assert (run_dir / "audit.md").is_file()
    assert "FAILED" in (run_dir / "audit.md").read_text(encoding="utf-8")
