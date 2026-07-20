"""Serverless unit tests for the WebSocket adapter."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from starlette.datastructures import Headers
from starlette.websockets import WebSocketDisconnect

from jung.api.app import ApiState
from jung.api.settings import ApiSettings
from jung.api.websocket import (
    _handle_chat_connection,
    _origin_is_allowed,
    chat_websocket,
    mapping_context_for_event,
    recover_request_id,
)
from jung.config import build_settings
from jung.domain.errors import (
    InvalidCommand,
    InvariantViolation,
    RevisionConflict,
    StoredWorkFailure,
)
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
    allowed_origins: tuple[str, ...] = (),
) -> ApiSettings:
    return ApiSettings(
        application=build_settings(
            database_path="data/jung.db",
            llm_base_url="http://127.0.0.1:8080/v1",
            llm_api_key="",
            default_model="local-model",
        ),
        allowed_origins=allowed_origins,
        websocket_send_timeout=send_timeout,
        websocket_close_timeout=close_timeout,
    )


class FakeWebSocket:
    def __init__(
        self,
        *,
        api_state: ApiState,
        api_settings: ApiSettings,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.headers = Headers(headers=headers or {})
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
        self._sent_condition = asyncio.Condition()

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
        async with self._sent_condition:
            self.sent.append(data)
            self._sent_condition.notify_all()

    async def wait_for_snapshot_revision(
        self,
        revision: int,
        *,
        timeout: float = 1.0,
    ) -> None:
        def was_received() -> bool:
            return any(
                item.get("type") == "snapshot_changed"
                and item.get("snapshot", {}).get("revision") == revision
                for item in self.sent
            )

        async with asyncio.timeout(timeout):
            async with self._sent_condition:
                await self._sent_condition.wait_for(was_received)


class SlowFakeWebSocket(FakeWebSocket):
    def __init__(
        self,
        *,
        api_state: ApiState,
        api_settings: ApiSettings,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            api_state=api_state,
            api_settings=api_settings,
            headers=headers,
        )
        self.first_send_started = asyncio.Event()

    async def send_json(self, data: dict[str, Any]) -> None:
        if not self.first_send_started.is_set():
            self.first_send_started.set()
        await super().send_json(data)


class TrackingEventStream(EventStream):
    def __init__(self, *, max_queue_size: int = 64) -> None:
        super().__init__(max_queue_size=max_queue_size)
        self._subscription_condition = asyncio.Condition()
        self._active_subscriptions = 0
        self._subscription_entries = 0

    @property
    def total_subscription_entries(self) -> int:
        return self._subscription_entries

    @asynccontextmanager
    async def subscribe(self):
        registered = False
        try:
            async with super().subscribe() as events:
                async with self._subscription_condition:
                    self._active_subscriptions += 1
                    self._subscription_entries += 1
                    registered = True
                    self._subscription_condition.notify_all()
                yield events
        finally:
            if registered:
                async with self._subscription_condition:
                    self._active_subscriptions -= 1
                    self._subscription_condition.notify_all()

    async def wait_for_subscriptions(self, count: int, *, timeout: float = 1.0) -> None:
        async with asyncio.timeout(timeout):
            async with self._subscription_condition:
                await self._subscription_condition.wait_for(
                    lambda: self._active_subscriptions == count
                )


def _snapshot_event(*, revision: int) -> SnapshotChanged:
    return SnapshotChanged(
        AppSnapshot(
            revision=revision,
            stage=Stage.SETUP,
            profile_complete=False,
            available_commands=frozenset(),
        )
    )


def snapshot_revisions(fake: FakeWebSocket) -> list[int]:
    return [
        event["snapshot"]["revision"]
        for event in fake.sent
        if event.get("type") == "snapshot_changed"
    ]


@dataclass
class MockApplication:
    submit_message: Any = None
    get_snapshot: Any = None


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
    events = TrackingEventStream(max_queue_size=4)
    settings = _default_settings(send_timeout=30.0, close_timeout=0.5)

    async def start_observer(
        fake: FakeWebSocket,
        *,
        block_first: bool,
    ) -> asyncio.Task[None]:
        runtime = MockRuntime(application=MockApplication(), events=events)
        fake.app.state.api = ApiState(runtime=runtime, ready=True)  # type: ignore[arg-type]
        if block_first:
            fake.block_sends()
        return asyncio.create_task(
            _handle_chat_connection(fake, runtime, settings)  # type: ignore[arg-type]
        )

    slow = SlowFakeWebSocket(
        api_state=ApiState(runtime=None, ready=True),
        api_settings=settings,
    )
    healthy = FakeWebSocket(
        api_state=ApiState(runtime=None, ready=True),
        api_settings=settings,
    )

    slow_task = await start_observer(slow, block_first=True)
    healthy_task = await start_observer(healthy, block_first=False)

    try:
        await events.wait_for_subscriptions(2)

        await events.publish(_snapshot_event(revision=1))
        await asyncio.wait_for(slow.first_send_started.wait(), timeout=1.0)
        await healthy.wait_for_snapshot_revision(1)

        for revision in range(2, 7):
            await events.publish(_snapshot_event(revision=revision))
            await healthy.wait_for_snapshot_revision(revision)

        slow.unblock_sends()
        await asyncio.wait_for(slow_task, timeout=1.0)

        assert snapshot_revisions(slow) == [1]
        assert snapshot_revisions(healthy) == [1, 2, 3, 4, 5, 6]
        assert slow.closed
        assert slow.close_code == 1011
    finally:
        if not slow_task.done():
            slow.queue_disconnect()
            slow_task.cancel()
        if not healthy_task.done():
            healthy.queue_disconnect()
            healthy_task.cancel()
        await asyncio.gather(slow_task, healthy_task, return_exceptions=True)
        await events.wait_for_subscriptions(0)


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
    events = TrackingEventStream()
    settings = _default_settings(send_timeout=30.0)

    async def start_observer(
        fake: FakeWebSocket, *, block_first: bool
    ) -> asyncio.Task[None]:
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

    try:
        await events.wait_for_subscriptions(2)
        await events.publish(_snapshot_event(revision=1))
        await healthy.wait_for_snapshot_revision(1)
        assert any(item.get("type") == "snapshot_changed" for item in healthy.sent)
    finally:
        slow.unblock_sends()
        if not slow_task.done():
            slow.queue_disconnect()
            slow_task.cancel()
        if not healthy_task.done():
            healthy.queue_disconnect()
            healthy_task.cancel()
        await asyncio.gather(slow_task, healthy_task, return_exceptions=True)
        await events.wait_for_subscriptions(0)


class DisconnectOnSendWebSocket(FakeWebSocket):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.send_attempted = asyncio.Event()

    async def send_json(self, data: dict[str, Any]) -> None:
        self.send_attempted.set()
        raise WebSocketDisconnect()


async def test_outbound_send_disconnect_terminates_without_propagation() -> None:
    events = TrackingEventStream()
    runtime = MockRuntime(application=MockApplication(), events=events)
    fake = DisconnectOnSendWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    settings = _default_settings()

    handler = asyncio.create_task(
        _handle_chat_connection(fake, runtime, settings)  # type: ignore[arg-type]
    )

    try:
        await events.wait_for_subscriptions(1)
        await events.publish(_snapshot_event(revision=1))

        await asyncio.wait_for(fake.send_attempted.wait(), timeout=1.0)
        await asyncio.wait_for(handler, timeout=1.0)

        assert handler.done()
        assert not handler.cancelled()
    finally:
        if not handler.done():
            fake.queue_disconnect()
            handler.cancel()

        await asyncio.gather(handler, return_exceptions=True)
        await events.wait_for_subscriptions(0)


async def test_internal_error_logs_without_sensitive_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_content = "private therapy content"
    internal_detail = "private invariant detail"
    request_id = uuid4()
    session_id = uuid4()
    client_message_id = uuid4()
    events = EventStream()
    runtime = MockRuntime(
        application=MockApplication(
            submit_message=AsyncMock(side_effect=InvariantViolation(internal_detail))
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
                "request_id": str(request_id),
                "expected_revision": 0,
                "content": secret_content,
            }
        )
    )
    fake.queue_disconnect()

    with caplog.at_level(logging.ERROR, logger="jung.api.websocket"):
        await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    records = [
        record
        for record in caplog.records
        if record.message == "websocket_command_rejected"
        and getattr(record, "request_id", None) == str(request_id)
        and getattr(record, "error_code", None) == "internal_error"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.ERROR
    assert getattr(record, "exception_type", None) == "InvariantViolation"
    assert getattr(record, "request_id", None) == str(request_id)
    assert getattr(record, "session_id", None) == str(session_id)
    assert secret_content not in caplog.text
    assert internal_detail not in caplog.text

    error = next(item for item in fake.sent if item.get("type") == "error")
    assert error["error"]["code"] == "internal_error"
    assert error["error"]["message"] == "An unexpected error occurred."


async def test_stored_work_failure_does_not_log_internal_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request_id = uuid4()
    session_id = uuid4()
    client_message_id = uuid4()
    events = EventStream()
    runtime = MockRuntime(
        application=MockApplication(
            submit_message=AsyncMock(
                side_effect=StoredWorkFailure(
                    code="internal_error",
                    message="stored safe message",
                    retryable=False,
                )
            )
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
                "request_id": str(request_id),
                "expected_revision": 0,
                "content": "hello",
            }
        )
    )
    fake.queue_disconnect()

    with caplog.at_level(logging.ERROR, logger="jung.api.websocket"):
        caplog.clear()
        await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    records = [
        record
        for record in caplog.records
        if record.message == "websocket_command_rejected"
        and getattr(record, "error_code", None) == "internal_error"
    ]
    assert records == []


@pytest.mark.parametrize(
    ("origin", "allowed_origins", "expected"),
    [
        (None, (), True),
        (None, ("http://frontend.test",), True),
        ("http://frontend.test", ("http://frontend.test",), True),
        ("http://evil.test", ("http://frontend.test",), False),
        ("http://evil.test", (), False),
        ("null", (), False),
        ("null", ("null",), False),
    ],
)
def test_origin_is_allowed_policy(
    origin: str | None,
    allowed_origins: tuple[str, ...],
    expected: bool,
) -> None:
    headers = {"Origin": origin} if origin is not None else {}
    fake = FakeWebSocket(
        headers=headers,
        api_state=ApiState(runtime=None, ready=False),
        api_settings=_default_settings(allowed_origins=allowed_origins),
    )
    assert _origin_is_allowed(fake, fake.app.state.api_settings) is expected


async def test_disallowed_origin_is_rejected_before_runtime_lookup() -> None:
    fake = FakeWebSocket(
        headers={"Origin": "http://evil.test"},
        api_state=ApiState(runtime=None, ready=False),
        api_settings=_default_settings(allowed_origins=("http://frontend.test",)),
    )

    await chat_websocket(fake)  # type: ignore[arg-type]

    assert not fake.accepted
    assert fake.closed
    assert fake.close_code == 1008


async def test_disallowed_origin_never_subscribes() -> None:
    events = TrackingEventStream()
    runtime = MockRuntime(
        application=MockApplication(),
        events=events,
    )
    fake = FakeWebSocket(
        headers={"Origin": "http://evil.test"},
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(allowed_origins=("http://frontend.test",)),
    )

    fake.queue_disconnect()

    await asyncio.wait_for(chat_websocket(fake), timeout=1.0)  # type: ignore[arg-type]

    assert not fake.accepted
    assert fake.closed
    assert fake.close_code == 1008
    assert events.total_subscription_entries == 0


async def test_allowed_configured_origin_subscribes_to_event_stream() -> None:
    events = TrackingEventStream()
    runtime = MockRuntime(
        application=MockApplication(),
        events=events,
    )
    fake = FakeWebSocket(
        headers={"Origin": "http://frontend.test"},
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(allowed_origins=("http://frontend.test",)),
    )

    task = asyncio.create_task(chat_websocket(fake))  # type: ignore[arg-type]
    try:
        await events.wait_for_subscriptions(1)
        assert fake.accepted
    finally:
        fake.queue_disconnect()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await events.wait_for_subscriptions(0)


async def test_revision_conflict_enrichment_failure_preserves_conflict_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stale_request_id = uuid4()
    session_id = uuid4()
    client_message_id = uuid4()
    second_request_id = uuid4()
    secret = "secret enrichment detail"
    events = EventStream()
    submit_message = AsyncMock(
        side_effect=[RevisionConflict(1, 2), _chat_turn(status=ChatTurnStatus.PENDING)]
    )
    get_snapshot = AsyncMock(side_effect=RuntimeError(secret))
    runtime = MockRuntime(
        application=MockApplication(
            submit_message=submit_message,
            get_snapshot=get_snapshot,
        ),
        events=events,
    )
    fake = FakeWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    stale_command = json.dumps(
        {
            "type": "send_message",
            "session_id": str(session_id),
            "client_message_id": str(client_message_id),
            "request_id": str(stale_request_id),
            "expected_revision": 1,
            "content": "stale",
        }
    )
    second_command = json.dumps(
        {
            "type": "send_message",
            "session_id": str(session_id),
            "client_message_id": str(uuid4()),
            "request_id": str(second_request_id),
            "expected_revision": 2,
            "content": "retry",
        }
    )
    fake.queue_text(stale_command)
    fake.queue_text(second_command)
    fake.queue_disconnect()

    with caplog.at_level(logging.ERROR, logger="jung.api.websocket"):
        await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    assert submit_message.await_count == 2
    assert get_snapshot.await_count == 1

    error = next(item for item in fake.sent if item.get("type") == "error")
    assert error["error"]["code"] == "state_conflict"
    assert error["error"]["current_snapshot"] is None
    assert secret not in caplog.text
    assert secret not in json.dumps(fake.sent)

    records = [
        record
        for record in caplog.records
        if record.message == "Failed to enrich WebSocket revision conflict"
    ]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "exception_type", None) == "RuntimeError"
    assert getattr(record, "request_id", None) == str(stale_request_id)


async def test_websocket_lifecycle_logs_connected_and_disconnected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events = EventStream()
    runtime = MockRuntime(application=MockApplication(), events=events)
    fake = FakeWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    fake.queue_disconnect()

    with caplog.at_level(logging.INFO, logger="jung.api.websocket"):
        await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    connected = [
        record for record in caplog.records if record.message == "websocket_connected"
    ]
    disconnected = [
        record
        for record in caplog.records
        if record.message == "websocket_disconnected"
    ]
    assert len(connected) == 1
    assert len(disconnected) == 1
    connection_id = getattr(connected[0], "connection_id", None)
    assert connection_id is not None
    assert getattr(disconnected[0], "connection_id", None) == connection_id
    assert getattr(disconnected[0], "duration_ms", None) is not None


async def test_chat_command_resolved_logs_turn_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request_id = uuid4()
    turn = _chat_turn(status=ChatTurnStatus.PENDING)
    events = EventStream()
    runtime = MockRuntime(
        application=MockApplication(
            submit_message=AsyncMock(return_value=turn),
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
                "session_id": str(turn.session_id),
                "client_message_id": str(turn.client_message_id),
                "request_id": str(request_id),
                "expected_revision": 0,
                "content": "hello",
            }
        )
    )
    fake.queue_disconnect()

    with caplog.at_level(logging.INFO, logger="jung.api.websocket"):
        await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    records = [
        record
        for record in caplog.records
        if record.message == "chat_command_resolved"
        and getattr(record, "request_id", None) == str(request_id)
    ]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "turn_id", None) == str(turn.id)
    assert getattr(record, "turn_status", None) == "pending"
    assert getattr(record, "session_id", None) == str(turn.session_id)
    assert getattr(record, "client_message_id", None) == str(turn.client_message_id)


async def test_malformed_json_logs_websocket_protocol_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events = EventStream()
    runtime = MockRuntime(application=MockApplication(), events=events)
    fake = FakeWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    fake.queue_text("not-json")
    fake.queue_disconnect()

    with caplog.at_level(logging.INFO, logger="jung.api.websocket"):
        await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    records = [
        record
        for record in caplog.records
        if record.message == "websocket_protocol_rejected"
    ]
    assert len(records) == 1
    assert getattr(records[0], "error_code", None) == "validation_error"
    assert getattr(records[0], "request_id", None) is not None


async def test_domain_error_logs_websocket_command_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
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

    with caplog.at_level(logging.INFO, logger="jung.api.websocket"):
        await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    records = [
        record
        for record in caplog.records
        if record.message == "websocket_command_rejected"
        and getattr(record, "error_code", None) == "invalid_command"
        and getattr(record, "request_id", None) == str(command_id)
    ]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
