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
- Default backend setup is lighter because local FAISS RAG dependencies are isolated behind the optional `RAG_BACKEND=faiss` path.
- Profile login, session ending, console exit, and assessment failure fallback now have deterministic product-path coverage.
- Non-blocking follow-up issues from the 2026-05-16 verification run are tracked in `docs/plans/RELEASE_CANDIDATE_TRACKING_ISSUES_2026-05-16.md`.

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

The default backend path now uses `RAG_BACKEND=none` and no longer installs FAISS, sentence-transformers, Hugging Face Hub, or Torch through `requirements.txt`. Optional local retrieval is explicitly enabled with `RAG_BACKEND=faiss` and the separate RAG requirements path.

Residual risk: the optional RAG install remains large and should be validated before local FAISS retrieval is treated as a supported release feature. Track that follow-up in `docs/plans/RELEASE_CANDIDATE_TRACKING_ISSUES_2026-05-16.md`.

### P1 - Documentation Drift and Planning Hygiene

The repository had many active files under `docs/plans` and `docs/todo`, including completed, superseded, and exploratory plans. This made it unclear which work remained authoritative.

The clean-slate action archived those files into `docs/legacy/plans/clean-slate-2026-05-15/` and kept this single baseline in `docs/plans`.

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

### P2 - Validation Breadth - Resolved 2026-05-16

Targeted backend and documentation checks passed, and frontend type-check/build plus Jest now pass. The full project is still not proven by one complete validation run because full backend tests and deterministic E2E were not rerun in this wave.

The project now has a single Docker-only `make finalization-check` target that runs docs, schemas, architecture, backend tests, frontend type-check/build, frontend Jest, and deterministic E2E in order. That target passed end to end on 2026-05-16.

## Recommended Next Sequence

1. Keep `make finalization-check` green as the release-candidate gate.
2. Review and disposition the active release-candidate follow-up list in `docs/plans/RELEASE_CANDIDATE_TRACKING_ISSUES_2026-05-16.md`.
3. Decide whether frontend dependency audit findings are release-blocking.
4. Validate the optional FAISS RAG install path before documenting it as a supported release feature.
5. Update active docs and contracts in the same commits as future behavior changes.

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
- Frontend Jest passed with 270 tests.
- Deterministic Playwright E2E passed with 3 tests.
- Remaining non-blocking issues are tracked in `docs/plans/RELEASE_CANDIDATE_TRACKING_ISSUES_2026-05-16.md`.

## Clean-Slate Archive

Archived source folders:

- `docs/plans/*`
- `docs/todo/*`

Archive destination:

- `docs/legacy/plans/clean-slate-2026-05-15/`
