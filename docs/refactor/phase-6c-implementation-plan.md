---
owner: engineering
status: accepted
last_reviewed: 2026-07-20
review_cycle_days: 30
source_of_truth_for: Detailed implementation plan for architecture refactor Phase 6C
---

# Architecture Refactor Phase 6C Implementation Plan

## 1. Phase objective

Phase 6C flips the default runtime to a reachable `jung-api` cutover and deletes the legacy infrastructure owned by `owner_pr = "6C"`. It is a deletion-and-cutover exercise—not a redesign—and stops short of 6D aggregate package deletion and Phase 7 documentation/tooling finalization.

After Phase 6C:

- Compose, Dockerfile, and entry points serve only `jung-api`;
- supported Make/VS Code/AGENTS/README surfaces are target-only;
- documentation governance treats target architecture, API v1, and workflow specification as active;
- the cutover Stage 6 validator and `finalization-check` gate enforce the new runtime;
- leftover `psychoanalyst_app` agents/orchestration/`console-ui/` remain for 6D.

Baseline: `main` at Phase 6B merge (`1db767f`). Authoritative checklist: [deletion-manifest.toml](deletion-manifest.toml).

## 2. Philosophy

- Delete, do not redesign.
- One supported runtime after cutover.
- Do not expand into 6D.
- Lean evidence (retarget existing Jung tests).
- Docs governance cutover, not rewrite.
- Extend the existing narrow Compose parser; no general YAML resolver.

## 3. Work packages

1. Manifest hygiene (evidence retargets; add `docker-compose.override.yml` and `check-usertest-key` deletes).
2. Runtime and configuration cutover (CMD, env merge, healthcheck, loopback ports, db-viewer, `env_file`/usertest profile).
3. Supported launcher and advertised-surface cutover (Make, VS Code, `.env*`, AGENTS, README).
4. Documentation-governance cutover (`ACTIVE_DOCS`, docs/README, DOCS_GOVERNANCE, ui-scope, exact index equality).
5. Strengthen Phase 6 validator (structural Compose contracts).
6. Delete 6C filesystem items.
7. Delete 6C Make targets; rewrite `finalization-check` and RC workflow.
8. Mark every 6C item complete; validate cutover + Compose smoke.

Detailed contracts for Compose, Make, validators, and docs are the accepted Phase 6C plan used to drive this implementation. Acceptance is green `validate_refactor_phase_6.py --stage cutover`, `make finalization-check`, and the failure-safe `ENV_FILE=.env.example` Compose health smoke.
