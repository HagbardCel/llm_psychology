---
owner: engineering
status: accepted
last_reviewed: 2026-07-10
review_cycle_days: 30
source_of_truth_for: Detailed implementation plan for architecture refactor Phase 1
---

# Architecture Refactor Phase 1 Implementation Plan

## 1. Phase objective

Phase 1 freezes the target architecture and creates a behavioral safety net before any runtime implementation is replaced.

This phase deliberately avoids changing production behavior. Its purpose is to ensure that Phases 2–7 can proceed without repeatedly reopening foundational decisions or discovering late that an important workflow behavior was not captured.

At the end of Phase 1, the project must have:

- explicit architecture decision records;
- an agreed target API and workflow model;
- black-box characterization tests for critical current behavior;
- reproducible baseline metrics;
- a deletion inventory;
- clear entry and exit criteria for Phase 2.

## 2. Scope

### 2.1 In scope

- document final architecture decisions;
- specify target package boundaries;
- specify the target workflow model;
- specify the `/api/v1` HTTP and WebSocket contract;
- specify single-user persistence semantics;
- specify long-running operation and recovery semantics;
- specify phase processor boundaries;
- capture current externally visible behavior with deterministic tests;
- record current code, test, dependency and runtime baselines;
- identify every legacy component scheduled for deletion;
- add validation that Phase 1 documents and characterization tests remain current.

### 2.2 Out of scope

Phase 1 must not:

- introduce the new SQLite schema;
- create the new production package;
- switch from Trio to asyncio;
- add FastAPI;
- change current HTTP or WebSocket payloads;
- change the console client;
- remove user IDs;
- rename the package;
- delete legacy agents or services;
- modify prompts;
- alter therapy behavior;
- add compatibility shims;
- create a database migration;
- run both architectures in production.

Any production behavior change discovered while writing characterization tests should be filed separately unless it blocks deterministic characterization.

## 3. Phase deliverables

Phase 1 should produce the following repository artifacts.

```text
docs/refactor/
├── architecture-refactor-roadmap.md
├── phase-1-implementation-plan.md
├── api-v1-contract.md
├── workflow-specification.md
├── baseline-metrics.md
└── deletion-inventory.md

docs/adr/
├── 0001-single-user-api-modular-monolith.md
├── 0002-asyncio-fastapi-runtime.md
├── 0003-workflow-stage-command-operation-model.md
├── 0004-single-sqlite-store-and-schema-reset.md
└── 0005-phase-processors-and-llm-gateway.md

tests/characterization/
├── conftest.py
├── legacy_client.py
├── assertions.py
├── test_onboarding_flow.py
├── test_therapy_lifecycle.py
└── test_restart.py

scripts/
└── measure_codebase.py
```

Existing files may be reused where appropriate, but the Phase 1 outputs should remain discoverable and separate from legacy unit tests.

## 4. Workstream A — Architecture decision records

### 4.1 ADR 0001: Single-user API modular monolith

File:

```text
docs/adr/0001-single-user-api-modular-monolith.md
```

Decision:

- one real user;
- no authentication or registration;
- separate test databases;
- API is the only frontend boundary;
- console and web use the same API;
- one backend process owns SQLite and LLM execution;
- no microservices.

Required sections:

- context;
- decision;
- consequences;
- rejected alternatives;
- invariants;
- follow-up work.

Rejected alternatives to record:

- retaining multi-user identifiers “for future use”;
- direct console-to-core calls;
- separate console and web backends;
- microservices;
- frontend-owned workflow state.

Acceptance criteria:

- states clearly that `user_id` is absent from the target domain and API;
- defines test profiles as isolated environments;
- defines the API server as the only database writer.

### 4.2 ADR 0002: Asyncio and FastAPI runtime

File:

```text
docs/adr/0002-asyncio-fastapi-runtime.md
```

Decision:

- replace Trio-specific runtime infrastructure with asyncio;
- use FastAPI and Uvicorn;
- use `httpx` and a compatible WebSocket client;
- preserve structured concurrency through application-owned tasks and task groups;
- do not expose async runtime concepts in domain models.

Required rationale:

- one async ecosystem across server, clients and LLM SDKs;
- future web-client OpenAPI support;
- removal of Trio-named persistence and orchestration types;
- lower integration friction.

Rejected alternatives:

- retaining Quart-Trio;
- mixing Trio and asyncio via adapters;
- synchronous server implementation.

Acceptance criteria:

- describes cancellation ownership for streaming and long-running operations;
- specifies startup recovery for persisted operations;
- specifies that “fire and forget” remains prohibited.

### 4.3 ADR 0003: Stage, command and operation model

File:

```text
docs/adr/0003-workflow-stage-command-operation-model.md
```

Decision:

- one durable `Stage`;
- explicit commands;
- generic persisted `Operation`;
- snapshot with monotonic revision;
- backend-derived available commands.

It must include the canonical transition table:

| Current stage | Command/result | Next stage |
|---|---|---|
| `SETUP` | profile completed | `INTAKE` |
| `INTAKE` | intake completion accepted | `ASSESSMENT` |
| `ASSESSMENT` | assessment operation completed | `STYLE_SELECTION` |
| `STYLE_SELECTION` | style selected | `READY` |
| `READY` | session started | `THERAPY` |
| `THERAPY` | session ended | `POST_SESSION` |
| `POST_SESSION` | post-session operation completed | `READY` |

Failure behavior:

- failed operation does not create a new workflow stage;
- retry updates the existing operation;
- stale running operations are recoverable;
- commands invalid for the current stage produce `invalid_command`;
- stale client revisions produce `state_conflict`.

Acceptance criteria:

- maps every existing workflow state to a target stage or operation status;
- explicitly removes legacy `REFLECTION_IN_PROGRESS`;
- explicitly removes generic string `next_action`.

### 4.4 ADR 0004: SQLiteStore and schema reset

File:

```text
docs/adr/0004-single-sqlite-store-and-schema-reset.md
```

Decision:

- one SQLite database;
- one concrete `SQLiteStore`;
- normalized messages;
- JSON for profile and structured results;
- immutable plan versions;
- no schema compatibility migration;
- reset at cutover.

Required transaction definitions:

- profile update;
- session creation;
- message append;
- assessment completion;
- post-session completion;
- retry status update.

Acceptance criteria:

- documents idempotent `client_message_id`;
- documents operation uniqueness;
- documents one active session invariant;
- documents database backup/reset procedure at cutover.

### 4.5 ADR 0005: Phase processors and LLM gateway

File:

```text
docs/adr/0005-phase-processors-and-llm-gateway.md
```

Decision:

- retain four dedicated phase processors;
- remove autonomous/nested agent orchestration;
- use phase-specific typed results;
- use one LLM gateway with task policies;
- retain fake LLM;
- remove no-op RAG.

Required mapping:

| Existing role | Target |
|---|---|
| intake agent | `IntakeProcessor` |
| assessment agent | `AssessmentProcessor` |
| therapist agent | `TherapyProcessor` |
| reflection agent | `PostSessionProcessor` |
| note taker | phase helper functions |
| planning agent | assessment/post-session plan patch |
| memory agent | profile/plan patch generation |
| agent factory | typed composition root |

Acceptance criteria:

- processors do not persist or emit transport events;
- processors do not call one another;
- model choice is a task policy, not a separate service graph;
- future RAG requires a concrete use case and new decision.

## 5. Workstream B — Target specifications

## 5.1 API v1 contract

File:

```text
docs/refactor/api-v1-contract.md
```

This is a design specification, not production code.

It must define:

### HTTP endpoints

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

For every endpoint specify:

- request body;
- response body;
- status codes;
- stable error codes;
- state revision behavior;
- allowed stages;
- idempotency behavior.

### Snapshot contract

Define:

- `revision`;
- `stage`;
- `profile_complete`;
- `selected_style`;
- `active_session`;
- `operation`;
- `available_commands`.

### WebSocket messages

Client:

- `send_message`;
- optionally reserve, but do not yet require, `cancel_generation`.

Server:

- `token`;
- `message_completed`;
- `snapshot_changed`;
- `operation_changed`;
- `error`.

For every event specify:

- discriminator;
- required fields;
- ordering;
- persistence point;
- reconnect behavior.

### Error taxonomy

At minimum:

- `invalid_command`;
- `state_conflict`;
- `busy`;
- `not_found`;
- `llm_unavailable`;
- `llm_timeout`;
- `invalid_llm_output`;
- `operation_failed`;
- `internal_error`.

Acceptance criteria:

- no `user_id`;
- no minimum-client version;
- no generic hierarchical job DTO;
- no workflow mutation endpoint;
- console requirements can be implemented entirely through this contract.

## 5.2 Workflow specification

File:

```text
docs/refactor/workflow-specification.md
```

It must include:

- stage definitions;
- command definitions;
- transition table;
- command availability by stage;
- session creation and closure rules;
- intake completion rules;
- assessment operation semantics;
- post-session operation semantics;
- retry behavior;
- startup recovery;
- concurrency rules;
- state revision rules;
- client reconnection rules.

Include a mapping table from all current states, events and actions to the target model. Each current value must be marked:

- retained;
- merged;
- converted to operation status;
- deleted.

Acceptance criteria:

- every existing path has an explicit target;
- no transition depends on frontend behavior;
- no processor decides global navigation.

## 6. Workstream C — Current-runtime characterization

## 6.1 Test philosophy

Characterization tests protect externally observable behavior rather than current internal classes.

They should interact only through the existing public HTTP/WebSocket interface and inspect SQLite only for final persisted assertions where no public read endpoint exists.

They must not:

- instantiate current agents directly;
- mock orchestration managers;
- assert current class names;
- assert service-container wiring;
- assert internal callback sequences;
- freeze deprecated fields that will intentionally disappear.

Use the existing deterministic fake-model path wherever possible.

Target-only guarantees belong in later `tests/acceptance/` tests as the new runtime appears. Unconditional `NotImplementedError` or placeholder `xfail` tests are not acceptable Phase 1 evidence.

The suite remains intentionally small: three broad scenario files, one process fixture, one minimal client, and one small assertion helper.

## 6.2 Shared test harness

Create:

```text
tests/characterization/conftest.py
tests/characterization/legacy_client.py
tests/characterization/assertions.py
```

The harness should provide:

- isolated temporary data directory;
- fresh database setup;
- deterministic fake LLM configuration;
- API process lifecycle with bounded shutdown;
- HTTP and WebSocket clients against the legacy public contract;
- event collection with bounded timeouts;
- database snapshot helper;
- captured stdout/stderr on failure;
- normalization of nondeterministic IDs and timestamps;
- clear trace output on failure.

## 6.3 Scenario 1: Onboarding flow

File:

```text
tests/characterization/test_onboarding_flow.py
```

Actions:

1. start backend with fresh storage;
2. create profile through the existing contract;
3. complete intake via deterministic chat turns;
4. wait for assessment completion;
5. select a style;
6. confirm initial plan creation.

Assertions (`must_preserve`):

- one logical intake session;
- ordered messages;
- intake evidence persisted;
- one assessment result;
- selected style persisted;
- one initial plan;
- ready-for-therapy state reached.

## 6.4 Scenario 2: Therapy lifecycle

File:

```text
tests/characterization/test_therapy_lifecycle.py
```

Actions:

1. begin from ready state;
2. start therapy session;
3. send a deterministic message;
4. collect streamed response chunks;
5. confirm persisted assistant response;
6. end session;
7. wait for post-session work;
8. inspect plan revision linkage.

Assertions (`must_preserve`):

- chunks reconstruct the completed response;
- messages are ordered;
- one active session during therapy;
- session closes;
- post-session data exists;
- exactly one new plan revision;
- historical plan linkage remains intact.

## 6.5 Scenario 3: Restart

File:

```text
tests/characterization/test_restart.py
```

Parametrize checkpoints:

- during intake after persisted messages;
- after style selection;
- after completed post-session work.

Assertions (`must_preserve`):

- durable state is recovered;
- no duplicate active session is created;
- no duplicate logical operation result is persisted;
- client can continue from backend state and history.

Document target-only gaps as `known_current_defect` rather than blocking smoke with unconditional `xfail`.

## 7. Workstream D — Baseline metrics

## 7.1 Measurement script

Create:

```text
scripts/measure_codebase.py
```

The script should produce deterministic JSON and Markdown output.

Measure separately:

- production Python physical lines;
- production Python nonblank/noncomment code lines;
- test Python physical lines;
- scripts and executable configuration;
- Python file counts;
- test file counts;
- dependency counts;
- number of Pydantic models;
- number of enums;
- number of classes with `Agent`, `Manager`, `Service`, `Repository`, `Factory` or `Container` in the name;
- number of modules importing Trio;
- number of modules importing the service container;
- number of API routes;
- number of WebSocket message types;
- number of database tables.

Exclude:

- `.git`;
- virtual environments;
- generated schemas;
- lockfiles;
- data files;
- logs;
- Markdown from LOC totals.

Prefer a small Python implementation over introducing a mandatory external LOC tool. It may optionally consume `tokei` when available but must have a repository-local fallback.

## 7.2 Baseline document

Create:

```text
docs/refactor/baseline-metrics.md
```

Record:

- source commit SHA;
- measurement command;
- timestamp;
- metrics;
- known limitations;
- target metrics.

Recommended target table:

| Metric | Baseline | Target |
|---|---:|---:|
| Runtime/backend physical LOC | measured | -40% minimum |
| Repository physical LOC | measured | -35% minimum |
| Trio-importing production modules | measured | 0 |
| Service-container imports | measured | 0 |
| User-scoped API routes | measured | 0 |
| Workflow state-like enums/models | measured | 1 durable stage + operation status |
| Database persistence layers | measured | 1 store |
| Production LLM adapters | measured | 1 initially |
| No-op services | measured | 0 |

## 8. Workstream E — Deletion inventory

Create:

```text
docs/refactor/deletion-inventory.md
```

Each entry should contain:

- current path or symbol;
- current responsibility;
- target replacement;
- deletion phase;
- tests to remove or rewrite;
- dependencies blocking deletion;
- deletion status.

Initial categories:

### Multi-user

- user registration routes;
- login/session lookup routes;
- `user_id` DTO fields;
- `user_id` database columns;
- user-scoped caches;
- active-session-per-user registries.

### Workflow and orchestration

- `WorkflowState` duplication;
- user status duplication;
- workflow events;
- generic next actions;
- legacy reflection state;
- job hierarchy;
- orchestrator;
- response handler;
- conversation manager;
- lifecycle manager.

### Agents

- agent factory;
- nested agent construction;
- note taker as top-level agent;
- planning agent;
- memory agent;
- generic `AgentResponse`.

### Persistence

- connection pool;
- Trio executor;
- repository modules;
- DB facade;
- migration compatibility;
- serialized transcript blob.

### Infrastructure

- no-op RAG;
- per-agent LLM service instances;
- unused providers;
- cloud rate limiter;
- API-key rotation;
- generated protocol constants;
- client-version negotiation.

### Operations

- duplicate Compose services;
- DB-viewer service;
- Docker-only lint/test commands;
- duplicate requirements files;
- legacy names and aliases.

Acceptance criteria:

- every intended deletion has a replacement or explicit “remove without replacement” rationale;
- every deletion is assigned to a phase;
- Phase 6 can be executed mechanically from the inventory.

## 9. Workstream F — Documentation integration

Phase 1 should update the documentation index only after the new files exist.

Add a proposed/refactor section to `docs/README.md` linking:

- roadmap;
- Phase 1 plan;
- API v1 contract;
- workflow specification;
- ADR index if created.

Do not rewrite the canonical current architecture documentation in Phase 1. It must continue to describe the running system until cutover.

Add a clear banner to proposed documents:

> This document specifies the target refactor architecture. The current runtime remains described by the canonical active architecture documents until Phase 6 cutover.

## 10. CI and validation

Add one CI or Make target:

```text
validate-refactor-phase-1
```

It should run:

- documentation link validation;
- ADR presence and metadata validation;
- metric-script unit test;
- characterization tests using the deterministic fake path;
- existing deterministic tests.

Do not make real-LLM tests mandatory.

Recommended local command:

```bash
uv run pytest tests/characterization
```

If the current repository still requires Docker in Phase 1, retain a temporary wrapper:

```bash
make characterization-test
```

The target native workflow is introduced later; Phase 1 should not mix tooling refactor with behavioral characterization.

## 11. Implementation sequence

## Step 1 — Add planning documents

Create:

- roadmap;
- Phase 1 plan;
- initial ADR templates;
- refactor documentation directory.

No test or runtime changes.

Validation:

- Markdown renders correctly;
- links resolve;
- metadata passes existing documentation checks.

## Step 2 — Record the baseline

Implement `measure_codebase.py`.

Run it against the pinned Phase 1 base commit.

Commit generated baseline metrics.

Validation:

- repeated runs on the same commit are stable;
- exclusions are documented;
- production and test LOC are separated.

## Step 3 — Complete ADRs

Fill and review all five ADRs.

Resolve every open decision before proceeding.

No ADR should remain “TBD” on:

- user model;
- client boundary;
- async runtime;
- server framework;
- stage names;
- operation semantics;
- persistence ownership;
- database reset;
- processor boundaries;
- initial LLM adapters.

## Step 4 — Write API and workflow specifications

Create the target contract and transition specification.

Review them from three perspectives:

- backend implementation;
- console implementation;
- future web frontend implementation.

Resolve any requirement that would force client-specific business logic.

## Step 5 — Build the characterization harness

Add process lifecycle, clients, deterministic configuration and trace helpers.

First prove that the harness can:

- start the current backend;
- issue one health request;
- open and close a WebSocket;
- capture failure diagnostics;
- clean up processes and temporary data.

## Step 6 — Add scenarios incrementally

Recommended order:

1. fresh installation and intake;
2. assessment and style selection;
3. therapy session;
4. post-session;
5. restart;
6. failure and retry.

Do not implement all scenarios in one test file.

## Step 7 — Build deletion inventory

As characterization work exposes actual dependencies, update the inventory.

Every existing agent, manager, service and repository touched by a scenario should be classified.

## Step 8 — Add validation target

Integrate Phase 1 checks without changing the normal real-LLM path.

## Step 9 — Phase review

Review all exit criteria.

Phase 2 may begin only after all blocking decisions are closed.

## 12. Suggested PR structure

Phase 1 can be delivered in two reviewable PRs.

### PR 1: Architecture decisions and baseline

Contains:

- roadmap;
- Phase 1 plan;
- ADRs;
- target API specification;
- target workflow specification;
- metric script;
- baseline metrics;
- initial deletion inventory.

It changes no production behavior.

### PR 2: Black-box characterization suite

Contains:

- characterization harness;
- three scenario files (onboarding, therapy lifecycle, restart);
- deterministic fixtures;
- validation target;
- known-current-behavior notes.

It must not add unconditional `xfail` placeholder tests. Target-only behavior belongs in `tests/acceptance/` later.

## 13. Detailed test acceptance matrix

| Capability | Characterization evidence | Required before Phase 2 |
|---|---|---|
| Fresh data directory startup | Backend creates usable state | Yes |
| Profile creation | Persisted and reconnectable | Yes |
| Intake persistence | Messages and structured record | Yes |
| Assessment | Exactly one logical result | Yes |
| Style selection | Style and initial plan persisted | Yes |
| Therapy streaming | Chunks equal persisted message | Yes |
| Session closure | Session final state persisted | Yes |
| Plan revision | Historical session link retained | Yes |
| Restart | Durable state reconstructed | Yes |
| Duplicate handling | No duplicate logical side effects | Yes |
| Failure behavior | Consistent state after failure | Target acceptance; not Phase 1 smoke |
| Retry behavior | Retry does not duplicate completion | Target acceptance; not Phase 1 smoke |
| Console/API contract | Existing console path covered | Yes |

## 14. Phase 1 exit criteria

All blocking criteria:

- [ ] Roadmap approved.
- [ ] All five ADRs accepted.
- [ ] API v1 contract has no unresolved fields.
- [ ] Workflow specification maps every current state/action.
- [ ] Single-user and test-data strategy fixed.
- [ ] Asyncio/FastAPI decision fixed.
- [ ] New database reset strategy fixed.
- [ ] Processor and LLM boundaries fixed.
- [ ] Baseline metrics recorded against an exact commit.
- [ ] Deletion inventory created.
- [ ] Onboarding characterization passes.
- [ ] Therapy lifecycle characterization passes.
- [ ] Restart characterization passes.
- [ ] Target-only behavior is not disguised as characterization.
- [ ] Existing deterministic tests still pass.
- [ ] No production behavior changed unintentionally.
- [ ] Phase 2 task list can be derived without another architecture decision.

## 15. Definition of done

Phase 1 is done when a developer or coding agent can answer all of the following by reading the Phase 1 artifacts:

- What is the final runtime architecture?
- Why is the product single-user?
- How does a test profile work?
- Which clients use the API?
- What are the exact durable stages?
- Which commands are valid in each stage?
- How are assessment and post-session work persisted and retried?
- What is the exact API v1 contract?
- Where do current agents move?
- Which components are deleted?
- What database schema will replace the current one?
- What current behaviors must survive the refactor?
- How will success and code reduction be measured?

If any answer still depends on an undocumented assumption, Phase 1 is not complete.

## 16. Rollback and failure handling

Phase 1 contains documentation, metrics and tests only. Rollback is therefore straightforward:

- revert the Phase 1 commits;
- no database rollback is required;
- no API rollback is required;
- no client rollback is required.

A characterization test that exposes an existing defect should not block the documentation portion. Record the defect, define target behavior and use an explicit `xfail` where necessary.

## 17. Handoff to Phase 2

Phase 2 begins with:

- accepted domain and workflow contracts;
- accepted schema design;
- stable target names;
- a temporary database testing pattern;
- baseline metrics;
- external behavior tests.

The first Phase 2 implementation commit should create the new domain/workflow package and tests. It should not modify the old orchestration path.

The new package must immediately obey these dependency rules:

```text
domain imports no infrastructure
workflow imports domain only
phases import domain and LLM gateway
persistence imports domain
application imports domain, workflow, phases and store interfaces
API imports application and API contracts
client imports API contracts only
```

Phase 2 must not reopen decisions already accepted in Phase 1 without a superseding ADR.
