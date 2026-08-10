"""Production composition root for the target application core."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, nullcontext
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import UUID, uuid4

from jung._async_cleanup import drain_cancelled_task
from jung.application import TherapyApplication
from jung.config import JungSettings
from jung.diagnostics import (
    DiagnosticRecorder,
    _safe_exception_message,
    snapshot_database,
)
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


def _secret_values(settings: JungSettings) -> list[str]:
    secrets = [settings.llm_api_key]
    if settings.llm_default_headers:
        secrets.extend(settings.llm_default_headers.values())
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
    application: TherapyApplication | None,
    primary: _ExcInfo | None,
    cleanup_error: _ExcInfo | None,
    shutdown_timeout_seconds: float,
) -> tuple[_ExcInfo | None, _ExcInfo | None]:
    if application is not None:
        try:
            await _drain_cleanup_step(
                application.shutdown(timeout_seconds=shutdown_timeout_seconds),
                on_drained_failure=lambda exc: _record_cleanup_failure(
                    recorder,
                    step="application.shutdown",
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
                step="application.shutdown",
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
    settings: JungSettings,
    *,
    now: Callable[[], datetime] | None = None,
    new_id: Callable[[], UUID] | None = None,
    llm_factory: (
        Callable[[AdapterConfig, DiagnosticRecorder | None], OpenAICompatibleLLM] | None
    ) = None,
) -> AsyncIterator[TherapyApplication]:
    run_cm: Any
    if settings.debug_run_dir is not None:
        run_cm = DiagnosticRecorder(
            settings.debug_run_dir,
            secret_values=_secret_values(settings),
        )
    else:
        run_cm = nullcontext(None)

    with run_cm as recorder:
        store: SQLiteStore | None = None
        store_initialized = False
        llm: OpenAICompatibleLLM | None = None
        application: TherapyApplication | None = None
        primary: _ExcInfo | None = None
        cleanup_error: _ExcInfo | None = None

        try:
            policies = build_model_policies(
                default_model=settings.model_name,
                task_overrides=settings.llm_task_config,
            )
            _preflight_json_schema_policies(policies)
            store = SQLiteStore(settings.database_path)
            await asyncio.to_thread(store.initialize)
            store_initialized = True
            task_extra_body = {
                task: override.extra_body
                for task, override in settings.llm_task_config.items()
                if override.extra_body
            }
            adapter_config = AdapterConfig(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                default_headers=settings.llm_default_headers,
                extra_body=settings.llm_extra_body,
                task_extra_body=task_extra_body or None,
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
                now=now or _default_now,
                new_id=new_id or _default_new_id,
                recorder=recorder,
            )
            await application.recover_on_startup()
            try:
                yield application
            except BaseException as exc:
                primary = (exc, exc.__traceback__)
        except BaseException as exc:
            if primary is None:
                primary = (exc, exc.__traceback__)
        finally:
            primary, cleanup_error = await _cleanup_application_runtime(
                recorder=recorder,
                llm=llm,
                application=application,
                primary=primary,
                cleanup_error=cleanup_error,
                shutdown_timeout_seconds=settings.shutdown_timeout_seconds,
            )
            if recorder is not None and store is not None and store_initialized:
                try:
                    # Synchronous by design: shutdown-only; avoid to_thread
                    # cancellation complexity.
                    snapshot_database(
                        store.database_path,
                        recorder.run_dir / "db_snapshot.sqlite",
                    )
                except Exception as exc:
                    message = _safe_exception_message(exc)
                    recorder.record(
                        "runtime.error",
                        {
                            "phase": "diagnostic_snapshot",
                            "error_type": type(exc).__name__,
                            "error_message": message,
                        },
                    )
                    logger.warning(
                        "diagnostic snapshot failed error_type=%s error=%s",
                        type(exc).__name__,
                        message,
                    )

        if primary is not None:
            exc, tb = primary
            raise exc.with_traceback(tb)
        if cleanup_error is not None:
            exc, tb = cleanup_error
            raise exc.with_traceback(tb)
