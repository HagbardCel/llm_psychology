"""Async fixture factory for TherapyApplication integration tests."""

from __future__ import annotations

import asyncio
import fnmatch
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import UUID, uuid4

from jung.application import TherapyApplication
from jung.domain.models import (
    ChatTurn,
    ChatTurnStatus,
    OperationStatus,
    PlanContent,
    Stage,
)
from jung.events import EventStream
from jung.llm.fake import FakeLLM, StreamExpectation, StructuredExpectation
from jung.llm.gateway import LLMSettings, LLMTask, ModelPolicy, StructuredOutputMode
from jung.llm.policies import build_model_policies
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult, StyleRecommendation
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
    DerivedProfilePatch,
    PlanPatch,
    PostSessionResult,
    SessionAnalysisResult,
    SessionBriefing,
)
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.therapy.processor import TherapyProcessor
from jung.styles import load_styles
from jung.supervisor import SupervisorClosed, TaskSupervisor

StartScript = bool | type[SupervisorClosed] | BaseException


def plan_content() -> PlanContent:
    return PlanContent(
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=["track sleep"],
    )


def assessment_result() -> AssessmentResult:
    return AssessmentResult(
        formulation="Anxiety presentation",
        presenting_concerns=("anxiety",),
        strengths_and_resources=("support",),
        style_recommendations=tuple(
            StyleRecommendation(
                style_id=style_id,
                score=0.9 if style_id == "cbt" else 0.5,
                rationale=f"Fit for {style_id}",
                key_topics=("anxiety",),
                initial_plan=plan_content(),
            )
            for style_id in ("jung", "cbt", "freud")
        ),
    )


def post_session_expectations() -> list[StreamExpectation | StructuredExpectation]:
    return [
        StructuredExpectation(
            task=LLMTask.POST_SESSION_ANALYSIS,
            output_type=SessionAnalysisResult,
            response=SessionAnalysisResult(
                summary="Patient explored sleep difficulties.",
                key_themes=("sleep",),
            ),
        ),
        StructuredExpectation(
            task=LLMTask.POST_SESSION_UPDATE,
            output_type=PostSessionResult,
            response=PostSessionResult(
                session_summary="Sleep remained difficult.",
                session_briefing=SessionBriefing(
                    narrative_handoff="Session focused on sleep.",
                    recommended_opening_focus="sleep routine",
                ),
                derived_profile_patch=DerivedProfilePatch(
                    observations=("reports poor sleep",)
                ),
                plan_patch=PlanPatch(current_progress="some progress"),
            ),
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


class ScriptedTaskSupervisor(TaskSupervisor):
    """Test supervisor that scripts ``start()`` outcomes by name or call order."""

    def __init__(
        self,
        *,
        by_name: Mapping[str, Sequence[StartScript]] | None = None,
        in_order: Sequence[StartScript] | None = None,
    ) -> None:
        super().__init__()
        self._by_name = {pattern: list(outcomes) for pattern, outcomes in (by_name or {}).items()}
        self._in_order = list(in_order or [])

    def start(
        self,
        *,
        name: str,
        run: Callable[[], Awaitable[None]],
    ) -> bool:
        outcome = self._next_outcome(name)
        if outcome is True:
            return super().start(name=name, run=run)
        if outcome is False:
            return False
        if outcome is SupervisorClosed or (
            isinstance(outcome, type) and issubclass(outcome, SupervisorClosed)
        ):
            raise SupervisorClosed(f"scripted supervisor closed for {name}")
        if isinstance(outcome, BaseException):
            raise outcome
        raise TypeError(f"unsupported scripted start outcome: {outcome!r}")

    def _next_outcome(self, name: str) -> StartScript:
        for pattern, outcomes in self._by_name.items():
            if fnmatch.fnmatch(name, pattern) and outcomes:
                return outcomes.pop(0)
        if self._in_order:
            return self._in_order.pop(0)
        return True


@dataclass
class TestApplicationRuntime:
    application: TherapyApplication
    events: EventStream
    supervisor: TaskSupervisor
    store: SQLiteStore
    fake_llm: FakeLLM


def _test_policies() -> dict[LLMTask, ModelPolicy]:
    return build_model_policies(
        LLMSettings(
            default_model="fake",
            base_url="http://fake.test",
            api_key="fake",
            task_structured_modes={
                LLMTask.INTAKE_PATCH: StructuredOutputMode.PROMPT,
                LLMTask.ASSESSMENT: StructuredOutputMode.PROMPT,
                LLMTask.POST_SESSION_ANALYSIS: StructuredOutputMode.PROMPT,
                LLMTask.POST_SESSION_UPDATE: StructuredOutputMode.PROMPT,
            },
        )
    )


def _build_processors(fake_llm: FakeLLM) -> tuple[
    IntakeProcessor,
    AssessmentProcessor,
    TherapyProcessor,
    PostSessionProcessor,
]:
    policies = _test_policies()
    return (
        IntakeProcessor(
            fake_llm,
            patch_policy=policies[LLMTask.INTAKE_PATCH],
            response_policy=policies[LLMTask.INTAKE_RESPONSE],
        ),
        AssessmentProcessor(
            fake_llm,
            assessment_policy=policies[LLMTask.ASSESSMENT],
        ),
        TherapyProcessor(
            fake_llm,
            response_policy=policies[LLMTask.THERAPY_RESPONSE],
        ),
        PostSessionProcessor(
            fake_llm,
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
    supervisor: TaskSupervisor | None = None,
) -> AsyncIterator[TestApplicationRuntime]:
    """Wire TherapyApplication with real store, processors, events, and supervisor."""
    intake, assessment, therapy, post_session = _build_processors(fake_llm)
    events = EventStream(max_queue_size=64)
    styles: MappingProxyType[str, object] = load_styles()
    clock = now or (lambda: datetime.now(UTC))
    ids = new_id or uuid4

    supervisor_instance = supervisor or TaskSupervisor()
    async with supervisor_instance as active_supervisor:
        application = TherapyApplication(
            store=store,
            intake=intake,
            assessment=assessment,
            therapy=therapy,
            post_session=post_session,
            styles=styles,
            events=events,
            supervisor=active_supervisor,
            now=clock,
            new_id=ids,
        )
        if recover:
            await application.recover_on_startup()
        runtime = TestApplicationRuntime(
            application=application,
            events=events,
            supervisor=active_supervisor,
            store=store,
            fake_llm=fake_llm,
        )
        try:
            yield runtime
        finally:
            application.begin_shutdown()
            await active_supervisor.shutdown(timeout_seconds=5.0)


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
    raise TimeoutError(f"timed out waiting for stage {stage.value}, got {snapshot.stage.value}")


async def wait_for_chat_turn(
    application: TherapyApplication,
    turn_id: UUID,
    status: ChatTurnStatus,
    *,
    timeout: float = 5.0,
) -> ChatTurn:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        turn = await application.get_chat_turn(turn_id)
        if turn.status is status:
            return turn
        await asyncio.sleep(0.01)
    turn = await application.get_chat_turn(turn_id)
    raise TimeoutError(
        f"timed out waiting for chat turn {turn_id} status {status.value}, got {turn.status.value}"
    )


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
    "ScriptedTaskSupervisor",
    "TestApplicationRuntime",
    "assessment_result",
    "build_test_application",
    "completing_intake_patch",
    "intake_message_expectations",
    "plan_content",
    "post_session_expectations",
    "wait_for_chat_turn",
    "wait_for_operation_status",
    "wait_for_stage",
]
