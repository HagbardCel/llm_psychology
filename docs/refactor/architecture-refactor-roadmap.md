---
owner: engineering
status: accepted
last_reviewed: 2026-07-10
review_cycle_days: 30
source_of_truth_for: Target architecture and phased simplification roadmap
---

# Local Therapist Architecture Refactor Roadmap

> The roadmap records sequencing and decisions only. The implementable target
> interfaces are maintained in [Target Architecture](target-architecture.md),
> [API v1 Contract](api-v1-contract.md), and [Workflow Specification](workflow-specification.md);
> obsolete duplicated DTO and schema snippets must be replaced by links to those
> documents rather than independently maintained here.

## 1. Purpose

This document defines the target architecture and phased refactor plan for the local therapist application.

The refactor is intentionally optimized for the actual product:

- a local application running on one laptop;
- exactly one real user;
- separate test data rather than multi-user support;
- a console client and future web clients using the same API;
- SQLite persistence;
- local OpenAI-compatible model servers as the primary LLM runtime;
- no production deployment history;
- no requirement to preserve legacy database schemas or internal APIs.

The goal is not merely to reorganize the current code. The goal is to replace a platform-shaped architecture with a small, explicit modular monolith whose runtime flow can be understood from a limited number of modules.

## 2. Executive summary

The target system is:

```text
Console client ─┐
                ├── HTTP/WebSocket API v1
Web client ─────┘            │
                             ▼
                   TherapyApplication
                    ├── Workflow
                    ├── Phase processors
                    ├── LLMGateway
                    └── SQLiteStore
```

The API remains the stable product boundary. Both the console client and any future web frontend use the same contract.

Internally, the system will remove:

- multi-user registration and identity plumbing;
- the string-keyed dependency injection container;
- the agent factory and nested agent construction graph;
- overlapping workflow state, event, action and job representations;
- the orchestration manager callback graph;
- the SQLite connection pool, executor, repository and facade stack;
- no-op RAG abstractions;
- unused LLM provider generality, API-key rotation and cloud rate limiting;
- compatibility migrations and deprecated naming;
- generated protocol machinery that does not provide sufficient value for one bundled client;
- Docker-first development requirements and duplicate Compose services.

Dedicated domain behaviors currently called agents will remain, but will become narrow workflow phase processors:

- `IntakeProcessor`
- `AssessmentProcessor`
- `TherapyProcessor`
- `PostSessionProcessor`

## 3. Success criteria

The refactor is complete when all of the following are true.

### 3.1 Product and runtime

- The application supports one user only.
- Test runs and manual test profiles use separate databases or data directories.
- The console uses the same public API as future frontends.
- The API server is the only process allowed to write SQLite.
- The server exposes a stable `/api/v1` HTTP and WebSocket contract.
- The server supports token streaming, session history and restart recovery.
- The normal runtime consists of one backend process plus zero or more clients.
- Docker remains supported for packaging and multi-process startup but is not required for formatting, linting or ordinary tests.

### 3.2 Architecture

- One `Stage` enum represents durable workflow progression.
- One `Operation` model represents long-running assessment and post-session work.
- One `TherapyApplication` owns application use cases and transactions.
- One `SQLiteStore` owns persistence.
- One `LLMGateway` owns all model calls.
- Phase processors contain prompt and domain behavior but not persistence, networking or workflow navigation.
- No string-keyed service locator remains.
- No workflow processor constructs or calls another workflow processor.
- No no-op service exists solely as a speculative extension point.
- The application and domain layers do not import API or client modules.

### 3.3 Maintainability

- The complete runtime path can be understood by reading approximately five central modules.
- Adding a workflow command does not require changing multiple overlapping state/event/action systems.
- Adding a frontend does not require changing application logic.
- Adding a local OpenAI-compatible model does not require a new service class.
- Database reset is the only supported transition from the old schema to the new schema.
- The old and new architecture do not coexist after cutover.
- Runtime/backend physical LOC is reduced by approximately 40–55%.
- Repository-wide physical LOC is reduced by approximately 35–45%, while preserving meaningful integration and workflow tests.

## 4. Fixed architectural decisions

These decisions should be treated as project invariants during the refactor.

### 4.1 Single-user domain

There is one profile and at most one active therapy session.

The application does not expose:

- registration;
- login;
- user lookup;
- user lists;
- user-scoped routes;
- `user_id` query parameters;
- `user_id` columns in the new schema.

Automated tests create isolated temporary SQLite databases. Manual test runs use a separate data directory, for example:

```bash
JUNG_DATA_DIR=./data/manual-test uv run jung-api
```

The test distinction is environmental, not a second user in the domain.

### 4.2 API-only clients

The console and future web frontend use `/api/v1`.

Clients never:

- access SQLite;
- import application internals;
- mutate workflow state directly;
- decide the next stage;
- invoke phase processors;
- perform LLM calls.

The console is the reference API client and a primary integration-test surface.

### 4.3 Modular monolith

The backend is a single deployable application. It is not split into microservices.

Internal dependency direction:

```text
client → API contracts → API adapter → application → domain
                                            ├── store
                                            └── LLM gateway
```

### 4.4 Asyncio runtime

The target runtime uses one async ecosystem:

- `asyncio`;
- FastAPI or Starlette;
- Uvicorn;
- `httpx`;
- a compatible WebSocket client;
- the async interfaces of the chosen OpenAI-compatible SDK.

Trio-specific names, executors and orchestration types are removed during cutover.

FastAPI is the recommended server framework because it provides:

- clear Pydantic request and response contracts;
- OpenAPI generation for future web clients;
- mature HTTP and WebSocket support;
- direct alignment with the broader Python async ecosystem.

### 4.5 Breaking schema reset

No migration path from the old schema is implemented.

At cutover:

- back up the existing database if desired;
- delete or archive it;
- create a fresh database from the new schema;
- optionally provide a one-off export script for human-readable history, but not a compatibility migration framework.

### 4.6 Stable external boundary, flexible internals

The API contract is versioned as `/api/v1`.

The project does not implement runtime client-version negotiation. Breaking external changes require a future `/api/v2`, but internal refactors do not affect clients.

## 5. Target package structure

Package shape, application interfaces, and client boundaries are defined in
[Target Architecture](target-architecture.md). This roadmap records sequencing
and cutover decisions only; it does not maintain an independent package tree or
client interface copy.

## 6. Domain, application, persistence, and LLM design

The target workflow, application interface, persistence schema, phase processors,
`EventStream`, and `LLMGateway` are defined in
[Target Architecture](target-architecture.md) and ADRs
[0003](../adr/0003-workflow-stage-command-operation-model.md),
[0004](../adr/0004-single-sqlite-store-and-schema-reset.md), and
[0005](../adr/0005-phase-processors-and-llm-gateway.md).

This roadmap records sequencing and cutover decisions only. It does not maintain
independent copies of:

- `Stage`, command names, or transition graphs;
- `TherapyApplication` method signatures;
- SQLite table definitions (including `chat_turns`);
- processor responsibilities;
- `LLMGateway` method signatures.

Canonical client commands are `update_profile`, `send_message`,
`select_style`, `start_session`, `end_session`, and `retry_operation`. Intake
completion is processor-driven during chat, not a client command. Chat
acceptance returns a durable `ChatTurn` from `submit_message`; live token
events are published through `EventStream` to API adapters.

Durable workflow behavior, command availability, operation and `ChatTurn`
lifecycles, and legacy mappings are specified in
[Workflow Specification](workflow-specification.md).

## 11. API v1 design

The endpoint matrix, Pydantic-style request/response shapes, WebSocket union,
reconnection, idempotency, and concurrency errors are maintained solely in the
[API v1 Contract](api-v1-contract.md). This roadmap deliberately does not copy
wire schemas or event lists.

## 12. Console and future frontends

Console UI code depends on the API client and wire contracts defined in
[Target Architecture](target-architecture.md) and [API v1 Contract](api-v1-contract.md).

The web client may use generated HTTP types from OpenAPI, but WebSocket event types remain a small explicitly maintained discriminated union.

## 13. Docker and developer workflow

### 13.1 Native workflow

Canonical development commands:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format .
uv run jung-api
uv run jung-console
```

### 13.2 Docker workflow

Docker is supported for packaged execution:

```yaml
services:
  api:
    build: .
    command: uv run jung-api
    volumes:
      - ${JUNG_DATA_DIR:-./data}:/app/data

  web:
    build: ./web
    depends_on:
      - api

  console:
    build: .
    command: uv run jung-console --api-url http://api:8000
    profiles: ["console"]
    depends_on:
      - api
```

Remove duplicate API, user-test, console-test, database-viewer and devcontainer services unless they provide an actively used capability that cannot be supplied more simply.

## 14. Testing strategy

### 14.1 Unit tests

Test:

- workflow transition functions;
- prompt builders;
- structured output models;
- profile and plan patch merging;
- error mapping;
- task policy selection.

### 14.2 Application integration tests

Use:

- a temporary SQLite database;
- real `SQLiteStore`;
- `FakeLLM`;
- real `TherapyApplication`.

Test complete use cases and transaction boundaries.

### 14.3 API contract tests

Test:

- request and response DTOs;
- stable error codes;
- revision conflicts;
- WebSocket event unions;
- token streaming;
- reconnect behavior;
- busy behavior.

### 14.4 End-to-end tests

Maintain a small set of high-value workflows:

1. Fresh profile through first ready state.
2. First therapy session through post-session update.
3. Restart and resume.
4. Failed structured generation and retry.
5. API-backed console deterministic probe.
6. Optional local-model smoke test.

Delete tests that solely protect removed layers.

## 15. Phased implementation plan

## Phase 1 — Architecture freeze and behavioral characterization

### Goal

Make all cross-cutting decisions explicit and establish a black-box safety net before production code is replaced.

### Deliverables

- architecture decision records;
- target package and dependency rules;
- API v1 contract specification;
- workflow transition specification;
- baseline code and test metrics;
- deterministic characterization tests for current externally visible behavior;
- deletion inventory mapped to later phases.

### Production behavior

No intended change.

### Exit criteria

- decisions are approved and no foundational question remains open;
- current deterministic tests pass;
- new black-box characterization tests pass;
- current main commit and baseline metrics are recorded;
- Phase 2 can begin without redefining the target architecture.

A separate detailed plan is provided in `phase-1-implementation-plan.md`.

## Phase 2 — New single-user domain and persistence foundation

### Goal

Implement the new domain models, workflow primitives and SQLite schema without yet replacing the current API.

### Main work

- create the new package skeleton;
- implement `Stage`, commands, results and errors;
- implement the transition table and command availability;
- implement the new schema;
- implement `SQLiteStore`;
- add temporary-database integration tests;
- implement profile, sessions, normalized messages, plans and operations;
- implement database initialization and reset commands;
- add state revision and idempotent `client_message_id`.

### Explicit exclusions

- no LLM calls;
- no new API;
- no console changes;
- no migration from the old database.

### Exit criteria

- all store and workflow tests pass;
- restart recovery primitives are tested;
- new modules do not import legacy orchestration or service-container code.

## Phase 3 — LLM gateway and phase processors

### Goal

Port domain behavior from the existing agents into narrow phase processors.

### Main work

- implement `LLMGateway`;
- implement `OpenAICompatibleLLM`;
- implement `FakeLLM`;
- implement task policies and tracing decorator;
- port intake prompts and note extraction;
- port assessment and style recommendations;
- port therapy prompts and style definitions;
- consolidate reflection, note-taking, planning and memory behavior into `PostSessionProcessor`;
- define typed phase-specific results;
- add structured-output validation and retry rules.

### Exit criteria

- processors have no persistence or API imports;
- all processors are testable with `FakeLLM`;
- no processor constructs another processor;
- no generic `AgentResponse` is used in the new package.

## Phase 4 — TherapyApplication and recoverable operations

### Goal

Create the new application use-case layer and make it fully executable in integration tests.

### Main work

- implement typed composition root;
- implement `TherapyApplication`;
- implement command validation and state locking;
- implement message streaming;
- implement assessment operation lifecycle;
- implement post-session operation lifecycle;
- implement atomic completion transactions;
- implement stale-operation recovery on startup;
- centralize application errors;
- add full application integration scenarios.

### Exit criteria

- all target workflows run without HTTP;
- restart and retry scenarios pass;
- one application lock and one generation lock enforce concurrency;
- the new core has no dependency on the legacy runtime.

## Phase 5 — API v1 and API-backed console

### Goal

Expose the new application through the final API and switch the console to it.

### Main work

- implement FastAPI application;
- implement HTTP contracts and routes;
- implement WebSocket contracts and streaming;
- implement error mapping;
- implement OpenAPI output;
- implement `JungApiClient`;
- adapt console screens to the new snapshot and commands;
- port deterministic workflow probes to `/api/v1`;
- add API contract and reconnect tests.

### Exit criteria

- console uses only `/api/v1`;
- deterministic console probe passes end to end;
- future web clients can operate without application imports;
- legacy and new APIs are not both exposed as supported contracts.

## Phase 6 — Cutover and legacy deletion

Phase 5 handoff: the authoritative deletion checklist lives in [deletion-inventory.md](deletion-inventory.md), grouped by **Owner PR** with **Confidence** ratings. Run `make validate-refactor-phase-5` before starting Phase 6 slices; do not delete legacy runtime paths until the corresponding inventory row’s blocker is cleared and characterization coverage exists.

### Goal

Remove the old architecture completely and make the new implementation the only runtime.

### Main work

Delete:

- multi-user routes, models and database columns;
- `ServiceContainer`;
- agent factory and nested agent wiring;
- old orchestration managers and workflow engine;
- old `AgentResponse`;
- old database executor, repositories and facade;
- migration compatibility;
- no-op RAG;
- legacy job DTOs and workers;
- unused provider adapters and rate limiting;
- generated protocol constants and redundant schemas;
- legacy package and container naming;
- tests tied only to deleted internals.

Reset the development database and update seed/test fixtures.

### Exit criteria

- no legacy runtime imports remain;
- no compatibility aliases remain;
- new database creation is the only supported startup path;
- all deterministic and optional smoke checks pass;
- deletion inventory is empty.

## Phase 7 — Tooling, Docker and documentation finalization

### Goal

Simplify repository operation and make the new architecture the documented default.

### Main work

- make `pyproject.toml` plus `uv.lock` canonical;
- remove duplicate requirements files;
- make native lint/test/run commands canonical;
- reduce Compose services;
- retain a small packaged Docker path;
- replace architecture line budgets with import-boundary checks;
- update architecture, lifecycle, API, data model and agent/phase documentation;
- measure final LOC and file-count reductions;
- archive or delete temporary refactor plans once durable guidance is incorporated into canonical docs.

### Exit criteria

- clean checkout can run natively with documented commands;
- Docker stack starts API and supported clients;
- canonical docs describe only the new architecture;
- LOC and complexity targets are measured and published;
- no transitional documentation or scripts remain.

## 16. Branch and review strategy

Recommended:

1. Merge Phase 1 documentation and characterization tests into `main`.
2. Implement Phases 2–6 on a dedicated refactor branch with review checkpoints or stacked draft PRs.
3. Do not maintain old and new systems as supported implementations on `main`.
4. Merge the cutover only when the API-backed deterministic console probe passes.
5. Perform Phase 7 immediately after cutover.

Each phase should use explicit commits and have its own acceptance checklist. Avoid drive-by feature development while the architectural refactor is active.

## 17. Deletion inventory

The following components are expected to disappear by Phase 6:

| Current concept | Target |
|---|---|
| User registration and user IDs | Singleton profile and state |
| `ServiceContainer` | Typed `composition.py` |
| Agent factory | Explicit processor construction |
| `TrioAgentOrchestrator` | `TherapyApplication` |
| `TrioWorkflowEngine` | `workflow.py` |
| `TrioConversationManager` | Application streaming + store |
| `AgentResponseHandler` | Application result handling |
| `SessionLifecycleManager` | Application use cases |
| Generic `AgentResponse` | Phase-specific typed results |
| `NoteTakerAgent` | Intake/post-session helper functions |
| `PlanningAgent` | Assessment/post-session plan patching |
| `MemoryAgent` | Profile/plan patch generation |
| `TrioSQLiteExecutor` | `SQLiteStore` |
| Repository modules and DB facade | `SQLiteStore` methods |
| Migration compatibility | Fresh `schema.sql` |
| Hierarchical job DTOs | One `Operation` model |
| No-op RAG | Nothing until a real use case |
| Multiple per-agent LLM services | One gateway + task policies |
| API-key rotation/rate limiting | Removed unless a cloud adapter requires it |
| Client-version negotiation | `/api/v1` |
| Generated WS constants | Discriminated contract models |
| Docker-first checks | Native `uv` commands |
| Test user domain records | Isolated test databases |

## 18. Risk register

### Risk: behavior is lost while deleting abstractions

Mitigation:

- Phase 1 black-box characterization;
- typed processor results;
- cutover gated by deterministic console probes.

### Risk: post-session operations become unreliable

Mitigation:

- persisted idempotent operation model;
- atomic completion transactions;
- startup recovery tests.

### Risk: API and console drift

Mitigation:

- one typed Python API client;
- console tests against a real ephemeral server;
- Pydantic discriminated unions.

### Risk: temporary architecture duplication grows

Mitigation:

- new code lives in one isolated package;
- no adapters from new internals back into legacy internals;
- fixed Phase 6 deletion inventory;
- old and new systems are not both maintained after cutover.

### Risk: over-consolidation creates large modules

Mitigation:

- split by domain phase and boundary;
- keep application methods use-case focused;
- prefer pure prompt and merge functions;
- use architectural dependency checks rather than arbitrary layers.

### Risk: future web requirements force another redesign

Mitigation:

- API-only clients;
- stable `/api/v1`;
- snapshot-based state;
- explicit WebSocket event union;
- no console-specific business logic.

## 19. Non-goals

This refactor does not introduce:

- multi-user support;
- authentication;
- cloud deployment;
- microservices;
- a message broker;
- event sourcing;
- a plugin framework;
- generic autonomous agent orchestration;
- generalized RAG;
- database migration compatibility;
- multiple concurrent therapy sessions;
- a web frontend itself.

## 20. Final acceptance checklist

- [ ] One user, one profile, one active session.
- [ ] Console communicates exclusively through `/api/v1`.
- [ ] One `Stage` enum.
- [ ] One `Operation` model.
- [ ] One `TherapyApplication`.
- [ ] One `SQLiteStore`.
- [ ] One `LLMGateway`.
- [ ] Four phase processors with typed contracts.
- [ ] Normalized message persistence.
- [ ] Restart and retry behavior tested.
- [ ] Legacy orchestration and DI deleted.
- [ ] No-op RAG deleted.
- [ ] Compatibility schema code deleted.
- [ ] Native development workflow documented.
- [ ] Docker retained as packaging.
- [ ] Canonical docs describe only the target architecture.
- [ ] Runtime/backend LOC reduced by at least 40%.
- [ ] API-backed deterministic console probe passes.
