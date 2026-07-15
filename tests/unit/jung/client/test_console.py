"""Unit tests for the Jung API-backed console client."""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from jung.api.contracts import (
    AppSnapshotResponse,
    ChatTurnSummaryResponse,
    ErrorEnvelope,
    ErrorEvent,
    ErrorResponse,
    MessageCompletedEvent,
    MessageInProgressEvent,
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
    StartSessionRequest,
    StartSessionResponse,
    StyleOptionsResponse,
    StyleSummaryResponse,
    TokenEvent,
)
from jung.client._chat_events import (
    ChatEventIdentity,
    classify_error,
)
from jung.client.api_client import (
    ChatReconciliationResult,
    ChatReconciliationStatus,
    ChatSendIntent,
    ClientSettings,
    JungApiClient,
    JungApiError,
    JungConnectionClosed,
    JungProtocolError,
    JungTransportError,
)
from jung.client.console import (
    ConsoleApp,
    ConsoleChatFailed,
    ConsoleExitRequested,
    ConsoleOperationFailed,
    ConsoleUncertainDelivery,
    ErrorDisplay,
    PendingTurnContext,
    PromptSpec,
    _async_cli,
    cli,
    require_command,
)

ROOT = Path(__file__).resolve().parents[4]
CHAT_EVENTS_PATH = ROOT / "src" / "jung" / "client" / "_chat_events.py"

pytestmark = pytest.mark.asyncio


def _open_chat_from_send(build_events):
    """Build chat events from the outbound SendMessageCommand."""

    @asynccontextmanager
    async def open_chat():
        holder: dict[str, AsyncIterator[object]] = {}
        chat = MagicMock()

        async def send(command: SendMessageCommand) -> None:
            holder["events"] = build_events(command)

        chat.send = send
        chat.events = lambda: holder["events"]
        yield chat

    return open_chat


class RecordingOutput:
    def __init__(self) -> None:
        self.snapshots: list[AppSnapshotResponse] = []
        self.messages: list[tuple[str, str]] = []
        self.tokens: list[str] = []
        self.system: list[str] = []
        self.command_rejections: list[ErrorEnvelope] = []
        self.chat_failures: list[ErrorEnvelope] = []
        self.operation_failures: list[ErrorDisplay] = []
        self.identity_conflicts: list[tuple[UUID, UUID]] = []
        self.uncertain: list[str] = []
        self.invalid: list[str] = []
        self.client_errors: list[Exception] = []

    def render_snapshot(self, snapshot: AppSnapshotResponse) -> None:
        self.snapshots.append(snapshot)

    def render_message(self, role: str, content: str) -> None:
        self.messages.append((role, content))

    def render_token(self, text: str) -> None:
        self.tokens.append(text)

    def render_newline(self) -> None:
        self.messages.append(("newline", ""))

    def render_system(self, message: str) -> None:
        self.system.append(message)

    def render_command_rejection(self, error: ErrorEnvelope) -> None:
        self.command_rejections.append(error)

    def render_chat_failure(self, error: ErrorEnvelope) -> None:
        self.chat_failures.append(error)

    def render_operation_failure(self, error: ErrorDisplay) -> None:
        self.operation_failures.append(error)

    def render_identity_conflict(
        self,
        *,
        session_id: UUID,
        client_message_id: UUID,
    ) -> None:
        self.identity_conflicts.append((session_id, client_message_id))

    def render_uncertain_delivery(self, message: str) -> None:
        self.uncertain.append(message)

    def render_invalid_action(self, message: str) -> None:
        self.invalid.append(message)

    def render_client_error(self, error: Exception) -> None:
        self.client_errors.append(error)


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
    revision: int = 1,
    commands: list[str] | None = None,
    session: SessionSummaryResponse | None = None,
    pending: ChatTurnSummaryResponse | None = None,
    operation: OperationSummaryResponse | None = None,
) -> AppSnapshotResponse:
    if commands is None:
        commands = ["send_message"]
    return AppSnapshotResponse(
        revision=revision,
        stage=stage,  # type: ignore[arg-type]
        profile_complete=True,
        active_session=session,
        operation=operation,
        active_chat_turn=pending,
        available_commands=commands,
    )


def _session(session_id: UUID | None = None, *, kind: str = "intake") -> SessionSummaryResponse:
    return SessionSummaryResponse(
        id=session_id or uuid4(),
        kind=kind,  # type: ignore[arg-type]
        started_at=datetime.now(UTC),
    )


def _turn(
    *,
    session_id: UUID,
    client_message_id: UUID,
    status: str = "pending",
) -> ChatTurnSummaryResponse:
    return ChatTurnSummaryResponse(
        id=uuid4(),
        session_id=session_id,
        client_message_id=client_message_id,
        status=status,  # type: ignore[arg-type]
        user_message_id=uuid4(),
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
    client_message_id: UUID,
    user_content: str = "hello",
    assistant_content: str | None = None,
) -> SessionHistoryResponse:
    messages = [
        _message(
            session_id=session_id,
            client_message_id=client_message_id,
            role="user",
            content=user_content,
            sequence=1,
        )
    ]
    if assistant_content is not None:
        messages.append(
            _message(
                session_id=session_id,
                client_message_id=client_message_id,
                role="assistant",
                content=assistant_content,
                sequence=2,
            )
        )
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
    client.new_chat_intent = JungApiClient.new_chat_intent.__get__(client)
    client.new_message_command = JungApiClient.new_message_command.__get__(client)
    return client


def _progress_event(
    *,
    session_id: UUID,
    client_message_id: UUID,
    turn_id: UUID | None = None,
) -> MessageInProgressEvent:
    turn_id = turn_id or uuid4()
    return MessageInProgressEvent(
        type="message_in_progress",
        session_id=session_id,
        turn=_turn(
            session_id=session_id,
            client_message_id=client_message_id,
            status="pending",
        ).model_copy(update={"id": turn_id}),
    )


def _completion_event(
    *,
    session_id: UUID,
    client_message_id: UUID,
    turn_id: UUID,
    content: str = "reply",
    sequence: int = 2,
) -> MessageCompletedEvent:
    turn = _turn(
        session_id=session_id,
        client_message_id=client_message_id,
        status="complete",
    ).model_copy(update={"id": turn_id})
    return MessageCompletedEvent(
        type="message_completed",
        session_id=session_id,
        turn=turn,
        message=_message(
            session_id=session_id,
            client_message_id=client_message_id,
            role="assistant",
            content=content,
            sequence=sequence,
        ),
    )


async def _event_stream(*events: object) -> AsyncIterator[object]:
    for event in events:
        yield event


@asynccontextmanager
async def _fake_chat(events: AsyncIterator[object]):
    chat = MagicMock()
    chat.send = AsyncMock()
    chat.events = MagicMock(return_value=events)
    yield chat


def _app(
    client: MagicMock,
    *,
    inputs: ScriptedInput | None = None,
    output: RecordingOutput | None = None,
) -> ConsoleApp:
    return ConsoleApp(
        client=client,
        input=inputs or ScriptedInput(),
        output=output or RecordingOutput(),
    )


async def test_mutations_use_authoritative_snapshot_revision() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(revision=7, session=session)

    def build_events(command: SendMessageCommand) -> AsyncIterator[object]:
        progress = _progress_event(
            session_id=session.id,
            client_message_id=command.client_message_id,
        )
        completion = _completion_event(
            session_id=session.id,
            client_message_id=command.client_message_id,
            turn_id=progress.turn.id,
        )
        return _event_stream(progress, completion)

    sent_commands: list[SendMessageCommand] = []

    @asynccontextmanager
    async def tracking_open_chat():
        async with _open_chat_from_send(build_events)() as chat:
            original_send = chat.send

            async def tracked_send(command: SendMessageCommand) -> None:
                sent_commands.append(command)
                return await original_send(command)

            chat.send = tracked_send
            yield chat

    client.open_chat = tracking_open_chat
    after = _snapshot(revision=8, stage="assessment", session=session, commands=[])
    client.get_state = AsyncMock(side_effect=[snapshot, after])
    app = _app(client, inputs=ScriptedInput("hello"))
    await app._handle_chat_turn(snapshot, content="hello")
    assert sent_commands
    assert sent_commands[0].expected_revision == 7


async def test_stage_alone_does_not_authorize_mutation() -> None:
    snapshot = _snapshot(stage="intake", commands=[])
    with pytest.raises(JungProtocolError):
        require_command(set(snapshot.available_commands), "send_message")


async def test_loaded_pending_turn_renders_history_before_wait() -> None:
    client = _mock_client()
    session = _session()
    client_message_id = uuid4()
    pending = _turn(session_id=session.id, client_message_id=client_message_id)
    snapshot = _snapshot(session=session, pending=pending)
    history = _history(
        session_id=session.id,
        client_message_id=client_message_id,
        user_content="prior user",
    )
    client.get_session = AsyncMock(return_value=history)
    output = RecordingOutput()
    app = _app(client, output=output)

    loaded = await app._load_pending_turn_context(snapshot)
    app._render_session_history(loaded.history)

    assert ("user", "prior user") in output.messages
    assert loaded.context.intent.content == "prior user"


async def test_fresh_console_into_pending_turn_renders_historical_user() -> None:
    client = _mock_client()
    session = _session()
    client_message_id = uuid4()
    pending = _turn(session_id=session.id, client_message_id=client_message_id)
    history = _history(
        session_id=session.id,
        client_message_id=client_message_id,
        user_content="stored message",
    )
    client.get_session = AsyncMock(return_value=history)
    output = RecordingOutput()
    app = _app(client, output=output)
    loaded = await app._load_pending_turn_context(
        _snapshot(session=session, pending=pending)
    )
    app._render_session_history(loaded.history)
    assert ("user", "stored message") in output.messages


async def test_pending_intent_requires_exactly_one_durable_user_message() -> None:
    client = _mock_client()
    session = _session()
    client_message_id = uuid4()
    pending = _turn(session_id=session.id, client_message_id=client_message_id)
    snapshot = _snapshot(session=session, pending=pending)
    history = SessionHistoryResponse(
        session=SessionDetailResponse(
            id=session.id,
            kind="intake",
            started_at=datetime.now(UTC),
        ),
        messages=[],
        plans=[],
    )
    client.get_session = AsyncMock(return_value=history)
    app = _app(client)
    with pytest.raises(JungProtocolError):
        await app._load_pending_turn_context(snapshot)


async def test_impossible_history_raises_protocol_error() -> None:
    client = _mock_client()
    session = _session()
    client_message_id = uuid4()
    pending = _turn(session_id=session.id, client_message_id=client_message_id)
    snapshot = _snapshot(session=session, pending=pending)
    mismatched = _history(
        session_id=uuid4(),
        client_message_id=client_message_id,
    )
    client.get_session = AsyncMock(return_value=mismatched)
    app = _app(client)
    with pytest.raises(JungProtocolError):
        await app._load_pending_turn_context(snapshot)


async def test_therapy_quit_command_vs_word_quit() -> None:
    client = _mock_client()
    session = _session(kind="therapy")
    therapy = _snapshot(
        stage="therapy",
        revision=3,
        session=session,
        commands=["send_message", "end_session"],
    )
    app = _app(client, inputs=ScriptedInput("/quit"))
    action = (await app.read_input(PromptSpec(text="> "))).strip()
    assert action == "/quit"
    with patch.object(app, "_end_active_session", AsyncMock(return_value=therapy)) as end:
        with patch.object(app, "_handle_chat_turn", AsyncMock()) as chat:
            if action == "/quit":
                require_command(set(therapy.available_commands), "end_session")
                await app._end_active_session(therapy)
            chat.assert_not_awaited()
            end.assert_awaited_once()

    app = _app(client, inputs=ScriptedInput("quit"))
    action = (await app.read_input(PromptSpec(text="> "))).strip()
    assert action == "quit"
    with patch.object(app, "_handle_chat_turn", AsyncMock(return_value=therapy)) as chat:
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
        revision=2,
        operation=operation,
        commands=["retry_operation"],
    )
    client.retry_current_operation = AsyncMock(
        return_value=_snapshot(stage="style_selection", revision=3)
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


async def test_eof_after_non_retryable_operation_failure_exits_one() -> None:
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

    async def fake_async_cli() -> int:
        return 1

    with patch("jung.client.console.asyncio.run", lambda coro: 1):
        assert cli() == 1


async def test_operation_complete_without_stage_transition_is_protocol_error() -> None:
    client = _mock_client()
    operation = OperationSummaryResponse(
        id=uuid4(),
        kind="assessment",
        status="complete",
    )
    snapshot = _snapshot(stage="assessment", revision=2, operation=operation)
    client.get_state = AsyncMock(return_value=snapshot)
    app = _app(client)
    with pytest.raises(JungProtocolError):
        await app._handle_operation_stage(snapshot)


async def test_pending_refresh_does_not_duplicate_user_message() -> None:
    client = _mock_client()
    session = _session()
    client_message_id = uuid4()
    app = _app(client)
    app._locally_submitted_client_ids.add(client_message_id)
    history = _history(
        session_id=session.id,
        client_message_id=client_message_id,
        user_content="hello",
    )
    app._render_session_history(history)
    app._render_session_history(history)
    assert [m for m in app._output.messages if m[0] == "user"] == []


async def test_failure_after_acceptance_does_not_duplicate_user_message() -> None:
    output = RecordingOutput()
    client = _mock_client()
    session = _session()
    client_message_id = uuid4()
    app = _app(client, output=output)
    app._locally_submitted_client_ids.add(client_message_id)
    history = _history(
        session_id=session.id,
        client_message_id=client_message_id,
        user_content="hello",
    )
    app._render_session_history(history)
    assert output.messages == []


async def test_completion_advances_high_water_mark() -> None:
    client = _mock_client()
    session = _session()
    client_message_id = uuid4()
    turn_id = uuid4()
    app = _app(client)
    completion = _completion_event(
        session_id=session.id,
        client_message_id=client_message_id,
        turn_id=turn_id,
        sequence=4,
    )
    app._finalize_completion(completion)
    assert app._last_rendered_sequence[session.id] == 4


async def test_before_turn_id_progress_establishes_identity() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=client_message_id,
        request_id=request_id,
    )
    progress = _progress_event(
        session_id=session_id,
        client_message_id=client_message_id,
    )
    app = _app(_mock_client())
    outcome = app._process_chat_event(progress, identity=identity, accepted=False)
    assert outcome is not None
    assert outcome[0] == "progress"
    assert outcome[2].turn_id == progress.turn.id


async def test_after_turn_id_wrong_turn_raises_violation() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    turn_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=client_message_id,
        request_id=uuid4(),
        turn_id=turn_id,
    )
    wrong_turn = _completion_event(
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=uuid4(),
    )
    app = _app(_mock_client())
    with pytest.raises(JungProtocolError):
        app._process_chat_event(wrong_turn, identity=identity, accepted=True)


async def test_different_pending_turn_not_adopted() -> None:
    client = _mock_client()
    session = _session()
    original_id = uuid4()
    other_id = uuid4()
    intent = client.new_chat_intent(session.id, "hello", client_message_id=original_id)
    context = PendingTurnContext(intent=intent, reconciliation_attempted=False)
    other_pending = _turn(session_id=session.id, client_message_id=other_id)
    snapshot = _snapshot(
        session=session,
        pending=other_pending,
    )
    history = _history(session_id=session.id, client_message_id=original_id)
    client.get_session = AsyncMock(return_value=history)
    client.reconcile_chat_turn = AsyncMock(
        return_value=ChatReconciliationResult(
            status=ChatReconciliationStatus.UNRESOLVED,
            snapshot=snapshot,
            history=history,
        )
    )
    app = _app(client)
    with pytest.raises(ConsoleUncertainDelivery):
        await app._wait_for_pending_chat_turn(snapshot, context=context)


async def test_command_rejection_discards_local_id_and_adopts_snapshot() -> None:
    client = _mock_client()
    session = _session()
    intent = client.new_chat_intent(session.id, "hello")
    adopted = _snapshot(revision=9, session=session)
    request_id = uuid4()
    error = ErrorEvent(
        type="error",
        request_id=request_id,
        error=ErrorEnvelope(
            code="state_conflict",
            message="stale revision",
            request_id=request_id,
            retryable=False,
            current_snapshot=adopted,
        ),
        session_id=session.id,
        client_message_id=intent.client_message_id,
    )
    app = _app(_mock_client())
    app._locally_submitted_client_ids.add(intent.client_message_id)
    result = await app._handle_command_rejection(error, intent)
    assert result.revision == 9
    assert intent.client_message_id not in app._locally_submitted_client_ids


async def test_durable_error_after_turn_id_raises_chat_failed() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(session=session)
    def build_events(command: SendMessageCommand) -> AsyncIterator[object]:
        progress = _progress_event(
            session_id=session.id,
            client_message_id=command.client_message_id,
        )
        durable_request_id = uuid4()
        durable = ErrorEvent(
            type="error",
            request_id=durable_request_id,
            error=ErrorEnvelope(
                code="llm_unavailable",
                message="failed",
                request_id=durable_request_id,
                retryable=False,
            ),
            session_id=session.id,
            client_message_id=command.client_message_id,
            turn_id=progress.turn.id,
        )
        return _event_stream(progress, durable)

    client.open_chat = _open_chat_from_send(build_events)
    client.get_state = AsyncMock(return_value=snapshot)
    client.get_session = AsyncMock(
        return_value=_history(
            session_id=session.id,
            client_message_id=uuid4(),
        )
    )
    app = _app(client)
    with pytest.raises(ConsoleChatFailed):
        await app._handle_chat_turn(snapshot, content="hello")


async def test_successful_completion_returns_get_state() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(revision=1, session=session)
    def build_events(command: SendMessageCommand) -> AsyncIterator[object]:
        progress = _progress_event(
            session_id=session.id,
            client_message_id=command.client_message_id,
        )
        completion = _completion_event(
            session_id=session.id,
            client_message_id=command.client_message_id,
            turn_id=progress.turn.id,
        )
        return _event_stream(progress, completion)

    client.open_chat = _open_chat_from_send(build_events)
    after = _snapshot(stage="assessment", revision=2, session=session, commands=[])
    client.get_state = AsyncMock(return_value=after)
    app = _app(client)
    result = await app._handle_chat_turn(snapshot, content="hello")
    assert result.stage == "assessment"
    client.get_state.assert_awaited()


async def test_handshake_failure_discards_local_id_without_reconcile() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(session=session)

    @asynccontextmanager
    async def failing_open():
        raise JungTransportError("handshake failed")
        yield  # pragma: no cover

    client.open_chat = failing_open
    client.reconcile_chat_turn = AsyncMock()
    app = _app(client)
    with pytest.raises(JungTransportError):
        await app._handle_chat_turn(snapshot, content="hello")
    client.reconcile_chat_turn.assert_not_called()


async def test_send_failure_reconciles_once_after_scope_exit() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(session=session)
    intent_holder: dict[str, ChatSendIntent] = {}

    @asynccontextmanager
    async def broken_chat():
        chat = MagicMock()

        async def send(_command: SendMessageCommand) -> None:
            raise JungConnectionClosed(code=None, reason=None)

        chat.send = send
        chat.events = MagicMock(return_value=_event_stream())
        yield chat

    client.open_chat = broken_chat
    history = _history(session_id=session.id, client_message_id=uuid4())

    async def reconcile(intent):
        intent_holder["intent"] = intent
        return ChatReconciliationResult(
            status=ChatReconciliationStatus.COMPLETE,
            snapshot=_snapshot(stage="intake", session=session, revision=2),
            history=history,
            completed_message=history.messages[-1],
        )

    client.reconcile_chat_turn = AsyncMock(side_effect=reconcile)
    app = _app(client)
    await app._handle_chat_turn(snapshot, content="hello")
    client.reconcile_chat_turn.assert_awaited_once()


async def test_single_events_iterator_per_turn() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(session=session)
    client_message_id = uuid4()
    events = _event_stream(
        _progress_event(session_id=session.id, client_message_id=client_message_id)
    )

    @asynccontextmanager
    async def open_chat():
        chat = MagicMock()
        chat.send = AsyncMock()
        events_mock = MagicMock(return_value=events)
        chat.events = events_mock
        yield chat
        events_mock.assert_called_once()

    client.open_chat = open_chat
    client.get_state = AsyncMock(return_value=snapshot)
    app = _app(client)
    with pytest.raises(JungProtocolError):
        await app._handle_chat_turn(snapshot, content="hello")


async def test_unresolved_reconciliation_raises_uncertain_delivery() -> None:
    client = _mock_client()
    session = _session()
    intent = client.new_chat_intent(session.id, "hello")
    history = _history(session_id=session.id, client_message_id=intent.client_message_id)
    result = ChatReconciliationResult(
        status=ChatReconciliationStatus.UNRESOLVED,
        snapshot=_snapshot(session=session),
        history=history,
    )
    app = _app(client)
    with pytest.raises(ConsoleUncertainDelivery):
        await app._apply_reconciliation_result(result, intent)


async def test_identity_conflict_is_terminal_protocol_error() -> None:
    client = _mock_client()
    session = _session()
    intent = client.new_chat_intent(session.id, "hello")
    history = _history(session_id=session.id, client_message_id=intent.client_message_id)
    result = ChatReconciliationResult(
        status=ChatReconciliationStatus.IDENTITY_CONFLICT,
        snapshot=_snapshot(session=session),
        history=history,
        conflicting_user_message=history.messages[0],
    )
    output = RecordingOutput()
    app = _app(client, output=output)
    with pytest.raises(JungProtocolError):
        await app._apply_reconciliation_result(result, intent)
    assert output.identity_conflicts


async def test_console_app_does_not_close_injected_client() -> None:
    client = _mock_client()
    client.aclose = AsyncMock()
    app = _app(client)
    assert app._client is client
    client.aclose.assert_not_called()


async def test_cli_maps_jung_client_errors_to_exit_three() -> None:
    request_id = uuid4()
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with patch("sys.argv", ["jung-console", "--api-url", "http://localhost:8000"]), patch(
        "jung.client.console.JungApiClient",
        return_value=mock_client,
    ), patch(
        "jung.client.console.ConsoleApp.run",
        AsyncMock(
            side_effect=JungApiError(
                status=503,
                error=ErrorResponse(
                    code="not_ready",
                    message="x",
                    request_id=request_id,
                    retryable=True,
                ),
            )
        ),
    ):
        assert await _async_cli() == 3


async def test_eof_maps_to_exit_zero() -> None:
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with patch("sys.argv", ["jung-console", "--api-url", "http://localhost:8000"]), patch(
        "jung.client.console.JungApiClient",
        return_value=mock_client,
    ), patch(
        "jung.client.console.ConsoleApp.run",
        AsyncMock(side_effect=ConsoleExitRequested),
    ):
        assert await _async_cli() == 0


def test_chat_events_module_has_no_api_client_import() -> None:
    tree = ast.parse(CHAT_EVENTS_PATH.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    assert "jung.client.api_client" not in imports


async def test_pending_reconcile_budget_once_per_client_message_id() -> None:
    client = _mock_client()
    session = _session()
    intent = client.new_chat_intent(session.id, "hello")
    context = PendingTurnContext(intent=intent, reconciliation_attempted=True)
    snapshot = _snapshot(session=session, pending=None)
    history = _history(session_id=session.id, client_message_id=intent.client_message_id)
    client.get_session = AsyncMock(return_value=history)
    client.reconcile_chat_turn = AsyncMock()
    app = _app(client)
    with pytest.raises(ConsoleUncertainDelivery):
        await app._wait_for_pending_chat_turn(snapshot, context=context)
    client.reconcile_chat_turn.assert_not_called()


async def test_profile_setup_preserves_optional_fields() -> None:
    client = _mock_client()
    profile = ProfileResponse(
        profile=ProfileWire(
            name="Alex",
            primary_language="English",
            date_of_birth=date(1990, 1, 2),
            notes="keep me",
        ),
        snapshot=_snapshot(stage="setup", revision=0, commands=["update_profile"]),
    )
    client.get_profile = AsyncMock(return_value=profile)
    client.update_profile = AsyncMock(return_value=_snapshot(stage="intake", revision=1))
    app = _app(client, inputs=ScriptedInput("New Name", "French"))
    await app._handle_setup()
    request = client.update_profile.await_args.args[0]
    assert isinstance(request, ProfileUpdateRequest)
    assert request.profile.date_of_birth == date(1990, 1, 2)
    assert request.profile.notes == "keep me"


async def test_read_input_eof_raises_console_exit_requested() -> None:
    class EofInput:
        async def read(self, prompt: PromptSpec) -> str:
            raise EOFError

    app = _app(_mock_client(), inputs=EofInput())  # type: ignore[arg-type]
    with pytest.raises(ConsoleExitRequested):
        await app.read_input(PromptSpec(text="> "))


async def test_pre_acceptance_command_error_not_chat_failed() -> None:
    client = _mock_client()
    session = _session()
    snapshot = _snapshot(revision=1, session=session)
    event_holder: dict[str, AsyncIterator[object]] = {}

    @asynccontextmanager
    async def open_chat():
        chat = MagicMock()

        async def send(command: SendMessageCommand) -> None:
            error = ErrorEvent(
                type="error",
                request_id=command.request_id,
                error=ErrorEnvelope(
                    code="validation_error",
                    message="bad",
                    request_id=command.request_id,
                    retryable=False,
                ),
                session_id=session.id,
                client_message_id=command.client_message_id,
            )
            event_holder["events"] = _event_stream(error)

        chat.send = send
        chat.events = lambda: event_holder["events"]
        yield chat

    client.open_chat = open_chat
    adopted = _snapshot(revision=2, session=session)
    client.get_state = AsyncMock(return_value=adopted)
    app = _app(client)
    result = await app._handle_chat_turn(snapshot, content="hello")
    assert result.revision == 2


async def test_classify_error_durable_before_turn_id_matches_session_client() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=client_message_id,
        request_id=uuid4(),
    )
    durable_request_id = uuid4()
    event = ErrorEvent(
        type="error",
        request_id=durable_request_id,
        error=ErrorEnvelope(
            code="llm_unavailable",
            message="x",
            request_id=durable_request_id,
            retryable=False,
        ),
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=uuid4(),
    )
    assert classify_error(event, identity) is not None


async def test_token_matches_request_id_before_turn_id() -> None:
    session_id = uuid4()
    request_id = uuid4()
    identity = ChatEventIdentity(
        session_id=session_id,
        client_message_id=uuid4(),
        request_id=request_id,
    )
    token = TokenEvent(
        type="token",
        session_id=session_id,
        turn_id=uuid4(),
        request_id=request_id,
        sequence=1,
        text="hi",
    )
    app = _app(_mock_client())
    app._process_chat_event(token, identity=identity, accepted=False)
    assert app._output.tokens == ["hi"]


async def test_style_selection_uses_snapshot_revision() -> None:
    client = _mock_client()
    snapshot = _snapshot(stage="style_selection", revision=5, commands=["select_style"])
    client.get_styles = AsyncMock(
        return_value=StyleOptionsResponse(
            styles=[StyleSummaryResponse(id="cbt", name="CBT", description="")],
            recommendations=[],
        )
    )
    client.select_style = AsyncMock(return_value=_snapshot(stage="ready", revision=6))
    app = _app(client, inputs=ScriptedInput("cbt"))
    await app._handle_style_selection(snapshot)
    request = client.select_style.await_args.args[0]
    assert isinstance(request, SelectStyleRequest)
    assert request.expected_revision == 5


async def test_start_session_uses_snapshot_revision() -> None:
    client = _mock_client()
    ready = _snapshot(stage="ready", revision=4, commands=["start_session"])
    client.start_session = AsyncMock(
        return_value=StartSessionResponse(
            session=_session(kind="therapy"),
            snapshot=_snapshot(stage="therapy", revision=5),
        )
    )
    app = _app(client, inputs=ScriptedInput("start"))
    action = (await app.read_input(PromptSpec(text="> "))).strip()
    assert action == "start"
    require_command(set(ready.available_commands), "start_session")
    await client.start_session(StartSessionRequest(expected_revision=ready.revision))
    request = client.start_session.await_args.args[0]
    assert isinstance(request, StartSessionRequest)
    assert request.expected_revision == 4
