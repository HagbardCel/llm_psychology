---
owner: engineering
status: active
last_reviewed: 2026-07-20
review_cycle_days: 30
source_of_truth_for: Supported architecture for the single-user Jung runtime
---

# Target Architecture

> This document governs the supported Phase 6C Jung runtime. It defines the
> architecture, dependency direction, and runtime boundaries for current work.

## Goals

The refactor should produce a lean, local-first therapist application that:

- runs on one laptop for one real user;
- supports a disposable test profile through a separate database/data directory, not multi-user domain plumbing;
- exposes one stable HTTP/WebSocket API used by every frontend, including the console client;
- keeps the backend as the only writer to SQLite;
- preserves dedicated, independently testable therapeutic phase behavior;
- minimizes framework-specific concepts and speculative abstractions;
- may introduce breaking changes and reset the database;
- retains deterministic workflow probes and useful LLM observability.

## Fixed architectural decisions

1. **Single-user domain**
   - No registration, login, user selection, `user_id`, per-user caches, or user-scoped routes.
   - Manual and automated tests select another data directory or temporary SQLite database.

2. **API-only clients**
   - Console, web, scripts, and workflow probes call `/api/v1`.
   - Clients never import backend domain, persistence, or workflow implementation types.

3. **One backend process**
   - The backend owns workflow state, persistence, LLM execution, concurrency control, and recovery.
   - Multiple connected clients may observe state, but only one conflicting state-changing operation is accepted at a time.

4. **Modular monolith**
   - No microservices, message broker, plugin framework, event sourcing, or general-purpose scheduler.
   - Docker remains an optional packaging and multi-process deployment mechanism, not an internal architecture requirement.

5. **One asyncio runtime**
   - Use asyncio consistently across API, WebSockets, LLM calls, console networking, background operations, and tests.
   - Remove Trio-specific application and infrastructure layers during cutover.

6. **One workflow model**
   - Persist one `Stage` and derive available commands from it.
   - Do not maintain overlapping user status, workflow state, next action, event, and agent transition systems.

7. **No legacy compatibility layer**
   - Reset/recreate the database.
   - Do not support old and new schemas or old and new orchestration paths concurrently after cutover.

## System shape

```text
Console client ─┐
                ├── HTTP / WebSocket ── API adapter ── TherapyApplication
Web frontend ───┘                                      │
                                                       ├── SQLiteStore
                                                       ├── LLMGateway
                                                       └── phase processors
```

Dependency direction:

```text
clients → API contracts → API adapter → application → store / LLM ports
```

The application and phase packages must not import API or client packages.

## Supported package structure

```text
src/jung/
├── config.py
├── application.py
├── workflow.py
├── domain/
│   ├── models.py
│   ├── commands.py
│   └── results.py
├── phases/
│   ├── intake/
│   │   ├── processor.py
│   │   ├── prompts.py
│   │   ├── models.py
│   │   └── policy.py
│   ├── assessment/
│   │   ├── processor.py
│   │   ├── prompts.py
│   │   └── models.py
│   ├── therapy/
│   │   ├── processor.py
│   │   ├── prompts.py
│   │   ├── context.py
│   │   ├── models.py
│   │   └── styles/
│   └── post_session/
│       ├── processor.py
│       ├── prompts.py
│       ├── models.py
│       ├── summarizer.py
│       ├── profile_updater.py
│       └── plan_updater.py
├── llm/
│   ├── gateway.py
│   ├── openai_compatible.py
│   ├── structured.py
│   ├── tracing.py
│   └── fake.py
├── persistence/
│   └── sqlite_store.py
├── api/
│   ├── app.py
│   ├── contracts.py
│   ├── routes.py
│   ├── websocket.py
│   └── errors.py
└── client/
    ├── api_client.py
    ├── websocket_client.py
    └── console.py
```

The package name may remain `psychoanalyst_app` during implementation if renaming would add risk without reducing complexity. The boundaries above are the important part.

The package tree is illustrative. Begin with the fewest modules that preserve dependency boundaries; split only when a file has independently testable logic or distinct dependencies. In particular, post-session summarization/patch helpers and client transport code may start consolidated:

```text
phases/post_session/
  processor.py
  prompts.py
  models.py

client/
  api_client.py
  console.py
```

## Application boundary

All use cases enter through one explicitly constructed application service:

```python
class TherapyApplication:
    async def get_snapshot(self) -> AppSnapshot: ...
    async def update_profile(self, command: UpdateProfile) -> AppSnapshot: ...
    async def select_style(self, command: SelectStyle) -> AppSnapshot: ...
    async def start_session(self, command: StartSession) -> Session: ...
    async def end_session(self, command: EndSession) -> AppSnapshot: ...
    async def submit_message(self, command: SendMessage) -> ChatTurn: ...
    async def get_chat_turn(self, turn_id: UUID) -> ChatTurn: ...
    async def retry_operation(self, command: RetryOperation) -> AppSnapshot: ...
```

Responsibilities:

- validate commands against current stage and revision;
- coordinate phase processors;
- own transactions and workflow transitions;
- enforce concurrency and idempotency;
- start and recover long-running operations;
- return domain results, not HTTP/WebSocket payloads.

Accepted chat work is application-owned. The composition root supplies an
application event subscription port for API adapters; WebSocket disconnects do
not own or cancel generation.

### Application event distribution

Live generation events are delivered through a small in-process broadcaster owned
by application composition. It is not a message broker, event store, replay
system, plugin bus, or generalized queueing framework.

```python
class EventStream:
    async def subscribe(self) -> AsyncIterator[ApplicationEvent]: ...
    async def publish(self, event: ApplicationEvent) -> None: ...
```

`submit_message` validates stage, revision, session, and idempotency; persists
the user message and pending `ChatTurn`; increments snapshot revision; schedules
generation through the application task supervisor; and returns the accepted
`ChatTurn`. Token events are published through `EventStream`; API adapters map
them to WebSocket `token` events.

Fixed semantics:

- disconnecting a WebSocket unsubscribes that client only;
- accepted generation continues after disconnect;
- token events are ephemeral and never advance revision;
- completed messages and snapshot changes are durable;
- startup converts stale pending turns into retryable failures;
- resubmission with the same `client_message_id` never duplicates the user message;
- all connected observers receive completion and snapshot notifications;
- token delivery is best-effort to currently connected observers only (no replay).

No generic service locator or runtime string-based dependency lookup remains.

## Therapeutic phase processors

Dedicated behavior files remain, but agents become narrow phase processors rather than autonomous orchestration objects.

### Retained top-level processors

- `IntakeProcessor`
- `AssessmentProcessor`
- `TherapyProcessor`
- `PostSessionProcessor`

Each processor owns its prompt strategy, phase-specific policy, and typed output. It does not own persistence, WebSocket messaging, global workflow transitions, or dependency construction.

### Mapping from current agents

| Current component | Target treatment |
|---|---|
| Intake agent | Retain as `phases/intake/processor.py` |
| Assessment agent | Retain and simplify as `phases/assessment/processor.py` |
| Therapist agent | Retain as the primary streaming `TherapyProcessor` |
| Reflection agent | Evolve into `PostSessionProcessor` |
| Note-taker agent | Split into intake/post-session helper functions or narrow services |
| Planning agent | Fold initial planning into assessment and later changes into post-session processing |
| Memory agent | Fold durable profile/plan patch generation into post-session processing |
| Agent factory/registry | Delete; wire processors explicitly in the composition root |

Processors should not call other workflow processors. A coordinator may call pure/stateless helpers such as `summarize_session()` or `propose_plan_patch()`.

## Workflow model

Use one persisted stage:

```python
class Stage(StrEnum):
    SETUP = "setup"
    INTAKE = "intake"
    ASSESSMENT = "assessment"
    STYLE_SELECTION = "style_selection"
    READY = "ready"
    THERAPY = "therapy"
    POST_SESSION = "post_session"
```

Expected progression:

```text
SETUP → INTAKE → ASSESSMENT → STYLE_SELECTION → READY
READY → THERAPY → POST_SESSION → READY
```

Commands are explicit application inputs, for example:

```text
update_profile
send_message
select_style
start_session
end_session
retry_operation
```

Intake completion is processor-driven during chat acceptance, not a separate client command.

The backend derives `available_commands` from the current snapshot. Clients display and invoke commands but do not implement workflow progression.

## Authoritative snapshot

```python
class AppSnapshot(BaseModel):
    revision: int
    stage: Stage
    profile_complete: bool
    selected_style: str | None
    active_session: SessionSummary | None
    operation: OperationSummary | None
    active_chat_turn: ChatTurnSummary | None
    available_commands: list[Command]
```

Every committed state change increments `revision`. State-changing requests may provide `expected_revision`; stale commands fail with `state_conflict`.

The snapshot replaces overlapping next-action messages, state signatures, and multiple status representations.

## Long-running operations

Use one generic persisted operation type for assessment and post-session processing:

```python
class OperationKind(StrEnum):
    ASSESSMENT = "assessment"
    POST_SESSION = "post_session"

class OperationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
```

Operations are idempotent by `(kind, source_session_id)`. On startup, stale `RUNNING` operations return to `PENDING` and are retried. This replaces job trees, child jobs, and a generalized scheduler.

Chat generation uses a separate durable `ChatTurn`, keyed by `(session_id, client_message_id)`, with `pending`, `complete`, and `failed` states. A disconnect does not cancel accepted work. Stale pending turns become retryable failures at startup; retrying the same client message never duplicates the persisted user message.

## API boundary

Use a small versioned API:

```text
GET    /api/v1/state
GET    /api/v1/profile
PUT    /api/v1/profile
GET    /api/v1/styles
PUT    /api/v1/style
GET    /api/v1/sessions
GET    /api/v1/sessions/{session_id}
POST   /api/v1/sessions
POST   /api/v1/sessions/{session_id}/end
POST   /api/v1/operations/current/retry
GET    /api/v1/health
WS     /api/v1/chat
```

No user routes, login, client-version negotiation, user query parameters, generic workflow-state mutation, or generic job lookup.

WebSocket server events should be a discriminated union containing only durable product semantics:

- `token`
- `message_in_progress`
- `message_completed`
- `snapshot_changed`
- `operation_changed`
- `error`

On reconnect, the client fetches `/state`; no event replay subsystem is required.

HTTP owns authoritative reads and non-chat commands. WebSocket owns `send_message`, token streaming, completion, and live notifications. A chat command includes `session_id`, `client_message_id`, `request_id`, and `expected_revision`; duplicate client message IDs are resolved before revision validation. Tokens are ephemeral and never advance revision. The server persists a pending turn and revision before streaming, then persists completion and a later revision before emitting `message_completed` followed by `snapshot_changed`.

## Console client

The console is the reference API client. It must use one reusable `JungApiClient` and must not perform direct database or application calls.

```text
console UI → JungApiClient → /api/v1
```

Use HTTP for commands and snapshots and WebSocket for chat streaming and state/operation notifications. Console contract tests run against an ephemeral real API server.

## Persistence

Use explicit SQL behind one concrete `SQLiteStore`. Avoid an ORM, repository-per-table hierarchy, connection pool abstraction, migration compatibility layer, and transitional database facade.

Supported tables:

- `app_state`
- `profile`
- `sessions`
- `messages`
- `plans`
- `operations`
- `chat_turns`

Messages are normalized by session and sequence. Chat idempotency uses the durable `(session_id, client_message_id)` key on `chat_turns`; `Message.client_message_id` is a derived read-model field joined from the owning turn, not a duplicate column on `messages`. Command retry safety comes from revision checks, snapshot reread, operation uniqueness, and chat turn keys — not a generic receipt store. Plans remain immutable, versioned revisions. Profile and derived result documents may be validated JSON where relational querying is not needed.

Atomic store methods should commit multi-table use cases such as assessment completion and post-session completion.

Each synchronous store operation opens and closes its own SQLite connection. Schema initialization enables WAL; connections enable foreign keys and a bounded busy timeout. Async code calls whole store operations via `asyncio.to_thread()`; no connection is shared across threads.

## LLM boundary

Application and phase code depend only on a small project-owned protocol:

```python
class LLMGateway(Protocol):
    async def stream_text(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
    ) -> AsyncIterator[str]: ...

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
    ) -> T: ...
```

Only the `llm/` infrastructure package imports provider and structured-output libraries. Provider-specific types must not leak into processors, application code, API contracts, or tests.

Structured-output capability is configuration-driven (`json_schema`, `json_object`, or `prompt`), not inferred from provider identity. The initial adapter uses Chat Completions-compatible behavior only and makes one correction attempt before returning `invalid_llm_output`.

The initial concrete provider is OpenAI-compatible and must work with llama.cpp, LM Studio, OpenRouter, and equivalent endpoints by changing configuration rather than application code.

## Concurrency

Explicit server-side rules:

- one process-level lock for state-changing commands;
- one active generation at a time;
- one active therapy session;
- one current background operation;
- conflicting commands return `busy` or `state_conflict`;
- cancellation and shutdown remain structured under asyncio task ownership.

FastAPI lifespan owns a failure-isolating application task supervisor backed by an `asyncio.TaskGroup`. Independent chat and operation failures are persisted locally and must not cancel siblings or API lifespan; detached tasks are prohibited.

## Error model

Use one small taxonomy mapped at the API boundary:

```text
invalid_command
state_conflict
busy
not_found
llm_unavailable
llm_timeout
invalid_llm_output
operation_failed
internal_error
```

Processors and stores raise domain/application exceptions. They do not construct HTTP or WebSocket errors.

## Docker

Docker packages the system but does not define internal boundaries.

Target Compose services:

- `api`
- `web` when implemented
- optional `console` profile

Native development must remain supported:

```bash
uv run jung-api
uv run jung-console --api-url http://127.0.0.1:8000
uv run pytest
```

Test profiles use temporary data volumes or databases, not duplicate API implementations or test-user services.

## Observability

Retain structured command, operation, and LLM call tracing through boundary decorators/middleware. Diagnostics observe the system and must not become workflow state or API contract fields.

Minimum useful records:

- command accepted/completed/failed;
- stage before/after and state revision;
- operation lifecycle;
- LLM task, model, latency, token usage when available, validation attempts, and status;
- correlation/request/session identifiers without unnecessary prompt content.

## Explicit non-goals

Do not add during this refactor:

- multi-user support;
- authentication for localhost;
- microservices or queues;
- event sourcing;
- generic agent/plugin frameworks;
- generalized RAG without a concrete retrieval use case;
- provider load balancing;
- database migration support;
- compatibility adapters preserving the old architecture in `main`.
