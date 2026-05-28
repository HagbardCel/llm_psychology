---
owner: engineering
status: active
last_reviewed: 2026-05-28
review_cycle_days: 30
source_of_truth_for: Foundation stabilization strategy and temporary frontend maintenance policy
---

# Foundation Stabilization Plan

## Purpose

This plan defines how to reduce frontend maintenance overhead while the core architecture, workflow, protocol contracts, persistence model, and LLM behavior are still being stabilized.

The project should temporarily operate as a **headless backend and protocol-contract project** with one maintained reference client. Full multi-frontend product development should resume only after the project foundation is stable.

## Core Decision

Until the project foundation is declared stable:

1. Treat the backend, workflow engine, persistence model, API DTOs, WebSocket protocol, schema generation, and deterministic tests as the main product.
2. Maintain only one reference client as a first-class client.
3. Freeze other frontends except for compatibility, build, and smoke-path fixes.
4. Avoid adding user-facing frontend features that depend on unstable workflow or protocol semantics.
5. Defer optional capabilities such as local RAG, advanced UI flows, and frontend polish until the foundation-complete checklist is satisfied.

## Rationale

The repository currently supports multiple client surfaces, including:

- standalone terminal UI,
- WebSocket-based console UI,
- React web frontend,
- usertest variants,
- frontend unit tests,
- frontend E2E tests.

This creates excessive change amplification: foundational backend or protocol changes tend to require updates across several clients, generated types, Docker services, frontend tests, E2E flows, and documentation.

The project architecture already aims to keep business logic independent of I/O. The next phase should enforce that intent more strictly by moving product development pressure away from the frontends and onto stable backend contracts.

## Support Tiers

### Tier 0 — Foundation Contracts

**Status:** Always maintained.

Includes:

- workflow state machine,
- session lifecycle,
- HTTP API DTOs,
- WebSocket protocol,
- schema generation,
- generated protocol constants,
- persistence and migrations,
- LLM abstraction,
- deterministic fake-provider behavior,
- backend tests,
- architecture and documentation validation.

Tier 0 is the main development surface during this phase.

### Tier 1 — Reference Client

**Status:** Maintained as the canonical integration client.

Recommended client:

- WebSocket-based console UI.

Responsibilities:

- exercise real backend workflow behavior,
- validate registration, connection, workflow-next-action, streaming, session ending, and style selection flows,
- remain simple enough to adapt quickly to backend contract changes,
- provide a useful debugging and manual-test interface.

### Tier 2 — React Web Frontend

**Status:** Frozen except for compatibility and smoke-path maintenance.

Allowed changes:

- generated type compatibility fixes,
- build fixes,
- dependency/security fixes,
- minimal changes needed to keep one golden path working,
- contract regression fixes caused by backend protocol changes.

Disallowed changes during foundation stabilization:

- new product features,
- UI redesign,
- new complex frontend state-management abstractions,
- expanded frontend unit-test surface unrelated to contract compatibility,
- frontend-specific workflow behavior that is not backend-driven,
- speculative UX flows before backend semantics are stable.

### Tier 3 — Standalone Terminal UI

**Status:** Legacy or local-debug mode.

Recommended policy:

- Do not add new features.
- Keep only if it provides a unique local-development benefit.
- Prefer migrating useful behavior into the console UI or backend tests.
- Consider removal after the console UI covers the same debugging and manual-test use cases.

## Frontend Maintenance Policy

Until foundation stabilization is complete:

```text
The React frontend is a compatibility/demo client, not the product development driver.
```

Rules:

1. No new React product features.
2. No UI redesign work.
3. No new frontend-only workflow semantics.
4. No frontend state transitions that bypass backend workflow authority.
5. Keep only minimal browser compatibility:
   - build passes,
   - type-check passes,
   - generated types remain usable,
   - one golden-path E2E flow remains green.
6. Prefer backend and protocol tests over frontend tests for foundational behavior.
7. Any frontend change must state whether it is:
   - contract compatibility,
   - build/dependency maintenance,
   - smoke-path repair,
   - or explicitly deferred product work.

## Foundation-Complete Checklist

Frontend product work should resume only when the following areas are stable.

### 1. Workflow State Machine

Completion criteria:

- All major workflow states are explicit.
- All state transitions are validated.
- Invalid transitions fail deterministically.
- Backend is the only authority for workflow progression.
- Clients never mutate workflow state directly.
- Regression tests cover the major transition paths.

Required paths:

- new user,
- profile creation,
- intake,
- assessment,
- therapy style selection,
- therapy session,
- session ending,
- reflection or planning transition,
- next-session resumption.

### 2. Session Lifecycle

Completion criteria:

- Session creation, resume, reconnect, end-session, and post-session state are deterministic.
- WebSocket reconnect reliably re-emits the required session and workflow state.
- `end_session` behavior is consistent across the reference client and backend tests.
- Session ownership and profile/session binding are enforced.
- Session-ending failures have deterministic error behavior.

Required scenarios:

- fresh user starts first session,
- existing user resumes,
- user reconnects during workflow wait state,
- user ends therapy session,
- backend emits session-ended confirmation,
- stale or invalid session IDs are rejected.

### 3. HTTP API Contract

Completion criteria:

- API-facing models are explicit DTOs.
- Persistence models are not leaked as wire models.
- DTO changes go through schema generation.
- Generated schemas are committed.
- API behavior is covered by backend tests.
- API errors use consistent response shapes.

Required areas:

- user registration,
- user status,
- session listing,
- session detail,
- session creation,
- session extension,
- therapy styles,
- therapy plan,
- workflow next action,
- workflow action completion.

### 4. WebSocket Protocol

Completion criteria:

- Message envelope is stable.
- Client-to-server message types are minimal and documented.
- Server-to-client message types are stable and generated where applicable.
- Error handling is deterministic.
- Streaming behavior is tested.
- Reconnect behavior is tested.
- Unknown or invalid messages are handled predictably.

Required messages:

- `connected`,
- `session_started`,
- `workflow_next_action`,
- `chat_message`,
- `chat_response_chunk`,
- `assessment_recommendations`,
- `session_ended`,
- `error`.

### 5. Type and Schema Pipeline

Completion criteria:

- Pydantic DTOs are the backend source of truth.
- JSON schemas are generated from backend models.
- Frontend types are generated from schemas.
- Protocol constants are generated where applicable.
- Schema drift is detected by validation.
- Contract changes and generated artifacts are committed together.

Rules:

- Do not hand-edit generated files.
- Do not introduce frontend-only copies of backend DTOs unless explicitly documented as UI-only state.
- Contract changes must include tests and regenerated artifacts.

### 6. Persistence and Data Integrity

Completion criteria:

- Migrations are deterministic.
- Profile, session, message, therapy plan, and workflow-state persistence are stable.
- Session immutability rules are explicit.
- Derived data is separated from raw transcripts.
- Background or post-session enrichment does not block normal user interactions.
- Database tests cover key lifecycle events.

Required decisions:

- durable vs in-memory active-session tracking,
- restart behavior,
- single-user vs multi-user assumptions,
- future multi-instance requirements,
- migration strategy before release.

### 7. LLM and Provider Abstraction

Completion criteria:

- Real provider calls and fake-provider tests use the same service boundary.
- Structured output behavior is validated.
- Quota, provider failure, timeout, and invalid-output behavior are deterministic.
- Agent-specific model selection is implemented through configuration, not hardcoded.
- Tests do not require network access unless explicitly marked as real-provider tests.

Required failure cases:

- provider unavailable,
- quota exhausted,
- invalid structured output,
- streaming interruption,
- slow response,
- fallback recommendation path.

### 8. Safety and Product Boundary

Completion criteria:

- The product boundary is explicit.
- The app does not present itself as medical care.
- Crisis or self-harm escalation behavior is defined.
- Privacy and data-retention assumptions are documented.
- LLM logging redaction policy is clear.
- User-facing disclaimers are consistent across clients.

Required artifacts:

- safety policy note,
- crisis-response behavior,
- privacy/data-retention note,
- logging/redaction defaults,
- test cases for safety-critical routing if implemented.

### 9. Validation Strategy

Completion criteria:

- Fast development checks are separated from full release-candidate checks.
- Backend and protocol tests catch most foundational regressions before browser tests run.
- One full validation target remains available before release.
- Validation order is documented.

Recommended validation layers:

| Layer | Purpose | Frequency |
|---|---|---|
| Docs validation | metadata, active-doc hygiene, source-of-truth clarity | every doc/architecture change |
| Schema validation | DTO/protocol drift detection | every contract change |
| Architecture validation | layer-boundary enforcement | every backend structural change |
| Backend unit tests | core logic and workflow correctness | continuously |
| Console/reference-client tests | protocol integration | continuously |
| React type-check/build | compatibility | before merge |
| React smoke E2E | minimal browser compatibility | before release candidate |
| Full release-candidate check | release readiness | before release or major merge |

## Recommended Work Sequence

### Phase 1 — Governance and Scope Control

1. Add this plan to active project documentation.
2. Add or update a frontend maintenance policy.
3. Mark support tiers for each client.
4. Identify the reference client.
5. Mark deferred frontend work as explicitly out of scope.

Deliverables:

- active foundation stabilization plan,
- client support-tier table,
- frontend maintenance policy,
- deferred-work list.

### Phase 2 — Contract Stabilization

1. Review all HTTP DTOs.
2. Review all WebSocket messages.
3. Remove or document unstable protocol behavior.
4. Ensure schema and type generation are reproducible.
5. Add missing protocol regression tests.
6. Ensure clients consume generated types/constants where practical.

Deliverables:

- stable HTTP contract inventory,
- stable WebSocket contract inventory,
- passing schema validation,
- passing protocol tests.

### Phase 3 — Workflow and Session Hardening

1. Audit workflow transitions.
2. Audit session start/resume/end behavior.
3. Add regression tests for all major paths.
4. Make reconnect behavior deterministic.
5. Ensure client behavior follows backend-required actions.

Deliverables:

- tested workflow transition matrix,
- tested session lifecycle matrix,
- deterministic reconnect behavior,
- tested end-session behavior.

### Phase 4 — Persistence and LLM Reliability

1. Review database lifecycle behavior.
2. Validate migrations.
3. Confirm fake-provider and real-provider boundaries.
4. Add deterministic tests for LLM failure modes.
5. Keep optional RAG out of the core release path unless separately stabilized.

Deliverables:

- persistence lifecycle tests,
- LLM failure-mode tests,
- documented RAG deferral or extension plan.

### Phase 5 — Minimal Client Compatibility

1. Keep the console UI aligned with backend contracts.
2. Keep React type-check and build passing.
3. Keep only one minimal browser golden path.
4. Remove or defer frontend tests that encode unstable product assumptions.
5. Ensure client code does not advance workflow state independently.

Deliverables:

- maintained console reference client,
- React build/type compatibility,
- one browser smoke path,
- no frontend-only workflow authority.

### Phase 6 — Foundation Exit Review

1. Run the full validation suite.
2. Review the foundation-complete checklist.
3. Close or explicitly defer all blocking foundation issues.
4. Decide whether to resume frontend product development.
5. Create a separate frontend product plan if frontend work resumes.

Deliverables:

- foundation-complete decision,
- release or continuation decision,
- next-phase frontend plan if appropriate.

## Deferred Work

The following work should remain deferred unless needed for foundation stabilization:

- advanced React UI polish,
- UI redesign,
- rich dashboard features,
- local FAISS or other heavy RAG backends,
- multi-client feature parity,
- mobile-specific UX,
- production deployment polish beyond what is needed for validation,
- extensive frontend unit-test expansion,
- non-essential dependency upgrades,
- multi-instance deployment behavior unless it changes core architecture decisions.

## Decision Rules

Use these rules when triaging new work.

### Rule 1 — Foundation Before Frontend

If a change affects workflow, persistence, API DTOs, WebSocket messages, LLM behavior, safety behavior, or validation, it belongs to the foundation phase.

### Rule 2 — Backend Owns Workflow

Clients may render workflow state and submit explicit user actions, but they must not own workflow progression.

### Rule 3 — Contracts Before Clients

When behavior changes, update contracts, tests, schemas, and generated artifacts before expanding client UX.

### Rule 4 — One Reference Client

Only one client should be used to validate end-to-end behavior during foundation stabilization.

### Rule 5 — Browser UI Is Compatibility Only

The React frontend should remain buildable and minimally usable, but it should not drive product behavior until the foundation-complete checklist is satisfied.

## Exit Criteria

The foundation stabilization phase can end when:

1. The foundation-complete checklist is satisfied.
2. The full validation path passes.
3. Contract drift is controlled by schemas and generated artifacts.
4. Workflow and session lifecycle behavior are deterministic.
5. LLM failure modes have deterministic fallbacks.
6. The reference client works against the current backend.
7. The React frontend has a passing minimal golden path.
8. Deferred work is clearly separated from release-blocking work.

## Post-Stabilization Options

After foundation stabilization, choose one of the following paths.

### Option A — Web-First Product

Make the React frontend the primary product surface and invest in:

- UX polish,
- accessibility,
- frontend state simplification,
- richer dashboards,
- session history,
- therapy plan visualization,
- user-facing error handling,
- browser E2E coverage.

### Option B — Console/Local-First Product

Keep the project as a local-first, developer-oriented tool and invest in:

- console UX,
- local model support,
- observability,
- transcript export,
- configuration ergonomics,
- deterministic local operation.

### Option C — API/Backend Platform

Treat the backend as the main artifact and invest in:

- stable API documentation,
- OpenAPI or equivalent generated docs,
- SDK/client generation,
- integration tests,
- deployment packaging,
- multi-client support after contracts are stable.

## Recommended Default Path

The recommended default is:

1. Complete foundation stabilization.
2. Keep the console UI as the reference client.
3. Keep the React frontend frozen except for compatibility.
4. Reassess whether the project should become web-first, local-first, or API-first only after the foundation exit review.
