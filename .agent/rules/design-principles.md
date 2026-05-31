---
trigger: always_on
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
The codebase is organized to keep business logic testable and reusable across multiple clients (web UI, console UI, terminal UI in Docker):
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

- `make run` → terminal UI (Docker)
- `make run-server` → HTTP + WebSocket server (Docker)
- `make run-e2e` → deterministic server for Playwright (Docker)

All runtime entry points are Docker-first; local Python execution is not supported in this workflow.

Packages are intentionally installed *inside* the Docker images (`docker compose build api` / `make dev-install`). The `test` profile already exports `PYTHONPATH=/app/src` so `pytest` can import `psychoanalyst_app` from the mounted sources even though the package itself isn’t globally installed.

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
- Service and worker: `src/psychoanalyst_app/services/session_enrichment.py`

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
- Agents should be “pure decision + prompt builde