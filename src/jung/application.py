"""Target application use-case coordinator."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from types import MappingProxyType
from typing import Any, TypeVar
from uuid import UUID

from pydantic import ValidationError

from jung import workflow
from jung.domain.commands import (
    EndSession,
    RetryOperation,
    SelectStyle,
    SendMessage,
    StartSession,
    UpdateProfile,
)
from jung.domain.errors import (
    Busy,
    InvalidCommand,
    InvariantViolation,
    NotFound,
    StoredWorkFailure,
)
from jung.domain.models import (
    AppSnapshot,
    ChatTurn,
    ChatTurnStatus,
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
    ProfileView,
    SessionHistory,
    StartedSession,
    StyleOptions,
    StyleRecommendationView,
    StyleSummary,
)
from jung.events import (
    ChatTokenGenerated,
    ChatTurnAccepted,
    ChatTurnCompleted,
    ChatTurnFailed,
    EventStream,
    OperationChanged,
    SnapshotChanged,
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
from jung.supervisor import SupervisorClosed, TaskSupervisor

logger = logging.getLogger(__name__)

_RECENT_SUMMARY_LIMIT = 5
_T = TypeVar("_T")


class ChatScheduleOutcomeKind(Enum):
    STARTED = auto()
    SUPERVISOR_CLOSED = auto()
    DUPLICATE_ACTIVE = auto()
    UNEXPECTED = auto()


@dataclass(frozen=True, slots=True)
class ChatScheduleOutcome:
    kind: ChatScheduleOutcomeKind
    error: BaseException | None = None


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
        events: EventStream,
        supervisor: TaskSupervisor,
        now: Callable[[], datetime],
        new_id: Callable[[], UUID],
    ) -> None:
        self._store = store
        self._intake = intake
        self._assessment = assessment
        self._therapy = therapy
        self._post_session = post_session
        self._styles = styles
        self._events = events
        self._supervisor = supervisor
        self._now = now
        self._new_id = new_id
        self._mutation_lock = asyncio.Lock()
        self._generation_lock = asyncio.Lock()
        self._shutdown = False

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown

    def begin_shutdown(self) -> None:
        self._shutdown = True

    async def _run_store(
        self, fn: Callable[..., _T], /, *args: Any, **kwargs: Any
    ) -> _T:
        # Bounded shutdown applies around LLM/background work; an already-running
        # local SQLite call is allowed to finish before the mutation lock releases.
        task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancellation:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break

            if not task.cancelled():
                try:
                    task.result()
                except Exception:
                    logger.exception(
                        "store call failed after caller cancellation function=%s",
                        getattr(fn, "__name__", repr(fn)),
                    )

            raise cancellation

    async def recover_on_startup(self) -> AppSnapshot:
        async with self._mutation_lock:
            await self._run_store(
                self._store.recover_stale_operations,
                now=self._now(),
            )
            await self._run_store(
                self._store.recover_stale_chat_turns,
                now=self._now(),
            )
            snapshot = await self._assemble_snapshot_locked()
        if snapshot.current_operation is not None:
            if snapshot.current_operation.status is OperationStatus.PENDING:
                self._schedule_operation(snapshot.current_operation)
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

    async def get_chat_turn(self, turn_id: UUID) -> ChatTurn:
        turn = await self._run_store(self._store.get_chat_turn, turn_id)
        if turn is None:
            raise NotFound(f"chat turn {turn_id}")
        return turn

    async def update_profile(self, command: UpdateProfile) -> AppSnapshot:
        self._reject_if_shutdown()
        async with self._mutation_lock:
            self._reject_if_shutdown()
            facts = await self._run_store(self._store.load_snapshot_facts)
            workflow.require_command_allowed(CommandName.UPDATE_PROFILE, facts)
            intake_session_id = (
                self._new_id()
                if facts.stage is Stage.SETUP and is_profile_complete(command.profile)
                else None
            )
            await self._run_store(
                self._store.update_profile,
                command.profile,
                expected_revision=command.expected_revision,
                intake_session_id=intake_session_id,
                now=self._now(),
            )
            snapshot = await self._assemble_snapshot_locked()
        await self._events.publish(SnapshotChanged(snapshot))
        return snapshot

    async def select_style(self, command: SelectStyle) -> AppSnapshot:
        self._reject_if_shutdown()
        if command.style_id not in self._styles:
            raise InvalidCommand(f"unknown style: {command.style_id}")
        async with self._mutation_lock:
            self._reject_if_shutdown()
            facts = await self._run_store(self._store.load_snapshot_facts)
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
                expected_revision=command.expected_revision,
                style_id=command.style_id,
                plan_id=plan_id,
                content=recommendation.initial_plan,
                intake_session_id=operation.source_session_id,
                now=self._now(),
            )
            snapshot = await self._assemble_snapshot_locked()
        await self._events.publish(SnapshotChanged(snapshot))
        return snapshot

    async def start_session(self, command: StartSession) -> StartedSession:
        self._reject_if_shutdown()
        session_id = self._new_id()
        async with self._mutation_lock:
            self._reject_if_shutdown()
            facts = await self._run_store(self._store.load_snapshot_facts)
            workflow.require_command_allowed(CommandName.START_SESSION, facts)
            _, session = await self._run_store(
                self._store.start_therapy_session,
                expected_revision=command.expected_revision,
                session_id=session_id,
                now=self._now(),
            )
            snapshot = await self._assemble_snapshot_locked()
            started = StartedSession(session=session, snapshot=snapshot)
        await self._events.publish(SnapshotChanged(started.snapshot))
        return started

    async def end_session(self, command: EndSession) -> AppSnapshot:
        self._reject_if_shutdown()
        operation_id = self._new_id()
        operation: Operation | None = None
        snapshot: AppSnapshot | None = None
        try:
            async with self._mutation_lock:
                self._reject_if_shutdown()
                facts = await self._run_store(self._store.load_snapshot_facts)
                workflow.require_command_allowed(CommandName.END_SESSION, facts)
                session = await self._run_store(
                    self._store.get_session,
                    command.session_id,
                )
                if session is None:
                    raise NotFound("session")
                active = await self._run_store(self._store.get_active_session)
                if active is None or active.id != command.session_id:
                    raise InvalidCommand("session_id does not match the active session")
                if active.kind is not SessionKind.THERAPY:
                    raise InvalidCommand("active session is not therapy")
                _, operation = await self._run_store(
                    self._store.end_therapy_session,
                    expected_revision=command.expected_revision,
                    session_id=command.session_id,
                    operation_id=operation_id,
                    now=self._now(),
                )
                snapshot = await self._assemble_snapshot_locked()
            await self._publish_pending_operation_changed(operation, snapshot)
            return snapshot
        finally:
            if operation is not None:
                self._schedule_operation(operation)

    async def retry_operation(self, command: RetryOperation) -> AppSnapshot:
        self._reject_if_shutdown()
        operation: Operation | None = None
        snapshot: AppSnapshot | None = None
        try:
            async with self._mutation_lock:
                self._reject_if_shutdown()
                facts = await self._run_store(self._store.load_snapshot_facts)
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
                    expected_revision=command.expected_revision,
                    now=self._now(),
                )
                snapshot = await self._assemble_snapshot_locked()
            await self._publish_pending_operation_changed(operation, snapshot)
            return snapshot
        finally:
            if operation is not None:
                self._schedule_operation(operation)

    async def _require_generation_available_locked(
        self,
        *,
        retrying_turn_id: UUID | None = None,
    ) -> None:
        facts = await self._run_store(self._store.load_snapshot_facts)
        if facts.chat_turn_status is ChatTurnStatus.PENDING:
            if retrying_turn_id is None:
                raise Busy("another chat generation is active")
            active = await self._run_store(self._store.get_active_chat_turn)
            if active is not None and active.id != retrying_turn_id:
                raise Busy("another chat generation is active")
        if self._generation_lock.locked():
            raise Busy("another chat generation is active")

    def _accepted_chat_events(
        self,
        turn: ChatTurn,
        snapshot: AppSnapshot,
        request_id: UUID | None,
    ) -> list[Any]:
        return [
            ChatTurnAccepted(
                session_id=turn.session_id,
                turn_id=turn.id,
                request_id=request_id,
                turn=turn,
            ),
            SnapshotChanged(snapshot),
        ]

    async def _retry_existing_chat_turn_locked(
        self,
        existing: ChatTurn,
        command: SendMessage,
    ) -> tuple[ChatTurn, list[Any]]:
        """Persist a retry after the generation lock has already been reserved."""
        turn = await self._run_store(
            self._store.retry_chat_turn,
            existing.id,
            expected_revision=command.expected_revision,
            now=self._now(),
        )
        snapshot = await self._assemble_snapshot_locked()
        return turn, self._accepted_chat_events(turn, snapshot, command.request_id)

    async def submit_message(self, command: SendMessage) -> ChatTurn:
        self._reject_if_shutdown()
        generation_reserved = False
        pending_events: list[Any] = []
        turn: ChatTurn | None = None
        handoff_on_cancel: ChatTurn | None = None
        try:
            async with self._mutation_lock:
                self._reject_if_shutdown()
                existing = await self._run_store(
                    self._store.get_chat_turn_by_client_id,
                    command.session_id,
                    command.client_message_id,
                )
                if existing is not None:
                    if existing.status is ChatTurnStatus.PENDING:
                        return existing
                    if existing.status is ChatTurnStatus.COMPLETE:
                        return existing
                    if existing.status is ChatTurnStatus.FAILED:
                        if not existing.retryable:
                            raise StoredWorkFailure.from_chat_turn(existing)
                        await self._require_generation_available_locked(
                            retrying_turn_id=existing.id,
                        )
                        if not await self._chat_retry_structurally_eligible(existing):
                            raise StoredWorkFailure(
                                code=existing.error_code or "operation_failed",
                                message=existing.error_message or "chat turn failed",
                                retryable=False,
                            )
                        await self._reserve_generation_lock()
                        generation_reserved = True
                        (
                            turn,
                            pending_events,
                        ) = await self._retry_existing_chat_turn_locked(
                            existing,
                            command,
                        )

                if turn is None:
                    await self._require_generation_available_locked()
                    facts = await self._run_store(self._store.load_snapshot_facts)
                    workflow.require_command_allowed(CommandName.SEND_MESSAGE, facts)
                    if not command.content.strip():
                        raise InvalidCommand("message content must be non-empty")
                    await self._reserve_generation_lock()
                    generation_reserved = True
                    turn_id = self._new_id()
                    user_message_id = self._new_id()
                    _, turn = await self._run_store(
                        self._store.accept_chat_message,
                        expected_revision=command.expected_revision,
                        session_id=command.session_id,
                        client_message_id=command.client_message_id,
                        turn_id=turn_id,
                        user_message_id=user_message_id,
                        content=command.content,
                        now=self._now(),
                    )
                    snapshot = await self._assemble_snapshot_locked()
                    pending_events = self._accepted_chat_events(
                        turn,
                        snapshot,
                        command.request_id,
                    )
        except asyncio.CancelledError:
            if generation_reserved:
                if turn is not None:
                    handoff_on_cancel = turn
                else:
                    self._release_generation_lock()
            raise
        except Exception:
            if generation_reserved:
                self._release_generation_lock()
            raise
        finally:
            if handoff_on_cancel is not None:
                outcome = self._try_start_chat_worker(
                    handoff_on_cancel,
                    request_id=command.request_id,
                )
                if outcome.kind is not ChatScheduleOutcomeKind.STARTED:
                    self._release_generation_lock()

        assert turn is not None
        if not pending_events:
            return turn
        return await self._handoff_accepted_chat_turn(
            turn,
            pending_events,
            command.request_id,
        )

    async def _handoff_accepted_chat_turn(
        self,
        turn: ChatTurn,
        pending_events: list[Any],
        request_id: UUID | None,
    ) -> ChatTurn:
        try:
            for event in pending_events:
                await self._events.publish(event)
        except asyncio.CancelledError:
            outcome = self._try_start_chat_worker(turn, request_id=request_id)
            if outcome.kind is ChatScheduleOutcomeKind.STARTED:
                raise
            self._release_generation_lock()
            raise
        except Exception:
            logger.exception(
                "failed to publish accepted chat events turn_id=%s",
                turn.id,
            )

        outcome = self._try_start_chat_worker(turn, request_id=request_id)
        return await self._resolve_chat_schedule_outcome(turn, outcome)

    async def _assemble_snapshot_locked(self) -> AppSnapshot:
        return await self._run_store(self._build_snapshot)

    def _build_snapshot(self) -> AppSnapshot:
        state = self._store.get_app_state()
        facts = self._store.load_snapshot_facts()
        plan = self._store.get_current_plan()
        active_session = self._store.get_active_session()
        current_operation = self._store.get_current_operation()
        active_chat_turn = self._store.get_active_chat_turn()
        snapshot = AppSnapshot(
            revision=state.revision,
            stage=state.stage,
            profile_complete=facts.profile_complete,
            selected_style=plan.selected_style if plan is not None else None,
            active_session=active_session,
            current_operation=current_operation,
            active_chat_turn=active_chat_turn,
            available_commands=workflow.available_commands(facts),
        )
        _validate_snapshot_invariants(snapshot, plan, self._styles)
        return snapshot

    def _reject_if_shutdown(self) -> None:
        if self._shutdown:
            raise Busy("application is shutting down")

    async def _reserve_generation_lock(self) -> None:
        if self._generation_lock.locked():
            raise Busy("another chat generation is active")
        await self._generation_lock.acquire()

    async def _chat_retry_structurally_eligible(self, turn: ChatTurn) -> bool:
        session = await self._run_store(self._store.get_session, turn.session_id)
        if session is None or session.ended_at is not None:
            return False
        active = await self._run_store(self._store.get_active_session)
        if active is None or active.id != turn.session_id:
            return False
        state = await self._run_store(self._store.get_app_state)
        if state.stage is Stage.INTAKE and session.kind is SessionKind.INTAKE:
            pass
        elif state.stage is Stage.THERAPY and session.kind is SessionKind.THERAPY:
            pass
        else:
            return False
        messages = await self._run_store(self._store.list_messages, turn.session_id)
        if not messages or messages[-1].id != turn.user_message_id:
            return False
        return True

    def _release_generation_lock(self) -> None:
        if self._generation_lock.locked():
            self._generation_lock.release()

    def _try_start_chat_worker(
        self,
        turn: ChatTurn,
        *,
        request_id: UUID | None,
    ) -> ChatScheduleOutcome:
        name = f"chat:{turn.id}"
        try:
            started = self._supervisor.start(
                name=name,
                run=lambda: self._run_chat_worker(
                    turn.id,
                    turn.session_id,
                    request_id,
                ),
            )
        except SupervisorClosed:
            return ChatScheduleOutcome(ChatScheduleOutcomeKind.SUPERVISOR_CLOSED)
        except Exception as exc:
            return ChatScheduleOutcome(ChatScheduleOutcomeKind.UNEXPECTED, exc)
        if started:
            return ChatScheduleOutcome(ChatScheduleOutcomeKind.STARTED)
        return ChatScheduleOutcome(ChatScheduleOutcomeKind.DUPLICATE_ACTIVE)

    async def _resolve_chat_schedule_outcome(
        self,
        turn: ChatTurn,
        outcome: ChatScheduleOutcome,
    ) -> ChatTurn:
        if outcome.kind is ChatScheduleOutcomeKind.STARTED:
            return turn
        if outcome.kind is ChatScheduleOutcomeKind.SUPERVISOR_CLOSED:
            self._release_generation_lock()
            return turn
        if outcome.kind is ChatScheduleOutcomeKind.UNEXPECTED:
            logger.error(
                "failed to schedule chat turn_id=%s",
                turn.id,
                exc_info=outcome.error,
            )
        self._release_generation_lock()
        return await self._persist_chat_schedule_failure(turn)

    async def _persist_chat_schedule_failure(self, turn: ChatTurn) -> ChatTurn:
        async with self._mutation_lock:
            failed = await self._run_store(
                self._store.fail_chat_turn,
                turn.id,
                error_code="internal_error",
                error_message="Failed to schedule chat generation",
                retryable=True,
                now=self._now(),
            )
            snapshot = await self._assemble_snapshot_locked()
        try:
            await self._events.publish(
                ChatTurnFailed(
                    session_id=turn.session_id,
                    turn_id=turn.id,
                    turn=failed,
                )
            )
            await self._events.publish(SnapshotChanged(snapshot))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "failed to publish chat schedule failure turn_id=%s",
                turn.id,
            )
        return failed

    async def _publish_non_authoritative(self, event: Any) -> None:
        try:
            await self._events.publish(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "failed to publish non-authoritative event event_type=%s",
                type(event).__name__,
            )

    async def _publish_pending_operation_changed(
        self,
        operation: Operation,
        snapshot: AppSnapshot,
    ) -> None:
        try:
            await self._events.publish(OperationChanged(operation, snapshot))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "failed to publish pending operation event operation_id=%s",
                operation.id,
            )

    def _operation_task_name(self, operation: Operation) -> str:
        return f"operation:{operation.id}:attempt:{operation.attempt + 1}"

    def _schedule_operation(self, operation: Operation) -> None:
        name = self._operation_task_name(operation)
        try:
            started = self._supervisor.start(
                name=name,
                run=lambda: self._run_operation_worker(operation.id),
            )
            if not started:
                logger.debug(
                    "operation attempt already scheduled operation_id=%s name=%s",
                    operation.id,
                    name,
                )
        except SupervisorClosed:
            return
        except Exception:
            logger.exception(
                "failed to schedule operation operation_id=%s",
                operation.id,
            )

    async def _run_chat_worker(
        self,
        turn_id: UUID,
        session_id: UUID,
        request_id: UUID | None,
    ) -> None:
        try:
            session = await self._run_store(self._store.get_session, session_id)
            if session is None:
                raise NotFound(f"session {session_id}")
            if session.kind is SessionKind.INTAKE:
                await self._generate_intake_response(turn_id, session_id, request_id)
            elif session.kind is SessionKind.THERAPY:
                await self._generate_therapy_response(turn_id, session_id, request_id)
            else:
                raise InvariantViolation(f"unsupported session kind: {session.kind}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "chat worker failed turn_id=%s session_id=%s",
                turn_id,
                session_id,
            )
            await self._persist_chat_failure_if_pending(turn_id, session_id, exc)
        finally:
            self._release_generation_lock()

    async def _generate_intake_response(
        self,
        turn_id: UUID,
        session_id: UUID,
        request_id: UUID | None,
    ) -> None:
        turn_input = await self._build_intake_turn_input(session_id)
        plan = await self._intake.prepare_turn(turn_input)
        response_text = await self._stream_chat_tokens(
            self._intake.stream_response(plan),
            session_id=session_id,
            turn_id=turn_id,
            request_id=request_id,
        )
        if not _response_has_content(response_text):
            raise InvalidLLMOutput(
                "assistant response must contain non-whitespace text"
            )
        if plan.completeness_complete:
            await self._complete_final_intake(
                turn_id,
                session_id,
                response_text,
                plan.merged_record,
            )
        else:
            await self._complete_ordinary_chat(
                turn_id,
                session_id,
                response_text,
                intake_record=plan.merged_record,
            )

    async def _generate_therapy_response(
        self,
        turn_id: UUID,
        session_id: UUID,
        request_id: UUID | None,
    ) -> None:
        turn_input = await self._build_therapy_turn_input(session_id)
        response_text = await self._stream_chat_tokens(
            self._therapy.stream_response(turn_input),
            session_id=session_id,
            turn_id=turn_id,
            request_id=request_id,
        )
        if not _response_has_content(response_text):
            raise InvalidLLMOutput(
                "assistant response must contain non-whitespace text"
            )
        await self._complete_ordinary_chat(turn_id, session_id, response_text)

    async def _stream_chat_tokens(
        self,
        chunks: Any,
        *,
        session_id: UUID,
        turn_id: UUID,
        request_id: UUID | None,
    ) -> str:
        buffer: list[str] = []
        sequence = 0
        async for chunk in chunks:
            if not chunk:
                continue
            buffer.append(chunk)
            sequence += 1
            await self._events.publish(
                ChatTokenGenerated(
                    session_id=session_id,
                    turn_id=turn_id,
                    request_id=request_id,
                    sequence=sequence,
                    text=chunk,
                )
            )
        return "".join(buffer)

    async def _complete_ordinary_chat(
        self,
        turn_id: UUID,
        session_id: UUID,
        content: str,
        *,
        intake_record: IntakeRecord | None = None,
    ) -> None:
        assistant_message_id = self._new_id()
        intake_payload = (
            intake_record.model_dump(mode="json") if intake_record is not None else None
        )
        async with self._mutation_lock:
            turn = await self._run_store(
                self._store.complete_chat_turn,
                turn_id,
                assistant_message_id=assistant_message_id,
                content=content,
                intake_record=intake_payload,
                now=self._now(),
            )
            snapshot = await self._assemble_snapshot_locked()
        assistant_message = await self._load_message(session_id, assistant_message_id)
        await self._events.publish(
            ChatTurnCompleted(
                session_id=session_id,
                turn_id=turn_id,
                turn=turn,
                assistant_message=assistant_message,
            )
        )
        await self._events.publish(SnapshotChanged(snapshot))

    async def _complete_final_intake(
        self,
        turn_id: UUID,
        session_id: UUID,
        content: str,
        intake_record: IntakeRecord,
    ) -> None:
        assistant_message_id = self._new_id()
        operation_id = self._new_id()
        operation: Operation | None = None
        try:
            async with self._mutation_lock:
                turn, operation, _state = await self._run_store(
                    self._store.complete_final_intake_turn,
                    turn_id,
                    assistant_message_id=assistant_message_id,
                    content=content,
                    intake_record=intake_record.model_dump(mode="json"),
                    operation_id=operation_id,
                    now=self._now(),
                )
                snapshot = await self._assemble_snapshot_locked()
            assistant_message = await self._load_message(
                session_id, assistant_message_id
            )
            await self._publish_non_authoritative(
                ChatTurnCompleted(
                    session_id=session_id,
                    turn_id=turn_id,
                    turn=turn,
                    assistant_message=assistant_message,
                )
            )
            await self._publish_non_authoritative(OperationChanged(operation, snapshot))
            await self._publish_non_authoritative(SnapshotChanged(snapshot))
        finally:
            if operation is not None:
                self._schedule_operation(operation)

    async def _persist_chat_failure_if_pending(
        self,
        turn_id: UUID,
        session_id: UUID,
        exc: Exception,
    ) -> None:
        code, message, retryable = _classify_worker_error(exc)
        async with self._mutation_lock:
            current = await self._run_store(self._store.get_chat_turn, turn_id)
            if current is None or current.status is not ChatTurnStatus.PENDING:
                logger.exception(
                    "chat worker failed after turn left pending turn_id=%s",
                    turn_id,
                    exc_info=exc,
                )
                return
            turn = await self._run_store(
                self._store.fail_chat_turn,
                turn_id,
                error_code=code,
                error_message=message,
                retryable=retryable,
                now=self._now(),
            )
            snapshot = await self._assemble_snapshot_locked()
        await self._events.publish(
            ChatTurnFailed(session_id=session_id, turn_id=turn_id, turn=turn)
        )
        await self._events.publish(SnapshotChanged(snapshot))

    async def _run_operation_worker(self, operation_id: UUID) -> None:
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
                snapshot = await self._assemble_snapshot_locked()
            try:
                await self._events.publish(OperationChanged(operation, snapshot))
            except Exception:
                logger.exception(
                    "failed to publish operation running event operation_id=%s",
                    operation_id,
                )

            if operation.kind is OperationKind.ASSESSMENT:
                assessment_input = await self._build_assessment_input(operation)
                result = await self._assessment.assess(assessment_input)
                async with self._mutation_lock:
                    await self._run_store(
                        self._store.complete_assessment,
                        operation_id,
                        result=result.model_dump(mode="json"),
                        now=self._now(),
                    )
                    snapshot = await self._assemble_snapshot_locked()
                completed = await self._run_store(
                    self._store.get_operation,
                    operation_id,
                )
                assert completed is not None
                await self._events.publish(OperationChanged(completed, snapshot))
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
                merged_plan = merge_plan_content(plan_for_session, result.plan_patch)
                new_plan = (
                    NewPlanRevision(
                        plan_id=self._new_id(),
                        content=merged_plan,
                    )
                    if merged_plan is not None
                    else None
                )
                async with self._mutation_lock:
                    await self._run_store(
                        self._store.complete_post_session,
                        operation_id,
                        summary=result.session_summary,
                        briefing=result.session_briefing.model_dump(mode="json"),
                        derived_profile=merged_profile,
                        new_plan=new_plan,
                        now=self._now(),
                    )
                    snapshot = await self._assemble_snapshot_locked()
                completed = await self._run_store(
                    self._store.get_operation,
                    operation_id,
                )
                assert completed is not None
                await self._events.publish(OperationChanged(completed, snapshot))
            else:
                raise InvariantViolation(f"unknown operation kind: {operation.kind}")
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
                return
            operation = await self._run_store(
                self._store.fail_operation,
                operation_id,
                error_code=code,
                error_message=message,
                retryable=retryable,
                now=self._now(),
            )
            snapshot = await self._assemble_snapshot_locked()
        try:
            await self._events.publish(OperationChanged(operation, snapshot))
        except Exception:
            logger.exception(
                "failed to publish operation failure event operation_id=%s",
                operation_id,
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


def _validate_snapshot_invariants(
    snapshot: AppSnapshot,
    plan: Plan | None,
    styles: MappingProxyType[str, StyleDefinition],
) -> None:
    stage = snapshot.stage
    if stage is Stage.SETUP and snapshot.active_session is not None:
        raise InvariantViolation("SETUP must not have an active session")
    if stage is Stage.INTAKE:
        if (
            snapshot.active_session is None
            or snapshot.active_session.kind is not SessionKind.INTAKE
        ):
            raise InvariantViolation("INTAKE requires an open intake session")
    if stage is Stage.THERAPY:
        if (
            snapshot.active_session is None
            or snapshot.active_session.kind is not SessionKind.THERAPY
        ):
            raise InvariantViolation("THERAPY requires an open therapy session")
    if stage is Stage.READY:
        if snapshot.active_session is not None:
            raise InvariantViolation("READY must not have an active session")
        if snapshot.current_operation is not None:
            raise InvariantViolation("READY must not have a current operation")
    if stage is Stage.ASSESSMENT:
        if (
            snapshot.current_operation is None
            or snapshot.current_operation.kind is not OperationKind.ASSESSMENT
        ):
            raise InvariantViolation("ASSESSMENT requires an assessment operation")
    if stage is Stage.POST_SESSION:
        if (
            snapshot.current_operation is None
            or snapshot.current_operation.kind is not OperationKind.POST_SESSION
        ):
            raise InvariantViolation("POST_SESSION requires a post-session operation")
    if snapshot.active_chat_turn is not None and stage not in {
        Stage.INTAKE,
        Stage.THERAPY,
    }:
        raise InvariantViolation(
            "pending chat turn is only allowed in INTAKE or THERAPY"
        )
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
