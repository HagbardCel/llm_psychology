---
owner: engineering
status: active
last_reviewed: 2026-05-28
review_cycle_days: 90
source_of_truth_for: Project-level architecture and implementation invariants
---

# Design Principles (How This Codebase Wants You To Build)

This document captures the *project-level design decisions* that shape how code is organized, how data flows, and how new features should be implemented. It is intended as an onboarding “mental model” so contributors (human and AI agents) can write code consistent with the existing architecture without reading the entire repository.

Documentation governance for this file is defined in `DOCS_GOVERNANCE.md`.

If you need deeper detail on a specific area, this document links to the canonical deep-dives:
- Architecture: `docs/ARCHITECTURE.md`
- Foundation stabilization priorities: `docs/reference/FOUNDATION_STABILIZATION_PLAN.md`
- Type system pipeline: `docs/TYPE_SYSTEM.md`
- WebSocket contract: `docs/WEBSOCKET_PROTOCOL.md`
- Session lifecycle: `docs/session_lifecycle.md`

## Table of Contents
- Non‑Negotiables (Project Invariants)
- Foundation Stabilization Mode
- System Overview (One Mental Model)
- Composition & Dependency Injection (DI)
- Domain Model vs Wire Model (Backend)
- Persistence & Data Integrity (SQLite)
- Workflow, Sessions, and Time
- LLM Integration (Configurable LangChain providers)
- Prompts, Styles, and RAG
- WebSocket Protocol (Realtime Chat)
- HTTP API Design
- Frontend Design Principles (React + TypeScript)
- Console UI Design Principles (Trio client)
- Testing & Determinism
- Configuration, Logging, and Operational Defaults
- Code Quality & Tooling
- Common Implementation Playbooks

---

## Non‑Negotiables (Project Invariants)

### 1) Structured concurrency is mandatory (Trio-first)
- The backend runtime is Trio; concurrency uses `trio.open_nursery()` and bounded channels.
- Blocking work (SQLite, embedding inference, LangChain streaming iterators) is moved to threads via `trio.to_thread.run_sync()`.
- Avoid “fire-and-forget” tasks; tasks must remain under a nursery so cancellation and error propagation are deterministic.

Canonical examples:
- `src/psychoanalyst_app/utils/trio_streaming.py` (bridges blocking iterators into async streaming)
- `src/psychoanalyst_app/services/db/executor.py` + `src/psychoanalyst_app/services/db/repos/*` (SQLite executor + domain repos behind the `TrioDatabaseService` facade)
- `src/psychoanalyst_app/trio_server.py` (server composition + nursery ownership)

### 2) Clean boundaries: business logic is independent of I/O
The codebase is organized to keep business logic testable and reusable across multiple clients (web UI, console UI, standalone terminal UI):
- **Gateway layer**: HTTP routes + WebSocket handler (I/O only)
- **Orchestration layer**: state machine + routing + streaming coordination
- **Agent layer**: domain logic (decide what to do next and what prompt/content to produce)
- **Service layer**: database, LLM, RAG, styles (infrastructure)

Canonical examples:
- Gateway: `src/psychoanalyst_app/trio_server.py` (composition/middleware) + `src/psychoanalyst_app/api/*_routes.py` (HTTP blueprints) + `src/psychoanalyst_app/api/ws_handler.py`
- Orchestration: `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py`, `src/psychoanalyst_app/orchestration/trio_conversation_manager.py`, `src/psychoanalyst_app/orchestration/trio_workflow_engine.py`
- Agents: `src/psychoanalyst_app/agents/trio_*_agent.py`
- Services: `src/psychoanalyst_app/services/*`

### 3) Workflow is an explicit state machine
User progression is represented by explicit states and validated transitions. Agents do not “navigate” the UI; they emit structured responses that orchestration interprets.

Canonical examples:
- State machine and transitions: `src/psychoanalyst_app/orchestration/trio_workflow_engine.py`
- Shared state + responses: `src/psychoanalyst_app/orchestration/models.py`

### 4) Stable contracts at boundaries (DTOs + schemas)
Cross-process boundaries use explicit models and stable serialization rules:
- **Backend Pydantic models are the source of truth** for API/WS payloads and schema generation.
- **HTTP DTOs exist to avoid leaking persistence models** directly over the wire.
- The frontend consumes **generated TypeScript types** from backend JSON schemas.

Canonical examples:
- HTTP DTOs: `src/psychoanalyst_app/models/http_models.py`
- Schema pipeline overview: `docs/TYPE_SYSTEM.md`
- Frontend DTO usage: `frontend/src/types/index.ts`

### 5) Streaming-first UX
Therapy chat is designed around incremental streaming rather than “single blob” responses:
- Server emits `chat_response_chunk` messages over WebSocket.
- Clients append chunks as they arrive; `is_complete=true` closes the stream.

Canonical examples:
- Message envelopes: `src/psychoanalyst_app/utils/ws_messages.py`
- WebSocket contract: `docs/WEBSOCKET_PROTOCOL.md`
- Console client streaming: `console-ui/src/console_client.py`

---

## Foundation Stabilization Mode

Until `docs/reference/FOUNDATION_STABILIZATION_PLAN.md` exit criteria are satisfied, the project is operated as a headless backend and protocol-contract project with one maintained reference client.

Support tiers:
- **Tier 0:** backend workflow engine, persistence, HTTP DTOs, WebSocket protocol, schema/type generation, generated protocol constants, LLM abstraction, deterministic fake-provider behavior, backend tests, and architecture/documentation validation.
- **Tier 1:** WebSocket-based console UI as the canonical integration and manual-test client.
- **Tier 2:** React web frontend as a frozen compatibility/demo client, maintained only for generated type compatibility, build/dependency fixes, contract regression fixes, and one golden smoke path.
- **Tier 3:** standalone terminal UI as legacy or local-debug mode; avoid new features.

Design rules during stabilization:
- Backend owns workflow progression. Clients may render workflow state and submit explicit user actions, but must not mutate workflow state directly.
- Contract changes must update specs, DTOs, schemas/generated artifacts, and deterministic tests before expanding client UX.
- Prefer backend, protocol, and reference-client tests for foundational behavior; keep React tests focused on compatibility and the minimal browser smoke path.
- Defer optional RAG, advanced UI flows, dashboard polish, multi-client feature parity, and frontend redesign until the foundation exit review.

---

## System Overview (One Mental Model)

At a high level:
1. A client registers via `POST /api/user/register` to create a complete profile and receive a session id.
2. The client connects via WebSocket (`/ws?user_id=...`); the server validates the profile and resumes the correct session.
3. Clients reconnect to prompt the backend to re-emit `session_started` and `workflow_next_action`.
4. The server registers the WebSocket to the active session.
5. For each `chat_message`, the orchestrator:
   - loads workflow state (`TrioWorkflowEngine`)
   - loads conversation context (`TrioConversationManager`)
   - selects/creates the correct agent
   - calls `agent.process_message(...)` to get an `AgentResponse`
   - streams the response (`TrioConversationManager`) either directly or via LLM
   - applies state transitions and side effects (DB writes, session switching)

Start here in code: `src/psychoanalyst_app/trio_server.py` → HTTP blueprints in `src/psychoanalyst_app/api/*_routes.py` (per domain) or the WebSocket handler in `src/psychoanalyst_app/api/ws_handler.py` → `TrioAgentOrchestrator.process_message()` in `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py`.

### Canonical Entry Points

- `make run` → standalone terminal UI (Docker)
- `make run-server` → HTTP + WebSocket server (Docker)
- `make run-e2e` → deterministic server for Playwright (Docker)

Packages are intentionally installed *inside* the Docker images (`docker compose build api` / `make dev-install`). The `test` profile exports `PYTHONPATH=/app/src` so `pytest` imports `psychoanalyst_app` from mounted sources in containers.

---

## Composition & Dependency Injection (DI)

### Why DI exists here
The backend has multiple “expensive” or “global-ish” dependencies (DB pool, LLM client, embedding model/index, style packs). DI makes those dependencies:
- constructed once and reused safely
- replaceable in tests (fakes/stubs)
- consistently wired (same dependency graph for server, agents, workers)

### The container is the intended composition root
`src/psychoanalyst_app/container/service_container.py` provides:
- singleton service creation (`container.get("trio_db_service")`, `container.get("rag_service")`, …)
- agent-specific LLM services (`llm_service_intake`, `llm_service_assessment`, …) to support per-agent model selection
- test override hooks (`register()`, `register_factory()`, `register_llm_service_for()`)

Design rule:
- Create runtime dependencies through the container, not by module-level singletons or ad-hoc instantiation spread across the codebase.

Related plan/doc:
- `docs/plans/phase-3/PHASE_3_DI_COMPOSITION_CLEANUP_IMPLEMENTATION_PLAN.md`

---

## Domain Model vs Wire Model (Backend)

This codebase distinguishes between:

### 1) Persistence/domain models (internal)
Defined in `src/psychoanalyst_app/models/data_models.py`. Examples:
- `UserProfile`, `Session`, `TherapyPlan`, `Message`, `Topic`
- Tiered “clinical” structures (Tier 1 profile, Tier 2 enriched session, Tier 3 analysis, Tier 4 plan trajectory)

### 2) HTTP-facing DTOs (external contract)
Defined in `src/psychoanalyst_app/models/http_models.py`. Key goals:
- expose only what clients need
- keep types stable across refactors
- centralize conversions (`*_to_dto()` helpers)

Design rule:
- Add/modify API responses by updating DTOs, not by returning persistence models directly.

### Datetimes on the wire
Datetimes are serialized as ISO 8601 strings in JSON. Clients may parse into `Date` objects for presentation, but wire format remains strings.

---

## Persistence & Data Integrity (SQLite)

### SQLite + migrations
- The primary store is SQLite (`data/psychoanalyst.db` by default).
- Migrations are executed through `src/psychoanalyst_app/services/migration_service.py` (invoked by DB initialization).

### TrioSQLiteExecutor + domain repositories
- `src/psychoanalyst_app/services/db/executor.py` owns the Trio-friendly connection pool (`trio.open_memory_channel(...)`) and runs every blocking SQL call inside `trio.to_thread.run_sync(...)`.
- Domain-specific repos under `src/psychoanalyst_app/services/db/repos/` (sessions, therapy plans, users, patient profiles, enrichment jobs, patient analysis) encapsulate SQL per domain and centralize serialization helpers from `src/psychoanalyst_app/services/db_serialization.py`.
- `src/psychoanalyst_app/services/trio_db_service.py` remains as a transitional facade so call sites keep importing `TrioDatabaseService` while the underlying work is delegated to the repos/executor stack.

### Immutability where it matters
Sessions become effectively immutable after Tier 2 enrichment:
- `save_session()` refuses to overwrite already-enriched sessions (`WHERE sessions.enriched = 0`).

Rationale:
- Keep raw transcripts stable once “published” into enriched/derived analysis.
- Make enrichment jobs idempotent and safe to retry.

### Tier 2 enrichment is off the request path
Tier 2 enrichment is intentionally run by a background worker so normal reads/writes remain fast and deterministic:
- Worker: `src/psychoanalyst_app/services/session_enrichment_worker.py`
- Enrichment logic: `src/psychoanalyst_app/services/session_enrichment_service.py`

Design rule:
- Avoid adding expensive LLM calls to HTTP “read” endpoints; prefer background jobs + persisted derived data.

---

## Workflow, Sessions, and Time

### Workflow state machine
Workflow states are explicit and validated:
- `WorkflowState` in `src/psychoanalyst_app/orchestration/models.py`
- transition validation in `src/psychoanalyst_app/orchestration/trio_workflow_engine.py`

### Backend-driven workflow invariants
These principles are non-negotiable and are sourced from the implementation plans:
- The backend orchestrator is the single source of truth for workflow state and required action.
- Clients never advance workflow state directly; profile PATCH/PUT must not mutate `status`.
- Profile creation is explicit via `POST /api/user/register`; WebSocket connections for unknown users are rejected.
- All workflow step completion calls require a valid `session_id` bound to the user.
- Active session tracking is in-memory (single active session per user) and is not durable across restarts/instances; clients must reconnect to rebind, and multi-instance deployments require sticky sessions or a shared store (not implemented).
- Assessment runs as a backend job; clients display `required_action: "wait"` until completion.
- Reconnects must re-emit `session_started` and `workflow_next_action`, and re-kick assessment jobs when needed.

Authoritative plan references:
- `docs/assessments/project/plans/BACKEND_DRIVEN_WORKFLOW_MIGRATION_PLAN.md`
- `docs/assessments/project/plans/SESSION_BOUND_WORKFLOW_IMPLEMENTATION_PLAN.md`
- `docs/assessments/project/plans/BACKEND_DRIVEN_WORKFLOW_REMEDIATION_PLAN.md`

### AgentResponse is the orchestrator contract
Agents return an `AgentResponse` with:
- `content`: either a direct user-facing message or an LLM prompt
- `next_action`: what orchestration should do (`continue`, `transition`, `offer_extension`, `end_session`, etc.)
- `next_state`: optional target `WorkflowState`
- `metadata`: optional extra info for clients (time remaining, topics covered, etc.)

Design rule:
- Agents should be “pure decision + prompt builders”; they should not know about WebSockets, HTTP, or UI rendering.

### Session timer
Session time tracking is derived from `ConversationContext`:
- `ConversationContext` in `src/psychoanalyst_app/orchestration/models.py` has `time_elapsed_minutes`, `time_remaining_minutes`, `can_extend`, `is_time_up`.
- Session extension behavior is enforced at orchestration/agent level, not in the client.

---

## LLM Integration (Configurable LangChain providers)

### LLMService responsibilities
`src/psychoanalyst_app/services/llm_service.py` encapsulates:
- calling Gemini, Ollama, or OpenAI-compatible local providers through LangChain
- rate limiting via a Trio token bucket (`TrioRateLimiter`)
- two output modes:
  - free-text streaming (`stream_response(...)`)
  - typed structured outputs (`generate_structured_output(...)` / async variant)

Design rules:
- Prefer structured outputs (Pydantic schema / JSON schema) for internal analysis, plan updates, and enrichment. Gemini uses native schema support; local providers use prompt-constrained JSON followed by Pydantic validation.
- If you need streaming, bridge the blocking iterator via `src/psychoanalyst_app/utils/trio_streaming.py` rather than buffering the full response.

### Per-agent model selection
The configuration supports agent-specific models (`INTAKE_MODEL`, `ASSESSMENT_MODEL`, …) with fallback to `MODEL_NAME`.
The intent is: the same agent-specific LLM service should be used for both:
- streaming responses, and
- structured calls inside that agent.

Container keys:
- `llm_service_intake`, `llm_service_assessment`, `llm_service_psychoanalyst`, `llm_service_reflection`, `llm_service_memory`, `llm_service_planning` in `src/psychoanalyst_app/container/service_container.py`

---

## Prompts, Styles, and RAG

### Prompts live close to the domain
Prompts are versioned as code assets:
- shared prompt templates: `src/psychoanalyst_app/prompts/*`
- psychoanalyst prompt composition: `src/psychoanalyst_app/prompts/psychoanalyst_prompt_builder.py`

Design rule:
- Prefer small prompt composition helpers that receive typed inputs and produce a single string prompt.

Example helper modules:
- Reflection: `src/psychoanalyst_app/agents/reflection/helpers.py` (prompt assembly + structured outputs for Tier updates)
- Planning: `src/psychoanalyst_app/agents/planning/helpers.py` (plan strategy models, RAG requests, structured extraction, recommendation scoring)
Agents (`src/psychoanalyst_app/agents/trio_reflection_agent.py`, `src/psychoanalyst_app/agents/trio_planning_agent.py`) now orchestrate these helpers instead of holding mega-methods.

### Therapy styles are “style packs”
Therapy styles are modeled as directory-based packs under `src/psychoanalyst_app/styles/<style_id>/` (e.g., `freud`, `jung`, `cbt`), typically including:
- `knowledge.md` (RAG source)
- `description.txt` (patient-facing)
- `psychoanalyst_prompt.txt`, `reflection_prompt.txt`, `assessment_prompt.txt` (style-specific instructions)

Loader/service:
- `src/psychoanalyst_app/services/style_service.py` loads those prompts via `importlib.resources` for packaged/container runtime resolution (override with `settings.STYLES_DIR` when you explicitly need alternate style assets).

### RAG is disabled for the current release
`RAG_BACKEND=none` is the only supported path and wires a no-op retriever.
Local vector retrieval is deferred to a future extension after the core product
path is fully tested and stable.

Design rule:
- Keep retrieval optional; it is an enhancement, not a hard dependency for correctness.

---

## WebSocket Protocol (Realtime Chat)

### Message envelope
All WS messages are JSON with:
```json
{ "type": "<message_type>", "data": { ... } }
```

Backend helpers:
- `src/psychoanalyst_app/utils/ws_messages.py`
- `src/psychoanalyst_app/api/ws_handler.py` (registers `/ws` on QuartTrio and streams orchestration output)

Contract spec:
- `docs/WEBSOCKET_PROTOCOL.md`

Design rules:
- Add a new WS message type by:
  1) updating the spec (`docs/WEBSOCKET_PROTOCOL.md`)
  2) adding an envelope helper in `src/psychoanalyst_app/utils/ws_messages.py` if appropriate
  3) updating both clients (`frontend/src/types/websocket.ts`, `console-ui/src/websocket_protocol.py`)

---

## HTTP API Design

### Primary goal: stable, type-safe endpoints
The HTTP API exists for:
- profile management
- session history and session timer
- therapy plan management
- workflow/navigation queries (when applicable)

Implementation lives in:
- `src/psychoanalyst_app/api/*_routes.py` (Quart blueprints grouped by domain: health, users, sessions, therapy, workflow)
- `src/psychoanalyst_app/api/ws_handler.py` (WebSocket registration + protocol glue)
- `src/psychoanalyst_app/trio_server.py` (composition root that wires middleware, blueprints, and the WS handler)

Design rules:
- Validate request bodies with Pydantic request DTOs (see `Create*RequestDTO` in `src/psychoanalyst_app/models/http_models.py`).
- Return response DTOs (e.g., `UserProfileDTO`, `SessionDTO`) rather than internal models.
- Keep “read endpoints” free from LLM calls; persist derived analyses via workers when possible.

---

## Frontend Design Principles (React + TypeScript)

During foundation stabilization, the React frontend is a compatibility/demo client rather than the product development driver. Do not add React product features, UI redesigns, frontend-only workflow semantics, or state transitions that bypass backend workflow authority. Allowed frontend work is limited to contract compatibility, build/dependency maintenance, smoke-path repair, and explicitly deferred product work documented as such.

### The backend schema is the source of truth
- Generated types: `frontend/src/types/generated/api.ts`
- Re-export + UI-only extensions live in: `frontend/src/types/index.ts`

Design rule:
- API DTOs remain `snake_case` (mirror backend wire contract). UI state can be `camelCase`, but avoid conversion layers unless unavoidable.

### Data fetching and mutations
Frontend uses React Query (`@tanstack/react-query`) for:
- caching, invalidation, retries
- query hooks that correspond to backend endpoints

Canonical entry:
- `frontend/src/providers/QueryProvider.tsx`

### WebSocket client uses native WebSocket (not Socket.IO)
The web client implements the WS protocol defined in `docs/WEBSOCKET_PROTOCOL.md`:
- `frontend/src/psychoanalyst_app/services/websocketService.ts`

---

## Console UI Design Principles (Trio client)

During foundation stabilization, the console client is the Tier 1 reference client. It should stay intentionally close to the backend protocol for debugging and “lowest common denominator” UX:
- Trio runtime + structured concurrency
- WS streaming chunk rendering
- minimal UI state machine around “session started” and “waiting for initial greeting”

Canonical code:
- `console-ui/src/console_client.py`
- `console-ui/src/websocket_protocol.py`

---

## Testing & Determinism

### Test philosophy
- Prefer tests that do not require network or real LLM calls.
- Use fakes/stubs for LLM and RAG in unit tests; reserve integration tests for end-to-end wiring.

Infrastructure:
- deterministic fakes: `src/psychoanalyst_app/testing/fakes.py`
- dedicated deterministic server for browser tests: `src/psychoanalyst_app/e2e_server.py`
- backend tests live under: `tests/`

Design rule:
- If a bug is found in orchestration, add a regression test close to the failing component (unit first; integration if it’s a cross-layer issue).

---

## Configuration, Logging, and Operational Defaults

### Settings
Configuration is provided by Pydantic settings:
- `src/psychoanalyst_app/config.py` (`Settings`, `settings`)

Important environment variables:
- `LLM_PROVIDER`, `LLM_BASE_URL` (LLM backend selection)
- `GOOGLE_API_KEY` (Gemini access only)
- `MODEL_NAME` and per-agent model overrides (`*_MODEL`)
- `DATABASE_PATH`, `RAG_BACKEND` (`none` only in the current release)
- CORS settings (`CORS_ALLOWED_ORIGINS`)

`GEMINI_API_KEY` is still accepted as a fallback for older shells when using Gemini, but `GOOGLE_API_KEY` is the canonical variable and is what `Settings` persists. Keep sensitive configuration in the appropriate `.env.*` file instead of hardcoding defaults in code.

### LLM Model Policy
- All model IDs live in environment files (`.env`, `.env.test`, `.env.usertest`). Code never embeds model names; it only reads `MODEL_NAME` + per-agent overrides.
- Local defaults (`.env`): `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL=http://host.docker.internal:8080/v1`, and `MODEL_NAME=local-model` for a host llama.cpp server. Override `MODEL_NAME` to match the model alias served locally.
- Gemini/usertest defaults (`.env.usertest`): everyone uses `MODEL_NAME=gemini-2.5-flash-light` unless overridden (keeps cost predictable for manual cloud testing).
- Rate limiting is controlled entirely via env (`LLM_RATE_LIMIT_ENABLED`, `LLM_REQUESTS_PER_MINUTE`, `LLM_BURST_CAPACITY`). The container reads those fields when constructing `LLMService`.

### Logging
Logging is configured centrally:
- `setup_logging()` in `src/psychoanalyst_app/config.py`

Design rule:
- Log operational events at INFO (session start, transitions, job completion).
- Keep app file logging opt-in (`APP_FILE_LOGGING_ENABLED=false` by default).
- Keep verbose LLM payload logging opt-in (`LLM_CALL_LOGGING_ENABLED=false` by default).
- When enabled, keep redaction on by default (`LLM_CALL_LOGGING_REDACT=true`).

---

## Code Quality & Tooling

### Backend (Python)
- Formatting: Black (`make format`)
- Linting: Ruff (`make lint`)
- Type checking: mypy is configured in `pyproject.toml` (strictness is part of the design intent; keep new code typed).

### Frontend (TypeScript)
- Type-check: `docker compose run --rm frontend npm run type-check`
- Lint: `docker compose run --rm frontend npm run lint`

Runtime, Docker images, and tooling all target Python 3.11 (`pyproject.toml` sets `requires-python = ">=3.11"` and formats/linters use `py311`). Use 3.11 features freely; no need to keep compatibility with older versions.

---

## Common Implementation Playbooks

### Add a new HTTP endpoint
1. Define request/response DTOs in `src/psychoanalyst_app/models/http_models.py` (or extend existing ones).
2. Create or extend the appropriate blueprint under `src/psychoanalyst_app/api/<domain>_routes.py` (or add a new module) and validate inputs with the DTOs/Pydantic.
3. If you introduced a brand-new blueprint, register it inside `TrioServer._setup_http_routes()`; existing domain files are already wired up.
4. Return DTOs (not persistence models) and ensure datetimes serialize as ISO 8601 strings.
5. Update schema generation if the model is API-facing: `scripts/generate_schemas.py`.
6. Regenerate TS types: `docker compose run --rm -v "$PWD/schemas:/schemas" frontend npm run generate:types`.

### Add a new WS message type
1. Update the spec: `docs/WEBSOCKET_PROTOCOL.md`.
2. Add helpers (optional but preferred): `src/psychoanalyst_app/utils/ws_messages.py`.
3. Emit from the WebSocket stack (`src/psychoanalyst_app/api/ws_handler.py` + orchestration helpers such as `src/psychoanalyst_app/orchestration/trio_conversation_manager.py`) so the new type flows through the same envelope helpers.
4. Update clients:
   - Web: `frontend/src/types/websocket.ts` and handler usage in `frontend/src/psychoanalyst_app/services/websocketService.ts`
   - Console: `console-ui/src/websocket_protocol.py` and `console-ui/src/console_client.py`

### Add or change an API-facing model (type pipeline)
1. Prefer adding/updating DTOs (wire models) rather than internal persistence models.
2. Add the DTO to the `pydantic_models` list in `scripts/generate_schemas.py`.
3. Run `make generate-schemas` and then:
   - `docker compose run --rm -v "$PWD/schemas:/schemas" frontend npm run generate:ts`
4. Commit the updated JSON schemas under `schemas/` and the generated TS file under `frontend/src/types/generated/api.ts`.

### Add a new agent (or change workflow routing)
1. Add the agent implementation under `src/psychoanalyst_app/agents/` as a Trio-native class with:
   - constructor dependencies injected (LLM/DB/RAG/style/etc)
   - `process_message(message, context) -> AgentResponse`
2. Wire it into:
   - `src/psychoanalyst_app/orchestration/trio_workflow_engine.py` (state→agent mapping, transitions)
   - `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py` (agent acquisition/creation path)
   - `src/psychoanalyst_app/container/service_container.py` (preferred composition/wiring story)
3. If it changes client UX, update WebSocket and/or HTTP contracts first, then update the clients.

---

## Architectural Patterns

### State Machine Pattern

**Usage:** Workflow management
**Implementation:** `TrioWorkflowEngine` in `src/psychoanalyst_app/orchestration/trio_workflow_engine.py`

**States:**
```
NEW → INTAKE_IN_PROGRESS → INTAKE_COMPLETE
  → ASSESSMENT_IN_PROGRESS → ASSESSMENT_COMPLETE
  → THERAPY_IN_PROGRESS → REFLECTION_IN_PROGRESS
  → PLAN_UPDATE_COMPLETE → THERAPY_IN_PROGRESS (cycle)
```

**Rules:**
- All transitions are explicit and validated
- Invalid transitions raise `WorkflowError`
- State is persisted in database
- No hidden state changes

### Strategy Pattern

**Usage:** Therapy style selection
**Implementation:** `StyleService` with style-specific prompts

**Example:**
```python
class TherapySession:
    def __init__(self, style: str):
        self.style_config = style_service.load_style(style)

    async def respond(self, message: str):
        # Use style-specific prompts and knowledge
        prompt = self.style_config.get_prompt("session")
        return await llm_service.generate(prompt, message)
```

### Repository Pattern

**Usage:** Data access abstraction
**Implementation:** `TrioDatabaseService` (facade) and `src/psychoanalyst_app/services/db/repos/*`

**Example:**
```python
class TrioDatabaseService:
    async def get_user_profile(self, user_id: str) -> UserProfile:
        # Encapsulates SQL details
        return await trio.to_thread.run_sync(
            self._get_user_profile_sync, user_id
        )
```

### Observer Pattern (Streaming)

**Usage:** Real-time LLM response streaming
**Implementation:** `TrioConversationManager` with async generators

**Example:**
```python
async def stream_response(self, prompt: str):
    async for chunk in llm_service.stream(prompt):
        yield chunk  # Observer gets immediate updates
```

### Dependency Injection

**Usage:** Service composition
**Implementation:** `ServiceContainer` in `src/psychoanalyst_app/container/service_container.py`

**Example:**
```python
class ServiceContainer:
    def __init__(self):
        self.db_service = TrioDatabaseService()
        self.llm_service = LLMService()
        self.rag_service = RAGService()

    def create_agent(self, agent_type: str):
        # Inject dependencies
        if agent_type == "intake":
            return TrioIntakeAgent(
                llm_service=self.llm_service,
                rag_service=self.rag_service
            )
```

---

## Coding Standards
Detailed coding examples and anti-pattern references moved to:
- `docs/reference/CODING_STANDARDS_AND_ANTI_PATTERNS.md`

Keep this active doc focused on architecture and runtime invariants. For code style:
- Follow typed Python + TypeScript conventions used in existing modules.
- Keep tests deterministic with clear arrange/act/assert structure.
- Avoid god objects, leaky abstractions, and callback-style async flows.
