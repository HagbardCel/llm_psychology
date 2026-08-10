"""Unit tests for the Jung API-backed console client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from jung.api.contracts import (
    AppSnapshotResponse,
    ErrorEnvelope,
    ErrorEvent,
    ErrorResponse,
    MessageCompletedEvent,
    MessageFailedEvent,
    MessageResponse,
    OperationSummaryResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    ProfileWire,
    SelectStyleRequest,
    SendMessageCommand,
    SessionDetailResponse,
    SessionHistoryResponse,
    SessionSummaryResponse,
    StartSessionResponse,
    StyleOptionsResponse,
    StyleSummaryResponse,
    TokenEvent,
)
from jung.client.api_client import (
    ClientSettings,
    JungApiClient,
    JungApiError,
    JungConnectionClosed,
    JungProtocolError,
    JungTransportError,
)
from jung.client.console import (
    ChatRenderState,
    ConsoleApp,
    ConsoleExitRequested,
    ConsoleOperationFailed,
    ErrorDisplay,
    PromptSpec,
    require_command,
)

pytestmark = pytest.mark.asyncio


def _open_chat_from_stream(build_events):
    """Build chat.stream from the outbound SendMessageCommand."""

    @asynccontextmanager
    async def open_chat():
        chat = MagicMock()
        sent: list[SendMessageCommand] = []

        async def stream(command: SendMessageCommand) -> AsyncIterator[object]:
            sent.append(command)
            async for event in build_events(command):
                yield event

        chat.stream = stream
        chat.sent = sent
        yield chat

    return open_chat


class RecordingOutput:
    def __init__(self) -> None:
        self.snapshots: list[AppSnapshotResponse] = []
        self.messages: list[tuple[str, str]] = []
        self.assistant_tokens: list[str] = []
        self.assistant_begins = 0
        self.assistant_finishes = 0
        self.assistant_replacements: list[str] = []
        self.assistant_direct: list[str] = []
        self.assistant_discards = 0
        self.style_options: list[StyleOptionsResponse] = []
        self.system: list[str] = []
        self.command_rejections: list[ErrorEnvelope] = []
        self.chat_failures: list[ErrorEnvelope] = []
        self.operation_failures: list[ErrorDisplay] = []
        self.invalid: list[str] = []

    def render_snapshot(self, snapshot: AppSnapshotResponse) -> None:
        self.snapshots.append(snapshot)

    def render_message(self, role: str, content: str) -> None:
        self.messages.append((role, content))

    def begin_assistant_message(self) -> None:
        self.assistant_begins += 1

    def append_assistant_token(self, text: str) -> None:
        self.assistant_tokens.append(text)

    def finish_assistant_stream(self) -> None:
        self.assistant_finishes += 1

    def replace_partial_assistant_message(self, content: str) -> None:
        self.assistant_replacements.append(content)

    def render_assistant_message(self, content: str) -> None:
        self.assistant_direct.append(content)

    def discard_partial_assistant_message(self) -> None:
        self.assistant_discards += 1

    def render_system(self, message: str) -> None:
        self.system.append(message)

    def render_command_rejection(self, error: ErrorEnvelope) -> None:
        self.command_rejections.append(error)

    def render_chat_failure(self, error: ErrorEnvelope) -> None:
        self.chat_failures.append(error)

    def render_operation_failure(self, error: ErrorDisplay) -> None:
        self.operation_failures.append(error)

    def render_style_options(self, options: StyleOptionsResponse) -> None:
        self.style_options.append(options)

    def render_invalid_action(self, message: str) -> None:
        self.invalid.append(message)


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def record(self, event: str, **fields: object) -> None:
        self.events.append((event, dict(fields)))


class ScriptedInput:
    def __init__(self, *lines: str) -> None:
        self._lines = list(lines)

    async def read(self, prompt: PromptSpec) -> str:
        if not self._lines:
            raise EOFError
        return self._lines.pop(0)


def _snapshot(
    *,
    stage: str = "intake",
    commands: list[str] | None = None,
    session: SessionSummaryResponse | None = None,
    operation: OperationSummaryResponse | None = None,
) -> AppSnapshotResponse:
    if commands is None:
        commands = ["send_message"]
    return AppSnapshotResponse(
        stage=stage,  # type: ignore[arg-type]
        profile_complete=True,
        active_session=session,
        operation=operation,
        available_commands=commands,
    )


def _session(
    session_id: UUID | None = None, *, kind: str = "intake"
) -> SessionSummaryResponse:
    return SessionSummaryResponse(
        id=session_id or uuid4(),
        kind=kind,  # type: ignore[arg-type]
        started_at=datetime.now(UTC),
    )


def _message(
    *,
    session_id: UUID,
    client_message_id: UUID,
    role: str,
    content: str,
    sequence: int,
) -> MessageResponse:
    return MessageResponse(
        id=uuid4(),
        session_id=session_id,
        sequence=sequence,
        role=role,  # type: ignore[arg-type]
        content=content,
        created_at=datetime.now(UTC),
        client_message_id=client_message_id,
    )


def _history(
    *,
    session_id: UUID,
    messages: list[MessageResponse],
) -> SessionHistoryResponse:
    return SessionHistoryResponse(
        session=SessionDetailResponse(
            id=session_id,
            kind="intake",
            started_at=datetime.now(UTC),
        ),
        messages=messages,
        plans=[],
    )


def _mock_client() -> MagicMock:
    client = MagicMock(spec=JungApiClient)
    client.settings = ClientSettings("http://localhost:8000")
    client.new_message_command = JungApiClient.new_message_command.__get__(client)
    return client


def _completion_event(
    *,
    session_id: UUID,
    client_message_id: UUID,
    request_id: UUID,
    content: str = "reply",
) -> MessageCompletedEvent:
    return MessageCompletedEvent(
        type="message_completed",
        request_id=request_id,
        session_id=session_id,
        client_message_id=client_message_id,
        user_message=_message(
            session_id=session_id,
            client_message_id=client_message_id,
            role="user",
            content="hello",
            sequence=1,
        ),
        assistant_message=_message(
            session_id=session_id,
            client_message_id=client_message_id,
            role="assistant",
            content=content,
            sequence=2,
        ),
    )


def _token_event(
    *,
    session_id: UUID,
    client_message_id: UUID,
    request_id: UUID,
    text: str = "hi",
) -> TokenEvent:
    return TokenEvent(
        type="token",
        session_id=session_id,
        client_message_id=client_message_id,
        request_id=request_id,
        text=text,
    )


async def _event_stream(*events: object) -> AsyncIterator[object]:
    for event in events:
        yield event


def _app(
    client: MagicMock,
    *,
    inputs: ScriptedInput | None = None,
    output: RecordingOutput | None = None,
    observer: RecordingObserver | None = None,
) -> ConsoleApp:
    return ConsoleApp(
        client=client,
        input=inputs or ScriptedInput(),
        output=output or RecordingOutput(),
        observer=observer,
    )


async def test_chat_turn_builds_send_message_command() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(session=session)
    sent_commands: list[SendMessageCommand] = []

    def build_events(command: SendMessageCommand) -> AsyncIterator[object]:
        return _event_stream(
            _completion_event(
                session_id=session.id,
                client_message_id=command.client_message_id,
                request_id=command.request_id,
            )
        )

    @asynccontextmanager
    async def tracking_open_chat():
        async with _open_chat_from_stream(build_events)() as chat:
            original = chat.stream

            async def tracked(command: SendMessageCommand):
                sent_commands.append(command)
                async for event in original(command):
                    yield event

            chat.stream = tracked
            yield chat

    client.open_chat = tracking_open_chat
    client.get_state = AsyncMock(
        return_value=_snapshot(stage="assessment", session=session, commands=[])
    )
    app = _app(client)
    await app._handle_chat_turn(snapshot, content="hello")
    assert sent_commands
    assert sent_commands[0].content == "hello"
    assert sent_commands[0].content == "hello"
    assert sent_commands[0].session_id == session.id


async def test_stage_alone_does_not_authorize_mutation() -> None:
    snapshot = _snapshot(stage="intake", commands=[])
    with pytest.raises(JungProtocolError):
        require_command(set(snapshot.available_commands), "send_message")


async def test_unanswered_user_retry_reuses_client_message_id() -> None:
    client = _mock_client()
    session = _session()
    client_message_id = uuid4()
    unanswered = _message(
        session_id=session.id,
        client_message_id=client_message_id,
        role="user",
        content="prior user",
        sequence=1,
    )
    snapshot = _snapshot(session=session)
    client.get_session = AsyncMock(
        return_value=_history(session_id=session.id, messages=[unanswered])
    )
    sent: list[SendMessageCommand] = []

    def build_events(command: SendMessageCommand) -> AsyncIterator[object]:
        sent.append(command)
        return _event_stream(
            _completion_event(
                session_id=session.id,
                client_message_id=command.client_message_id,
                request_id=command.request_id,
            )
        )

    client.open_chat = _open_chat_from_stream(build_events)
    client.get_state = AsyncMock(return_value=snapshot)
    output = RecordingOutput()
    app = _app(client, inputs=ScriptedInput("/retry"), output=output)

    result = await app._handle_unanswered_user(snapshot, unanswered)
    assert result == snapshot
    assert len(sent) == 1
    assert sent[0].client_message_id == client_message_id
    assert sent[0].content == "prior user"


async def test_unanswered_user_exit_raises() -> None:
    client = _mock_client()
    session = _session()
    unanswered = _message(
        session_id=session.id,
        client_message_id=uuid4(),
        role="user",
        content="stuck",
        sequence=1,
    )
    app = _app(client, inputs=ScriptedInput("/exit"))
    with pytest.raises(ConsoleExitRequested):
        await app._handle_unanswered_user(_snapshot(session=session), unanswered)


async def test_run_prompts_retry_for_trailing_user_before_new_input() -> None:
    client = _mock_client()
    session = _session()
    unanswered = _message(
        session_id=session.id,
        client_message_id=uuid4(),
        role="user",
        content="needs reply",
        sequence=1,
    )
    snapshot = _snapshot(session=session)
    after = _snapshot(session=session)
    unanswered_history = _history(session_id=session.id, messages=[unanswered])
    completed_history = _history(
        session_id=session.id,
        messages=[
            unanswered,
            _message(
                session_id=session.id,
                client_message_id=unanswered.client_message_id,
                role="assistant",
                content="ok",
                sequence=2,
            ),
        ],
    )

    def build_events(command: SendMessageCommand) -> AsyncIterator[object]:
        return _event_stream(
            _completion_event(
                session_id=session.id,
                client_message_id=command.client_message_id,
                request_id=command.request_id,
                content="ok",
            )
        )

    client.get_state = AsyncMock(side_effect=[snapshot, after])
    client.get_session = AsyncMock(
        side_effect=[
            unanswered_history,  # unanswered detection
            unanswered_history,  # render before retry prompt
            completed_history,  # unanswered detection after retry
            completed_history,  # render before new intake prompt
        ]
    )
    client.open_chat = _open_chat_from_stream(build_events)
    output = RecordingOutput()
    app = _app(
        client,
        inputs=ScriptedInput("/retry"),
        output=output,
    )

    with pytest.raises(ConsoleExitRequested):
        await app.run()

    assert ("user", "needs reply") in output.messages


async def test_start_session_is_bodyless() -> None:
    client = _mock_client()
    session = _session(kind="therapy")
    snapshot = _snapshot(stage="ready", commands=["start_session"])
    therapy = _snapshot(
        stage="therapy",
        session=session,
        commands=["send_message", "end_session"],
    )
    client.start_session = AsyncMock(
        return_value=StartSessionResponse(
            session=session,
            snapshot=therapy,
        )
    )
    client.end_session = AsyncMock(
        return_value=_snapshot(stage="ready", commands=["start_session"])
    )
    client.get_state = AsyncMock(return_value=snapshot)
    client.get_session = AsyncMock(
        return_value=_history(session_id=session.id, messages=[])
    )
    app = _app(client, inputs=ScriptedInput("start", "/quit", "/exit"))
    with pytest.raises(ConsoleExitRequested):
        await app.run()
    client.start_session.assert_awaited_once_with()
    client.end_session.assert_awaited_once_with(session.id)


async def test_therapy_quit_command_vs_word_quit() -> None:
    client = _mock_client()
    session = _session(kind="therapy")
    therapy = _snapshot(
        stage="therapy",
        session=session,
        commands=["send_message", "end_session"],
    )
    observer = RecordingObserver()
    app = _app(client, inputs=ScriptedInput("/quit"), observer=observer)
    action = (await app.read_input(PromptSpec(text="> "))).strip()
    assert action == "/quit"
    with patch.object(
        app, "_end_active_session", AsyncMock(return_value=therapy)
    ) as end:
        with patch.object(app, "_handle_chat_turn", AsyncMock()) as chat:
            if action == "/quit":
                require_command(set(therapy.available_commands), "end_session")
                await app._end_active_session(therapy)
            chat.assert_not_awaited()
            end.assert_awaited_once()
    assert not any(event == "user_message" for event, _ in observer.events)

    observer = RecordingObserver()
    app = _app(client, inputs=ScriptedInput("quit"), observer=observer)
    action = (await app.read_input(PromptSpec(text="> "))).strip()
    assert action == "quit"
    with patch.object(
        app, "_handle_chat_turn", AsyncMock(return_value=therapy)
    ) as chat:
        with patch.object(app, "_end_active_session", AsyncMock()) as end:
            if action != "/quit":
                require_command(set(therapy.available_commands), "send_message")
                await app._handle_chat_turn(therapy, content=action)
            chat.assert_awaited_once()
            end.assert_not_awaited()


async def test_retryable_operation_invalid_input_reprompts() -> None:
    client = _mock_client()
    operation = OperationSummaryResponse(
        id=uuid4(),
        kind="assessment",
        status="failed",
        error=ErrorEnvelope(
            code="llm_timeout",
            message="timed out",
            request_id=uuid4(),
            retryable=True,
        ),
    )
    snapshot = _snapshot(
        stage="assessment",
        operation=operation,
        commands=["retry_operation"],
    )
    client.retry_current_operation = AsyncMock(
        return_value=_snapshot(stage="style_selection")
    )
    app = _app(client, inputs=ScriptedInput("maybe", "/retry"))
    result = await app._handle_operation_stage(snapshot)
    assert result.stage == "style_selection"
    assert client.retry_current_operation.await_count == 1


async def test_non_retryable_operation_failure_is_terminal() -> None:
    client = _mock_client()
    operation = OperationSummaryResponse(
        id=uuid4(),
        kind="assessment",
        status="failed",
        error=ErrorEnvelope(
            code="operation_failed",
            message="failed",
            request_id=uuid4(),
            retryable=False,
        ),
    )
    snapshot = _snapshot(stage="assessment", operation=operation, commands=[])
    app = _app(client)
    with pytest.raises(ConsoleOperationFailed):
        await app._handle_operation_stage(snapshot)


async def test_non_retryable_operation_failure_propagates_from_run() -> None:
    client = _mock_client()
    operation = OperationSummaryResponse(
        id=uuid4(),
        kind="assessment",
        status="failed",
        error=ErrorEnvelope(
            code="operation_failed",
            message="failed",
            request_id=uuid4(),
            retryable=False,
        ),
    )
    snapshot = _snapshot(stage="assessment", operation=operation, commands=[])
    client.get_state = AsyncMock(return_value=snapshot)

    async def run_and_fail():
        app = _app(client, inputs=ScriptedInput())
        await app.run()

    with patch.object(ConsoleApp, "POLL_INTERVAL", 0):
        with pytest.raises(ConsoleOperationFailed):
            await run_and_fail()


async def test_operation_complete_without_stage_transition_is_protocol_error() -> None:
    client = _mock_client()
    operation = OperationSummaryResponse(
        id=uuid4(),
        kind="assessment",
        status="complete",
    )
    snapshot = _snapshot(stage="assessment", operation=operation)
    client.get_state = AsyncMock(return_value=snapshot)
    app = _app(client)
    with pytest.raises(JungProtocolError):
        await app._handle_operation_stage(snapshot)


async def test_message_failed_renders_chat_failure_without_raising() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(session=session)
    request_id = uuid4()
    failure = MessageFailedEvent(
        type="message_failed",
        request_id=request_id,
        session_id=session.id,
        client_message_id=uuid4(),
        error=ErrorEnvelope(
            code="llm_timeout",
            message="Generation timed out",
            request_id=request_id,
            retryable=True,
        ),
    )

    def build_events(command: SendMessageCommand) -> AsyncIterator[object]:
        return _event_stream(
            failure.model_copy(update={"client_message_id": command.client_message_id})
        )

    client.open_chat = _open_chat_from_stream(build_events)
    client.get_state = AsyncMock(return_value=snapshot)
    output = RecordingOutput()
    app = _app(client, output=output)
    result = await app._handle_chat_turn(snapshot, content="hello")
    assert result == snapshot
    assert len(output.chat_failures) == 1
    assert output.chat_failures[0].code == "llm_timeout"


async def test_error_event_renders_command_rejection() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(session=session)

    def build_events(command: SendMessageCommand) -> AsyncIterator[object]:
        return _event_stream(
            ErrorEvent(
                type="error",
                request_id=command.request_id,
                session_id=session.id,
                client_message_id=command.client_message_id,
                error=ErrorEnvelope(
                    code="invalid_command",
                    message="not allowed",
                    request_id=command.request_id,
                    retryable=False,
                ),
            )
        )

    client.open_chat = _open_chat_from_stream(build_events)
    client.get_state = AsyncMock(return_value=snapshot)
    output = RecordingOutput()
    app = _app(client, output=output)
    await app._handle_chat_turn(snapshot, content="hello")
    assert len(output.command_rejections) == 1
    assert output.command_rejections[0].code == "invalid_command"


async def test_disconnect_during_stream_refreshes_state() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(session=session)
    refreshed = _snapshot(session=session, stage="intake")

    def build_events(command: SendMessageCommand) -> AsyncIterator[object]:
        async def events():
            yield _token_event(
                session_id=session.id,
                client_message_id=command.client_message_id,
                request_id=command.request_id,
            )
            raise JungConnectionClosed(code=1006, reason=None)

        return events()

    client.open_chat = _open_chat_from_stream(build_events)
    client.get_state = AsyncMock(return_value=refreshed)
    output = RecordingOutput()
    app = _app(client, output=output)
    result = await app._handle_chat_turn(snapshot, content="hello")
    assert result == refreshed
    assert output.assistant_discards == 1


async def test_profile_setup_preserves_optional_fields() -> None:
    client = _mock_client()
    profile = ProfileResponse(
        profile=ProfileWire(
            name="Alex",
            primary_language="English",
            date_of_birth=date(1990, 1, 2),
            notes="keep me",
        ),
        snapshot=_snapshot(stage="setup", commands=["update_profile"]),
    )
    client.get_profile = AsyncMock(return_value=profile)
    client.update_profile = AsyncMock(return_value=_snapshot(stage="intake"))
    observer = RecordingObserver()
    app = _app(client, inputs=ScriptedInput("New Name", "French"), observer=observer)
    await app._handle_setup()
    request = client.update_profile.await_args.args[0]
    assert isinstance(request, ProfileUpdateRequest)
    assert request.profile.date_of_birth == date(1990, 1, 2)
    assert request.profile.notes == "keep me"
    assert not any(event == "user_message" for event, _ in observer.events)


async def test_read_input_eof_raises_console_exit_requested() -> None:
    class EofInput:
        async def read(self, prompt: PromptSpec) -> str:
            raise EOFError

    app = _app(_mock_client(), inputs=EofInput())  # type: ignore[arg-type]
    with pytest.raises(ConsoleExitRequested):
        await app.read_input(PromptSpec(text="> "))


async def test_token_then_matching_completion_renders_stream() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(session=session)
    output = RecordingOutput()

    def build_events(command: SendMessageCommand) -> AsyncIterator[object]:
        return _event_stream(
            _token_event(
                session_id=session.id,
                client_message_id=command.client_message_id,
                request_id=command.request_id,
                text="re",
            ),
            _token_event(
                session_id=session.id,
                client_message_id=command.client_message_id,
                request_id=command.request_id,
                text="ply",
            ),
            _completion_event(
                session_id=session.id,
                client_message_id=command.client_message_id,
                request_id=command.request_id,
                content="reply",
            ),
        )

    client.open_chat = _open_chat_from_stream(build_events)
    client.get_state = AsyncMock(return_value=snapshot)
    app = _app(client, output=output)
    await app._handle_chat_turn(snapshot, content="hello")
    assert output.assistant_begins == 1
    assert output.assistant_tokens == ["re", "ply"]
    assert output.assistant_finishes == 1


async def test_completion_without_tokens_renders_direct() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(session=session)
    output = RecordingOutput()

    def build_events(command: SendMessageCommand) -> AsyncIterator[object]:
        return _event_stream(
            _completion_event(
                session_id=session.id,
                client_message_id=command.client_message_id,
                request_id=command.request_id,
                content="direct",
            )
        )

    client.open_chat = _open_chat_from_stream(build_events)
    client.get_state = AsyncMock(return_value=snapshot)
    app = _app(client, output=output)
    await app._handle_chat_turn(snapshot, content="hello")
    assert output.assistant_direct == ["direct"]
    assert output.assistant_begins == 0


async def test_streamed_text_differs_uses_correction() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(session=session)
    output = RecordingOutput()

    def build_events(command: SendMessageCommand) -> AsyncIterator[object]:
        return _event_stream(
            _token_event(
                session_id=session.id,
                client_message_id=command.client_message_id,
                request_id=command.request_id,
                text="partial",
            ),
            _completion_event(
                session_id=session.id,
                client_message_id=command.client_message_id,
                request_id=command.request_id,
                content="canonical",
            ),
        )

    client.open_chat = _open_chat_from_stream(build_events)
    client.get_state = AsyncMock(return_value=snapshot)
    app = _app(client, output=output)
    await app._handle_chat_turn(snapshot, content="hello")
    assert output.assistant_replacements == ["canonical"]


async def test_style_selection_recovers_from_invalid_command_through_run() -> None:
    client = _mock_client()
    styles = StyleOptionsResponse(
        styles=[
            StyleSummaryResponse(id="cbt", name="CBT", description="desc"),
        ],
        recommendations=[],
    )
    selecting = _snapshot(stage="style_selection", commands=["select_style"])
    ready = _snapshot(stage="ready", commands=["start_session"])
    client.get_state = AsyncMock(side_effect=[selecting, selecting, ready])
    client.get_styles = AsyncMock(return_value=styles)
    client.select_style = AsyncMock(
        side_effect=[
            JungApiError(
                status=409,
                error=ErrorResponse(
                    code="invalid_command",
                    message="not allowed",
                    request_id=uuid4(),
                    retryable=False,
                ),
            ),
            ready,
        ]
    )
    output = RecordingOutput()
    app = _app(
        client,
        inputs=ScriptedInput("bad", "cbt", "/exit"),
        output=output,
    )
    with patch.object(ConsoleApp, "POLL_INTERVAL", 0):
        with pytest.raises(ConsoleExitRequested):
            await app.run()
    assert client.select_style.await_count == 2
    assert len(output.command_rejections) == 1


async def test_style_selection_sends_style_id_only() -> None:
    client = _mock_client()
    styles = StyleOptionsResponse(
        styles=[StyleSummaryResponse(id="cbt", name="CBT", description="d")],
        recommendations=[],
    )
    snapshot = _snapshot(stage="style_selection", commands=["select_style"])
    client.get_styles = AsyncMock(return_value=styles)
    client.select_style = AsyncMock(return_value=_snapshot(stage="ready"))
    app = _app(client, inputs=ScriptedInput("cbt"))
    await app._handle_style_selection(snapshot)
    request = client.select_style.await_args.args[0]
    assert isinstance(request, SelectStyleRequest)
    assert request.style_id == "cbt"


async def test_chat_input_recorded_before_transport_failure() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(session=session)
    observer = RecordingObserver()

    @asynccontextmanager
    async def failing_open_chat():
        raise JungTransportError("handshake")
        yield  # pragma: no cover

    client.open_chat = failing_open_chat
    app = _app(client, observer=observer)
    with pytest.raises(JungTransportError):
        await app._handle_chat_turn(snapshot, content="spoken aloud")
    assert ("user_message", {"content": "spoken aloud"}) in observer.events


async def test_append_token_helper_starts_output() -> None:
    app = _app(_mock_client())
    state = ChatRenderState()
    event = _token_event(
        session_id=uuid4(),
        client_message_id=uuid4(),
        request_id=uuid4(),
        text="hi",
    )
    app._append_token(state, event)
    assert app._output.assistant_tokens == ["hi"]
    assert state.output_started is True
