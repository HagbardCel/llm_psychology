---
owner: engineering
status: completed
last_reviewed: 2026-07-16
review_cycle_days: 30
source_of_truth_for: Detailed implementation plan for architecture refactor Phase 5
---

# Architecture Refactor Phase 5 Implementation Plan

## 1. Phase objective

Phase 5 exposes the completed target application core through the final `/api/v1` HTTP and WebSocket boundary and converts the console into the reference API-only client.

The phase implements:

- one FastAPI application around the existing production `application_context()`;
- explicit Pydantic wire contracts and conversion functions;
- the accepted `/api/v1` HTTP routes;
- one `/api/v1/chat` WebSocket endpoint backed by the application-owned `EventStream`;
- stable transport error mapping and request correlation;
- runtime OpenAPI generation without restoring generated protocol machinery;
- one reusable asyncio-native `JungApiClient` for HTTP and WebSocket access;
- a lean console workflow driven by `AppSnapshot.available_commands`;
- deterministic API and console probes against an ephemeral real server;
- contract, reconnect, idempotency, and lifecycle tests.

At the end of Phase 5, the console must communicate exclusively through `/api/v1`. A future frontend must be able to implement the complete product workflow from the public contract without importing `jung.application`, `jung.workflow`, `jung.persistence`, phase processors, or legacy packages.

The accepted decisions in the following documents are binding:

- [Target Architecture](target-architecture.md);
- [Architecture Refactor Roadmap](architecture-refactor-roadmap.md);
- [Workflow Specification](workflow-specification.md);
- [API v1 Contract](api-v1-contract.md);
- [ADR 0002](../adr/0002-asyncio-fastapi-runtime.md);
- [ADR 0003](../adr/0003-workflow-stage-command-operation-model.md);
- [ADR 0004](../adr/0004-single-sqlite-store-and-schema-reset.md);
- [ADR 0005](../adr/0005-phase-processors-and-llm-gateway.md);
- [Phase 2 Implementation Plan](phase-2-implementation-plan.md);
- [Phase 3 Implementation Plan](phase-3-implementation-plan.md);
- [Phase 4 Implementation Plan](phase-4-implementation-plan.md).

This document translates those decisions into implementable Phase 5 work. It must not independently redefine workflow progression, persistence transactions, operation lifecycle, LLM behavior, or durable chat semantics. Any implementation-blocking contradiction must first be resolved in the relevant canonical contract or ADR.

## 2. Desired implementation philosophy

### 2.1 Treat Phase 5 as an adapter phase

The target core already owns:

- command validation;
- optimistic concurrency;
- durable chat acceptance;
- chat and operation idempotency;
- generation and operation supervision;
- workflow transitions;
- application locking;
- persistence transactions;
- recovery;
- LLM calls;
- transport-neutral live events.

The API layer must only:

1. validate and deserialize wire input;
2. construct application commands;
3. call one `TherapyApplication` use case;
4. convert domain/application results to wire DTOs;
5. map application events to WebSocket events;
6. map errors to stable transport envelopes.

Route handlers and WebSocket code must not:

- import `SQLiteStore`;
- call phase processors;
- call `LLMGateway`;
- decide the next workflow stage;
- mutate or infer durable state independently;
- schedule application tasks;
- retry LLM work;
- implement a second idempotency store;
- reproduce application locking;
- reconstruct an assistant message from streamed tokens.

If a route needs persistence knowledge or processor output not available through `TherapyApplication`, add the narrowest application read model necessary. Do not bypass the application boundary.

### 2.2 Keep durable state authoritative

HTTP snapshots and stored session history are authoritative. WebSocket events are live notifications.

Fixed rules:

- token events are ephemeral and best-effort;
- missed tokens are not replayed;
- disconnecting a WebSocket unsubscribes that observer only;
- accepted generation and operations continue after disconnect;
- reconnect begins with `GET /api/v1/state`;
- persisted messages, `ChatTurn`, `Operation`, and `AppSnapshot` win over client-local state;
- the console never treats an in-memory event sequence as a durable workflow ledger.

No event replay buffer, message broker, durable event log, event-sourcing abstraction, or resumable token stream is introduced.

### 2.3 Maintain one explicit public contract

The API contract is deliberately small and hand-maintained. Prefer:

- explicit Pydantic request and response models;
- `Literal`-discriminated WebSocket unions;
- small conversion functions;
- direct FastAPI route declarations;
- stable machine-readable error codes;
- generated OpenAPI from those runtime models.

Do not introduce:

- a generic RPC layer;
- a command bus exposed over HTTP;
- a generic workflow mutation endpoint;
- a generic job endpoint;
- generated Python protocol constants;
- a schema compiler pipeline;
- dynamic route registration;
- client-version negotiation;
- duplicated DTO sets per client;
- domain-model serialization by accident.

The backend Pydantic wire models are the source of truth for `/api/v1`. OpenAPI is generated from them on demand. Phase 5 does not commit a generated protocol package merely to support the bundled Python console.

### 2.4 Build one typed client, not networking inside the console

`JungApiClient` owns:

- base URL handling;
- the shared `httpx.AsyncClient`;
- HTTP request/response validation;
- WebSocket connection and event decoding;
- error-envelope decoding;
- reconnect-oriented state refresh helpers;
- request IDs and chat idempotency IDs;
- clean resource shutdown.

The console owns:

- terminal rendering;
- prompting;
- selection UX;
- local slash commands;
- deterministic or LLM-backed test input providers;
- high-level sequencing based on snapshots and events.

The console must not know route fragments, JSON field names, WebSocket envelopes, HTTP status codes, or serialization details outside the typed client.

### 2.5 Use one asyncio concurrency model

Production Phase 5 code uses:

- `asyncio`;
- FastAPI;
- Uvicorn;
- `httpx.AsyncClient`;
- an asyncio-compatible WebSocket client;
- `asyncio.TaskGroup` or equivalent explicit task ownership.

Do not retain Trio networking in the target console path. Do not add AnyIO abstractions merely to preserve dual Trio/asyncio operation. Legacy Trio remains only until Phase 6 deletion.

Each WebSocket connection owns a small structured-concurrency scope for:

- inbound client messages;
- outbound mapped application events;
- connection-local cancellation and cleanup.

The connection scope does not own application generation tasks.

### 2.6 Prefer final-form corrections over compatibility shims

The target system has no production deployment history. Phase 5 may make the narrow breaking corrections needed to produce a coherent final API.

Do not:

- expose both legacy and v1 route shapes as equivalent supported APIs;
- retain `user_id` as an ignored parameter;
- translate legacy workflow actions into target commands;
- emit both legacy and target WebSocket events;
- preserve profile selection in the target console;
- maintain two console networking implementations after cutover.

Temporary coexistence in the repository is allowed only because Phase 6 performs deletion. It is not a supported runtime mode.

### 2.7 Optimize for local clarity, not distributed-system generality

The product runs locally for one user. Prefer:

- one FastAPI process;
- one application runtime;
- one SQLite file;
- one WebSocket endpoint;
- straightforward process readiness;
- explicit local URLs;
- bounded timeouts;
- concise structured logs.

Do not add authentication, tenancy, distributed tracing infrastructure, rate limiting, reverse-proxy assumptions, service discovery, a broker, or horizontal-scaling coordination.

## 3. Scope

### 3.1 In scope

Phase 5 includes:

- final review and correction of implementation-blocking API seams;
- target API package creation;
- Pydantic request, response, and WebSocket contract models;
- domain-to-wire conversion functions;
- FastAPI application factory and lifespan integration;
- typed access to the `ApplicationRuntime` created by `application_context()`;
- all accepted `/api/v1` HTTP routes;
- `/api/v1/chat` WebSocket handling;
- transport error mapping;
- request ID generation and propagation;
- OpenAPI output and contract validation;
- API runtime configuration and CLI entry point;
- `JungApiClient`;
- asyncio-native target console adaptation;
- deterministic API-backed workflow probes;
- API, client, console, reconnect, and full-stack tests;
- Phase 5 import-boundary and forbidden-concept validation;
- documentation updates necessary to keep the canonical API coherent.

### 3.2 Out of scope

Phase 5 must not implement:

- new workflow stages or commands;
- a new persistence schema;
- database migration compatibility;
- direct API access to assessment internals beyond the accepted style-selection read model;
- a generic operation-history API;
- a generic chat-turn polling API unless a demonstrated client requirement cannot be solved through state and session history;
- event replay;
- durable token storage;
- a message broker;
- multiple active sessions;
- multi-user routes or authentication;
- browser UI implementation;
- cloud deployment;
- reverse-proxy configuration;
- legacy deletion beyond target-console replacement work necessary to avoid duplicate maintained clients;
- repository-wide packaging and Docker cleanup reserved for Phases 6 and 7;
- prompt or therapeutic-behavior redesign;
- provider-specific API behavior;
- SonarQube or unrelated tooling adoption;
- generated client SDK publication.

## 4. Entry conditions and mandatory seam review

### 4.1 Phase 4 entry conditions

Phase 5 begins only when:

- all Phase 2 workflow and persistence tests pass;
- all Phase 3 gateway and processor tests pass;
- all Phase 4 application integration tests pass;
- `application_context()` initializes, recovers, yields, shuts down, and closes the LLM client correctly;
- the target core imports no legacy API or client code;
- `TherapyApplication` owns every mutation needed by `/api/v1`;
- `EventStream` publishes the accepted transport-neutral event union;
- startup recovery runs before API readiness;
- the Phase 4 strict local-model acceptance evidence is recorded where required;
- the API contract and workflow specification agree on stages, commands, revision effects, and retry semantics.

Recommended branch:

```text
refactor/phase-5-api-console
```

Phase 5 must remain reviewable as a transport and reference-client change. Do not mix Phase 6 legacy deletion or Phase 7 repository cleanup into the same implementation commits.

### 4.2 Resolve style recommendation exposure before route implementation

The current target application exposes the static style catalog through `list_styles()`, while the completed assessment persists ranked `StyleRecommendation` values. The accepted workflow enters `STYLE_SELECTION` only after recommendations are durable, and the console must be able to present those recommendations.

The current API contract's `{styles: list[StyleSummary]}` response is insufficient to reproduce this product behavior without allowing the API adapter to read the store directly.

Resolve this in final form before implementing `GET /api/v1/styles`:

1. Add a narrow application read model, for example:

   ```python
   class StyleRecommendationView(BaseModel):
       style_id: str
       score: float
       rationale: str
       key_topics: tuple[str, ...]

   class StyleOptions(BaseModel):
       styles: tuple[StyleSummary, ...]
       recommendations: tuple[StyleRecommendationView, ...]
   ```

2. Add one application read method:

   ```python
   async def get_style_options(self) -> StyleOptions: ...
   ```

3. The method may read the latest completed assessment operation through `SQLiteStore` because it remains inside `TherapyApplication`.
4. It must validate the stored `AssessmentResult` before returning recommendations.
5. It must expose no formulation, risk notes, derived profile, or initial-plan internals.
6. Before assessment completion, `recommendations` is empty.
7. In `STYLE_SELECTION`, recommendations are ordered deterministically by descending score, preserving stored order for ties.
8. Update `api-v1-contract.md` so `GET /styles` returns a named `StyleOptionsResponse` containing both catalog entries and recommendation summaries.

Do not expose the full stored assessment JSON merely because it already exists.

### 4.3 Resolve fresh-setup profile reads

Database initialization seeds a persistent profile singleton (`name=""`, `primary_language="English"`). `PUT /profile` updates that singleton; it does not create the row.

Use the lean final behavior:

- `GET /api/v1/profile` returns the seeded profile and any subsequently persisted partial or complete profile;
- partial profiles persisted in `SETUP` remain readable via `GET /profile`;
- `GET /api/v1/state` remains the canonical fresh-start read;
- the client fills or replaces the seeded profile through `PUT /api/v1/profile` using the current snapshot revision;
- `404 not_found` is only a defensive response if the required profile singleton row is unexpectedly absent;
- update the endpoint matrix in `api-v1-contract.md` to document the defensive `404`.

The application and API must return the persisted seeded profile singleton; they must not synthesize a replacement profile at read time. An unexpectedly missing singleton maps to the documented defensive `404 not_found`.

### 4.4 Confirm domain-to-wire naming differences are adapter mappings

The domain currently uses `AppSnapshot.current_operation`; the API contract uses `operation`. This is not a reason to rename the domain model during Phase 5.

The contract mapper must explicitly convert:

- `current_operation` → `operation`;
- domain `Session` → `SessionSummary` or `SessionDetail`;
- domain `Operation` → `OperationSummary` with `ErrorEnvelope | None`;
- domain `ChatTurn` → `ChatTurnSummary` with `ErrorEnvelope | None`;
- domain `Plan` → `PlanSummary` or `PlanDetail`;
- `frozenset[CommandName]` → deterministically ordered `list[Command]`.

Do not serialize domain models directly with `model_dump()` and expose whichever field names happen to exist internally.

### 4.5 Define duplicate chat reconciliation without event replay

The application intentionally returns an existing `PENDING` or `COMPLETE` `ChatTurn` for a duplicate `(session_id, client_message_id)` and does not republish historical tokens or success acknowledgement events.

The client contract must therefore use reconciliation rather than a replay subsystem:

1. Preserve the original `session_id`, `client_message_id`, and message content.
2. Use a fresh `request_id` and latest snapshot `expected_revision` for each transmission attempt.
3. Establish `WS /api/v1/chat` before authoritative reconciliation, or refresh state/history again after connect.
4. Fetch `GET /api/v1/state` and `GET /api/v1/sessions/{session_id}` when history is needed.
5. Reconcile by shared `client_message_id` on user and assistant messages in session history. Absence from `active_chat_turn` is not evidence that the durable turn row is absent.
6. When retransmission is required, send the same logical message. Duplicate `PENDING` or `COMPLETE` retransmission may produce **no new application event**.
7. Wait for matching `message_in_progress`, `message_completed`, or correlated `error` (current `request_id` before acceptance; retained `client_message_id` after durable acceptance).
8. If no matching event within a bounded acknowledgement interval, fetch state and history again and treat refreshed durable HTTP state as authoritative.
9. Never reconstruct the assistant response from partial tokens.

One reconciliation invocation performs at most one retransmission and one final HTTP refresh, then returns a typed outcome. The caller decides whether to begin another explicit attempt. Chat retransmission is the narrow exception to the no-silent-retry rule for state-changing HTTP commands.

Do not solve silent duplicate acknowledgement by republishing application events; that would duplicate success events for every observer.

This keeps the backend idempotent without adding a WebSocket replay cache or a second command-receipt model.

### 4.6 Fix health semantics before tests depend on them

`GET /api/v1/health` is process readiness, not a synchronous provider health check.

It returns healthy only after:

- the FastAPI lifespan has entered `application_context()`;
- database initialization and startup recovery have completed;
- the application is accepting commands;
- shutdown has not begun.

It must not:

- make an LLM request;
- mutate SQLite;
- inspect legacy services;
- claim model-provider health;
- expose configuration secrets.

Provider failures remain visible through stable LLM error codes during actual work and through server logs.

## 5. Target runtime flow

```text
jung-api process
  └── FastAPI lifespan
       └── application_context(Settings)
            ├── SQLiteStore.initialize()
            ├── LLM gateway + processors
            ├── EventStream
            ├── TaskSupervisor
            ├── TherapyApplication.recover_on_startup()
            └── ApplicationRuntime

HTTP request
  └── route → TherapyApplication method → wire mapper → response

WebSocket connection
  ├── inbound loop → validate send_message → TherapyApplication.submit_message()
  └── outbound loop → EventStream subscription → wire event mapper → send_json()

Console
  └── JungApiClient
       ├── HTTP snapshots and commands
       └── WebSocket chat and live notifications
```

Only the API process constructs the target application runtime. Clients construct only `JungApiClient`.

## 6. Target package and file changes

Use the fewest modules that keep transport, application, and client dependencies clear.

Recommended target additions:

```text
src/jung/
├── api/
│   ├── __init__.py
│   ├── app.py
│   ├── contracts.py
│   ├── errors.py
│   ├── routes.py
│   └── websocket.py
├── client/
│   ├── __init__.py
│   ├── api_client.py
│   └── console.py
└── cli.py                         # only if separate entry points remain clearer

tests/
├── unit/jung/api/
│   ├── test_contracts.py
│   ├── test_errors.py
│   └── test_event_mapping.py
├── unit/jung/client/
│   └── test_api_client_models.py
├── integration/jung/api/
│   ├── conftest.py
│   ├── test_http_routes.py
│   ├── test_websocket_chat.py
│   ├── test_reconnect.py
│   └── test_lifespan.py
├── integration/jung/client/
│   └── test_api_client.py
└── e2e/
    └── test_console_v1_workflow.py

scripts/
└── validate_refactor_phase_5.py
```

Consolidation rules:

- Keep all wire DTOs and conversion helpers in `contracts.py` initially.
- Split `contracts.py` only if independent HTTP and WebSocket sections become difficult to navigate.
- Keep HTTP routes in one `routes.py`; the endpoint set is too small to justify one module per domain.
- Keep one `websocket.py`; do not create connection-manager, registry, dispatcher, and handler class layers.
- Keep HTTP and WebSocket networking in one `JungApiClient` unless a concrete testing or dependency boundary requires a second file.
- Reuse existing console rendering and input-provider concepts where they remain useful, but move or rewrite the maintained target entry path under `jung.client`.
- Do not rename the entire repository package during Phase 5.

## 7. Wire contract implementation

### 7.1 Contract-model rules

Every request, response, and WebSocket payload is a named Pydantic model.

Use:

- `ConfigDict(extra="forbid")` for incoming requests and WebSocket commands;
- frozen response models where practical;
- `Literal[...]` for event `type` values;
- `Field(discriminator="type")` for the event union;
- UUID, aware datetime, date, enum, and bounded numeric types directly;
- explicit nullable fields rather than omitted ad hoc shapes;
- deterministic command ordering;
- Pydantic-native ISO 8601 serialization.

Do not use `dict[str, Any]` for top-level contract envelopes. Opaque validated JSON remains allowed only where the accepted contract explicitly permits it, such as session briefing material.

### 7.2 Request models

Implement request DTOs corresponding to the canonical API contract:

- `ProfileUpdateRequest`;
- `SelectStyleRequest`;
- `StartSessionRequest`;
- `EndSessionRequest`;
- `RetryOperationRequest`;
- `SendMessageCommand`.

The adapter derives identifiers already present in the route or authoritative snapshot:

- `session_id` for session end comes from the path;
- current `operation_id` for retry comes from the current snapshot/application state;
- internal session, operation, turn, and message IDs remain application-generated.

No request model contains `user_id`, legacy status, next action, job ID, provider name, or persistence fields.

### 7.3 Response models

Implement the named response/read models from `api-v1-contract.md`, including the style-options correction:

- profile;
- style catalog and recommendation summaries;
- session summary/detail/history;
- message;
- plan summary/detail;
- operation summary;
- chat-turn summary;
- application snapshot;
- start-session response;
- list wrappers;
- health response;
- error response/envelope.

Use separate wire types even where fields currently resemble domain models. This prevents future internal changes from becoming accidental API changes.

### 7.4 Conversion functions

Use small pure functions, for example:

```python
def to_snapshot_response(snapshot: AppSnapshot) -> AppSnapshotResponse: ...
def to_session_summary(session: Session) -> SessionSummaryResponse: ...
def to_session_detail(session: Session) -> SessionDetailResponse: ...
def to_message_response(message: Message) -> MessageResponse: ...
def to_plan_summary(plan: Plan) -> PlanSummaryResponse: ...
def to_plan_detail(plan: Plan) -> PlanDetailResponse: ...
def to_operation_summary(operation: Operation) -> OperationSummaryResponse: ...
def to_chat_turn_summary(turn: ChatTurn) -> ChatTurnSummaryResponse: ...
```

Conversion functions must:

- include only public fields;
- create `ErrorEnvelope` from stored error code/message/retryability;
- never include provider diagnostics;
- preserve UUIDs and datetimes as typed values until serialization;
- sort `available_commands` by a fixed canonical command order;
- not access the database;
- not perform workflow decisions.

### 7.5 Canonical command ordering

Because the domain snapshot stores a `frozenset`, define one wire-order constant:

```python
COMMAND_ORDER = (
    CommandName.UPDATE_PROFILE,
    CommandName.SEND_MESSAGE,
    CommandName.SELECT_STYLE,
    CommandName.START_SESSION,
    CommandName.END_SESSION,
    CommandName.RETRY_OPERATION,
)
```

Filter this order by membership when constructing the response. Do not sort lexicographically in each caller or rely on set iteration.

### 7.6 Error-envelope construction

Stored operation and chat errors become nested `ErrorEnvelope` values with:

- stable `code`;
- safe human-readable `message`;
- request ID generated for the response/event;
- `retryable`;
- no current snapshot unless the envelope represents `state_conflict`.

For a durable stored error not caused by the current request, generate a new correlation request ID for transport while preserving the durable error code/message.

## 8. FastAPI application and lifespan

### 8.1 Application factory

Implement a pure construction entry point:

```python
def create_app(
    settings: Settings,
    *,
    runtime_factory: RuntimeFactory = application_context,
) -> FastAPI: ...
```

The factory:

- creates no database connection immediately;
- creates no LLM client immediately;
- stores no mutable application singleton at module import time;
- configures metadata, routes, exception handlers, and lifespan;
- supports deterministic tests through an injected runtime factory;
- returns one FastAPI instance.

A module-level `app` may exist only in a small entry module if Uvicorn import-string startup materially simplifies execution. It must be constructed from explicit environment settings and must not hide additional dependency construction.

### 8.2 Lifespan

The FastAPI lifespan must:

1. enter `application_context(settings)`;
2. wait for initialization and `recover_on_startup()` to complete;
3. expose the yielded `ApplicationRuntime` to route dependencies;
4. mark readiness only after the runtime is available;
5. reject new work as shutdown begins through the existing application lifecycle;
6. exit the application context exactly once;
7. let `TaskSupervisor` perform bounded shutdown;
8. close the LLM client after supervised work stops.

Do not duplicate Phase 4 shutdown code in FastAPI callbacks.

### 8.3 Runtime dependency

Use one narrow typed dependency helper:

```python
def get_runtime(request: Request) -> ApplicationRuntime: ...
```

A corresponding WebSocket helper may read the same app state.

This helper is not a general service locator. It exposes exactly one typed composition object created by the lifespan. Do not add string-keyed access or per-service dependency functions for store, processors, and LLM.

### 8.4 Configuration

Phase 5 needs explicit runtime settings for:

- database path/data directory;
- LLM settings already required by composition;
- API host;
- API port;
- log level;
- shutdown timeout;
- HTTP/client timeouts;
- optional allowed browser origins;
- optional event queue size and tracing flags already supported by composition.

Prefer one small settings-loading function or Pydantic settings model. Do not maintain duplicate environment parsing in server, console, tests, and Docker.

Secrets must never appear in OpenAPI, health responses, or logs.

### 8.5 CORS and origins

Authentication is out of scope, but browser origin policy should be explicit:

- install CORS middleware only when allowed origins are configured;
- default local native clients require no CORS;
- do not use `allow_origins=["*"]` together with credentials;
- WebSocket origin checks may be deferred until a browser client exists, or use the same explicit configured origin set if implemented now;
- lack of authentication must be documented as a local-only assumption, not hidden as production security.

## 9. HTTP route implementation

Implement exactly the accepted endpoint matrix. Keep each handler short and visibly mechanical.

### 9.1 `GET /api/v1/state`

- call `application.get_snapshot()`;
- convert to `AppSnapshotResponse`;
- no caching layer;
- no mutation;
- no provider call.

### 9.2 `GET /api/v1/profile`

- call `application.get_profile()`;
- map `ProfileView` to `ProfileResponse`;
- map missing profile to `404 not_found` as resolved in §4.3;
- expose only the user-editable profile and current immutable plan;
- do not expose derived profile or assessment internals.

### 9.3 `PUT /api/v1/profile`

- validate `ProfileUpdateRequest`;
- construct `UpdateProfile`;
- call `application.update_profile()`;
- return the new snapshot;
- preserve `409 invalid_command`, `409 state_conflict`, and `422 validation_error` semantics.

### 9.4 `GET /api/v1/styles`

- call `application.get_style_options()` after the seam correction;
- return static styles plus assessment recommendation summaries;
- expose no initial plan material;
- preserve stable catalog IDs;
- return recommendations empty before assessment completion.

### 9.5 `PUT /api/v1/style`

- construct `SelectStyle` from revision and style ID;
- call `application.select_style()`;
- return the new snapshot;
- do not call an LLM;
- do not accept legacy names such as `selected_therapy_style`.

### 9.6 `GET /api/v1/sessions`

- call `application.list_sessions()`;
- convert each to `SessionSummary`;
- preserve descending `started_at` order from the application/store contract;
- do not paginate in v1;
- do not include messages in the list response.

### 9.7 `GET /api/v1/sessions/{session_id}`

- call `application.get_session_history(session_id)`;
- map session, messages, and linked plans;
- preserve message sequence order;
- return `404 not_found` for an unknown session;
- do not infer session kind from `plan_id`.

### 9.8 `POST /api/v1/sessions`

- construct `StartSession` from `expected_revision`;
- call `application.start_session()`;
- obtain the authoritative snapshot after creation if the application result does not already include it;
- return `{session, snapshot}` with status `201`;
- perform no assistant-only opening generation.

Prefer a narrow application result such as `StartedSession(session, snapshot)` only if avoiding a second consistent application read materially improves correctness. Do not access the store from the route.

### 9.9 `POST /api/v1/sessions/{session_id}/end`

- construct `EndSession` from path ID and revision;
- call `application.end_session()`;
- return the accepted post-session snapshot with status `202`;
- do not wait for post-session LLM completion;
- do not schedule or inspect the operation in the route.

### 9.10 `POST /api/v1/operations/current/retry`

- read the authoritative current snapshot through the application;
- require a visible current failed operation;
- construct `RetryOperation` with that operation ID and expected revision;
- call `application.retry_operation()`;
- return status `202`;
- do not accept an arbitrary operation ID from the client in v1.

A race between the read and retry is resolved by the application revision and operation validation, not route-level locking.

### 9.11 `GET /api/v1/health`

- return `200 {"status": "healthy"}` only when lifespan initialization completed and shutdown has not begun;
- otherwise return `503` with a minimal safe error body;
- do not invoke application commands, the store, or the model provider during each health request.

## 10. Error mapping and request correlation

### 10.1 One exception mapping table

Centralize transport mapping in `api/errors.py`.

Map:

| Internal failure | Public code | HTTP status | Notes |
|---|---|---:|---|
| `InvalidCommand` | `invalid_command` | 409 | safe message |
| `RevisionConflict` | `state_conflict` | 409 | include current snapshot |
| `Busy` | `busy` | 409 | safe message |
| `NotFound` | `not_found` | 404 | safe message |
| request validation | `validation_error` | 422 | normalized field details only if contract allows |
| `StoredWorkFailure` | stored code | 409 on unexpected HTTP; WebSocket preserves stored safe fields | preserve retryable; do not derive HTTP status from historical stored codes |
| `InvariantViolation` | `internal_error` | 500 | log details server-side |
| `PersistenceFailure` | `internal_error` | 500 | log details server-side |
| unexpected exception (including raw provider escape) | `internal_error` | 500 | generic client message |
| process not ready | `not_ready` | 503 | retryable |

`jung.api.errors` imports only domain/application error types. Provider failures reach the adapter as `StoredWorkFailure` or stored operation/chat error fields after application-layer classification and public-message sanitization. A raw provider error escaping to the API is an unexpected boundary violation mapped to `internal_error`.

### 10.2 Revision conflict snapshot

A `RevisionConflict` does not currently carry an `AppSnapshot`. The exception handler must obtain the current snapshot through `TherapyApplication.get_snapshot()` and include it in the envelope.

Rules:

- do not access SQLite directly;
- if snapshot retrieval unexpectedly fails, return the conflict without `current_snapshot` and log the secondary failure;
- do not convert a conflict to `500` merely because enrichment of the error envelope failed.

### 10.3 Request IDs

For each HTTP request:

- accept one documented correlation header, recommended `X-Request-ID`;
- validate it as UUID when supplied;
- otherwise generate a UUID;
- return it in the response header;
- include it in every error envelope;
- bind it to structured logs.

For WebSocket commands:

- require `request_id` in `send_message` as accepted by the contract;
- echo it on `token` and command-specific error events where defined;
- log connection ID, request ID, session ID, and turn ID as available;
- never log full therapy message content by default.

Do not add a global distributed-tracing framework.

### 10.4 Validation errors

Replace FastAPI's default validation body with the stable `ErrorResponse` envelope.

The public message should be concise. Field-level details may be included only in a stable optional field added to the canonical contract; otherwise keep detailed Pydantic errors in debug logs.

## 11. WebSocket implementation

### 11.1 Connection lifecycle

`WS /api/v1/chat` uses one connection-local structured-concurrency scope:

1. resolve the initialized `ApplicationRuntime`;
2. accept the WebSocket;
3. enter `runtime.events.subscribe()` before reading commands;
4. start an inbound command loop;
5. start an outbound application-event loop;
6. cancel the sibling loop when the socket closes;
7. exit the event subscription;
8. do not cancel application work.

Use `asyncio.TaskGroup` where its cancellation behavior is clear. Ordinary disconnect exceptions should close the connection scope quietly. Unexpected exceptions should be logged once and produce an error event only when the connection remains usable.

### 11.2 Inbound command loop

The inbound loop accepts only the discriminated `send_message` command.

For each message:

- receive text or JSON;
- reject binary payloads;
- parse JSON;
- validate `SendMessageCommand` with Pydantic;
- construct the domain `SendMessage` command;
- call `application.submit_message()`;
- do not stream tokens itself;
- do not wait for generation completion;
- map pre-acceptance errors to a WebSocket `error` event;
- keep the connection open for recoverable command errors;
- do **not** manufacture duplicate-success acknowledgement events when `submit_message()` returns an existing `PENDING` or `COMPLETE` turn; the client must HTTP-refresh instead.

Malformed JSON, unknown event types, missing fields, and invalid UUIDs produce `validation_error` events with the command request ID when recoverable.

Do not create a generic dispatcher registry for one command type.

### 11.3 Outbound event mapping

Map application events as follows:

| Application event | WebSocket event |
|---|---|
| `ChatTurnAccepted` | `message_in_progress` |
| `ChatTokenGenerated` | `token` |
| `ChatTurnCompleted` | `message_completed` |
| `ChatTurnFailed` | `error` with `session_id`, `turn_id`, `client_message_id`, and transport `request_id`, then durable `snapshot_changed` from the separately published snapshot event |
| `SnapshotChanged` | `snapshot_changed` |
| `OperationChanged` | `operation_changed` |

The mapper is pure except for request-ID generation needed by a stored failure envelope.

Event rules:

- preserve token `sequence` exactly;
- never combine or re-tokenize text;
- do not emit legacy typing events;
- do not emit legacy workflow-next-action events;
- do not emit job hierarchies;
- do not emit a second snapshot by independently reading state after every event;
- do not expose raw domain model dumps.

### 11.4 Event ordering

Preserve application publication order for each subscriber.

Expected chat sequence:

```text
message_in_progress
snapshot_changed        # acceptance revision
token *
message_completed
snapshot_changed        # completion revision
```

Expected durable chat failure sequence:

```text
message_in_progress
snapshot_changed        # acceptance revision
token *                  # possibly zero
error
snapshot_changed        # failed-turn revision
```

Expected operation status notifications are emitted exactly as the application publishes `OperationChanged` events. The API layer must not manufacture progress percentages or child jobs.

### 11.5 Slow clients

`EventStream` already evicts a subscriber whose bounded queue fills. The WebSocket adapter must treat subscription completion as a reason to close that socket cleanly.

Do not add another unbounded outbound queue. If a connection-local send queue is required to serialize direct command errors with application events, it must be bounded and have a documented overflow policy that closes only the slow connection.

Slow clients must never block model generation or operation completion.

### 11.6 Disconnect and reconnect

On disconnect:

- stop receiving and sending for that socket;
- leave accepted work untouched;
- release only connection-local resources;
- log a concise disconnect reason;
- do not mark the active `ChatTurn` failed.

On reconnect, the client follows the canonical sequence in [`api-v1-contract.md`](api-v1-contract.md):

1. establish `WS /api/v1/chat` (or refresh state/history again immediately after connect);
2. `GET /api/v1/state`;
3. `GET /api/v1/sessions/{session_id}` when history is needed (for uncertain delivery, fetch the original command's `session_id`, even if that session is no longer active; a separate active-session read may be used for current UI rendering);
4. reconcile using shared `client_message_id` and bounded single-invocation rules;
5. treat persisted HTTP state and stored messages as authoritative;
6. never reconstruct a completed message from missed `token` events.

### 11.7 Multiple observers

Multiple local clients may connect as observers. Every subscriber receives live application events.

The application still enforces one conflicting generation and one active session. Do not add a connection owner, leader election, or per-client workflow state.

## 12. OpenAPI

### 12.1 Runtime output

FastAPI must expose:

- `/openapi.json`;
- interactive documentation in development unless deliberately disabled by configuration.

OpenAPI must include:

- all HTTP paths under `/api/v1`;
- named schemas;
- stable error responses;
- response status codes;
- request ID header documentation;
- descriptions noting that WebSocket payloads are documented in the canonical API contract because OpenAPI does not fully describe WebSocket message unions.

### 12.2 Validation

Add a deterministic test that:

- builds the app with a fake runtime factory;
- generates OpenAPI;
- verifies the expected path set exactly;
- rejects any legacy route;
- verifies that no schema contains `user_id`;
- verifies no internal persistence or provider fields leak;
- verifies named response models are referenced rather than anonymous arbitrary objects.

Do not commit generated Python constants. An optional `scripts/export_openapi.py` may write JSON for a future web client on demand, but the generated file is not a second source of truth.

## 13. `JungApiClient`

### 13.1 Public interface

Provide a small typed client interface, for example:

```python
class JungApiClient:
    async def __aenter__(self) -> JungApiClient: ...
    async def __aexit__(...) -> None: ...

    async def get_state(self) -> AppSnapshotResponse: ...
    async def get_profile(self) -> ProfileResponse: ...
    async def update_profile(self, request: ProfileUpdateRequest) -> AppSnapshotResponse: ...
    async def get_style_options(self) -> StyleOptionsResponse: ...
    async def select_style(self, request: SelectStyleRequest) -> AppSnapshotResponse: ...
    async def list_sessions(self) -> tuple[SessionSummaryResponse, ...]: ...
    async def get_session(self, session_id: UUID) -> SessionHistoryResponse: ...
    async def start_session(self, request: StartSessionRequest) -> StartSessionResponse: ...
    async def end_session(self, session_id: UUID, request: EndSessionRequest) -> AppSnapshotResponse: ...
    async def retry_current_operation(self, request: RetryOperationRequest) -> AppSnapshotResponse: ...
    async def health(self) -> HealthResponse: ...

    async def chat_events(self) -> AsyncIterator[ServerEvent]: ...
    async def send_message(self, command: SendMessageCommand) -> None: ...
```

The exact WebSocket API may use a scoped chat connection object if that makes lifecycle ownership clearer:

```python
async with client.open_chat() as chat:
    await chat.send(command)
    async for event in chat.events(): ...
```

Prefer the scoped object if it prevents hidden background tasks and ambiguous reconnect behavior.

### 13.2 HTTP behavior

The client:

- owns one `httpx.AsyncClient`;
- uses a configured base URL and timeout;
- validates every success body with the corresponding response model;
- parses every non-success body as `ErrorResponse`;
- raises one typed `JungApiError` containing status, code, message, request ID, retryability, and optional current snapshot;
- does not return untyped dictionaries;
- never silently retries state-changing HTTP commands;
- may retry idempotent reads for transient connection establishment only if explicitly configured and tested.

### 13.3 WebSocket behavior

The client:

- converts the HTTP base URL to `ws://` or `wss://` centrally;
- connects to `/api/v1/chat` without `user_id`;
- serializes `SendMessageCommand` through Pydantic;
- validates every server event through the discriminated union;
- raises a typed protocol error for unknown or invalid payloads;
- exposes closure distinctly from server `error` events;
- does not hide reconnect in an infinite loop;
- gives the console explicit control over reconnect and state refresh.

### 13.4 Reconciliation helper

Provide one narrow helper for uncertain chat delivery, for example:

```python
class ChatReconciliationStatus(StrEnum):
    COMPLETE = "complete"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"
    UNRESOLVED = "unresolved"

async def reconcile_chat_turn(
    session_id: UUID,
    client_message_id: UUID,
) -> ChatReconciliationResult: ...
```

One invocation performs at most: one initial HTTP refresh, zero or one retransmission, one bounded event wait, one final HTTP refresh, then returns a typed result carrying relevant durable state (completed message, pending turn, or public error envelope). It never loops or retransmits indefinitely.

It may combine:

- `GET /state`;
- `GET /sessions/{session_id}`;
- lookup of durable user and assistant messages by shared `client_message_id`;
- snapshot `active_chat_turn` when pending;
- correlated `error` events (`request_id` before acceptance; `client_message_id` after durable acceptance).

Chat retransmission is the narrow exception to the rule that state-changing HTTP commands are not silently retried.

Do not add a new backend endpoint solely to avoid two local reads unless profiling or correctness demonstrates a real need.

### 13.5 Dependency direction

`jung.client` may import `jung.api.contracts` because those are the shared Python wire definitions for the bundled client.

It must not import:

- `jung.application`;
- `jung.workflow`;
- `jung.persistence`;
- `jung.phases`;
- `jung.llm`;
- legacy `psychoanalyst_app` modules.

A future non-Python frontend consumes OpenAPI and the documented WebSocket union rather than importing Python types.

## 14. Console adaptation

### 14.1 Product model

The target console is a single-user reference client. Remove target-path concepts for:

- profile listing;
- login;
- registration;
- user IDs;
- session rebinding by user;
- legacy status strings;
- workflow-next-action signatures;
- one-shot legacy workflow action guards;
- job-status dictionaries;
- assessment recommendation events;
- generated WebSocket constants;
- direct legacy route calls.

The console starts by reading `AppSnapshot` and renders the command(s) permitted by `available_commands`.

### 14.2 State-driven main loop

Recommended high-level loop:

```text
fetch state
while running:
    render durable state
    choose behavior from available_commands and stage
    perform one explicit command or open chat
    refresh state after command/disconnect
```

Stage behavior:

- `SETUP`: prompt for profile and call `update_profile`;
- `INTAKE`: open chat and accept user messages until snapshot changes to `ASSESSMENT`;
- `ASSESSMENT`: display waiting state; observe `operation_changed` or poll state only after reconnect;
- `STYLE_SELECTION`: fetch style options, display ranked recommendations, call `select_style`;
- `READY`: offer to start therapy or exit;
- `THERAPY`: open chat, support `/quit` to end the active session, and display stored history on reconnect;
- `POST_SESSION`: display waiting or failure/retry option based on operation state;
- failed retryable operation: offer `retry_current_operation` only when present in `available_commands`.

Do not recreate a second workflow state machine. The stage switch is presentation logic; command availability remains server-derived.

### 14.3 Chat rendering

For each turn:

- generate one `client_message_id` before send;
- retain it through uncertain delivery reconciliation;
- render user input once locally or from durable history, not both;
- begin therapist output on the first token;
- append tokens by increasing sequence;
- finalize from `message_completed.message.content`;
- discard any partial buffer on durable failure;
- on reconnect, reload durable history and do not replay the partial buffer.

The console may detect skipped or duplicate token sequence values for diagnostics, but must not fail durable workflow because token delivery is best-effort.

### 14.4 Operation waiting

The console should prefer live `operation_changed` and `snapshot_changed` events while connected. It must also remain correct without them:

- after reconnect, call `get_state()`;
- when no chat connection is needed, bounded low-frequency polling is acceptable for the reference console;
- do not query a legacy job endpoint;
- do not infer completion from elapsed time;
- do not invent progress percentages.

### 14.5 Existing reusable console components

Review existing `console-ui` components individually:

Retain or port when still useful:

- terminal output abstraction;
- human input provider;
- deterministic scripted input provider;
- local-LLM simulated input provider;
- event sink used by workflow probes;
- transcript logging with sensitive-output controls.

Replace rather than adapt when tied to legacy protocol:

- `ConsoleClient` networking and workflow-action state;
- Trio WebSocket receiver;
- profile selection/login flows;
- legacy event constants;
- legacy job tracking;
- route-fragment construction;
- workflow action deduplication guards.

Do not wrap the old `ConsoleClient` behind `JungApiClient`. Build a smaller target console around the new client.

### 14.6 Console entry point

Add a final target command such as:

```bash
uv run jung-console --api-url http://127.0.0.1:8000
```

Arguments should remain small:

- API URL;
- optional input-provider mode for probes;
- optional output/trace directory;
- optional timeout overrides;
- optional non-interactive fixture.

No user ID argument exists.

## 15. Deterministic workflow probes

### 15.1 Probe architecture

Port the deterministic console probe to the target API stack:

```text
probe harness
  ├── temporary data directory / SQLite database
  ├── FakeLLM target application
  ├── real FastAPI/Uvicorn server on an ephemeral port
  ├── real JungApiClient
  └── target console with scripted input provider
```

The probe must not:

- import application internals from the console process;
- mutate SQLite directly during the workflow;
- call legacy routes;
- inspect legacy workflow state;
- rely on Docker networking for deterministic correctness;
- require a local model.

Direct database inspection is allowed only after shutdown for test assertions or diagnostic artifact creation.

### 15.2 Required deterministic scenarios

Maintain two full deterministic console/API workflow probes:

1. **Fresh setup through ready**
   - fresh database;
   - profile update;
   - complete intake fixture/dialogue;
   - assessment operation completes;
   - style recommendations displayed;
   - style selected;
   - final stage `READY`.

2. **Therapy session through post-session update**
   - start from a prepared ready fixture or continue scenario 1;
   - start therapy;
   - complete at least one chat turn;
   - end session;
   - post-session operation completes;
   - new plan/profile material is durable;
   - final stage `READY`.

Cover the remaining high-value resilience scenarios as focused integration tests (not full workflow probes):

3. **Restart and resume**
   - accept durable work;
   - stop the API at a controlled boundary;
   - restart against the same temporary database;
   - verify operation/chat recovery semantics;
   - reconnect the API client and reconcile through state/history.

4. **Structured generation failure and retry**
   - fail assessment or post-session with a retryable fake error;
   - expose durable failure;
   - retry the same operation row;
   - complete without duplicate plan/session rows.

5. **Chat disconnect during generation**
   - disconnect after at least one token;
   - allow generation to complete;
   - reconnect;
   - fetch stored assistant message;
   - verify no duplicate user message.

### 15.3 Probe artifacts

Retain useful lean artifacts:

- run manifest;
- normalized timeline;
- console transcript;
- server log;
- API request/event trace without secrets or full prompts by default;
- final summary;
- failure summary;
- optional post-run database snapshot.

Replace legacy-specific fields with:

- snapshot revision;
- stage;
- available commands;
- operation kind/status/attempt;
- chat turn ID/status;
- client message ID;
- request ID;
- WebSocket event type and sequence.

Do not preserve legacy action signatures or hierarchical job trees merely for artifact continuity.

### 15.4 Optional local-model smoke

Keep one optional manual local-model smoke after deterministic probes pass:

```text
make smoke-refactor-phase-5-local-llm
```

It should:

- use a temporary data directory;
- start the real API;
- use the real `JungApiClient`;
- complete a bounded intake or prepared-ready therapy scenario;
- verify strict structured-output compatibility already established in Phase 3;
- record model/server/base URL and timing evidence;
- avoid normal development data;
- remain outside hosted CI.

Do not replace deterministic `FakeLLM` coverage with the local-model smoke.

## 16. Testing strategy

### 16.1 Unit contract tests

Test pure wire conversion and validation:

- every domain-to-wire mapper;
- `current_operation` → `operation` mapping;
- deterministic command order;
- session summary/detail field separation;
- plan summary/detail field separation;
- stored error-envelope construction;
- recommendation view redaction of initial plan and assessment internals;
- UUID and aware-datetime serialization;
- request `extra="forbid"` behavior;
- discriminated WebSocket union validation;
- token sequence preservation;
- no `user_id` in any schema.

### 16.2 Error-mapping tests

For every supported exception:

- assert public code;
- assert HTTP status;
- assert retryability;
- assert safe message;
- assert request ID;
- assert conflict snapshot behavior;
- assert internal details are not leaked.

Test FastAPI request validation through the same envelope.

### 16.3 HTTP integration tests

Use:

- a temporary SQLite database;
- real `SQLiteStore`;
- real `TherapyApplication`;
- real `EventStream` and `TaskSupervisor`;
- `FakeLLM`;
- real FastAPI lifespan;
- `httpx.AsyncClient` with ASGI transport where network behavior is irrelevant.

Cover:

- fresh state;
- missing profile read;
- profile update and conflict;
- style options before and after assessment;
- invalid style;
- session list/detail;
- session start/end statuses;
- current-operation retry;
- unknown session;
- health before/after lifespan if test harness permits;
- absence of legacy routes.

### 16.4 WebSocket integration tests

Use a real ephemeral Uvicorn server and an asyncio WebSocket client. This validates actual handshake, lifespan, JSON framing, and disconnect behavior.

Cover:

- connection without `user_id`;
- malformed command;
- invalid command in current stage;
- acceptance event ordering;
- monotonic token sequence;
- completion event and stored message;
- durable failure event and snapshot;
- second distinct chat receives `busy`;
- duplicate client message does not duplicate the user message;
- disconnect does not cancel generation;
- reconnect sees durable state but no token replay;
- multiple observers receive completion;
- slow observer eviction does not block work;
- shutdown closes sockets and leaves accepted work recoverable.

### 16.5 Client integration tests

Run `JungApiClient` against the ephemeral real server.

Test:

- typed success decoding;
- typed error decoding;
- request ID propagation;
- URL normalization;
- HTTP resource cleanup;
- WebSocket event validation;
- explicit connection closure;
- reconnect state refresh;
- uncertain-send reconciliation with bounded single invocation and post-resend HTTP refresh;
- no silent retry of state-changing HTTP commands except the documented chat retransmission identity exception;
- durable `error` events include chat identifiers for post-acceptance failures.

### 16.6 Console tests

Test console behavior with a fake or real `JungApiClient` boundary depending on scope:

- setup prompt and profile submission;
- intake chat rendering;
- style recommendation display and selection;
- ready/start-session flow;
- `/quit` end-session behavior;
- post-session wait and retry;
- disconnect recovery;
- no profile selection or login prompt;
- no legacy event handling;
- deterministic event sink output.

The final end-to-end console test must use the real API client and ephemeral server.

### 16.7 OpenAPI and import-boundary tests

Add tests or validation rules that fail when:

- target API imports legacy packages;
- target client imports application, persistence, phases, or LLM modules;
- core imports FastAPI, Uvicorn, HTTPX, or WebSocket client modules;
- a route outside the exact `/api/v1` path set appears in the target app;
- `user_id` appears in target API/client source or schemas;
- generic `workflow`, `job`, or `agent` mutation endpoints appear;
- target WebSocket emits legacy event names;
- API route code calls store or processor methods.

## 17. Observability and operational behavior

### 17.1 Structured logging

Log concise boundary events:

- API startup and readiness;
- API shutdown;
- HTTP method/path/status/duration/request ID;
- WebSocket connect/disconnect with connection ID;
- accepted chat request ID/session ID/turn ID;
- mapped application error code;
- operation status transitions already visible from application logs;
- protocol validation failures.

Do not log by default:

- full therapy messages;
- full prompts;
- profile notes;
- derived profile;
- assessment formulation;
- plan content;
- API keys;
- provider response bodies.

### 17.2 Boundary timing

Lightweight timing at the HTTP/WebSocket boundary is sufficient. Do not add metrics infrastructure during Phase 5.

Useful durations:

- request handling;
- WebSocket connection lifetime;
- command acceptance latency;
- time from acceptance to completion, preferably already derived from application timestamps.

### 17.3 Graceful shutdown

Uvicorn shutdown must:

- stop accepting new connections;
- begin FastAPI lifespan exit;
- invoke existing application shutdown behavior through context exit;
- allow bounded supervised work completion;
- close remaining sockets;
- preserve recoverable durable states.

Do not let Uvicorn and `TaskSupervisor` apply contradictory independent task timeouts without a documented ordering.

## 18. Dependencies and entry points

### 18.1 Runtime dependencies

Add only direct dependencies needed by the target path:

- FastAPI;
- Uvicorn;
- HTTPX, already used by the repository;
- one asyncio WebSocket client library if not supplied by the selected Uvicorn installation;
- existing Pydantic dependencies.

Do not add:

- an ORM;
- Celery/RQ;
- a DI framework;
- a REST client generator;
- Socket.IO;
- GraphQL;
- a retry framework for ordinary commands;
- an API gateway library.

Version cleanup and removal of Quart/Trio/LangChain legacy dependencies occur after cutover in Phases 6 and 7. Phase 5 may add target dependencies without pretending the legacy requirements have already disappeared.

### 18.2 Target commands

Add canonical target entry points, for example:

```toml
[project.scripts]
jung-api = "jung.api.app:cli"
jung-console = "jung.client.console:cli"
```

The API CLI:

- loads settings once;
- configures logging once;
- starts Uvicorn;
- contains no application logic.

The console CLI:

- loads client settings;
- enters `JungApiClient`;
- runs the target console;
- contains no transport implementation.

Do not rename or remove legacy entry points until Phase 6 cutover commits are ready.

## 19. Implementation sequence

Implement in reviewable work packages. Each package should leave tests green and avoid mixing unrelated legacy cleanup.

### Work package 1 — Contract seam corrections

- add `StyleRecommendationView` and `StyleOptions` application result models;
- add `TherapyApplication.get_style_options()`;
- document style response correction in `api-v1-contract.md`;
- document seeded/partial `GET /profile` reads and defensive `404` only when the singleton row is absent;
- add focused application tests;
- confirm no API imports enter the core.

Acceptance:

- recommendations are accessible without store bypass;
- no initial plan or sensitive assessment fields leak;
- canonical docs are internally consistent.

### Work package 2 — Wire contracts and mappers

- create `jung.api.contracts`;
- implement HTTP and WebSocket DTOs;
- implement all pure mappers;
- implement deterministic command ordering;
- add unit tests and schema leak checks.

Acceptance:

- contract models cover every endpoint/event;
- no route code is needed to test conversion;
- OpenAPI-compatible models contain no `user_id`.

### Work package 3 — Errors and request IDs

- create `jung.api.errors`;
- implement typed exception-to-envelope mapping;
- implement request ID parsing helper (middleware deferred to work package 4);
- normalize request validation errors;
- test conflict snapshot enrichment and redaction.

Acceptance:

- all documented error codes have deterministic mappings;
- unexpected errors leak no internals;
- Request-ID parsing and envelope primitives preserve the supplied correlation ID. Header and logging propagation are verified in work package 4.

### Work package 4 — FastAPI lifespan and HTTP routes

- create `jung.api.app` and `routes`;
- wrap `application_context()` in lifespan;
- implement readiness;
- implement all HTTP routes;
- add ASGI HTTP integration tests;
- validate exact path set and OpenAPI.

Acceptance:

- every route calls only application methods;
- no target route includes `user_id`;
- startup recovery completes before health becomes ready.

### Work package 5 — WebSocket adapter

- create `jung.api.websocket`;
- implement inbound command validation;
- implement outbound event mapping;
- implement connection-local structured concurrency;
- add real-server WebSocket tests;
- test disconnect, multiple observers, and slow clients.

Acceptance:

- accepted generation survives disconnect;
- event order matches durable semantics;
- no legacy WebSocket event is emitted.

### Work package 6 — Typed API client

- create `jung.client.api_client`;
- implement HTTP methods;
- implement scoped chat connection;
- implement typed errors;
- implement reconciliation helper;
- add real-server client integration tests.

Acceptance:

- no untyped JSON reaches console code;
- client imports only API contracts and ordinary client dependencies;
- state-changing calls are not silently retried.

### Work package 7 — Target console

- create or rewrite the maintained console around `JungApiClient`;
- remove target-path profile selection/login;
- drive behavior from snapshot and commands;
- port reusable input providers/output/event sink;
- add target CLI;
- add console tests.

Acceptance:

- console contains no route strings or WebSocket payload parsing;
- console performs no direct database/application calls;
- full manual workflow is possible through `/api/v1`.

### Work package 8 — Deterministic probes

- port the main workflow probe to the target console/API;
- add restart, failure/retry, and disconnect scenarios;
- update artifacts to target fields;
- add a native make target;
- keep optional local-model smoke separate.

Acceptance:

- deterministic setup-to-ready and therapy-to-ready probes pass;
- probes use a real API server and client;
- no legacy workflow/job assertions remain.

### Work package 9 — Validation and handoff

- add `validate_refactor_phase_5.py`;
- run all prior phase tests;
- run API/client/console tests;
- run deterministic probe;
- record OpenAPI path/schema checks;
- prepare Phase 6 deletion inventory updates.

Acceptance:

- Phase 5 exit criteria are satisfied;
- legacy API and console are no longer needed for behavioral confidence;
- Phase 6 can delete rather than migrate.

## 20. Phase 5 validation script

Add `scripts/validate_refactor_phase_5.py` with deterministic static and lightweight runtime checks.

It should verify:

- required target files exist;
- `create_app` and target CLI entry points exist;
- exact `/api/v1` endpoint paths exist in OpenAPI;
- no `user_id` appears in target API/client source or schemas;
- API modules do not import store, phases, LLM, or legacy packages except the allowed typed `ApplicationRuntime`/application boundary;
- client modules do not import application/core internals;
- core modules do not import FastAPI/Uvicorn/HTTPX/WebSocket clients;
- no legacy WebSocket event names appear in target API/client code;
- no generic workflow/job mutation route appears;
- no `trio`, `quart`, or `trio_websocket` import appears in target API/client code;
- route handlers contain no direct `_store`, processor, or LLM access;
- OpenAPI schemas contain no provider configuration fields;
- all required tests and probe targets are discoverable.

The validator must not enforce arbitrary line-count budgets. Use dependency and forbidden-concept checks that reflect architectural intent.

## 21. Required commands and CI gates

Recommended Phase 5 checks:

```bash
uv run ruff format --check src/jung tests/unit/jung tests/integration/jung tests/e2e
uv run ruff check src/jung tests/unit/jung tests/integration/jung tests/e2e
uv run pytest tests/unit/jung
uv run pytest tests/integration/jung
uv run pytest tests/e2e/test_console_v1_workflow.py
uv run python scripts/validate_refactor_phase_5.py
make probe-console-v1-deterministic
```

The Phase 5 PR should also run:

- Phase 2 persistence/workflow tests;
- Phase 3 gateway/processor tests;
- Phase 4 application tests;
- Phase 1 black-box characterization tests while the legacy runtime still exists;
- standard repository finalization once.

Hosted CI uses `FakeLLM` and an ephemeral real Uvicorn server in the normal containerized test environment. It does not require an external model server.

Run the optional local-model smoke manually when production API composition, model settings loading, or provider payload behavior changes.

## 22. Acceptance scenarios

### 22.1 Fresh application

Given a fresh database:

- `/health` becomes ready only after initialization;
- `/state` returns `SETUP`, revision `0` or the schema-defined initial revision, and `update_profile` available;
- `/profile` returns the seeded profile singleton;
- no route or schema contains `user_id`.

### 22.2 Profile to intake

Given the current revision:

- `PUT /profile` persists a valid profile;
- snapshot becomes `INTAKE`;
- intake session is visible as the active session;
- stale revision returns `state_conflict` with current snapshot.

### 22.3 Intake chat

Given `INTAKE`:

- WebSocket `send_message` accepts a durable user message;
- `message_in_progress` and acceptance snapshot are emitted;
- tokens stream with monotonic sequence;
- completed assistant message is durable;
- completion snapshot is emitted;
- disconnect does not cancel generation;
- duplicate client ID creates no second user message.

### 22.4 Assessment and style selection

When intake completes:

- assessment operation becomes visible;
- `operation_changed` reflects pending/running/complete or failed;
- completed recommendations are available from `GET /styles`;
- recommendation response contains no initial-plan payload;
- style selection makes no LLM call;
- selected style and initial plan become durable;
- stage becomes `READY`.

### 22.5 Therapy session

Given `READY`:

- `POST /sessions` returns `201 {session, snapshot}`;
- stage becomes `THERAPY`;
- no undocumented assistant-only greeting is persisted;
- chat works through the same WebSocket contract;
- history returns ordered durable messages.

### 22.6 End and post-session operation

Given an active therapy session:

- end returns `202` with `POST_SESSION` snapshot;
- post-session work runs after response;
- completion updates session/profile/plan atomically;
- stage returns to `READY`;
- failure leaves stage unchanged and exposes retryability;
- retry reuses the same operation row.

### 22.7 Restart

Given interrupted durable work:

- API is not healthy until recovery completes;
- stale operations recover according to Phase 4;
- stale chat turns become retryable failures;
- completed work is not rerun;
- console refreshes through HTTP and reconnects without replay assumptions.

## 23. Risk register

### Risk: API logic recreates orchestration

Mitigation:

- routes call one application method;
- adapter imports are validated;
- no store/processor/LLM access from API;
- integration tests compare API behavior to application behavior;
- review rejects route-level workflow branching beyond response selection.

### Risk: assessment recommendations remain inaccessible

Mitigation:

- add one narrow application read model before API implementation;
- update canonical contract;
- test redaction of initial plan and sensitive assessment fields;
- drive console style selection solely from the public response.

### Risk: wire models leak internal fields

Mitigation:

- explicit DTOs and pure mappers;
- no domain `model_dump()` response shortcuts;
- schema tests for forbidden names;
- separate summary/detail models;
- security review of assessment, profile, and plan responses.

### Risk: WebSocket disconnect cancels generation

Mitigation:

- generation remains supervisor-owned;
- connection only subscribes to `EventStream`;
- disconnect tests block `FakeLLM`, close socket, then release generation;
- no task handle from application work is stored in connection state.

### Risk: duplicate chat resubmission hangs the client

Mitigation:

- client uses bounded acknowledgement wait;
- uncertain delivery triggers HTTP reconciliation;
- same client message ID is retained;
- no token replay is expected;
- integration tests cover pending and completed duplicate states.

### Risk: slow WebSocket blocks application events

Mitigation:

- retain bounded `EventStream` queues;
- avoid an unbounded adapter queue;
- close only the slow connection;
- test a non-reading observer alongside a healthy observer.

### Risk: FastAPI lifespan duplicates shutdown behavior

Mitigation:

- lifespan enters/exits `application_context()` only;
- Phase 4 remains owner of supervisor and LLM closure;
- lifecycle tests assert exactly-once initialization and closure;
- no separate route-level task registry.

### Risk: console becomes another workflow engine

Mitigation:

- `available_commands` gates actions;
- stage switch is display/navigation only;
- no client mutation of stage;
- reconnect always refreshes snapshot;
- console tests use server conflicts as authoritative.

### Risk: legacy and target APIs become permanently dual-maintained

Mitigation:

- target console uses only `/api/v1`;
- deterministic cutover probe uses only target API;
- legacy characterization remains temporary protection;
- Phase 6 deletion begins immediately after Phase 5 acceptance;
- docs state that legacy and target are not both supported contracts.

### Risk: OpenAPI becomes a second manually maintained specification

Mitigation:

- generate it from runtime models;
- canonical prose covers semantics not expressible in OpenAPI;
- tests compare path/schema invariants;
- do not hand-edit or commit generated protocol code.

### Risk: local-only API is mistaken for a secure network service

Mitigation:

- bind to loopback by default;
- document lack of authentication;
- make non-loopback binding explicit configuration;
- avoid permissive credentialed CORS;
- defer production security architecture until there is a real deployment requirement.

## 24. Review checklist

### Architecture

- [x] Phase 5 remains an adapter/reference-client change.
- [x] API routes call only `TherapyApplication` reads and commands.
- [x] API code never accesses `SQLiteStore`, processors, or LLM directly.
- [x] Client code never imports application/core internals.
- [x] Core code imports no API/client framework.
- [x] No service locator, dispatcher framework, broker, or event store was introduced.
- [x] One FastAPI lifespan owns one `ApplicationRuntime` context.

### Contracts

- [x] All requests and responses use named Pydantic models.
- [x] Incoming models forbid unknown fields.
- [x] No `user_id` exists in v1.
- [x] Domain-to-wire differences are explicit mappings.
- [x] Commands have deterministic wire order.
- [x] Summary and detail responses expose only intended fields.
- [x] Style recommendations are available without exposing assessment internals.
- [x] Fresh profile absence is documented and tested.

### HTTP

- [x] Exact endpoint matrix is implemented.
- [x] State-changing requests require `expected_revision`.
- [x] Correct `200`, `201`, and `202` statuses are used.
- [x] No generic workflow or job route exists.
- [x] Health represents initialized process readiness only.
- [x] OpenAPI contains the exact target path set.

### Errors

- [x] Stable error codes map consistently.
- [x] Revision conflict includes current snapshot when available.
- [x] Request validation uses the stable envelope.
- [x] Request IDs are returned and logged.
- [x] Provider/internal diagnostics never reach clients.
- [x] Durable retryability is preserved.

### WebSocket

- [x] Only `send_message` is accepted from clients.
- [x] Server events form a validated discriminated union.
- [x] Event mapping preserves application order.
- [x] Token sequence is unchanged.
- [x] Disconnect cannot cancel accepted work.
- [x] No replay buffer exists.
- [x] Slow client handling is bounded.
- [x] Multiple observers work.
- [x] No legacy events are emitted.

### Client

- [x] `JungApiClient` owns all networking and validation.
- [x] Console contains no route strings or JSON parsing.
- [x] Typed errors include code, status, request ID, and snapshot where applicable.
- [x] State-changing HTTP calls are not silently retried.
- [x] WebSocket reconnect is explicit.
- [x] Uncertain chat delivery reconciles through durable reads.
- [x] Resources close cleanly.

### Console

- [x] No profile selection, login, or user ID flow remains in the target path.
- [x] Snapshot and available commands drive behavior.
- [x] Recommendations are displayed from `GET /styles`.
- [x] Chat finalizes from `message_completed`, not token concatenation alone.
- [x] Partial buffers are discarded after failure/reconnect.
- [x] Failed operations can be retried only when server permits.
- [x] Existing useful input providers and event sinks are retained without legacy protocol coupling.

### Tests and probes

- [x] Contract and mapper unit tests pass.
- [x] HTTP integration tests use real application/store and `FakeLLM`.
- [x] WebSocket tests use a real ephemeral server.
- [x] Client tests use the real API boundary.
- [x] Deterministic console probe passes end to end.
- [x] Restart, retry, duplicate, disconnect, and slow-client cases are covered.
- [x] Phase 2–4 tests remain green.
- [x] Legacy characterization tests remain green until Phase 6.
- [x] Optional local-model smoke evidence is recorded when required.

## 25. Phase 5 exit criteria

All criteria are blocking:

> **Phase 5 exit evidence (2026-07-16):** `make validate-refactor-phase-5` — scoped ruff, `scripts/validate_refactor_phase_5.py` static/runtime checks, and `phase-5-test` (unit/integration resilience plus `_phase-5-console-v1` E2E). Phase 6 handoff: [deletion-inventory.md](deletion-inventory.md).

- [x] FastAPI wraps the Phase 4 `application_context()` without duplicating lifecycle logic.
- [x] Startup recovery completes before the API reports healthy.
- [x] All accepted `/api/v1` HTTP routes are implemented.
- [x] `/api/v1/chat` implements the accepted command/event contract.
- [x] No target endpoint accepts `user_id`.
- [x] No generic workflow mutation or job API exists.
- [x] Explicit wire DTOs prevent internal model leakage.
- [x] Style recommendations are available through the public API with sensitive fields redacted.
- [x] Fresh setup/profile-read behavior is coherent and documented.
- [x] Stable error mapping and request IDs are implemented.
- [x] Revision conflicts return the authoritative snapshot when available.
- [x] WebSocket disconnects do not cancel accepted chat or operations.
- [x] Tokens remain ephemeral and unreplayed.
- [x] Slow subscribers cannot block accepted work indefinitely.
- [x] OpenAPI contains the exact target HTTP contract and no legacy paths.
- [x] `JungApiClient` validates every HTTP response and WebSocket event.
- [x] Console networking occurs only through `JungApiClient`.
- [x] Target console uses only `/api/v1`.
- [x] Target console contains no login/profile-selection/user-ID flow.
- [x] Deterministic setup-to-ready console probe passes.
- [x] Deterministic therapy-to-ready console probe passes.
- [x] Restart, retry, duplicate chat, and disconnect scenarios pass.
- [x] API/client/core import-boundary validation passes.
- [x] Phase 2, Phase 3, and Phase 4 tests remain green.
- [x] The target API and console have no dependency on the legacy runtime.
- [x] Legacy and target APIs are not documented as concurrently supported contracts.

## 26. Definition of done

Phase 5 is done when a developer can implement a new frontend without deciding:

- how to construct or recover the backend application;
- which routes represent product commands;
- which fields are public;
- how revisions and conflicts work;
- how to discover available commands;
- how to obtain style recommendations;
- how to start and end sessions;
- how to retry a failed operation;
- how chat acceptance, tokens, completion, and failure are represented;
- how disconnect and reconnect work;
- how duplicate chat IDs are reconciled;
- how errors and request IDs are encoded;
- how session history is fetched;
- whether clients may access SQLite or application internals;
- whether missed tokens are replayed;
- whether WebSocket connections own generation;
- how the bundled console performs networking.

If Phase 6 still needs to preserve legacy routes because the target console depends on them, Phase 5 is not complete.

If a future frontend must import `TherapyApplication`, inspect SQLite, infer workflow transitions, parse legacy events, or access full assessment results to select a style, Phase 5 is not complete.

## 27. Handoff to Phase 6

Phase 6 begins with:

- one final `/api/v1` FastAPI server;
- one final WebSocket contract;
- one typed `JungApiClient`;
- one API-backed target console;
- deterministic API and console workflow probes;
- OpenAPI generated from explicit contracts;
- no target dependency on the legacy runtime;
- a proven behavioral replacement for the legacy server and console.

Phase 6 may then delete:

- Quart/Quart-Trio server composition;
- legacy HTTP routes and DTOs;
- legacy WebSocket handler and protocol constants;
- registration, login, profile-selection, and user-scoped APIs;
- legacy workflow-next-action and job-status events;
- Trio console networking;
- legacy console workflow-action state;
- service container and orchestration graph;
- legacy database facade/repositories/executor;
- compatibility and generated protocol machinery;
- tests that protect only deleted internals.

Phase 5 must not pre-emptively preserve adapters from `/api/v1` back into legacy code. Its purpose is to make Phase 6 a deletion exercise rather than another behavioral redesign.
