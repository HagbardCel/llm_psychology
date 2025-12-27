# Phase 5 — Module Splits (DB, Server, Agents) (Detailed Implementation Plan)

Source: `docs/assessments/project/CODEBASE_ASSESSMENT_2025-12-16.md` (Phase 5 — Module Splits)

## Objective

Reduce “mega-file” maintenance risk by splitting the largest backend modules into cohesive units with clear responsibilities, while preserving:
- the Trio-first runtime model,
- the stable boundary contracts (HTTP DTOs + WebSocket protocol),
- and the DI container as the single composition root.

This phase is primarily a **structural refactor**: behavior should remain unchanged except where the refactor reveals small correctness issues that must be fixed to complete the split safely.

## Inputs and Constraints (Carry-Forward From Phases 1–4)

### Phase 1 Contract Decisions (must remain true)
- **D1 (Field naming)**: HTTP DTOs use `snake_case` keys end-to-end; generated TypeScript preserves wire keys.
- **D2 (Datetimes)**: HTTP datetimes are ISO 8601 strings; frontend types keep them as `string` (no implicit decoding).

Phase 5 must not introduce new mapping/conversion layers that undermine D1/D2.

### Phase 2 Workflow Decision (must remain true)
- Proceed with **backend-driven navigation** using `POST /api/workflow/next-action`.
- WebSocket workflow/session behavior must not regress.

### Phase 3 DI/Composition Target (must remain true)
- The DI container (`src/container/service_container.py`) remains the composition root.
- No new module-level runtime singletons.

### Phase 4 Utilities (assumed available)
This plan assumes Phase 4 utilities exist and should be reused rather than re-implemented:
- Trio streaming bridge: `src/utils/trio_streaming.py`
- WS message helpers: `src/utils/ws_messages.py`
- DB serialization helpers: `src/services/db_serialization.py` (or equivalent)

## Non-goals (Explicitly Out of Scope)
- Changing the HTTP API contract (Phase 1).
- Changing workflow semantics or UI routing/product behavior (Phase 2).
- Reworking DI design (Phase 3) beyond wiring changes required by splits.
- WebSocket protocol redesign (message types/shapes stay stable).
- SQLite schema redesign (migrations can be added only if strictly required to keep current behavior correct).

## Phase 5 Scope (What We Touch)

### A) Database layer split
Target: `src/services/trio_db_service.py` (~2000 LOC) → domain-focused “repos” + shared DB executor/pool.

### B) Server/gateway split
Target: `src/trio_server.py` (~700 LOC) → route modules (blueprints) + small composition entry.

### C) Agent splits (Reflection/Planning)
Targets:
- `src/agents/trio_reflection_agent.py` (~1350 LOC)
- `src/agents/trio_planning_agent.py` (~1038 LOC)

Split into focused components:
- prompt builders / formatters
- structured-output extractors
- persistence/updaters (ideally in services/repo layer)

## Key Decisions (Lock These Early)

### D5.1 DB split pattern: “shared executor + domain repos + optional facade”
Adopt the repository approach without breaking call sites abruptly:
- Introduce a shared Trio-friendly SQLite executor/pool (single responsibility: run SQL safely in threads).
- Create domain repositories with small, typed methods.
- Keep a transitional facade (`TrioDatabaseService`) that delegates to repos until call sites are migrated.

Rationale (aligned with `docs/design-principles.md`):
- Preserves “sync DB, async shell” and the connection-pool design.
- Improves testability and isolates serialization logic.
- Allows incremental PRs with minimal blast radius.

### D5.2 Server split pattern: “TrioServer composes, route modules own handlers”
Keep `TrioServer` as the lifecycle/composition owner (app creation, middleware, nursery ownership), but move:
- HTTP handlers into route modules (prefer Quart `Blueprint`s),
- WebSocket handler wiring into a dedicated WS module (registered by `TrioServer`).

### D5.3 Agent split pattern: “agent orchestrates; helpers do the work”
Keep agent public APIs stable, but move:
- prompt formatting into prompt-builder modules under `src/prompts/` (pure functions where possible),
- structured-output extraction into small, typed “extractor” utilities,
- DB writes/versioning logic into services that depend on the new repos.

Design rule alignment:
- Agents remain “decision + prompt builders” (from `docs/design-principles.md`), and persistence becomes service-layer behavior.

## Implementation Plan

### P5.1 Split `TrioDatabaseService` into a shared DB executor + domain repositories

**Goal**
Decompose `src/services/trio_db_service.py` into cohesive units without changing behavior or schema.

**Proposed module layout**
- `src/services/db/`
  - `executor.py` (pool + acquire/release + thread boundary helpers)
  - `repos/`
    - `sessions_repo.py` (sessions, transcripts, session details, timers, counts)
    - `therapy_plans_repo.py` (plan CRUD, latest plan retrieval)
    - `users_repo.py` (user profile + status)
    - `auth_repo.py` (credentials, last_login, username lookup)
    - `patient_profiles_repo.py` (patient profile + history)
    - `enrichment_jobs_repo.py` (queue/claim/mark complete/failed)
    - `patient_analysis_repo.py` (analysis versions, history, supersede logic)
  - `types.py` (optional: shared row types / small DTOs used by repos)
- `src/services/trio_db_service.py` (transitional facade that delegates to repos)

**Refactor approach**
1. Extract pool/executor logic first (connection creation, acquire/release, `to_thread` wrapper, health check).
2. Move one domain at a time into repos, preserving method names/signatures on the facade until call sites migrate.
3. Centralize JSON serialization/deserialization through the Phase 4 helper (`src/services/db_serialization.py`), not inside repos.

**Acceptance**
- All tests pass with no behavioral changes.
- Call sites can continue importing `TrioDatabaseService` during transition.
- Each repo contains one domain and does not “reach across” into others except via explicit, typed inputs.

### P5.2 Update DI wiring to construct repos once and inject them consistently

**Goal**
Keep the container as the sole composition root while introducing new repo services.

**Changes**
- `src/container/service_container.py`
  - Construct and cache the DB executor/pool once.
  - Construct repos as singletons that share the executor.
  - Provide either:
    - `container.get("trio_db_service")` returning the transitional facade, or
    - direct repo access via keys (`sessions_repo`, `therapy_plans_repo`, …) for migrated call sites.

**Acceptance**
- No module-level globals are introduced.
- Tests can override individual repos/services via `container.register(...)` / `register_factory(...)`.

### P5.3 Split `TrioServer` HTTP routes into blueprint modules

**Goal**
Reduce `src/trio_server.py` to a small “server composition” module that registers route groups.

**Proposed route modules**
- Existing:
  - `src/api/auth_routes.py` (already blueprint-based)
  - `src/api/version_routes.py` (already blueprint-based)
- New:
  - `src/api/health_routes.py` (`GET /health`)
  - `src/api/user_routes.py` (`/api/user/*`)
  - `src/api/session_routes.py` (`/api/sessions*` + timer/extend)
  - `src/api/therapy_routes.py` (`/api/therapy/*` + styles + plan)
  - `src/api/workflow_routes.py` (`POST /api/workflow/next-action`)

**WebSocket**
- Create `src/api/ws_routes.py` (or `src/ws/handler.py`) with a single “register” function that attaches the WS endpoint to the Quart app and delegates message handling to orchestration.
- Continue using `src/utils/ws_messages.py` for message envelopes.

**Middleware**
- Move compression middleware to `src/api/middleware/compression.py` (optional but recommended) and keep registration in `TrioServer.__init__`.

**Acceptance**
- Route paths, request/response bodies, and status codes remain identical (Phase 1 contract remains stable).
- `src/trio_server.py` primarily performs:
  - app construction (QuartTrio + CORS),
  - middleware registration,
  - blueprint registration,
  - WS endpoint registration,
  - server run lifecycle.

### P5.4 Clarify “workflow next action” ownership

**Goal**
Move `_determine_next_action(...)` out of `TrioServer` into a single obvious location.

**Options (choose one)**
- **Option A (recommended): orchestration-owned**: create `src/orchestration/workflow_next_action.py` with a pure function (inputs: profile/status/session/plan) so both HTTP and WS flows can reuse it.
- **Option B: API-owned**: keep the logic within `src/api/workflow_routes.py` only.

**Acceptance**
- There is exactly one implementation of “next action selection” and it is unit-tested.

### P5.5 Split `TrioReflectionAgent` into prompt builders, structured extractors, and persistence services

**Goal**
Make reflection behavior easier to understand and maintain by splitting responsibilities without changing outcomes.

**Proposed internal modules**
- Prompts/formatting (pure):
  - `src/prompts/reflection_prompt_builder.py`
    - converts typed inputs (`Session`, `UserProfile`, `TherapyPlan`, `SessionBriefing`, Tier 3 state) into prompt strings
    - preserves existing prompt templates in `src/prompts/reflection_prompts.py` (constants) but moves assembly logic out of the agent
- Structured output extraction:
  - `src/agents/reflection/extractors.py`
    - wrappers for `LLMService.generate_structured_output(...)`
    - common error handling for `ValidationError` and “retry with repaired prompt” patterns (if already used)
    - returns typed models (`Tier2Enrichment`, `Tier1ProfilePatch`, `ChangeDetectionDecision`, …)
- Persistence/updaters:
  - `src/services/reflection_persistence_service.py`
    - depends on repos (sessions, patient analysis, enrichment jobs)
    - encapsulates:
      - Tier 2 enrichment persistence
      - patient analysis versioning/supersede logic
      - “ensure recent sessions enriched” job orchestration (DB-level operations only)

**Agent after split**
`src/agents/trio_reflection_agent.py` remains the public class, but becomes mostly orchestration:
- fetch required domain data,
- call prompt builder + extractor,
- delegate persistence to the persistence service,
- return `AgentResponse` for orchestration layer streaming.

**Acceptance**
- Public behavior and outputs remain the same.
- The reflection agent file becomes substantially smaller and mostly reads as a high-level flow.

### P5.6 Split `TrioPlanningAgent` into planning logic, formatting, and extraction helpers

**Goal**
Reduce `src/agents/trio_planning_agent.py` size and isolate plan-generation logic from I/O.

**Proposed internal modules**
- `src/agents/planning/models.py`:
  - `PlanEvolution`, `PlanningStrategy`
- `src/agents/planning/formatting.py`:
  - `_format_plan_details`, bullet splitting, user-facing formatting helpers
- `src/agents/planning/analysis.py`:
  - “update necessity” decision logic
  - change identification + scoring helpers (pure functions)
- `src/agents/planning/extractors.py`:
  - wrappers around structured output parsing (`PlanUpdate`, initial plan schema, etc.)
- `src/prompts/planning_prompt_builder.py` (optional):
  - typed inputs → prompt strings for initial and updated plan prompts

**Persistence**
Use the new DB repos for plan read/write operations (or keep the transitional facade until migration completes).

**Acceptance**
- Planning agent remains the main entry point but reads as “orchestrate helpers + persist”.
- Pure helpers are unit-testable without DB/LLM.

### P5.7 “Module split hygiene”: imports, public APIs, and deprecation strategy

**Goal**
Avoid a long-lived half-migrated state that confuses contributors.

**Rules**
- Prefer stable import paths for external consumers:
  - keep `TrioDatabaseService` importable from `src/services/trio_db_service.py` during transition
  - keep `TrioServer` importable from `src/trio_server.py`
  - keep `TrioReflectionAgent` and `TrioPlanningAgent` importable from their current locations
- New internal modules should not be imported directly from unrelated layers (e.g., UI/gateway should not import agent internals).
- When transitional shims exist, mark them as transitional in docstrings and include a removal checklist for the next phase.

## Validation Checklist

### Static checks (fast)
- `rg \"from services\\.trio_db_service import\" src` only appears where intended (or is shrinking PR-by-PR).
- `rg \"def _setup_http_routes\\(\" src/trio_server.py` no longer exists (routes moved to `src/api/*`).
- `ruff` and `mypy` run cleanly for modified modules (repo-standard targets).

### Tests (recommended)
- Backend unit/integration subset that covers:
  - HTTP contract endpoints (Phase 1)
  - WebSocket protocol contract: `tests/integration/test_websocket_protocol_contract.py`
  - Orchestration flow tests (if present)
- Run the deterministic E2E server tests if they exist for your workflow (no network required).

## Suggested PR Breakdown (Minimize Risk)

1) **PR 1 — DB executor extraction + facade wiring**
   - Introduce `src/services/db/executor.py`
   - Wire `TrioDatabaseService` to delegate acquire/release to the executor

2) **PR 2 — DB repos: sessions + plans**
   - Extract `sessions_repo.py` + `therapy_plans_repo.py`
   - Keep facade method names stable; update the container

3) **PR 3 — DB repos: users + auth**
   - Extract `users_repo.py` + `auth_repo.py`

4) **PR 4 — DB repos: enrichment + patient analysis**
   - Extract `enrichment_jobs_repo.py` + `patient_analysis_repo.py` (+ patient profiles if needed)

5) **PR 5 — Server route modules**
   - Introduce blueprints for health/user/sessions/therapy/workflow
   - `src/trio_server.py` becomes registration + lifecycle only

6) **PR 6 — Reflection agent split**
   - Extract prompt builder + extractor + persistence service
   - Keep public agent API stable

7) **PR 7 — Planning agent split**
   - Extract models/analysis/formatting/extractors
   - Add focused unit tests for pure helpers

## Exit Criteria (Phase 5 is Done When…)

- **DB layer**: `TrioDatabaseService` is no longer a “dumping ground”; domain repos exist and are the primary home for DB operations.
- **Server layer**: `src/trio_server.py` is a small composition module; HTTP routes live in `src/api/*` and are grouped by domain.
- **Agents**: `TrioReflectionAgent` and `TrioPlanningAgent` are readable orchestration shells; prompt construction, extraction, and persistence are in separate modules.
- **No regressions**: Phase 1 HTTP contract, Phase 2 workflow behavior, and WebSocket protocol contract remain stable.

## Required Documentation Updates (Post-Implementation)

After the module split is implemented, update `docs/design-principles.md` to remove drift and keep it a reliable onboarding “mental model”:

1. **Canonical file references**
   - Replace references to `src/services/trio_db_service.py` with the new DB executor + repo paths.
   - Replace “Gateway: `src/trio_server.py`” with the new route module layout (and keep `src/trio_server.py` as the composition root reference).
   - Update “Start here in code” to match the new entry points for HTTP and WS routing.

2. **Persistence section wording**
   - Document the repo split and clarify that “repos share the Trio SQLite executor/pool”.

3. **Playbooks**
   - Update “Add a new HTTP endpoint” to reference `src/api/<domain>_routes.py` (blueprints) rather than adding handlers directly to `src/trio_server.py`.

4. **Optional (recommended)**
   - If `docs/ARCHITECTURE.md` contains deep-links into old mega-files, update those references for consistency.
