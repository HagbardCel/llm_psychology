"""Workflow and chat coordination for the Jung API-backed console client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol, TypeVar
from uuid import UUID, uuid4

from jung.api.contracts import (
    AppSnapshotResponse,
    ErrorEnvelope,
    ErrorEvent,
    MessageCompletedEvent,
    MessageFailedEvent,
    MessageResponse,
    ProfileUpdateRequest,
    ProfileWire,
    SelectStyleRequest,
    SessionHistoryResponse,
    StyleOptionsResponse,
    TokenEvent,
)
from jung.client.api_client import (
    JungApiClient,
    JungApiError,
    JungProtocolError,
    JungTransportError,
    ProtocolErrorKind,
)

_ResultT = TypeVar("_ResultT")


class ConsoleExitRequested(Exception):
    """Normal user-requested exit (/exit or EOF)."""


class ConsoleOperationFailed(Exception):
    """Terminal non-retryable background operation failure."""


@dataclass(frozen=True)
class ErrorDisplay:
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True)
class PromptSpec:
    text: str


@dataclass
class ChatRenderState:
    streamed_parts: list[str] = field(default_factory=list)
    output_started: bool = False

    @property
    def streamed_text(self) -> str:
        return "".join(self.streamed_parts)


class ConsoleObserver(Protocol):
    def record(self, event: str, **fields: object) -> None: ...


class NoOpConsoleObserver:
    def record(self, event: str, **fields: object) -> None:
        return None


class InputProvider(Protocol):
    async def read(self, prompt: PromptSpec) -> str: ...


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
    def render_invalid_action(self, message: str) -> None: ...


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
            if exc.code == "invalid_command":
                self._output.render_command_rejection(_envelope_from_api_error(exc))
                return await self._client.get_state()
            raise
        return snapshot_of(result)

    async def run(self) -> None:
        snapshot = await self._client.get_state()
        while True:
            self._output.render_snapshot(snapshot)
            self._observer.record(
                "snapshot",
                stage=snapshot.stage,
                commands=list(snapshot.available_commands),
            )

            unanswered = await self._latest_unanswered_user(snapshot)
            if unanswered is not None:
                await self._render_session_history_if_needed(snapshot)
                snapshot = await self._handle_unanswered_user(snapshot, unanswered)
                continue

            commands = set(snapshot.available_commands)

            match snapshot.stage:
                case "setup":
                    snapshot = await self._handle_setup()
                case "intake":
                    await self._render_session_history_if_needed(snapshot)
                    require_command(commands, "send_message")
                    content = await self.read_input(PromptSpec(text="\nYour message: "))
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
                                "\nEnter 'start' to begin therapy or '/exit' to quit: "
                            ),
                        )
                    )
                    if action.strip() == "/exit":
                        raise ConsoleExitRequested
                    if action.strip().lower() != "start":
                        self._output.render_invalid_action("Enter 'start' or '/exit'.")
                        continue
                    require_command(commands, "start_session")
                    snapshot = await self._apply_mutation(
                        self._client.start_session(),
                        snapshot_of=lambda response: response.snapshot,
                    )
                case "therapy":
                    await self._render_session_history_if_needed(snapshot)
                    action = await self.read_input(
                        PromptSpec(
                            text=("\nYour message (or /quit to end session): "),
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

    async def _latest_unanswered_user(
        self,
        snapshot: AppSnapshotResponse,
    ) -> MessageResponse | None:
        session = snapshot.active_session
        if session is None or session.ended_at is not None:
            return None
        history = await self._client.get_session(session.id)
        if not history.messages:
            return None
        latest = history.messages[-1]
        if latest.role != "user":
            return None
        return latest

    async def _handle_unanswered_user(
        self,
        snapshot: AppSnapshotResponse,
        user_msg: MessageResponse,
    ) -> AppSnapshotResponse:
        if snapshot.stage == "intake":
            while True:
                action = (
                    await self.read_input(PromptSpec(text="\nEnter /retry or /exit: "))
                ).strip()
                if action == "/retry":
                    return await self._handle_chat_turn(
                        snapshot,
                        content=user_msg.content,
                        client_message_id=user_msg.client_message_id,
                    )
                if action == "/exit":
                    raise ConsoleExitRequested
                self._output.render_invalid_action("Enter /retry or /exit.")

        if snapshot.stage == "therapy":
            while True:
                action = (
                    await self.read_input(
                        PromptSpec(text="\nEnter /retry, /quit, or /exit: ")
                    )
                ).strip()
                if action == "/retry":
                    return await self._handle_chat_turn(
                        snapshot,
                        content=user_msg.content,
                        client_message_id=user_msg.client_message_id,
                    )
                if action == "/quit":
                    require_command(set(snapshot.available_commands), "end_session")
                    return await self._end_active_session(snapshot)
                if action == "/exit":
                    raise ConsoleExitRequested
                self._output.render_invalid_action("Enter /retry, /quit, or /exit.")

        raise JungProtocolError(
            kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
            expected_model="unanswered user on intake or therapy stage",
        )

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
        style_id = await self.read_input(PromptSpec(text="\nStyle id to select: "))
        return await self._apply_mutation(
            self._client.select_style(
                SelectStyleRequest(
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
            self._client.end_session(session.id),
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
                        error.message if error else "The background operation failed."
                    ),
                    retryable=error.retryable if error else False,
                )
                self._output.render_operation_failure(display)
                raise ConsoleOperationFailed

            while True:
                action = (
                    await self.read_input(PromptSpec(text="\nEnter /retry or /exit: "))
                ).strip()
                if action == "/retry":
                    return await self._apply_mutation(
                        self._client.retry_current_operation(),
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
        client_message_id: UUID | None = None,
    ) -> AppSnapshotResponse:
        session = snapshot.active_session
        if session is None:
            raise JungProtocolError(
                kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                expected_model="active session for chat",
            )
        self._observer.record("user_message", content=content)
        client_message_id = client_message_id or uuid4()
        request_id = uuid4()
        self._observer.record(
            "chat_send",
            session_id=str(session.id),
            client_message_id=str(client_message_id),
            request_id=str(request_id),
        )

        render_state = ChatRenderState()

        try:
            async with self._client.stream_message(
                session.id,
                content,
                client_message_id=client_message_id,
                request_id=request_id,
            ) as events:
                self._locally_submitted_client_ids.add(client_message_id)
                try:
                    async for event in events:
                        if isinstance(event, TokenEvent):
                            self._append_token(render_state, event)
                            self._observer.record("chat_event", type=event.type)
                            continue

                        if isinstance(event, MessageCompletedEvent):
                            self._finalize_completion(render_state, event)
                            return await self._client.get_state()

                        if isinstance(event, MessageFailedEvent):
                            self._discard_partial(render_state)
                            self._output.render_chat_failure(event.error)
                            return await self._client.get_state()

                        if isinstance(event, ErrorEvent):
                            self._discard_partial(render_state)
                            self._locally_submitted_client_ids.discard(
                                client_message_id
                            )
                            self._output.render_command_rejection(event.error)
                            return await self._client.get_state()

                        raise JungProtocolError(
                            kind=ProtocolErrorKind.INVALID_SERVER_EVENT,
                            expected_model="ServerEvent",
                        )
                except asyncio.CancelledError:
                    self._discard_partial(render_state)
                    raise
                except JungTransportError:
                    self._discard_partial(render_state)
                    return await self._client.get_state()
                except JungProtocolError as exc:
                    if exc.kind is ProtocolErrorKind.INCOMPLETE_STREAM:
                        self._discard_partial(render_state)
                        return await self._client.get_state()
                    raise
        except JungTransportError:
            self._locally_submitted_client_ids.discard(client_message_id)
            raise

        raise JungProtocolError(
            kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
            expected_model="chat stream terminal event",
        )

    def _ensure_output_started(self, state: ChatRenderState) -> None:
        if state.output_started:
            return
        self._output.begin_assistant_message()
        state.output_started = True

    def _append_token(self, state: ChatRenderState, event: TokenEvent) -> None:
        self._ensure_output_started(state)
        state.streamed_parts.append(event.text)
        self._output.append_assistant_token(event.text)

    def _discard_partial(self, state: ChatRenderState) -> None:
        if not state.output_started:
            return
        self._output.discard_partial_assistant_message()
        state.output_started = False
        state.streamed_parts.clear()

    def _finalize_completion(
        self,
        state: ChatRenderState,
        completion: MessageCompletedEvent,
    ) -> None:
        canonical = completion.assistant_message.content
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
            completion.user_message.sequence,
            completion.assistant_message.sequence,
        )
        self._locally_submitted_client_ids.discard(completion.client_message_id)
        self._observer.record(
            "chat_event",
            type=completion.type,
            client_message_id=str(completion.client_message_id),
        )
        self._observer.record(
            "assistant_message",
            content=canonical,
            client_message_id=str(completion.client_message_id),
        )
