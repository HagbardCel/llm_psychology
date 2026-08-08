---
owner: engineering
status: active
last_reviewed: 2026-08-08
review_cycle_days: 30
source_of_truth_for: Runtime architecture, tech stack, source layout, and UI policy
---

# Architecture

> This document governs the supported Jung runtime architecture, dependency
> direction, and runtime boundaries. Workflow stages and transitions live in
> [workflow.md](workflow.md). HTTP/WebSocket contract semantics live in
> [api-v1.md](api-v1.md). Persistence tables and invariants live in
> [database.md](database.md).

## Goals

The supported runtime is a lean, local-first therapist application that:

- runs on one laptop for one real user;
- supports a disposable test profile through a separate database/data directory, not multi-user domain plumbing;
- exposes one stable HTTP/WebSocket API used by every client, including the console;
- keeps the API/application process as the sole product-level SQLite writer; clients never write the database directly;
- preserves dedicated, independently testable therapeutic phase behavior;
- minimizes framework-specific concepts and speculative abstractions;
- retains deterministic workflow probes and useful LLM observability.

## Tech stack

| Layer | Technology |
|---|---|
| Language/runtime | Python ≥3.11, asyncio |
| HTTP API | FastAPI + Uvicorn |
| WebSocket | FastAPI/Starlette server, `websockets` client |
| Models/contracts | Pydantic |
| Persistence | Python `sqlite3`, SQLite WAL |
| LLM integration | OpenAI Python SDK against OpenAI-compatible Chat Completions endpoints |
| HTTP client | HTTPX |
| Package management | uv |
| Tests | pytest + pytest-asyncio |
| Quality | Ruff |
| Packaging | Optional Docker Compose |

## Fixed architectural decisions

1. **Single-user domain**
   - No registration, login, user selection, `user_id`, per-user caches, or user-scoped routes.
   - Manual and automated tests select another data directory or temporary SQLite database.

2. **API-only clients**
   - Console, scripts, and workflow probes call `/api/v1` only.
   - Clients never import backend domain, persistence, or workflow implementation types.
   - `jung-console` is the supported reference frontend for manual sessions, contract integration, and deterministic workflow probes.

3. **One backend process**
   - The backend owns workflow state, persistence, LLM execution, concurrency control, and recovery.
   - Multiple connected clients may observe state, but only one conflicting state-changing operation is accepted at a time.

4. **Modular monolith**
   - No microservices, message broker, plugin framework, event sourcing, or general-purpose scheduler.
   - Docker remains an optional packaging and multi-process deployment mechanism, not an internal architecture requirement.

5. **One asyncio runtime**
   - Use asyncio consistently across API, WebSockets, LLM calls, console networking, background operations, and tests.
   - Trio adapters are not supported.

6. **One workflow model**
   - Persist one workflow stage and derive available commands from it.
   - See [workflow.md](workflow.md) for stages, transitions, operation/ChatTurn lifecycle, retry, and recovery.

7. **No schema migration compatibility**
   - Incompatible database schemas are rejected. Resetting requires stopping the application and manually removing `jung.db` together with any `jung.db-wal` and `jung.db-shm` sidecars. See [safety-and-data.md](safety-and-data.md) and [database.md](database.md).

## System shape

```text
Console client ── HTTP / WebSocket ── API adapter ── TherapyApplication
                                                       │
                                                       ├── SQLiteStore
                                                       ├── LLMGateway
                                                       └── phase processors
```

Dependency direction:

```text
clients → API contracts → API adapter → application → store / LLM ports
```

The application and phase packages must not import API or client packages.

The supported runtime package is `jung`. `config.py` defines environment-backed
`ApplicationSettings`, and the composition root constructs the application from
those settings rather than having runtime components read the environment
directly.

## Source layout

```text
src/jung/
├── api/             HTTP/WebSocket adapter
├── client/          typed API client + console
├── domain/          domain models, commands, errors
├── persistence/     SQLite implementation
├── phases/          therapeutic phase processors
├── llm/             LLM abstraction/provider adapter
├── application.py   use-case coordination
├── workflow.py      pure workflow policy
├── events.py        in-process event distribution
├── supervisor.py    accepted-work supervision
├── composition.py   composition root
└── config.py        application configuration
```

## Application boundary

All use cases enter through one explicitly constructed application service.
The application:

- validates commands against current stage and revision;
- coordinates phase processors;
- orchestrates use cases and selects workflow behavior (transition policy lives in workflow; SQL transactions and durable revision enforcement live in `SQLiteStore`);
- enforces concurrency and idempotency;
- starts and recovers long-running operations;
- returns domain results, not HTTP/WebSocket payloads.

Use-case surface (semantic):

- **Reads:** `get_snapshot`, `get_profile`, `get_style_options`, `list_sessions`, `get_session_history`, `get_chat_turn`
- **Mutations:** `update_profile`, `select_style`, `start_session` (returns session plus snapshot), `end_session`, `retry_operation`
- **Chat:** `submit_message` accepts a turn; accepted chat work is application-owned
- **Lifecycle:** `recover_on_startup`, `begin_shutdown`

Accepted chat work is application-owned. The composition root supplies an
application event subscription port for API adapters; WebSocket disconnects do
not own or cancel generation.

### Application event distribution

Live generation events are delivered through a small in-process broadcaster
(`EventStream`) owned by application composition. It is not a message broker,
event store, replay system, plugin bus, or generalized queueing framework.

Semantics:

- bounded in-process fan-out to currently connected subscribers;
- scoped subscriptions (enter/exit a subscription context; disconnect unsubscribes one client only);
- non-blocking publication;
- slow-subscriber eviction;
- no replay — token delivery is best-effort to currently connected observers only;
- accepted generation continues after disconnect;
- token events are ephemeral and never advance revision;
- completed messages and snapshot changes are durable.

`submit_message` validates stage, revision, session, and idempotency; persists
the user message and pending `ChatTurn`; increments snapshot revision; schedules
generation through the application task supervisor; and returns the accepted
`ChatTurn`. Token events are published through `EventStream`; API adapters map
them to WebSocket `token` events. See [workflow.md](workflow.md) for ChatTurn
lifecycle and recovery, and [api-v1.md](api-v1.md) for wire events.

No generic service locator or runtime string-based dependency lookup remains.

## Therapeutic phase processors

Therapeutic behavior is implemented by narrow phase processors rather than autonomous orchestration objects.

### Retained top-level processors

- `IntakeProcessor`
- `AssessmentProcessor`
- `TherapyProcessor`
- `PostSessionProcessor`

Each processor owns its prompt strategy, phase-specific policy, and typed output. It does not own persistence, WebSocket messaging, global workflow transitions, or dependency construction.

Processors should not call other workflow processors. A coordinator may call pure/stateless helpers such as `summarize_session()` or `propose_plan_patch()`.

## Workflow, API, and persistence (owned elsewhere)

One persisted workflow stage and backend-derived command set govern progression.
See [workflow.md](workflow.md) for stages, transitions, operation/ChatTurn
lifecycle, retry, and recovery semantics.

Clients use versioned HTTP and WebSocket interfaces under `/api/v1`. See
[api-v1.md](api-v1.md) for routes, DTOs, public errors, ordering, and WebSocket
messages.

Persistence uses one explicit `SQLiteStore` with immutable plan revisions and
durable operation/chat idempotency. See [database.md](database.md) for tables,
relationships, and invariants.

## Console client

The console is the reference API client. It must use one reusable `JungApiClient` and must not perform direct database or application calls.

```text
console UI → JungApiClient → /api/v1
```

Use HTTP for commands and snapshots and WebSocket for chat streaming and state/operation notifications. Console contract tests run against an ephemeral real API server.

Development priority: backend workflow and persistence correctness, then LLM
reliability, then `/api/v1` contract stability, then `jung-console` and
deterministic workflow-probe reliability.

## LLM boundary

Application and phase code depend only on a small project-owned protocol with
two capabilities: `stream_text` for token streaming and `generate_structured`
for typed structured output. `generate_structured` may take an optional
result-validation hook. Only the `llm/` infrastructure package imports provider
and structured-output libraries. Provider-specific types must not leak into
production `src/jung` domain, application, phase, API, or client code.
Adapter-focused tests may use provider test types.

Structured-output capability is configuration-driven (`json_schema`,
`json_object`, or `prompt`), not inferred from provider identity. The adapter
uses Chat Completions-compatible behavior only and makes one correction attempt
before returning `invalid_llm_output`.

The concrete provider is OpenAI-compatible and must work with llama.cpp,
LM Studio, OpenRouter, and equivalent endpoints by changing configuration
rather than application code.

## Runtime synchronization

Explicit server-side structure:

- one process-level mutation lock for state-changing commands;
- one generation lock / one active generation at a time;
- FastAPI lifespan owns a failure-isolating application `TaskSupervisor` backed by an `asyncio.TaskGroup`;
- independent chat and operation failures are persisted locally and must not cancel siblings or API lifespan;
- detached tasks are prohibited;
- each synchronous store operation opens and closes its own SQLite connection;
- async code calls whole store operations via `asyncio.to_thread()`; no connection is shared across threads.

Behavioral concurrency (when commands conflict, when `busy` applies, one active
session/operation/chat behavior, retry/recovery) is specified in
[workflow.md](workflow.md).

## Error model

Errors are mapped at the API boundary to the stable public taxonomy documented
in [api-v1.md](api-v1.md). Domain and application layers do not construct
transport errors.

## Docker

Docker packages the system but does not define internal boundaries.

The root [Docker Compose configuration](../docker-compose.yml) defines a
single `api` service. Manual user testing reuses that service through the
`ui-console-test` Make target with an isolated Compose project, port,
environment file, and data directory.

Native development remains the normal path; see [development.md](development.md).

## Observability

Retain structured command, operation, and LLM call tracing through boundary decorators/middleware. Diagnostics observe the system and must not become workflow state or API contract fields.

Ordinary logs may include safe LLM metadata when enabled. Opt-in
`JUNG_DEBUG_RUN_DIR` writes a sensitive correlated `trace.jsonl` for local
debugging (provider LLM traffic, accepted structured outputs, domain
outcomes, workflow state, and task lifecycle)—not a forensic completeness
guarantee. See [safety-and-data.md](safety-and-data.md).

Minimum useful ordinary-log records:

- command accepted/completed/failed;
- stage before/after and state revision;
- operation lifecycle;
- LLM task, model, latency, token usage when available, validation attempts, and status;
- correlation/request/session identifiers without unnecessary prompt content.

## Constraints / non-goals

The supported product explicitly excludes:

- multi-user support;
- authentication for localhost;
- microservices or queues;
- event sourcing;
- generic agent/plugin frameworks;
- Trio or Socket.IO as part of the runtime;
- ORM or migration subsystems;
- generalized RAG without a concrete retrieval use case;
- provider load balancing;
- Responses API, tool calling, or LangChain graphs as application assumptions;
- database migration support.
