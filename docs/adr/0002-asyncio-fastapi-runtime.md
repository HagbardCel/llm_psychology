---
owner: engineering
status: accepted
last_reviewed: 2026-07-21
review_cycle_days: 30
source_of_truth_for: Runtime, transport, and task supervision decision
---

# ADR 0002: Asyncio, FastAPI, and supervised work

## Decision

The supported runtime uses asyncio, FastAPI/Uvicorn, `httpx`, and plain RFC 6455
WebSockets (`websockets` for Python clients/tests). FastAPI/Starlette owns server
WebSockets. Socket.IO, Quart-Trio, and Trio/asyncio adapters are rejected.

FastAPI lifespan owns a `TaskSupervisor` backed by an entered
`asyncio.TaskGroup`. The supervisor wraps independent chat, assessment, and
post-session tasks: local failures are persisted and do not cancel unrelated
work or terminate lifespan. Detached `asyncio.create_task()` calls are
prohibited.

## Lifecycle

Startup initializes storage, returns stale operations to `PENDING`, marks stale
chat turns retryable failures, starts the supervisor, schedules pending
operations, then accepts requests. Shutdown rejects new mutations, signals work
to stop, waits for bounded graceful completion, persists recoverable state,
cancels remaining tasks, and closes resources.

## Consequences

The supported application and gateway tests run under `pytest-asyncio`.

## Related canonical documentation

- [Target Architecture](../refactor/target-architecture.md)
