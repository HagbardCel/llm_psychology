---
owner: engineering
status: accepted
last_reviewed: 2026-07-13
review_cycle_days: 30
source_of_truth_for: Detailed implementation plan for architecture refactor Phase 4
---

# Architecture Refactor Phase 4 Implementation Plan

## 1. Phase objective

Phase 4 turns the target domain, persistence, LLM gateway, style catalog, and phase processors into one executable application core.

The phase implements:

- one explicitly constructed `TherapyApplication`;
- one small in-process `EventStream` for live application events;
- one structured `TaskSupervisor` for accepted chat and operation work;
- one application mutation lock and one generation lock;
- durable chat acceptance, streaming, completion, failure, idempotency, and retry behavior;
- assessment and post-session operation execution;
- atomic application completion transactions;
- startup recovery and bounded shutdown behavior;
- full application integration tests using the real `SQLiteStore` and deterministic `FakeLLM`.

At the end of Phase 4, every target workflow must run without HTTP, WebSockets, the console, the legacy orchestration graph, or the legacy database stack. Phase 5 should be able to expose the application through `/api/v1` without inventing workflow, persistence, generation, recovery, or concurrency semantics.

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
- [Phase 3 Implementation Plan](phase-3-implementation-plan.md).

This document translates those decisions into implementable Phase 4 work. It must not redefine the public API, processor contracts, model-provider boundary, or durable workflow unless an implementation-blocking contradiction is first recorded in the relevant canonical document or ADR.

## 2. Desired implementation philosophy

### 2.1 Build a use-case coordinator, not a new orchestration framework

`TherapyApplication` replaces the legacy orchestrator, conversation manager, workflow engine, response handler, session lifecycle manager, workers, and service-container lookup graph.

It must therefore be simpler than the combined system it replaces.

Prefer:

- explicit methods named after product use cases;
- direct typed constructor dependencies;
- short private helpers for repeated application mechanics;
- pure workflow policy calls;
- whole-store operations through `SQLiteStore`;
- typed processor inputs and outputs;
- durable state as the source of truth.

Do not introduce:

- a generic command bus;
- handlers registered by string or type;
- middleware pipelines inside the application layer;
- an application plugin system;
- a generic workflow engine;
- a generalized job scheduler;
- an event-sourcing abstraction;
- an application repository layer over `SQLiteStore`;
- an async store facade with one wrapper method per store method;
- a second dependency-injection container;
- compatibility adapters back to legacy orchestration.

The central runtime path should remain understandable by reading approximately:

1. `application.py`;
2. `events.py`;
3. `supervisor.py`;
4. `composition.py`;
5. `sqlite_store.py`.

### 2.2 Durable acceptance comes before asynchronous work

No LLM call starts before the corresponding work is durable.

For chat:

1. validate idempotency, stage, session, revision, and active-generation availability;
2. reserve generation ownership;
3. persist the user message and `PENDING` `ChatTurn`;
4. increment revision;
5. publish accepted events;
6. synchronously admit the supervised worker (or place the turn in the defined failed/recoverable state);
7. return the authoritative durable turn.

Steps 5–6 must guarantee that generation ownership is transferred to a supervised worker or the generation lock is released and the durable turn is placed in the defined recoverable/failed state, even if event publication is interrupted.

For assessment and post-session work:

1. atomically mutate the workflow and create/reuse the `PENDING` `Operation`;
2. increment revision;
3. schedule supervised execution;
4. return the authoritative snapshot.

This ordering is non-negotiable. A crash may interrupt generation, but it must not erase accepted user input or create invisible work.

### 2.3 Keep concurrency rules intentionally narrow

The product is local, single-user, and single-session. It does not need a generalized concurrency-control subsystem.

Use exactly:

- one application mutation lock for command validation, durable state mutation, recovery, and consistent snapshot assembly;
- one generation lock for the single accepted chat generation;
- the durable operation uniqueness constraints already owned by SQLite;
- the task supervisor for lifecycle ownership.

Do not add:

- per-user locks;
- per-session lock registries;
- distributed locks;
- queues or brokers;
- worker pools;
- database advisory-lock emulation;
- lock-ordering frameworks.

LLM execution must happen outside the application mutation lock. Only durable acceptance, completion, failure, recovery, and snapshot assembly hold that lock.

### 2.4 Treat synchronous SQLite operations as complete units

`SQLiteStore` remains synchronous and concrete. Async application code calls complete store operations with `asyncio.to_thread()`.

Do not:

- share SQLite connections across threads;
- wrap individual SQL statements in `to_thread()`;
- introduce `aiosqlite` during this refactor;
- create a connection pool;
- create a generic async repository protocol solely to hide `to_thread()`.

A small private helper such as `_run_store(callable, *args, **kwargs)` is sufficient.

Round-2 remediation hardens this helper: once a synchronous store call starts, repeated `CancelledError` during `asyncio.shield()` drain cannot release the application mutation lock until the thread-backed task finishes. Bounded shutdown applies around LLM and supervised background work; an already-running local SQLite call is allowed to complete before lock release.

### 2.5 Keep live events subordinate to durable state

`EventStream` is a local fan-out mechanism for currently connected observers. It is not authoritative.

Rules:

- tokens are ephemeral and best-effort;
- snapshots, messages, chat-turn states, operation states, plans, and profile changes are durable;
- reconnecting clients recover through application reads in Phase 4 and `/api/v1/state` in Phase 5;
- the event stream performs no replay;
- events do not become workflow inputs;
- subscriber failure never cancels accepted work;
- WebSocket concepts do not appear in Phase 4.

### 2.6 Make failure explicit and durable

Expected LLM failures retain the Phase 3 taxonomy:

- `llm_unavailable` — retryable;
- `llm_timeout` — retryable;
- `invalid_llm_output` — not retryable;
- `internal_error` for unexpected provider-protocol or application failures — not retryable by default, except pre-worker chat task-admission failures which use `internal_error` with `retryable=True` because the accepted turn remains valid and no generation attempt occurred.

Processors must not generate friendly fallback text after a failed model call. The application records the failed `ChatTurn` or `Operation`; Phase 5 maps the result to transport errors.

Partial streamed text is never persisted as a completed assistant message.

### 2.7 Optimize for testability without building a test framework

Inject only nondeterminism that materially improves deterministic tests:

- current-time callable;
- UUID callable;
- `FakeLLM` through the existing gateway interface;
- concrete temporary `SQLiteStore`;
- immutable style catalog;
- real `EventStream` and `TaskSupervisor`.

Use ordinary callables rather than clock, UUID, and factory class hierarchies.

### 2.8 Prefer final-form breaking corrections over transitional compatibility

The target system has not been deployed in production. Where Phase 2 store-facing command models conflict with the accepted API or application boundary, correct them now.

Do not preserve construction-only identifiers or payloads in user-facing application commands merely because Phase 2 tests used them.

## 3. Scope

### 3.1 In scope

Phase 4 includes:

- `TherapyApplication` construction and lifecycle;
- target application command cleanup;
- application result and event models;
- snapshot assembly and command validation;
- explicit style selection from the persisted assessment result;
- session start and end use cases;
- chat idempotency and generation ownership;
- intake and therapy processor input assembly;
- intake response streaming and durable intake-record updates;
- processor-driven intake completion;
- atomic intake-turn completion plus assessment-operation creation;
- therapy response streaming and durable completion;
- chat failure persistence and retry classification;
- assessment operation execution;
- post-session operation execution;
- deterministic patch merging before persistence;
- operation failure and retry behavior;
- startup recovery of operations and chat turns;
- scheduling of durable pending operations;
- bounded graceful shutdown semantics;
- in-process event fan-out;
- application-level tracing hooks or structured logging at command/task boundaries;
- full application integration tests;
- Phase 4 import and forbidden-concept validation;
- documentation of any narrowly required Phase 2 persistence seam correction.

### 3.2 Out of scope

Phase 4 must not implement:

- FastAPI or Starlette;
- HTTP routes or DTOs;
- WebSocket connections or wire-event serialization;
- OpenAPI generation;
- `JungApiClient`;
- console changes;
- workflow probes through `/api/v1`;
- client reconnect code;
- legacy runtime cutover;
- legacy code deletion;
- database migration compatibility;
- a web frontend;
- authentication;
- multi-user behavior;
- multiple concurrent therapy sessions;
- a general background-job framework;
- event replay or durable event storage;
- a message broker;
- provider-specific logic outside `llm/`;
- redesign of processor prompts or structured result schemas without measured evidence;
- automatic LLM retries beyond Phase 3's structured correction attempt;
- a generic chat-turn retry endpoint or command not present in the accepted API v1 contract;
- an implicit assistant-only therapy opening turn that is not represented by the accepted API and durable `ChatTurn` model.

`POST /api/v1/sessions` creates a therapy session. The first therapy response in Phase 4 follows the first accepted user message. `TherapyTurnInput.is_opening_turn` remains processor capability, not a reason to invent an undocumented assistant-only persistence path.

## 4. Entry conditions

Phase 4 begins only when:

- Phase 2 domain, workflow, and persistence tests pass;
- Phase 3 gateway, style, and processor tests pass;
- the Phase 3 local-model acceptance smoke has been recorded for the intended runtime configuration;
- no target module imports the legacy runtime;
- no unresolved ADR-level question remains about application, task, event, or recovery ownership;
- the target processor contracts are stable;
- the accepted workflow and API documents agree on command names, revision behavior, operation lifecycle, and chat idempotency.

The Phase 4 branch should be based on the merged Phase 3 head.

Recommended branch:

```text
refactor/phase-4-application-core
```

Phase 4 must remain reviewable as an application-core change. Do not mix in Phase 5 transport implementation or Phase 6 deletion.

## 5. Existing foundation and required seam review

### 5.1 Reuse without redesign

Phase 4 should directly reuse:

- `Stage`, `CommandName`, `OperationKind`, `OperationStatus`, and `ChatTurnStatus`;
- `Profile`, `StoredProfile`, `Session`, `Message`, `Plan`, `PlanContent`, `Operation`, `ChatTurn`, `AppState`, `WorkflowFacts`, and `AppSnapshot`;
- pure workflow functions in `jung.workflow`;
- the concrete `SQLiteStore`;
- `LLMGateway`, `ModelPolicy`, and existing LLM error classes;
- `IntakeProcessor`, `AssessmentProcessor`, `TherapyProcessor`, and `PostSessionProcessor`;
- transcript models and normalization helpers;
- pure post-session merge helpers;
- immutable style loading/catalog behavior;
- `FakeLLM`.

### 5.2 Correct application command shapes before orchestration

The Phase 2 command models currently include identifiers and plan material needed by low-level store tests. Those fields must not leak into the Phase 4 application boundary.

Final application command intent:

```python
class UpdateProfile(BaseModel):
    expected_revision: int
    profile: Profile

class SelectStyle(BaseModel):
    expected_revision: int
    style_id: str

class StartSession(BaseModel):
    expected_revision: int

class EndSession(BaseModel):
    expected_revision: int
    session_id: UUID

class SendMessage(BaseModel):
    expected_revision: int
    session_id: UUID
    client_message_id: UUID
    content: str
    request_id: UUID | None = None

class RetryOperation(BaseModel):
    expected_revision: int
    operation_id: UUID
```

The application generates:

- therapy session IDs;
- operation IDs;
- chat-turn IDs;
- user-message IDs;
- assistant-message IDs;
- initial and revised plan IDs.

`FinishIntake` is an internal processor-driven transition, not a client command. It should not remain part of the externally constructible application command set.

Store methods may continue accepting generated IDs as explicit parameters. That keeps persistence deterministic without making clients responsible for internal entity construction.

### 5.3 Minimal persistence seam corrections

Before implementing application orchestration, confirm that `SQLiteStore` supports the following complete use cases.

Required additions or corrections:

1. **Load the latest completed assessment operation**
   - Add a narrow read such as `get_latest_completed_operation(OperationKind.ASSESSMENT)`.
   - The application parses the durable result as `AssessmentResult` and selects initial plan material.
   - The store must not import assessment processor models.

2. **Atomically complete a final intake turn and create assessment work**
   - Add one store operation that, in one `BEGIN IMMEDIATE` transaction:
     - inserts the assistant message;
     - marks the `ChatTurn` `COMPLETE`;
     - persists the final intake record;
     - closes the intake session;
     - creates or reuses the assessment `Operation` keyed by `(kind, source_session_id)`;
     - sets `Stage.ASSESSMENT`;
     - increments revision exactly once.
   - Return the completed turn, operation, and resulting app state or enough typed values to assemble them without ambiguous rereads.

3. **Preserve existing atomic completion methods**
   - `complete_assessment()` remains the atomic assessment-result and stage transition.
   - `complete_post_session()` remains the atomic session/profile/plan/operation and stage transition.
   - `complete_chat_turn()` remains the ordinary incomplete-intake or therapy turn completion.

4. **Maintain revision semantics**
   - accepted chat increments revision;
   - successful chat completion increments revision;
   - failed accepted chat increments revision;
   - operation creation, start, completion, failure, retry, and recovery increment revision when durable visible state changes;
   - ephemeral tokens never increment revision.

5. **Avoid a generic snapshot query layer unless needed**
   - The application mutation lock prevents in-process writes while assembling a snapshot.
   - Reuse existing typed reads first.
   - Add one aggregate read only if integration tests demonstrate an inconsistent or excessively complex snapshot path.

Do not change the schema unless a required invariant cannot be satisfied with the existing tables. No migration is added; reset remains the supported transition.

## 6. Phase deliverables and package shape

Recommended minimal additions:

```text
src/jung/
├── application.py
├── composition.py
├── events.py
├── supervisor.py
├── domain/
│   ├── commands.py
│   ├── errors.py
│   ├── models.py
│   └── results.py          # only when a concrete compound result is needed
├── persistence/
│   └── sqlite_store.py
├── phases/
└── llm/

tests/unit/jung/
├── test_events.py
├── test_supervisor.py
└── test_application_helpers.py

tests/integration/jung/
├── test_application_workflow.py
├── test_application_chat.py
├── test_application_operations.py
├── test_application_recovery.py
├── test_application_concurrency.py
└── application_scenarios.py
```

Consolidation rules:

- begin with one `application.py`;
- split only if a cohesive section becomes independently testable or materially obscures the use-case flow;
- do not create `application/handlers/`, `commands/handlers/`, `services/`, `workers/`, or `use_cases/` directories;
- keep event models and fan-out mechanics together unless the file becomes unwieldy;
- keep supervisor lifecycle in one module;
- keep concrete construction in `composition.py`;
- do not create abstract base classes for events, tasks, processors, stores, clocks, or ID factories.

## 7. Target application boundary

### 7.1 Public use cases

The application should expose the accepted core methods:

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

Read helpers needed by application tests or Phase 5 may be added only as explicit product reads, for example:

- `get_profile()`;
- `list_styles()`;
- `list_sessions()`;
- `get_session_history(session_id)`.

Do not add a generic `execute(command)` method.

### 7.2 Constructor dependencies

Illustrative constructor:

```python
class TherapyApplication:
    def __init__(
        self,
        *,
        store: SQLiteStore,
        intake: IntakeProcessor,
        assessment: AssessmentProcessor,
        therapy: TherapyProcessor,
        post_session: PostSessionProcessor,
        styles: StyleCatalog,
        events: EventStream,
        supervisor: TaskSupervisor,
        now: Callable[[], datetime],
        new_id: Callable[[], UUID],
    ) -> None: ...
```

Use the existing concrete style-catalog type or a small immutable project-owned interface if one already exists. Do not introduce a runtime registry.

### 7.3 Application invariants

Every public mutation method must:

1. reject new work when shutdown has begun;
2. acquire the application mutation lock;
3. load current workflow facts or snapshot;
4. call `require_command_allowed()` where applicable;
5. preserve duplicate-chat resolution before revision validation;
6. invoke one complete store operation;
7. reread or assemble the authoritative result;
8. release the mutation lock;
9. publish durable-change events;
10. schedule accepted background work after persistence.

No processor call occurs while the mutation lock is held.

## 8. Snapshot assembly

### 8.1 Authoritative derivation

`get_snapshot()` should derive one `AppSnapshot` from durable state:

- `revision` and `stage` from `app_state`;
- `profile_complete` from the stored editable profile;
- `selected_style` from the current plan when one exists;
- `active_session` from the one open session;
- `current_operation` from pending, running, or failed operation state;
- `active_chat_turn` from the pending turn;
- `available_commands` from `workflow.available_commands(WorkflowFacts)`.

The application must not persist `available_commands` or another next-action representation.

### 8.2 Consistency rule

Snapshot assembly acquires the application mutation lock. Background completion and failure persistence also acquire that lock. This ensures that multiple typed store reads do not straddle an in-process mutation.

Do not hold the lock while publishing events.

### 8.3 Validation

Add invariant checks for impossible combinations, including:

- `SETUP` with an active session;
- `INTAKE` without an open intake session;
- `THERAPY` without an open therapy session;
- `READY` with an open session or current operation;
- `ASSESSMENT` with a non-assessment current operation;
- `POST_SESSION` with a non-post-session current operation;
- pending chat turn outside `INTAKE` or `THERAPY`;
- selected plan style missing from the immutable catalog.

Raise `InvariantViolation`; do not silently repair ordinary corruption in read paths.

## 9. EventStream design

### 9.1 Purpose

`EventStream` distributes application-owned live events to zero or more current subscribers.

Illustrative interface:

```python
class EventStream:
    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[AsyncIterator[ApplicationEvent]]: ...

    async def publish(self, event: ApplicationEvent) -> None: ...
```

An equivalent explicit `Subscription` object is acceptable if it makes cleanup clearer.

### 9.2 Minimal application event union

Use project-owned typed dataclasses or frozen Pydantic models. Keep the union small:

```text
ChatTurnAccepted
ChatTokenGenerated
ChatTurnCompleted
ChatTurnFailed
SnapshotChanged
OperationChanged
```

Recommended fields:

- `session_id`;
- `turn_id` where relevant;
- `request_id` where relevant;
- monotonic token `sequence`;
- token text;
- durable `ChatTurn`;
- completed assistant `Message` where relevant;
- durable `Operation`;
- authoritative `AppSnapshot`.

Do not use wire event names as class names merely to mirror WebSocket JSON. Phase 5 performs the transport mapping.

### 9.3 Subscriber behavior

Use one bounded queue per subscriber.

Rules:

- publishing never waits indefinitely for a slow subscriber;
- any subscriber queue overflow evicts that subscription rather than blocking accepted work;
- unsubscribe removes the queue in `finally`;
- one subscriber exception does not affect other subscribers;
- there is no replay;
- reconnect relies on an authoritative snapshot and persisted history.

Keep queue policy simple and explicitly tested. Do not implement prioritization, persistence, acknowledgment, offsets, or consumer groups.

### 9.4 Event ordering

Chat acceptance:

1. durable user message and pending turn;
2. `ChatTurnAccepted`;
3. `SnapshotChanged`.

Chat success:

1. zero or more `ChatTokenGenerated` events;
2. durable assistant message and completed turn;
3. `ChatTurnCompleted`;
4. `SnapshotChanged`.

Chat failure after acceptance:

1. durable failed turn;
2. `ChatTurnFailed`;
3. `SnapshotChanged`.

Operation status change:

1. durable operation mutation;
2. `OperationChanged` containing the operation and current snapshot.

Ordinary synchronous command:

1. durable mutation;
2. `SnapshotChanged`.

## 10. TaskSupervisor design

### 10.1 Responsibilities

`TaskSupervisor` owns every accepted background coroutine:

- intake response generation;
- therapy response generation;
- assessment operation execution;
- post-session operation execution.

It must be backed by an entered `asyncio.TaskGroup` as required by ADR 0002.

Illustrative interface:

```python
class TaskSupervisor:
    async def __aenter__(self) -> TaskSupervisor: ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...
    def start(
        self,
        *,
        name: str,
        run: Callable[[], Awaitable[None]],
    ) -> bool: ...
    async def shutdown(self, *, timeout_seconds: float) -> None: ...
```

`start()` tracks owned `asyncio.Task` objects, rolls back active names when `create_task()` fails, and `shutdown()` waits/cancels only owned tasks via `asyncio.wait()`. Shutdown is safely repeatable.

### 10.2 Failure isolation

A raw child exception in `TaskGroup` would cancel siblings. Therefore every scheduled task must run inside a supervisor wrapper that:

- catches ordinary `Exception`;
- logs task name and correlation identifiers;
- prevents sibling cancellation;
- never swallows `asyncio.CancelledError`;
- relies on the application worker to persist the durable failure before returning.

The wrapper is a containment boundary, not the primary error handler. Application chat and operation workers must catch, classify, and persist their own failures.

### 10.3 Task tracking

Track active tasks by stable name or durable entity ID only to support:

- duplicate scheduling prevention;
- bounded shutdown;
- tests asserting no leaked tasks.

Do not expose a general job registry or task query API.

### 10.4 Shutdown

Shutdown sequence:

1. stop accepting new tasks;
2. application stops accepting new mutations;
3. wait up to the configured grace interval for active work;
4. cancel remaining supervised tasks;
5. allow cancellation cleanup to release the generation lock;
6. leave interrupted durable operations recoverable;
7. leave interrupted pending chat turns for startup stale-turn recovery;
8. exit the task group;
9. close the concrete LLM client in composition.

A worker cancelled during shutdown must not mark incomplete work successful. For chat cancellation, leave the turn pending so startup recovery can mark it retryable failed. For operations, leave `RUNNING` so startup recovery returns it to `PENDING`.

## 11. Composition root

### 11.1 Explicit construction

`composition.py` is the only production location that constructs the target dependency graph.

It should:

1. parse application and LLM settings once;
2. validate request extras and task policies before the first model call;
3. create and initialize `SQLiteStore`;
4. create one concrete OpenAI-compatible client;
5. wrap it with tracing when enabled;
6. build all task policies;
7. preflight `JSON_SCHEMA` response formats for `IntakeRecordPatch`, `AssessmentResult`, `SessionAnalysisResult`, and `PostSessionResult` before creating the concrete LLM client;
8. load the immutable style catalog;
9. construct the four processors explicitly;
10. construct `EventStream`;
11. enter `TaskSupervisor`;
12. construct `TherapyApplication`;
13. run startup recovery;
14. yield the application/runtime components;
15. perform bounded shutdown and close the concrete LLM client.

Strict schema conversion uses a schema-node allowlist: structural keys (`type`, `properties`, `required`, `additionalProperties`, `items`, `$defs`, `$ref`, `anyOf`, `enum`, `description`), constraint keys including `minLength`/`maxLength`, and strips `default`/`title`. Unknown keywords on schema nodes fail preflight with `UnsupportedStrictSchema`.

### 11.2 Lifecycle shape

Prefer one async context manager:

```python
@asynccontextmanager
async def application_context(settings: Settings) -> AsyncIterator[ApplicationRuntime]:
    ...
```

`ApplicationRuntime` may be a small frozen dataclass containing:

- `application`;
- `events`;
- optionally the concrete resources Phase 5 lifespan must close.

Do not turn it into another service locator. Phase 5 receives explicit attributes.

### 11.3 Test construction

Application integration tests should normally construct dependencies directly with:

- temporary `SQLiteStore`;
- `FakeLLM`;
- real processors;
- real styles;
- real `EventStream`;
- real `TaskSupervisor`;
- deterministic clock and UUID sequence.

Use the production composition context only in a small composition smoke test.

## 12. Synchronous use cases

### 12.1 `update_profile`

Flow:

1. acquire mutation lock;
2. load facts;
3. require `UPDATE_PROFILE`;
4. call `store.update_profile()` through `to_thread()`;
5. assemble snapshot;
6. release lock;
7. publish `SnapshotChanged`;
8. return snapshot.

The store remains responsible for creating the initial intake session when the profile becomes complete.

### 12.2 `select_style`

Flow:

1. acquire mutation lock;
2. require `SELECT_STYLE`;
3. validate `style_id` against the immutable catalog;
4. load the latest completed assessment operation;
5. parse `operation.result` as `AssessmentResult` with strict validation;
6. select the matching `StyleRecommendation`;
7. take its `initial_plan` without another LLM call;
8. generate a plan ID;
9. call `store.select_style_and_create_initial_plan()`;
10. assemble snapshot;
11. release lock;
12. publish `SnapshotChanged`;
13. return snapshot.

Failure to parse a supposedly completed assessment is `InvariantViolation`, not `invalid_llm_output`; the invalid output should have been rejected before completion.

### 12.3 `start_session`

Flow:

1. acquire mutation lock;
2. require `START_SESSION`;
3. generate a therapy session ID;
4. call `store.start_therapy_session()`;
5. assemble snapshot for the emitted event;
6. release lock;
7. publish `SnapshotChanged`;
8. return the created `Session`.

No model call is made. No assistant-only opening message is created.

### 12.4 `end_session`

Flow:

1. acquire mutation lock;
2. require `END_SESSION`;
3. validate the command session matches the active therapy session;
4. generate an operation ID;
5. atomically close the session and create/reuse the pending post-session operation;
6. assemble snapshot;
7. release lock;
8. publish `OperationChanged` for the pending operation;
9. schedule operation execution;
10. return snapshot.

### 12.5 `retry_operation`

Flow:

1. acquire mutation lock;
2. require `RETRY_OPERATION`;
3. verify the requested operation is the current failed retryable operation;
4. reset the same durable row to `PENDING` through the store;
5. assemble snapshot;
6. release lock;
7. publish `OperationChanged`;
8. schedule the same operation ID;
9. return snapshot.

Retry never creates a second operation row and never duplicates result artifacts.

## 13. Chat acceptance and generation

### 13.1 Acceptance and idempotency

`submit_message()` must resolve `(session_id, client_message_id)` before revision validation.

Under the mutation lock:

1. load an existing turn by client ID;
2. when existing status is `PENDING`, return it without creating or scheduling another task;
3. when existing status is `COMPLETE`, return it without revision validation or duplicate events;
4. when existing status is retryable `FAILED`, reserve the generation lock, reset the same turn to `PENDING`, and schedule it with the new request correlation;
5. when existing status is permanently `FAILED`, raise a stable application error carrying the stored code and retryability;
6. for a new turn, raise `Busy` when another chat turn is pending or generation is active; otherwise require `SEND_MESSAGE`, validate content, and ensure the generation lock is available;
7. reserve generation before durable acceptance so a second distinct command cannot pass the same check;
8. generate turn and user-message IDs;
9. call `store.accept_chat_message()`;
10. assemble snapshot;
11. release the mutation lock;
12. publish `ChatTurnAccepted` and `SnapshotChanged`;
13. schedule the worker;
14. return the durable turn.

If persistence or scheduling fails after the generation lock is reserved but before the worker owns it, release the lock in a guaranteed cleanup path. If persistence succeeded but chat task admission returns `False` or raises unexpectedly, mark the turn failed with retryable `internal_error` rather than leaving accepted work silently stranded. Operation scheduling uses attempt-scoped task names `operation:{id}:attempt:{attempt + 1}`; benign duplicate admission for the same attempt is ignored.

### 13.2 Generation lock ownership

The generation lock is reserved during acceptance and released by the scheduled worker in `finally`.

The worker owns exactly one durable `turn_id`. The lock must remain held through:

- processor preparation;
- model streaming;
- durable completion or failure persistence;
- final event publication setup.

A WebSocket or event subscriber has no ownership relationship to this lock.

### 13.3 Input assembly: intake

For an intake turn, the worker loads:

- stored editable profile;
- active intake session;
- full ordered intake transcript;
- current persisted `IntakeRecord`, defaulting to an empty typed record;
- latest persisted user message;
- previous assistant message when present;
- patient turn count.

Convert durable `Message` rows to processor-owned `TranscriptTurn` values in one pure helper.

Build `IntakeTurnInput`, then call:

1. `IntakeProcessor.prepare_turn()`;
2. `IntakeProcessor.stream_response(plan)`.

Accumulate the streamed assistant text while publishing token events.

### 13.4 Input assembly: therapy

For a therapy turn, load:

- editable profile;
- derived profile document;
- current immutable plan tied to the session;
- selected style definition;
- current session transcript including the accepted user message;
- current plan/session briefing;
- bounded recent closed-session summaries.

Build `TherapyTurnInput` with:

- `is_opening_turn=False`;
- `latest_user_message` equal to the final persisted user message;
- explicit current plan and style;
- deterministic context limits owned by the processor model.

Call `TherapyProcessor.stream_response()` once.

Do not load context inside the processor and do not rescan legacy tables.

### 13.5 Token publication

For every non-empty text chunk:

- append it to the in-memory response buffer;
- increment a per-turn sequence starting at 1;
- publish `ChatTokenGenerated` with session, turn, request, sequence, and text.

Do not persist chunks.

Do not normalize or merge chunks in a way that changes the provider output. Only validate that the final concatenated response contains non-whitespace text.

### 13.6 Ordinary completion

For incomplete intake and therapy turns:

1. acquire mutation lock after streaming;
2. generate assistant-message ID;
3. call `complete_chat_turn()` with final text;
4. include the merged intake record for intake turns;
5. assemble snapshot;
6. release lock;
7. publish `ChatTurnCompleted` with the persisted assistant message;
8. publish `SnapshotChanged`.

### 13.7 Intake completion

When `IntakeTurnPlan.completeness_complete` is true:

1. acquire mutation lock after streaming;
2. generate assistant-message and assessment-operation IDs;
3. call the atomic final-intake completion store method;
4. persist the assistant message and merged intake record;
5. close the intake session;
6. complete the chat turn;
7. create/reuse the assessment operation;
8. transition to `ASSESSMENT`;
9. increment revision once for the combined completion transaction;
10. assemble snapshot;
11. release lock;
12. publish `ChatTurnCompleted`;
13. publish `OperationChanged` for the pending assessment;
14. publish authoritative `SnapshotChanged`;
15. schedule assessment execution.

Use an explicit publish-then-schedule sequence in `_complete_final_intake()`. Do not route final intake through `_handoff_pending_operation()` — scheduling in that helper's `finally` would allow the assessment worker to publish `OperationChanged(RUNNING/COMPLETE)` before the authoritative `SnapshotChanged(ASSESSMENT)` event.

`_handoff_pending_operation()` is reserved for `end_session()` and `retry_operation()` only: publish pending `OperationChanged`, then schedule in `finally` even when publication fails or is cancelled.

There must be no externally observable committed state in which the intake turn is complete, the processor declared intake complete, but the application remains indefinitely in `INTAKE` without assessment work.

### 13.8 Chat failure

Catch `LLMError` and persist its stable `code` and `retryable` flag.

Catch unexpected ordinary exceptions at the worker boundary and persist:

- `error_code="internal_error"`;
- a safe non-sensitive message;
- `retryable=False` unless the exception is explicitly classified as transient infrastructure.

Flow:

1. acquire mutation lock;
2. mark the same `ChatTurn` failed;
3. assemble snapshot;
4. release lock;
5. publish `ChatTurnFailed`;
6. publish `SnapshotChanged`;
7. log the full exception server-side with correlation identifiers;
8. release the generation lock.

If cancellation is caused by shutdown, re-raise `CancelledError` and leave the durable turn pending for startup recovery.

## 14. Assessment operation execution

### 14.1 Scheduling

An assessment operation is scheduled after:

- final intake completion creates it;
- startup finds it `PENDING`;
- retry returns it to `PENDING`.

Prevent duplicate in-process scheduling by operation ID. Durable uniqueness remains the ultimate guard.

### 14.2 Start transition

Worker flow:

1. acquire mutation lock;
2. verify the operation still exists and is `PENDING`;
3. mark it `RUNNING`, incrementing attempt and revision;
4. assemble snapshot;
5. release lock;
6. publish `OperationChanged`.

### 14.3 Processor input

Load outside the mutation lock after the running transition:

- source intake session;
- persisted final `IntakeRecord`;
- ordered intake transcript;
- editable profile;
- immutable available style definitions.

Validate stored JSON into `IntakeRecord`. Build `AssessmentInput` and call `AssessmentProcessor.assess()` once.

### 14.4 Completion

On success:

1. serialize `AssessmentResult` with JSON-compatible typed dumping;
2. acquire mutation lock;
3. atomically store the result, mark operation `COMPLETE`, transition to `STYLE_SELECTION`, and increment revision;
4. assemble snapshot;
5. release lock;
6. publish `OperationChanged`.

The result must retain every style recommendation and its style-specific `initial_plan` material so `select_style()` needs no LLM call.

### 14.5 Failure

On `LLMError` or unexpected failure:

1. acquire mutation lock;
2. mark operation `FAILED` with safe code/message/retryability;
3. keep stage `ASSESSMENT`;
4. assemble snapshot;
5. release lock;
6. publish `OperationChanged`;
7. log diagnostics without prompt content by default.

## 15. Post-session operation execution

### 15.1 Scheduling and start

Use the same scheduling and `PENDING → RUNNING` mechanics as assessment. Do not create a hierarchy of reflection, memory, enrichment, and plan-update jobs.

### 15.2 Processor input

Load:

- source closed therapy session;
- complete ordered source transcript;
- editable profile;
- derived profile document;
- immutable plan used by the source session;
- selected style definition;
- prior session briefing from the current plan or previous closed session;
- bounded recent session summaries excluding the source session.

Validate the session-plan-style relationship before the LLM call.

Build one `PostSessionInput` and call `PostSessionProcessor.process()`.

### 15.3 Merge and no-op policy

After the typed result returns:

- call `merge_derived_profile()`;
- call `merge_plan_content()`;
- create `NewPlanRevision` only when the plan patch is not a no-op;
- generate a new plan ID only when a new revision is required;
- serialize `SessionBriefing` as validated JSON;
- pass the final merged artifacts to the store.

Do not persist raw patch objects as if they were final profile or plan documents.

### 15.4 Completion

Under the mutation lock, call `complete_post_session()` so one transaction:

- stores the session summary and briefing;
- updates the derived profile only when changed;
- inserts an immutable plan revision only when changed;
- updates the current plan pointer when needed;
- marks the operation complete with compact result metadata;
- transitions to `READY`;
- increments revision.

Then publish `OperationChanged` with the authoritative snapshot.

### 15.5 Failure

Persist the same stable error taxonomy and retryability rules as assessment. Leave stage `POST_SESSION`; do not partially persist analysis, briefing, profile changes, or plan changes.

A failure in either structured model call means the operation fails as a whole.

## 16. Application error model

### 16.1 Reuse and extend minimally

Retain current domain errors:

- `InvalidCommand`;
- `RevisionConflict`;
- `Busy`;
- `NotFound`;
- `InvariantViolation`;
- `PersistenceFailure`.

Add only errors needed to represent durable failed work to callers, for example:

```python
class StoredWorkFailure(DomainError):
    code: str
    retryable: bool
```

Separate chat and operation subclasses are acceptable when they improve Phase 5 mapping. Avoid an elaborate error-envelope hierarchy in the application layer.

### 16.2 Safe messages

Durable error messages and application exceptions must not contain:

- API keys;
- raw provider response bodies;
- complete prompts;
- complete therapeutic transcripts;
- stack traces;
- private SDK object representations.

Full diagnostic context belongs in structured logs.

## 17. Startup recovery

### 17.1 Startup sequence

Before accepting mutations:

1. initialize the store;
2. enter the task supervisor;
3. acquire the application mutation lock;
4. recover stale `RUNNING` operations to `PENDING`;
5. recover stale `PENDING` chat turns to retryable `FAILED`;
6. load the current pending operation, if any;
7. assemble the authoritative snapshot;
8. release the lock;
9. publish recovery-related durable events only after subscribers exist, or rely on the initial snapshot in Phase 5;
10. schedule the pending operation;
11. mark the application ready to accept commands.

Recovery must be idempotent. Calling it twice without intervening state changes must not increment revision twice or duplicate work.

### 17.2 Pending operations not previously running

Startup must schedule an already-`PENDING` operation even when it was never marked `RUNNING`. Recovery cannot be limited to rows changed by `recover_stale_operations()`.

### 17.3 Chat recovery

Stale pending turns become retryable `FAILED` while preserving:

- the user message;
- `session_id`;
- `client_message_id`;
- turn ID.

Resubmitting the same client message can reuse the durable turn and generate a new response without duplicating the user message.

### 17.4 Corruption policy

Recovery handles expected interrupted lifecycle states only. It must not silently invent missing sessions, plans, profiles, or operation results. Unexpected corruption raises a startup failure with a clear reset instruction.

## 18. Shutdown behavior

### 18.1 Stop acceptance first

Set an application-closing flag before waiting for tasks. New mutations and chat acceptance fail immediately with a stable busy/unavailable application error. Read-only snapshots remain available while resources are valid.

### 18.2 Graceful interval

Use one configured grace timeout. Do not add per-task shutdown policies.

During the interval:

- completed work persists normally;
- new work is rejected;
- event subscribers may continue receiving final durable notifications.

After the interval:

- cancel remaining supervised tasks;
- do not rewrite their durable state as success;
- release in-memory generation ownership;
- close the LLM client after task cancellation completes.

### 18.3 Restart guarantee

After forced shutdown:

- `RUNNING` operations are recoverable to `PENDING`;
- pending chat turns are recoverable to retryable `FAILED`;
- completed work is not rerun;
- user messages are not duplicated.

## 19. Structured logging and observability

Phase 4 retains concise boundary diagnostics without creating a telemetry framework.

Minimum command records:

- command name;
- request ID when supplied;
- stage and revision before acceptance;
- stage and revision after completion;
- durable entity IDs;
- status and latency;
- error code.

Minimum task records:

- task kind;
- turn or operation ID;
- source session ID;
- attempt;
- started/completed/failed/cancelled;
- latency;
- safe error code;
- correlated LLM call IDs when available.

Do not log prompt or transcript content by default.

Tracing observes application behavior; it never changes workflow state or appears in `AppSnapshot`.

## 20. Detailed implementation sequence

### Step 0 — Validate Phase 3 handoff and close command/store seams

Implement only the changes in Section 5.

Validation:

- Phase 2 and Phase 3 tests stay green;
- command models match application inputs, not store construction inputs;
- latest completed assessment can be loaded;
- final intake turn plus assessment creation is atomic;
- no schema migration is introduced.

### Step 1 — Implement application event models and `EventStream`

Add the typed event union, subscription cleanup, bounded subscriber behavior, token overflow policy, and ordering tests.

Validation:

- multiple subscribers receive events independently;
- unsubscribe removes resources;
- slow subscriber does not block publisher indefinitely;
- token events may be dropped only according to documented policy;
- no API/WebSocket imports.

### Step 2 — Implement `TaskSupervisor`

Add TaskGroup lifecycle, failure-isolating wrapper, duplicate task-name protection, task tracking, bounded shutdown, and cancellation tests.

Validation:

- one failed task does not cancel a sibling;
- cancellation propagates;
- shutdown leaves no active tasks;
- no detached `asyncio.create_task()` outside the supervisor.

### Step 3 — Implement composition-independent `TherapyApplication` skeleton

Add constructor dependencies, lifecycle flags, locks, `_run_store`, snapshot assembly, consistent reads, and read-only methods.

Validation:

- application tests use real store and no HTTP;
- snapshot commands derive from pure workflow facts;
- impossible durable combinations fail clearly;
- no legacy imports.

### Step 4 — Implement synchronous mutation use cases

Add:

- `update_profile`;
- `select_style`;
- `start_session`;
- `end_session`;
- `retry_operation`.

Validation:

- exact stage/revision behavior;
- style selection performs zero model calls;
- internal IDs are generated by the application;
- operation creation and retry schedule exactly one task;
- events follow durable commits.

### Step 5 — Implement chat acceptance and duplicate resolution

Add generation reservation, new-turn persistence, pending/complete/failed duplicate behavior, retry of the same turn, and scheduling handoff.

Validation:

- duplicate client message never duplicates the user message;
- duplicate resolution precedes revision validation;
- second distinct generation receives `Busy`;
- scheduling failure cannot strand silent accepted work;
- generation lock is always released.

### Step 6 — Implement intake and therapy generation workers

Add processor input assembly, transcript conversion, streaming, token events, final response validation, ordinary completion, failure persistence, and cancellation behavior.

Validation:

- processors receive typed explicit context;
- one accepted turn produces one response stream;
- partial failure never stores a completed assistant message;
- disconnecting/unsubscribing does not cancel generation;
- intake record persists only after validated processor preparation and completed response.

### Step 7 — Implement processor-driven intake completion

Wire final intake completion to the atomic store method, publish completion/operation events, and schedule assessment.

Validation:

- final intake record, assistant response, closed session, pending operation, stage, and revision commit atomically;
- assessment schedules once;
- failed assessment does not revert intake completion;
- no client command directly finishes intake.

### Step 8 — Implement assessment operation worker

Add running transition, typed input assembly, processor call, atomic completion, failure mapping, retry, and event publication.

Validation:

- result round-trips through strict `AssessmentResult` validation;
- style recommendations and initial plans remain durable;
- retry reuses operation ID and increments attempt;
- restart schedules pending assessment exactly once.

### Step 9 — Implement post-session operation worker

Add typed context assembly, processor call, pure merges, no-op detection, atomic completion, failure, retry, and event publication.

Validation:

- normal path uses the Phase 3 two-call processor only;
- no partial result persists after failure;
- no-op plan patch creates no plan revision;
- changed plan creates exactly one immutable revision;
- source session keeps the plan effective at session start;
- current profile points to the new plan only after atomic completion.

### Step 10 — Implement production composition and recovery lifecycle

Add settings-to-policy construction, concrete gateway creation, tracing, processor wiring, supervisor context, application recovery, bounded shutdown, and LLM client closure.

Validation:

- malformed settings fail before first request;
- one gateway instance serves all processors;
- store initializes once;
- startup recovery precedes readiness;
- pending operation schedules;
- LLM client closes once.

### Step 11 — Add full application scenarios and architectural validation

Run complete target workflows with real SQLite and `FakeLLM`.

Add a Phase 4 validation command, for example:

```text
make validate-refactor-phase-4
```

It should check imports and forbidden concepts, then run focused unit/integration suites.

## 21. Application integration scenario matrix

### 21.1 Fresh profile through style selection

1. initialize empty database;
2. update incomplete profile and remain `SETUP`;
3. update complete profile and enter `INTAKE` with one intake session;
4. submit multiple intake turns;
5. final processor decision completes intake;
6. assessment operation becomes pending/running/complete;
7. stage becomes `STYLE_SELECTION`;
8. select a style;
9. initial immutable plan is created from the stored matching recommendation;
10. stage becomes `READY`.

Assertions:

- no legacy components are called;
- no LLM call occurs during style selection;
- revisions increase only at documented durable points;
- available commands match every stage.

### 21.2 Therapy session through post-session completion

1. start therapy session;
2. submit first user message;
3. stream and complete assistant response;
4. submit another turn;
5. end the session;
6. post-session operation runs;
7. session summary and briefing persist;
8. derived profile merges;
9. optional plan revision persists;
10. stage returns to `READY`.

Assertions:

- session `plan_id` remains historical;
- profile current plan advances only when a new revision exists;
- one operation represents the complete post-session workflow.

### 21.3 Chat idempotency

Cover:

- duplicate while pending;
- duplicate after completion;
- duplicate after retryable failure;
- duplicate after permanent failure;
- duplicate with stale expected revision;
- distinct message while generation active.

Assertions:

- exactly one user message row per client message ID;
- same turn ID is reused;
- revision validation occurs after duplicate lookup;
- generation is scheduled at most once per pending attempt.

### 21.4 LLM failures

Cover each stable LLM error for chat and operations.

Assertions:

- durable error code and retryability are correct;
- stage does not advance on failure;
- partial chat output is not persisted;
- transient operation retry uses the same row;
- invalid output is not offered as retryable.

### 21.5 Restart recovery

Persist fixtures for:

- running assessment operation;
- running post-session operation;
- pending operation never started;
- pending chat turn;
- complete operation;
- complete chat turn.

Restart application context.

Assertions:

- running operations become pending and execute once;
- existing pending operation executes once;
- pending chat becomes retryable failed;
- completed work is untouched;
- revisions change only for actual recovery mutations.

### 21.6 Shutdown recovery

Block a fake stream and a fake structured call, initiate bounded shutdown, then restart.

Assertions:

- tasks are cancelled after grace timeout;
- no success is persisted;
- generation lock is released;
- running operation is recoverable;
- pending chat is recoverable;
- no task leaks.

### 21.7 Event semantics

Assert exact ordering for:

- chat acceptance;
- token stream;
- chat completion;
- chat failure;
- operation pending/running/complete;
- operation failure/retry;
- ordinary snapshot mutation.

Do not assert implementation-private queue or task internals beyond leak and ordering guarantees.

### 21.8 Concurrency

Use deterministic barriers to race:

- two profile mutations with one expected revision;
- two session starts;
- two distinct messages;
- end session versus message acceptance;
- operation retry versus duplicate retry;
- snapshot read during completion.

Expected outcomes are one success plus `state_conflict`, `busy`, or `invalid_command` according to the accepted workflow; never duplicate durable artifacts.

## 22. Unit-test boundaries

Use unit tests for:

- event subscription and overflow policy;
- supervisor isolation and shutdown;
- exception classification helper;
- transcript conversion;
- response non-empty validation;
- assessment recommendation lookup;
- application event construction;
- recent-summary selection;
- safe error-message normalization;
- strict JSON schema allowlist conversion for all four structured output models (`IntakeRecordPatch`, `AssessmentResult`, `SessionAnalysisResult`, `PostSessionResult`).

Integration tests added in round-2 remediation:

- `test_submit_message_cancel_during_store_call_drains_and_releases_lock`;
- `test_submit_message_cancel_after_turn_assigned_hands_off_worker`;
- `test_submit_message_cancel_during_accepted_event_publication`;
- `test_end_session_schedules_operation_when_publish_cancelled`;
- `test_retry_operation_schedules_operation_when_publish_fails`;
- `test_application_context_preflights_json_schema_models`;
- `test_application_context_rejects_unsupported_schema`;
- `test_full_intake_lifecycle_through_application`;
- split failed-chat retry matrix (four tests) including busy retry when another turn is `PENDING`.

Do not mock `SQLiteStore` in the main application workflow tests. The real temporary database is part of the Phase 4 contract.

## 23. Architectural validation

Add a focused script or test that rejects target-core imports of:

- `psychoanalyst_app` legacy runtime modules;
- Trio;
- Quart;
- Socket.IO;
- FastAPI or Starlette inside application/domain/phases/persistence/llm;
- LangChain outside the legacy package;
- service-container modules;
- legacy agents;
- legacy workflow/orchestration models;
- generated WebSocket constants;
- repository/facade layers over `SQLiteStore`;
- `asyncio.create_task` outside the approved supervisor implementation;
- provider SDKs outside `jung.llm`.

Also reject new target symbols matching concepts such as:

- `AgentResponse`;
- `ServiceContainer`;
- `AgentFactory`;
- `WorkflowEngine`;
- `JobManager`;
- `EventBus`;
- `RepositoryFactory`;
- `UserContext`.

The validator should permit ordinary domain words in documentation and tests; target runtime imports and definitions are the concern.

## 24. Validation commands

Recommended local validation sequence:

```bash
uv run ruff format --check src/jung tests/unit/jung tests/integration/jung
uv run ruff check src/jung tests/unit/jung tests/integration/jung
uv run pytest tests/unit/jung
uv run pytest tests/integration/jung
uv run python scripts/validate_refactor_phase_4.py
```

The Phase 4 PR should also run:

- Phase 3 gateway and processor tests;
- Phase 2 persistence/workflow tests;
- Phase 1 characterization tests proving the still-running legacy product was not changed;
- standard repository finalization once.

A real local model is not required for mandatory Phase 4 CI because Phase 3 already validated provider compatibility. A small optional Phase 4 local smoke may be used to verify full application wiring, but it must not replace deterministic `FakeLLM` integration tests.

## 25. Optional local application smoke

Provide only if it adds value beyond the Phase 3 processor smoke:

```text
make smoke-refactor-phase-4-local-llm
```

The smoke should:

- use a temporary database/data directory;
- run through application methods directly, not HTTP;
- complete profile setup;
- execute a short intake turn;
- use a prepared complete intake fixture if full intake duration is excessive;
- run assessment;
- select a style without an LLM call;
- start a therapy session and complete one user turn;
- close all resources;
- emit non-sensitive timing and lifecycle evidence.

It must not mutate the normal development database and must not become a hosted-CI requirement.

## 26. Risk register

### Risk: `TherapyApplication` becomes the new monolith-sized orchestrator

Mitigation:

- explicit use-case methods;
- pure context builders and conversion helpers;
- processors retain therapeutic behavior;
- store retains transactions;
- events and supervision remain separate small modules;
- split only cohesive independently testable logic.

### Risk: accepted chat work is lost between persistence and scheduling

Mitigation:

- reserve generation before acceptance;
- schedule immediately after commit;
- mark durable failure if scheduling cannot occur;
- startup recovers stale pending turns;
- deterministic failure-injection test at the scheduling seam.

### Risk: slow clients block model generation

Mitigation:

- bounded per-subscriber queues;
- non-blocking token fan-out;
- evict slow subscriptions rather than blocking durable work;
- authoritative reconnect snapshot.

### Risk: TaskGroup child failure cancels unrelated work

Mitigation:

- supervisor wrapper catches ordinary child exceptions;
- application workers persist failures;
- sibling-isolation test;
- `CancelledError` remains unmodified.

### Risk: lock scope expands around model calls

Mitigation:

- explicit review rule: no processor or gateway call while mutation lock is held;
- concurrency tests use blocked fake calls;
- application helpers separate context load, model work, and durable completion.

### Risk: separate store reads produce inconsistent snapshots

Mitigation:

- all in-process mutations use the same application lock;
- snapshot assembly uses that lock;
- add an aggregate store read only if a reproducible inconsistency remains.

### Risk: application recreates a job scheduler

Mitigation:

- one current durable operation;
- one supervisor;
- one scheduling helper by operation ID;
- no priorities, queues, cron, dependencies, children, or generic job API.

### Risk: permanent model errors are retried indefinitely

Mitigation:

- retryability comes from stable error classes;
- invalid structured output is non-retryable;
- retry command checks stored retryability;
- same operation row records attempts.

### Risk: final intake response and workflow transition split across commits

Mitigation:

- dedicated atomic final-intake completion transaction;
- integration test interrupts every boundary;
- no client-controlled `finish_intake` command.

### Risk: post-session partial results leak into durable state

Mitigation:

- processor returns only after both calls succeed;
- pure merges happen before transaction;
- one atomic completion method persists all artifacts;
- failure path stores no analysis/profile/plan artifacts.

### Risk: Phase 4 starts implementing Phase 5 transport concerns

Mitigation:

- application events are transport-neutral;
- no HTTP status codes or WebSocket payloads in target core;
- Phase 4 tests call application methods directly;
- import validator rejects FastAPI/Starlette in core modules.

### Risk: temporary legacy and target runtimes become permanently dual-maintained

Mitigation:

- target core never calls legacy code;
- Phase 4 changes no legacy runtime behavior;
- Phase 5 immediately exposes the target application;
- Phase 6 deletion remains mandatory after console cutover.

## 27. Review checklist

### Architecture

- [ ] One `TherapyApplication` owns target use cases.
- [ ] Dependencies are explicit and typed.
- [ ] No service locator, command bus, handler registry, or agent factory exists.
- [ ] Application, domain, phases, persistence, and LLM do not import API or client modules.
- [ ] Target core has no legacy runtime imports.
- [ ] SQLite access remains behind one concrete `SQLiteStore`.
- [ ] No generalized scheduler, queue, event bus, or repository hierarchy was introduced.

### Commands and workflow

- [ ] Application commands contain only caller-supplied intent.
- [ ] Internal entity IDs are generated by the application.
- [ ] `FinishIntake` is processor-driven and not a client command.
- [ ] Every command is validated against workflow facts.
- [ ] `available_commands` is derived, not stored.
- [ ] Revision conflicts preserve the accepted semantics.

### Concurrency

- [ ] Exactly one application mutation lock exists.
- [ ] Exactly one generation lock exists.
- [ ] No LLM call occurs while the mutation lock is held.
- [ ] Distinct concurrent chat receives `busy`.
- [ ] Accepted work is supervised.
- [ ] No detached task creation exists outside the supervisor.

### Chat lifecycle

- [ ] Duplicate client-message resolution precedes revision validation.
- [ ] User message and pending turn are durable before generation.
- [ ] Tokens are ephemeral.
- [ ] Completion persists assistant message and turn atomically.
- [ ] Final intake completion also creates assessment atomically.
- [ ] Partial failure does not persist an assistant completion.
- [ ] Retryable failed duplicate reuses the same turn and user message.
- [ ] Subscriber disconnect does not cancel generation.

### Operations

- [ ] Assessment and post-session use one `Operation` model.
- [ ] Creation is idempotent by kind/source session.
- [ ] Start increments attempt on the same row.
- [ ] Completion transactions persist all artifacts atomically.
- [ ] Failure never advances stage.
- [ ] Retry uses the same row.
- [ ] Startup schedules pending work exactly once.

### Recovery and shutdown

- [ ] Running operations recover to pending.
- [ ] Pending chat turns recover to retryable failed.
- [ ] Completed work is not rerun.
- [ ] Shutdown rejects new mutations first.
- [ ] Shutdown waits a bounded interval and cancels remaining tasks.
- [ ] Cancelled work remains recoverable.
- [ ] LLM client closes after supervised work stops.

### Events

- [ ] Event types are application-owned and transport-neutral.
- [ ] Token sequence is monotonic per turn.
- [ ] Durable events follow durable commits.
- [ ] Slow subscriber cannot block accepted work indefinitely.
- [ ] No replay or durable event log exists.

### Tests

- [ ] Main application scenarios use real temporary SQLite.
- [ ] All LLM behavior is deterministic through `FakeLLM`.
- [ ] Full setup-to-ready workflow passes.
- [ ] Full therapy-to-post-session workflow passes.
- [ ] Idempotency, concurrency, failures, retry, restart, and shutdown are covered.
- [ ] Phase 2 and Phase 3 tests remain green.
- [ ] Legacy characterization tests remain green.

## 28. Phase 4 exit criteria

All criteria are blocking:

- [ ] `TherapyApplication` exposes the target use cases without HTTP.
- [ ] Composition is explicit and contains no string-keyed lookup.
- [ ] One application mutation lock serializes durable state changes.
- [ ] One generation lock enforces one active chat generation.
- [ ] All accepted background work is owned by `TaskSupervisor`.
- [ ] Child task failure does not cancel unrelated work or application lifespan.
- [ ] `EventStream` fans out typed transport-neutral events.
- [ ] WebSocket disconnect/subscriber removal cannot cancel accepted generation.
- [ ] Chat acceptance is durable before model execution.
- [ ] Duplicate chat IDs never duplicate user messages.
- [ ] Chat completion and failure increment revision according to the workflow specification.
- [ ] Final intake completion and assessment-operation creation are atomic.
- [ ] Assessment runs through `AssessmentProcessor` and persists its typed result.
- [ ] Style selection uses stored assessment material and performs no LLM call.
- [ ] Therapy turns run through `TherapyProcessor` and persist only completed responses.
- [ ] Post-session work runs through one `PostSessionProcessor` operation.
- [ ] Post-session profile and plan updates use pure merge/no-op helpers.
- [ ] Assessment and post-session completion transactions are atomic.
- [ ] LLM failures map to durable stable codes and retryability.
- [ ] Operation retry reuses the same durable row.
- [ ] Startup recovers stale operations and chat turns before accepting commands.
- [ ] Pending operations are scheduled exactly once after startup.
- [ ] Bounded shutdown leaves interrupted work recoverable.
- [ ] Full application workflows pass with real `SQLiteStore` and `FakeLLM`.
- [ ] No target core module imports legacy orchestration, Trio, API, client, or provider-specific code outside `llm/`.
- [ ] The running legacy product remains unchanged pending Phase 5 cutover.

## 29. Definition of done

Phase 4 is done when a developer can implement Phase 5 without deciding:

- where commands are validated;
- who generates internal entity IDs;
- how snapshots and available commands are derived;
- how chat idempotency works;
- when generation ownership is acquired and released;
- how accepted chat survives disconnect;
- how tokens are distributed;
- how chat completion and failure become durable;
- how intake completion creates assessment work;
- how assessment and post-session operations are scheduled;
- how operation attempts, failures, and retries work;
- how processor inputs are assembled from persistence;
- how processor results are merged and committed;
- how startup recovers interrupted work;
- how shutdown handles accepted work;
- how application events map from durable lifecycle changes;
- how application behavior is tested without HTTP or a real LLM.

If Phase 5 needs to call processors, access `SQLiteStore` directly for mutations, own generation tasks, recreate workflow transitions, interpret legacy `AgentResponse`, or invent recovery semantics, Phase 4 is not complete.

## 30. Handoff to Phase 5

Phase 5 begins with:

- one fully tested `TherapyApplication`;
- one explicit production composition context;
- one supervised asyncio lifecycle;
- one transport-neutral application event union;
- one authoritative `AppSnapshot`;
- durable chat and operation lifecycle behavior;
- tested retry, restart, concurrency, and shutdown semantics;
- no dependency on the legacy runtime in the target core.

Phase 5 may then add:

- FastAPI lifespan around the production application context;
- HTTP request/response contracts and routes;
- WebSocket subscription and event mapping;
- transport error mapping;
- OpenAPI generation;
- `JungApiClient`;
- API-backed console adaptation;
- deterministic `/api/v1` workflow probes.

Phase 5 must remain an adapter phase. It must not become the owner of application workflow, persistence transactions, LLM execution, background tasks, or recovery.
