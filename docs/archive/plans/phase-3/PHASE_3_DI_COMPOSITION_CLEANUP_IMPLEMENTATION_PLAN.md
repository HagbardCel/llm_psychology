# Phase 3 — DI + Composition Cleanup (Detailed Implementation Plan)

Source: `docs/assessments/project/CODEBASE_ASSESSMENT_2025-12-16.md` (Phase 3 — DI + Composition Cleanup)

## Objective

Establish a single “wiring story” for the backend:
- **All services and agents are constructed in one place** (the DI container).
- **No module-level singletons** (remove global service instances).
- **Orchestrator and server depend on abstractions/services**, not on ad-hoc imports or duplicate factories.
- **Agent-specific LLM configuration is consistently applied** for *both* streaming and structured calls.

This phase is intentionally *composition-focused*: it should not change the HTTP contract (Phase 1) or the workflow routing semantics (Phase 2), except where DI cleanup is required to implement those behaviors reliably.

## Inputs and Constraints (Carry-Forward from Phases 1–2)

### Phase 1 Contract Decisions (must remain true)
- **D1 (Field naming)**: `snake_case` end-to-end for HTTP DTOs and generated TypeScript.
- **D2 (Datetime representation)**: datetimes remain **ISO 8601 strings on the wire**; frontend types keep them as `string` (no implicit `Date` decoding).

Phase 3 must not introduce new “conversion layers” that violate D1/D2. Any parsing (e.g., `new Date(...)`) remains strictly UI/presentation logic.

### Phase 2 Workflow Decisions (must remain true)
- Proceed with **backend-driven navigation** using `POST /api/workflow/next-action`.
- WebSocket workflow/session behaviors added in Phase 2 (e.g., `session_type`, assessment recommendations messages) must not regress during refactors.

## Non-goals (Explicitly Out of Scope)
- True streaming implementation (Phase 4).
- Domain/module splits (Phase 5).
- Contract shape changes (Phase 1).
- Workflow mapping/routing product decisions (Phase 2).

## Current Problems to Fix (as Implementation Checklist)

1. **Global singleton usage**
   - `src/services/style_service.py` defines a module-level `style_service = StyleService()`.
   - Agents and orchestrator import and use that global, bypassing the container.

2. **Duplicate agent factories**
   - `src/container/service_container.py` has `create_*_agent(...)` methods.
   - `src/orchestration/trio_agent_orchestrator.py` also has `_create_*_agent(...)` methods (and does direct instantiation for sub-agents).

3. **Agent-specific LLM configuration is inconsistently applied**
   - Orchestrator selects `llm_service_<agent>` for streaming.
   - Agents are typically constructed with the default `llm_service`, so structured calls inside agents don’t use the agent-specific model.

4. **Container lifecycle drift**
   - `ServiceContainer.shutdown()` contains legacy `_pool` logic that no longer matches the Trio DB implementation.

## Target Architecture (What “Done” Looks Like)

### A) One composition root
- **`ServiceContainer` is the only place that constructs services and agents.**
- Everything else (server, orchestrator, agents) receives dependencies via constructor parameters.

### B) No module-level globals for runtime dependencies
- Remove singleton `style_service` and any similar patterns that appear during implementation.

### C) Agent creation is centralized, consistent, and testable
- Orchestrator does *not* construct agents directly.
- Orchestrator asks the container for an agent (or uses a container-provided `AgentFactory` service).
- Tests can replace any service (including StyleService and LLMService) via container registration.

### D) Agent-specific LLM selection is consistent
- The LLM service used for:
  - streaming response generation, and
  - agent internal structured calls
  is the same service instance configured for that agent type.

## Implementation Plan

### P3.1 Remove global `style_service` and inject StyleService everywhere

**Code changes**
- `src/services/style_service.py`
  - Delete the module-level `style_service = StyleService()` singleton export.
- Agents: stop importing the global and accept a `StyleService` dependency:
  - `src/agents/trio_assessment_agent.py`
  - `src/agents/trio_planning_agent.py`
  - `src/agents/trio_psychoanalyst_agent.py`
  - (and any other modules found by `rg "from services.style_service import style_service"`).
- Orchestrator: replace ad-hoc global import usage:
  - `src/orchestration/trio_agent_orchestrator.py:create_therapy_plan()` should validate styles via `self.service_container.get("style_service")`.
- Ensure any server endpoints that expose styles use `container.get("style_service")` only (already the preferred pattern in `src/trio_server.py`).

**Behavioral acceptance**
- No runtime import paths rely on a global singleton.
- A test can inject a fake `StyleService` via `ServiceContainer.register("style_service", fake)`.

**Search-based acceptance**
- `rg "style_service = StyleService\\(" src` finds **no** module-level singletons.
- `rg "from services\\.style_service import style_service" src` returns **no matches**.

### P3.2 Consolidate agent construction into the container

**Approach**
- Make the container the single place that knows how to build each agent and its sub-dependencies.
- Remove/retire orchestrator-local `_create_*_agent(...)` methods.

**Code changes**
- `src/container/service_container.py`
  - Add a single entry point such as `create_agent(agent_type: str, user_id: str)` or `create_agent(agent_type: AgentType, user_context: UserContext)`.
  - Keep existing `create_*_agent` methods but route through the single entry point to avoid drift.
- `src/orchestration/trio_agent_orchestrator.py`
  - Replace `_create_*_agent(...)` and any direct instantiation of memory/planning agents with calls to the container.
  - Keep orchestrator’s cache (`self.agents`) if desired, but cache the instances returned by container creation.

**Behavioral acceptance**
- Orchestrator no longer imports agent classes directly for construction.
- “How do I create an agent?” has one answer: the container (or a container-provided factory service).

### P3.3 Make agent-specific LLM config apply consistently (streaming + structured)

**Goal**
Ensure the same agent-specific LLM service is used:
- when generating streaming responses (orchestrator → conversation manager), and
- within the agent’s internal structured calls.

**Implementation**
- `src/container/service_container.py`
  - Update each `create_*_agent(...)` to use the correct LLM key:
    - intake → `llm_service_intake`
    - assessment → `llm_service_assessment`
    - psychoanalyst → `llm_service_psychoanalyst`
    - reflection → `llm_service_reflection`
    - memory → `llm_service_memory`
    - planning → `llm_service_planning`
  - Ensure sub-agent wiring (reflection → memory + planning) also uses their correct keys.
- `src/orchestration/trio_agent_orchestrator.py`
  - Prefer streaming with the same LLM service instance the agent was constructed with (e.g., `agent.llm_service`) to prevent drift between construction and streaming.
  - Remove the separate `llm_service_key_map` if it becomes redundant, or centralize mapping in one place (container).

**Behavioral acceptance**
- Changing `Settings.<AGENT>_MODEL` changes both:
  - streamed outputs, and
  - structured metadata generation inside that agent.

### P3.4 Container override story (tests and local development)

**Goal**
Make it trivial for tests to replace any dependency without importing globals.

**Code changes**
- `src/container/service_container.py`
  - Verify `register()` and `register_factory()` can override:
    - all LLM keys (already special-cased for `llm_service`)
    - `style_service`
    - `rag_service`
    - `trio_db_service`
  - Consider adding a helper: `register_llm_service_for(agent_type, instance)` if tests need per-agent overrides.

**Acceptance**
- Unit/integration tests can inject a stub LLM without setting API keys.
- No test requires `monkeypatch` against module globals to replace services.

### P3.5 Fix container lifecycle drift (`shutdown()`)

**Code changes**
- `src/container/service_container.py`
  - Replace legacy `_pool` closing logic with one of:
    - `await trio_db_service.aclose()` / `trio_db_service.close()` if such a method exists, or
    - no-op cleanup if DB service is process-lifetime only, but remove misleading pool logic.

**Acceptance**
- Shutdown does not error and does not refer to attributes that no longer exist.

## Validation Checklist

### Static checks (fast)
- `rg "from services\\.style_service import style_service" src` returns no matches.
- `rg "def _create_.*_agent" src/orchestration/trio_agent_orchestrator.py` returns no matches (or only intentionally retained transitional wrappers).

### Runtime tests (recommended)
- Backend unit/integration tests:
  - `pytest -q` (or repo-standard backend test command).
  - Ensure Phase 1 contract tests and Phase 2 workflow tests still pass.
- WebSocket protocol contract test remains green:
  - `tests/integration/test_websocket_protocol_contract.py`

## Suggested PR Breakdown (Minimize Risk)

1) **PR 1 — StyleService injection**
   - Remove singleton, thread StyleService dependency through agents/orchestrator/container.
   - Keep behavior unchanged.

2) **PR 2 — Container becomes the agent factory**
   - Orchestrator stops constructing agents directly.
   - Introduce `create_agent(...)` entry point and migrate orchestrator.

3) **PR 3 — Agent-specific LLM consistency**
   - Update container wiring to use agent-specific LLM keys for construction.
   - Update orchestrator to stream using the agent’s configured `llm_service`.

4) **PR 4 — Lifecycle cleanup**
   - Fix `ServiceContainer.shutdown()` drift.

## Exit Criteria (Phase 3 is Done When…)
- “How do I create an agent?” has one answer: `ServiceContainer` (composition root).
- No module-level global service singletons remain for runtime behavior (especially `style_service`).
- Agent-specific LLM model selection is applied consistently for both streaming and structured calls.
- Tests can override any dependency via container registration without patching module globals.

