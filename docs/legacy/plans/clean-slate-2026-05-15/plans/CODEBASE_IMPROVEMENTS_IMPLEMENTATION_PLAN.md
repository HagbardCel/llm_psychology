# Codebase Improvements Implementation Plan

**Source assessment**: `docs/assessments/project/CODEBASE_ASSESSMENT_2025-12-22.md`  
**Scope**: Backend (`src/`), frontend (`frontend/`), console UI (`console-ui/`), tooling (`scripts/`, `schemas/`, `Makefile`), documentation (`docs/`).  
**Execution constraint**: Docker-only commands (see `AGENTS.md`).  
**Primary goal**: Lean, maintainable, reusable architecture with minimal behavioral change.  
**Non-goals**: Security hardening, large feature additions, major UX redesign, or protocol changes outside documented contracts.

---

## Guiding Principles

- Preserve Trio structured concurrency and layering boundaries (gateway → orchestration → agents → services).
- Prefer reuse over duplication; remove transitional abstractions.
- Keep contracts stable; update docs and schemas when contracts change.
- Favor small, reviewable changes with explicit acceptance criteria.
- All commands and tests run inside containers.

---

## Workstreams Overview

1) **Contracts & Type Pipeline**  
2) **Configuration & DI Consistency**  
3) **Persistence Layer Consolidation**  
4) **Orchestration and Agent Slimming**  
5) **Prompt Composition Consolidation**  
6) **WebSocket/Streaming Alignment**  
7) **Frontend Cleanup & Consistency**  
8) **Docs & Tooling Alignment**

Each workstream is broken into phases below. Phases are sequenced to reduce downstream churn.

---

## Phase 0 — Alignment & Cleanup (1–2 days)

**Goal**: Remove obvious drift and unblock downstream work.

### Tasks

- **Schema location decision**
  - Choose a canonical schema output directory: `schemas/` (root) vs `src/psychoanalyst_app/schemas/`.
  - Update schema generator (`src/psychoanalyst_app/schemas/generate_schemas.py`) and validator (`scripts/validate_schemas.py`) to use the same location.
  - Update frontend generation (`frontend/scripts/generate-types.js`) if the canonical path changes.

- **Settings cleanup**
  - Remove duplicate fields (e.g., duplicate `APP_ENV`) from `src/psychoanalyst_app/config.py`.
  - Decide on a single env var name for the Gemini key (keep alias only if required).

- **Code hygiene fixes**
  - Add missing logger import in `src/psychoanalyst_app/utils/trio_streaming.py`.
  - Remove unused imports (example: `LLMChain` in `src/psychoanalyst_app/services/llm_service.py` if unused).

- **Docs quick alignment**
  - Update `docs/TECH_STACK.md` to reflect FAISS (not ChromaDB).
  - Update `docs/ARCHITECTURE.md` to reflect native WebSocket (not Socket.IO).
  - Update `docs/TYPE_SYSTEM.md` examples to use `data_of_birth` (not `birthdate`).

### Acceptance Criteria

- Schema generation, validation, and frontend type generation all read/write the same schema directory.
- `Settings` has no duplicate fields and a single canonical API key name (with optional alias if required).
- No obvious unused imports or missing logger references in critical helper modules.
- Docs reflect actual runtime technologies and field names.

### Tests (Docker-only)

- `docker compose run --rm api python scripts/validate_schemas.py`
- `docker compose run --rm frontend npm run generate:types`

---

## Phase 1 — Contract & Type Stability (2–4 days)

**Goal**: Enforce DTO-first boundaries across HTTP and keep frontend types fully aligned.

### Tasks

- Audit HTTP endpoints to ensure responses use DTOs from `src/psychoanalyst_app/models/http_models.py`.
- If any endpoint returns internal models, add explicit DTO conversions (`*_to_dto`) at the route layer.
- Ensure schema generation includes all HTTP DTOs and excludes internal-only models.
- Confirm the frontend uses generated DTOs as the default import source.
- Remove any legacy manual type aliases that duplicate generated DTOs (or document why they remain).

### Acceptance Criteria

- All HTTP responses are serialized from DTOs (not internal models).
- Regenerated JSON schemas reflect the DTO shapes used on the wire.
- Frontend types compile against generated DTOs without manual mapping for core API types.

### Tests (Docker-only)

- `docker compose run --rm api python scripts/generate_schemas.py`
- `docker compose run --rm api python scripts/validate_schemas.py`
- `docker compose run --rm frontend npm run generate:types`
- `docker compose run --rm frontend npm run lint`

---

## Phase 2 — Configuration & DI Consistency (2–3 days)

**Goal**: One consistent dependency injection path for services and settings.

### Tasks

- Remove module-level `settings` usage in favor of container-provided `Settings` where feasible.
- Update `TrioConversationManager` to use injected configuration instead of `config.settings` singleton.
- Move `AuthService` creation into `ServiceContainer` to keep all services DI-managed.
- Update `TrioServer` to use container-managed `AuthService`.

### Acceptance Criteria

- No runtime-critical components depend on module-level `settings` directly (except for clearly documented exceptions).
- `AuthService` is constructed in the container and injected into `TrioServer`.

### Tests (Docker-only)

- `docker compose run --rm api pytest tests/unit/test_service_container.py`
- `docker compose run --rm api pytest tests/unit/test_trio_server.py`

---

## Phase 3 — Persistence Layer Consolidation (3–5 days)

**Goal**: Remove redundant DB abstractions and reduce SQL mapping duplication.

### Decision Required (choose one)

- **Option A (recommended)**: Keep `TrioDatabaseService` as primary API; remove repository classes in `services/db/repositories.py` and avoid container registration for them.
- **Option B**: Keep repository classes and reduce `TrioDatabaseService` to a thin facade (or remove it entirely).

### Tasks (Option A)

- Remove unused repository classes and container factories for them.
- Keep `services/db/repos/*` as low-level query modules.
- Add shared helper(s) for common column lists and row-to-model mapping (e.g., in `services/db_serialization.py`).

### Tasks (Option B)

- Move all DB operations to repository classes and update call sites to use them.
- Slim `TrioDatabaseService` or replace it entirely.

### Acceptance Criteria

- Exactly one persistence abstraction is used by orchestrator and services.
- SQL mapping logic is centralized for repeated columns and conversions.

### Tests (Docker-only)

- `docker compose run --rm api pytest tests/unit/test_trio_db_service.py`
- `docker compose run --rm api pytest tests/integration/test_trio_orchestration.py`

---

## Phase 4 — Orchestration & Agent Slimming (4–6 days)

**Goal**: Reduce orchestrator and agent complexity by extracting reusable helpers.

### Tasks

- Split `TrioAgentOrchestrator` into focused helpers:
  - Session lifecycle (create/extend/end)
  - Profile creation/updates
  - Workflow transition handling
  - Greeting and streaming helpers
- Extract shared agent parsing logic (style selection, continuation intent) into a reusable helper module (e.g., `src/psychoanalyst_app/agents/parsing.py`).
- Create a profile merge helper to replace the large parameter list in `create_user_profile`.
- Add small helper constructors for `AgentResponse` to standardize responses.

### Acceptance Criteria

- `TrioAgentOrchestrator` is structurally smaller and easier to scan.
- Parsing logic is reused across assessment/planning/reflection agents without duplication.
- Profile updates use a reusable helper with clear semantics.

### Tests (Docker-only)

- `docker compose run --rm api pytest tests/unit/test_trio_agent_orchestrator.py`
- `docker compose run --rm api pytest tests/integration/test_trio_flow.py`

---

## Phase 5 — Prompt Composition Consolidation (2–4 days)

**Goal**: Make prompt construction consistent and reusable across agents.

### Tasks

- Consolidate prompt composition into a single module area under `src/psychoanalyst_app/prompts/`.
- Ensure style-specific prompt retrieval is centralized (avoid duplicated string loads).
- Add prompt builders for any agent that currently assembles large prompt strings inline.

### Acceptance Criteria

- Prompt construction is concentrated in one location and reused across agents.
- Agents read prompts through builders or `StyleService`, not ad-hoc file loads.

### Tests (Docker-only)

- `docker compose run --rm api pytest tests/unit/test_trio_psychoanalyst_agent.py`
- `docker compose run --rm api pytest tests/unit/test_trio_reflection_agent.py`

---

## Phase 6 — WebSocket & Streaming Alignment (2–3 days)

**Goal**: Align implementation and documentation for WS protocol and streaming.

### Tasks

- Ensure `iter_in_thread` logs correctly and remains safe under cancellation.
- Align `docs/WEBSOCKET_PROTOCOL.md` with actual message types emitted by `ws_handler.py` and `utils/ws_messages.py`.
- Optional: add protocol version field or explicit “unsupported/optional messages” section in docs.

### Acceptance Criteria

- Protocol docs match the server’s real message set.
- Streaming helper has correct logging and no missing references.

### Tests (Docker-only)

- `docker compose run --rm api pytest tests/integration/test_websocket_protocol_contract.py`

---

## Phase 7 — Frontend Cleanup & Consistency (3–5 days)

**Goal**: Remove HTTP duplication and unused dependencies; reduce TODO noise.

### Tasks

- Route `AuthContext` calls through `apiClient` (single HTTP abstraction).
- Remove unused dependencies (`axios`) and adjust any tooling if needed.
- Resolve or explicitly defer TODO features in:
  - `frontend/src/pages/SettingsPage.tsx`
  - `frontend/src/components/Navigation.tsx`
  - `frontend/src/components/MessageInput.tsx`
  - `frontend/src/components/TherapySession.tsx`
- Prefer generated types for API payloads; use small adapters for UI-only fields.

### Acceptance Criteria

- All frontend HTTP calls flow through `apiClient`.
- Unused dependencies removed; `npm run lint` passes.
- TODOs are either implemented or gated with a clear “not yet supported” UX.

### Tests (Docker-only)

- `docker compose run --rm frontend npm run lint`
- `docker compose run --rm frontend npm run test`

---

## Phase 8 — Docs & Tooling Alignment (2–3 days)

**Goal**: Make documentation and tooling consistent with Docker-only execution.

### Tasks

- Update `Makefile` targets to call Docker-based commands (or document local usage as optional).
- Add “Docker-only commands” section to `docs/README.md` or `docs/TECH_STACK.md`.
- Add “Last verified” dates to docs likely to drift (`docs/ARCHITECTURE.md`, `docs/TECH_STACK.md`, `docs/TYPE_SYSTEM.md`, `docs/WEBSOCKET_PROTOCOL.md`).
- Remove or ignore runtime artifacts (e.g., `app.log`, `out_test_*`) via `.gitignore` or cleanup targets.

### Acceptance Criteria

- Developer instructions in docs match the Makefile.
- No runtime artifacts tracked in the repo root.

### Tests (Docker-only)

- `docker compose run --rm api python scripts/validate_schemas.py`
- `docker compose run --rm frontend npm run generate:types`

---

## Cross-Cutting Acceptance Criteria

- No contract changes without updating:
  - `docs/contracts/HTTP_API_CONTRACT.md`
  - `docs/WEBSOCKET_PROTOCOL.md`
  - JSON schemas (`schemas/*.json`)
  - Generated frontend types
- Orchestrator, agents, and services keep Trio structured concurrency patterns.
- No new asyncio usage.

---

## Risk Management

- **Schema/Type drift**: Mitigated by canonical schema output and validation gate.
- **Large refactors**: Phase splitting keeps each change small and reversible.
- **Hidden coupling**: Add focused unit tests around refactored helpers (parsing, prompt builders, DB mapping).

---

## Suggested Execution Order

1) Phase 0 (alignment)  
2) Phase 1 (contracts/types)  
3) Phase 2 (DI/config)  
4) Phase 3 (persistence)  
5) Phase 4 (orchestrator/agents)  
6) Phase 5 (prompts)  
7) Phase 6 (WS/streaming docs)  
8) Phase 7 (frontend)  
9) Phase 8 (docs/tooling)

---

## Open Decisions to Confirm

- Canonical schema output directory.
- Persistence abstraction choice (Option A vs Option B).
- Whether to keep a `settings` module singleton or move all config into DI.
- How to handle TODO UI features (implement now vs defer with explicit UI gating).

---

## Notes on Docker-Only Execution

All commands in this plan are written in Docker form to comply with project guidance. If you decide to allow local execution, update the Makefile and docs together so the workflow remains consistent.
