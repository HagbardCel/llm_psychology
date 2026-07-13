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
from jung.domain.models import ChatTurn, ChatTurnStatus, OperationStatus, Stage
from jung.events import EventStream
from jung.llm.fake import FakeLLM
from jung.llm.gateway import LLMSettings, LLMTask, ModelPolicy, StructuredOutputMode
from jung.llm.policies import build_model_policies
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.processor import AssessmentProcessor
from jung.phases.intake.processor import IntakeProcessor
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.therapy.processor import TherapyProcessor
from jung.styles import load_styles
from jung.supervisor import TaskSupervisor


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
) -> AsyncIterator[TestApplicationRuntime]:
    """Wire TherapyApplication with real store, processors, events, and supervisor."""
    intake, assessment, therapy, post_session = _build_processors(fake_llm)
    events = EventStream(max_queue_size=64)
    styles: MappingProxyType[str, object] = load_styles()
    clock = now or (lambda: datetime.now(UTC))
    ids = new_id or uuid4

    async with TaskSupervisor() as supervisor:
        application = TherapyApplication(
            store=store,
            intake=intake,
            assessment=assessment,
            therapy=therapy,
            post_session=post_session,
            styles=styles,
            events=events,
            supervisor=supervisor,
            now=clock,
            new_id=ids,
        )
        if recover:
            await application.recover_on_startup()
        runtime = TestApplicationRuntime(
            application=application,
            events=events,
            supervisor=supervisor,
            store=store,
            fake_llm=fake_llm,
        )
        try:
            yield runtime
        finally:
            application.begin_shutdown()
            await supervisor.shutdown(timeout_seconds=5.0)


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
