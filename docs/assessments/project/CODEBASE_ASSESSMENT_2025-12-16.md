# Comprehensive Codebase Assessment & Improvement Plan (2025-12-16)

**Repository**: `psychoanalyst_app/`  
**Scope**: Backend (`src/`), Console UI (`console-ui/`), Web Frontend (`frontend/`), tooling (`scripts/`, `schemas/`), tests (`tests/`), docs (`docs/`).  
**Assumptions from request**: Runs locally for 1–few users; prioritize lean, maintainable, best-practice code; maximize reuse where it creates synergy; extensive security/error-hardening is *not* a goal.

---

## Executive Summary

The codebase has a strong foundation: a complete Trio migration, a clear agent/orchestration architecture, deterministic fakes for E2E, and a schema→TypeScript generation pipeline. The main issue is **integration drift**: frontend expectations do not match backend HTTP responses, several backend endpoints are placeholders, and there’s inconsistent usage of dependency injection vs. global singletons. The second major issue is **consolidation**: a handful of very large modules (DB service, orchestrator, server, reflection/planning agents) concentrate too many responsibilities and contain repeated patterns that should be factored into reusable helpers or split into focused modules.

If the goal is “lean & maintainable,” the shortest path is:

1. **Stabilize the API contract** (backend responses ↔ frontend types/hooks) and finish “backend-driven navigation” consistently across all pages.
2. **Make DI consistent** (remove/avoid global singletons like `style_service` and stop duplicating agent factory logic).
3. **Split oversized modules** into cohesive units and introduce a small set of reusable helpers (DB serialization, prompt composition, WebSocket message envelope, streaming bridge).
4. **Fix doc drift** (FAISS vs ChromaDB, Python version targets, workflow routes).

---

## Codebase Map (What’s Here)

### Backend (`src/`)

- **Entry points**
  - `src/main.py`: standalone terminal UI (no Docker).
  - `src/server.py`: server entry (runs `run_trio_server`).
  - `src/trio_server.py`: QuartTrio + Hypercorn server (HTTP + WebSocket).
  - `src/e2e_server.py`: deterministic backend for Playwright E2E (no network).
- **Architecture**
  - `src/orchestration/*`: workflow state machine + conversation manager + orchestrator.
  - `src/agents/*`: Trio agents (intake/assessment/psychoanalyst/reflection/memory/planning).
  - `src/services/*`: DB, migrations, LLM, RAG, style packs, auth, enrichment worker.
  - `src/models/*`: Pydantic models (data + API DTOs + structured-output schemas).
  - `src/container/service_container.py`: DI container / service factories.
- **Size hotspots**
  - `src/services/trio_db_service.py` (~2080 LOC)
  - `src/agents/trio_reflection_agent.py` (~1350 LOC)
  - `src/agents/trio_planning_agent.py` (~1038 LOC)
  - `src/orchestration/trio_agent_orchestrator.py` (~807 LOC)
  - `src/trio_server.py` (~722 LOC)

### Console UI (`console-ui/`)

- Trio console client using `trio-websocket` and `httpx`.
- Aligns well with the documented WebSocket protocol (`docs/WEBSOCKET_PROTOCOL.md`).
- Has separate auth flow (`console-ui/src/auth.py`) and version check (`console-ui/src/version_check.py`).

### Web Frontend (`frontend/`)

- React + TS + MUI + Vite + React Query + PWA SW registration.
- WebSocket client (`frontend/src/services/websocketService.ts`) + hooks.
- Type generation pipeline from backend JSON schemas → `frontend/src/types/generated/api.ts`.
- Currently in a “mixed refactor state”: parts moved to React Query + backend-driven navigation, other parts still rely on legacy assumptions and/or placeholder endpoints.

### Tests (`tests/`)

- Strong testing intent: unit + integration + protocol contract tests.
- Uses mocked LLM/RAG by default (good for determinism).
- In this environment, `pytest` is not installed (so tests were not executed here), but the suite itself is structured and maintained.

### Tooling & Docs

- `scripts/generate_schemas.py` and `scripts/validate_schemas.py`: JSON schema pipeline.
- `.github/workflows/type-safety.yml`: generates schemas, generates TS types, builds frontend.
- Docs are extensive (architecture, type system, assessments), but some are outdated vs the current implementation (notably RAG backend and API shapes).

---

## Strengths (Keep and Build On)

### 1) Trio-first architecture is coherent

- Structured concurrency via nurseries is used across server/orchestration/console client.
- Blocking operations correctly use `trio.to_thread.run_sync()` (SQLite, embeddings, LangChain/Gemini).

### 2) Deterministic E2E story exists

- `src/e2e_server.py` + `src/testing/fakes.py` is the right pattern to keep browser tests stable and no-network.

### 3) Clear layering intent

- Orchestration layer (`TrioAgentOrchestrator`, `TrioConversationManager`, `TrioWorkflowEngine`) is the right place for workflow/state and cross-agent coordination.
- Agents generally return `AgentResponse` for the orchestrator to stream (good separation from I/O).

### 4) Schema generation pipeline is valuable

- You already have “backend as source of truth” for shared types via JSON schema + quicktype.
- CI enforces that schemas and frontend builds remain consistent.

---

## High-Impact Findings (What’s Hurting Maintainability)

### A) Backend ↔ Frontend API contract drift (largest practical issue)

Several frontend hooks/services expect shapes that the backend does not return today:

- `GET /api/sessions` returns `Session.model_dump()` (fields like `session_id`, `timestamp`, `transcript`), but frontend expects fields like `start_time`, `agent_type`, `status`, etc. (`frontend/src/hooks/useSessionHistory.ts`).
- `GET /api/therapy/plan` is currently a placeholder in `src/trio_server.py` (`_get_therapy_plan` returns “not implemented”), but frontend uses `useTherapyPlan` and `api.therapy.getPlan`.
- `POST /api/therapy/plan` returns a **UserProfile** (per `src/trio_server.py` `_create_therapy_plan`), but frontend expects a **TherapyPlan** (`frontend/src/services/api.ts`, `frontend/src/hooks/useTherapyPlan.ts`, `frontend/src/pages/AssessmentPage.tsx`).

Impact:
- Frontend refactors become fragile because “type safety” can’t protect runtime drift when endpoints are placeholders or return different objects than expected.

Lean fix direction:
- Pick a single “API DTO” shape per endpoint and enforce it in the backend with explicit API models (Pydantic DTOs) rather than returning internal DB models directly.
- Make frontend use the generated schema types for these DTOs (or keep a minimal mapping layer, but keep it consistent).

### B) Workflow navigation is only partially “backend-driven”

Backend-driven navigation exists (`POST /api/workflow/next-action`) and is used in `Dashboard` + `ProfilePage`, but not consistently in:

- `frontend/src/pages/IntakePage.tsx` (still checks `user.status` and hardcodes navigation)
- `frontend/src/pages/AssessmentPage.tsx` (uses a custom event `assessment-complete` that is never dispatched in the current code)

Additionally, the backend’s `_determine_next_action()` currently routes `PLAN_COMPLETE → /dashboard`, which makes “Continue” on the dashboard navigate to… the same page. If you want “Continue → start therapy”, the mapping should likely be `PLAN_COMPLETE → /session/<new>` or a dedicated “new session” route.

Lean fix direction:
- Make workflow routing consistent: either (a) truly backend-driven everywhere, or (b) accept client-driven routes and remove the “backend-driven navigation” claims/complexity.
- If you keep backend-driven navigation: provide **one canonical mapping** and make all pages follow it (or redirect when they don’t match).

### C) Dependency injection is inconsistent (container vs globals vs duplication)

You have a DI container (`src/container/service_container.py`), but you also have:

- A module-level singleton `style_service = StyleService()` in `src/services/style_service.py`.
- Agents importing `style_service` directly (`trio_assessment_agent.py`, `trio_planning_agent.py`, `trio_psychoanalyst_agent.py`), while `TrioServer` uses `container.get("style_service")`.
- `TrioAgentOrchestrator` contains its own internal agent factory methods (`_create_*_agent`) while `ServiceContainer` also has `create_*_agent` methods.

Impact:
- Harder to test (overriding services is inconsistent).
- Changes to construction/injection need to be made in multiple places.

Lean fix direction:
- Choose one approach: **container creates services + agents** (recommended), and remove global singletons and duplicate factories.
- Make “agent-specific LLM service selection” consistent: right now, streaming uses `llm_service_*` but agent-internal structured calls still use the default `llm_service`.

### D) “Streaming” isn’t truly streaming (UX and correctness drift)

- `LLMService.generate_response_stream()` collects all chunks in a thread and returns `list[str]`.
- `TrioConversationManager._stream_llm_response()` awaits the full list before yielding chunks.

Result: the UX *looks* chunked, but it’s not real-time; the first chunk only arrives after the full generation completes.

Lean fix direction:
- Bridge the blocking iterator to Trio via a `trio.MemorySendChannel`: run the blocking stream in a worker thread and `send()` chunks into the channel as they arrive. Yield from the receive channel in real time. This is a small, high-leverage change.

### E) Oversized modules hide repeated patterns

This is a maintainability problem more than a correctness problem. The following modules are doing too much:

- `src/services/trio_db_service.py`: multiple domains (sessions, users, auth creds, plans, tiered patient info, enrichment jobs) + serialization logic.
- `src/trio_server.py`: WebSocket protocol + all HTTP endpoints + orchestration initialization + compression + CORS.
- `src/orchestration/trio_agent_orchestrator.py`: routing + agent lifecycle + session creation + user/profile/plan business logic + WebSocket greeting workaround.
- `src/agents/trio_reflection_agent.py` and `src/agents/trio_planning_agent.py`: multi-responsibility coordination + persistence + prompt construction + change detection + formatting.

Lean fix direction:
- Split by *domain responsibility* (not by “class size” alone).
- Extract repeated primitives into small helpers (DB row↔model, prompt composition, event/message envelopes).

### F) Configuration and documentation drift

Concrete inconsistencies found:

- `.env.example` uses `GEMINI_API_KEY`, but backend `Settings` expects `GOOGLE_API_KEY`.
- Docs mention ChromaDB in multiple places (`docs/TECH_STACK.md`), but the implementation is FAISS-based (`src/services/rag_service.py`).
- Docs claim Python 3.11+, but formatting/lint config targets 3.10 (`pyproject.toml`), while CI uses Python 3.11 (`.github/workflows/type-safety.yml`).
- `ServiceContainer.shutdown()` tries to close a `_pool` attribute that doesn’t exist on `TrioDatabaseService` (it now uses memory channels).

Lean fix direction:
- Decide on a single supported Python version and align config/docs.
- Align env var names and update `.env.example` + `Settings` (prefer one canonical name).
- Update docs to reflect FAISS and current endpoint shapes (or change implementation to match docs, but that’s a bigger decision).

---

## Detailed Recommendations (Lean Refactors With Synergy)

### 1) Define explicit API DTOs (stop returning internal models directly)

Right now `Session.model_dump()` is used as a response body. That couples the frontend to internal storage shape.

Proposed approach:

- Create `src/models/http_models.py` (or extend `src/models/api_models.py`) with:
  - `SessionDTO` (id, user_id, started_at, transcript, enriched fields, etc.)
  - `TherapyPlanDTO` (plan_id, user_id, selected_style, tier4 fields, timestamps, etc.)
  - `UserProfileDTO` (basically current `UserProfile`, but ensure field names match)
- Make `trio_server.py` endpoints return these DTOs only.
- Generate schemas from these DTOs (so TS is “truthfully generated”).

This yields a stable contract without overengineering.

### 2) Normalize field naming across backend JSON and frontend types

Your type generation uses quicktype with `--nice-property-names`, which produces `userid` rather than `user_id`. This forced a “compatibility layer” (`frontend/src/types/index.ts` and `frontend/src/types/converters.ts`).

Lean choices:

**Option A (recommended): keep JSON keys as-is in TS**
- Remove `--nice-property-names` from `frontend/scripts/generate-types.js`.
- Regenerate types so `user_id`, `session_id`, etc remain stable.
- Delete most of the mapping layer and converters.

**Option B: keep nice names, but generate converters**
- Don’t use `--just-types`; generate quicktype “converter functions” to map JSON↔TS automatically.
- Still more complexity than Option A.

### 3) Finish backend-driven navigation (or remove it)

If the backend is the single source of truth for workflow routing:

- All pages should use `useWorkflowNextAction()` (or a wrapper) and redirect if the current route is not valid.
- The backend should provide routes that actually exist in the router.
- Remove the unused/incorrect routes (`/session/current`, `/session/new`) or implement them.

If you don’t want this complexity:
- Remove `/api/workflow/next-action`, delete the hook, and drive routing locally with a single mapping table in the frontend.

### 4) Make DI consistent (remove global singletons and duplicate factories)

Concrete steps:

- Delete the module-level `style_service` singleton and always use `container.get("style_service")`.
- Remove agent creation duplication:
  - Either `ServiceContainer.create_*_agent()` is canonical, or orchestrator’s `_create_*_agent()` is.
  - Prefer the container to keep agent wiring in one place.
- Ensure agent-specific LLM selection is used consistently:
  - If you want `ASSESSMENT_MODEL` etc to matter, inject the correct `llm_service_*` into the agent itself (not only into streaming).

### 5) Implement true streaming

Replace “collect list then yield” with a real bridge:

- Thread function iterates `self.llm.stream(messages)` and sends each chunk to a Trio channel.
- Trio async generator yields chunks as they are received.
- Add a sentinel to indicate completion.

This is a small change that removes a “paper streaming” mismatch and improves both console and web UX immediately.

### 6) Split the DB service by domain + extract serialization helpers

`TrioDatabaseService` currently mixes:

- Sessions (CRUD + enriched immutability)
- User profiles
- Auth credentials
- Therapy plans
- Tiered patient analysis/profile history
- Enrichment job queue
- Helpers (datetime serialization, JSON parsing)

Lean split (no new libraries required):

- `src/services/db/connection_pool.py`: pool init + acquire context manager.
- `src/services/db/serialization.py`: `to_iso()`, `from_iso()`, `dump_json()`, `load_json()`, `session_from_row()`, etc.
- `src/services/db/session_repo.py`, `user_repo.py`, `plan_repo.py`, `auth_repo.py`, `enrichment_repo.py`.
- `src/services/trio_db_service.py` becomes a thin facade composing repos (or is replaced by them).

Synergy:
- Removes repeated transcript/topic parsing code.
- Makes tests smaller and targeted (per repo).

### 7) Modularize `TrioServer` routes

`src/trio_server.py` currently does:

- App creation + CORS + compression + route wiring
- WebSocket protocol loop
- Many endpoint handlers
- Orchestration initialization

Lean split:

- `src/api/http_routes/*.py`: create blueprints for `users`, `sessions`, `therapy`, `workflow`, `health`.
- `src/api/ws_handler.py`: WebSocket loop + message handling.
- `src/trio_server.py`: `create_app(container) -> QuartTrio` + `run()` only.

### 8) Remove legacy code paths (as per repo guidance)

Several agents still mention “legacy/backward compatibility” mode. Even if it’s harmless, it adds cognitive load.

Lean approach:
- Keep only orchestrator-facing interfaces.
- Move any remaining “legacy UI” behavior into the UI layer (if still needed).

### 9) Fix “paper cuts” that signal drift

These aren’t critical but contribute to entropy:

- Align env var name: `GOOGLE_API_KEY` vs `GEMINI_API_KEY`.
- Update docs that mention ChromaDB to reflect FAISS, or rename code to match docs.
- Fix `ServiceContainer.shutdown()` to match the DB pool implementation (or remove it if the process ends anyway).
- Decide whether schema JSON files are committed or not; align `.gitignore` and tests accordingly.

---

## Proposed Roadmap (Detailed, Practical, Ordered)

This is intentionally sequenced to minimize rework.

### Phase 1 — Contract Stabilization (Highest ROI)

**Goal**: The frontend and backend agree on what each endpoint returns; type generation reflects reality.

1. Define API DTOs for:
   - sessions (list + detail)
   - therapy plan (get + create)
   - user profile/status
2. Update `src/trio_server.py` endpoints to return DTOs only.
3. Update frontend hooks to match DTOs:
   - Prefer using generated types for responses.
4. Decide on TS field naming:
   - Recommended: remove quicktype `--nice-property-names` so generated types match JSON keys.
5. Add/adjust contract tests:
   - Extend the existing WebSocket contract test pattern to HTTP responses for sessions/plan.

**Exit criteria**:
- No placeholder endpoints used by UI (`_get_therapy_plan` implemented or UI stops calling it).
- `Dashboard`, `History`, and `Session detail` display correct session dates and transcripts.

### Phase 2 — Workflow Navigation Consistency

**Goal**: One consistent source of truth for “what screen should the user see next.”

1. Decide architecture:
   - Backend-driven routing (current intent) vs frontend-driven mapping.
2. If backend-driven:
   - Update backend mapping to use routes that exist.
   - Refactor `IntakePage` and `AssessmentPage` to use `useWorkflowNextAction` and remove custom event logic.
   - Add WebSocket “state_change/user_status” events *only if needed* (polling may be enough for local use).

**Exit criteria**:
- User can go Profile → Intake → Assessment → Plan selection → Therapy without manual hacks.

### Phase 3 — DI + Composition Cleanup

**Goal**: One wiring story; agents and services created in one place; remove globals.

1. Remove global `style_service` usage (agents use injected style service or prompt provider).
2. Remove orchestrator’s duplicate agent creation or container’s duplicate factories.
3. Ensure agent-specific LLM config is actually used consistently (streaming + structured calls).

**Exit criteria**:
- “How do I create an agent?” has one answer (the container).
- Tests can replace any service via container registration.

### Phase 4 — True Streaming + Shared Utilities

**Goal**: Real-time streaming and reduced duplication.

1. Implement channel-based streaming bridge in `LLMService` + `TrioConversationManager`.
2. Extract common helpers:
   - DB serialization helpers
   - Prompt composition helpers (especially around resumption/session briefing)
   - WebSocket message envelope helpers (`type` + `data`)

**Exit criteria**:
- First chunk arrives quickly; console/web UI feel responsive.
- Repeated JSON parsing/formatting code is centralized.

### Phase 5 — Module Splits (DB, Server, Agents)

**Goal**: Smaller modules and clearer boundaries.

1. Split `TrioDatabaseService` by domain (repos).
2. Split `TrioServer` routes into blueprints/modules.
3. Split large agents (Reflection/Planning) into:
   - prompt builders
   - structured-output extractors
   - persistence/updaters

**Exit criteria**:
- No single file is “the dumping ground” for multiple domains.

### Phase 6 (Optional) — Packaging + Dev Experience Polish

**Goal**: Remove `sys.path` hacks and make execution uniform.

1. Turn backend into an installable package (`src/<package_name>/...`) and use `python -m ...` entry points.
2. Align supported Python version and tooling config (3.10 vs 3.11).
3. Move dev-only deps out of production requirements (e.g., `ruff` in `requirements.in`).

---

## Reuse Opportunities (Concrete “Synergy” Targets)

These are specific places where reusable functions/classes will reduce duplication:

1. **DB JSON ↔ Model mapping**
   - Transcript parsing is repeated in multiple `TrioDatabaseService` methods.
   - Introduce `serialize_message()`, `deserialize_message()`, `serialize_session()`, `deserialize_session_row()`.
2. **Prompt composition**
   - Session resumption prompt assembly in `TrioPsychoanalystAgent` is long and formatting-heavy.
   - Extract a `BriefingPromptBuilder` that takes `UserProfile`, `TherapyPlan`, `SessionBriefing` and returns a system prompt.
3. **WebSocket message envelopes**
   - Both server and clients build `{"type": ..., "data": ...}` repeatedly.
   - Create a tiny shared helper (per language): `make_ws_message(type, data)` and/or constants module (already partially done in console UI).
4. **Agent routing + LLM selection**
   - Centralize mapping from agent type → llm service key in one place (avoid repeating).
5. **Schema/type generation**
   - Decide whether you want snake_case TS fields. If yes, remove the converters layer entirely.

---

## Notes on Error Handling & Security (Given Local-Only Scope)

You explicitly deprioritized robust error catching and extensive security. That said:

- Some current debug behavior is *too* loud for end users (e.g., streaming stack traces into the chat stream). For a local single-user app, it’s fine to log stack traces to file and show a short UI message instead.
- Authentication is already implemented; if you want to keep the app “single user,” you can default `REQUIRE_AUTHENTICATION=false` in local mode and avoid extra complexity in the UI flow.

Lean stance:
- Keep security and hardening “good enough” for local use; focus on clarity, contract correctness, and maintainability.

---

## Appendix: Concrete Observations Worth Tracking

- **Env var mismatch**: `.env.example` uses `GEMINI_API_KEY`; backend `Settings` uses `GOOGLE_API_KEY`.
- **RAG mismatch**: docs mention ChromaDB; code uses FAISS (`src/services/rag_service.py`).
- **Shutdown mismatch**: `ServiceContainer.shutdown()` expects a `_pool` attribute on DB service that no longer exists.
- **Workflow routes mismatch**: frontend references `/session/current` and `/session/new` in places; router currently defines `/session/:sessionId`.
- **Assessment UI mismatch**: `AssessmentPage.tsx` listens for an `assessment-complete` browser event that is not emitted in current code.
- **Streaming mismatch**: “streaming” collects all chunks before yielding.

---

## Recommended Next Step

If you want the biggest maintainability win with minimal risk, start with **Phase 1: Contract Stabilization**. Once the API is stable and type generation reflects reality, the remaining refactors become straightforward and much less error-prone.

