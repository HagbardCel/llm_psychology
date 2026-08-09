"""Target application use-case coordinator."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from datetime import datetime
from types import MappingProxyType
from typing import Any, TypeVar
from uuid import UUID

from pydantic import ValidationError

from jung import workflow
from jung._async_cleanup import drain_cancelled_task
from jung.diagnostics import (
    DiagnosticRecorder,
    _safe_exception_message,
    diagnostic_context,
)
from jung.domain.commands import (
    EndSession,
    SelectStyle,
    SendMessage,
    UpdateProfile,
)
from jung.domain.errors import (
    Busy,
    InvalidCommand,
    InvariantViolation,
    NotFound,
)
from jung.domain.models import (
    AppSnapshot,
    CommandName,
    Message,
    MessageRole,
    NewPlanRevision,
    Operation,
    OperationKind,
    OperationStatus,
    Plan,
    Session,
    SessionKind,
    Stage,
    is_profile_complete,
)
from jung.domain.results import (
    ChatCompleted,
    ChatFailed,
    ChatStreamResult,
    ChatToken,
    ProfileView,
    SessionHistory,
    StartedSession,
    StyleOptions,
    StyleRecommendationView,
    StyleSummary,
)
from jung.llm.errors import InvalidLLMOutput, LLMError
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import (
    AssessmentInput,
    AssessmentResult,
    StyleRecommendation,
)
from jung.phases.assessment.processor import AssessmentProcessor
from jung.phases.assessment.validation import validate_and_normalize_assessment
from jung.phases.intake.models import IntakeRecord, IntakeTurnInput
from jung.phases.intake.processor import IntakeProcessor
from jung.phases.post_session.merge import merge_derived_profile, merge_plan_content
from jung.phases.post_session.models import PostSessionInput
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.therapy.models import TherapyTurnInput
from jung.phases.therapy.processor import TherapyProcessor
from jung.phases.transcript import messages_to_transcript
from jung.styles import StyleDefinition

logger = logging.getLogger(__name__)

_RECENT_SUMMARY_LIMIT = 5
_T = TypeVar("_T")


class ScheduleRejected(Exception):
    """Test seam: refuse schedule without recording operation_schedule error."""


class _AcceptedDuringCancel(Exception):
    def __init__(self, message: Message, cancellation: BaseException) -> None:
        self.message = message
        self.cancellation = cancellation
        super().__init__("user message accepted during cancellation")


class _TerminalDuringCancel(Exception):
    def __init__(self, result: ChatCompleted, cancellation: BaseException) -> None:
        self.result = result
        self.cancellation = cancellation
        super().__init__("chat terminalized during cancellation")


class TherapyApplication:
    def __init__(
        self,
        *,
        store: SQLiteStore,
        intake: IntakeProcessor,
        assessment: AssessmentProcessor,
        therapy: TherapyProcessor,
        post_session: PostSessionProcessor,
        styles: MappingProxyType[str, StyleDefinition],
        now: Callable[[], datetime],
        new_id: Callable[[], UUID],
        recorder: DiagnosticRecorder | None = None,
    ) -> None:
        self._store = store
        self._intake = intake
        self._assessment = assessment
        self._therapy = therapy
        self._post_session = post_session
        self._styles = styles
        self._now = now
        self._new_id = new_id
        self._recorder = recorder
        self._mutation_lock = asyncio.Lock()
        self._generation_lock = asyncio.Lock()
        self._shutdown = False
        self._operation_task: asyncio.Task[None] | None = None
        self._operation_task_id: UUID | None = None
        self._schedule_test_hook: Callable[[Operation], None] | None = None

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown

    async def shutdown(self, *, timeout_seconds: float) -> None:
        self._shutdown = True
        task = self._operation_task
        if task is None:
            return
        if task.done():
            self._clear_operation_ownership(expected=task)
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
            self._clear_operation_ownership(expected=task)

    def _clear_operation_ownership(
        self, *, expected: asyncio.Task[None] | None = None
    ) -> None:
        current = self._operation_task
        if expected is not None and current is not None and current is not expected:
            return
        self._operation_task = None
        self._operation_task_id = None

    def _record(self, kind: str, data: dict[str, Any] | None = None) -> None:
        if self._recorder is not None:
            self._recorder.record(kind, data)

    def _record_runtime_error(
        self,
        *,
        phase: str,
        exc: BaseException,
        **extra: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "phase": phase,
            "error_type": type(exc).__name__,
            "error_message": _safe_exception_message(exc),
        }
        payload.update(extra)
        self._record("runtime.error", payload)

    def _record_command_error(self, command: str, exc: BaseException) -> None:
        self._record_runtime_error(
            phase="workflow_command",
            exc=exc,
            command=command,
        )

    def _record_command_started(self, command: str) -> None:
        self._record("workflow.command.started", {"command": command})

    def _record_command_completed(self, command: str, outcome: str) -> None:
        self._record(
            "workflow.command.completed",
            {"command": command, "outcome": outcome},
        )

    def _record_command_rejected(self, command: str, exc: BaseException) -> None:
        self._record(
            "workflow.command.rejected",
            {"command": command, "error_type": type(exc).__name__},
        )

    def _record_transition_if_changed(
        self,
        *,
        from_stage: Stage,
        to_stage: Stage,
        trigger: str,
    ) -> None:
        if from_stage is to_stage:
            return
        self._record(
            "workflow.transition",
            {
                "from_stage": from_stage.value,
                "to_stage": to_stage.value,
                "trigger": trigger,
            },
        )

    _COMMAND_REJECT_TYPES = (
        InvalidCommand,
        Busy,
        NotFound,
    )

    async def _run_store(
        self, fn: Callable[..., _T], /, *args: Any, **kwargs: Any
    ) -> _T:
        # Bounded shutdown applies around LLM/background work; an already-running
        # local SQLite call is allowed to finish before the mutation lock releases.
        method_name = getattr(fn, "__name__", None) or type(fn).__name__

        task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancellation:
            failure = await drain_cancelled_task(task)
            if failure is not None:
                logger.error(
                    "store call failed after caller cancellation "
                    "function=%s error_type=%s",
                    method_name,
                    type(failure).__name__,
                    exc_info=failure,
                )
                self._record_runtime_error(
                    phase="store_drained",
                    exc=failure,
                    function=method_name,
                )

            raise cancellation

    async def recover_on_startup(self) -> AppSnapshot:
        async with self._mutation_lock:
            if self._operation_task is not None and not self._operation_task.done():
                return await self._assemble_snapshot_locked()
            recovered = await self._run_store(
                self._store.recover_stale_operation,
                now=self._now(),
            )
            snapshot = await self._assemble_snapshot_locked()

        pending = snapshot.current_operation
        if pending is not None and pending.status is OperationStatus.PENDING:
            self._schedule_operation(pending)

        if recovered is not None:
            with diagnostic_context(
                operation_id=str(recovered.id),
                session_id=str(recovered.source_session_id),
            ):
                self._record(
                    "operation.recovered",
                    {
                        "kind": recovered.kind.value,
                        "attempt": recovered.attempt,
                        "from_status": OperationStatus.RUNNING.value,
                        "to_status": OperationStatus.PENDING.value,
                    },
                )
        return snapshot

    async def get_snapshot(self) -> AppSnapshot:
        async with self._mutation_lock:
            return await self._assemble_snapshot_locked()

    async def get_profile(self) -> ProfileView:
        async with self._mutation_lock:
            stored = await self._run_store(self._store.get_profile)
            if stored is None:
                raise NotFound("profile")

            plan = await self._run_store(self._store.get_current_plan)
            snapshot = await self._assemble_snapshot_locked()
            return ProfileView(
                profile=stored.profile,
                current_plan=plan,
                snapshot=snapshot,
            )

    async def get_style_options(self) -> StyleOptions:
        async with self._mutation_lock:
            assessment = await self._load_completed_assessment_locked()
            recommendations = (
                ()
                if assessment is None
                else tuple(
                    _to_style_recommendation_view(item)
                    for item in assessment.style_recommendations
                )
            )
            return StyleOptions(
                styles=tuple(
                    StyleSummary(
                        id=style.id,
                        name=style.name,
                        description=style.description,
                    )
                    for style in self._styles.values()
                ),
                recommendations=recommendations,
            )

    async def _load_completed_assessment_locked(
        self,
    ) -> AssessmentResult | None:
        # Completed assessments are validated against the current style catalog
        # set and order; catalog changes can invalidate stored results.
        operation = await self._run_store(
            self._store.get_latest_completed_operation,
            OperationKind.ASSESSMENT,
        )
        if operation is None:
            return None
        if operation.result is None:
            raise InvariantViolation("completed assessment result is missing")

        available_style_ids = tuple(self._styles)

        try:
            assessment = AssessmentResult.model_validate(operation.result)
            normalized = validate_and_normalize_assessment(
                assessment,
                available_style_ids,
            )
        except (ValidationError, ValueError) as exc:
            raise InvariantViolation("completed assessment result is invalid") from exc

        if assessment.style_recommendations != normalized.style_recommendations:
            raise InvariantViolation(
                "completed assessment recommendations are not normalized"
            )

        return assessment

    async def list_sessions(self) -> list[Session]:
        return await self._run_store(self._store.list_sessions)

    async def get_session_history(self, session_id: UUID) -> SessionHistory:
        async with self._mutation_lock:
            session = await self._run_store(self._store.get_session, session_id)
            if session is None:
                raise NotFound(f"session {session_id}")
            messages = await self._run_store(self._store.list_messages, session_id)
            plans = await self._run_store(
                self._store.list_plans_for_session, session_id
            )
            return SessionHistory(
                session=session,
                messages=tuple(messages),
                plans=tuple(plans),
            )

    async def update_profile(self, command: UpdateProfile) -> AppSnapshot:
        self._record_command_started("update_profile")
        try:
            self._reject_if_shutdown()
            self._reject_if_generation_active()
            async with self._mutation_lock:
                self._reject_if_shutdown()
                self._reject_if_generation_active()
                facts = await self._run_store(self._store.load_snapshot_facts)
                from_stage = facts.stage
                workflow.require_command_allowed(CommandName.UPDATE_PROFILE, facts)
                profile_complete = is_profile_complete(command.profile)

                if facts.stage is Stage.INTAKE and not profile_complete:
                    raise InvalidCommand("profile must remain complete during intake")

                intake_session_id = (
                    self._new_id()
                    if facts.stage is Stage.SETUP and profile_complete
                    else None
                )
                await self._run_store(
                    self._store.update_profile,
                    command.profile,
                    intake_session_id=intake_session_id,
                    now=self._now(),
                )
                snapshot = await self._assemble_snapshot_locked()
            self._record_command_completed("update_profile", "committed")
            self._record_transition_if_changed(
                from_stage=from_stage,
                to_stage=snapshot.stage,
                trigger="update_profile",
            )
            return snapshot
        except self._COMMAND_REJECT_TYPES as exc:
            self._record_command_rejected("update_profile", exc)
            raise
        except Exception as exc:
            self._record_command_error("update_profile", exc)
            raise

    async def select_style(self, command: SelectStyle) -> AppSnapshot:
        self._record_command_started("select_style")
        try:
            self._reject_if_shutdown()
            self._reject_if_generation_active()
            if command.style_id not in self._styles:
                raise InvalidCommand(f"unknown style: {command.style_id}")
            async with self._mutation_lock:
                self._reject_if_shutdown()
                self._reject_if_generation_active()
                facts = await self._run_store(self._store.load_snapshot_facts)
                from_stage = facts.stage
                workflow.require_command_allowed(CommandName.SELECT_STYLE, facts)
                assessment = await self._load_completed_assessment_locked()
                if assessment is None:
                    raise InvariantViolation("completed assessment result is required")
                recommendation = _select_style_recommendation(
                    assessment,
                    command.style_id,
                )
                operation = await self._run_store(
                    self._store.get_latest_completed_operation,
                    OperationKind.ASSESSMENT,
                )
                assert operation is not None
                plan_id = self._new_id()
                await self._run_store(
                    self._store.select_style_and_create_initial_plan,
                    style_id=command.style_id,
                    plan_id=plan_id,
                    content=recommendation.initial_plan,
                    intake_session_id=operation.source_session_id,
                    now=self._now(),
                )
                snapshot = await self._assemble_snapshot_locked()
            self._record_command_completed("select_style", "committed")
            self._record_transition_if_changed(
                from_stage=from_stage,
                to_stage=snapshot.stage,
                trigger="select_style",
            )
            return snapshot
        except self._COMMAND_REJECT_TYPES as exc:
            self._record_command_rejected("select_style", exc)
            raise
        except Exception as exc:
            self._record_command_error("select_style", exc)
            raise

    async def start_session(self) -> StartedSession:
        self._record_command_started("start_session")
        try:
            self._reject_if_shutdown()
            self._reject_if_generation_active()
            session_id = self._new_id()
            async with self._mutation_lock:
                self._reject_if_shutdown()
                self._reject_if_generation_active()
                facts = await self._run_store(self._store.load_snapshot_facts)
                from_stage = facts.stage
                workflow.require_command_allowed(CommandName.START_SESSION, facts)
                session = await self._run_store(
                    self._store.start_therapy_session,
                    session_id=session_id,
                    now=self._now(),
                )
                snapshot = await self._assemble_snapshot_locked()
                started = StartedSession(session=session, snapshot=snapshot)
            self._record_command_completed("start_session", "committed")
            self._record_transition_if_changed(
                from_stage=from_stage,
                to_stage=started.snapshot.stage,
                trigger="start_session",
            )
            return started
        except self._COMMAND_REJECT_TYPES as exc:
            self._record_command_rejected("start_session", exc)
            raise
        except Exception as exc:
            self._record_command_error("start_session", exc)
            raise

    async def end_session(self, command: EndSession) -> AppSnapshot:
        self._record_command_started("end_session")
        operation: Operation | None = None
        snapshot: AppSnapshot | None = None
        from_stage: Stage | None = None
        try:
            self._reject_if_shutdown()
            self._reject_if_generation_active()
            operation_id = self._new_id()
            try:
                async with self._mutation_lock:
                    self._reject_if_shutdown()
                    self._reject_if_generation_active()
                    facts = await self._run_store(self._store.load_snapshot_facts)
                    from_stage = facts.stage
                    workflow.require_command_allowed(CommandName.END_SESSION, facts)
                    session = await self._run_store(
                        self._store.get_session,
                        command.session_id,
                    )
                    if session is None:
                        raise NotFound("session")
                    active = await self._run_store(self._store.get_active_session)
                    if active is None or active.id != command.session_id:
                        raise InvalidCommand(
                            "session_id does not match the active session"
                        )
                    if active.kind is not SessionKind.THERAPY:
                        raise InvalidCommand("active session is not therapy")
                    operation = await self._run_store(
                        self._store.end_therapy_session,
                        session_id=command.session_id,
                        operation_id=operation_id,
                        now=self._now(),
                    )
                    snapshot = await self._assemble_snapshot_locked()
                assert operation is not None and snapshot is not None
                with diagnostic_context(
                    operation_id=str(operation.id),
                    session_id=str(operation.source_session_id),
                ):
                    self._record(
                        "operation.created",
                        {
                            "kind": operation.kind.value,
                            "attempt": operation.attempt,
                        },
                    )
                self._record_command_completed("end_session", "committed")
                if from_stage is not None:
                    self._record_transition_if_changed(
                        from_stage=from_stage,
                        to_stage=snapshot.stage,
                        trigger="end_session",
                    )
                return snapshot
            finally:
                if operation is not None:
                    self._schedule_operation(operation)
        except self._COMMAND_REJECT_TYPES as exc:
            self._record_command_rejected("end_session", exc)
            raise
        except Exception as exc:
            self._record_command_error("end_session", exc)
            raise

    async def retry_operation(self) -> AppSnapshot:
        self._record_command_started("retry_operation")
        operation: Operation | None = None
        snapshot: AppSnapshot | None = None
        from_stage: Stage | None = None
        try:
            self._reject_if_shutdown()
            self._reject_if_generation_active()
            try:
                async with self._mutation_lock:
                    self._reject_if_shutdown()
                    self._reject_if_generation_active()
                    facts = await self._run_store(self._store.load_snapshot_facts)
                    from_stage = facts.stage
                    workflow.require_command_allowed(CommandName.RETRY_OPERATION, facts)
                    current = await self._run_store(self._store.get_current_operation)
                    if current is None:
                        raise InvariantViolation(
                            "retry command available without current operation"
                        )
                    if (
                        current.status is not OperationStatus.FAILED
                        or not current.retryable
                    ):
                        raise InvariantViolation(
                            "retry command available for ineligible operation"
                        )
                    operation = await self._run_store(
                        self._store.retry_operation,
                        current.id,
                        now=self._now(),
                    )
                    snapshot = await self._assemble_snapshot_locked()
                assert operation is not None and snapshot is not None
                with diagnostic_context(
                    operation_id=str(operation.id),
                    session_id=str(operation.source_session_id),
                ):
                    self._record(
                        "operation.retried",
                        {
                            "kind": operation.kind.value,
                            "attempt": operation.attempt,
                        },
                    )
                self._record_command_completed("retry_operation", "committed")
                if from_stage is not None:
                    self._record_transition_if_changed(
                        from_stage=from_stage,
                        to_stage=snapshot.stage,
                        trigger="retry_operation",
                    )
                return snapshot
            finally:
                if operation is not None:
                    self._schedule_operation(operation)
        except self._COMMAND_REJECT_TYPES as exc:
            self._record_command_rejected("retry_operation", exc)
            raise
        except Exception as exc:
            self._record_command_error("retry_operation", exc)
            raise

    def _reject_if_generation_active(self) -> None:
        if self._generation_lock.locked():
            raise Busy("another chat generation is active")

    async def _accept_chat_command_locked(
        self, command: SendMessage
    ) -> tuple[Message | None, ChatCompleted | None, bool]:
        """Under mutation lock: reuse, retry, or persist USER.

        Returns ``(user_message, reused_completion, generation_owned)``.
        When ``reused_completion`` is set, ``user_message`` is None.
        """
        session_id = command.session_id
        client_message_id = command.client_message_id
        request_id = command.request_id
        existing_user, existing_assistant = await self._run_store(
            self._store.get_messages_by_client_id,
            session_id,
            client_message_id,
        )

        if existing_user is not None and existing_assistant is not None:
            if existing_user.content != command.content:
                raise InvalidCommand(
                    "client_message_id already used with different content"
                )
            self._record_command_completed("send_message", "idempotent_existing")
            with diagnostic_context(
                session_id=str(session_id),
                client_message_id=str(client_message_id),
                request_id=str(request_id) if request_id is not None else None,
            ):
                self._record("chat.turn.reused", {})
            return (
                None,
                ChatCompleted(
                    session_id=session_id,
                    client_message_id=client_message_id,
                    request_id=request_id,
                    user_message=existing_user,
                    assistant_message=existing_assistant,
                ),
                False,
            )

        if existing_user is not None and existing_assistant is None:
            if existing_user.content != command.content:
                raise InvalidCommand(
                    "client_message_id already used with different content"
                )
            if not await self._chat_retry_structurally_eligible(
                session_id, existing_user
            ):
                raise InvalidCommand(
                    "unanswered user message is not eligible for retry"
                )
            self._reject_if_generation_active()
            await self._reserve_generation_lock()
            with diagnostic_context(
                session_id=str(session_id),
                client_message_id=str(client_message_id),
                request_id=str(request_id) if request_id is not None else None,
            ):
                self._record_command_completed("send_message", "committed")
                self._record("chat.turn.retried", {})
                self._record("chat.turn.started", {})
            return existing_user, None, True

        if existing_user is None and existing_assistant is not None:
            raise InvariantViolation(
                "assistant message exists without matching user message"
            )

        facts = await self._run_store(self._store.load_snapshot_facts)
        workflow.require_command_allowed(CommandName.SEND_MESSAGE, facts)
        if not command.content.strip():
            raise InvalidCommand("message content must be non-empty")
        messages = await self._run_store(self._store.list_messages, session_id)
        if messages and messages[-1].role is MessageRole.USER:
            raise InvalidCommand("retry the unanswered message before sending another")
        self._reject_if_generation_active()
        await self._reserve_generation_lock()
        try:
            user_message = await self._persist_user_message_drained(
                session_id=session_id,
                client_message_id=client_message_id,
                content=command.content,
            )
        except _AcceptedDuringCancel:
            with diagnostic_context(
                session_id=str(session_id),
                client_message_id=str(client_message_id),
                request_id=str(request_id) if request_id is not None else None,
            ):
                self._record_command_completed("send_message", "committed")
                self._record("chat.turn.accepted", {})
            raise
        except BaseException:
            self._release_generation_lock()
            raise
        with diagnostic_context(
            session_id=str(session_id),
            client_message_id=str(client_message_id),
            request_id=str(request_id) if request_id is not None else None,
        ):
            self._record_command_completed("send_message", "committed")
            self._record("chat.turn.accepted", {})
            self._record("chat.turn.started", {})
        return user_message, None, True

    def _chat_failure_result(
        self,
        exc: Exception,
        *,
        session_id: UUID,
        client_message_id: UUID,
        request_id: UUID | None,
    ) -> ChatFailed:
        if not isinstance(exc, LLMError):
            self._record_runtime_error(
                phase="chat_attempt",
                exc=exc,
                session_id=str(session_id),
                client_message_id=str(client_message_id),
                request_id=str(request_id) if request_id is not None else None,
            )
        code, message, retryable = _classify_worker_error(exc)
        with diagnostic_context(
            session_id=str(session_id),
            client_message_id=str(client_message_id),
            request_id=str(request_id) if request_id is not None else None,
        ):
            self._record(
                "chat.turn.failed",
                {
                    "error_code": code,
                    "retryable": retryable,
                    "source": "chat_attempt",
                },
            )
        return ChatFailed(
            session_id=session_id,
            client_message_id=client_message_id,
            request_id=request_id,
            code=code,
            message=message,
        )

    async def stream_message(
        self, command: SendMessage
    ) -> AsyncIterator[ChatStreamResult]:
        self._record_command_started("send_message")
        accepted = False
        terminal = False
        generation_owned = False
        user_message: Message | None = None
        session_id = command.session_id
        client_message_id = command.client_message_id
        request_id = command.request_id

        try:
            self._reject_if_shutdown()
            async with self._mutation_lock:
                self._reject_if_shutdown()
                (
                    user_message,
                    reused,
                    generation_owned,
                ) = await self._accept_chat_command_locked(command)
                accepted = user_message is not None

            if reused is not None:
                terminal = True
                yield reused
                return

            assert user_message is not None
            try:
                async with aclosing(
                    self._generate_chat_stream(
                        user_message=user_message,
                        request_id=request_id,
                    )
                ) as generated:
                    async for item in generated:
                        if isinstance(item, (ChatCompleted, ChatFailed)):
                            terminal = True
                            if generation_owned:
                                self._release_generation_lock()
                                generation_owned = False
                        yield item
            except _TerminalDuringCancel as terminal_cancel:
                terminal = True
                raise terminal_cancel.cancellation from None
        except _AcceptedDuringCancel as cancel_accept:
            accepted = True
            generation_owned = True
            raise cancel_accept.cancellation from None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not accepted:
                if isinstance(exc, self._COMMAND_REJECT_TYPES):
                    self._record_command_rejected("send_message", exc)
                else:
                    self._record_command_error("send_message", exc)
                raise

            result = self._chat_failure_result(
                exc,
                session_id=session_id,
                client_message_id=client_message_id,
                request_id=request_id,
            )
            terminal = True
            if generation_owned:
                self._release_generation_lock()
                generation_owned = False
            yield result
        finally:
            if accepted and not terminal:
                with diagnostic_context(
                    session_id=str(session_id),
                    client_message_id=str(client_message_id),
                    request_id=str(request_id) if request_id is not None else None,
                ):
                    self._record(
                        "chat.turn.cancelled",
                        {"reason": "connection_cancelled"},
                    )
            if generation_owned:
                self._release_generation_lock()

    async def _persist_user_message_drained(
        self,
        *,
        session_id: UUID,
        client_message_id: UUID,
        content: str,
    ) -> Message:
        user_message_id = self._new_id()

        async def _persist() -> Message:
            return await self._run_store(
                self._store.append_user_message,
                session_id=session_id,
                client_message_id=client_message_id,
                user_message_id=user_message_id,
                content=content,
                now=self._now(),
            )

        task = asyncio.create_task(_persist())
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancellation:
            failure = await drain_cancelled_task(task)
            if failure is None:
                raise _AcceptedDuringCancel(task.result(), cancellation) from None
            if isinstance(failure, asyncio.CancelledError):
                raise cancellation
            raise failure from None

    async def _chat_retry_structurally_eligible(
        self, session_id: UUID, user_message: Message
    ) -> bool:
        session = await self._run_store(self._store.get_session, session_id)
        if session is None or session.ended_at is not None:
            return False
        active = await self._run_store(self._store.get_active_session)
        if active is None or active.id != session_id:
            return False
        state = await self._run_store(self._store.load_snapshot_facts)
        if state.stage is Stage.INTAKE and session.kind is not SessionKind.INTAKE:
            return False
        if state.stage is Stage.THERAPY and session.kind is not SessionKind.THERAPY:
            return False
        if state.stage not in {Stage.INTAKE, Stage.THERAPY}:
            return False
        messages = await self._run_store(self._store.list_messages, session_id)
        if not messages:
            return False
        latest = messages[-1]
        return (
            latest.id == user_message.id
            and latest.role is MessageRole.USER
            and latest.client_message_id == user_message.client_message_id
        )

    async def _generate_chat_stream(
        self,
        *,
        user_message: Message,
        request_id: UUID | None,
    ) -> AsyncIterator[ChatStreamResult]:
        session_id = user_message.session_id
        client_message_id = user_message.client_message_id
        session = await self._run_store(self._store.get_session, session_id)
        if session is None:
            raise NotFound(f"session {session_id}")

        intake_record: IntakeRecord | None = None
        completeness_complete = False
        if session.kind is SessionKind.INTAKE:
            turn_input = await self._build_intake_turn_input(session_id)
            plan = await self._intake.prepare_turn(turn_input)
            intake_record = plan.merged_record
            completeness_complete = plan.completeness_complete
            chunk_source = self._intake.stream_response(plan)
        elif session.kind is SessionKind.THERAPY:
            turn_input = await self._build_therapy_turn_input(session_id)
            chunk_source = self._therapy.stream_response(turn_input)
        else:
            raise InvariantViolation(f"unsupported session kind: {session.kind}")

        buffer: list[str] = []
        async with aclosing(chunk_source) as chunks:
            async for chunk in chunks:
                if not chunk:
                    continue
                buffer.append(chunk)
                yield ChatToken(
                    text=chunk,
                    session_id=session_id,
                    client_message_id=client_message_id,
                    request_id=request_id,
                )

        response_text = "".join(buffer)
        if not _response_has_content(response_text):
            raise InvalidLLMOutput(
                "assistant response must contain non-whitespace text"
            )

        if completeness_complete:
            assert intake_record is not None
            completed = await self._terminalize_final_intake_drained(
                user_message=user_message,
                content=response_text,
                intake_record=intake_record,
                request_id=request_id,
            )
        else:
            completed = await self._terminalize_ordinary_drained(
                user_message=user_message,
                content=response_text,
                intake_record=intake_record,
                request_id=request_id,
            )
        yield completed

    async def _terminalize_ordinary_drained(
        self,
        *,
        user_message: Message,
        content: str,
        intake_record: IntakeRecord | None,
        request_id: UUID | None,
    ) -> ChatCompleted:
        async def _terminalize() -> ChatCompleted:
            assistant_message_id = self._new_id()
            intake_payload = (
                intake_record.model_dump(mode="json")
                if intake_record is not None
                else None
            )
            async with self._mutation_lock:
                assistant = await self._run_store(
                    self._store.complete_chat_response,
                    session_id=user_message.session_id,
                    client_message_id=user_message.client_message_id,
                    assistant_message_id=assistant_message_id,
                    content=content,
                    intake_record=intake_payload,
                    now=self._now(),
                )
            with diagnostic_context(
                session_id=str(user_message.session_id),
                client_message_id=str(user_message.client_message_id),
                request_id=str(request_id) if request_id is not None else None,
            ):
                self._record("chat.turn.completed", {})
            return ChatCompleted(
                session_id=user_message.session_id,
                client_message_id=user_message.client_message_id,
                request_id=request_id,
                user_message=user_message,
                assistant_message=assistant,
            )

        return await self._await_owned_terminalization(_terminalize())

    async def _terminalize_final_intake_drained(
        self,
        *,
        user_message: Message,
        content: str,
        intake_record: IntakeRecord,
        request_id: UUID | None,
    ) -> ChatCompleted:
        async def _terminalize() -> ChatCompleted:
            assistant_message_id = self._new_id()
            operation_id = self._new_id()
            from_stage: Stage | None = None
            async with self._mutation_lock:
                facts = await self._run_store(self._store.load_snapshot_facts)
                from_stage = facts.stage
                assistant, operation = await self._run_store(
                    self._store.complete_final_intake_response,
                    session_id=user_message.session_id,
                    client_message_id=user_message.client_message_id,
                    assistant_message_id=assistant_message_id,
                    content=content,
                    intake_record=intake_record.model_dump(mode="json"),
                    operation_id=operation_id,
                    now=self._now(),
                )
            with diagnostic_context(
                session_id=str(user_message.session_id),
                client_message_id=str(user_message.client_message_id),
                request_id=str(request_id) if request_id is not None else None,
            ):
                self._record("chat.turn.completed", {})
            assert from_stage is not None
            self._record_transition_if_changed(
                from_stage=from_stage,
                to_stage=Stage.ASSESSMENT,
                trigger="final_intake",
            )
            with diagnostic_context(
                operation_id=str(operation.id),
                session_id=str(operation.source_session_id),
            ):
                self._record(
                    "operation.created",
                    {
                        "kind": operation.kind.value,
                        "attempt": operation.attempt,
                    },
                )
            # Assistant commit is irreversible; scheduling failure cannot ChatFailed.
            self._schedule_operation(operation)
            return ChatCompleted(
                session_id=user_message.session_id,
                client_message_id=user_message.client_message_id,
                request_id=request_id,
                user_message=user_message,
                assistant_message=assistant,
            )

        return await self._await_owned_terminalization(_terminalize())

    async def _await_owned_terminalization(
        self, terminalize_coro: Any
    ) -> ChatCompleted:
        task = asyncio.create_task(terminalize_coro)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancellation:
            failure = await drain_cancelled_task(task)
            if failure is None:
                raise _TerminalDuringCancel(task.result(), cancellation) from None
            if isinstance(failure, asyncio.CancelledError):
                raise cancellation
            raise failure from None

    async def _assemble_snapshot_locked(self) -> AppSnapshot:
        snapshot = await self._run_store(self._build_snapshot)
        if self._generation_lock.locked():
            snapshot = snapshot.model_copy(update={"available_commands": frozenset()})
        return snapshot

    def _build_snapshot(self) -> AppSnapshot:
        facts = self._store.load_snapshot_facts()
        plan = self._store.get_current_plan()
        active_session = self._store.get_active_session()
        current_operation = self._store.get_current_operation()
        snapshot = AppSnapshot(
            stage=facts.stage,
            profile_complete=facts.profile_complete,
            selected_style=plan.selected_style if plan is not None else None,
            active_session=active_session,
            current_operation=current_operation,
            available_commands=workflow.available_commands(facts),
        )
        _validate_plan_style(plan, self._styles)
        return snapshot

    def _reject_if_shutdown(self) -> None:
        if self._shutdown:
            raise Busy("application is shutting down")

    async def _reserve_generation_lock(self) -> None:
        if self._generation_lock.locked():
            raise Busy("another chat generation is active")
        await self._generation_lock.acquire()

    def _release_generation_lock(self) -> None:
        if self._generation_lock.locked():
            self._generation_lock.release()

    def _operation_task_name(self, operation: Operation) -> str:
        return f"operation:{operation.id}"

    def _schedule_operation(self, operation: Operation) -> None:
        if self._shutdown:
            return
        task = self._operation_task
        if task is not None and not task.done():
            if self._operation_task_id == operation.id:
                return
            pending = operation

            def _defer(_done: asyncio.Task[None]) -> None:
                self._schedule_operation(pending)

            task.add_done_callback(_defer)
            return

        if self._schedule_test_hook is not None:
            try:
                self._schedule_test_hook(operation)
            except ScheduleRejected:
                return
            except Exception as exc:
                logger.exception(
                    "failed to schedule operation operation_id=%s",
                    operation.id,
                )
                self._record_runtime_error(
                    phase="operation_schedule",
                    exc=exc,
                    operation_id=str(operation.id),
                )
                return

        coro = self._run_owned_operation(operation.id)
        try:
            created = asyncio.create_task(
                coro,
                name=self._operation_task_name(operation),
            )
        except Exception as exc:
            coro.close()
            logger.exception(
                "failed to schedule operation operation_id=%s",
                operation.id,
            )
            self._record_runtime_error(
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
            self._record_runtime_error(
                phase="operation_task",
                exc=exc,
                operation_id=str(operation_id),
            )
        finally:
            current = asyncio.current_task()
            self._clear_operation_ownership(expected=current)

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
                self._record(
                    "operation.started",
                    {
                        "kind": operation.kind.value,
                        "attempt": operation.attempt,
                    },
                )

                if operation.kind is OperationKind.ASSESSMENT:
                    assessment_input = await self._build_assessment_input(operation)
                    result = await self._assessment.assess(assessment_input)
                    async with self._mutation_lock:
                        before = await self._run_store(self._store.load_snapshot_facts)
                        to_stage = await self._run_store(
                            self._store.complete_assessment,
                            operation_id,
                            result=result.model_dump(mode="json"),
                            now=self._now(),
                        )
                    self._record(
                        "operation.completed",
                        {
                            "kind": operation.kind.value,
                            "attempt": operation.attempt,
                        },
                    )
                    self._record_transition_if_changed(
                        from_stage=before.stage,
                        to_stage=to_stage,
                        trigger="assessment_completed",
                    )
                elif operation.kind is OperationKind.POST_SESSION:
                    post_input = await self._build_post_session_input(operation)
                    result = await self._post_session.process(post_input)
                    stored = await self._run_store(self._store.get_profile)
                    session = await self._run_store(
                        self._store.get_session,
                        operation.source_session_id,
                    )
                    assert session is not None and session.plan_id is not None
                    plan_for_session = await self._load_plan_for_session(
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
                    self._record(
                        "operation.completed",
                        {
                            "kind": operation.kind.value,
                            "attempt": operation.attempt,
                        },
                    )
                    self._record_transition_if_changed(
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
        code, message, retryable = _classify_worker_error(exc)
        async with self._mutation_lock:
            current = await self._run_store(self._store.get_operation, operation_id)
            if current is None or current.status is not OperationStatus.RUNNING:
                logger.exception(
                    "operation worker failed after row left running operation_id=%s",
                    operation_id,
                    exc_info=exc,
                )
                self._record_runtime_error(
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
            self._record(
                "operation.failed",
                {
                    "kind": operation.kind.value,
                    "attempt": operation.attempt,
                    "error_code": operation.error_code or code,
                    "retryable": operation.retryable,
                },
            )

    async def _build_intake_turn_input(self, session_id: UUID) -> IntakeTurnInput:
        stored = await self._run_store(self._store.get_profile)
        session = await self._run_store(self._store.get_session, session_id)
        if stored is None or session is None:
            raise NotFound(f"session {session_id}")
        messages = await self._run_store(self._store.list_messages, session_id)
        transcript = messages_to_transcript(messages)
        latest_user = _latest_user_message_content(messages)
        previous_assistant = _previous_assistant_message_content(messages)
        record = _load_intake_record(session)
        patient_turn_count = sum(
            1 for message in messages if message.role is MessageRole.USER
        )
        return IntakeTurnInput(
            profile=stored.profile,
            current_record=record,
            transcript=transcript,
            latest_user_message=latest_user,
            previous_assistant_message=previous_assistant,
            patient_turn_count=patient_turn_count,
        )

    async def _build_therapy_turn_input(self, session_id: UUID) -> TherapyTurnInput:
        stored = await self._run_store(self._store.get_profile)
        session = await self._run_store(self._store.get_session, session_id)
        if stored is None or session is None or session.plan_id is None:
            raise NotFound(f"session {session_id}")
        plan = await self._load_plan_for_session(session_id, session.plan_id)
        style = self._styles.get(plan.selected_style)
        if style is None:
            raise InvariantViolation(f"unknown style: {plan.selected_style}")
        messages = await self._run_store(self._store.list_messages, session_id)
        transcript = messages_to_transcript(messages)
        latest_user = _latest_user_message_content(messages)
        if latest_user is None:
            raise InvariantViolation("therapy turn requires a user message")
        all_sessions = await self._run_store(self._store.list_sessions)
        summaries = _recent_session_summaries(
            all_sessions,
            exclude_session_id=session_id,
        )
        return TherapyTurnInput(
            profile=stored.profile,
            derived_profile=stored.derived_profile,
            current_plan=plan,
            session_briefing=plan.session_briefing,
            recent_session_summaries=summaries,
            transcript=transcript,
            latest_user_message=latest_user,
            is_opening_turn=False,
            selected_style=style,
        )

    async def _build_assessment_input(
        self,
        operation: Operation,
    ) -> AssessmentInput:
        session = await self._run_store(
            self._store.get_session,
            operation.source_session_id,
        )
        stored = await self._run_store(self._store.get_profile)
        if session is None or stored is None:
            raise NotFound(f"session {operation.source_session_id}")
        messages = await self._run_store(
            self._store.list_messages,
            operation.source_session_id,
        )
        return AssessmentInput(
            intake_record=_load_intake_record(session),
            transcript=messages_to_transcript(messages),
            profile=stored.profile,
            available_styles=tuple(self._styles.values()),
        )

    async def _build_post_session_input(
        self,
        operation: Operation,
    ) -> PostSessionInput:
        session = await self._run_store(
            self._store.get_session,
            operation.source_session_id,
        )
        stored = await self._run_store(self._store.get_profile)
        if session is None or stored is None or session.plan_id is None:
            raise NotFound(f"session {operation.source_session_id}")
        plan = await self._load_plan_for_session(
            operation.source_session_id,
            session.plan_id,
        )
        style = self._styles.get(plan.selected_style)
        if style is None:
            raise InvariantViolation(f"unknown style: {plan.selected_style}")
        messages = await self._run_store(
            self._store.list_messages,
            operation.source_session_id,
        )
        sessions = await self._run_store(self._store.list_sessions)
        return PostSessionInput(
            transcript=messages_to_transcript(messages),
            current_plan=plan,
            profile=stored.profile,
            derived_profile=stored.derived_profile,
            prior_session_briefing=_prior_session_briefing(
                sessions,
                source_session_id=operation.source_session_id,
                plan=plan,
            ),
            recent_session_summaries=_recent_session_summaries(
                sessions,
                exclude_session_id=operation.source_session_id,
            ),
            selected_style=style,
        )

    async def _load_plan_for_session(
        self,
        session_id: UUID,
        plan_id: UUID,
    ) -> Plan:
        plans = await self._run_store(
            self._store.list_plans_for_session,
            session_id,
        )
        for plan in plans:
            if plan.id == plan_id:
                return plan
        raise NotFound(f"plan {plan_id}")

    async def _load_message(self, session_id: UUID, message_id: UUID) -> Message:
        messages = await self._run_store(self._store.list_messages, session_id)
        for message in messages:
            if message.id == message_id:
                return message
        raise NotFound(f"message {message_id}")


def _latest_user_message_content(messages: list[Message]) -> str | None:
    for message in reversed(messages):
        if message.role is MessageRole.USER:
            return message.content
    return None


def _previous_assistant_message_content(messages: list[Message]) -> str | None:
    seen_latest_user = False
    for message in reversed(messages):
        if message.role is MessageRole.USER:
            if seen_latest_user:
                break
            seen_latest_user = True
            continue
        if message.role is MessageRole.ASSISTANT and seen_latest_user:
            return message.content
    return None


def _load_intake_record(session: Session) -> IntakeRecord:
    if session.intake_record:
        return IntakeRecord.model_validate(session.intake_record)
    return IntakeRecord()


def _response_has_content(text: str) -> bool:
    return bool(text.strip())


def _to_style_recommendation_view(
    recommendation: StyleRecommendation,
) -> StyleRecommendationView:
    return StyleRecommendationView(
        style_id=recommendation.style_id,
        score=recommendation.score,
        rationale=recommendation.rationale,
        key_topics=recommendation.key_topics,
    )


def _select_style_recommendation(
    result: AssessmentResult,
    style_id: str,
) -> StyleRecommendation:
    for recommendation in result.style_recommendations:
        if recommendation.style_id == style_id:
            return recommendation
    raise InvalidCommand(f"style {style_id} is not in assessment recommendations")


def _validate_plan_style(
    plan: Plan | None,
    styles: MappingProxyType[str, StyleDefinition],
) -> None:
    if plan is not None and plan.selected_style not in styles:
        raise InvariantViolation(f"unknown style: {plan.selected_style}")


def _recent_session_summaries(
    sessions: list[Session],
    *,
    exclude_session_id: UUID,
    limit: int = _RECENT_SUMMARY_LIMIT,
) -> tuple[str, ...]:
    summaries: list[str] = []
    for session in sessions:
        if session.id == exclude_session_id:
            continue
        if session.kind is not SessionKind.THERAPY:
            continue
        if session.ended_at is None or not session.summary:
            continue
        summaries.append(session.summary)
        if len(summaries) >= limit:
            break
    return tuple(summaries)


def _prior_session_briefing(
    sessions: list[Session],
    *,
    source_session_id: UUID,
    plan: Plan,
) -> dict[str, Any] | None:
    if plan.session_briefing is not None:
        return plan.session_briefing
    for session in sessions:
        if session.id == source_session_id:
            continue
        if session.kind is not SessionKind.THERAPY:
            continue
        if session.ended_at is not None and session.briefing is not None:
            return session.briefing
    return None


_PUBLIC_WORK_ERROR_MESSAGES = {
    "llm_unavailable": "The language model is currently unavailable.",
    "llm_timeout": "The language model request timed out.",
    "invalid_llm_output": "The language model returned an invalid response.",
    "internal_error": "An unexpected error occurred.",
}


def _classify_worker_error(exc: Exception) -> tuple[str, str, bool]:
    if isinstance(exc, LLMError):
        return (
            exc.code,
            _PUBLIC_WORK_ERROR_MESSAGES.get(
                exc.code,
                "The language model request failed.",
            ),
            exc.retryable,
        )
    return "internal_error", "An unexpected error occurred.", False
