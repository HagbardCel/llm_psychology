"""Durable assessment/post-session operation task ownership."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from jung._application import diagnostics as diag
from jung._application.inputs import PhaseInputs
from jung._application.store_calls import run_store_call
from jung._application.work_errors import _classify_work_error
from jung._async_cleanup import drain_cancelled_task
from jung.diagnostics import DiagnosticRecorder, diagnostic_context
from jung.domain.errors import InvariantViolation
from jung.domain.models import (
    NewPlanRevision,
    Operation,
    OperationKind,
    OperationStatus,
)
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.processor import AssessmentProcessor
from jung.phases.post_session.merge import merge_derived_profile, merge_plan_content
from jung.phases.post_session.processor import PostSessionProcessor

logger = logging.getLogger(__name__)


class OperationRuntime:
    def __init__(
        self,
        *,
        store: SQLiteStore,
        assessment: AssessmentProcessor,
        post_session: PostSessionProcessor,
        inputs: PhaseInputs,
        mutation_lock: asyncio.Lock,
        shutdown_started: asyncio.Event,
        now: Callable[[], datetime],
        new_id: Callable[[], UUID],
        recorder: DiagnosticRecorder | None = None,
    ) -> None:
        self._store = store
        self._assessment = assessment
        self._post_session = post_session
        self._inputs = inputs
        self._mutation_lock = mutation_lock
        self._shutdown_started = shutdown_started
        self._now = now
        self._new_id = new_id
        self._recorder = recorder
        self._operation_task: asyncio.Task[None] | None = None
        self._operation_task_id: UUID | None = None

    @property
    def has_live_task(self) -> bool:
        task = self._operation_task
        return task is not None and not task.done()

    async def _run_store(self, fn, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        return await run_store_call(fn, *args, recorder=self._recorder, **kwargs)

    def _clear_ownership(self, *, expected: asyncio.Task[None] | None = None) -> None:
        current = self._operation_task
        if expected is not None and current is not None and current is not expected:
            return
        self._operation_task = None
        self._operation_task_id = None

    async def shutdown(self, *, timeout_seconds: float) -> None:
        task = self._operation_task
        if task is None:
            return
        if task.done():
            self._clear_ownership(expected=task)
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
        except TimeoutError:
            task.cancel()
            await drain_cancelled_task(task)
        except asyncio.CancelledError:
            task.cancel()
            await drain_cancelled_task(task)
            raise
        finally:
            self._clear_ownership(expected=task)

    def _operation_task_name(self, operation: Operation) -> str:
        return f"operation:{operation.id}"

    def _spawn_operation_task(self, operation: Operation) -> asyncio.Task[None]:
        coro = self._run_owned_operation(operation.id)
        try:
            return asyncio.create_task(
                coro,
                name=self._operation_task_name(operation),
            )
        except Exception:
            coro.close()
            raise

    def schedule(self, operation: Operation) -> None:
        if self._shutdown_started.is_set():
            return
        task = self._operation_task
        if task is not None and not task.done():
            if self._operation_task_id == operation.id:
                return
            pending = operation

            def _defer(_done: asyncio.Task[None]) -> None:
                self.schedule(pending)

            task.add_done_callback(_defer)
            return

        try:
            created = self._spawn_operation_task(operation)
        except Exception as exc:
            logger.exception(
                "failed to schedule operation operation_id=%s",
                operation.id,
            )
            diag.record_runtime_error(
                self._recorder,
                phase="operation_schedule",
                exc=exc,
                operation_id=str(operation.id),
            )
            return
        self._operation_task = created
        self._operation_task_id = operation.id

    async def _run_owned_operation(self, operation_id: UUID) -> None:
        try:
            with diagnostic_context(operation_id=str(operation_id)):
                await self._run_operation_worker_body(operation_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "operation task failed unexpectedly operation_id=%s",
                operation_id,
            )
            diag.record_runtime_error(
                self._recorder,
                phase="operation_task",
                exc=exc,
                operation_id=str(operation_id),
            )
        finally:
            current = asyncio.current_task()
            self._clear_ownership(expected=current)

    async def _run_operation_worker_body(self, operation_id: UUID) -> None:
        running_owned = False
        try:
            async with self._mutation_lock:
                operation = await self._run_store(
                    self._store.get_operation,
                    operation_id,
                )
                if operation is None or operation.status is not OperationStatus.PENDING:
                    return
                operation = await self._run_store(
                    self._store.mark_operation_running,
                    operation_id,
                    now=self._now(),
                )
                running_owned = True
            with diagnostic_context(
                operation_id=str(operation_id),
                session_id=str(operation.source_session_id),
            ):
                diag.record(
                    self._recorder,
                    "operation.started",
                    {
                        "kind": operation.kind.value,
                        "attempt": operation.attempt,
                    },
                )

                if operation.kind is OperationKind.ASSESSMENT:
                    assessment_input = await self._inputs.build_assessment_input(
                        operation
                    )
                    result = await self._assessment.assess(assessment_input)
                    async with self._mutation_lock:
                        before = await self._run_store(self._store.load_snapshot_facts)
                        to_stage = await self._run_store(
                            self._store.complete_assessment,
                            operation_id,
                            result=result.model_dump(mode="json"),
                            now=self._now(),
                        )
                    diag.record(
                        self._recorder,
                        "operation.completed",
                        {
                            "kind": operation.kind.value,
                            "attempt": operation.attempt,
                        },
                    )
                    diag.record_transition(
                        self._recorder,
                        from_stage=before.stage,
                        to_stage=to_stage,
                        trigger="assessment_completed",
                    )
                elif operation.kind is OperationKind.POST_SESSION:
                    post_input = await self._inputs.build_post_session_input(operation)
                    result = await self._post_session.process(post_input)
                    stored = await self._run_store(self._store.get_profile)
                    session = await self._run_store(
                        self._store.get_session,
                        operation.source_session_id,
                    )
                    assert session is not None and session.plan_id is not None
                    plan_for_session = await self._inputs.load_plan_for_session(
                        operation.source_session_id,
                        session.plan_id,
                    )
                    merged_profile = merge_derived_profile(
                        stored.derived_profile if stored else None,
                        result.derived_profile_patch,
                    )
                    merged_plan = merge_plan_content(
                        plan_for_session, result.plan_patch
                    )
                    new_plan = (
                        NewPlanRevision(
                            plan_id=self._new_id(),
                            content=merged_plan,
                        )
                        if merged_plan is not None
                        else None
                    )
                    async with self._mutation_lock:
                        before = await self._run_store(self._store.load_snapshot_facts)
                        to_stage = await self._run_store(
                            self._store.complete_post_session,
                            operation_id,
                            summary=result.session_summary,
                            briefing=result.session_briefing.model_dump(mode="json"),
                            derived_profile=merged_profile,
                            new_plan=new_plan,
                            now=self._now(),
                        )
                    diag.record(
                        self._recorder,
                        "operation.completed",
                        {
                            "kind": operation.kind.value,
                            "attempt": operation.attempt,
                        },
                    )
                    diag.record_transition(
                        self._recorder,
                        from_stage=before.stage,
                        to_stage=to_stage,
                        trigger="post_session_completed",
                    )
                else:
                    raise InvariantViolation(
                        f"unknown operation kind: {operation.kind}"
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if running_owned:
                logger.exception(
                    "operation worker failed operation_id=%s",
                    operation_id,
                )
                await self._persist_operation_failure_if_running(operation_id, exc)
            else:
                logger.exception(
                    "operation ownership transition failed operation_id=%s",
                    operation_id,
                )
                raise

    async def _persist_operation_failure_if_running(
        self,
        operation_id: UUID,
        exc: Exception,
    ) -> None:
        code, message, retryable = _classify_work_error(exc)
        async with self._mutation_lock:
            current = await self._run_store(self._store.get_operation, operation_id)
            if current is None or current.status is not OperationStatus.RUNNING:
                logger.exception(
                    "operation worker failed after row left running operation_id=%s",
                    operation_id,
                    exc_info=exc,
                )
                diag.record_runtime_error(
                    self._recorder,
                    phase="operation_worker_late_failure",
                    exc=exc,
                    operation_id=str(operation_id),
                )
                return
            operation = await self._run_store(
                self._store.fail_operation,
                operation_id,
                error_code=code,
                error_message=message,
                retryable=retryable,
                now=self._now(),
            )
        with diagnostic_context(
            operation_id=str(operation.id),
            session_id=str(operation.source_session_id),
        ):
            diag.record(
                self._recorder,
                "operation.failed",
                {
                    "kind": operation.kind.value,
                    "attempt": operation.attempt,
                    "error_code": operation.error_code or code,
                    "retryable": operation.retryable,
                },
            )
