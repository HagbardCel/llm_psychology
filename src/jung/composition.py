"""Production composition root for the target application core."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from jung.application import TherapyApplication
from jung.config import ApplicationSettings
from jung.events import EventStream
from jung.llm.gateway import AdapterConfig, LLMTask, ModelPolicy, StructuredOutputMode
from jung.llm.openai_compatible import OpenAICompatibleLLM
from jung.llm.policies import build_model_policies
from jung.llm.structured import response_format_for_mode
from jung.llm.tracing import TracingLLMGateway
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult
from jung.phases.assessment.processor import AssessmentProcessor
from jung.phases.intake.models import IntakeRecordPatch
from jung.phases.intake.processor import IntakeProcessor
from jung.phases.post_session.models import PostSessionResult, SessionAnalysisResult
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.therapy.processor import TherapyProcessor
from jung.styles import load_styles
from jung.supervisor import TaskSupervisor


@dataclass(frozen=True, slots=True)
class ApplicationRuntime:
    application: TherapyApplication
    events: EventStream
    supervisor: TaskSupervisor
    llm: OpenAICompatibleLLM


def _default_now() -> datetime:
    return datetime.now(UTC)


def _default_new_id() -> UUID:
    return uuid4()


_SCHEMA_OUTPUT_TYPES = {
    LLMTask.INTAKE_PATCH: IntakeRecordPatch,
    LLMTask.ASSESSMENT: AssessmentResult,
    LLMTask.POST_SESSION_ANALYSIS: SessionAnalysisResult,
    LLMTask.POST_SESSION_UPDATE: PostSessionResult,
}


def _preflight_json_schema_policies(
    policies: dict[LLMTask, ModelPolicy],
) -> None:
    for task, output_type in _SCHEMA_OUTPUT_TYPES.items():
        policy = policies[task]
        if policy.structured_output_mode is StructuredOutputMode.JSON_SCHEMA:
            response_format_for_mode(StructuredOutputMode.JSON_SCHEMA, output_type)


@asynccontextmanager
async def application_context(
    settings: ApplicationSettings,
    *,
    now: Callable[[], datetime] | None = None,
    new_id: Callable[[], UUID] | None = None,
) -> AsyncIterator[ApplicationRuntime]:
    store = SQLiteStore(settings.database_path)
    await asyncio.to_thread(store.initialize)

    policies = build_model_policies(settings.llm)
    _preflight_json_schema_policies(policies)
    adapter_config = AdapterConfig(
        base_url=settings.llm.base_url,
        api_key=settings.llm.api_key,
        default_headers=settings.llm.default_headers,
        extra_body=settings.llm.extra_body,
        task_extra_body=settings.llm.task_extra_body,
    )
    llm = OpenAICompatibleLLM(adapter_config)
    try:
        gateway: OpenAICompatibleLLM | TracingLLMGateway = llm
        if settings.enable_llm_tracing:
            gateway = TracingLLMGateway(
                llm,
                log_prompt_previews=settings.log_prompt_previews,
            )

        styles = load_styles()
        intake = IntakeProcessor(
            gateway,
            patch_policy=policies[LLMTask.INTAKE_PATCH],
            response_policy=policies[LLMTask.INTAKE_RESPONSE],
        )
        assessment = AssessmentProcessor(
            gateway,
            assessment_policy=policies[LLMTask.ASSESSMENT],
        )
        therapy = TherapyProcessor(
            gateway,
            response_policy=policies[LLMTask.THERAPY_RESPONSE],
        )
        post_session = PostSessionProcessor(
            gateway,
            analysis_policy=policies[LLMTask.POST_SESSION_ANALYSIS],
            update_policy=policies[LLMTask.POST_SESSION_UPDATE],
        )
        events = EventStream(max_queue_size=settings.event_queue_size)

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
                now=now or _default_now,
                new_id=new_id or _default_new_id,
            )
            await application.recover_on_startup()
            runtime = ApplicationRuntime(
                application=application,
                events=events,
                supervisor=supervisor,
                llm=llm,
            )
            try:
                yield runtime
            finally:
                application.begin_shutdown()
                await supervisor.shutdown(
                    timeout_seconds=settings.shutdown_timeout_seconds
                )
    finally:
        await llm.aclose()
