"""Production composition root for the target application core."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import UUID, uuid4

from jung._async_cleanup import drain_cancelled_task
from jung.application import TherapyApplication
from jung.config import ApplicationSettings
from jung.debug_bundle import (
    build_manifest_llm_info,
    finalize_debug_bundle,
    write_manifest,
)
from jung.diagnostics import (
    DiagnosticRecorder,
    DiagnosticRun,
    _safe_exception_message,
)
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
from jung.phases.post_session.models import (
    PostSessionUpdateResult,
    SessionAnalysisResult,
)
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.therapy.processor import TherapyProcessor
from jung.styles import load_styles
from jung.supervisor import TaskSupervisor

_ExcInfo = tuple[BaseException, TracebackType | None]

logger = logging.getLogger(__name__)


def _record_cleanup_failure(
    recorder: DiagnosticRecorder | None,
    *,
    step: str,
    exc: BaseException,
    selected_as_cleanup_error: bool,
    discovered_while_draining: bool = False,
) -> None:
    logger.warning(
        "runtime cleanup failed step=%s error_type=%s selected_as_cleanup_error=%s "
        "discovered_while_draining=%s",
        step,
        type(exc).__name__,
        selected_as_cleanup_error,
        discovered_while_draining,
    )
    if recorder is not None:
        recorder.record(
            "runtime.error",
            {
                "phase": f"cleanup:{step}",
                "error_type": type(exc).__name__,
                "error_message": _safe_exception_message(exc),
                "selected_as_cleanup_error": selected_as_cleanup_error,
                "discovered_while_draining": discovered_while_draining,
            },
        )


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
    LLMTask.POST_SESSION_UPDATE: PostSessionUpdateResult,
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


async def _drain_cleanup_step(
    awaitable: Awaitable[Any],
    *,
    on_drained_failure: Callable[[BaseException], None],
) -> Any:
    """Await cleanup work; record failures discovered while draining cancellation."""
    owned_failure: list[BaseException] = []

    async def _owned() -> Any:
        try:
            return await awaitable
        except BaseException as exc:
            owned_failure.append(exc)
            raise

    task = asyncio.ensure_future(_owned())
    caller = asyncio.current_task()
    cancels_before = caller.cancelling() if caller is not None else 0

    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as cancellation:
        cancels_after = caller.cancelling() if caller is not None else 0
        ambient_cancellation = cancels_after > cancels_before

        if not ambient_cancellation and task.done() and task.cancelled():
            # Cleanup operation itself was cancelled. Outer cleanup-precedence
            # classifies this once (selected_as_cleanup_error, not drained).
            if owned_failure:
                raise owned_failure[0] from None
            raise cancellation

        drained_failure = await drain_cancelled_task(task)
        if drained_failure is not None:
            on_drained_failure(drained_failure)

        raise cancellation


async def _cleanup_application_runtime(
    *,
    recorder: DiagnosticRecorder | None,
    llm: OpenAICompatibleLLM | None,
    supervisor: TaskSupervisor | None,
    supervisor_entered: bool,
    application: TherapyApplication | None,
    primary: _ExcInfo | None,
    cleanup_error: _ExcInfo | None,
    shutdown_timeout_seconds: float,
) -> tuple[_ExcInfo | None, _ExcInfo | None]:
    if application is not None:
        try:
            application.begin_shutdown()
        except BaseException as exc:
            selected_as_cleanup_error = _selected_cleanup_error(
                exc,
                primary=primary,
                cleanup_error=cleanup_error,
            )
            if selected_as_cleanup_error:
                cleanup_error = (exc, exc.__traceback__)
            _record_cleanup_failure(
                recorder,
                step="application.begin_shutdown",
                exc=exc,
                selected_as_cleanup_error=selected_as_cleanup_error,
            )

    if supervisor is not None:
        try:
            await _drain_cleanup_step(
                supervisor.shutdown(timeout_seconds=shutdown_timeout_seconds),
                on_drained_failure=lambda exc: _record_cleanup_failure(
                    recorder,
                    step="supervisor.shutdown",
                    exc=exc,
                    selected_as_cleanup_error=False,
                    discovered_while_draining=True,
                ),
            )
        except BaseException as exc:
            selected_as_cleanup_error = _selected_cleanup_error(
                exc,
                primary=primary,
                cleanup_error=cleanup_error,
            )
            if selected_as_cleanup_error:
                cleanup_error = (exc, exc.__traceback__)
            _record_cleanup_failure(
                recorder,
                step="supervisor.shutdown",
                exc=exc,
                selected_as_cleanup_error=selected_as_cleanup_error,
            )
        if supervisor_entered:
            try:
                await _drain_cleanup_step(
                    supervisor.__aexit__(None, None, None),
                    on_drained_failure=lambda exc: _record_cleanup_failure(
                        recorder,
                        step="supervisor.__aexit__",
                        exc=exc,
                        selected_as_cleanup_error=False,
                        discovered_while_draining=True,
                    ),
                )
            except BaseException as exc:
                selected_as_cleanup_error = _selected_cleanup_error(
                    exc,
                    primary=primary,
                    cleanup_error=cleanup_error,
                )
                if selected_as_cleanup_error:
                    cleanup_error = (exc, exc.__traceback__)
                _record_cleanup_failure(
                    recorder,
                    step="supervisor.__aexit__",
                    exc=exc,
                    selected_as_cleanup_error=selected_as_cleanup_error,
                )

    if llm is not None:
        try:
            await _drain_cleanup_step(
                llm.aclose(),
                on_drained_failure=lambda exc: _record_cleanup_failure(
                    recorder,
                    step="llm.aclose",
                    exc=exc,
                    selected_as_cleanup_error=False,
                    discovered_while_draining=True,
                ),
            )
        except BaseException as exc:
            selected_as_cleanup_error = _selected_cleanup_error(
                exc,
                primary=primary,
                cleanup_error=cleanup_error,
            )
            if selected_as_cleanup_error:
                cleanup_error = (exc, exc.__traceback__)
            _record_cleanup_failure(
                recorder,
                step="llm.aclose",
                exc=exc,
                selected_as_cleanup_error=selected_as_cleanup_error,
            )

    return primary, cleanup_error


def _selected_cleanup_error(
    exc: BaseException,
    *,
    primary: _ExcInfo | None,
    cleanup_error: _ExcInfo | None,
) -> bool:
    """Whether this failure should become the selected cleanup exception.

    Ambient cancellation during cleanup only becomes the selected cleanup error
    when there is no runtime primary and no earlier cleanup failure.
    """
    if isinstance(exc, asyncio.CancelledError):
        return primary is None and cleanup_error is None
    return cleanup_error is None


@asynccontextmanager
async def application_context(
    settings: ApplicationSettings,
    *,
    now: Callable[[], datetime] | None = None,
    new_id: Callable[[], UUID] | None = None,
    llm_factory: (
        Callable[[AdapterConfig, DiagnosticRecorder | None], OpenAICompatibleLLM] | None
    ) = None,
) -> AsyncIterator[ApplicationRuntime]:
    run_cm: Any
    if settings.debug_run_dir is not None:
        run_cm = DiagnosticRun(
            settings.debug_run_dir,
            secret_values=_secret_values(settings),
        )
    else:
        run_cm = nullcontext(None)

    with run_cm as recorder:
        store: SQLiteStore | None = None
        llm: OpenAICompatibleLLM | None = None
        supervisor: TaskSupervisor | None = None
        supervisor_entered = False
        application: TherapyApplication | None = None
        primary: _ExcInfo | None = None
        cleanup_error: _ExcInfo | None = None

        try:
            policies = build_model_policies(settings.llm)
            if recorder is not None:
                write_manifest(
                    recorder,
                    llm=build_manifest_llm_info(
                        provider_url=settings.llm.base_url,
                        policies=policies,
                    ),
                )
            _preflight_json_schema_policies(policies)
            store = SQLiteStore(settings.database_path)
            await asyncio.to_thread(store.initialize)
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

            gateway: OpenAICompatibleLLM | ObservedLLMGateway = llm
            if settings.enable_llm_tracing or recorder is not None:
                gateway = ObservedLLMGateway(
                    llm,
                    log_metadata=settings.enable_llm_tracing,
                    recorder=recorder,
                )

            styles = load_styles()
            events = EventStream(max_queue_size=settings.event_queue_size)
            supervisor = TaskSupervisor(recorder=recorder)
            await supervisor.__aenter__()
            supervisor_entered = True
            application = TherapyApplication(
                store=store,
                intake=IntakeProcessor(
                    gateway,
                    patch_policy=policies[LLMTask.INTAKE_PATCH],
                    response_policy=policies[LLMTask.INTAKE_RESPONSE],
                ),
                assessment=AssessmentProcessor(
                    gateway,
                    assessment_policy=policies[LLMTask.ASSESSMENT],
                ),
                therapy=TherapyProcessor(
                    gateway,
                    response_policy=policies[LLMTask.THERAPY_RESPONSE],
                ),
                post_session=PostSessionProcessor(
                    gateway,
                    analysis_policy=policies[LLMTask.POST_SESSION_ANALYSIS],
                    update_policy=policies[LLMTask.POST_SESSION_UPDATE],
                ),
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
            )
            try:
                yield runtime
            except BaseException as exc:
                primary = (exc, exc.__traceback__)
        except BaseException as exc:
            if primary is None:
                primary = (exc, exc.__traceback__)
        finally:
            primary, cleanup_error = await _cleanup_application_runtime(
                recorder=recorder,
                llm=llm,
                supervisor=supervisor,
                supervisor_entered=supervisor_entered,
                application=application,
                primary=primary,
                cleanup_error=cleanup_error,
                shutdown_timeout_seconds=settings.shutdown_timeout_seconds,
            )
            if recorder is not None and store is not None:
                finalize_debug_bundle(
                    recorder,
                    store,
                    primary_exception=primary[0] if primary is not None else None,
                    cleanup_exception=(
                        cleanup_error[0] if cleanup_error is not None else None
                    ),
                )

        if primary is not None:
            exc, tb = primary
            raise exc.with_traceback(tb)
        if cleanup_error is not None:
            exc, tb = cleanup_error
            raise exc.with_traceback(tb)
