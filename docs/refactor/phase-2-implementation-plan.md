---
owner: engineering
status: proposed
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Detailed implementation plan for architecture refactor Phase 2
---

# Architecture Refactor Phase 2 Implementation Plan

## 1. Phase objective

Phase 2 builds the new single-user domain, workflow, and persistence foundation without replacing the running legacy application.

The phase must establish a small, final-form core that later phases can use directly:

- one set of target domain models;
- one persisted `Stage` and pure workflow policy;
- one concrete `SQLiteStore`;
- one fresh SQLite schema;
- durable revision, operation, plan, session, message, and chat-turn semantics;
- deterministic tests against temporary file-backed databases.

Phase 2 is not an adapter phase and must not create a second supported runtime. The current Trio application remains the only running product path until the later API cutover. New code is exercised only through unit and persistence integration tests.

The accepted decisions in the following documents are binding:

- [Target Architecture](target-architecture.md);
- [Architecture Refactor Roadmap](architecture-refactor-roadmap.md);
- [API v1 Contract](api-v1-contract.md);
- [Workflow Specification](workflow-specification.md);
- [ADR 0001](../adr/0001-single-user-api-modular-monolith.md);
- [ADR 0003](../adr/0003-workflow-stage-command-operation-model.md);
- [ADR 0004](../adr/0004-single-sqlite-store-and-schema-reset.md).

This plan translates those accepted decisions into Phase 2 implementation tasks. It must not redefine the public API, LLM behavior, or later application-runtime design.

## 2. Desired implementation philosophy

### 2.1 Build final-form foundations, not transitional wrappers

Phase 2 may run alongside the legacy code in the repository, but the new modules must already use their final concepts and names.

Do not introduce:

- `New*`, `V2*`, `Target*`, or `LegacyAdapter*` class names;
- compatibility aliases for old models;
- repository facades over `SQLiteStore`;
- a second service container;
- translation layers between old and new database rows;
- database migrations from the legacy schema;
- feature flags selecting old versus new persistence.

The new package is intentionally unused by the running legacy API until later phases. That isolation is preferable to a temporary bridge.

### 2.2 Prefer a few cohesive modules

The package shape in `target-architecture.md` is illustrative, not a file-creation checklist.

Start with the fewest modules that preserve dependency direction and readability. Split only when a module contains independently testable logic or materially different dependencies.

Recommended Phase 2 shape:

```text
src/jung/
├── __init__.py
├── domain/
│   ├── __init__.py
│   ├── models.py
│   ├── commands.py
│   └── errors.py
├── workflow.py
└── persistence/
    ├── __init__.py
    └── sqlite_store.py

tests/
├── unit/jung/
│   ├── test_domain_models.py
│   └── test_workflow.py
└── integration/jung/
    └── test_sqlite_store.py
```

Do not create empty placeholder modules for application, API, LLM, processors, event streaming, composition, or console code. Those belong to later phases.

The package may instead live under `src/psychoanalyst_app/` only if that avoids packaging friction without introducing legacy imports. Do not create a temporary namespace that must be renamed at cutover.

### 2.3 Use concrete persistence

Phase 2 implements one concrete `SQLiteStore`. Application tests in later phases will also use the real store with a temporary database.

Do not add:

- a generic repository interface;
- repository-per-table classes;
- a fake in-memory store;
- a connection-pool abstraction;
- an executor abstraction;
- a unit-of-work framework;
- an ORM.

A narrow project-owned store protocol may be introduced later only if a real second implementation becomes necessary. It is not required for current testability.

### 2.4 Test behavior and invariants, not implementation choreography

Tests should verify:

- persisted state;
- revision changes;
- atomicity;
- uniqueness and foreign-key constraints;
- recovery transformations;
- exact workflow availability and transitions.

Avoid mock-heavy assertions such as connection call order, SQL statement count, helper invocation order, or private method calls.

### 2.5 Preserve the legacy runtime without importing it

The new package must not import:

- `psychoanalyst_app.orchestration`;
- `psychoanalyst_app.container`;
- `psychoanalyst_app.services.trio_db_service`;
- legacy API DTOs or routes;
- Trio;
- LangChain or provider SDKs;
- console modules.

Port durable logic deliberately. Do not copy entire legacy models, status enums, or repository APIs.

## 3. Scope

### 3.1 In scope

Phase 2 includes:

- the final single-user domain model;
- typed commands and domain errors needed by the new core;
- pure workflow command-availability and transition policy;
- the seven-table SQLite schema accepted in ADR 0004;
- `SQLiteStore` initialization, reads, and atomic write operations;
- profile persistence;
- session persistence;
- normalized message persistence;
- immutable plan revisions and lineage;
- assessment and post-session `Operation` persistence;
- durable `ChatTurn` persistence and `client_message_id` uniqueness;
- monotonic snapshot revision handling;
- restart-recovery primitives for operations and chat turns;
- explicit database reset support;
- temporary-database tests;
- import-boundary validation for the new package.

### 3.2 Out of scope

Phase 2 must not implement:

- LLM calls or provider adapters;
- `FakeLLM`;
- prompts or phase processors;
- `TherapyApplication`;
- application task supervision;
- `EventStream`;
- HTTP or WebSocket routes;
- FastAPI or Uvicorn startup;
- console changes;
- OpenAPI generation;
- API error mapping;
- real token streaming;
- background task execution;
- migration from the legacy database;
- synchronization between old and new databases;
- deletion of legacy runtime code;
- production selection of the new package.

The store may expose atomic methods that later application code will call, but Phase 2 must not build a partial application service around them.

## 4. Entry conditions

Phase 2 starts only after:

- Phase 1 is merged or otherwise treated as the accepted repository baseline;
- all Phase 1 characterization tests remain green;
- the accepted API and workflow contracts have no unresolved foundation-level questions;
- the Phase 2 branch starts from current `main`;
- no unrelated product feature work is mixed into the branch.

Recommended branch:

```text
refactor/phase-2-domain-persistence
```

A stacked branch is acceptable if the repository workflow deliberately keeps Phase 1 unmerged, but the Phase 2 diff must still be reviewable independently from the Phase 1 evidence changes.

## 5. Phase deliverables

Phase 2 should produce:

```text
src/jung/
├── domain/
│   ├── models.py
│   ├── commands.py
│   └── errors.py
├── workflow.py
└── persistence/
    └── sqlite_store.py

tests/unit/jung/
├── test_domain_models.py
└── test_workflow.py

tests/integration/jung/
└── test_sqlite_store.py
```

Optional additions are acceptable only when they reduce complexity:

- `persistence/schema.sql` if keeping SQL separate is clearer than one schema string;
- a small `testing.py` fixture helper if used by several later test modules;
- one import-boundary test or architecture rule.

Do not create speculative files for future phases.

## 6. Workstream A — Domain models

### 6.1 Model conventions

Use project-owned Pydantic v2 models and `StrEnum` values unless a standard-library dataclass is materially simpler for a specific internal value object.

Rules:

- domain models contain no database connection or SQL behavior;
- domain models contain no HTTP status codes or wire-event names;
- domain models contain no legacy `user_id`;
- immutable historical records should be frozen where practical;
- timestamps are timezone-aware UTC values;
- UUIDs are generated in application/store acceptance methods, not hidden in model defaults when deterministic tests need control;
- JSON documents are represented as validated Python mappings at the domain boundary and serialized only inside the store.

### 6.2 Required enums

Implement exactly the target concepts needed by Phase 2:

```text
Stage
CommandName
SessionKind
MessageRole
OperationKind
OperationStatus
ChatTurnStatus
```

Required values:

```text
Stage:
  setup
  intake
  assessment
  style_selection
  ready
  therapy
  post_session

CommandName:
  update_profile
  send_message
  finish_intake
  select_style
  start_session
  end_session
  retry_operation

SessionKind:
  intake
  therapy

MessageRole:
  user
  assistant
  system

OperationKind:
  assessment
  post_session

OperationStatus:
  pending
  running
  complete
  failed

ChatTurnStatus:
  pending
  complete
  failed
```

Do not port legacy user-status, workflow-event, next-action, job-status, agent-type, or manager enums.

### 6.3 Required domain entities

Implement the minimum final entities needed by the store and workflow:

#### `Profile`

User-editable identity and preference fields only:

- `name`;
- `primary_language`;
- optional `date_of_birth`;
- optional `notes`.

Derived therapeutic profile data is separate backend-owned JSON and must not be merged into this editable model.

#### `StoredProfile`

Persistence view containing:

- editable `Profile`;
- optional backend-owned derived-profile document;
- optional `current_plan_id`;
- creation and update timestamps.

Avoid exposing internal derived-profile fields through the future `PUT /profile` command.

#### `Session`

- `id`;
- `kind`;
- optional `plan_id` effective at session start;
- `started_at`;
- optional `ended_at`;
- optional summary;
- optional canonical briefing document.

The closed session is the canonical owner of the session briefing.

#### `Message`

- `id`;
- `session_id`;
- monotonic `sequence` within the session;
- `role`;
- `content`;
- `created_at`.

`client_message_id` is not a durable column on `messages`; it is owned by `chat_turns` and exposed on message read models via join.

#### `Plan`

Use the accepted `PlanDetail` semantics:

- `id`;
- monotonic `version`;
- selected style;
- focus;
- themes;
- goals;
- non-empty current progress;
- planned interventions;
- revision recommendations;
- optional immutable session-briefing snapshot;
- optional source session;
- optional superseded-plan link;
- creation timestamp.

A plan revision is immutable after insertion.

#### `Operation`

- `id`;
- kind;
- status;
- source session;
- attempt number;
- optional validated result document;
- optional stable error information;
- retryability;
- lifecycle timestamps.

Phase 2 stores result documents as validated JSON mappings. Phase 3 will define typed assessment and post-session result models.

#### `ChatTurn`

- `id`;
- session;
- `client_message_id`;
- status;
- persisted user-message ID;
- optional persisted assistant-message ID;
- optional stable error information;
- retryability;
- lifecycle timestamps.

#### `AppState`

Persist only authoritative singleton workflow fields:

- `stage`;
- monotonic `revision`;
- creation and update timestamps.

Do not duplicate active session, operation, plan, or chat-turn identifiers in `app_state` when they can be derived unambiguously through constrained rows.

#### `AppSnapshot`

A derived read model containing:

- revision;
- stage;
- profile completeness;
- selected style;
- active session;
- current operation;
- active chat turn;
- available commands.

`available_commands` comes from `workflow.py`, not from persisted JSON.

### 6.4 Commands

Create typed command models for the accepted command set, but include only fields that belong to domain/application semantics.

At minimum:

- `UpdateProfile`;
- `FinishIntake` as an internal processor-triggered command/result transition;
- `SelectStyle`;
- `StartSession`;
- `EndSession`;
- `SendMessage`;
- `RetryOperation`.

Every external mutation command carries `expected_revision`. `SendMessage` also carries:

- `session_id`;
- `client_message_id`;
- ephemeral `request_id` only if it is useful outside the API adapter;
- content.

Prefer keeping `request_id` at the API/application edge rather than persisting it or making it part of domain identity.

### 6.5 Domain errors

Define a small internal taxonomy that later API code can map:

- `InvalidCommand`;
- `RevisionConflict`;
- `Busy`;
- `NotFound`;
- `InvariantViolation`;
- `PersistenceFailure` only where a stable wrapper adds value.

Errors must not contain HTTP response objects, status codes, WebSocket payloads, or provider diagnostics.

### 6.6 Domain acceptance criteria

- no `user_id` exists in new entities, commands, tables, or method signatures;
- no legacy status/event/action types are imported;
- plans are immutable value objects;
- result/briefing JSON is validated as a mapping and not treated as arbitrary serialized Python;
- timestamp and UUID handling is deterministic in tests;
- models do not know about SQLite rows or HTTP DTOs.

## 7. Workstream B — Pure workflow policy

### 7.1 Purpose

`workflow.py` implements the accepted command matrix and stage transitions as pure functions. It is not a persisted workflow engine and does not emit events.

Recommended public functions:

```python
def available_commands(facts: WorkflowFacts) -> frozenset[CommandName]: ...

def require_command_allowed(
    command: CommandName,
    facts: WorkflowFacts,
) -> None: ...

def stage_after_profile_update(
    current: Stage,
    *,
    profile_complete: bool,
) -> Stage: ...

def stage_after_intake_completion(current: Stage) -> Stage: ...

def stage_after_operation_completion(
    current: Stage,
    kind: OperationKind,
) -> Stage: ...

def stage_after_style_selection(current: Stage) -> Stage: ...

def stage_after_session_start(current: Stage) -> Stage: ...

def stage_after_session_end(current: Stage) -> Stage: ...
```

Equivalent names are acceptable. The key constraint is to avoid a generic state-machine framework, persisted event log, or second workflow representation.

### 7.2 `WorkflowFacts`

Use one compact input object containing only facts needed to derive commands:

- stage;
- profile completeness;
- whether an active session exists;
- current operation status/kind;
- active chat-turn status.

Do not pass store objects or database rows into workflow functions.

### 7.3 Required policy behavior

Implement the accepted matrix exactly:

- `SETUP`: `update_profile` only;
- `INTAKE`: `update_profile`, `send_message`; `finish_intake` is processor-only;
- `ASSESSMENT`: only retry of a failed assessment operation;
- `STYLE_SELECTION`: `select_style` only;
- `READY`: `start_session` only;
- `THERAPY`: `send_message` and end of the active session;
- `POST_SESSION`: only retry of a failed post-session operation.

Additional rules:

- a distinct chat command is unavailable while another turn is pending;
- a same-key chat retry is resolved by store/application idempotency before normal availability checking;
- failed operations do not advance stage;
- operation completion advances only the matching stage and operation kind;
- invalid combinations raise `InvalidCommand` or `InvariantViolation`;
- workflow functions never mutate objects or persist state.

### 7.4 Workflow tests

Use table-driven tests for:

- all stage/command combinations;
- conditional retry availability;
- active-generation restrictions;
- every valid stage transition;
- invalid transition rejection;
- failed operation preserving stage.

Avoid one test function per enum value when a parameterized matrix is clearer.

## 8. Workstream C — SQLite schema

### 8.1 General rules

The schema is created fresh. There is no Alembic migration and no compatibility view.

On initialization:

- enable WAL mode;
- enable foreign keys on every connection;
- configure a bounded busy timeout;
- create schema in one transaction;
- seed one `app_state` row at `stage=setup`, `revision=0`;
- schema creation is idempotent for an already initialized database.

Every write method:

- opens a short-lived connection;
- starts `BEGIN IMMEDIATE`;
- performs the complete use-case transaction;
- commits or rolls back;
- closes the connection.

No connection may be retained on the store instance or shared across threads.

### 8.2 `app_state`

Minimum columns:

```text
singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1)
stage TEXT NOT NULL
revision INTEGER NOT NULL CHECK (revision >= 0)
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

The row stores only stage and revision. Active entities are derived from their own constrained tables.

### 8.3 `profile`

Minimum columns:

```text
singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1)
name TEXT NOT NULL
primary_language TEXT NOT NULL
date_of_birth TEXT NULL
notes TEXT NULL
derived_profile_json TEXT NULL
current_plan_id TEXT NULL
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

`current_plan_id` references `plans(id)` and is updated only in the same transaction that creates the relevant plan revision.

### 8.4 `sessions`

Minimum columns:

```text
id TEXT PRIMARY KEY
kind TEXT NOT NULL
plan_id TEXT NULL
started_at TEXT NOT NULL
ended_at TEXT NULL
summary TEXT NULL
briefing_json TEXT NULL
```

Constraints:

- `kind` is `intake` or `therapy`;
- `plan_id` references `plans(id)`;
- at most one session may have `ended_at IS NULL`;
- a therapy session records the plan effective at start and never changes that historical link.

Use a partial unique index to enforce one open session.

### 8.5 `messages`

Minimum columns:

```text
id TEXT PRIMARY KEY
session_id TEXT NOT NULL
sequence INTEGER NOT NULL
role TEXT NOT NULL
content TEXT NOT NULL
created_at TEXT NOT NULL
```

Constraints:

- foreign key to session with explicit deletion policy;
- unique `(session_id, sequence)`;
- `sequence >= 1`;
- role in the accepted role set.

`client_message_id` is **not** stored on `messages`. The canonical durable idempotency key lives on `chat_turns.client_message_id`; message read models derive it through `chat_turns.user_message_id`.

Do not store a serialized transcript blob.

### 8.6 `plans`

Minimum columns:

```text
id TEXT PRIMARY KEY
version INTEGER NOT NULL UNIQUE
selected_style TEXT NOT NULL
focus TEXT NOT NULL
themes_json TEXT NOT NULL
goals_json TEXT NOT NULL
current_progress TEXT NOT NULL
planned_interventions_json TEXT NOT NULL
revision_recommendations_json TEXT NOT NULL
session_briefing_json TEXT NULL
source_session_id TEXT NULL
supersedes_plan_id TEXT NULL
created_at TEXT NOT NULL
```

Constraints:

- non-empty focus and current progress;
- foreign keys to source session and superseded plan;
- at most one successor for a superseded plan;
- plan rows are insert-only;
- source session plus plan revision semantics prevent duplicate post-session plan creation.

A uniqueness constraint on `source_session_id` is appropriate if every session can create at most one plan revision. The initial plan may use the intake session as its source if that remains consistent with the accepted domain model.

### 8.7 `operations`

Minimum columns:

```text
id TEXT PRIMARY KEY
kind TEXT NOT NULL
status TEXT NOT NULL
source_session_id TEXT NOT NULL
attempt INTEGER NOT NULL
result_json TEXT NULL
error_code TEXT NULL
error_message TEXT NULL
retryable INTEGER NOT NULL
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
started_at TEXT NULL
completed_at TEXT NULL
```

Constraints:

- unique `(kind, source_session_id)`;
- attempt starts at zero or one and follows one documented convention;
- error fields are consistent with failed status;
- result exists only for complete operations;
- only one operation may be current in `pending`, `running`, or `failed` status;
- retry updates the same row rather than inserting another operation.

Use a partial unique index for the one-current-operation invariant.

### 8.8 `chat_turns`

Minimum columns:

```text
id TEXT PRIMARY KEY
session_id TEXT NOT NULL
client_message_id TEXT NOT NULL
status TEXT NOT NULL
user_message_id TEXT NOT NULL
assistant_message_id TEXT NULL
error_code TEXT NULL
error_message TEXT NULL
retryable INTEGER NOT NULL
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
completed_at TEXT NULL
```

Constraints:

- unique `(session_id, client_message_id)`;
- user and assistant message foreign keys;
- assistant message exists only for complete turns;
- failed turns retain the user message;
- at most one turn may be pending at a time;
- completed turns are immutable;
- retry reuses the same turn and never inserts a second user message.

Use a partial unique index for one pending chat turn.

### 8.9 JSON handling

Centralize JSON serialization in small private store helpers:

- canonical UTF-8 JSON;
- stable key ordering where useful for deterministic tests;
- explicit decode errors;
- mappings/lists only, never pickle or arbitrary Python serialization.

Do not introduce a generic document-store abstraction.

## 9. Workstream D — `SQLiteStore`

### 9.1 Construction

Recommended construction:

```python
store = SQLiteStore(database_path)
store.initialize()
```

The store holds only configuration such as the path and timeout. It does not hold an open connection.

### 9.2 Read operations

Implement cohesive reads needed by later phases:

- `get_app_state()`;
- `get_profile()`;
- `get_current_plan()`;
- `list_sessions()`;
- `get_session(session_id)`;
- `list_messages(session_id)`;
- `get_current_operation()`;
- `get_operation(operation_id)`;
- `get_chat_turn(turn_id)`;
- `get_chat_turn_by_client_id(session_id, client_message_id)`;
- `get_active_session()`;
- `get_active_chat_turn()`;
- `load_snapshot_facts()` or an equivalently small aggregate read.

Avoid both extremes:

- no repository-per-table object graph;
- no single `execute(sql, parameters)` escape hatch exposed to callers.

### 9.3 Revision handling

Every durable mutation increments `app_state.revision` in the same transaction.

Implement one private helper that:

1. loads the current revision;
2. optionally compares `expected_revision`;
3. raises `RevisionConflict` before any write when stale;
4. applies the mutation;
5. increments revision exactly once for that committed mutation.

Do not let callers manually update revision columns.

Store methods that update internal lifecycle status without an external expected revision—such as operation start or chat completion—still increment revision because they change durable snapshot-visible state.

### 9.4 Atomic write operations

Implement use-case-level methods rather than CRUD wrappers.

Recommended Phase 2 methods:

#### Profile

- replace the editable profile under expected revision;
- transition `SETUP` to `INTAKE` when the supplied profile is complete;
- retain backend-derived profile JSON and current-plan linkage.

#### Intake and assessment operation

- append intake user/assistant messages;
- atomically finish intake and create/reuse the assessment operation;
- mark an operation running;
- atomically complete assessment by storing its result document, marking the operation complete, and advancing to `STYLE_SELECTION`;
- fail the operation without advancing stage;
- retry the same failed operation row.

Phase 2 uses fixture result JSON. Phase 3 supplies typed processor results.

#### Style and initial plan

- atomically validate the completed assessment result exists;
- create the first immutable plan;
- store selected style within the plan;
- point the profile to the plan;
- advance `STYLE_SELECTION` to `READY`;
- increment revision once.

There is no separate initial-plan operation.

#### Session lifecycle

- start one therapy session from `READY` using the current plan;
- preserve the session-to-plan link;
- end the active therapy session;
- atomically create/reuse the post-session operation;
- advance to `POST_SESSION`.

#### Post-session completion

In one transaction:

- persist session summary and canonical briefing;
- apply the derived-profile document update;
- insert one immutable plan revision;
- copy the briefing snapshot into that plan when present;
- link the old and new plans;
- update profile current-plan pointer;
- store operation result;
- mark operation complete;
- advance to `READY`;
- increment revision once.

#### Chat acceptance

In one transaction:

1. look up `(session_id, client_message_id)` before revision validation;
2. if found, return the existing turn outcome without inserting another user message;
3. otherwise validate expected revision and current session;
4. insert one user message using the next sequence;
5. insert one pending chat turn;
6. increment revision once.

#### Chat completion

In one transaction:

- append assistant message at the next sequence;
- mark the same turn complete;
- link assistant message;
- increment revision once.

#### Chat failure and retry state

- post-acceptance failure marks the same turn failed and increments revision;
- a retryable failed turn may return to pending without another user message;
- permanent failed turns remain queryable and cannot be regenerated;
- Phase 2 does not generate or stream text.

### 9.5 Transaction-failure behavior

For every multi-table method, tests must demonstrate that an exception leaves:

- revision unchanged;
- stage unchanged;
- no partial messages;
- no partial plan;
- no partially completed operation;
- no broken current-plan pointer.

Prefer natural constraint failures or a narrow internal test fault hook over mocking each SQL call.

## 10. Workstream E — Initialization, reset, and recovery primitives

### 10.1 Initialization

`initialize()` must:

- create parent directory when appropriate;
- configure database pragmas;
- create all tables and indexes;
- seed singleton state exactly once;
- be safe to call repeatedly;
- reject a database with an incompatible unexpected schema rather than silently migrating it.

A simple schema-version constant may be stored if it helps identify incompatible databases. Do not build a migration framework.

### 10.2 Reset

Provide an explicit development/test reset command or function that:

- refuses dangerous paths where practical;
- closes no shared connection because none exists;
- removes or archives the selected SQLite database and WAL/SHM files;
- recreates a clean schema;
- returns a fresh `SETUP`, revision-zero state.

Reset behavior is environment-based and never user-based.

### 10.3 Operation recovery

Implement one synchronous recovery transaction for startup use in Phase 4:

- stale `RUNNING` operations become `PENDING`;
- attempt count is not incremented until an actual retry starts;
- completed operations remain unchanged;
- failed operations remain failed until explicit retry;
- revision increments once if any operation changes.

Return the operations that should later be scheduled by the application supervisor.

### 10.4 Chat-turn recovery

Implement one synchronous recovery transaction:

- stale pending chat turns become failed and retryable;
- user messages remain durable;
- no assistant message is fabricated;
- completed and already-failed turns remain unchanged;
- revision increments once if any turn changes.

The application will later decide when to invoke regeneration.

### 10.5 Recovery acceptance criteria

- recovery methods are idempotent;
- a second recovery call makes no further changes;
- completed records are never rerun or altered;
- recovery does not require API, asyncio, or task-supervisor code.

## 11. Workstream F — Testing strategy

### 11.1 Test database policy

Use temporary file-backed SQLite databases, not `:memory:`.

This is required to exercise:

- connection-per-operation behavior;
- WAL initialization;
- foreign keys on new connections;
- busy timeout;
- restart/reopen semantics;
- WAL/SHM reset behavior.

A fixture should return a fresh database path and initialized concrete store. Keep it small and local to the new test package.

### 11.2 Unit tests

Use approximately 8–12 focused unit tests, primarily table-driven:

- domain validation and immutability;
- command model validation;
- complete command-availability matrix;
- valid stage transitions;
- invalid stage transitions;
- operation completion routing;
- retry availability;
- active-generation restrictions.

Do not test Pydantic or enum behavior that is already guaranteed by the library unless project-specific validation exists.

### 11.3 Store integration tests

Use approximately 15–22 scenario-oriented tests. Prefer one test per invariant or transaction family rather than one per SQL method.

Required scenarios:

1. schema initialization and idempotent reopen;
2. fresh `SETUP`, revision-zero state;
3. foreign keys, WAL, and busy timeout on actual connections;
4. profile replacement and `SETUP → INTAKE`;
5. stale revision rejects without mutation;
6. exactly one open session;
7. normalized message ordering and sequence uniqueness;
8. chat acceptance creates one user message and one turn;
9. duplicate `client_message_id` returns the existing turn before revision validation;
10. chat completion appends one assistant message;
11. chat failure preserves user message;
12. immutable initial plan and profile current-plan pointer;
13. operation uniqueness by kind/source session;
14. operation failure leaves stage unchanged;
15. retry reuses the operation row;
16. post-session completion atomically creates one plan revision and preserves historical session linkage;
17. plan briefing snapshot matches the canonical session briefing at creation;
18. transaction rollback prevents partial plan/profile/operation writes;
19. startup operation recovery is idempotent;
20. startup chat-turn recovery is idempotent;
21. reset recreates a clean database;
22. close and reopen reconstructs all durable state.

The exact number may be lower if parameterization keeps scenarios readable. Do not increase the suite merely to hit a number.

### 11.4 What not to test in Phase 2

Do not add tests for:

- HTTP payloads;
- WebSocket events;
- real token streaming;
- LLM retries;
- prompt output;
- task-supervisor cancellation;
- console behavior;
- legacy/new database synchronization;
- SQL helper call order;
- private connection helper implementation.

### 11.5 Existing test treatment

Do not delete legacy tests in Phase 2 because the legacy runtime still runs.

Port only durable logic that now has a real target home, such as:

- profile completeness rules;
- plan-lineage invariants;
- profile/plan merge behavior that remains part of the accepted domain;
- structured JSON validation helpers that are genuinely persistence-related.

Do not copy tests for:

- service-container wiring;
- Trio orchestration;
- legacy repositories;
- user-scoped routes;
- workflow event emission;
- job trees.

Record any newly ported or superseded areas in `test-treatment-inventory.md`, but do not mark legacy tests for deletion until their production component is removed.

## 12. Workstream G — Import and architecture boundaries

Add one lightweight automated rule for the new package.

The rule should fail if Phase 2 code imports:

```text
psychoanalyst_app.api
psychoanalyst_app.container
psychoanalyst_app.orchestration
psychoanalyst_app.services
console-ui modules
trio
quart
quart_trio
langchain
openai
fastapi
```

Standard-library `sqlite3`, Pydantic, and project-owned new-domain modules are allowed.

Do not create a second large architecture-validation framework. Extend the existing checker if simple; otherwise use one focused test that parses imports with AST.

Dependency direction:

```text
domain imports standard library and Pydantic only
workflow imports domain only
persistence imports domain and workflow result types only when required
legacy runtime imports nothing from the new package in Phase 2
```

Ideally `persistence` does not import workflow policy at all; it persists stages and domain records, while later application code coordinates policy and transaction selection.

## 13. Implementation sequence

### Step 1 — Create the minimal package and test roots

Add only the modules required for Phase 2.

Validation:

- package imports cleanly;
- no legacy imports;
- no production runtime registration or wiring changes;
- Phase 1 characterization remains green.

### Step 2 — Implement domain models and errors

Add enums, entities, commands, state/snapshot models, and internal errors.

Validation:

- domain unit tests;
- no wire or database concerns in models;
- no `user_id`.

### Step 3 — Implement pure workflow policy

Implement the command matrix and transition functions.

Validation:

- table-driven matrix tests;
- all accepted transitions covered;
- invalid combinations rejected;
- no generic workflow engine or event model.

### Step 4 — Implement schema and connection lifecycle

Add `SQLiteStore`, initialization, connection setup, schema creation, and base reads.

Validation:

- file-backed database tests;
- WAL and foreign-key checks;
- repeated initialization;
- fresh state.

### Step 5 — Implement profile, session, and message transactions

Add profile replacement, open-session constraint, session reads, normalized message insertion, and sequence allocation.

Validation:

- revision conflicts;
- one active session;
- ordered transcript reconstruction;
- rollback on failure.

### Step 6 — Implement plans and operation transactions

Add immutable plans, lineage, profile current-plan linkage, operation lifecycle, assessment completion, style/initial-plan transaction, session ending, and post-session completion.

Validation:

- operation uniqueness;
- failed operation does not advance stage;
- one plan revision per source session;
- historical plan link remains stable;
- atomic completion tests.

### Step 7 — Implement chat-turn persistence

Add acceptance, duplicate lookup, completion, failure, and retry-state persistence.

Validation:

- duplicate client ID is resolved before revision validation;
- no duplicate user message;
- assistant sequence and linkage;
- one pending turn;
- failed retry reuses the row.

### Step 8 — Implement reset and recovery primitives

Add explicit reset, stale-operation recovery, and stale-chat-turn recovery.

Validation:

- recovery idempotency;
- reopen/restart tests;
- clean reset state;
- no application/task code.

### Step 9 — Add focused phase validation

Add or extend Make targets:

```text
phase-2-test
validate-refactor-phase-2
```

Recommended composition:

```text
phase-2-test:
  new domain/workflow unit tests
  new SQLiteStore integration tests

validate-refactor-phase-2:
  lint/type checks for new package
  import-boundary check
  phase-2-test
```

Do not duplicate the full standard finalization suite inside these targets. CI should run normal finalization once, then add Phase 2-specific checks only.

### Step 10 — Review and handoff

Update:

- deletion inventory status where concrete target replacements now exist;
- test-treatment inventory for genuinely ported tests;
- baseline metrics for the new package and tests;
- this plan's exit checklist.

Do not mark legacy components deleted or deprecated yet.

## 14. Suggested commit structure

Keep commits narrow and executable.

### Commit 1

```text
feat(domain): add target single-user models and workflow policy
```

Includes:

- domain models;
- commands/errors;
- workflow functions;
- unit tests.

### Commit 2

```text
feat(persistence): add target SQLite schema and store foundation
```

Includes:

- initialization;
- connection lifecycle;
- schema;
- base reads;
- schema tests.

### Commit 3

```text
feat(persistence): add profile session message and plan transactions
```

Includes:

- profile;
- sessions;
- messages;
- initial plan;
- revision behavior;
- integration tests.

### Commit 4

```text
feat(persistence): add operation and chat-turn lifecycle
```

Includes:

- operations;
- chat turns;
- atomic assessment/post-session completion;
- idempotency tests.

### Commit 5

```text
feat(persistence): add reset recovery and Phase 2 validation
```

Includes:

- recovery primitives;
- reset;
- import checks;
- Make/CI Phase 2 targets;
- inventory and metric updates.

Fewer commits are acceptable when changes remain reviewable. Do not split every model or table into its own commit.

## 15. CI and local validation

### 15.1 Fast local loop

Recommended:

```bash
uv run pytest tests/unit/jung tests/integration/jung/test_sqlite_store.py -q
uv run ruff check src/jung tests/unit/jung tests/integration/jung
```

If the repository still requires Docker for dependency consistency, keep one temporary Docker wrapper rather than duplicating native and Docker-specific test logic.

### 15.2 PR validation

The Phase 2 PR should run:

1. standard repository finalization once;
2. Phase 2 import-boundary validation;
3. Phase 2 domain/workflow/store tests;
4. Phase 1 characterization smoke to prove the legacy runtime was not disturbed.

Full legacy characterization may remain in the existing release-candidate path rather than being repeated in a separate Phase 2 job.

### 15.3 No new permanent governance subsystem

Do not add a large Phase 2 document parser or duplicate contract validator. Code tests and import rules provide the relevant evidence in this phase.

## 16. Review checklist

Reviewers should verify:

### Architecture

- [ ] New code uses final target names rather than transitional aliases.
- [ ] New code is not imported by the running legacy path.
- [ ] No legacy runtime dependency enters `src/jung`.
- [ ] No second DI container, repository hierarchy, or workflow engine appears.
- [ ] The store owns connection and transaction mechanics.
- [ ] Workflow policy remains pure.

### Domain

- [ ] No `user_id` exists.
- [ ] Editable profile data is distinct from derived therapeutic documents.
- [ ] Plans are immutable revisions.
- [ ] Session-to-plan historical linkage is preserved.
- [ ] Operation and chat-turn concepts remain separate.

### Persistence

- [ ] Schema contains exactly the accepted seven tables unless an ADR supersedes the decision.
- [ ] All connections enable foreign keys and busy timeout.
- [ ] WAL is initialized.
- [ ] Multi-table writes use `BEGIN IMMEDIATE` and one transaction.
- [ ] Every durable mutation increments revision exactly once.
- [ ] Failed transactions do not partially mutate state.
- [ ] No migration or compatibility code is introduced.

### Tests

- [ ] Tests use temporary file-backed databases.
- [ ] Tests assert outcomes and invariants rather than mocks/call order.
- [ ] Command matrix and transition behavior are table-driven.
- [ ] Idempotency and recovery paths are covered.
- [ ] Test count remains proportional and no scenario DSL/framework is introduced.
- [ ] Legacy characterization remains green.

## 17. Phase 2 exit criteria

All criteria are blocking:

- [ ] Minimal final-form target package exists.
- [ ] `Stage`, commands, domain entities, and errors are implemented.
- [ ] Command availability matches the accepted workflow specification.
- [ ] All valid transitions are implemented as pure policy.
- [ ] Invalid transitions fail deterministically.
- [ ] Fresh SQLite schema contains the accepted seven tables and constraints.
- [ ] `SQLiteStore` uses short-lived connections and explicit SQL.
- [ ] Initialization is idempotent and reset recreates a clean database.
- [ ] Profile persistence has no user identifiers.
- [ ] Sessions preserve immutable plan-at-start linkage.
- [ ] Messages are normalized and ordered by per-session sequence.
- [ ] Plans are immutable, versioned, and linked.
- [ ] Assessment and post-session operations are unique by kind/source session.
- [ ] Failed operations do not advance stage.
- [ ] Operation retry reuses the same row.
- [ ] Chat turns are unique by session/client-message ID.
- [ ] Duplicate chat acceptance never inserts another user message.
- [ ] Every durable mutation increments revision exactly once.
- [ ] Stale revision attempts leave the database unchanged.
- [ ] Post-session completion is atomic across session, profile, plan, operation, stage, and revision.
- [ ] Startup operation and chat-turn recovery primitives are idempotent.
- [ ] Store close/reopen tests reconstruct durable state.
- [ ] New package has no legacy orchestration, service-container, Trio, API, console, or LLM imports.
- [ ] Phase 2 tests pass without HTTP or an LLM.
- [ ] Phase 1 characterization and existing deterministic tests remain green.
- [ ] No production runtime behavior changed.

## 18. Definition of done

Phase 2 is done when a developer can implement Phase 3 processors and Phase 4 `TherapyApplication` without deciding:

- what the durable entities are;
- how stage transitions are represented;
- which commands are valid;
- how revision comparison works;
- how sessions, messages, plans, operations, and chat turns are stored;
- what transaction creates or completes each durable workflow artifact;
- how duplicate client messages are resolved;
- how startup recovery transforms stale records;
- how a fresh or reset database is created.

If later phases still require a repository hierarchy, compatibility adapter, generic workflow framework, or database-model redesign, Phase 2 is not complete.

## 19. Handoff to Phase 3

Phase 3 begins with:

- accepted final domain models;
- tested pure workflow policy;
- tested concrete `SQLiteStore`;
- stable JSON/document persistence seams;
- no LLM dependency in the core;
- no legacy dependency in the new package.

Phase 3 may then add:

- `LLMGateway`;
- `OpenAICompatibleLLM`;
- `FakeLLM`;
- typed processor results;
- intake, assessment, therapy, and post-session processors.

Phase 3 must not replace the store, introduce another domain model, or reopen Phase 2 persistence decisions without a superseding ADR.
