"""Serverless unit tests for the WebSocket adapter."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from starlette.websockets import WebSocketDisconnect

from jung.api.app import ApiState
from jung.api.settings import ApiSettings
from jung.api.websocket import (
    _handle_chat_connection,
    chat_websocket,
    mapping_context_for_event,
    recover_request_id,
)
from jung.composition import build_settings
from jung.domain.errors import InvalidCommand
from jung.domain.models import (
    AppSnapshot,
    ChatTurn,
    ChatTurnStatus,
    Message,
    MessageRole,
    Stage,
)
from jung.events import (
    ChatTokenGenerated,
    ChatTurnAccepted,
    ChatTurnCompleted,
    EventStream,
    SnapshotChanged,
)

pytestmark = pytest.mark.asyncio


def _now() -> datetime:
    return datetime.now(UTC)


def _chat_turn(**kwargs: Any) -> ChatTurn:
    now = _now()
    status = kwargs.pop("status", ChatTurnStatus.PENDING)
    session_id = kwargs.pop("session_id", uuid4())
    return ChatTurn(
        id=kwargs.pop("id", uuid4()),
        session_id=session_id,
        client_message_id=kwargs.pop("client_message_id", uuid4()),
        status=status,
        user_message_id=kwargs.pop("user_message_id", uuid4()),
        assistant_message_id=kwargs.pop(
            "assistant_message_id",
            uuid4() if status is ChatTurnStatus.COMPLETE else None,
        ),
        error_code=kwargs.pop("error_code", None),
        error_message=kwargs.pop("error_message", None),
        retryable=kwargs.pop("retryable", False),
        created_at=kwargs.pop("created_at", now),
        updated_at=kwargs.pop("updated_at", now),
        completed_at=kwargs.pop(
            "completed_at",
            now if status is ChatTurnStatus.COMPLETE else None,
        ),
        **kwargs,
    )


class SentinelError(Exception):
    pass


def _default_settings(
    *,
    send_timeout: float = 5.0,
    close_timeout: float = 2.0,
) -> ApiSettings:
    return ApiSettings(
        application=build_settings(
            database_path="data/jung.db",
            llm_base_url="http://127.0.0.1:8080/v1",
            llm_api_key="",
            default_model="local-model",
        ),
        websocket_send_timeout=send_timeout,
        websocket_close_timeout=close_timeout,
    )


class FakeWebSocket:
    def __init__(
        self,
        *,
        api_state: ApiState,
        api_settings: ApiSettings,
    ) -> None:
        self.app = SimpleNamespace(
            state=SimpleNamespace(api=api_state, api_settings=api_settings)
        )
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None
        self.sent: list[dict[str, Any]] = []
        self._receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._send_gate = asyncio.Event()
        self._send_gate.set()

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code

    async def receive(self) -> dict[str, Any]:
        return await self._receive_queue.get()

    def queue_disconnect(self) -> None:
        self._receive_queue.put_nowait({"type": "websocket.disconnect"})

    def queue_binary(self, payload: bytes = b"\x00") -> None:
        self._receive_queue.put_nowait({"type": "websocket.receive", "bytes": payload})

    def queue_text(self, text: str) -> None:
        self._receive_queue.put_nowait({"type": "websocket.receive", "text": text})

    def block_sends(self) -> None:
        self._send_gate.clear()

    def unblock_sends(self) -> None:
        self._send_gate.set()

    async def send_json(self, data: dict[str, Any]) -> None:
        await self._send_gate.wait()
        self.sent.append(data)


@dataclass
class MockApplication:
    submit_message: Any = None


@dataclass
class MockRuntime:
    application: MockApplication
    events: EventStream


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"request_id": str(uuid4())}, True),
        ({"request_id": "not-a-uuid"}, False),
        ([], False),
    ],
)
def test_recover_request_id(payload: object, expected: bool) -> None:
    recovered = recover_request_id(payload)
    if expected:
        assert recovered is not None
    else:
        assert recovered is None


@pytest.mark.parametrize(
    "text_payload",
    [
        "not json",
        json.dumps([]),
        json.dumps({"type": "send_message", "request_id": str(uuid4())}),
        json.dumps(
            {
                "type": "unknown",
                "request_id": str(uuid4()),
                "session_id": str(uuid4()),
                "client_message_id": str(uuid4()),
                "expected_revision": 0,
                "content": "secret-content",
            }
        ),
    ],
)
async def test_invalid_inbound_produces_validation_error_without_content_echo(
    text_payload: str,
) -> None:
    events = EventStream()
    runtime = MockRuntime(application=MockApplication(), events=events)
    fake = FakeWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    fake.queue_text(text_payload)
    fake.queue_disconnect()

    await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    errors = [item for item in fake.sent if item.get("type") == "error"]
    assert errors
    dumped = json.dumps(errors[0])
    assert "secret-content" not in dumped
    assert "input" not in dumped


async def test_binary_frame_then_valid_command() -> None:
    events = EventStream()
    runtime = MockRuntime(
        application=MockApplication(submit_message=AsyncMock()),
        events=events,
    )
    fake = FakeWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    fake.queue_binary()
    fake.queue_text(
        json.dumps(
            {
                "type": "send_message",
                "session_id": str(uuid4()),
                "client_message_id": str(uuid4()),
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "content": "hello",
            }
        )
    )
    fake.queue_disconnect()

    await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    assert runtime.application.submit_message.await_count == 1


async def test_not_ready_closes_without_accept() -> None:
    fake = FakeWebSocket(
        api_state=ApiState(runtime=None, ready=False),
        api_settings=_default_settings(),
    )
    await chat_websocket(fake)  # type: ignore[arg-type]
    assert not fake.accepted
    assert fake.closed


async def test_sentinel_error_propagates_and_drains_tasks() -> None:
    class EvilStream(EventStream):
        @asynccontextmanager
        async def subscribe(self):
            async def evil():
                raise SentinelError
                yield  # pragma: no cover

            yield evil()

    events = EvilStream()
    runtime = MockRuntime(application=MockApplication(), events=events)
    fake = FakeWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    fake.queue_disconnect()

    with pytest.raises(SentinelError):
        await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    await events.publish(
        SnapshotChanged(
            AppSnapshot(
                revision=0,
                stage=Stage.SETUP,
                profile_complete=False,
                available_commands=frozenset(),
            )
        )
    )
    assert fake.sent == []


async def test_parent_cancel_drains_tasks() -> None:
    events = EventStream()
    runtime = MockRuntime(application=MockApplication(), events=events)
    fake = FakeWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )

    handler = asyncio.create_task(
        _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]
    )
    await asyncio.sleep(0.05)
    handler.cancel()
    with pytest.raises(asyncio.CancelledError):
        await handler

    await events.publish(
        SnapshotChanged(
            AppSnapshot(
                revision=0,
                stage=Stage.SETUP,
                profile_complete=False,
                available_commands=frozenset(),
            )
        )
    )
    assert fake.sent == []


async def test_duplicate_complete_submit_sends_no_adapter_events() -> None:
    turn = _chat_turn(status=ChatTurnStatus.COMPLETE)
    events = EventStream()
    runtime = MockRuntime(
        application=MockApplication(submit_message=AsyncMock(return_value=turn)),
        events=events,
    )
    fake = FakeWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    fake.queue_text(
        json.dumps(
            {
                "type": "send_message",
                "session_id": str(turn.session_id),
                "client_message_id": str(turn.client_message_id),
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "content": "hello",
            }
        )
    )
    fake.queue_disconnect()

    await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    assert not any(
        item.get("type") in {"message_in_progress", "message_completed"}
        for item in fake.sent
    )


async def test_domain_error_uses_command_request_id() -> None:
    command_id = uuid4()
    session_id = uuid4()
    client_message_id = uuid4()
    events = EventStream()
    runtime = MockRuntime(
        application=MockApplication(
            submit_message=AsyncMock(side_effect=InvalidCommand("nope"))
        ),
        events=events,
    )
    fake = FakeWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    fake.queue_text(
        json.dumps(
            {
                "type": "send_message",
                "session_id": str(session_id),
                "client_message_id": str(client_message_id),
                "request_id": str(command_id),
                "expected_revision": 0,
                "content": "hello",
            }
        )
    )
    fake.queue_disconnect()

    await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    error = next(item for item in fake.sent if item["type"] == "error")
    assert error["request_id"] == str(command_id)
    assert error["error"]["request_id"] == str(command_id)


async def test_eviction_closes_slow_observer_while_healthy_receives() -> None:
    events = EventStream(max_queue_size=1)
    settings = _default_settings(send_timeout=30.0, close_timeout=0.5)

    async def start_observer(fake: FakeWebSocket, *, block_first: bool) -> asyncio.Task[None]:
        runtime = MockRuntime(application=MockApplication(), events=events)
        fake.app.state.api = ApiState(runtime=runtime, ready=True)  # type: ignore[arg-type]
        if block_first:
            fake.block_sends()
        return asyncio.create_task(
            _handle_chat_connection(fake, runtime, settings)  # type: ignore[arg-type]
        )

    slow = FakeWebSocket(
        api_state=ApiState(runtime=None, ready=True),
        api_settings=settings,
    )
    healthy = FakeWebSocket(
        api_state=ApiState(runtime=None, ready=True),
        api_settings=settings,
    )

    slow_task = await start_observer(slow, block_first=True)
    healthy_task = await start_observer(healthy, block_first=False)
    for _ in range(50):
        if slow.accepted and healthy.accepted:
            break
        await asyncio.sleep(0.01)
    assert slow.accepted and healthy.accepted

    snapshot = AppSnapshot(
        revision=1,
        stage=Stage.SETUP,
        profile_complete=False,
        available_commands=frozenset(),
    )
    for revision in range(2, 7):
        await events.publish(
            SnapshotChanged(snapshot.model_copy(update={"revision": revision}))
        )
        await asyncio.sleep(0.02)

    slow.unblock_sends()
    await asyncio.wait({slow_task, healthy_task}, timeout=2.0)

    assert slow.closed
    assert slow.close_code == 1011
    assert any(item.get("type") == "snapshot_changed" for item in healthy.sent)

    await events.publish(SnapshotChanged(snapshot.model_copy(update={"revision": 2})))
    await asyncio.sleep(0.05)
    snapshot_events = [
        item for item in healthy.sent if item.get("type") == "snapshot_changed"
    ]
    assert len(snapshot_events) >= 2


def test_mapping_context_stores_and_pops_turn_ids() -> None:
    turn_id = uuid4()
    request_id = uuid4()
    session_id = uuid4()
    turn_map: dict[UUID, UUID] = {}
    accepted = ChatTurnAccepted(
        session_id=session_id,
        turn_id=turn_id,
        request_id=request_id,
        turn=_chat_turn(
            id=turn_id,
            session_id=session_id,
            status=ChatTurnStatus.PENDING,
        ),
    )
    ctx = mapping_context_for_event(
        accepted,
        turn_request_ids=turn_map,
        connection_id="conn",
    )
    assert ctx.request_id == request_id
    assert turn_map[turn_id] == request_id

    completed = ChatTurnCompleted(
        session_id=session_id,
        turn_id=turn_id,
        turn=_chat_turn(
            id=turn_id,
            session_id=session_id,
            status=ChatTurnStatus.COMPLETE,
        ),
        assistant_message=Message(
            id=uuid4(),
            session_id=session_id,
            sequence=2,
            role=MessageRole.ASSISTANT,
            content="done",
            created_at=_now(),
            client_message_id=None,
        ),
    )
    completed_ctx = mapping_context_for_event(
        completed,
        turn_request_ids=turn_map,
        connection_id="conn",
    )
    assert completed_ctx.request_id == request_id
    assert turn_id not in turn_map


async def test_duplicate_pending_submit_emits_no_immediate_adapter_events() -> None:
    turn = _chat_turn(status=ChatTurnStatus.PENDING)
    events = EventStream()
    submit_message = AsyncMock(side_effect=[turn, turn])
    runtime = MockRuntime(
        application=MockApplication(submit_message=submit_message),
        events=events,
    )
    fake = FakeWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    command = {
        "type": "send_message",
        "session_id": str(turn.session_id),
        "client_message_id": str(turn.client_message_id),
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "content": "hello",
    }
    fake.queue_text(json.dumps(command))
    fake.queue_text(json.dumps({**command, "request_id": str(uuid4())}))

    handler = asyncio.create_task(
        _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]
    )
    while submit_message.await_count < 2:
        await asyncio.sleep(0.01)

    await events.publish(
        ChatTurnAccepted(
            session_id=turn.session_id,
            turn_id=turn.id,
            request_id=uuid4(),
            turn=turn,
        )
    )
    await asyncio.sleep(0.05)
    progress_count = sum(
        1 for item in fake.sent if item.get("type") == "message_in_progress"
    )

    await events.publish(
        ChatTokenGenerated(
            session_id=turn.session_id,
            turn_id=turn.id,
            request_id=uuid4(),
            sequence=1,
            text="tok",
        )
    )
    fake.queue_disconnect()
    await handler

    assert progress_count == 1
    assert any(item.get("type") == "token" for item in fake.sent)


async def test_dual_observer_healthy_receives_while_slow_blocked() -> None:
    events = EventStream()
    settings = _default_settings(send_timeout=30.0)

    async def start_observer(fake: FakeWebSocket, *, block_first: bool) -> asyncio.Task[None]:
        runtime = MockRuntime(application=MockApplication(), events=events)
        fake.app.state.api = ApiState(runtime=runtime, ready=True)  # type: ignore[arg-type]
        if block_first:
            fake.block_sends()
        return asyncio.create_task(
            _handle_chat_connection(fake, runtime, settings)  # type: ignore[arg-type]
        )

    slow = FakeWebSocket(
        api_state=ApiState(runtime=None, ready=True),
        api_settings=settings,
    )
    healthy = FakeWebSocket(
        api_state=ApiState(runtime=None, ready=True),
        api_settings=settings,
    )
    slow_task = await start_observer(slow, block_first=True)
    healthy_task = await start_observer(healthy, block_first=False)
    while not (slow.accepted and healthy.accepted):
        await asyncio.sleep(0.01)

    snapshot = AppSnapshot(
        revision=1,
        stage=Stage.SETUP,
        profile_complete=False,
        available_commands=frozenset(),
    )
    await events.publish(SnapshotChanged(snapshot))
    await asyncio.sleep(0.05)

    assert any(item.get("type") == "snapshot_changed" for item in healthy.sent)
    slow.unblock_sends()
    slow.queue_disconnect()
    healthy.queue_disconnect()
    await asyncio.gather(slow_task, healthy_task)


class DisconnectOnSendWebSocket(FakeWebSocket):
    async def send_json(self, data: dict[str, Any]) -> None:
        raise WebSocketDisconnect()


async def test_outbound_send_disconnect_terminates_without_propagation() -> None:
    events = EventStream()
    runtime = MockRuntime(application=MockApplication(), events=events)
    fake = DisconnectOnSendWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    fake.queue_disconnect()

    await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    await events.publish(
        SnapshotChanged(
            AppSnapshot(
                revision=1,
                stage=Stage.SETUP,
                profile_complete=False,
                available_commands=frozenset(),
            )
        )
    )
    assert fake.sent == []
