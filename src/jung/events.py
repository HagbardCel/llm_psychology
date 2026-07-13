"""In-process application event fan-out."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from jung.domain.models import AppSnapshot, ChatTurn, Message, Operation

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


class _Subscription:
    def __init__(self, queue: asyncio.Queue[ApplicationEvent | object]) -> None:
        self.queue = queue

    async def events(self) -> AsyncIterator[ApplicationEvent]:
        while True:
            item = await self.queue.get()
            if item is _SUBSCRIPTION_CLOSED:
                return
            yield item


class EventStream:
    """Bounded local fan-out for currently connected observers."""

    def __init__(self, *, max_queue_size: int = 64) -> None:
        self._max_queue_size = max_queue_size
        self._subscribers: set[_Subscription] = set()
        self._lock = asyncio.Lock()

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
        async with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.queue.put_nowait(event)
            except asyncio.QueueFull:
                await self._evict(subscriber)

    async def _evict(self, subscription: _Subscription) -> None:
        async with self._lock:
            self._subscribers.discard(subscription)
        queue = subscription.queue
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(_SUBSCRIPTION_CLOSED)
        except asyncio.QueueFull:
            pass
