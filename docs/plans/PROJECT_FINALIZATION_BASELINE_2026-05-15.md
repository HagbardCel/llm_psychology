---
owner: engineering
status: supporting
last_reviewed: 2026-05-16
review_cycle_days: 30
source_of_truth_for: Current finalization baseline, open findings, and next improvement priorities
---

# Project Finalization Baseline (2026-05-15)

## Purpose

This document is the active baseline for improving and finalizing the local AI virtual psychologist project. It replaces the older implementation plans and todo notes that were moved to `docs/legacy/plans/clean-slate-2026-05-15/`.

Use this file as the starting point for new remediation work. Historical plans may provide context, but they are no longer current guidance.

## Current State

- The branch has a reproducible frontend validation path after the first finalization implementation wave.
- Architecture simplification has progressed: active architecture docs are leaner, orchestration hotspots were split, structured assessment outputs were introduced, and WebSocket message constants now use generated protocol values in key paths.
- The Docker-only `make finalization-check` path now passes end to end after release-candidate hardening.
- Default backend setup is lighter because `RAG_BACKEND=none` is the only supported release path and local FAISS retrieval has been deferred.
- Profile login, session ending, console exit, and assessment failure fallback now have deterministic product-path coverage.
- Release-candidate signal cleanup resolved the backend async warning, frontend Vitest warning noise, and the large frontend bundle warning.
- The remaining non-blocking follow-up from the 2026-05-16 verification run was resolved by deferring optional FAISS RAG support out of the current release.
- The Node 26 Playwright `DEP0205` warning has been traced to Playwright 1.60.0 internals and accepted as a non-blocking upstream tolerance until Playwright ships a compatible fix.
- Intake completion is now deterministic: terminal intake responses are direct static messages, so the backend no longer asks a final follow-up question immediately before advancing to assessment.
- Console therapy style selection is verified as a first-class workflow action: recommendations are cached, the user can select by number or style id, and the console posts the selected style to the workflow endpoint.
- The resolved `docs/current_issues` notes were archived under `docs/archive/current_issues/2026-05-16/`, so the current-issues folder no longer carries closed release-candidate problems.
- Release validation now has generated-contract drift checks and a single Docker-only GitHub Actions gate that runs the same `make finalization-check` path used locally.
- The resolved release-candidate tracking note was archived under `docs/archive/plans/2026-05-16/`, so `docs/plans/` contains only the active finalization baseline.

## Findings

### P0 - Frontend Validation Reproducibility - Resolved 2026-05-15

The original MUI Grid type-check failure was caused by stale frontend dependencies, not by invalid source code. The lockfile resolves MUI 7.3.6 where `Grid size={{ ... }}` is valid, but Docker images and the dev `node_modules` volume could still expose older MUI 5 modules.

The fix established lockfile-backed frontend Docker validation:

- `frontend/Dockerfile.dev` now installs with `npm ci`.
- `frontend/.dockerignore` prevents host `node_modules` from overwriting image dependencies.
- `make validate-frontend` runs type-check and Vite build in an isolated Docker container.
- `make frontend-sync-deps` refreshes the dev frontend dependency volume.

### P1 - Dependency Footprint and Docker Build Cost - Resolved 2026-05-16

`make validate-architecture` completed successfully, but the first run pulled and exported a very large backend dependency stack, including heavy ML/runtime packages such as Torch, Triton, NVIDIA package families, FAISS, sentence-transformers, and ONNX-related dependencies.

The default backend path now uses `RAG_BACKEND=none` and no longer installs FAISS, sentence-transformers, Hugging Face Hub, or Torch through `requirements.txt`. Local FAISS retrieval is not a supported backend in the current release.

The optional RAG install risk was removed from release scope by deleting the active optional dependency files/package extra and making non-`none` RAG backends fail fast as future-extension work.

### P1 - Documentation Drift and Planning Hygiene - Resolved 2026-05-16

The repository had many active files under `docs/plans` and `docs/todo`, including completed, superseded, and exploratory plans. This made it unclear which work remained authoritative.

The clean-slate action archived those files into `docs/legacy/plans/clean-slate-2026-05-15/` and kept this single baseline in `docs/plans`.

The post-verification release-candidate tracking note was also archived after
all of its findings were resolved or accepted as release tolerances.

### P1 - Product Finalization Gaps - Resolved 2026-05-16

Several product-facing areas still need focused review before finalization:

- session ending behavior across backend, web UI, and console UI,
- user/profile selection and login flow,
- assessment stability under quota exhaustion and provider failures,
- consistency between active contracts, generated schemas, frontend types, and client behavior.

The release-candidate hardening pass closed these gaps:

- the web UI lists existing profiles, supports login, and still allows new profile creation,
- the web session-ending flow sends `end_session` and waits for `session_ended` before marking the session complete,
- the console `/quit` and `/exit` flows wait briefly for `session_ended`,
- failed or quota-exhausted assessment jobs emit a WebSocket `error`, send deterministic fallback recommendations, and transition to `ASSESSMENT_COMPLETE`,
- frontend and backend tests now cover the hardened paths.

### P1 - Abrupt Intake End After Follow-Up Prompt - Resolved 2026-05-16

The console intake flow could show an LLM-generated closing response that asked another user-facing question while the backend immediately transitioned into assessment. This made the session appear to end abruptly before the user could answer.

The intake agent now uses direct static responses for intake completion and time-up terminal messages. Completion still emits `COMPLETE_INTAKE` and starts the assessment path, but the streamed text no longer asks follow-up questions. Time-up without completion still leaves intake in progress for the next session and now also bypasses LLM generation.

### P1 - Console Therapy Style Selection - Resolved 2026-05-16

The console UI previously exposed backend API instructions after assessment recommendations instead of presenting the workflow selection step as an in-client action.

The console workflow now caches `assessment_recommendations`, exits chat mode when the backend returns `required_action=select_therapy_style`, prompts the user for a recommendation number or style id, and submits `selected_therapy_style` through `/api/workflow/select_therapy_style`. Regression coverage verifies that `_follow_workflow()` dispatches the selection action instead of treating the numeric choice as chat input.

The historical issue notes for abrupt intake ending and therapy style selection were moved from `docs/current_issues/` to `docs/archive/current_issues/2026-05-16/`, and assessment references now point to those archived records as resolved context.

### P2 - Validation Breadth - Resolved 2026-05-16

Targeted backend and documentation checks passed, and frontend type-check/build plus unit tests now pass. The full project is still not proven by one complete validation run because full backend tests and deterministic E2E were not rerun in this wave.

The project now has a single Docker-only `make finalization-check` target that runs docs, schemas, architecture, backend tests, frontend type-check/build, frontend Vitest, and deterministic E2E in order. That target passed end to end on 2026-05-16.

### P2 - Release Gate and Generated Contract Drift - Resolved 2026-05-16

The local release-candidate gate was stronger than CI: the active GitHub Actions workflows were split across docs, architecture, and type-safety checks, and still used host Python/Node setup paths even though the project is Docker-only and the frontend requires Node 26 tooling.

The gate now includes `make validate-generated-contracts`, which checks generated WebSocket protocol constants and frontend API types without rewriting tracked files. GitHub Actions now uses a single Docker-backed release-candidate workflow that runs `make finalization-check`, then verifies whitespace and stale generated diffs with `git diff --check` and `git diff --exit-code`.

## Recommended Next Sequence

1. Keep `make finalization-check` green as the release-candidate gate.
2. Keep the frontend dependency audit clean after the Node 26 and package refresh.
3. Keep generated contract drift checks in the release-candidate gate when changing schemas, WebSocket protocol constants, or frontend generated types.
4. Keep local FAISS RAG retrieval out of the release path until a future extension has its own dependency, image-size, and retrieval-quality validation plan.
5. Recheck the accepted Node 26 Playwright `DEP0205` tolerance when upgrading Playwright beyond 1.60.0 or if CI begins failing on deprecation warnings.
6. Keep `docs/current_issues/` reserved for active problems; move resolved issue notes to `docs/archive/current_issues/` with a status note.
7. Update active docs and contracts in the same commits as future behavior changes.

## Validation Snapshot

Known passing checks after the first finalization implementation wave:

- `make validate-architecture`
- `make validate-docs`
- `make validate-schemas`
- `make validate-frontend`
- `make test-frontend`
- `make frontend-sync-deps`
- targeted backend unit tests for Trio intake, schema generation, logging config, Trio assessment, and workflow next-action behavior

2026-05-16 release-candidate hardening update:

- `make finalization-check` passed end to end through Docker.
- Backend tests passed with 318 passed, 2 skipped, and 1 warning.
- Frontend Vitest passed with 270 tests.
- Deterministic Playwright E2E passed with 3 tests.
- The temporary release-candidate tracking note later closed out all
  non-blocking findings and was archived under
  `docs/archive/plans/2026-05-16/`.

2026-05-16 release-candidate signal cleanup update:

- `make finalization-check` passed end to end through Docker.
- Backend tests passed with 318 passed and 2 skipped, without the previous `AsyncMock` warning.
- Frontend validation passed with no Vite large chunk warning; the largest emitted chunks were `vendor-react` at approximately 395 kB and `vendor-mui` at approximately 389 kB minified.
- Frontend Vitest passed with 270 tests and no repeated React act or simulated WebSocket warning blocks.
- Deterministic Playwright E2E passed with 3 tests.
- Optional FAISS RAG dependency validation is no longer an open release-candidate follow-up; FAISS support was deferred out of scope, and `RAG_BACKEND=none` remains the supported path.

2026-05-16 RAG deferral update:

- `make finalization-check` passed end to end through Docker after removing the active optional FAISS dependency path.
- Backend tests passed with 314 passed and 6 skipped; the additional skipped tests are the dormant FAISS retrieval tests retained for future-extension work.
- Frontend Vitest passed with 270 tests.
- Deterministic Playwright E2E passed with 3 tests.
- Node 26 Playwright `DEP0205` warnings still appear during E2E and remain a non-blocking signal-cleanup item if they become noisy in CI.

2026-05-16 Playwright warning disposition update:

- `make test-e2e` passed with 3 deterministic Playwright tests.
- `NODE_OPTIONS=--trace-deprecation npx playwright test` traced the `DEP0205` warning to Playwright's internal `registerESMLoader` path in `node_modules/playwright/lib/common/index.js`.
- The frontend E2E image uses `@playwright/test` 1.60.0 and `playwright` 1.60.0; `npm view @playwright/test version` reports 1.60.0 as current.
- The warning is accepted as a non-blocking upstream Node 26 compatibility tolerance for the current release candidate, without project-level warning suppression.

2026-05-16 deterministic intake closure update:

- `make docker-test-one TEST=tests/unit/test_trio_intake_agent.py` passed with 2 tests.
- `make docker-test-one TEST=tests/unit/test_console_client_workflow.py` passed with 5 tests.
- `make finalization-check` passed end to end through Docker.
- Backend tests passed with 314 passed and 6 skipped.
- Frontend Vitest passed with 270 tests.
- Deterministic Playwright E2E passed with 3 tests.
- The accepted Node 26 Playwright `DEP0205` warnings still appear during E2E and remain an upstream tolerance.

2026-05-16 current-issue closeout update:

- `make docker-test-one TEST=tests/unit/test_console_client_workflow.py` passed with 6 tests, including regression coverage for `_follow_workflow()` dispatching `select_therapy_style`.
- `make docker-test-one TEST=tests/unit/test_workflow_routes.py` passed with 2 tests.
- `make validate-docs` passed with 11 active docs validated.
- `git diff --check` passed.
- Resolved current-issue notes were archived under `docs/archive/current_issues/2026-05-16/`.

2026-05-16 release-gate consolidation update:

- `make validate-generated-contracts` passed through Docker.
- WebSocket generated files were confirmed up to date without rewriting tracked files.
- Frontend generated API types were regenerated in a temporary file and matched the committed file after ignoring the volatile generation timestamp.
- `make finalization-check` passed end to end through Docker with the new generated-contract gate included.
- Backend tests passed with 315 passed and 6 skipped.
- Frontend validation passed with no Vite large chunk warning; the largest emitted chunks remained `vendor-react` at approximately 395 kB and `vendor-mui` at approximately 389 kB minified.
- Frontend Vitest passed with 270 tests.
- Deterministic Playwright E2E passed with 3 tests; the accepted Node 26 Playwright `DEP0205` warnings still appear and remain an upstream tolerance.
- GitHub Actions was consolidated to a Docker-only release-candidate workflow that runs `make finalization-check`, `git diff --check`, and `git diff --exit-code`.

2026-05-16 planning closeout update:

- The resolved release-candidate tracking note was moved from `docs/plans/`
  to `docs/archive/plans/2026-05-16/` and marked `status: archived`.
- `docs/plans/` now contains only this active finalization baseline.
- `make validate-docs` passed with 11 active docs validated.
- `make finalization-check` passed end to end through Docker.
- Backend tests passed with 315 passed and 6 skipped.
- Frontend Vitest passed with 270 tests.
- Deterministic Playwright E2E passed with 3 tests; the accepted Node 26
  Playwright `DEP0205` warnings still appear and remain an upstream tolerance.
- `git diff --check` passed.

## Clean-Slate Archive

Archived source folders:

- `docs/plans/*`
- `docs/todo/*`

Archive destination:

- `docs/legacy/plans/clean-slate-2026-05-15/`
