"""Async fixture factory for TherapyApplication integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import UUID, uuid4

from jung.application import TherapyApplication
from jung.domain.commands import SendMessage
from jung.domain.models import (
    OperationStatus,
    Stage,
)
from jung.domain.results import ChatStreamResult
from jung.llm.gateway import LLMTask, ModelPolicy, StructuredOutputMode
from jung.llm.policies import TaskOverride, build_model_policies
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult
from jung.phases.assessment.processor import AssessmentProcessor
from jung.phases.intake.models import (
    CopingRecord,
    GoalsRecord,
    IntakeEvidence,
    IntakeRecordPatch,
    PresentingProblemRecord,
    SafetyRecord,
    TimeCourseRecord,
)
from jung.phases.intake.processor import IntakeProcessor
from jung.phases.post_session.models import (
    PatientTurnCitation,
    PlanPatch,
    PostSessionUpdateResult,
    SessionAnalysisResult,
    SessionBriefing,
)
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.therapy.processor import TherapyProcessor
from jung.styles import load_styles
from tests.support.fake_llm import FakeLLM, StreamExpectation, StructuredExpectation

from .assessment_test_data import assessment_result_data, plan_content


def assessment_result() -> AssessmentResult:
    return AssessmentResult.model_validate(assessment_result_data())


def post_session_expectations(
    *,
    patient_sequence: int | None = None,
    update_fragments: tuple[str, ...] = (),
) -> list[StreamExpectation | StructuredExpectation]:
    """Expectations for a conversational therapy transcript (user + assistant).

    Non-conversational sessions (empty, user-only, or assistant-only) take the
    deterministic zero-call path and must use ``FakeLLM([])`` instead.
    """
    citations = ()
    if patient_sequence is not None:
        citations = (PatientTurnCitation(patient_sequence=patient_sequence),)
    return [
        StructuredExpectation(
            task=LLMTask.POST_SESSION_ANALYSIS,
            output_type=SessionAnalysisResult,
            response=SessionAnalysisResult(
                summary="Patient explored sleep difficulties.",
                key_themes=("sleep",),
                patient_turn_citations=citations,
            ),
        ),
        StructuredExpectation(
            task=LLMTask.POST_SESSION_UPDATE,
            output_type=PostSessionUpdateResult,
            response=PostSessionUpdateResult(
                session_briefing=SessionBriefing(
                    narrative_handoff="Session focused on sleep.",
                    recommended_opening_focus="sleep routine",
                ),
                plan_patch=PlanPatch(current_progress="some progress"),
            ),
            message_fragments=update_fragments,
        ),
    ]


def intake_message_expectations(
    response: str,
) -> list[StructuredExpectation | StreamExpectation]:
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


def _intake_evidence(
    value: str,
    *,
    quote: str,
    sequence: int,
) -> IntakeEvidence:
    return IntakeEvidence(
        value=value,
        evidence_quote=quote,
        source_message_sequence=sequence,
        source_role="user",
        confidence="high",
    )


def completing_intake_patch(
    *,
    message_sequence: int,
    quote: str,
) -> IntakeRecordPatch:
    """Patch satisfying intake completion rules for the final patient turn."""

    def evidence(value: str) -> IntakeEvidence:
        return _intake_evidence(value, quote=quote, sequence=message_sequence)

    return IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            main_concern=evidence("anxiety"),
            time_course=TimeCourseRecord(
                duration_or_onset=evidence("3 months"),
            ),
            functional_impairment=evidence("work stress"),
            sleep_impact=evidence("poor sleep"),
        ),
        safety=SafetyRecord(
            self_harm=evidence("none"),
            harm_to_others=evidence("none"),
            medical_urgency=evidence("none"),
        ),
        coping=CopingRecord(
            attempted_strategies=(evidence("breathing exercises"),),
        ),
        goals=GoalsRecord(
            preferred_start=evidence("sleep routine"),
        ),
    )


@dataclass
class TestApplicationRuntime:
    application: TherapyApplication
    store: SQLiteStore
    fake_llm: FakeLLM


def _test_policies() -> dict[LLMTask, ModelPolicy]:
    return build_model_policies(
        session_model="fake",
        supervisor_model="fake",
        task_overrides={
            LLMTask.INTAKE_PATCH: TaskOverride(
                structured_output_mode=StructuredOutputMode.PROMPT,
            ),
            LLMTask.ASSESSMENT: TaskOverride(
                structured_output_mode=StructuredOutputMode.PROMPT,
            ),
            LLMTask.POST_SESSION_ANALYSIS: TaskOverride(
                structured_output_mode=StructuredOutputMode.PROMPT,
            ),
            LLMTask.POST_SESSION_UPDATE: TaskOverride(
                structured_output_mode=StructuredOutputMode.PROMPT,
            ),
        },
    )


def _build_processors(
    gateway: object,
) -> tuple[
    IntakeProcessor,
    AssessmentProcessor,
    TherapyProcessor,
    PostSessionProcessor,
]:
    policies = _test_policies()
    return (
        IntakeProcessor(
            gateway,  # type: ignore[arg-type]
            patch_policy=policies[LLMTask.INTAKE_PATCH],
            response_policy=policies[LLMTask.INTAKE_RESPONSE],
        ),
        AssessmentProcessor(
            gateway,  # type: ignore[arg-type]
            assessment_policy=policies[LLMTask.ASSESSMENT],
        ),
        TherapyProcessor(
            gateway,  # type: ignore[arg-type]
            response_policy=policies[LLMTask.THERAPY_RESPONSE],
        ),
        PostSessionProcessor(
            gateway,  # type: ignore[arg-type]
            analysis_policy=policies[LLMTask.POST_SESSION_ANALYSIS],
            update_policy=policies[LLMTask.POST_SESSION_UPDATE],
        ),
    )


@asynccontextmanager
async def build_test_application(
    store: SQLiteStore,
    fake_llm: FakeLLM,
    *,
    now: Callable[[], datetime] | None = None,
    new_id: Callable[[], UUID] | None = None,
    recover: bool = True,
    recorder: object | None = None,
) -> AsyncIterator[TestApplicationRuntime]:
    """Wire TherapyApplication with real store and processors."""
    from jung.llm.tracing import ObservedLLMGateway

    gateway: object = fake_llm
    if recorder is not None:
        gateway = ObservedLLMGateway(
            fake_llm,
            log_metadata=False,
            recorder=recorder,  # type: ignore[arg-type]
        )
    intake, assessment, therapy, post_session = _build_processors(gateway)  # type: ignore[arg-type]
    styles: MappingProxyType[str, object] = load_styles()
    clock = now or (lambda: datetime.now(UTC))
    ids = new_id or uuid4

    application = TherapyApplication(
        store=store,
        intake=intake,
        assessment=assessment,
        therapy=therapy,
        post_session=post_session,
        styles=styles,
        now=clock,
        new_id=ids,
        recorder=recorder,  # type: ignore[arg-type]
    )
    if recover:
        await application.recover_on_startup()
    runtime = TestApplicationRuntime(
        application=application,
        store=store,
        fake_llm=fake_llm,
    )
    try:
        yield runtime
    finally:
        await application.shutdown(timeout_seconds=5.0)


async def wait_for_stage(
    application: TherapyApplication,
    stage: Stage,
    *,
    timeout: float = 5.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        snapshot = await application.get_snapshot()
        if snapshot.stage is stage:
            return
        await asyncio.sleep(0.01)
    snapshot = await application.get_snapshot()
    raise TimeoutError(
        f"timed out waiting for stage {stage.value}, got {snapshot.stage.value}"
    )


async def wait_for_assistant_message(
    store: SQLiteStore,
    session_id: UUID,
    client_message_id: UUID,
    *,
    timeout: float = 5.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        _user, assistant = store.get_messages_by_client_id(
            session_id, client_message_id
        )
        if assistant is not None:
            return
        await asyncio.sleep(0.01)
    raise TimeoutError(f"timed out waiting for assistant message {client_message_id}")


async def collect_stream(
    application: TherapyApplication,
    command: SendMessage,
) -> list[ChatStreamResult]:
    items: list[ChatStreamResult] = []
    async for item in application.stream_message(command):
        items.append(item)
    return items


async def wait_for_operation_status(
    application: TherapyApplication,
    operation_id: UUID,
    status: OperationStatus,
    *,
    timeout: float = 5.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        snapshot = await application.get_snapshot()
        operation = snapshot.current_operation
        if (
            operation is not None
            and operation.id == operation_id
            and operation.status is status
        ):
            return
        await asyncio.sleep(0.01)
    snapshot = await application.get_snapshot()
    operation = snapshot.current_operation
    current = operation.status if operation is not None else None
    raise TimeoutError(
        f"timed out waiting for operation {operation_id} status {status.value}, got {current}"
    )


__all__ = [
    "TestApplicationRuntime",
    "assessment_result",
    "build_test_application",
    "collect_stream",
    "completing_intake_patch",
    "intake_message_expectations",
    "plan_content",
    "post_session_expectations",
    "wait_for_assistant_message",
    "wait_for_operation_status",
    "wait_for_stage",
]
