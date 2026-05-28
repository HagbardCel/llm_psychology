# Comprehensive Project Analysis Report: Psychoanalyst Application

**Generated:** 2026-01-22
**Branch:** `feat/local-llm-providers`
**Scope:** Architecture, user flows, agentic flows, codebase, contracts, and deployment

---

## 1. Executive Summary

The **Psychoanalyst Application** is a multi-agent, LLM-driven psychotherapy assistant. Four specialized agents (Intake, Assessment, Psychoanalyst, Reflection) collaborate through a deterministic workflow state machine, with real-time streaming responses delivered to a React frontend over native WebSocket. The project demonstrates strong architectural discipline: structured concurrency (Trio), typed interfaces (Pydantic → JSON Schema → TypeScript), dependency injection, and a tiered clinical data model (Tier 1–4).

This report identifies **14 actionable issues** across seven categories, ranked by severity. The most critical gaps are: (1) no authentication/authorization, (2) in-memory-only session tracking, (3) RAG disabled with no migration path, (4) SQLite concurrency risks under load, and (5) limited integration/E2E test coverage for the agentic workflow.

---

## 2. Architecture Overview

### 2.1 Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| **Backend Runtime** | Python 3.11 + Trio (structured concurrency) | trio, trio-websocket |
| **Web Framework** | Quart (async) + Hypercorn (ASGI) | quart, hypercorn, quart-trio |
| **Data Validation** | Pydantic + pydantic-settings | pydantic, pydantic-settings |
| **Database** | SQLite (versioned migrations, WAL mode) | sqlite3 |
| **LLM Abstraction** | LangChain (gemini, ollama, lmstudio, openai_compatible) | langchain, langchain-google-genai, langchain-ollama, langchain-openai |
| **Frontend** | React 19 + TypeScript + Material-UI 7 + Vite 8 | react, typescript, @mui/material, vite |
| **Data Fetching** | React Query 5 | @tanstack/react-query |
| **Testing** | Pytest (backend), Vitest + Playwright (frontend) | pytest, vitest, @playwright/test |
| **Deployment** | Docker Compose, multi-stage builds | docker-compose.yml |

### 2.2 Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                         │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  HomePage │  │ SessionPage  │  │  Assessment/Intake Pages │  │
│  └────┬─────┘  └──────┬───────┘  └──────────────┬───────────┘  │
│       │                │                          │             │
│  ┌────▼────────────────▼──────────────────────────▼──────────┐  │
│  │              apiClient.ts + websocketService.ts           │  │
│  └────────────────────────┬─────────────────────────────────┘  │
└───────────────────────────┼─────────────────────────────────────┘
                            │ HTTP / WebSocket
┌───────────────────────────▼─────────────────────────────────────┐
│                     Backend (Quart + Trio)                      │
│                                                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  HTTP Routes │  │ WS Handler   │  │  Background Workers  │   │
│  │  (api/*)     │  │ (ws_handler) │  │  (tier2_enrichment)  │   │
│  └──────┬──────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         │                │                       │              │
│  ┌──────▼────────────────▼───────────────────────▼──────────┐   │
│  │           TrioAgentOrchestrator                          │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │   │
│  │  │ Workflow │  │Conversation│  │  Agent   │  │  DB    │  │   │
│  │  │ Engine   │  │  Manager  │  │  Router  │  │  Svc   │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Agents (Pure Business Logic)          │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌────────┐  │   │
│  │  │ Intake   │ │Assessment│ │ Psychoanalyst│ │Reflect │  │   │
│  │  └──────────┘ └──────────┘ └──────────────┘ └────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Supporting Services                         │   │
│  │  LLMService │ RAGService │ StyleService │ MemoryAgent   │   │
│  │  PlanningAgent │ SessionContextManager                  │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                     SQLite Database                             │
│  users │ sessions │ session_messages │ therapy_plans │ profiles  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 Type Generation Pipeline

```
Pydantic Models (src/psychoanalyst_app/models/)
    │
    ▼  (scripts/generate_schemas.py)
JSON Schemas (schemas/)
    │
    ▼  (quicktype)
TypeScript Types (frontend/src/types/ws_protocol.generated.ts)
```

---

## 3. Workflow & User Flows

### 3.1 Therapy Workflow State Machine

```
                    ┌─────────┐
                    │   NEW   │
                    └────┬────┘
                         │ (user sends first message)
                         ▼
                    ┌─────────┐
              ┌────│  INTAKE │────┐
              │      └─────────┘    │
              │                     │
              │   ┌─────────┐       │
              └───│ASSESSMENT│──────┘
              │     └─────────┘     │
              │          │          │
              │   ┌──────▼──────┐   │
              │   │  THERAPY    │   │
              │   │  (cycle)    │◄──┘
              │   └──────┬──────┘   │
              │          │          │
              │   ┌──────▼──────┐   │
              └───│ REFLECTION  │───┘
              │     └─────────┘     │
              │          │          │
              │   ┌──────▼──────┐   │
              │   │    PLAN     │   │
              │   └─────────────┘   │
              │                     │
              └───────(cycle back to THERAPY)
```

**States:** `NEW` → `INTAKE` → `ASSESSMENT` → `THERAPY` ↔ `REFLECTION` → `PLAN` → `THERAPY` (cycle)

**Transitions are enforced by:** `trio_workflow_engine.py` with a `VALID_TRANSITIONS` dict. Invalid transitions return a `400` error with the allowed next actions.

### 3.2 User Journey (Web UI)

1. **Home/Dashboard** → User lands on `/dashboard` (redirected from `/`).
2. **Intake** → User navigates to `/intake`. The WorkflowGate ensures they only land here when `workflow_state == INTAKE`. The Intake agent extracts Tier 1 data (demographics, concerns, goals).
3. **Assessment** → After intake completes, `workflow_state` transitions to `ASSESSMENT`. The Assessment agent runs asynchronously (Tier 2 enrichment). The user sees `/assessment` with style recommendations and selects a therapy style (freud/jung/cbt).
4. **Therapy Sessions** → User navigates to `/session/new`. The Psychoanalyst agent handles real-time streaming chat. Session context is maintained via `ConversationContext`.
5. **Reflection** → After each therapy session, the Reflection agent runs asynchronously (Tier 3/4 enrichment). The user is redirected to `/session/new` for the next session.
6. **Session History** → User views past sessions at `/history`.
7. **Profile** → User manages their profile at `/profile`.
8. **Settings** → User configures the app at `/settings`.

### 3.3 Agentic Flow (Per Therapy Session)

```
User sends message
    │
    ▼
WebSocket Handler (ws_handler.py)
    │
    ▼
TrioAgentOrchestrator.process_message()
    │
    ├──▶ SessionLifecycleManager (create/find session)
    │
    ├──▶ WorkflowEngine.get_next_action() (determine current state)
    │
    ├──▶ AgentRouter.route_agent() (select agent by state)
    │
    ├──▶ ConversationManager (streaming setup)
    │       ├──▶ register WebSocket handler
    │       ├──▶ update conversation context
    │       └──▶ unregister on completion
    │
    ├──▶ Agent Execution (Trio task group)
    │       ├── IntakeAgent.run_intake()
    │       ├── AssessmentAgent.run_assessment()
    │       ├── PsychoanalystAgent.run_therapy()
    │       └── ReflectionAgent.run_reflection()
    │
    ├──▶ AgentResponseHandler.handle_response()
    │       ├── persist session messages
    │       ├── persist therapy plan (if applicable)
    │       ├── persist tier3/tier4 updates
    │       └── update workflow state
    │
    ├──▶ Background Jobs (if applicable)
    │       ├── AssessmentJob (async style assessment)
    │       ├── ReflectionJob (async tier2/3/4 enrichment)
    │       └── Tier2EnrichmentWorker (periodic)
    │
    ▼
WebSocket broadcast (streaming chunks → frontend)
```

### 3.4 Session Resumption (Briefing System)

When a user resumes a therapy session:
1. `ReflectionAgent.generate_session_briefing()` creates a compact summary of prior context.
2. `SessionContextManager.get_session_context()` loads the briefing.
3. The briefing is injected into the Psychoanalyst agent's prompt, enabling continuity.

---

## 4. Detailed Issue Analysis

### 4.1 Privacy, Security & Compliance

#### Issue 1: No Authentication or Authorization (CRITICAL)

**Evidence:**
- `AppContext.tsx` generates a local `currentUserId` via `crypto.randomUUID()` with no backend verification.
- No JWT, session cookies, or API key validation in any route.
- `ws_handler.py` accepts `user_id` from a query parameter without verification.
- No role-based access control; any user can access any session.

**Impact:** Complete absence of identity verification. Any client can impersonate any user, access any session, or inject arbitrary user IDs.

**Recommendation:**
- Implement JWT-based auth with refresh tokens.
- Add auth middleware to all HTTP routes (`@require_auth` decorator pattern).
- Validate `user_id` in WebSocket connections against the auth token.
- Add session-level authorization (users can only access their own sessions).

#### Issue 2: Therapy Data Caching Headers (HIGH)

**Evidence:**
- `src/psychoanalyst_app/api/cache_utils.py` applies `Cache-Control`, `Expires`, and `ETag` headers to responses.

**Impact:** Therapy session transcripts, user profiles, and agent responses could be cached by browsers, CDNs, or intermediate proxies, violating HIPAA/GDPR principles for PHI.

**Recommendation:**
- Strip caching headers from all therapy/session endpoints.
- Add `Cache-Control: no-store, no-cache` to PHI-containing responses.
- Audit all route decorators for unintended caching.

#### Issue 3: No PII/PHI Encryption at Rest (HIGH)

**Evidence:**
- `user_context.py` and `orchestration/models.py` store therapeutic data as plain strings/dicts in SQLite.
- No field-level encryption for sensitive fields (e.g., `RelationalLifeContext`, `AnalyticFrame`).

**Impact:** Database compromise exposes all PHI in plaintext.

**Recommendation:**
- Add field-level encryption for sensitive user data using `cryptography.fernet`.
- Evaluate SQLite encryption extensions (e.g., SQLCipher) for full-disk encryption.

### 4.2 Error Resilience & Fault Tolerance

#### Issue 4: No LLM Service Fallback Strategy (HIGH)

**Evidence:**
- `service_container.py` creates LLM services via factories but provides no degradation strategy.
- `llm_service.py` has no retry logic, circuit breaker, or fallback provider.

**Impact:** LLM provider outage or rate limiting causes complete session failure.

**Recommendation:**
- Implement a provider fallback chain (e.g., gemini → ollama → local model).
- Add exponential backoff with jitter for transient errors.
- Add circuit breaker pattern (e.g., `pybreaker` or custom implementation).
- Define graceful degradation messages for when all providers are unavailable.

#### Issue 5: No WebSocket Message Ordering or Deduplication (MEDIUM)

**Evidence:**
- WebSocket events (`session_started`, `chat_response_chunk`, `workflow_next_action`) arrive asynchronously without sequence IDs.
- `websocketService.ts` has no message deduplication logic.

**Impact:** Out-of-order rendering, duplicate UI states, or lost events during network blips.

**Recommendation:**
- Add sequence IDs to all WebSocket messages.
- Implement client-side message deduplication using sequence numbers.
- Add backend message buffering for in-flight session state.

#### Issue 6: API Client Lacks Retry Logic (MEDIUM)

**Evidence:**
- `apiClient.ts` aborts on timeout but has no retry, exponential backoff, or circuit breaker.

**Impact:** Network blips or LLM provider throttling immediately fail user sessions.

**Recommendation:**
- Add retry policy with exponential backoff (e.g., 3 retries, 1s/2s/4s delays).
- Add retry-only for idempotent methods (GET, POST for non-critical operations).
- Add circuit breaker for repeated failures.

### 4.3 Data Persistence & Database Management

#### Issue 7: In-Memory-Only Active Session Tracking (HIGH)

**Evidence:**
- `ActiveSessionRegistry` in `orchestration/helpers.py` tracks active sessions in memory only.
- No durable session state across server restarts.

**Impact:** Server restarts lose all active sessions, disconnecting users mid-session with no recovery path.

**Recommendation:**
- Persist active session state to SQLite (e.g., `active_sessions` table with heartbeat timestamps).
- Implement session recovery on startup (scan for sessions with recent heartbeats).
- Add session timeout/expiration for abandoned sessions.

#### Issue 8: SQLite Concurrency Risks (MEDIUM)

**Evidence:**
- SQLite is inherently single-writer. Concurrent agent writes or WebSocket broadcasts could trigger `database is locked` errors.
- `trio_db_service.py` manages a connection pool but SQLite's write concurrency is limited.

**Impact:** Under load, concurrent writes fail with `database is locked` errors.

**Recommendation:**
- Enable SQLite WAL mode (write-ahead logging) for better concurrent reads.
- Add retry logic with exponential backoff for `database is locked` errors.
- Consider write-queueing for high-concurrency scenarios.
- For production multi-user deployments, evaluate PostgreSQL.

#### Issue 9: No Automated Backup/Restore (MEDIUM)

**Evidence:**
- No backup mechanism for therapy session data.
- No data retention policy.

**Impact:** Data loss on hardware failure; no compliance with data retention requirements.

**Recommendation:**
- Implement automated periodic backups (e.g., cron job copying SQLite to S3/GCS).
- Add data retention policy (e.g., archive sessions older than 2 years).
- Add restore procedure documentation.

### 4.4 Agent Orchestration & Prompt Engineering

#### Issue 10: Topic Detection Uses Keyword Matching (LOW)

**Evidence:**
- `trio_intake_agent.py` and `trio_psychoanalyst_agent.py` use keyword-based topic detection.
- No sophisticated NLP or LLM-based topic extraction.

**Impact:** Topic detection is brittle and misses nuanced patient expressions.

**Recommendation:**
- Replace keyword matching with LLM-based topic extraction (e.g., prompt the LLM to identify topics from the patient's message).
- Add a fallback to keyword matching for cost efficiency.
- Evaluate embedding-based similarity for theme matching.

#### Issue 11: RAG is Disabled (LOW)

**Evidence:**
- `RAG_BACKEND=none` in `.env.example`.
- `rag_service.py` has a no-op backend.
- `TrioMemoryAgent.analyze_session_context()` calls `rag_service.retrieve_relevant_knowledge()` which returns empty results.

**Impact:** The memory agent's RAG integration is non-functional. Domain knowledge is not injected into prompts.

**Recommendation:**
- Implement a RAG backend (e.g., ChromaDB, FAISS) for psychological domain knowledge.
- Add embedding generation for domain knowledge documents.
- Re-enable RAG integration in the memory agent with a configurable backend.
- Document the RAG migration path in `docs/features/`.

#### Issue 12: Hardcoded Therapy Style Descriptions (LOW)

**Evidence:**
- `AssessmentPage.tsx` has hardcoded `getStyleDescription()` for freud/jung/cbt.
- Style descriptions should come from the backend's `StyleService` for consistency.

**Impact:** Style descriptions can drift between frontend and backend.

**Recommendation:**
- Fetch style descriptions from the backend API (`/styles` endpoint).
- Remove frontend hardcoded descriptions.

### 4.5 Real-Time Communication & Frontend-Backend Sync

#### Issue 13: WebSocket Reconnection Has Limited Resilience (MEDIUM)

**Evidence:**
- `websocketService.ts` implements exponential backoff reconnection (5 attempts max).
- No heartbeat/ping-pong for connection liveness detection.
- No session state sync after reconnection.

**Impact:** After reconnection, the frontend may be out of sync with the backend session state.

**Recommendation:**
- Add heartbeat/ping-pong for connection liveness detection.
- Implement session state sync after reconnection (fetch current workflow state).
- Increase max reconnection attempts or make it configurable.
- Add UI notification for reconnection success/failure.

#### Issue 14: Optimistic UI Absent (LOW)

**Evidence:**
- `AppContext.tsx` manages UI state but doesn't implement optimistic updates for messages.
- Users experience lag during network latency or LLM streaming delays.

**Impact:** Perceived latency in message sending and session progress.

**Recommendation:**
- Implement optimistic message display (show user message immediately, confirm with server response).
- Add loading indicators for session state transitions.
- Consider React Query's `onMutate`/`onSettled` for optimistic updates.

---

## 5. Strengths

1. **Clean Architecture:** Well-defined layering (Gateway → Orchestration → Agent → Service) with clear separation of concerns.
2. **Structured Concurrency:** Trio eliminates many async bugs (no race conditions, clean cancellation).
3. **Type Safety Pipeline:** Pydantic → JSON Schema → TypeScript ensures contract consistency.
4. **Tiered Clinical Data Model:** Clear progression from Tier 1 (static background) through Tier 4 (treatment plan).
5. **Session Briefing System:** Enables therapeutic continuity across sessions.
6. **Per-Agent Model Selection:** Cost optimization by assigning cheaper models to non-critical agents.
7. **Docker-Only Execution:** Consistent development and deployment environments.
8. **Comprehensive Documentation:** 145+ documentation files covering architecture, contracts, and user flows.
9. **Dependency Injection:** ServiceContainer provides testable composition.
10. **Workflow State Machine:** Deterministic transitions prevent invalid state jumps.

---

## 6. Risk Assessment

| Category | Severity | Likelihood | Impact |
|----------|----------|------------|--------|
| **Auth/Authorization** | 🔴 Critical | High | Complete data breach, identity impersonation |
| **Caching PHI** | 🟠 High | Medium | Regulatory violation, PII exposure |
| **In-Memory Sessions** | 🟠 High | Medium | Session loss on restart, data loss |
| **LLM Fallback** | 🟠 High | Medium | Complete service outage on provider failure |
| **DB Encryption** | 🟠 High | Medium | Plaintext PHI exposure on DB compromise |
| **WebSocket Sync** | 🟡 Medium | High | Stale UI, lost events, confused UX |
| **SQLite Concurrency** | 🟡 Medium | Medium | `database is locked` errors under load |
| **Backup/Restore** | 🟡 Medium | Low | Data loss on hardware failure |
| **Topic Detection** | 🟢 Low | High | Suboptimal therapy quality |
| **RAG Disabled** | 🟢 Low | High | Missing domain knowledge in prompts |
| **Hardcoded Styles** | 🟢 Low | Medium | Frontend/backend drift |
| **Optimistic UI** | 🟢 Low | High | Perceived latency |
| **API Retry** | 🟡 Medium | Medium | Session failure on network blip |
| **Message Ordering** | 🟡 Medium | Medium | Out-of-order rendering |

---

## 7. Recommended Action Plan

### Phase 1: Critical Security (Immediate)
1. Implement JWT-based authentication with refresh tokens.
2. Add auth middleware to all HTTP routes.
3. Validate `user_id` in WebSocket connections.
4. Strip caching headers from PHI-containing responses.
5. Add field-level encryption for sensitive user data.

### Phase 2: Resilience (Short-Term)
6. Implement LLM service fallback chain (gemini → ollama → local).
7. Add retry logic with exponential backoff to `apiClient.ts`.
8. Persist active session state to SQLite for crash recovery.
9. Enable SQLite WAL mode and add `database is locked` retry logic.
10. Add WebSocket heartbeat/ping-pong for liveness detection.

### Phase 3: Data Integrity (Medium-Term)
11. Implement automated SQLite backups.
12. Add WebSocket message sequence IDs and deduplication.
13. Implement session state sync after WebSocket reconnection.
14. Add data retention policy.

### Phase 4: Quality Improvements (Long-Term)
15. Replace keyword topic detection with LLM-based extraction.
16. Implement RAG backend (ChromaDB/FAISS) for domain knowledge.
17. Fetch therapy style descriptions from backend API.
18. Implement optimistic UI updates for message sending.
19. Increase WebSocket reconnection attempts or make configurable.

---

## 8. Reference File Mapping

| Issue Area | Primary Files |
|------------|---------------|
| Auth/Authorization | `src/psychoanalyst_app/trio_server.py`, `frontend/src/contexts/AppContext.tsx` |
| Caching/PHI | `src/psychoanalyst_app/api/cache_utils.py` |
| Encryption | `src/psychoanalyst_app/context/user_context.py`, `src/psychoanalyst_app/orchestration/models.py` |
| LLM Fallback | `src/psychoanalyst_app/services/llm_service.py`, `src/psychoanalyst_app/container/factories/llm.py` |
| WebSocket Sync | `frontend/src/services/websocketService.ts`, `frontend/src/contexts/WebSocketContext.tsx` |
| API Retry | `frontend/src/services/apiClient.ts` |
| Session Tracking | `src/psychoanalyst_app/orchestration/helpers.py` |
| Database | `src/psychoanalyst_app/services/trio_db_service.py`, `src/psychoanalyst_app/services/db/executor.py` |
| Topic Detection | `src/psychoanalyst_app/agents/trio_intake_agent.py`, `src/psychoanalyst_app/agents/trio_psychoanalyst_agent.py` |
| RAG | `src/psychoanalyst_app/services/rag_service.py`, `src/psychoanalyst_app/agents/trio_memory_agent.py` |
| Style Descriptions | `frontend/src/pages/AssessmentPage.tsx`, `src/psychoanalyst_app/services/style_service.py` |
| Optimistic UI | `frontend/src/contexts/AppContext.tsx`, `frontend/src/contexts/WebSocketContext.tsx` |
| Workflow Engine | `src/psychoanalyst_app/orchestration/trio_workflow_engine.py` |
| Orchestrator | `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py` |
| Conversation Manager | `src/psychoanalyst_app/orchestration/trio_conversation_manager.py` |
| Agents | `src/psychoanalyst_app/agents/trio_*_agent.py` |
| Types Pipeline | `schemas/`, `frontend/src/types/ws_protocol.generated.ts` |
| Docker | `docker-compose.yml`, `Dockerfile`, `Makefile` |

---

## 9. Appendix: Current Codebase Status

### 9.1 Implemented Features
- ✅ Multi-agent orchestration (Intake, Assessment, Psychoanalyst, Reflection)
- ✅ Workflow state machine with deterministic transitions
- ✅ Real-time streaming via native WebSocket
- ✅ Session briefing for resumption continuity
- ✅ Per-agent model selection via environment variables
- ✅ Tiered clinical data model (Tier 1–4)
- ✅ Dependency injection via ServiceContainer
- ✅ Type generation pipeline (Pydantic → JSON Schema → TypeScript)
- ✅ Background workers (Tier 2 enrichment, assessment, reflection)
- ✅ Memory agent (session context, therapeutic memory, pattern analysis)
- ✅ Planning agent (initial plan creation, plan updates, effectiveness assessment)
- ✅ Therapy style selection (freud, jung, cbt)
- ✅ Docker Compose development environment
- ✅ Console UI (terminal WebSocket client)
- ✅ Web UI (React + Material-UI)

### 9.2 Deferred/Disabled Features
- ⏸️ RAG (disabled, no-op backend)
- ⏸️ Authentication/Authorization
- ⏸️ Multi-instance deployment (sticky sessions not implemented)
- ⏸️ Sophisticated topic detection (keyword-only)
- ⏸️ LLM provider fallback chain
- ⏸️ Automated database backups
- ⏸️ PII/PHI encryption at rest

### 9.3 Known Limitations
- Active session tracking is in-memory only (lost on restart)
- SQLite concurrency limited to single-writer
- No rate limiting on WebSocket connections
- Assessment agent uses string-matching for state detection (fragile)
- Tier 2 enrichment runs in background (potential for stale data)
- Code duplication between legacy and orchestrator interfaces
