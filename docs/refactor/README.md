---
owner: engineering
status: supporting
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Navigation and consistency rules for the single-user simplification refactor plans
---

# Refactor Planning Index

These documents define the intended single-user simplification refactor. They describe the planned target and are not canonical documentation for the current implementation until cutover.

## Planning documents

1. [`target-architecture.md`](target-architecture.md)
   - Product and architecture invariants.
   - Single-user domain and test-data isolation.
   - API-only console and future web clients.
   - `TherapyApplication`, workflow stages, phase processors, persistence, operations, Docker, and observability.

2. [`technology-decisions.md`](technology-decisions.md)
   - Third-party library policy and package boundaries.
   - FastAPI/Uvicorn, Pydantic, AsyncOpenAI, HTTPX, WebSockets, aiosqlite, and pytest-asyncio.
   - Instructor compatibility gate for structured local-model output.
   - Removal of LangChain/LangGraph and the Trio/Quart stack.
   - Explicit non-adoption of speculative agent, ORM, DI, provider-routing, and retry frameworks.

## Combined binding decisions

Implementation work must preserve all of these constraints:

- One real user; test profiles use separate data directories or temporary databases.
- Every frontend, including the console, uses the same `/api/v1` HTTP/WebSocket boundary.
- The backend is the sole SQLite writer.
- Workflow and therapeutic phase coordination remain explicit project-owned application code.
- Dedicated intake, assessment, therapy, and post-session behavior remains independently testable.
- Third-party libraries stay behind narrow infrastructure or adapter boundaries.
- LangChain, LangGraph, Trio, Quart, and the current service-container/orchestration stack are removed rather than retained behind compatibility flags.
- Docker remains supported packaging, not an internal architectural dependency.
- The old implementation is preserved through Git history/tag/archive procedures, not through legacy modules in the new runtime.

## Pre-implementation gates

Before broad implementation begins:

1. Preserve and tag the pre-refactor snapshot.
2. Run the current deterministic workflow probe and record its successful baseline.
3. Complete the Instructor/local-LLM compatibility spike described in `technology-decisions.md`.
4. Confirm the final baseline dependency set and retry limits.
5. Build pure workflow transition tests for the target `Stage` and command model.
6. Confirm that the new API contracts cover console requirements before replacing the console client.

## Consistency rule

When a planning change affects both system structure and technology selection, update both documents in the same branch. `target-architecture.md` owns architectural boundaries; `technology-decisions.md` owns concrete library choices and compatibility gates.
