"""Connection-owned chat generation lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from datetime import datetime
from uuid import UUID

from jung import workflow
from jung._application import diagnostics as diag
from jung._application.inputs import PhaseInputs
from jung._application.operations import OperationRuntime
from jung._application.store_calls import run_store_call
from jung._application.work_errors import _classify_work_error
from jung._async_cleanup import drain_cancelled_task
from jung.diagnostics import DiagnosticRecorder, diagnostic_context
from jung.domain.commands import SendMessage
from jung.domain.errors import (
    Busy,
    InvalidCommand,
    InvariantViolation,
    NotFound,
)
from jung.domain.models import (
    CommandName,
    Message,
    MessageRole,
    SessionKind,
    Stage,
)
from jung.domain.results import (
    ChatCompleted,
    ChatFailed,
    ChatStreamResult,
    ChatToken,
)
from jung.llm.errors import InvalidLLMOutput, LLMError
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.intake.models import IntakeRecord
from jung.phases.intake.processor import IntakeProcessor
from jung.phases.therapy.processor import TherapyProcessor

_COMMAND_REJECT_TYPES = (
    InvalidCommand,
    Busy,
    NotFound,
)


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


class ChatRuntime:
    def __init__(
        self,
        *,
        store: SQLiteStore,
        intake: IntakeProcessor,
        therapy: TherapyProcessor,
        inputs: PhaseInputs,
        operations: OperationRuntime,
        mutation_lock: asyncio.Lock,
        shutdown_started: asyncio.Event,
        now: Callable[[], datetime],
        new_id: Callable[[], UUID],
        recorder: DiagnosticRecorder | None = None,
    ) -> None:
        self._store = store
        self._intake = intake
        self._therapy = therapy
        self._inputs = inputs
        self._operations = operations
        self._mutation_lock = mutation_lock
        self._shutdown_started = shutdown_started
        self._now = now
        self._new_id = new_id
        self._recorder = recorder
        self._generation_lock = asyncio.Lock()

    @property
    def generation_active(self) -> bool:
        return self._generation_lock.locked()

    async def _run_store(self, fn, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        return await run_store_call(fn, *args, recorder=self._recorder, **kwargs)

    def _reject_if_shutdown(self) -> None:
        if self._shutdown_started.is_set():
            raise Busy("application is shutting down")

    def _reject_if_generation_active(self) -> None:
        if self._generation_lock.locked():
            raise Busy("another chat generation is active")

    async def _reserve_generation_lock(self) -> None:
        if self._generation_lock.locked():
            raise Busy("another chat generation is active")
        await self._generation_lock.acquire()

    def _release_generation_lock(self) -> None:
        if self._generation_lock.locked():
            self._generation_lock.release()

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
            diag.record_command_completed(
                self._recorder, "send_message", "idempotent_existing"
            )
            with diagnostic_context(
                session_id=str(session_id),
                client_message_id=str(client_message_id),
                request_id=str(request_id) if request_id is not None else None,
            ):
                diag.record(self._recorder, "chat.turn.reused", {})
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
                diag.record_command_completed(
                    self._recorder, "send_message", "committed"
                )
                diag.record(self._recorder, "chat.turn.retried", {})
                diag.record(self._recorder, "chat.turn.started", {})
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
                diag.record_command_completed(
                    self._recorder, "send_message", "committed"
                )
                diag.record(self._recorder, "chat.turn.accepted", {})
            raise
        except BaseException:
            self._release_generation_lock()
            raise
        with diagnostic_context(
            session_id=str(session_id),
            client_message_id=str(client_message_id),
            request_id=str(request_id) if request_id is not None else None,
        ):
            diag.record_command_completed(self._recorder, "send_message", "committed")
            diag.record(self._recorder, "chat.turn.accepted", {})
            diag.record(self._recorder, "chat.turn.started", {})
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
            diag.record_runtime_error(
                self._recorder,
                phase="chat_attempt",
                exc=exc,
                session_id=str(session_id),
                client_message_id=str(client_message_id),
                request_id=str(request_id) if request_id is not None else None,
            )
        code, message, retryable = _classify_work_error(exc)
        with diagnostic_context(
            session_id=str(session_id),
            client_message_id=str(client_message_id),
            request_id=str(request_id) if request_id is not None else None,
        ):
            diag.record(
                self._recorder,
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
        diag.record_command_started(self._recorder, "send_message")
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
                if isinstance(exc, _COMMAND_REJECT_TYPES):
                    diag.record_command_rejected(self._recorder, "send_message", exc)
                else:
                    diag.record_command_error(self._recorder, "send_message", exc)
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
                    diag.record(
                        self._recorder,
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
            turn_input = await self._inputs.build_intake_turn_input(session_id)
            plan = await self._intake.prepare_turn(turn_input)
            intake_record = plan.merged_record
            completeness_complete = plan.completeness_complete
            chunk_source = self._intake.stream_response(plan)
        elif session.kind is SessionKind.THERAPY:
            turn_input = await self._inputs.build_therapy_turn_input(session_id)
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
                diag.record(self._recorder, "chat.turn.completed", {})
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
                diag.record(self._recorder, "chat.turn.completed", {})
            assert from_stage is not None
            diag.record_transition(
                self._recorder,
                from_stage=from_stage,
                to_stage=Stage.ASSESSMENT,
                trigger="final_intake",
            )
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
            # Assistant commit is irreversible; scheduling failure cannot ChatFailed.
            self._operations.schedule(operation)
            return ChatCompleted(
                session_id=user_message.session_id,
                client_message_id=user_message.client_message_id,
                request_id=request_id,
                user_message=user_message,
                assistant_message=assistant,
            )

        return await self._await_owned_terminalization(_terminalize())

    async def _await_owned_terminalization(
        self, terminalize_coro: object
    ) -> ChatCompleted:
        task = asyncio.create_task(terminalize_coro)  # type: ignore[arg-type]
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancellation:
            failure = await drain_cancelled_task(task)
            if failure is None:
                raise _TerminalDuringCancel(task.result(), cancellation) from None
            if isinstance(failure, asyncio.CancelledError):
                raise cancellation
            raise failure from None


def _response_has_content(text: str) -> bool:
    return bool(text.strip())
