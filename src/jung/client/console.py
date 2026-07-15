"""API-backed terminal console for the local Jung therapist application."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, TypeVar
from uuid import UUID

from jung.api.contracts import (
    AppSnapshotResponse,
    EndSessionRequest,
    ErrorEnvelope,
    ErrorEvent,
    MessageCompletedEvent,
    MessageInProgressEvent,
    ProfileUpdateRequest,
    ProfileWire,
    RetryOperationRequest,
    SelectStyleRequest,
    ServerEvent,
    SessionHistoryResponse,
    StartSessionRequest,
    StyleOptionsResponse,
    TokenEvent,
)
from jung.client._chat_events import (
    ChatEventIdentity,
    ChatEventViolation,
    ErrorCorrelation,
    classify_error,
    identity_after_progress,
    is_ignorable_event,
    matches_completion,
    matches_progress,
    matches_token,
)
from jung.client.api_client import (
    ChatReconciliationStatus,
    ChatSendIntent,
    ClientSettings,
    JungApiClient,
    JungApiError,
    JungClientError,
    JungConnectionClosed,
    JungProtocolError,
    JungTransportError,
    ProtocolErrorKind,
)

_ResultT = TypeVar("_ResultT")


class ConsoleExitRequested(Exception):
    """Normal user-requested exit (/exit or EOF)."""


class ConsoleChatFailed(Exception):
    """Terminal durable chat generation failure."""


class ConsoleOperationFailed(Exception):
    """Terminal non-retryable background operation failure."""


class ConsoleUncertainDelivery(Exception):
    """Outcome cannot safely be established."""


@dataclass(frozen=True)
class ErrorDisplay:
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True)
class PendingTurnContext:
    intent: ChatSendIntent
    reconciliation_attempted: bool = False


@dataclass(frozen=True)
class LoadedPendingTurn:
    context: PendingTurnContext
    history: SessionHistoryResponse


@dataclass(frozen=True)
class PromptSpec:
    text: str


@dataclass
class ChatRenderState:
    turn_id: UUID | None = None
    last_token_sequence: int = 0
    streamed_parts: list[str] = field(default_factory=list)
    output_started: bool = False

    @property
    def streamed_text(self) -> str:
        return "".join(self.streamed_parts)


class ChatOutcomeKind(StrEnum):
    PROGRESS = "progress"
    COMPLETION = "completion"
    COMMAND_ERROR = "command_error"
    DURABLE_ERROR = "durable_error"


@dataclass(frozen=True)
class ChatEventOutcome:
    kind: ChatOutcomeKind
    identity: ChatEventIdentity
    event: MessageInProgressEvent | MessageCompletedEvent | ErrorEvent


class ConsoleObserver(Protocol):
    def record(self, event: str, **fields: object) -> None: ...


class NoOpConsoleObserver:
    def record(self, event: str, **fields: object) -> None:
        return None


class InputProvider(Protocol):
    async def read(self, prompt: PromptSpec) -> str: ...


class HumanInputProvider:
    async def read(self, prompt: PromptSpec) -> str:
        print(prompt.text, end="", flush=True)
        line = await asyncio.to_thread(sys.stdin.readline)
        if line == "":
            raise EOFError
        return line.rstrip("\r\n")


class ConsoleOutput(Protocol):
    def render_snapshot(self, snapshot: AppSnapshotResponse) -> None: ...
    def render_message(self, role: str, content: str) -> None: ...
    def begin_assistant_message(self) -> None: ...
    def append_assistant_token(self, text: str) -> None: ...
    def finish_assistant_stream(self) -> None: ...
    def replace_partial_assistant_message(self, content: str) -> None: ...
    def render_assistant_message(self, content: str) -> None: ...
    def discard_partial_assistant_message(self) -> None: ...
    def render_system(self, message: str) -> None: ...
    def render_command_rejection(self, error: ErrorEnvelope) -> None: ...
    def render_chat_failure(self, error: ErrorEnvelope) -> None: ...
    def render_operation_failure(self, error: ErrorDisplay) -> None: ...
    def render_style_options(self, options: StyleOptionsResponse) -> None: ...
    def render_identity_conflict(
        self,
        *,
        session_id: UUID,
        client_message_id: UUID,
    ) -> None: ...
    def render_uncertain_delivery(self, message: str) -> None: ...
    def render_invalid_action(self, message: str) -> None: ...
    def render_client_error(self, error: JungClientError) -> None: ...


class TerminalConsoleOutput:
    def __init__(self) -> None:
        self._assistant_stream_active = False

    def render_snapshot(self, snapshot: AppSnapshotResponse) -> None:
        commands = ", ".join(snapshot.available_commands) or "(none)"
        print(
            f"\n[stage={snapshot.stage} revision={snapshot.revision} "
            f"commands={commands}]"
        )

    def render_message(self, role: str, content: str) -> None:
        label = "You" if role == "user" else "Therapist"
        print(f"\n{label}: {content}")

    def begin_assistant_message(self) -> None:
        print("\nTherapist: ", end="", flush=True)
        self._assistant_stream_active = True

    def append_assistant_token(self, text: str) -> None:
        print(text, end="", flush=True)

    def finish_assistant_stream(self) -> None:
        if self._assistant_stream_active:
            print()
            self._assistant_stream_active = False

    def replace_partial_assistant_message(self, content: str) -> None:
        if self._assistant_stream_active:
            print()
            self._assistant_stream_active = False
        print("\n[Stream corrected from durable completion]")
        print(f"Therapist: {content}")

    def render_assistant_message(self, content: str) -> None:
        print(f"\nTherapist: {content}")

    def discard_partial_assistant_message(self) -> None:
        if self._assistant_stream_active:
            print()
            self._assistant_stream_active = False

    def render_system(self, message: str) -> None:
        print(f"\n{message}")

    def render_command_rejection(self, error: ErrorEnvelope) -> None:
        print(f"\nRequest rejected ({error.code}): {error.message}")

    def render_chat_failure(self, error: ErrorEnvelope) -> None:
        print(f"\nChat failed ({error.code}): {error.message}")

    def render_operation_failure(self, error: ErrorDisplay) -> None:
        print(f"\nOperation failed ({error.code}): {error.message}")

    def render_style_options(self, options: StyleOptionsResponse) -> None:
        print("\nAvailable styles:")
        for style in options.styles:
            print(f"  {style.id}: {style.name}")
        if options.recommendations:
            print("\nRecommendations:")
            for rec in options.recommendations:
                print(
                    f"  {rec.style_id} (score={rec.score:.2f}): "
                    f"{rec.rationale}"
                )

    def render_identity_conflict(
        self,
        *,
        session_id: UUID,
        client_message_id: UUID,
    ) -> None:
        print(
            "\nIdentity conflict for chat turn "
            f"session={session_id} client_message_id={client_message_id}."
        )

    def render_uncertain_delivery(self, message: str) -> None:
        print(f"\n{message}")

    def render_invalid_action(self, message: str) -> None:
        print(f"\n{message}")

    def render_client_error(self, error: JungClientError) -> None:
        print(f"\nClient error: {error}")


def _bind_stream_turn(
    state: ChatRenderState,
    turn_id: UUID,
) -> None:
    if state.turn_id is None:
        state.turn_id = turn_id
        return
    if state.turn_id != turn_id:
        raise ChatEventViolation(
            expected_model="consistent turn_id across correlated chat events",
        )


def require_command(commands: set[str], command: str) -> None:
    if command not in commands:
        raise JungProtocolError(
            kind=ProtocolErrorKind.INVALID_SERVER_EVENT,
            expected_model=f"available command {command}",
        )


def _envelope_from_api_error(exc: JungApiError) -> ErrorEnvelope:
    return ErrorEnvelope(
        code=exc.code,
        message=exc.message,
        request_id=exc.request_id,
        retryable=exc.retryable,
        current_snapshot=exc.current_snapshot,
    )


class ConsoleApp:
    POLL_INTERVAL = 0.35

    def __init__(
        self,
        *,
        client: JungApiClient,
        input: InputProvider,
        output: ConsoleOutput,
        observer: ConsoleObserver | None = None,
    ) -> None:
        self._client = client
        self._input = input
        self._output = output
        self._observer = observer or NoOpConsoleObserver()
        self._last_rendered_sequence: dict[UUID, int] = {}
        self._locally_submitted_client_ids: set[UUID] = set()

    async def read_input(self, prompt: PromptSpec) -> str:
        try:
            return await self._input.read(prompt)
        except EOFError:
            raise ConsoleExitRequested from None

    async def _apply_mutation(
        self,
        mutation: Awaitable[_ResultT],
        *,
        snapshot_of: Callable[[_ResultT], AppSnapshotResponse],
    ) -> AppSnapshotResponse:
        try:
            result = await mutation
        except JungApiError as exc:
            if exc.code == "state_conflict" and exc.current_snapshot is not None:
                self._output.render_command_rejection(_envelope_from_api_error(exc))
                return exc.current_snapshot
            raise
        return snapshot_of(result)

    async def run(self) -> None:
        snapshot = await self._client.get_state()
        while True:
            self._output.render_snapshot(snapshot)
            self._observer.record(
                "snapshot",
                stage=snapshot.stage,
                revision=snapshot.revision,
                commands=list(snapshot.available_commands),
            )

            active_turn = snapshot.active_chat_turn
            if active_turn is not None and active_turn.status == "pending":
                loaded = await self._load_pending_turn_context(snapshot)
                self._render_session_history(loaded.history)
                snapshot = await self._wait_for_pending_chat_turn(
                    snapshot,
                    context=loaded.context,
                )
                continue

            commands = set(snapshot.available_commands)

            match snapshot.stage:
                case "setup":
                    snapshot = await self._handle_setup()
                case "intake":
                    await self._render_session_history_if_needed(snapshot)
                    require_command(commands, "send_message")
                    content = await self.read_input(
                        PromptSpec(text="\nYour message: ")
                    )
                    snapshot = await self._handle_chat_turn(
                        snapshot,
                        content=content,
                    )
                case "assessment" | "post_session":
                    snapshot = await self._handle_operation_stage(snapshot)
                case "style_selection":
                    require_command(commands, "select_style")
                    snapshot = await self._handle_style_selection(snapshot)
                case "ready":
                    action = await self.read_input(
                        PromptSpec(
                            text=(
                                "\nEnter 'start' to begin therapy or "
                                "'/exit' to quit: "
                            ),
                        )
                    )
                    if action.strip() == "/exit":
                        raise ConsoleExitRequested
                    if action.strip().lower() != "start":
                        self._output.render_invalid_action(
                            "Enter 'start' or '/exit'."
                        )
                        continue
                    require_command(commands, "start_session")
                    snapshot = await self._apply_mutation(
                        self._client.start_session(
                            StartSessionRequest(
                                expected_revision=snapshot.revision,
                            )
                        ),
                        snapshot_of=lambda response: response.snapshot,
                    )
                case "therapy":
                    await self._render_session_history_if_needed(snapshot)
                    action = await self.read_input(
                        PromptSpec(
                            text=(
                                "\nYour message (or /quit to end session): "
                            ),
                        )
                    )
                    if action.strip() == "/quit":
                        require_command(commands, "end_session")
                        snapshot = await self._end_active_session(snapshot)
                    else:
                        require_command(commands, "send_message")
                        snapshot = await self._handle_chat_turn(
                            snapshot,
                            content=action,
                        )
                case _:
                    self._output.render_system(
                        f"Unhandled stage {snapshot.stage!r}; waiting."
                    )
                    await asyncio.sleep(self.POLL_INTERVAL)
                    snapshot = await self._client.get_state()

    async def _handle_setup(self) -> AppSnapshotResponse:
        current = await self._client.get_profile()
        profile_snapshot = current.snapshot
        require_command(
            set(profile_snapshot.available_commands),
            "update_profile",
        )
        name = await self.read_input(PromptSpec(text="\nYour name: "))
        language = await self.read_input(PromptSpec(text="Primary language: "))
        updated = ProfileWire(
            name=name.strip() or current.profile.name,
            primary_language=language.strip() or current.profile.primary_language,
            date_of_birth=current.profile.date_of_birth,
            notes=current.profile.notes,
        )
        return await self._apply_mutation(
            self._client.update_profile(
                ProfileUpdateRequest(
                    expected_revision=profile_snapshot.revision,
                    profile=updated,
                )
            ),
            snapshot_of=lambda snapshot: snapshot,
        )

    async def _handle_style_selection(
        self,
        snapshot: AppSnapshotResponse,
    ) -> AppSnapshotResponse:
        options = await self._client.get_styles()
        self._output.render_style_options(options)
        style_id = await self.read_input(
            PromptSpec(text="\nStyle id to select: ")
        )
        return await self._apply_mutation(
            self._client.select_style(
                SelectStyleRequest(
                    expected_revision=snapshot.revision,
                    style_id=style_id.strip(),
                )
            ),
            snapshot_of=lambda adopted: adopted,
        )

    async def _end_active_session(
        self,
        snapshot: AppSnapshotResponse,
    ) -> AppSnapshotResponse:
        session = snapshot.active_session
        if session is None:
            raise JungProtocolError(
                kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                expected_model="active therapy session",
            )
        return await self._apply_mutation(
            self._client.end_session(
                session.id,
                EndSessionRequest(expected_revision=snapshot.revision),
            ),
            snapshot_of=lambda adopted: adopted,
        )

    async def _handle_operation_stage(
        self,
        snapshot: AppSnapshotResponse,
    ) -> AppSnapshotResponse:
        operation = snapshot.operation
        if operation is None:
            raise JungProtocolError(
                kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                expected_model="current operation",
            )
        commands = set(snapshot.available_commands)

        if operation.status == "failed":
            if "retry_operation" not in commands:
                error = operation.error
                display = ErrorDisplay(
                    code=error.code if error else "operation_failed",
                    message=(
                        error.message
                        if error
                        else "The background operation failed."
                    ),
                    retryable=error.retryable if error else False,
                )
                self._output.render_operation_failure(display)
                raise ConsoleOperationFailed

            while True:
                action = (
                    await self.read_input(
                        PromptSpec(text="\nEnter /retry or /exit: ")
                    )
                ).strip()
                if action == "/retry":
                    return await self._apply_mutation(
                        self._client.retry_current_operation(
                            RetryOperationRequest(
                                expected_revision=snapshot.revision,
                            )
                        ),
                        snapshot_of=lambda adopted: adopted,
                    )
                if action == "/exit":
                    raise ConsoleExitRequested
                self._output.render_invalid_action("Enter /retry or /exit.")

        if operation.status in {"pending", "running"}:
            return await self._wait_for_operation(snapshot)

        refreshed = await self._client.get_state()
        if refreshed.stage == snapshot.stage:
            raise JungProtocolError(
                kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                expected_model="operation complete with stage transition",
            )
        return refreshed

    async def _wait_for_operation(
        self,
        snapshot: AppSnapshotResponse,
    ) -> AppSnapshotResponse:
        while True:
            operation = snapshot.operation
            if snapshot.stage not in {"assessment", "post_session"}:
                return snapshot
            if operation and operation.status in {"complete", "failed"}:
                return snapshot
            await asyncio.sleep(self.POLL_INTERVAL)
            snapshot = await self._client.get_state()

    async def _load_pending_turn_context(
        self,
        snapshot: AppSnapshotResponse,
    ) -> LoadedPendingTurn:
        turn = snapshot.active_chat_turn
        if turn is None or turn.status != "pending":
            raise JungProtocolError(
                kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                expected_model="pending active chat turn",
            )
        history = await self._client.get_session(turn.session_id)
        if history.session.id != turn.session_id:
            raise JungProtocolError(
                kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                expected_model="session history for pending turn",
            )
        matching_users = [
            message
            for message in history.messages
            if message.role == "user"
            and message.client_message_id == turn.client_message_id
        ]
        if len(matching_users) != 1:
            raise JungProtocolError(
                kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                expected_model="one durable user message for pending turn",
            )
        user_message = matching_users[0]
        intent = self._client.new_chat_intent(
            turn.session_id,
            user_message.content,
            client_message_id=turn.client_message_id,
        )
        return LoadedPendingTurn(
            context=PendingTurnContext(
                intent=intent,
                reconciliation_attempted=False,
            ),
            history=history,
        )

    async def _wait_for_pending_chat_turn(
        self,
        snapshot: AppSnapshotResponse,
        *,
        context: PendingTurnContext,
    ) -> AppSnapshotResponse:
        while True:
            pending = snapshot.active_chat_turn
            if (
                pending is not None
                and pending.status == "pending"
                and pending.session_id == context.intent.session_id
                and pending.client_message_id == context.intent.client_message_id
            ):
                await asyncio.sleep(self.POLL_INTERVAL)
                snapshot = await self._client.get_state()
                history = await self._client.get_session(
                    context.intent.session_id
                )
                assistant = self._assistant_for_intent(
                    history,
                    context.intent.client_message_id,
                )
                if assistant is not None:
                    return await self._complete_from_history(
                        intent=context.intent,
                        history=history,
                    )
                continue

            history = await self._client.get_session(context.intent.session_id)
            assistant = self._assistant_for_intent(
                history,
                context.intent.client_message_id,
            )
            if assistant is not None:
                return await self._complete_from_history(
                    intent=context.intent,
                    history=history,
                )

            if context.reconciliation_attempted:
                self._output.render_uncertain_delivery(
                    "The previous message outcome could not be determined safely."
                )
                raise ConsoleUncertainDelivery

            result = await self._client.reconcile_chat_turn(context.intent)
            return await self._apply_reconciliation_result(
                result,
                context.intent,
            )

    async def _apply_reconciliation_result(
        self,
        result,
        intent: ChatSendIntent,
    ) -> AppSnapshotResponse:
        match result.status:
            case ChatReconciliationStatus.COMPLETE:
                return await self._complete_from_history(
                    intent=intent,
                    history=result.history,
                )
            case ChatReconciliationStatus.FAILED:
                error_event = result.error_event
                if error_event is None:
                    raise JungProtocolError(
                        kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                        expected_model="failed reconciliation error event",
                    )
                if error_event.turn_id is None:
                    return await self._handle_command_rejection(
                        error_event,
                        intent,
                    )
                self._render_session_history(result.history)
                self._output.render_chat_failure(error_event.error)
                raise ConsoleChatFailed
            case ChatReconciliationStatus.IN_PROGRESS:
                return await self._wait_for_pending_chat_turn(
                    result.snapshot,
                    context=PendingTurnContext(
                        intent=intent,
                        reconciliation_attempted=True,
                    ),
                )
            case ChatReconciliationStatus.UNRESOLVED:
                self._render_session_history(result.history)
                self._output.render_uncertain_delivery(
                    "The previous message outcome could not be determined safely."
                )
                raise ConsoleUncertainDelivery
            case ChatReconciliationStatus.IDENTITY_CONFLICT:
                self._output.render_identity_conflict(
                    session_id=intent.session_id,
                    client_message_id=intent.client_message_id,
                )
                raise JungProtocolError(
                    kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                    expected_model=(
                        "durable user content matching ChatSendIntent "
                        "for client_message_id"
                    ),
                )
            case _:
                raise JungProtocolError(
                    kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                    expected_model="known reconciliation status",
                )

    def _assistant_for_intent(
        self,
        history: SessionHistoryResponse,
        client_message_id: UUID,
    ):
        assistants = [
            message
            for message in history.messages
            if message.role == "assistant"
            and message.client_message_id == client_message_id
        ]
        if len(assistants) > 1:
            raise JungProtocolError(
                kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                expected_model="at most one assistant per client_message_id",
            )
        return assistants[0] if assistants else None

    async def _complete_from_history(
        self,
        *,
        intent: ChatSendIntent,
        history: SessionHistoryResponse,
    ) -> AppSnapshotResponse:
        self._render_session_history(history)
        self._locally_submitted_client_ids.discard(intent.client_message_id)
        return await self._client.get_state()

    async def _render_session_history_if_needed(
        self,
        snapshot: AppSnapshotResponse,
    ) -> None:
        session = snapshot.active_session
        if session is None:
            return
        history = await self._client.get_session(session.id)
        self._render_session_history(history)

    def _render_session_history(self, history: SessionHistoryResponse) -> None:
        session_id = history.session.id
        last_rendered = self._last_rendered_sequence.get(session_id, 0)
        for message in history.messages:
            if message.sequence <= last_rendered:
                continue
            if (
                message.role == "user"
                and message.client_message_id is not None
                and message.client_message_id in self._locally_submitted_client_ids
            ):
                last_rendered = message.sequence
                continue
            self._output.render_message(message.role, message.content)
            last_rendered = message.sequence
        self._last_rendered_sequence[session_id] = last_rendered

    async def _handle_chat_turn(
        self,
        snapshot: AppSnapshotResponse,
        *,
        content: str,
    ) -> AppSnapshotResponse:
        session = snapshot.active_session
        if session is None:
            raise JungProtocolError(
                kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                expected_model="active session for chat",
            )
        self._observer.record("user_message", content=content)
        intent = self._client.new_chat_intent(session.id, content)
        command = self._client.new_message_command(
            intent,
            expected_revision=snapshot.revision,
        )
        self._observer.record(
            "chat_send",
            session_id=str(intent.session_id),
            client_message_id=str(intent.client_message_id),
            request_id=str(command.request_id),
        )

        render_state = ChatRenderState()
        reconciliation_needed = False

        try:
            async with self._client.open_chat() as chat:
                self._locally_submitted_client_ids.add(intent.client_message_id)
                try:
                    await chat.send(command)
                    events = chat.events()
                    identity = ChatEventIdentity(
                        session_id=intent.session_id,
                        client_message_id=intent.client_message_id,
                        request_id=command.request_id,
                    )
                    identity, early = await self._wait_for_acknowledgement(
                        events,
                        identity=identity,
                        render_state=render_state,
                    )
                    if early is not None:
                        return await self._resolve_terminal_outcome(
                            early,
                            intent=intent,
                            render_state=render_state,
                        )
                    outcome = await self._wait_for_completion(
                        events,
                        identity=identity,
                        render_state=render_state,
                    )
                    return await self._resolve_terminal_outcome(
                        outcome,
                        intent=intent,
                        render_state=render_state,
                    )
                except asyncio.CancelledError:
                    self._discard_partial(render_state)
                    raise
                except (
                    JungConnectionClosed,
                    JungTransportError,
                    TimeoutError,
                ):
                    self._discard_partial(render_state)
                    reconciliation_needed = True
                except JungProtocolError:
                    self._discard_partial(render_state)
                    raise
        except JungTransportError:
            self._locally_submitted_client_ids.discard(intent.client_message_id)
            raise

        if reconciliation_needed:
            result = await self._client.reconcile_chat_turn(intent)
            return await self._apply_reconciliation_result(result, intent)

        raise JungProtocolError(
            kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
            expected_model="chat turn outcome",
        )

    async def _resolve_terminal_outcome(
        self,
        outcome: ChatEventOutcome,
        *,
        intent: ChatSendIntent,
        render_state: ChatRenderState,
    ) -> AppSnapshotResponse:
        if outcome.kind is ChatOutcomeKind.COMMAND_ERROR:
            self._discard_partial(render_state)
            return await self._handle_command_rejection(
                outcome.event,
                intent,
            )
        if outcome.kind is ChatOutcomeKind.DURABLE_ERROR:
            self._discard_partial(render_state)
            snapshot = await self._client.get_state()
            await self._render_session_history_if_needed(snapshot)
            self._output.render_chat_failure(outcome.event.error)
            raise ConsoleChatFailed
        if outcome.kind is ChatOutcomeKind.COMPLETION:
            self._finalize_turn_completion(render_state, outcome.event)
            return await self._client.get_state()
        raise JungProtocolError(
            kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
            expected_model="terminal chat outcome",
        )

    async def _wait_for_acknowledgement(
        self,
        events: AsyncIterator[ServerEvent],
        *,
        identity: ChatEventIdentity,
        render_state: ChatRenderState,
    ) -> tuple[ChatEventIdentity, ChatEventOutcome | None]:
        async with asyncio.timeout(self._client.settings.acknowledgement_timeout):
            async for event in events:
                outcome = self._process_chat_event(
                    event,
                    identity=identity,
                    render_state=render_state,
                )
                if outcome is None:
                    continue
                if outcome.kind is ChatOutcomeKind.PROGRESS:
                    return outcome.identity, None
                return outcome.identity, outcome
        raise TimeoutError

    async def _wait_for_completion(
        self,
        events: AsyncIterator[ServerEvent],
        *,
        identity: ChatEventIdentity,
        render_state: ChatRenderState,
    ) -> ChatEventOutcome:
        async for event in events:
            outcome = self._process_chat_event(
                event,
                identity=identity,
                render_state=render_state,
            )
            if outcome is None:
                continue
            if outcome.kind is ChatOutcomeKind.PROGRESS:
                continue
            return outcome
        raise JungProtocolError(
            kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
            expected_model="chat completion event",
        )

    def _ensure_output_started(self, state: ChatRenderState) -> None:
        if state.output_started:
            return
        self._output.begin_assistant_message()
        state.output_started = True

    def _append_token(self, state: ChatRenderState, event: TokenEvent) -> None:
        self._ensure_output_started(state)
        if event.sequence <= state.last_token_sequence:
            return
        if event.sequence > state.last_token_sequence + 1:
            self._observer.record(
                "token_gap",
                expected=state.last_token_sequence + 1,
                received=event.sequence,
            )
        state.last_token_sequence = event.sequence
        state.streamed_parts.append(event.text)
        self._output.append_assistant_token(event.text)

    def _discard_partial(self, state: ChatRenderState) -> None:
        if not state.output_started:
            return
        self._output.discard_partial_assistant_message()
        state.output_started = False
        state.streamed_parts.clear()
        state.last_token_sequence = 0

    def _process_chat_event(
        self,
        event: ServerEvent,
        *,
        identity: ChatEventIdentity,
        render_state: ChatRenderState,
    ) -> ChatEventOutcome | None:
        try:
            if isinstance(event, MessageInProgressEvent):
                if matches_progress(event, identity):
                    _bind_stream_turn(render_state, event.turn.id)
                    new_identity = identity_after_progress(event, identity)
                    self._observer.record(
                        "ws_event",
                        type=event.type,
                        turn_id=str(event.turn.id),
                    )
                    return ChatEventOutcome(
                        kind=ChatOutcomeKind.PROGRESS,
                        identity=new_identity,
                        event=event,
                    )
                return None

            if isinstance(event, TokenEvent):
                if matches_token(event, identity):
                    _bind_stream_turn(render_state, event.turn_id)
                    self._append_token(render_state, event)
                    self._observer.record(
                        "ws_event",
                        type=event.type,
                        sequence=event.sequence,
                    )
                return None

            if isinstance(event, MessageCompletedEvent):
                if matches_completion(event, identity):
                    _bind_stream_turn(render_state, event.turn.id)
                    return ChatEventOutcome(
                        kind=ChatOutcomeKind.COMPLETION,
                        identity=identity,
                        event=event,
                    )
                return None

            if isinstance(event, ErrorEvent):
                correlation = classify_error(event, identity)
                if correlation is ErrorCorrelation.UNRELATED:
                    return None
                if correlation is ErrorCorrelation.COMMAND_REJECTED:
                    return ChatEventOutcome(
                        kind=ChatOutcomeKind.COMMAND_ERROR,
                        identity=identity,
                        event=event,
                    )
                return ChatEventOutcome(
                    kind=ChatOutcomeKind.DURABLE_ERROR,
                    identity=identity,
                    event=event,
                )

            if is_ignorable_event(event):
                if hasattr(event, "snapshot"):
                    self._observer.record(
                        "ws_event",
                        type=event.type,
                        revision=event.snapshot.revision,
                        stage=event.snapshot.stage,
                    )
                elif hasattr(event, "operation"):
                    self._observer.record(
                        "ws_event",
                        type=event.type,
                        operation_kind=getattr(
                            event.operation,
                            "kind",
                            None,
                        ),
                        operation_status=getattr(
                            event.operation,
                            "status",
                            None,
                        ),
                    )
                return None
        except ChatEventViolation as exc:
            raise JungProtocolError(
                kind=ProtocolErrorKind.INVALID_SERVER_EVENT,
                expected_model=exc.expected_model,
            ) from None

        return None

    def _finalize_turn_completion(
        self,
        state: ChatRenderState,
        completion: MessageCompletedEvent,
    ) -> None:
        canonical = completion.message.content
        if not state.output_started:
            self._output.render_assistant_message(canonical)
        elif state.streamed_text == canonical:
            self._output.finish_assistant_stream()
        else:
            self._output.replace_partial_assistant_message(canonical)
        state.output_started = False
        state.streamed_parts.clear()

        session_id = completion.session_id
        self._last_rendered_sequence[session_id] = max(
            self._last_rendered_sequence.get(session_id, 0),
            completion.message.sequence,
        )
        client_id = completion.turn.client_message_id
        self._locally_submitted_client_ids.discard(client_id)
        self._observer.record(
            "ws_event",
            type=completion.type,
            client_message_id=str(client_id),
        )
        self._observer.record(
            "assistant_message",
            content=canonical,
            client_message_id=str(client_id),
        )

    async def _handle_command_rejection(
        self,
        error_event: ErrorEvent,
        intent: ChatSendIntent,
    ) -> AppSnapshotResponse:
        self._locally_submitted_client_ids.discard(intent.client_message_id)
        self._output.render_command_rejection(error_event.error)
        snapshot = (
            error_event.error.current_snapshot
            or await self._client.get_state()
        )
        return snapshot


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jung therapy console client")
    parser.add_argument(
        "--api-url",
        required=True,
        help="Base URL for the Jung API (e.g. http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--transport-timeout",
        type=float,
        default=None,
        help="HTTP/WebSocket transport timeout in seconds",
    )
    return parser


def cli() -> int:
    return asyncio.run(_async_cli())


async def _async_cli() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    settings_kwargs: dict[str, object] = {"base_url": args.api_url}
    if args.transport_timeout is not None:
        settings_kwargs["transport_timeout"] = args.transport_timeout
    settings = ClientSettings(**settings_kwargs)
    output = TerminalConsoleOutput()

    try:
        async with JungApiClient(settings) as client:
            await ConsoleApp(
                client=client,
                input=HumanInputProvider(),
                output=output,
            ).run()
    except ConsoleExitRequested:
        return 0
    except (ConsoleChatFailed, ConsoleOperationFailed):
        return 1
    except ConsoleUncertainDelivery:
        return 2
    except JungClientError as exc:
        output.render_client_error(exc)
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
