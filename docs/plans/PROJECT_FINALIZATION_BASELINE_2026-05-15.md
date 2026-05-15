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

- The branch has a reproducible frontend validation path after the first finalization implementation wave.
- Architecture simplification has progressed: active architecture docs are leaner, orchestration hotspots were split, structured assessment outputs were introduced, and WebSocket message constants now use generated protocol values in key paths.
- Documentation, schema, architecture, frontend type-check/build, and frontend Jest checks pass through Docker.
- The clearest remaining validation gap is a full backend suite plus deterministic E2E run after the next behavior-focused changes.

## Findings

### P0 - Frontend Validation Reproducibility - Resolved 2026-05-15

The original MUI Grid type-check failure was caused by stale frontend dependencies, not by invalid source code. The lockfile resolves MUI 7.3.6 where `Grid size={{ ... }}` is valid, but Docker images and the dev `node_modules` volume could still expose older MUI 5 modules.

The fix established lockfile-backed frontend Docker validation:

- `frontend/Dockerfile.dev` now installs with `npm ci`.
- `frontend/.dockerignore` prevents host `node_modules` from overwriting image dependencies.
- `make validate-frontend` runs type-check and Vite build in an isolated Docker container.
- `make frontend-sync-deps` refreshes the dev frontend dependency volume.

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

Targeted backend and documentation checks passed, and frontend type-check/build plus Jest now pass. The full project is still not proven by one complete validation run because full backend tests and deterministic E2E were not rerun in this wave.

The finalization path should establish one repeatable Docker-only validation command set that covers docs, schemas, backend tests, frontend type-check/build, and the most important user workflow tests.

## Recommended Next Sequence

1. Run the full backend suite and deterministic E2E path through Docker.
2. Slim optional ML/dependency paths so default local setup remains practical.
3. Reassess session ending, profile selection, and assessment failure handling against current code before making product fixes.
4. Update active docs and contracts in the same commits as behavior changes.
5. Track frontend dependency audit output separately from this baseline if it becomes a release requirement.

## Validation Snapshot

Known passing checks after the first finalization implementation wave:

- `make validate-architecture`
- `make validate-docs`
- `make validate-schemas`
- `make validate-frontend`
- `make test-frontend`
- `make frontend-sync-deps`
- targeted backend unit tests for Trio intake, schema generation, logging config, Trio assessment, and workflow next-action behavior

Known validation gaps:

- full backend suite not rerun in this wave
- deterministic E2E not rerun in this wave

## Clean-Slate Archive

Archived source folders:

- `docs/plans/*`
- `docs/todo/*`

Archive destination:

- `docs/legacy/plans/clean-slate-2026-05-15/`
