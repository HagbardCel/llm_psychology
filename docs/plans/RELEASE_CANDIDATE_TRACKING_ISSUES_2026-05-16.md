---
owner: engineering
status: active
last_reviewed: 2026-05-16
review_cycle_days: 14
source_of_truth_for: Release-candidate follow-up issues after Docker finalization verification
---

# Release Candidate Tracking Issues (2026-05-16)

## Verification Context

The Docker-only release-candidate verification path passed on 2026-05-16 with:

- `make finalization-check`
- backend tests: 318 passed, 2 skipped, 1 warning
- frontend Vitest: 270 passed
- deterministic Playwright E2E: 3 passed
- `git diff --check`

This file tracks non-blocking issues observed during that run. These should remain visible until they are either fixed, accepted as release tolerances, or moved into a dedicated dependency/security backlog.

## Issues To Track

### P1 - Frontend Dependency Audit Findings - Resolved 2026-05-16

The frontend runtime and package set were refreshed for Node 26, Vite 8, Vitest 4, React 19, React Router 7, and current MUI 7 releases. The obsolete PWA plugin and service worker files were removed.

`npm audit --json` now reports 0 vulnerabilities during frontend validation. Remaining install warnings are deprecated transitive dependencies from tooling, not reported security findings.

### P2 - Large Frontend Bundle Chunk - Resolved 2026-05-16

Vite reports that the main `index` chunk is larger than 500 kB after minification. The observed chunk was approximately 746 kB minified.

After the Node 26 and frontend package refresh, the observed `index` chunk is approximately 765 kB minified.

The frontend build now uses explicit Rollup manual chunks for React/router, MUI/emotion, and shared vendor dependencies. The release-candidate validation build now emits:

- `index`: approximately 30 kB minified,
- `vendor-react`: approximately 395 kB minified,
- `vendor-mui`: approximately 389 kB minified,
- no Vite large chunk warning.

### P2 - Backend AsyncMock Warning - Resolved 2026-05-16

The backend suite passes, but emits one warning in `tests/unit/test_trio_agent_orchestrator.py::test_create_therapy_plan_invalid_style`:

```text
RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited
```

The orchestrator unit tests now use explicit async method mocks instead of broad async service doubles. Targeted and full backend Docker test runs now pass without this warning.

### P2 - Frontend Vitest Warning Noise - Resolved 2026-05-16

Frontend Vitest passes but emits repeated non-fatal warnings:

- React reports that the testing environment is not configured to support `act(...)` in several MUI interaction paths.
- WebSocket service tests intentionally log simulated connection failures and disconnected-send warnings.

The old `ts-jest` warning was removed by migrating to Vitest. Remaining warnings reduce signal during CI review and should be either fixed or explicitly filtered where they are intentional.

Vitest setup now filters the known React act environment warning, and WebSocket tests silence/assert expected simulated connection logs locally. The frontend Docker test run now passes with 270 tests and no repeated warning blocks.

### P2 - Optional RAG Dependency Weight - Resolved 2026-05-16

Default backend requirements no longer include the heavy local RAG stack. FAISS-backed retrieval is deferred to a future extension instead of being treated as a release-candidate feature.

`RAG_BACKEND=none` is the only supported backend for the current release. The optional FAISS dependency files and package extra were removed from the active setup path, and `RAG_BACKEND=faiss` now fails fast with a configuration error that points to the future-extension decision.

### P2 - Node 26 Playwright DEP0205 Warning - Accepted Upstream Tolerance 2026-05-16

`make test-e2e` passes, but Node 26 emits `DEP0205` warnings from Playwright before and during the deterministic E2E run:

```text
DeprecationWarning: `module.register()` is deprecated. Use `module.registerHooks()` instead.
```

Tracing with `NODE_OPTIONS=--trace-deprecation npx playwright test` shows the warning originates in Playwright's own `registerESMLoader` path under `node_modules/playwright/lib/common/index.js`, both in the CLI process and worker processes. The project is already on `@playwright/test` 1.60.0 and `playwright` 1.60.0, and `npm view @playwright/test version` reports 1.60.0 as current.

Decision: this is accepted as a non-blocking upstream Node 26 compatibility warning for the current release candidate. Do not add broad warning suppression in project code. Revisit when a newer Playwright release is available or if CI policy starts treating Node deprecation warnings as failures.
