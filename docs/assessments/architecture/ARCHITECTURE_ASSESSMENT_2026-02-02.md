# Project Architecture Assessment (2026-02-02)

This assessment reviews the current codebase against the project’s intended architecture as defined in `docs/design-principles.md`, and proposes improvements to make the system leaner, more maintainable, and more consistently aligned with established engineering practices.

## Scope & Inputs

Reviewed (non-exhaustive):
- Architecture + contracts: `docs/design-principles.md`, `docs/ARCHITECTURE.md`, `docs/contracts/HTTP_API_CONTRACT.md`, `docs/WEBSOCKET_PROTOCOL.md`, `docs/TYPE_SYSTEM.md`, `docs/session_lifecycle.md`, `docs/session_block_lifecycle.md`
- Backend: `src/psychoanalyst_app/` (server composition, gateway routes/WS handler, orchestration, agents, services, models, schema tooling)
- Frontend: `frontend/src/` (API client, WebSocket client, types pipeline)
- Console UI: `console-ui/src/` (WS protocol and client)
- Tests: `tests/` (unit/integration + deterministic fakes)

## Executive Summary

The project largely reflects the intended “gateway → orchestration → agents → services” layering and is meaningfully Trio-first and streaming-first. However, the highest-impact architectural risk is **contract drift**: the code, docs, schemas, generated frontend types, and tests disagree on core identifiers and DTO names (notably `session_id` vs `session_block_id`, and `Session` vs `SessionBlock`). This is directly contrary to the “stable contracts” and “type pipeline” principles and is likely to cause runtime integration failures and/or broken builds.

Top priorities:
1. **Restore contract + schema/type generation consistency** (P0): make one naming scheme canonical and regenerate + validate artifacts.
2. **Create and enforce a single WS protocol source of truth** (P0): fix the missing `schemas/ws_protocol.json` and remove duplicated protocol constants.
3. **Lean out dead/broken modules and outdated docs/tests** (P0/P1): eliminate “ghost” packages and contradicting lifecycle docs.
4. **Strengthen boundaries** (P1): reduce agent-level I/O and orchestration responsibility; concentrate side effects and concurrency management in orchestration/services.
5. **Tighten engineering feedback loops** (P1): CI should fail on contract drift, type-check errors, and stale generation outputs.

## Design Principles Alignment (Gap Analysis)

### 1) Structured concurrency is mandatory (Trio-first)
**Status: Mostly aligned**
- Good use of Trio nurseries in server composition and orchestration.
- Blocking calls are often bridged via `trio.to_thread.run_sync()` (DB executor, RAG retrieval, LLM streaming bridge).

**Gaps / Recommendations**
- Keep all long-lived background work explicitly owned by a nursery; avoid ad-hoc background tasks outside orchestrator/server composition.
- Standardize time and cancellation behavior across background jobs (enrichment/reflection/assessment) so cancellation is deterministic.

### 2) Clean boundaries: business logic independent of I/O
**Status: Partially aligned**
- Gateway layer exists (`src/psychoanalyst_app/api/*_routes.py`, `src/psychoanalyst_app/api/ws_handler.py`) and orchestration is clearly present.
- However, several agents take DB/RAG services and perform non-trivial infrastructure work (DB reads, RAG calls, cross-agent coordination), which blurs boundaries and makes unit testing harder.

**Recommendations**
- Treat agents as “decision + prompt composition” units. Pass all data needed for decisions into `ConversationContext` (or a richer context object), rather than fetching data inside agents.
- Push side effects (DB writes, job scheduling, WS emits) into orchestration/services; keep agents deterministic given inputs.

### 3) Workflow is an explicit state machine
**Status: Aligned (with edge-case issues)**
- `TrioWorkflowEngine` clearly encodes states, transitions, and mappings.
- `WorkflowNextAction` is a strong pattern for backend-owned workflow invariants.

**Gaps / Recommendations**
- Resolve “end of session while last prompt is on screen” (see `docs/current_issues/abrupt_intake_end.md`) by making session-end semantics explicit and testable (see recommendations under “Workflow & Session Time”).

### 4) Stable contracts at boundaries (DTOs + schemas)
**Status: Currently misaligned (P0)**
Observed drift signals:
- Backend HTTP routes and DTOs use `session_id`, while schemas and generated frontend types include `session_block_id`.
- Schemas include `SessionBlock.json` (and TS `SessionBlockDTO`) rather than `Session.json`/`SessionDTO`, while backend code and docs refer to sessions.
- Frontend `frontend/src/types/index.ts` imports types (`Session`, etc.) that are not exported by the current `frontend/src/types/generated/api.ts` output.

**Recommendations**
- Decide and enforce canonical names and regenerate all artifacts in a single pass:
  - Backend DTO models (`src/psychoanalyst_app/models/http_models.py`)
  - JSON schemas (`schemas/*.json`)
  - Generated TS types (`frontend/src/types/generated/api.ts`)
  - API contract docs (`docs/contracts/HTTP_API_CONTRACT.md`, `docs/TYPE_SYSTEM.md`)
  - Tests that construct contexts/DTOs
- Add a CI check that fails if the repo’s committed schemas/types are out of date with current backend models.

### 5) Streaming-first UX
**Status: Aligned**
- WS chunk streaming exists; console client and frontend handle `chat_response_chunk`.

**Gaps / Recommendations**
- Consolidate WS message types/versions into a single source of truth and regenerate clients to avoid silent drift.

## High-Impact Architectural Improvements (Prioritized)

### P0 — Fix Contract Drift: `session_id` vs `session_block_id` (and `Session` vs `SessionBlock`)
This is the most urgent maintainability and correctness issue because it breaks the “stable contracts” and “type system pipeline” principles.

**What to do**
1. **Choose the canonical concept**:
   - If the system uses `sessions` (current DB repos and server behavior suggest it does), standardize on:
     - `session_id` everywhere (HTTP, WS payloads, schemas, TS types, tests, docs)
     - `Session`/`SessionDTO` naming (not `SessionBlock`)
   - If the system truly wants `session_blocks`, then the backend implementation must be updated to match that model consistently (tables, services, DTOs, and orchestrator semantics).
2. **Remove or archive contradictory documentation**:
   - Either remove `docs/session_block_lifecycle.md` or clearly mark it as archived if the implementation is “sessions”.
3. **Regenerate and validate artifacts (Docker-first)**:
   - Regenerate schemas (backend): `make generate-schemas`
   - Regenerate frontend types (frontend): `docker compose run --rm frontend npm run generate:types`
   - Ensure the generated files match committed expectations and that frontend type imports actually resolve.
4. **Make CI strict**:
   - Stop allowing type-check failures to pass silently (avoid `|| true` for `npm run type-check`).
   - Add a “dirty tree” check after schema/type generation to ensure committed artifacts are up-to-date.

**Why this aligns with design principles**
- Restores “Backend Pydantic models as source of truth” and ensures stable cross-process contracts.

### P0 — Reintroduce a Single Source of Truth for the WebSocket Protocol
Currently there are multiple protocol constant definitions across backend/frontend/console, and the generator expects `schemas/ws_protocol.json` but it is missing.

**What to do**
1. Add `schemas/ws_protocol.json` as the canonical message type/version inventory.
2. Run `scripts/generate_ws_protocol.py` to generate:
   - `src/psychoanalyst_app/utils/ws_protocol.py`
   - `console-ui/src/websocket_protocol.py`
   - `frontend/src/types/ws_protocol.generated.ts`
3. Remove duplicated manual constants:
   - Prefer importing the generated constants from one place (or re-exporting them).
   - Keep `docs/WEBSOCKET_PROTOCOL.md` as the narrative spec; keep `schemas/ws_protocol.json` as the machine-readable inventory.

**Why this aligns with design principles**
- Enforces stable boundary contracts across all clients with minimal human error.

### P0/P1 — Remove Dead or Broken Modules and Outdated Paths
Lean architecture requires removing misleading or broken code paths.

**Observed issues**
- `src/psychoanalyst_app/gateways/__init__.py` imports a missing module (`websocket_gateway`), indicating a stale package.
- Presence of “session_block” vocabulary in tests and docs that no longer matches core runtime concepts.

**What to do**
- Delete or repair the `gateways` package so imports don’t break unexpectedly.
- Identify other “legacy leftovers” (unused scripts, old naming, outdated docs) and either:
  - move them to `docs/archive/` (for docs), or
  - remove them (for code) once confirmed unused.

### P1 — Tighten Layer Boundaries (Agents vs Orchestration vs Services)
The codebase already has the right conceptual layers, but the boundaries are porous in places.

**What to do**
- Make `ConversationContext` the primary “read model” for agents:
  - include only the data agents need for decisions (profile, plan, recent messages, timing, possibly precomputed briefing/context)
  - do not require agents to call DB for routine reads during message processing
- Keep agent outputs structured:
  - Use LLM structured outputs for internal decisions and data updates (already supported by `LLMService.generate_structured_output_async`).
  - Avoid regex parsing and implicit “signature phrases” to detect state (“Based on our intake session…”); replace with explicit orchestrator-owned state flags and WS events.
- Standardize agent outputs:
  - Prefer `workflow_event` over `next_state` and keep transitions orchestrator-owned.
  - Define a small enum (or Literal union) for `next_action` values to prevent accidental divergence (`continue`, `transition`, `wait`, `end_session`, etc.).

### P1 — Database Executor and Persistence Hardening
**What to do**
- Fix pooled connection “row_factory leakage” by restoring the previous `row_factory` after each `executor.connection(row_factory=...)` block.
- Consider normalizing persistence for transcripts:
  - current pattern appends to an in-memory transcript and persists the full session record; this is simple but may become expensive and makes concurrent updates harder
  - a future “messages table” would allow append-only writes and easier querying, while keeping the `SessionDTO` shape unchanged.
- Document immutability rules (Tier 2 enrichment) as hard constraints with explicit error messages and tests.

### P1 — Logging, Privacy, and Operational Defaults
**What to do**
- Remove `INFO` logs that are labeled “DEBUG:” and move them to DEBUG level.
- Add a configuration toggle for transcript/prompt logging:
  - current LLM call logging records prompts and context at INFO into `logs/llm_calls.log`; this is useful but can leak sensitive content
  - implement opt-in redaction or per-environment logging policies (production vs dev/test)
- Standardize time sources:
  - choose timezone-aware UTC (`datetime.now(timezone.utc)`) end-to-end for persisted timestamps and log correlation.

### P2 — Frontend Structure and Type Usage
**What to do**
- Once schemas/types are regenerated, ensure frontend compiles with strict type checking:
  - `frontend/src/types/index.ts` should match what `frontend/src/types/generated/api.ts` exports.
  - Ensure API request types match backend DTOs (`session_id` vs `session_block_id`).
- Consolidate WS types:
  - Prefer generated `ws_protocol.generated.ts` as the constant source, and layer richer TS interfaces separately if needed.
- Consider generating a small typed API wrapper per endpoint group (user/session/workflow/therapy) that:
  - uses the generated DTO types directly
  - centralizes query-string construction and error handling

### P2 — Testing and Determinism Improvements
**What to do**
- Add regression tests for known workflow/time bugs (notably abrupt intake end).
- Add contract tests:
  - verify that schema generation output matches current DTO models
  - verify that frontend generated types correspond to schema inventory
- Remove or update stale tests that still reference `session_block_id` or outdated models.

## Lean Structure Proposal (Non-Disruptive Refactor)

The current directory layout is close to the intended architecture, but you can make it more “self-documenting” with small changes that don’t require a big rewrite:

- Keep `src/psychoanalyst_app/api/` as the gateway layer, but consider splitting by transport:
  - `api/http/*_routes.py`
  - `api/ws/ws_handler.py`
- Keep `src/psychoanalyst_app/orchestration/` as “application logic”, but formalize subpackages:
  - `orchestration/workflow/` (state machine, next-action resolver)
  - `orchestration/session/` (session lifecycle, timers, end-session rules)
  - `orchestration/streaming/` (conversation manager, WS emit helpers)
- Keep `src/psychoanalyst_app/agents/` for business logic:
  - push extraction/formatting into `agents/<agent_name>/helpers.py` (already happening for reflection/planning)
  - minimize direct DB/RAG calls from agents by enriching `ConversationContext`
- Keep `src/psychoanalyst_app/services/` as infrastructure:
  - DB executor + repos as a stable boundary
  - LLM and RAG services as infrastructure with deterministic fakes in `src/psychoanalyst_app/testing/`

## Documentation Extensions (Recommended)

To keep the system maintainable as complexity grows, extend docs in these specific ways:

1. **Contract hygiene**
   - Update `docs/TYPE_SYSTEM.md` to reflect the actual schema inventory and generation commands (and remove references to files that are no longer produced).
   - Add a short “Contract drift checklist” section to `docs/design-principles.md` or `docs/contracts/HTTP_API_CONTRACT.md` describing what must be updated together when DTOs change.

2. **WebSocket protocol source of truth**
   - Add a doc section describing how `schemas/ws_protocol.json` relates to `docs/WEBSOCKET_PROTOCOL.md` and how to regenerate protocol constants.

3. **Lifecycle documentation de-duplication**
   - Either consolidate `docs/session_lifecycle.md` and `docs/session_block_lifecycle.md` or archive one with a clear note.

4. **ADRs (Architecture Decision Records)**
   - Add `docs/adr/` with 1-page ADRs for:
     - Trio-first decision
     - “Streaming-first” UX
     - DTO/schema type pipeline
     - SQLite + immutability/enrichment rules

5. **Operational runbooks**
   - Add `docs/runbooks/`:
     - “Schema/type regeneration”
     - “Debugging workflow state issues”
     - “Investigating streaming hangs”
     - “Data reset and migrations”

6. **Security & privacy posture**
   - Add `docs/security.md` documenting:
     - what `session_id` represents (auth token vs correlation id)
     - where sensitive transcript data is logged and how to disable/redact it

## Suggested 2-Phase Implementation Plan

### Phase A (P0, 1–3 days): Restore invariants
- Choose canonical `session_id` vs `session_block_id` naming and apply everywhere.
- Regenerate schemas + frontend types; fix any broken imports/types.
- Add `schemas/ws_protocol.json` and regenerate WS constants; remove duplicated sources.
- Make CI fail on drift and type-check errors.

### Phase B (P1/P2, 1–2 weeks): Lean refactors
- Tighten boundaries: enrich context, reduce agent I/O, consolidate workflow/session lifecycle rules.
- Improve DB executor safety and document immutability constraints.
- Add regression and contract tests for key workflow/time edge cases.

## Appendix: Concrete Drift Examples Observed

These are representative examples of misalignment that should be resolved under P0:
- `schemas/PatchUserProfileRequest.json` requires `session_block_id`, while backend request DTOs and routes use `session_id`.
- `schemas/SessionBlock.json` exists, while the backend and contract docs describe `Session`/`session_id`.
- `frontend/src/types/generated/api.ts` exports `SessionBlockDTO` rather than `Session`, but `frontend/src/types/index.ts` imports `Session`.
- `docs/session_block_lifecycle.md` describes a `session_blocks` table, but the DB layer is built around `sessions`.
- `src/psychoanalyst_app/gateways/__init__.py` imports a missing module, indicating stale package structure.

