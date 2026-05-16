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
- frontend Jest: 270 passed
- deterministic Playwright E2E: 3 passed
- `git diff --check`

This file tracks non-blocking issues observed during that run. These should remain visible until they are either fixed, accepted as release tolerances, or moved into a dedicated dependency/security backlog.

## Issues To Track

### P1 - Frontend Dependency Audit Findings

`npm audit` reports 20 vulnerabilities during frontend validation:

- 1 low
- 5 moderate
- 13 high
- 1 critical

These do not currently fail `make finalization-check`, but they should be reviewed before a release candidate is declared production-ready.

### P2 - Large Frontend Bundle Chunk

Vite reports that the main `index` chunk is larger than 500 kB after minification. The observed chunk was approximately 746 kB minified.

Track whether route-level code splitting or manual chunking is needed before release. This is a performance and maintainability concern, not a current correctness failure.

### P2 - Backend AsyncMock Warning

The backend suite passes, but emits one warning in `tests/unit/test_trio_agent_orchestrator.py::test_create_therapy_plan_invalid_style`:

```text
RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited
```

This should be cleaned up so async test failures are not hidden by noisy warning output.

### P2 - Frontend Jest Warning Noise

Frontend Jest passes but emits repeated non-fatal warnings:

- `ts-jest` recommends enabling `esModuleInterop`.
- React reports that the testing environment is not configured to support `act(...)` in several MUI interaction paths.
- WebSocket service tests intentionally log simulated connection failures and disconnected-send warnings.

These warnings reduce signal during CI review and should be either fixed or explicitly filtered where they are intentional.

### P2 - Optional RAG Dependency Weight

Default backend requirements no longer include the heavy local RAG stack. Optional RAG dependencies are isolated in `requirements-rag.txt`, but that optional path remains large and includes `torch==2.12.0`.

Before treating local FAISS RAG as a supported release feature, verify the optional install path, CPU-only constraints, image size impact, and developer setup documentation.
