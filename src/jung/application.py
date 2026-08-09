"""Target application use-case coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from datetime import datetime
from types import MappingProxyType
from typing import Any, TypeVar
from uuid import UUID

from pydantic import ValidationError

from jung import workflow
from jung._application import diagnostics as diag
from jung._application.chat import ChatRuntime
from jung._application.inputs import PhaseInputs
from jung._application.operations import OperationRuntime
from jung._application.store_calls import run_store_call
from jung.diagnostics import DiagnosticRecorder, diagnostic_context
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
    ChatStreamResult,
    ProfileView,
    SessionHistory,
    StartedSession,
    StyleOptions,
    StyleRecommendationView,
    StyleSummary,
)
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import (
    AssessmentResult,
    StyleRecommendation,
)
from jung.phases.assessment.processor import AssessmentProcessor
from jung.phases.assessment.validation import validate_and_normalize_assessment
from jung.phases.intake.processor import IntakeProcessor
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.therapy.processor import TherapyProcessor
from jung.styles import StyleDefinition

_T = TypeVar("_T")

_COMMAND_REJECT_TYPES = (
    InvalidCommand,
    Busy,
    NotFound,
)


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
        self._styles = styles
        self._now = now
        self._new_id = new_id
        self._recorder = recorder
        self._mutation_lock = asyncio.Lock()
        self._shutdown_started = asyncio.Event()

        self._inputs = PhaseInputs(
            store=store,
            styles=styles,
            recorder=recorder,
        )
        self._operations = OperationRuntime(
            store=store,
            assessment=assessment,
            post_session=post_session,
            inputs=self._inputs,
            mutation_lock=self._mutation_lock,
            shutdown_started=self._shutdown_started,
            now=now,
            new_id=new_id,
            recorder=recorder,
        )
        self._chat = ChatRuntime(
            store=store,
            intake=intake,
            therapy=therapy,
            inputs=self._inputs,
            operations=self._operations,
            mutation_lock=self._mutation_lock,
            shutdown_started=self._shutdown_started,
            now=now,
            new_id=new_id,
            recorder=recorder,
        )

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown_started.is_set()

    async def shutdown(self, *, timeout_seconds: float) -> None:
        self._shutdown_started.set()
        await self._operations.shutdown(timeout_seconds=timeout_seconds)

    async def _run_store(
        self, fn: Callable[..., _T], /, *args: Any, **kwargs: Any
    ) -> _T:
        return await run_store_call(fn, *args, recorder=self._recorder, **kwargs)

    async def recover_on_startup(self) -> AppSnapshot:
        async with self._mutation_lock:
            if self._operations.has_live_task:
                return await self._assemble_snapshot_locked()
            recovered = await self._run_store(
                self._store.recover_stale_operation,
                now=self._now(),
            )
            snapshot = await self._assemble_snapshot_locked()

        pending = snapshot.current_operation
        if pending is not None and pending.status is OperationStatus.PENDING:
            self._operations.schedule(pending)

        if recovered is not None:
            with diagnostic_context(
                operation_id=str(recovered.id),
                session_id=str(recovered.source_session_id),
            ):
                diag.record(
                    self._recorder,
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
        diag.record_command_started(self._recorder, "update_profile")
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
            diag.record_command_completed(self._recorder, "update_profile", "committed")
            diag.record_transition(
                self._recorder,
                from_stage=from_stage,
                to_stage=snapshot.stage,
                trigger="update_profile",
            )
            return snapshot
        except _COMMAND_REJECT_TYPES as exc:
            diag.record_command_rejected(self._recorder, "update_profile", exc)
            raise
        except Exception as exc:
            diag.record_command_error(self._recorder, "update_profile", exc)
            raise

    async def select_style(self, command: SelectStyle) -> AppSnapshot:
        diag.record_command_started(self._recorder, "select_style")
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
            diag.record_command_completed(self._recorder, "select_style", "committed")
            diag.record_transition(
                self._recorder,
                from_stage=from_stage,
                to_stage=snapshot.stage,
                trigger="select_style",
            )
            return snapshot
        except _COMMAND_REJECT_TYPES as exc:
            diag.record_command_rejected(self._recorder, "select_style", exc)
            raise
        except Exception as exc:
            diag.record_command_error(self._recorder, "select_style", exc)
            raise

    async def start_session(self) -> StartedSession:
        diag.record_command_started(self._recorder, "start_session")
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
            diag.record_command_completed(self._recorder, "start_session", "committed")
            diag.record_transition(
                self._recorder,
                from_stage=from_stage,
                to_stage=started.snapshot.stage,
                trigger="start_session",
            )
            return started
        except _COMMAND_REJECT_TYPES as exc:
            diag.record_command_rejected(self._recorder, "start_session", exc)
            raise
        except Exception as exc:
            diag.record_command_error(self._recorder, "start_session", exc)
            raise

    async def end_session(self, command: EndSession) -> AppSnapshot:
        diag.record_command_started(self._recorder, "end_session")
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
                    diag.record(
                        self._recorder,
                        "operation.created",
                        {
                            "kind": operation.kind.value,
                            "attempt": operation.attempt,
                        },
                    )
                diag.record_command_completed(
                    self._recorder, "end_session", "committed"
                )
                if from_stage is not None:
                    diag.record_transition(
                        self._recorder,
                        from_stage=from_stage,
                        to_stage=snapshot.stage,
                        trigger="end_session",
                    )
                return snapshot
            finally:
                if operation is not None:
                    self._operations.schedule(operation)
        except _COMMAND_REJECT_TYPES as exc:
            diag.record_command_rejected(self._recorder, "end_session", exc)
            raise
        except Exception as exc:
            diag.record_command_error(self._recorder, "end_session", exc)
            raise

    async def retry_operation(self) -> AppSnapshot:
        diag.record_command_started(self._recorder, "retry_operation")
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
                    diag.record(
                        self._recorder,
                        "operation.retried",
                        {
                            "kind": operation.kind.value,
                            "attempt": operation.attempt,
                        },
                    )
                diag.record_command_completed(
                    self._recorder, "retry_operation", "committed"
                )
                if from_stage is not None:
                    diag.record_transition(
                        self._recorder,
                        from_stage=from_stage,
                        to_stage=snapshot.stage,
                        trigger="retry_operation",
                    )
                return snapshot
            finally:
                if operation is not None:
                    self._operations.schedule(operation)
        except _COMMAND_REJECT_TYPES as exc:
            diag.record_command_rejected(self._recorder, "retry_operation", exc)
            raise
        except Exception as exc:
            diag.record_command_error(self._recorder, "retry_operation", exc)
            raise

    async def stream_message(
        self, command: SendMessage
    ) -> AsyncIterator[ChatStreamResult]:
        async with aclosing(self._chat.stream_message(command)) as stream:
            async for item in stream:
                yield item

    def _reject_if_generation_active(self) -> None:
        if self._chat.generation_active:
            raise Busy("another chat generation is active")

    def _reject_if_shutdown(self) -> None:
        if self._shutdown_started.is_set():
            raise Busy("application is shutting down")

    async def _assemble_snapshot_locked(self) -> AppSnapshot:
        snapshot = await self._run_store(self._build_snapshot)
        if self._chat.generation_active:
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
