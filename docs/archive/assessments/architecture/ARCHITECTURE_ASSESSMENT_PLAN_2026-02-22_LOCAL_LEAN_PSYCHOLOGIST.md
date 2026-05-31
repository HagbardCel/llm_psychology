---
owner: engineering
status: active
last_reviewed: 2026-02-22
review_cycle_days: 30
source_of_truth_for: In-depth architecture assessment findings for a laptop-first, local AI virtual psychologist codebase
---

# Architecture Assessment Plan (Local-Lean Psychologist, 2026-02-22)

## Objective
Assess the architecture of this local AI virtual psychologist project to ensure it remains lightweight for simple laptops, clean in boundaries, and maintainable for iterative development.

## Assessment Status
Completed on 2026-02-22.

## Scope
- Backend runtime and architecture: `src/psychoanalyst_app/`
- Frontend architecture: `frontend/src/`
- Console client architecture: `console-ui/src/`
- Contracts and schema/type pipeline:
  - `docs/contracts/HTTP_API_CONTRACT.md`
  - `docs/WEBSOCKET_PROTOCOL.md`
  - `docs/TYPE_SYSTEM.md`
  - `schemas/`
- Runtime/dev governance:
  - `Makefile`
  - `scripts/check_architecture_budgets.py`
  - docs governance validation

## Baseline Snapshot (Observed)

### Code and Docs Size
| Area | Files | Lines |
|---|---:|---:|
| `src/` | 156 | 20,117 |
| `frontend/src/` | 67 | 10,133 |
| `console-ui/src/` | 6 | 1,452 |
| `tests/` | 58 | 14,084 |
| `docs/` | 141 | 62,739 |

### Current Hotspot Modules
| File | Lines |
|---|---:|
| `src/psychoanalyst_app/agents/trio_reflection_agent.py` | 656 |
| `src/psychoanalyst_app/services/llm_service.py` | 576 |
| `src/psychoanalyst_app/agents/trio_memory_agent.py` | 574 |
| `src/psychoanalyst_app/services/trio_db_service.py` | 527 |
| `src/psychoanalyst_app/orchestration/trio_conversation_manager.py` | 513 |
| `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py` | 511 |
| `src/psychoanalyst_app/agents/trio_planning_agent.py` | 510 |
| `src/psychoanalyst_app/orchestration/helpers/response_handler.py` | 487 |
| `src/psychoanalyst_app/container/service_container.py` | 487 |

### Existing Strengths
- Domain language (intake/assessment/therapy/reflection) is coherent with product intent.
- Architecture budgets and layer checks are automated and currently passing.
- Docs metadata governance and schema validation are automated and currently passing.
- No active `TODO/FIXME/HACK/XXX` markers were found in main code/test areas.

## Weighted Prioritization Model
Each finding is scored using:
- Maintainability impact: 35%
- Laptop runtime/resource impact: 30%
- Correctness/risk reduction: 20%
- Effort (inverse): 15%

Scoring scale: 1 (low) to 5 (high), normalized to a 0-100 weighted score.

## Findings (Evidence-Backed)

### F-001 (P0) Retrieval and Embedding Stack Is Eagerly Initialized
Evidence:
- RAG service is fetched during orchestration startup paths:
  - `src/psychoanalyst_app/trio_server.py:129`
  - `src/psychoanalyst_app/main.py:199`
- RAG constructor immediately constructs embedding utilities and loads/creates index:
  - `src/psychoanalyst_app/services/rag_service.py:53`
  - `src/psychoanalyst_app/services/rag_service.py:71`
  - `src/psychoanalyst_app/services/rag_service.py:74`
- Embedding utility initializes `SentenceTransformer` in constructor:
  - `src/psychoanalyst_app/utils/embedding_utils.py:12`
  - `src/psychoanalyst_app/utils/embedding_utils.py:29`

Impact:
- Startup overhead on low-resource laptops is higher than necessary.
- Memory/CPU costs are paid even when retrieval features are not used yet.

Recommendation:
1. Defer embedding model initialization and index load to first retrieval call.
2. Add explicit runtime profiles (`minimal`, `full`) via config.
3. Keep startup path free of embedding stack unless retrieval is enabled.

Score:
- Maintainability: 4
- Laptop impact: 5
- Risk reduction: 4
- Effort inverse: 3
- Weighted score: 83

---

### F-002 (P0) Dependency Footprint Is Heavy for a Simple-Laptop Baseline
Evidence:
- Core dependencies include FAISS and sentence-transformers with ONNX extras:
  - `pyproject.toml:15`
  - `pyproject.toml:16`
- Runtime lockfiles include heavyweight transitive stack (for example `torch`, `onnx`):
  - `requirements.txt:258`
  - `requirements.txt:412`
  - `requirements-dev.txt:256`
  - `requirements-dev.txt:417`

Impact:
- Slower installs/builds and larger runtime footprint.
- Harder onboarding for contributors on constrained machines.

Recommendation:
1. Split install profiles: core runtime vs optional retrieval/embedding extras.
2. Ensure minimal profile avoids torch/onnx transitive install path.
3. Add CI matrix to validate both minimal and full profiles.

Score:
- Maintainability: 4
- Laptop impact: 5
- Risk reduction: 3
- Effort inverse: 3
- Weighted score: 79

---

### F-003 (P1) Architecture Budget Coverage Misses Current Largest Runtime Modules
Evidence:
- Current large runtime files include:
  - `src/psychoanalyst_app/services/llm_service.py` (576)
  - `src/psychoanalyst_app/agents/trio_memory_agent.py` (574)
  - `src/psychoanalyst_app/agents/trio_planning_agent.py` (510)
  - `src/psychoanalyst_app/services/trio_db_service.py` (527)
- These modules are not included in budget/method checks:
  - `scripts/check_architecture_budgets.py:11`
  - `scripts/check_architecture_budgets.py:24`

Impact:
- Core hotspot growth can continue without CI feedback.
- Regression and review risk increases in high-change files.

Recommendation:
1. Extend file and method budgets to all current >500-line runtime hotspots.
2. Add budget thresholds that force decomposition plans before growth continues.
3. Add periodic hotspot trend report in architecture governance output.

Score:
- Maintainability: 4
- Laptop impact: 3
- Risk reduction: 4
- Effort inverse: 4
- Weighted score: 74

---

### F-004 (P1) Orchestration Bootstrap Wiring Is Duplicated Across Entry Points
Evidence:
- Similar orchestration setup appears in server and standalone terminal path:
  - `src/psychoanalyst_app/trio_server.py:119`
  - `src/psychoanalyst_app/main.py:205`

Impact:
- Drift risk between runtime modes.
- Duplicate maintenance for startup wiring and background job setup.

Recommendation:
1. Extract a shared orchestration bootstrap builder/factory.
2. Keep entrypoints thin (transport-specific concerns only).
3. Add tests that assert identical core wiring across entrypoints.

Score:
- Maintainability: 3
- Laptop impact: 2
- Risk reduction: 3
- Effort inverse: 4
- Weighted score: 57

---

### F-005 (P2) Documentation Surface Is Still Large Relative to Runtime Code
Evidence:
- Docs line count remains large relative to source: `62,739` vs `20,117`.
- Significant legacy/archive/supporting volume remains:
  - `docs/legacy` (~20k lines)
  - `docs/archive` (~15k lines)
  - `docs/features` (~7.7k lines)

Impact:
- Navigation overhead remains high.
- Stale or duplicate guidance risk remains non-trivial.

Recommendation:
1. Continue strict active/supporting/archive curation.
2. Add stale-doc reporting by `last_reviewed` age.
3. Add ownership escalation for overdue active docs.

Score:
- Maintainability: 4
- Laptop impact: 2
- Risk reduction: 2
- Effort inverse: 3
- Weighted score: 57

## Prioritized Improvement Backlog

### P0 (Immediate)
1. Lazy retrieval initialization and minimal runtime profile (F-001).
2. Dependency profile split with minimal install mode (F-002).

### P1 (Next)
1. Expand architecture budgets to current hotspot modules (F-003).
2. Consolidate orchestration bootstrap/wiring path (F-004).

### P2 (Later)
1. Docs consolidation and stale-governance automation improvements (F-005).

## Suggested Execution Sequence
1. Implement minimal runtime profile and lazy retrieval loading.
2. Split dependencies and enforce profile-based CI validation.
3. Extend architecture budgets to unguarded hotspot modules.
4. Extract shared orchestration bootstrap layer.
5. Continue docs governance tightening.

## Acceptance Criteria for Follow-up Implementation
- Startup path does not initialize embedding stack in minimal mode.
- Minimal install profile runs core local session loop without retrieval dependencies.
- Architecture budgets include all current >500-line runtime hotspot modules.
- Entry points share one orchestration bootstrap path.
- Docs governance includes stale-review visibility.

## Validation Log (Assessment Execution)
- Baseline and hotspot inventory:
  - `rg --files ...`, `wc -l ...`, `sort -nr ... | head`
- Marker scan:
  - `rg -n "TODO|FIXME|HACK|XXX" ...` (none found in scoped code)
- Architecture governance:
  - `make validate-architecture` -> pass (`Validated budgets: 10`, `Validated method budgets: 7`)
- Docs governance:
  - `make validate-docs` -> pass (`Validated active docs: 11`)
- Schema integrity:
  - `make validate-schemas` -> pass (all schemas valid)

## Decision Log
- 2026-02-22: Replaced financial-scoped latest assessment with psychologist-focused scope.
- 2026-02-22: Kept weighted scoring model for prioritization.
- 2026-02-22: Prioritized runtime weight reduction for laptop-first operation.
