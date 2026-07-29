"""Production composition root for the target application core."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from jung.application import TherapyApplication
from jung.config import ApplicationSettings
from jung.diagnostics import DiagnosticRecorder, DiagnosticRun, sanitize_url
from jung.events import EventStream
from jung.llm.gateway import AdapterConfig, LLMTask, ModelPolicy, StructuredOutputMode
from jung.llm.openai_compatible import OpenAICompatibleLLM
from jung.llm.policies import build_model_policies
from jung.llm.structured import response_format_for_mode
from jung.llm.tracing import ObservedLLMGateway
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
    recorder: DiagnosticRecorder | None = None


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


def _secret_values(settings: ApplicationSettings) -> list[str]:
    secrets = [settings.llm.api_key]
    if settings.llm.default_headers:
        secrets.extend(settings.llm.default_headers.values())
    return [value for value in secrets if value]


def _diagnostic_metadata(settings: ApplicationSettings) -> dict[str, Any]:
    policies = build_model_policies(settings.llm)
    return {
        "database_path": str(settings.database_path),
        "model": settings.llm.default_model,
        "provider_base_url": sanitize_url(settings.llm.base_url),
        "structured_output_modes": {
            task.value: policies[task].structured_output_mode.value for task in LLMTask
        },
        "timeouts_seconds": {
            task.value: policies[task].timeout_seconds for task in LLMTask
        },
        "max_completion_tokens": {
            task.value: policies[task].max_completion_tokens
            for task in LLMTask
            if policies[task].max_completion_tokens is not None
        },
    }


@asynccontextmanager
async def application_context(
    settings: ApplicationSettings,
    *,
    now: Callable[[], datetime] | None = None,
    new_id: Callable[[], UUID] | None = None,
    llm_factory: (
        Callable[[AdapterConfig, DiagnosticRecorder | None], OpenAICompatibleLLM]
        | None
    ) = None,
) -> AsyncIterator[ApplicationRuntime]:
    run_cm: Any
    if settings.debug_run_dir is not None:
        run_cm = DiagnosticRun(
            settings.debug_run_dir,
            metadata=_diagnostic_metadata(settings),
            secret_values=_secret_values(settings),
        )
    else:
        run_cm = nullcontext(None)

    with run_cm as recorder:
        store = SQLiteStore(settings.database_path, recorder=recorder)
        await asyncio.to_thread(store.initialize)
        if recorder is not None:
            await asyncio.to_thread(
                store.backup_to,
                recorder.artifact_path("database-start.sqlite"),
            )

        policies = build_model_policies(settings.llm)
        _preflight_json_schema_policies(policies)
        adapter_config = AdapterConfig(
            base_url=settings.llm.base_url,
            api_key=settings.llm.api_key,
            default_headers=settings.llm.default_headers,
            extra_body=settings.llm.extra_body,
            task_extra_body=settings.llm.task_extra_body,
        )
        if llm_factory is not None:
            llm = llm_factory(adapter_config, recorder)
        else:
            llm = OpenAICompatibleLLM(adapter_config, recorder=recorder)
        try:
            gateway: OpenAICompatibleLLM | ObservedLLMGateway = llm
            if settings.enable_llm_tracing or recorder is not None:
                gateway = ObservedLLMGateway(
                    llm,
                    log_metadata=settings.enable_llm_tracing,
                    recorder=recorder,
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
            events = EventStream(
                max_queue_size=settings.event_queue_size,
                recorder=recorder,
            )

            async with TaskSupervisor(recorder=recorder) as supervisor:
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
                    recorder=recorder,
                )
                await application.recover_on_startup()
                runtime = ApplicationRuntime(
                    application=application,
                    events=events,
                    supervisor=supervisor,
                    llm=llm,
                    recorder=recorder,
                )
                try:
                    yield runtime
                finally:
                    application.begin_shutdown()
                    await supervisor.shutdown(
                        timeout_seconds=settings.shutdown_timeout_seconds
                    )
                    if recorder is not None:
                        try:
                            await asyncio.to_thread(
                                store.backup_to,
                                recorder.artifact_path("database-end.sqlite"),
                            )
                        except Exception as exc:
                            recorder.capture_error(
                                "database-end snapshot failed",
                                exc,
                            )
        finally:
            await llm.aclose()
