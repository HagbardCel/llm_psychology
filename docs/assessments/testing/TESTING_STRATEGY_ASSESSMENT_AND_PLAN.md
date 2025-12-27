# Testing Strategy Assessment & Improvement Plan
**Date:** 2025-12-15  
**Scope:** Backend (pytest/pytest-trio), Frontend unit tests (Jest/RTL), Frontend E2E (Playwright), and overall workflow/CI alignment.

## Executive Summary

The repository contains a substantial number of backend unit/integration tests and a sizable frontend Jest + Playwright suite. There are strong areas (DB persistence/migrations, workflow/orchestration, WebSocket streaming, authentication) but also several issues that reduce confidence in the “green tests ⇒ working app” expectation:

- **False-green tests removed/reworked** (LLM/RAG adapter tests, frontend async assertions) so failures represent real regressions.
- **Marker selection is reliable** via folder-based auto-marking, so `make test-unit`/`make test-integration` match intent.
- **One CI-grade entrypoint exists**: `make test-all` runs backend + frontend unit + deterministic full-stack E2E.
- **Environment-dependent tests are isolated** under `tests/real_llm/` and gated by `-m real_llm --no-mocks`.
- **Remaining risk**: the longest “patient flow” integrations still contain fixed sleeps and could be further hardened with event-driven waits.

This document (1) inventories what exists, (2) assesses each unit/integration test file for meaningfulness and failure modes, (3) identifies gaps vs best practices, and (4) proposes a concrete, prioritized plan to raise confidence so that a fully passing suite strongly correlates with a fully functioning application.

---

## Implementation Status (As of 2025-12-16)

The phases below have been implemented in the codebase. The most important outcome is that the default suites are deterministic and “green” has a much higher correlation with a working application.

- **Phase 0 (False greens): Completed** — removed ineffective tests, fixed async assertions, added folder-based auto-marking, and eliminated hard-coded ports in shared server fixtures.
- **Phase 1 (LLM/RAG unit tests): Completed** — LLM adapter tests use a fake chat model + Trio `MockClock`; RAG tests use deterministic embeddings and include an index persistence/load check (RAG is used in production via `TrioConversationManager` when a therapy plan exists).
- **Phase 2 (Integration hardening): Completed** — integration suite uses an ephemeral-port TrioServer fixture and includes a WebSocket protocol contract test; removed the most brittle time-based auth sleeps.
- **Phase 3 (Deterministic full-stack E2E): Completed** — Playwright starts `src/psychoanalyst_app/e2e_server.py` (deterministic backend) + `npm run dev` automatically and runs a golden path + auth guard + WebSocket reconnect test.
- **Phase 4 (Real LLM smoke): Completed** — real-service tests live under `tests/real_llm/` and are gated by the `real_llm` marker + `--no-mocks`.
- **Phase 5 (Workflow integration): Mostly completed** — `make test-all` runs backend + frontend unit tests + deterministic E2E, and schemas are enforced via a parity test. Backend coverage enforcement is not enabled yet (would require adding `pytest-cov`).

## Current Testing Stack & How It’s Wired

### Backend (Python)
- **Framework:** `pytest` with `pytest-trio`
- **Config:** `pytest.ini` (single source of truth); folder-based marker auto-assignment lives in `tests/conftest.py`.
- **Markers declared:** `slow`, `unit`, `integration`, `real_llm`, `asyncio`, `trio` (strict markers enabled).
- **Test entry points (Makefile):**
  - `make test` (backend deterministic, excludes `real_llm`)
  - `make test-unit` / `make test-integration`
  - `make test-real-llm` (requires secrets / external services)
  - `make test-all` (backend + frontend unit + deterministic Playwright E2E)

### Frontend (React/TS)
- **Unit tests:** Jest + React Testing Library (`frontend/jest.config.js`)
- **E2E tests:** Playwright (`frontend/playwright.config.ts`, specs in `frontend/e2e/`)
- **Coverage thresholds:** Jest global 80% branches/functions/lines/statements.

### Full-stack deterministic E2E
- **Backend test entrypoint:** `src/psychoanalyst_app/e2e_server.py` (runs the backend with deterministic LLM/RAG fakes; no API keys, no network)
- **Playwright wiring:** `frontend/playwright.config.ts` starts both backend + frontend via `webServer`

### High-level observation
Backend, frontend unit, and deterministic full-stack E2E tests are all runnable from the repo root via `make test-all`.

---

## Backend Unit Tests — Assessment (pytest)

### Summary
There are several strong backend unit suites (auth, DB service, Pydantic models, schema generation, orchestration/server ordering). The LLM and RAG unit tests now validate the production adapters deterministically (fake chat model + injected embeddings), so failures represent real regressions rather than “mock behavior” breakage.

### Per-file assessment (backend unit and root-level tests)

| File | Intent | Meaningfulness | Key issues | Recommendation |
|---|---|---:|---|---|
| `tests/test_entry_points.py` | Import smoke tests for `src.server`, `src.main` | Medium | Only checks importability; no behavior | Keep as smoke; consider timeouts + add to a “smoke” marker |
| `tests/test_trio_validation.py` | Trio “environment” validation | Low–Medium | Time-based sleep assertion can be flaky; mostly verifies Trio itself | Keep only if it guards real env regressions; otherwise move to smoke or remove |
| `tests/unit/test_version.py` | Version parsing/comparison | High | Looks solid | Keep |
| `tests/unit/test_auth_service.py` | JWT + bcrypt behavior | High | Uses real time sleeps (slow/flaky potential) | Keep; replace sleeps with time control if needed |
| `tests/unit/test_tier_data_models.py` | Pydantic model validation/serialization | High | Large but valuable schema invariants | Keep |
| `tests/unit/test_schema_generation.py` | Schema generation parity check | High | Requires schemas to stay committed + up to date | Keep; this is a strong release gate |
| `tests/unit/test_style_service.py` | Style pack loading + validity | Medium | Assumes specific style IDs exist; `is_valid()` only checks file existence, not content | Keep; consider improving validity definition + corresponding tests |
| `tests/unit/test_session_timer.py` | Session timer math | Medium | Real-time based, wide tolerances; could still be flaky | Keep; refactor to deterministic clock or injectable time source |
| `tests/unit/test_service_container.py` | DI container + agent wiring | Medium–High | Reasonable; some tests check stringified type names | Keep; prefer asserting behavior over class-name strings where possible |
| `tests/unit/test_trio_db_service.py` | DB persistence + migrations + auth tables | High | Uses private `_create_connection`; lots of value otherwise | Keep; consider migration-from-old-schema test using an older DB fixture |
| `tests/unit/test_trio_server.py` | Server init ordering + health check | Medium–High | Reasonable; avoids real serving via patch | Keep |
| `tests/unit/test_trio_agent_orchestrator.py` | Orchestrator response handling + plan creation | Medium | Mostly mock-driven; still validates branching logic | Keep; add stronger assertions on persisted results where applicable |
| `tests/unit/test_trio_psychoanalyst_agent.py` | Resumption/briefing prompt composition + context assembly | Medium | Several tests are “string contains”; one test has no meaningful assertion about style | Keep; tighten assertions + add negative/error path tests |
| `tests/unit/test_trio_reflection_agent.py` | Briefing generation + fail-fast behavior | High | Good focus on the “don’t swallow exceptions” bug class | Keep |
| `tests/unit/test_llm_service.py` | LLM adapter + rate limiting | High | Depends on langchain message types; otherwise deterministic | Keep; validates role mapping, streaming chunk filtering, error wrapping, and Trio `MockClock` rate limiting |
| `tests/unit/test_rag_service.py` | RAG retrieval + persistence | Medium–High | Requires FAISS; otherwise deterministic | Keep; validates ranking/filtering and that the FAISS index persists + reloads correctly |

---

## Backend Integration Tests — Assessment (pytest-trio)

### Summary
Backend integration coverage is broad: HTTP endpoints, WebSocket flows, workflow orchestration, agent integration, and long “patient journey” suites. The shared TrioServer fixture uses an ephemeral port + health-check loop, and there is an explicit WebSocket protocol contract test. The main remaining risk is runtime and brittleness in the largest flow tests (they still include some fixed sleeps and cover a lot of behavior per file).

### Per-file assessment (backend integration)

| File | Intent | Meaningfulness | Key issues | Recommendation |
|---|---|---:|---|---|
| `tests/integration/test_trio_flow.py` | HTTP + DB integration | High | None notable | Keep |
| `tests/integration/test_websocket_protocol_contract.py` | WebSocket protocol contract | High | Relies on documented message shapes | Keep; treat as protocol gate |
| `tests/integration/test_trio_orchestration.py` | Orchestration + workflow integration | High | Some assertions are heuristic | Keep; tighten behavior assertions over time |
| `tests/integration/test_trio_agents.py` | Agent integration | Medium–High | Heavy reliance on deterministic LLM payloads | Keep |
| `tests/integration/test_console_ui_patient_flow.py` | Full “patient journey” via WS | High | Long; still uses a few fixed sleeps | Keep; consider `slow` marker if runtime hurts CI |
| `tests/integration/test_natural_patient_flow.py` | Long “natural” WS flow | Medium | Long; some sleeps; broad surface area | Keep, but consider splitting + `slow` marker |
| `tests/integration/test_auth_endpoints.py` | Auth endpoints with auth enabled | High | A few time-based assertions remain | Keep; prefer time injection where feasible |
| `tests/integration/test_console_client_auth.py` | Console client auth | Medium | Some broad assertions | Keep; tighten expectations under known config |
| `tests/integration/test_session_timer_endpoint.py` | Timer endpoint contract | Medium–High | Time-based ranges | Keep; keep ranges tight and deterministic |
| `tests/integration/test_version_endpoints.py` | Version endpoint contract | High | Minor-version edge cases | Keep |

---

## Frontend Unit Tests (Jest/RTL) — Assessment

### Summary
There is broad unit coverage across services, hooks, context, and UI components. However, several tests are ineffective or likely broken:
- `SessionHeader` tests schedule assertions in `setTimeout(...)` without awaiting → assertions never run.
- `TherapySession` tests use `act(...)` without importing it → will crash if executed.
- `ApiClient` has at least one `expect(promise).rejects...` that is not awaited/returned → may not assert.
- Many tests over-mock (e.g., `App.test.tsx`, `HomePage.test.tsx`, `SessionPage.test.tsx`) and assert on MUI class names, which inflates coverage but not confidence.

### Per-file assessment (frontend Jest)

| File | Intent | Meaningfulness | Key issues | Recommendation |
|---|---|---:|---|---|
| `frontend/src/services/__tests__/apiClient.test.ts` | Fetch wrapper behavior | High | None notable | Keep |
| `frontend/src/services/__tests__/versionService.test.ts` | Version parsing + API calls | High | Looks solid | Keep |
| `frontend/src/services/__tests__/websocketService.test.ts` | WS client behavior + reconnection | High | Implementation-detail coupling, but valuable | Keep |
| `frontend/src/hooks/__tests__/useLocalStorage.test.ts` | Storage utilities | High | Looks solid | Keep |
| `frontend/src/hooks/__tests__/useTypingIndicator.test.ts` | Typing indicator | Medium–High | “cleanup” test asserts `true` | Keep; tighten unmount assertions |
| `frontend/src/types/__tests__/converters.test.ts` | API↔UI type conversion | High | Uses `any` in places; still valuable | Keep |
| `frontend/src/types/__tests__/type-safety.test.ts` | “Type safety integration” | Low–Medium | Mostly compile-time concerns expressed as runtime tests | Consider replacing with `tsc --noEmit` (or `tsd`) in CI; keep only if it prevents real regressions |
| `frontend/src/components/__tests__/ConnectionStatus.test.tsx` | Connection status UI | Medium–High | Tooltip content not actually asserted | Keep; improve tooltip assertions via user-event hover |
| `frontend/src/components/__tests__/MessageInput.test.tsx` | Message input UX | High | Looks solid | Keep |
| `frontend/src/components/__tests__/MessageHistory.test.tsx` | Transcript UI + streaming display | High | Looks solid | Keep |
| `frontend/src/components/__tests__/SessionHeader.test.tsx` | Header/menu behavior | Medium–High | Some assertions still check MUI structure | Keep; prefer user-visible assertions where feasible |
| `frontend/src/components/__tests__/Navigation.test.tsx` | Navigation menu gating | Medium | Heavy reliance on MUI classes and `require(...).useAppContext` spying | Keep; prefer user-level assertions; ensure mocks restored |
| `frontend/src/components/__tests__/Dashboard.test.tsx` | Dashboard UX for states | Medium | Some generic assertions | Keep; tighten UX-level expectations as the UI stabilizes |
| `frontend/src/components/__tests__/TherapySession.test.tsx` | Main session UI logic | High | Relies on hook mocking (by design) | Keep; complements Playwright golden path |
| `frontend/src/contexts/__tests__/AppContext.test.tsx` | App state reducer/actions | Medium–High | Very large; likely valuable; risk of over-testing internals | Keep; consider splitting by concern and adding higher-level integration tests |
| `frontend/src/pages/__tests__/HomePage.test.tsx` | Home page wrapper | Low | Mocks Dashboard; trivial | Remove or keep as minimal smoke only |
| `frontend/src/pages/__tests__/SessionPage.test.tsx` | Session route parameter plumbing | Low | Mocks TherapySession; trivial | Remove or keep minimal |
| `frontend/src/pages/__tests__/NotFoundPage.test.tsx` | 404 UX | Medium | Many MUI-class assertions | Keep; prefer user-visible behavior |
| `frontend/src/pages/__tests__/SessionHistoryPage.test.tsx` | Fetch + UI for history | Medium–High | Mocks `useAppContext` and fetch; still good | Keep |

---

## Frontend E2E Tests (Playwright) — Assessment

### Summary
Playwright is now **self-contained**: `frontend/playwright.config.ts` starts the deterministic backend (`src/psychoanalyst_app/e2e_server.py`) and the frontend dev server automatically. The suite includes a deterministic “golden path” and negative-path coverage (auth guard + WebSocket reconnect).

| File | Intent | Meaningfulness | Key issues | Recommendation |
|---|---|---:|---|---|
| `frontend/e2e/golden-path.spec.ts` | Happy-path full-stack smoke | High | None notable (deterministic backend) | Keep; this is the main “green ⇒ working” signal |
| `frontend/e2e/auth-guards.spec.ts` | API auth guard | High | None notable | Keep |
| `frontend/e2e/websocket-reconnect.spec.ts` | WS disconnect/reconnect UX | Medium–High | Timing-sensitive by nature | Keep; ensures reconnection path stays functional |
| `frontend/e2e/auth.spec.ts` | Register/login flows | Medium | Some overlap with golden path | Keep (or prune if runtime becomes an issue) |
| `frontend/e2e/navigation.spec.ts` | Routing + protected routes | Medium | Some assertions are intentionally generic | Keep; tighten if it becomes noisy |
| `frontend/e2e/version-check.spec.ts` | Version check UX | Medium–High | Requires stable `/api/version/check` behavior | Keep |

---

## Alignment With Best Practices (What’s Good / What’s Not)

### What’s already aligned
- Strong use of **mocking for external services** (LLM/RAG) in backend integration tests.
- Many backend integration tests validate **real WebSocket streaming** and **database persistence**, which is high value.
- There is an explicit effort to test **fail-fast behavior** and avoid swallowed exceptions (reflection agent tests).
- Deterministic full-stack E2E now exists (backend fakes + Playwright) to raise confidence beyond unit/integration scope.

### Where it diverges from best practices
- **Some long-flow integration suites still use fixed sleeps**, which can be slow and brittle (prefer event-driven waits).
- **Backend coverage isn’t enforced yet** (optional improvement; would require adding `pytest-cov`).
- **Some frontend unit tests assert implementation details** (MUI class names), which can be noisy during UI refactors.

---

## Remaining Gaps (What Still Risks “Green = Working”)

### 1) Deterministic test environment for full-stack flows
Implemented:
- `src/psychoanalyst_app/e2e_server.py` runs a deterministic backend (no network, no API keys).
- `frontend/playwright.config.ts` starts backend + frontend automatically for Playwright runs.
- E2E coverage: `frontend/e2e/golden-path.spec.ts`, `frontend/e2e/auth-guards.spec.ts`, `frontend/e2e/websocket-reconnect.spec.ts`.

### 2) Production adapter tests for LLM and RAG
Implemented:
- `tests/unit/test_llm_service.py` validates role mapping, streaming chunk filtering, structured output wiring, error wrapping, and Trio `MockClock` rate limiting.
- `tests/unit/test_rag_service.py` validates deterministic retrieval, source filtering, and persistence (index save/load).

### 3) Contract tests for the WebSocket protocol
Implemented:
- `tests/integration/test_websocket_protocol_contract.py` validates key protocol messages against the documented shapes.

### 4) Migration tests that simulate real upgrades
There are schema existence checks, but limited coverage of:
- Migrating an *existing* DB with data from prior schema versions.
- Backward-compat behavior for partial rows / missing fields.

### 5) CI orchestration and test selection
Implemented:
- `make test-all` runs backend (excluding `real_llm`) + frontend Jest + deterministic Playwright E2E.
- `make test` runs deterministic backend tests; `make test-real-llm` runs external-service tests explicitly.
- Schema drift is gated by the committed-schema parity check in `tests/unit/test_schema_generation.py`.

---

## Improvement Plan (Prioritized, Concrete)
Status: Implemented (kept below as the original plan text for reference).

### Phase 0 — Fix “false green” tests (1–2 days)
**Goal:** Eliminate tests that pass without verifying behavior; ensure basic suite is trustworthy.

Backend:
1. Remove or rewrite `tests/test_devcontainer.py` so it fails when broken (or move to `scripts/`).
2. Rewrite or remove `tests/unit/test_llm_service.py` and mock-only portions of `tests/unit/test_rag_service.py`.
3. Make marker selection match Makefile intent:
   - Add automatic marking by folder (mark `tests/unit/**` as `unit`, `tests/integration/**` as `integration`) via `pytest_collection_modifyitems`.
   - Or adjust Makefile to use paths instead of markers.
4. Replace hardcoded ports in shared server fixtures with ephemeral ports.
5. Remove `-p no:warnings` (or at least allow warnings during CI) so broken tests don’t silently pass.

Frontend:
1. Fix `frontend/src/components/__tests__/SessionHeader.test.tsx` by replacing `setTimeout` assertions with `await waitFor(...)`.
2. Fix `frontend/src/components/__tests__/TherapySession.test.tsx` by importing `act` (or avoiding explicit `act` by using RTL user events + `waitFor`).
3. Fix async assertion in `frontend/src/services/__tests__/apiClient.test.ts` (return/await the `.rejects` expectation).
4. Add `afterEach(jest.restoreAllMocks)` where module spies are used heavily (e.g., Dashboard).

Deliverable:
- A test suite where “pass” implies assertions executed.

### Phase 1 — Strengthen backend unit tests for LLM + RAG (2–4 days)
**Goal:** Validate production adapters with deterministic fakes (no external network).

LLM:
- Add tests for `TrioRateLimiter` using Trio’s test clock (`trio.testing.MockClock`) to avoid real sleeps.
- Patch `ChatGoogleGenerativeAI` with a fake implementation to assert:
  - context role mapping → message types (`SystemMessage`, `HumanMessage`, `AIMessage`)
  - streaming collects non-empty chunks
  - exceptions propagate as `LLMServiceError` with stacktrace included

RAG:
- Refactor `RAGService` to allow injecting an embedding function or `EmbeddingUtils` instance.
- Add deterministic retrieval tests using a fixed embedding stub (e.g., map strings → small vectors).
- Add persistence tests (index saved/loaded) without relying on external model downloads.

Deliverable:
- LLM/RAG tests that fail when the real adapter logic breaks.

### Phase 2 — Harden backend integration suite (2–5 days)
**Goal:** Reduce flakiness and increase signal from integration tests.

1. Replace “sleep then assert” patterns with explicit event-driven waits (`trio.fail_after` loops on conditions).
2. Tighten auth tests: when auth is enabled in the fixture, assert `401` (not `[200, 401]`).
3. Consolidate version tests into one suite (keep either endpoints-focused or cross-client-focused, not both).
4. Ensure all integration tests are consistently marked `@pytest.mark.integration`.
5. Add one “contract-level” WebSocket integration test that validates emitted payload shapes against documented protocol (or a shared schema).

Deliverable:
- Stable integration tests that fail only on real regressions.

### Phase 3 — Establish deterministic full-stack E2E (Playwright) (3–7 days)
**Goal:** Make “tests green” strongly correlate with a working application for real users.

1. Provide a test mode for the backend:
   - Start `TrioServer` with deterministic fake LLM/RAG (same approach used in pytest fixtures).
   - Expose configuration via env (e.g., `TEST_MODE=1`) so Playwright can start it as a subprocess.
2. Update Playwright config to start both backend and frontend for E2E runs (e.g., `npm-run-all` or a small Node script).
3. Add a small “golden path” suite:
   - Register → login → dashboard → start therapy session → send message → verify streamed assistant response appears.
4. Add one negative-path suite:
   - Auth required endpoints fail without token (UI shows error).
   - WebSocket disconnect triggers reconnection UI state.

Deliverable:
- A minimal but high-value E2E suite that runs locally and in CI without API keys.

### Phase 4 — Optional: Real LLM/RAG smoke tests (nightly / manual)
**Goal:** Catch upstream API changes and production-only failures without blocking PRs.

1. Move real-LLM tests into a dedicated folder and marker (e.g., `real_llm`).
2. Run them only when secrets are available (nightly schedule).
3. Use robust assertions:
   - Validate structured outputs against schema.
   - Avoid exact text matching.
   - Keep token usage low and enforce rate limiting.

Deliverable:
- A “production realism” suite that complements deterministic CI tests.

### Phase 5 — CI/Dev Workflow Integration (1–3 days)
**Goal:** One command / one CI pipeline that truly reflects application health.

1. Add a root-level `make test-all` that runs:
   - backend unit + integration
   - frontend Jest
   - E2E smoke (optional on PR, required on main/nightly)
2. Enforce coverage where it matters (backend via `pytest-cov`, frontend already has thresholds).
3. Ensure schema generation is validated:
   - Generate schemas to temp and compare to committed output, or run schema generation in CI and fail on diff.

Deliverable:
- “All tests pass” becomes a meaningful release gate.

---

## Definition of Done (Target State)

When the plan is complete:
- A clean run of `make test-all` (or CI equivalent) starts from scratch and produces deterministic results.
- Backend unit tests cover all core adapters (DB, LLM, RAG, orchestration) without relying on real external services.
- Backend integration tests cover HTTP + WebSocket flows with deterministic fakes and no hard-coded ports.
- Frontend unit tests run reliably and avoid false greens (all async assertions awaited).
- Full-stack E2E includes at least one happy path that exercises:
  - auth → session creation → WS streaming → UI rendering.

---

## Quick “Next Actions” Checklist

1. Fix/relocate ineffective tests: `tests/test_devcontainer.py`, `frontend/src/components/__tests__/SessionHeader.test.tsx`, `frontend/src/components/__tests__/TherapySession.test.tsx`, `frontend/src/services/__tests__/apiClient.test.ts`.
2. Decide marker strategy: auto-mark by directory or change Makefile targets to path-based selection.
3. Introduce a shared “ephemeral port” server fixture for all backend HTTP/WS integration tests.
4. Implement deterministic fakes for LLM/RAG at the adapter boundary (not just in high-level tests).
5. Add a deterministic Playwright full-stack smoke suite that starts backend + frontend automatically.
