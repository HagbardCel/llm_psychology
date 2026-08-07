"""In-process application event fan-out."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from jung.domain.models import AppSnapshot, ChatTurn, Message, Operation

if TYPE_CHECKING:
    from jung.diagnostics import DiagnosticRecorder

_SUBSCRIPTION_CLOSED = object()


@dataclass(frozen=True, slots=True)
class ChatTurnAccepted:
    session_id: UUID
    turn_id: UUID
    request_id: UUID | None
    turn: ChatTurn


@dataclass(frozen=True, slots=True)
class ChatTokenGenerated:
    session_id: UUID
    turn_id: UUID
    request_id: UUID | None
    sequence: int
    text: str


@dataclass(frozen=True, slots=True)
class ChatTurnCompleted:
    session_id: UUID
    turn_id: UUID
    turn: ChatTurn
    assistant_message: Message


@dataclass(frozen=True, slots=True)
class ChatTurnFailed:
    session_id: UUID
    turn_id: UUID
    turn: ChatTurn


@dataclass(frozen=True, slots=True)
class SnapshotChanged:
    snapshot: AppSnapshot


@dataclass(frozen=True, slots=True)
class OperationChanged:
    operation: Operation
    snapshot: AppSnapshot


ApplicationEvent = (
    ChatTurnAccepted
    | ChatTokenGenerated
    | ChatTurnCompleted
    | ChatTurnFailed
    | SnapshotChanged
    | OperationChanged
)


def _diagnostic_projections(
    event: ApplicationEvent,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    match event:
        case ChatTurnAccepted():
            return (
                (
                    "chat.turn.accepted",
                    {
                        "session_id": str(event.session_id),
                        "turn_id": str(event.turn_id),
                        "client_message_id": str(event.turn.client_message_id),
                        "request_id": (
                            str(event.request_id)
                            if event.request_id is not None
                            else None
                        ),
                    },
                ),
            )
        case ChatTurnCompleted():
            return (
                (
                    "chat.turn.completed",
                    {
                        "session_id": str(event.session_id),
                        "turn_id": str(event.turn_id),
                        "client_message_id": str(event.turn.client_message_id),
                    },
                ),
            )
        case ChatTurnFailed():
            return (
                (
                    "chat.turn.failed",
                    {
                        "session_id": str(event.session_id),
                        "turn_id": str(event.turn_id),
                        "client_message_id": str(event.turn.client_message_id),
                        "error_code": event.turn.error_code,
                        "retryable": event.turn.retryable,
                    },
                ),
            )
        case OperationChanged(operation=operation, snapshot=snapshot):
            return (
                (
                    "operation.status",
                    {
                        "operation_id": str(operation.id),
                        "source_session_id": str(operation.source_session_id),
                        "kind": operation.kind.value,
                        "status": operation.status.value,
                        "attempt": operation.attempt,
                        "stage": snapshot.stage.value,
                        "revision": snapshot.revision,
                        "error_code": operation.error_code,
                        "retryable": operation.retryable,
                    },
                ),
                (
                    "workflow.state",
                    {
                        "revision": snapshot.revision,
                        "stage": snapshot.stage.value,
                    },
                ),
            )
        case SnapshotChanged(snapshot=snapshot):
            return (
                (
                    "workflow.state",
                    {
                        "revision": snapshot.revision,
                        "stage": snapshot.stage.value,
                    },
                ),
            )
        case ChatTokenGenerated():
            return ()
    return ()


class _Subscription:
    def __init__(self, queue: asyncio.Queue[ApplicationEvent | object]) -> None:
        self.queue = queue

    async def events(self) -> AsyncIterator[ApplicationEvent]:
        while True:
            item = await self.queue.get()
            if item is _SUBSCRIPTION_CLOSED:
                return
            yield item  # type: ignore[misc]


class EventStream:
    """Bounded local fan-out for currently connected observers."""

    def __init__(
        self,
        *,
        max_queue_size: int = 64,
        recorder: DiagnosticRecorder | None = None,
    ) -> None:
        self._max_queue_size = max_queue_size
        self._subscribers: set[_Subscription] = set()
        self._lock = asyncio.Lock()
        self._recorder = recorder

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[AsyncIterator[ApplicationEvent]]:
        queue: asyncio.Queue[ApplicationEvent | object] = asyncio.Queue(
            maxsize=self._max_queue_size
        )
        subscription = _Subscription(queue)
        async with self._lock:
            self._subscribers.add(subscription)
        try:
            yield subscription.events()
        finally:
            async with self._lock:
                self._subscribers.discard(subscription)

    async def publish(self, event: ApplicationEvent) -> None:
        # Keep membership checks, non-blocking delivery, and eviction atomic
        # across concurrent publishers.
        if self._recorder is not None:
            for kind, data in _diagnostic_projections(event):
                self._recorder.record(kind, data)
        async with self._lock:
            for subscriber in tuple(self._subscribers):
                try:
                    subscriber.queue.put_nowait(event)
                except asyncio.QueueFull:
                    self._subscribers.discard(subscriber)
                    _close_subscription_queue(subscriber.queue)


def _close_subscription_queue(
    queue: asyncio.Queue[ApplicationEvent | object],
) -> None:
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    queue.put_nowait(_SUBSCRIPTION_CLOSED)
