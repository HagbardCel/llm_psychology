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

5. **One asyncio runtime**
   - Use asyncio consistently across API, WebSockets, LLM calls, console networking, background operations, and tests.
   - Trio adapters are not supported.

6. **One workflow model**
   - Derive the current workflow stage from authoritative durable profile, session, plan, and operation state. Do not persist a second workflow-state projection.
   - See [workflow.md](workflow.md) for stages, transitions, operation lifecycle, message-native chat acceptance/retry, and recovery.

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
├── application.py   use-case façade
├── _application/    private chat/operation/input helpers
├── workflow.py      pure workflow policy
├── composition.py   composition root
└── config.py        application configuration
```

`TherapyApplication` remains the sole application-facing type. Private helpers under
`_application/` implement chat generation, durable operation tasks, phase-input
construction, and cancellation-safe store calls; they are not a public service layer.

## Application boundary

All use cases enter through one explicitly constructed application service.
The backend is the sole writer of workflow state. Clients do not participate in
concurrency control.

The application:

- serializes state-changing commands through a process-level mutation lock and validates each command against authoritative state at execution time;
- coordinates phase processors;
- orchestrates use cases and selects workflow behavior (transition policy lives in workflow; SQL transaction boundaries live in `SQLiteStore`);
- enforces server-side concurrency and idempotency;
- owns and recovers at most one long-running assessment or post-session operation task;
- streams chat generation on the calling connection through `stream_message`;
- returns domain results, not HTTP/WebSocket payloads.

Use-case surface (semantic):

- **Reads:** `get_snapshot`, `get_profile`, `get_style_options`, `list_sessions`, `get_session_history`
- **Mutations:** `update_profile`, `select_style`, `start_session` (returns session plus snapshot), `end_session`, `retry_operation`
- **Chat:** `stream_message` — connection-owned acceptance, token stream, and terminal result
- **Lifecycle:** `recover_on_startup`, `shutdown`

### Connection-owned chat streaming

Chat is not supervised background work and does not use an in-process event
fan-out. The WebSocket adapter calls `TherapyApplication.stream_message` on the
connection that issued `send_message`. That connection owns the stream:

- normally: one command frame → token events → one terminal event → close;
  active protocol aborts follow the uncertain-delivery behavior defined in
  [api-v1.md](api-v1.md);
- disconnect cancels generation for that attempt;
- durable truth is messages only (see [workflow.md](workflow.md) and
  [database.md](database.md));
- a generation lock serializes chat work and masks `available_commands` while
  generation is active (conflicting workflow commands return `busy`).

`TherapyApplication` schedules assessment and post-session operations as a
single owned asyncio task. See [api-v1.md](api-v1.md) for the four-event
WebSocket wire contract.

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

One derived workflow stage and backend-derived command set govern progression.
See [workflow.md](workflow.md) for stages, transitions, operation lifecycle,
message-native chat acceptance/retry, and recovery semantics.

Clients use versioned HTTP and WebSocket interfaces under `/api/v1`. See
[api-v1.md](api-v1.md) for routes, DTOs, public errors, ordering, and WebSocket
messages.

Persistence uses one explicit `SQLiteStore` with immutable plan revisions and
durable message/operation idempotency. See [database.md](database.md) for tables,
relationships, and invariants.

## Console client

The console is the reference API client. It must use one reusable `JungApiClient` and must not perform direct database or application calls.

```text
console UI → JungApiClient → /api/v1
```

Use HTTP for commands and snapshots and a one-shot WebSocket
(`JungChatConnection.stream`) for each chat message. Console contract tests run
against an ephemeral real API server.

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

- one process-level mutation lock for state-changing commands (`TherapyApplication`);
- `SQLiteStore` owns `BEGIN IMMEDIATE` transaction boundaries for durable writes;
- clients observe state and issue commands; they do not send concurrency tokens or otherwise participate in concurrency control;
- one generation lock / one active generation at a time;
- while generation is active, snapshot assembly masks `available_commands` to empty, and public workflow commands that conflict with generation return `busy`;
- FastAPI lifespan owns `TherapyApplication`, which schedules at most one assessment or post-session operation task;
- independent operation failures are persisted locally and must not cancel API lifespan;
- chat generation is connection-owned and is not scheduled as that owned operation task;
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

## Observability

Diagnostics observe the system and must not become workflow state or API
contract fields. Application command, chat, operation, and recovery paths
record schema-v5 events directly into an opt-in `DiagnosticRecorder`.
Chat correlation uses `client_message_id` (no `turn_id` or `task` context field).

Ordinary logs may include safe LLM metadata when enabled. Opt-in
`JUNG_DEBUG_RUN_DIR` captures two primary evidence sources for local debugging:
ordered `trace.jsonl` for runtime/LLM activity, and a shutdown-time SQLite
snapshot for durable application state. Diagnostics do not maintain derived
workflow, transcript, or failure projections. See
[safety-and-data.md](safety-and-data.md).

Minimum useful ordinary-log records:

- command accepted/completed/failed;
- stage before/after when a transition occurs;
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
