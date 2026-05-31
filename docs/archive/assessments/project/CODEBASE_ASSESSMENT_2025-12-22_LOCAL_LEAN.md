# Comprehensive Codebase & Documentation Assessment (2025-12-22) — Local Lean Focus

**Repository**: `psychoanalyst_app/`  
**Scope**: Backend (`src/`), Web frontend (`frontend/`), Console UI (`console-ui/`), tooling (`scripts/`, `Makefile`, `pyproject.toml`), tests (`tests/`), and documentation (`docs/`).  
**Assumptions from request**:
- Runs on a local machine for 1–few users.
- Lean, maintainable code is the priority.
- Reuse functions and shared helpers wherever it reduces duplication.
- Verbose documentation and explicit plans are valued.
- Heavy error catching and extensive security hardening are not required.
- Authentication can be disabled by default; if it simplifies the codebase, auth can be removed.
- Multiple virtual users are still needed for local testing.
- Legacy code should be removed entirely, not preserved for compatibility.
- The WebSocket protocol should be strictly minimal.

---

## Executive Summary

The codebase already follows a clean, layered architecture with strong Trio-first concurrency, separation between I/O and business logic, and a coherent orchestration pipeline. The main opportunities now are **consistency and simplification**: aligning docs with actual runtime behavior, trimming legacy or unused features, and consolidating protocol definitions and helper functions across backend, frontend, and console UI.

For a local, single-user environment, several features are heavier than needed (auth defaults, broad error catching, redundant protocol definitions, and unused WS event types). A focused refactor can preserve the existing architecture while significantly reducing cognitive load, improving reuse, and making the system easier to maintain.

---

## Current Architecture Snapshot (Observed)

### Backend
- **Server composition**: `src/psychoanalyst_app/trio_server.py` wires Quart + Hypercorn, config, DI container, routes, WS handler, and orchestration.
- **Gateway layer**: HTTP routes in `src/psychoanalyst_app/api/*_routes.py`; WS handler in `src/psychoanalyst_app/api/ws_handler.py`.
- **Orchestration layer**: `src/psychoanalyst_app/orchestration/*` (workflow engine, conversation manager, agent orchestrator).
- **Agents**: `src/psychoanalyst_app/agents/trio_*_agent.py` (intake, assessment, psychoanalyst, reflection, planning, memory).
- **Services**: `src/psychoanalyst_app/services/*` (DB, LLM, RAG, styles, auth).
- **Models**: `src/psychoanalyst_app/models/*` for persistence, DTOs, structured outputs.

### Frontend
- **React + TS** in `frontend/`, with API wrappers in `frontend/src/services/*` and types in `frontend/src/types/*`.
- **WebSocket client** in `frontend/src/services/websocketService.ts` with protocol constants in `frontend/src/types/websocket.ts`.

### Console UI
- **Trio WebSocket client** in `console-ui/src/console_client.py`, protocol constants in `console-ui/src/websocket_protocol.py`.

### Docs & Contracts
- Contract docs in `docs/contracts/HTTP_API_CONTRACT.md` and `docs/WEBSOCKET_PROTOCOL.md`.
- Architecture and workflow docs in `docs/ARCHITECTURE.md`, `docs/design-principles.md`, `docs/user_journey.md`, `docs/session_lifecycle.md`.

---

## Strengths Worth Preserving

- **Clear layering**: I/O (routes, WS handler) is separated from orchestration and agents, and DTOs are distinct from persistence models.
- **Trio structured concurrency**: Good use of nurseries and `trio.to_thread.run_sync()` for blocking work.
- **Schema/type pipeline**: JSON schema generation in `src/psychoanalyst_app/schemas/generate_schemas.py` and TS type consumption in `frontend/src/types/generated/`.
- **RAG + style pack design**: Encapsulated style packs via `StyleService` and RAG via FAISS are a solid baseline.
- **Test suite breadth**: Integration tests include WS contract checks (`tests/integration/test_websocket_protocol_contract.py`) and end-to-end orchestration flows.

---

## Key Gaps and Frictions (Detailed)

### 1) Documentation and Contract Drift

The documentation is extensive but inconsistent with current implementation details:

- **WebSocket examples should stay native**:
  - Keep `docs/QUICKSTART.md` aligned to native `WebSocket` usage (no Socket.IO).
- **Paths must match current modules**:
  - Keep `docs/session_lifecycle.md` aligned to `src/psychoanalyst_app/trio_server.py` and `src/psychoanalyst_app/api/ws_handler.py`.
- **Removed dev guide references**:
  - The deleted `CLAUDE.md` is still referenced in some docs; those links should point to current sources (for example `docs/design-principles.md`).

Impact: The docs are detailed but reduce confidence because they visibly diverge from code.

### 2) WebSocket Protocol Divergence Across Clients

Backend, frontend, console, and docs do not agree on protocol scope:

- **Backend emits a minimal set**:
  - `connected`, `session_started`, `chat_response_chunk`, `session_ended`, `assessment_recommendations` (see `src/psychoanalyst_app/utils/ws_messages.py` and `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`).
- **Frontend defines a much larger set**:
  - `frontend/src/types/websocket.ts` includes `ping/pong`, `user_status`, `style_selected`, `session_extended`, etc. Some of these are never sent by the backend.
- **Console protocol is also larger and version-mismatched**:
  - `console-ui/src/websocket_protocol.py` uses `WS_PROTOCOL_VERSION = "1.0"` while docs say `1.2.1`, and includes message types not emitted.

Impact: Protocol confusion and unnecessary client complexity. The protocol should be reduced to the smallest set required for the current flows.

### 3) Configuration and Runtime Mode Ambiguity

- **Config instance drift**:
  - `src/psychoanalyst_app/config.py` exports a global `settings`, but `ServiceContainer` also creates its own `Settings` instance.
  - `src/psychoanalyst_app/server.py` uses global `settings`, while `trio_server` accepts a passed config.
- **Auth by default**:
  - Auth is currently wired into HTTP routes with `require_auth`, but local usage does not require it and can be simplified by removing auth entirely.

Impact: Mixed configuration sources and an auth layer that adds complexity without current value.

### 4) Orchestration Complexity and Heavy Error Handling

- `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py` still handles multiple responsibilities (session creation, profile bootstrap, streaming, transitions) despite some refactoring into helpers.
- The top-level `process_message()` catches all exceptions and yields a full stacktrace to the user. This is useful for debugging, but overkill for a lean, local usage mode.
- `ws_handler.py` does its own user profile creation rather than reusing `merge_user_profile()` and orchestration-level helpers.

Impact: Orchestration is functional but not yet as lean or modular as it could be.

### 5) Agents Carry Legacy Paths and TODOs

Examples:
- `src/psychoanalyst_app/agents/trio_assessment_agent.py` has TODOs for scoring and key topic extraction.
- `src/psychoanalyst_app/agents/trio_therapist_agent.py` has TODOs for topic detection and a `get_initial_prompt_legacy()` method.
- Agent code includes explicit mentions of "legacy mode" even though the orchestration layer is now standard.

Impact: The codebase contains unused or incomplete logic, increasing maintenance burden. Legacy paths should be removed completely.

### 6) RAG + Style Pack Overlap

- `src/psychoanalyst_app/services/rag_service.py` loads knowledge from both `DOMAIN_KNOWLEDGE_PATH` and `styles/` packs.
- `StyleService` separately loads style pack knowledge and prompts.

Impact: Two parallel knowledge sources create duplication and unclear single source of truth. Domain knowledge loading can be removed for now and revisited later if needed.

### 7) Frontend Consistency and Lean UX

Examples:
- `frontend/src/services/versionService.ts` uses raw `fetch` instead of the shared `apiClient`.
- `frontend/src/services/websocketService.ts` sends `typing_start`, `typing_stop`, and `ping` to the server, but the backend does not handle them.
- `frontend/src/pages/SettingsPage.tsx` exposes a reset flow with `resetAvailable = false`, effectively a stub.

Impact: Some UI paths are half-implemented or carry unused complexity.

### 8) Console UI Protocol Drift

The console UI mirrors many of the frontend’s WS mismatches:
- Protocol version and event list do not align with `docs/WEBSOCKET_PROTOCOL.md` or backend implementation.

Impact: Increases confusion for anyone debugging WS flows.

### 9) Dependencies and Legacy Settings

From `pyproject.toml`:
- `chromadb.*` is listed in mypy overrides but is not a dependency anymore.
- `torchvision` and `torchaudio` are included but may not be necessary for sentence-transformers in this context.

Impact: Dependency footprint is larger than needed for a local, single-user system.

---

## Lean Improvement Plan (Local-First, Reuse-Oriented)

The following plan is intentionally staged. Each phase is meant to be small, reversible, and focused on making the system leaner rather than adding features.

### Phase 0 — Documentation and Contract Alignment (High Priority)
**Goal**: Make docs and contracts match actual runtime behavior.

- Update WebSocket examples in `docs/QUICKSTART.md` to use native `WebSocket` instead of Socket.IO.
- Fix paths in `docs/session_lifecycle.md` to point to `src/psychoanalyst_app/trio_server.py` and `src/psychoanalyst_app/api/ws_handler.py`.
- Remove `CLAUDE.md` references and link to current documentation sources instead.
- Verify and update `docs/WEBSOCKET_PROTOCOL.md` to list only implemented message types.

### Phase 1 — WebSocket Protocol Consolidation
**Goal**: One protocol definition, shared across backend, frontend, and console.

- Decide the minimal WS event set (strictly required for current flows only).
- Update:
  - `src/psychoanalyst_app/utils/ws_messages.py`
  - `docs/WEBSOCKET_PROTOCOL.md`
  - `frontend/src/types/websocket.ts`
  - `console-ui/src/websocket_protocol.py`
- Remove client-side `ping/pong`, `typing_start/typing_stop`, and any unused message types.

### Phase 2 — Configuration Simplification (Local Mode)
**Goal**: Single config source, minimal auth overhead.

- Remove reliance on module-level `settings` in `src/psychoanalyst_app/server.py`, use container-provided config consistently.
- Remove authentication plumbing entirely if it is not needed for local usage.
- Preserve user_id-based virtual users for local testing (no auth tokens required).

### Phase 3 — Orchestration & Agent Cleanup
**Goal**: Reduce orchestration complexity and error-catch verbosity.

- Split `TrioAgentOrchestrator.process_message()` into smaller helpers:
  - session resolution
  - state/agent resolution
  - streaming
  - transition handling
- Replace heavy `try/except` that emits stacktraces with lean logging and re-raises.
- Consolidate profile creation so `ws_handler.py` reuses the same profile merge logic as HTTP routes.
- Remove all legacy methods and compatibility code paths in agents.

### Phase 4 — RAG and Style Pack Unification
**Goal**: One knowledge source, one import path.

- Remove `DOMAIN_KNOWLEDGE_PATH` loading from `RAGService` for now and rely solely on style packs.
- If domain knowledge is reintroduced later, document it as an optional extension.

### Phase 5 — Frontend and Console Lean Pass
**Goal**: Remove unused features and unify API usage.

- Route version checks through `apiClient` for consistency.
- Remove stub UI paths (or hide them):
  - Settings reset flow (`resetAvailable = false`) should be either implemented or removed.
- Align WebSocket client behavior with backend messages only.

### Phase 6 — Dependency and Tooling Slimming
**Goal**: Reduce footprint and confusion for local use.

- Remove unused mypy overrides (`chromadb.*`).
- Audit `torchvision` and `torchaudio` dependencies; drop if not required.
- Align Makefile and docs to a single local-vs-docker story (choose one and document it clearly).

---

## Reusability Opportunities (Concrete Targets)

- **Shared WS protocol constants**: Generate a single source (backend JSON or schema) and import in frontend/console.
- **Profile creation/update**: Centralize in `profile_helpers.py` and reuse in both HTTP routes and WS handler.
- **Session creation**: One helper for session initialization to reduce duplication across orchestrator and routes.
- **Error responses**: One lean error helper for API routes (similar to `validation_error_response()`).

---

## Suggested Lean Defaults for Local Usage

- No authentication layer by default; user identity is `user_id` only.
- Disable LLM rate limiting unless needed.
- Prefer console logging only; optional file logging.
- Keep WS messages minimal and remove unused types from clients.

---

## Open Questions / Decisions to Confirm

All questions resolved:

- Authentication can be removed for now as long as virtual users remain supported.
- `DOMAIN_KNOWLEDGE_PATH` loading is not needed and can be removed.
- All legacy agent methods and compatibility code should be removed.
- WS protocol should be strictly minimal (current flow only).

---

## Closing Notes

This codebase is already strong in structure and intent. The next iteration should focus on **alignment, trimming, and reuse**, not new features. With a small number of targeted cleanups, the system can be significantly leaner while staying fully functional for local, low-user-count usage.
