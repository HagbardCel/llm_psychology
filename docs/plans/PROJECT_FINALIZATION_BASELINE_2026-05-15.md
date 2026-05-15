---
owner: engineering
status: supporting
last_reviewed: 2026-05-15
review_cycle_days: 30
source_of_truth_for: Current finalization baseline, open findings, and next improvement priorities
---

# Project Finalization Baseline (2026-05-15)

## Purpose

This document is the active baseline for improving and finalizing the local AI virtual psychologist project. It replaces the older implementation plans and todo notes that were moved to `docs/legacy/plans/clean-slate-2026-05-15/`.

Use this file as the starting point for new remediation work. Historical plans may provide context, but they are no longer current guidance.

## Current State

- The branch is clean after the recent architecture, assessment, tooling, and orchestration commits.
- Architecture simplification has progressed: active architecture docs are leaner, orchestration hotspots were split, structured assessment outputs were introduced, and WebSocket message constants now use generated protocol values in key paths.
- Documentation, schema, architecture, and targeted backend checks passed during the assessment cycle.
- The frontend type-check still fails in existing MUI Grid usage and remains the clearest known validation blocker before calling the project final.

## Findings

### P0 - Frontend Type-Check Failure

`docker compose run --rm frontend npm run type-check` fails because installed MUI types reject `Grid size={{ ... }}` usage in:

- `frontend/src/components/Dashboard.tsx`
- `frontend/src/pages/AssessmentPage.tsx`

This blocks a clean full validation run. Fix this before treating the UI as release-ready.

### P1 - Dependency Footprint and Docker Build Cost

`make validate-architecture` completed successfully, but the first run pulled and exported a very large backend dependency stack, including heavy ML/runtime packages such as Torch, Triton, NVIDIA package families, FAISS, sentence-transformers, and ONNX-related dependencies.

For a local-first project, this remains a maintainability and onboarding risk. The next improvement pass should separate required runtime dependencies from optional retrieval/embedding tooling and verify that the default developer path stays lightweight.

### P1 - Documentation Drift and Planning Hygiene

The repository had many active files under `docs/plans` and `docs/todo`, including completed, superseded, and exploratory plans. This made it unclear which work remained authoritative.

The clean-slate action archived those files into `docs/legacy/plans/clean-slate-2026-05-15/` and kept this single baseline in `docs/plans`.

### P1 - Product Finalization Gaps

Several product-facing areas still need focused review before finalization:

- session ending behavior across backend, web UI, and console UI,
- user/profile selection and login flow,
- assessment stability under quota exhaustion and provider failures,
- consistency between active contracts, generated schemas, frontend types, and client behavior.

Treat archived plans as input only. Reassess each item against the current implementation before fixing it.

### P2 - Validation Breadth

Targeted backend and documentation checks passed, but the full project is not yet proven by a single clean validation run because frontend type-check currently fails.

The finalization path should establish one repeatable Docker-only validation command set that covers docs, schemas, backend tests, frontend type-check/build, and the most important user workflow tests.

## Recommended Next Sequence

1. Fix the frontend MUI Grid type errors and rerun frontend type-check.
2. Re-run the full Docker-only validation set and record exact results.
3. Slim optional ML/dependency paths so default local setup remains practical.
4. Reassess session ending, profile selection, and assessment failure handling against current code before making product fixes.
5. Update active docs and contracts in the same commits as behavior changes.

## Validation Snapshot

Known passing checks from the assessment cycle:

- `make validate-architecture`
- `make validate-docs`
- `make validate-schemas`
- targeted backend unit tests for Trio intake, schema generation, logging config, Trio assessment, and workflow next-action behavior

Known failing check:

- `docker compose run --rm frontend npm run type-check`

## Clean-Slate Archive

Archived source folders:

- `docs/plans/*`
- `docs/todo/*`

Archive destination:

- `docs/legacy/plans/clean-slate-2026-05-15/`

