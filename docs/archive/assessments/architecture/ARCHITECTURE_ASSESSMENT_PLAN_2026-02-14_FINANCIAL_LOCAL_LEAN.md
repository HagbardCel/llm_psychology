---
owner: engineering
status: active
last_reviewed: 2026-02-14
review_cycle_days: 30
source_of_truth_for: In-depth architecture assessment plan for a laptop-first, lean financial-analysis codebase
---

# Architecture Assessment Plan (Financial, Local-Lean, 2026-02-14)

## Objective
Run an in-depth architecture assessment to ensure this project remains:
- lightweight enough for a simple laptop,
- clean and maintainable for a small team,
- focused on efficient financial analysis workflows (not framework-heavy platform work).

This document is both:
- the execution plan for the assessment, and
- the findings log for concrete improvements.

## Assessment Success Criteria
The assessment is successful when it produces:
1. A ranked list of architecture issues with evidence.
2. A practical remediation roadmap (P0/P1/P2) that avoids unnecessary complexity.
3. Measurable targets for runtime footprint, code complexity, and developer friction.

## Scope
- Backend core: `src/psychoanalyst_app/`
- Frontend core: `frontend/src/`
- Console client: `console-ui/src/`
- Contracts and types: `docs/contracts/HTTP_API_CONTRACT.md`, `docs/WEBSOCKET_PROTOCOL.md`, `docs/TYPE_SYSTEM.md`, `schemas/`
- Build and dev workflow: `Makefile`, `docker-compose.yml`, test and schema/type generation flows

## Non-Goals
- Shipping new product features before architecture evidence is collected.
- Large rewrites without a measured before/after benefit.
- Premature scaling work for multi-node/cloud-first operation.

## Key Questions
1. Which modules carry too much responsibility and should be split or simplified?
2. Which dependencies, services, or runtime defaults are too heavy for laptop-first usage?
3. Where are boundaries unclear (gateway/orchestration/agent/service/client)?
4. Which contracts/types/docs are duplicated or drifting?
5. Which workflows increase maintenance cost without clear product value?

## Method (In-Depth)

### Phase 1: Architecture Inventory
- Build a module map: responsibilities, coupling, and ownership.
- Identify hotspot files by size, churn, and responsibility mixing.
- Inventory TODO/FIXME and stale paths.

Output:
- Hotspot table with risk notes.
- Boundary map (expected vs actual).

### Phase 2: Runtime and Resource Audit (Laptop Focus)
- Measure startup/runtime assumptions and expensive defaults.
- Audit logging volume and persisted artifacts.
- Review local storage/database/index growth behavior.

Output:
- Baseline resource profile and bottleneck list.
- Candidate runtime simplifications.

### Phase 3: Workflow and Boundary Audit
- Validate gateway -> orchestration -> agent -> service separation.
- Detect I/O leakage into domain logic.
- Check client duplication of backend workflow decisions.

Output:
- Boundary violations list with concrete file references.

### Phase 4: Contract and Type Integrity Audit
- Verify API DTOs, WebSocket envelopes, schema generation, and frontend types stay aligned.
- Identify duplicated payload shaping logic across layers.

Output:
- Contract-drift report and normalization opportunities.

### Phase 5: Maintainability and DX Audit
- Evaluate contributor path-to-productivity.
- Audit doc sprawl and conflicting guidance.
- Validate Docker-first workflow ergonomics and command surface simplicity.

Output:
- Friction map (change-cost drivers + simplification targets).

### Phase 6: Prioritization and Remediation Plan
- Score each finding with weighted criteria:
  - maintainability impact (30%),
  - laptop runtime/resource impact (30%),
  - correctness/risk reduction (20%),
  - effort (inverse, 20%).
- Classify as P0, P1, P2, or Reject.

Output:
- Incremental roadmap with acceptance criteria per item.

## Evidence Collection Checklist
Use Docker/containerized commands where execution is needed.

- Codebase shape:
  - `rg --files src frontend/src console-ui/src tests docs`
  - `wc -l $(rg --files src frontend/src console-ui/src tests docs)`
  - `rg -n "TODO|FIXME|HACK|XXX" src frontend/src console-ui/src`
- Dependency usage:
  - Compare declared dependencies with import usage via `rg`.
- Boundary integrity:
  - Trace key flows from API/WS entry points into orchestration and services.
- Contract integrity:
  - Regenerate and validate schemas/types, then diff outputs.
- Confidence checks:
  - Run targeted tests around touched architecture areas.

## Deliverables
1. `Assessment Findings` section completed in this file.
2. Prioritized remediation backlog with owner + effort + acceptance checks.
3. Follow-up implementation plan docs for approved P0/P1 items.

## Candidate Improvements To Validate
These are hypotheses; confirm with evidence before implementation.

### C-01 (Likely P0): Remove unnecessary runtime and dependency weight
- Remove unused/heavy dependencies and stale package configuration.
- Remove committed runtime artifacts from source paths.
- Tighten default runtime profile for low-memory laptops.

### C-02 (Likely P0): Reduce oversized modules and mixed responsibilities
- Split very large files into focused modules by responsibility.
- Keep side effects in orchestration/services; keep agents deterministic.

### C-03 (Likely P0): Make logging lean and safe by default
- Set verbose payload logging to explicit debug mode.
- Add redaction/sampling and lower default log volume.

### C-04 (Likely P1): Eliminate configuration drift
- Remove unused env/config knobs or wire them end-to-end with tests.
- Ensure tuning parameters actually affect runtime behavior.

### C-05 (Likely P1): Consolidate duplicated API/state shaping logic
- Centralize profile/state merge and normalization behavior.
- Keep client logic thin and backend-driven for workflow policy.

### C-06 (Likely P1): Align architecture to financial-analysis product intent
- Evaluate therapy-domain abstractions that add complexity without financial-analysis value.
- Rename or isolate domain-specific layers to reduce conceptual load.

### C-07 (Likely P2): Prune docs and implementation-plan sprawl
- Archive or consolidate stale plans.
- Keep one canonical active path for architecture and workflow guidance.

## Findings Log (Fill During Assessment)

| ID | Priority | Finding | Evidence (files/metrics) | Impact | Recommendation | Effort |
|---|---|---|---|---|---|---|
| F-001 |  |  |  |  |  |  |
| F-002 |  |  |  |  |  |  |
| F-003 |  |  |  |  |  |  |

## Remediation Backlog (Post-Assessment)

| Priority | Item | Owner | Acceptance Criteria | Status |
|---|---|---|---|---|
| P0 |  |  |  | Planned |
| P1 |  |  |  | Planned |
| P2 |  |  |  | Planned |

## Execution Notes
- Keep each remediation step small and reversible.
- Prefer deletion/simplification over abstraction expansion.
- Require tests for behavior-affecting architectural changes.
