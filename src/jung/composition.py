"""Production composition root for the target application core."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
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
from jung.llm.gateway import (
    AdapterConfig,
    LLMRole,
    LLMTask,
    ModelPolicy,
    StructuredOutputMode,
    role_for_task,
)
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
) -> None:
    logger.warning(
        "runtime cleanup failed step=%s error_type=%s",
        step,
        type(exc).__name__,
    )
    if recorder is not None:
        recorder.record(
            "runtime.error",
            {
                "phase": f"cleanup:{step}",
                "error_type": type(exc).__name__,
                "error_message": _safe_exception_message(exc),
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
    if settings.supervisor_llm_api_key is not None:
        secrets.append(settings.supervisor_llm_api_key)
    if settings.llm_default_headers:
        secrets.extend(settings.llm_default_headers.values())
    if settings.supervisor_llm_default_headers:
        secrets.extend(settings.supervisor_llm_default_headers.values())
    return [value for value in secrets if value]


def _task_extra_body_for_role(
    settings: JungSettings,
    role: LLMRole,
) -> dict[LLMTask, dict[str, object]] | None:
    filtered = {
        task: override.extra_body
        for task, override in settings.llm_task_config.items()
        if override.extra_body and role_for_task(task) is role
    }
    return filtered or None


async def _close_llm(
    llm: OpenAICompatibleLLM,
    *,
    step: str,
    recorder: DiagnosticRecorder | None,
    primary: _ExcInfo | None,
    cleanup_error: _ExcInfo | None,
) -> _ExcInfo | None:
    """Close one LLM client without aborting the rest of aggregate teardown."""
    try:
        close_task = asyncio.ensure_future(llm.aclose())
        try:
            await asyncio.shield(close_task)
        except asyncio.CancelledError as cancel_exc:
            drained = await drain_cancelled_task(close_task)
            if drained is not None and not isinstance(drained, asyncio.CancelledError):
                _record_cleanup_failure(
                    recorder,
                    step=step,
                    exc=drained,
                )
            if primary is None and cleanup_error is None:
                cleanup_error = (cancel_exc, cancel_exc.__traceback__)
            _record_cleanup_failure(
                recorder,
                step=step,
                exc=cancel_exc,
            )
            return cleanup_error
    except BaseException as exc:
        if primary is None and cleanup_error is None:
            cleanup_error = (exc, exc.__traceback__)
        _record_cleanup_failure(
            recorder,
            step=step,
            exc=exc,
        )
    return cleanup_error


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
        session_llm: OpenAICompatibleLLM | None = None
        supervisor_llm: OpenAICompatibleLLM | None = None
        application: TherapyApplication | None = None
        primary: _ExcInfo | None = None
        cleanup_error: _ExcInfo | None = None

        try:
            supervisor_base_url = (
                settings.supervisor_llm_base_url or settings.llm_base_url
            )
            supervisor_model = settings.supervisor_model_name or settings.model_name
            supervisor_api_key = (
                settings.llm_api_key
                if settings.supervisor_llm_api_key is None
                else settings.supervisor_llm_api_key
            )
            supervisor_extra_body = (
                settings.llm_extra_body
                if settings.supervisor_llm_extra_body is None
                else settings.supervisor_llm_extra_body
            )
            supervisor_headers = (
                settings.llm_default_headers
                if settings.supervisor_llm_default_headers is None
                else settings.supervisor_llm_default_headers
            )

            policies = build_model_policies(
                session_model=settings.model_name,
                supervisor_model=supervisor_model,
                task_overrides=settings.llm_task_config,
            )
            _preflight_json_schema_policies(policies)
            store = SQLiteStore(settings.database_path)
            await asyncio.to_thread(store.initialize)
            store_initialized = True

            session_adapter_config = AdapterConfig(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                default_headers=settings.llm_default_headers,
                extra_body=settings.llm_extra_body,
                task_extra_body=_task_extra_body_for_role(settings, LLMRole.SESSION),
            )
            supervisor_adapter_config = AdapterConfig(
                base_url=supervisor_base_url,
                api_key=supervisor_api_key,
                default_headers=supervisor_headers,
                extra_body=supervisor_extra_body,
                task_extra_body=_task_extra_body_for_role(settings, LLMRole.SUPERVISOR),
            )

            if llm_factory is not None:
                session_llm = llm_factory(session_adapter_config, recorder)
                supervisor_llm = llm_factory(supervisor_adapter_config, recorder)
            else:
                session_llm = OpenAICompatibleLLM(
                    session_adapter_config, recorder=recorder
                )
                supervisor_llm = OpenAICompatibleLLM(
                    supervisor_adapter_config, recorder=recorder
                )

            session_gateway: OpenAICompatibleLLM | ObservedLLMGateway = session_llm
            supervisor_gateway: OpenAICompatibleLLM | ObservedLLMGateway = (
                supervisor_llm
            )
            if settings.enable_llm_tracing or recorder is not None:
                session_gateway = ObservedLLMGateway(
                    session_llm,
                    role=LLMRole.SESSION,
                    log_metadata=settings.enable_llm_tracing,
                    recorder=recorder,
                )
                supervisor_gateway = ObservedLLMGateway(
                    supervisor_llm,
                    role=LLMRole.SUPERVISOR,
                    log_metadata=settings.enable_llm_tracing,
                    recorder=recorder,
                )

            styles = load_styles()
            application = TherapyApplication(
                store=store,
                intake=IntakeProcessor(
                    session_gateway,
                    patch_policy=policies[LLMTask.INTAKE_PATCH],
                    response_policy=policies[LLMTask.INTAKE_RESPONSE],
                ),
                assessment=AssessmentProcessor(
                    supervisor_gateway,
                    assessment_policy=policies[LLMTask.ASSESSMENT],
                ),
                therapy=TherapyProcessor(
                    session_gateway,
                    response_policy=policies[LLMTask.THERAPY_RESPONSE],
                ),
                post_session=PostSessionProcessor(
                    supervisor_gateway,
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
            if application is not None:
                try:
                    await application.shutdown(
                        timeout_seconds=settings.shutdown_timeout_seconds
                    )
                except BaseException as exc:
                    if primary is None and cleanup_error is None:
                        cleanup_error = (exc, exc.__traceback__)
                    _record_cleanup_failure(
                        recorder,
                        step="application.shutdown",
                        exc=exc,
                    )

            if session_llm is not None:
                cleanup_error = await _close_llm(
                    session_llm,
                    step="session_llm.aclose",
                    recorder=recorder,
                    primary=primary,
                    cleanup_error=cleanup_error,
                )
            if supervisor_llm is not None:
                cleanup_error = await _close_llm(
                    supervisor_llm,
                    step="supervisor_llm.aclose",
                    recorder=recorder,
                    primary=primary,
                    cleanup_error=cleanup_error,
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
