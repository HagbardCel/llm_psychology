"""Generic lifecycle observers for the console client."""

from __future__ import annotations

from typing import Any, Protocol


class ConsoleEventSink(Protocol):
    """Observe console lifecycle events without affecting client behavior."""

    async def emit(self, event: str, **fields: Any) -> None:
        """Record or react to a console lifecycle event."""


class NoOpConsoleEventSink:
    """Default observer used by the interactive console."""

    async def emit(self, event: str, **fields: Any) -> None:
        return None


class CompositeConsoleEventSink:
    """Fan out lifecycle events to multiple independent observers."""

    def __init__(self, *sinks: ConsoleEventSink):
        self.sinks = sinks

    async def emit(self, event: str, **fields: Any) -> None:
        for sink in self.sinks:
            await sink.emit(event, **fields)
