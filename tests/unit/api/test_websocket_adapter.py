"""Serverless unit tests for the WebSocket adapter."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from starlette.datastructures import Headers
from starlette.websockets import WebSocketDisconnect

from jung.api.app import ApiState
from jung.api.settings import ApiSettings
from jung.api.websocket import _handle_chat_connection
from jung.config import build_settings
from jung.domain.errors import InvalidCommand
from jung.domain.models import AppSnapshot, Stage
from jung.events import EventStream, SnapshotChanged

pytestmark = pytest.mark.asyncio


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

    @asynccontextmanager
    async def subscribe(self):
        registered = False
        try:
            async with super().subscribe() as events:
                async with self._subscription_condition:
                    self._active_subscriptions += 1
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


FIXED_INVALID_REQUEST_ID = uuid4()


@pytest.mark.parametrize(
    ("text_payload", "expected_request_id"),
    [
        ("not json", None),
        (
            json.dumps(
                {
                    "type": "send_message",
                    "request_id": str(FIXED_INVALID_REQUEST_ID),
                }
            ),
            FIXED_INVALID_REQUEST_ID,
        ),
        (
            json.dumps(
                {
                    "type": "unknown",
                    "request_id": str(FIXED_INVALID_REQUEST_ID),
                    "session_id": str(uuid4()),
                    "client_message_id": str(uuid4()),
                    "expected_revision": 0,
                    "content": "secret-content",
                }
            ),
            FIXED_INVALID_REQUEST_ID,
        ),
    ],
)
async def test_invalid_inbound_produces_validation_error_without_content_echo(
    text_payload: str,
    expected_request_id: object,
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
    actual = UUID(errors[0]["request_id"])
    if expected_request_id is not None:
        assert actual == expected_request_id


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
