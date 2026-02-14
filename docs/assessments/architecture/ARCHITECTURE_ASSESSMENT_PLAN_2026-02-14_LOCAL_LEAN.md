# Architecture Assessment Plan (Local-Lean, 2026-02-14)

## Objective
Run a deep architecture assessment focused on a **small, laptop-friendly, maintainable** codebase for efficient financial analysis workflows, then record concrete findings and prioritized improvements in this document.

## Scope
- Backend architecture: `src/psychoanalyst_app/` (gateway, orchestration, agents, services, models, container).
- Frontend architecture: `frontend/src/` (API/WS clients, state and routing responsibilities).
- Console client architecture: `console-ui/src/`.
- Contracts and documentation alignment: `docs/design-principles.md`, `docs/ARCHITECTURE.md`, `docs/contracts/HTTP_API_CONTRACT.md`, `docs/WEBSOCKET_PROTOCOL.md`, `docs/TYPE_SYSTEM.md`.
- Build/test workflow and operational ergonomics: `Makefile`, schema/type generation flow, Docker-first developer loop.

## Non-Goals
- Feature delivery.
- UI redesign.
- Large rewrites before assessment evidence is collected.

## Assessment Principles
1. Keep runtime and cognitive overhead low.
2. Prefer single sources of truth over duplicated logic.
3. Keep business logic deterministic and easy to test.
4. Optimize for local reliability over theoretical scalability.
5. Remove unused weight (dependencies, dead paths, stale docs).

## Method (In-Depth)

### Phase 1: Baseline Inventory
- Collect objective baselines: file/module size, dependency footprint, test surface, docs volume.
- Produce a hotspot map (largest files, highest-responsibility modules, TODO/FIXME concentration).
- Capture startup/runtime assumptions affecting laptop usage (model loading, DB usage, logging defaults).

### Phase 2: Architecture Boundary Audit
- Validate layering: gateway -> orchestration -> agents -> services.
- Identify boundary leaks (agent I/O, duplicate business rules in clients, orchestration helper bloat).
- Verify state-machine ownership and session lifecycle consistency.

### Phase 3: Lean Runtime Audit
- Evaluate what runs per request vs background job.
- Check synchronous/blocking bridges and concurrency ownership.
- Identify expensive defaults (embedding stack, logging policy, rate limiting defaults, pool sizes) that impact low-resource laptops.

### Phase 4: Contract and Type Pipeline Audit
- Confirm DTO/schema/type consistency across backend, frontend, and console.
- Check that generated artifacts are authoritative and reproducible.
- Verify protocol/type duplication is minimized.

### Phase 5: Developer Experience and Maintainability Audit
- Review Docker-only vs local workflow consistency.
- Evaluate how quickly a contributor can reason about and safely change core flows.
- Identify doc sprawl, outdated references, and conflicting guidance.

### Phase 6: Prioritization and Execution Roadmap
- Score findings with weighted criteria:
  - Maintainability impact: 35%
  - Local runtime/resource impact: 30%
  - Correctness/risk reduction: 20%
  - Implementation effort (inverse): 15%
- Group into:
  - P0 (do now), P1 (next), P2 (later), and “do not do”.
- Define incremental implementation steps with validation criteria per item.

## Evidence Checklist
- Static inventory: `rg --files`, `wc -l`, `du -sh`, `rg -n "TODO|FIXME"`.
- Dependency usage: scan for imports/usages of heavy or legacy packages.
- Contract consistency: schema/type generation + diff check.
- Behavior confidence: focused Docker-based tests for touched architecture areas.

## Assessment Status
Completed on 2026-02-14.

## Baseline Snapshot (Observed)

### Codebase Size
| Area | Files | Lines |
|---|---:|---:|
| `src/` | 125 | 19,894 |
| `frontend/src/` | 67 | 10,162 |
| `console-ui/src/` | 6 | 1,452 |
| `tests/` | 47 | 12,853 |
| `docs/` | 136 | 62,444 |

### Hotspot Files (Maintainability Risk)
| File | Lines |
|---|---:|
| `src/psychoanalyst_app/orchestration/orchestrator_helpers.py` | 1,188 |
| `src/psychoanalyst_app/agents/trio_reflection_agent.py` | 1,129 |
| `src/psychoanalyst_app/container/service_container.py` | 737 |
| `src/psychoanalyst_app/agents/trio_psychoanalyst_agent.py` | 631 |
| `src/psychoanalyst_app/agents/trio_assessment_agent.py` | 612 |

### Useful Existing Strengths
- WS protocol has a generated single source and CI consistency checks:
  - `schemas/ws_protocol.json`
  - `src/psychoanalyst_app/utils/ws_protocol.py`
  - `.github/workflows/type-safety.yml`
- The gateway -> orchestration -> agent -> service layering exists and is understandable.
- Trio-first concurrency model is consistent in key runtime paths.

## Findings (Evidence-Backed)

### F-001 (P0) Dependency and Artifact Weight Is Higher Than Needed for a Laptop-First Project
Evidence:
- Runtime dependency list includes heavy or likely-unused entries:
  - `pyproject.toml:18`
  - `pyproject.toml:19`
  - `pyproject.toml:24`
  - `pyproject.toml:25`
  - `pyproject.toml:26`
- No code usage found for `jwt`, `passlib`, `bcrypt`, `torchvision`, `torchaudio`, `chromadb` outside lock/config metadata.
- Stale mypy override remains:
  - `pyproject.toml:80`
- Package data references a path not present in source tree:
  - `pyproject.toml:49`
- Runtime DB artifacts are committed under source:
  - `src/psychoanalyst_app/data/vector_db/chroma.sqlite3`
  - `src/psychoanalyst_app/data/vector_db/b796e9c6-9d3d-4ed7-8c0a-48faefc87aa8/data_level0.bin`

Impact:
- Slower builds and heavier environments.
- Higher cognitive load due to stale dependencies/artifacts and unclear source-of-truth paths.

Recommendation:
1. Remove confirmed-unused deps and stale mypy overrides.
2. Remove committed runtime vector-db artifacts from `src/`.
3. Align package data paths with real packaged assets (or remove dead entry).

### F-002 (P0) Default Logging Behavior Is Expensive and Sensitive for Local Use
Evidence:
- App logging always creates file handlers:
  - `src/psychoanalyst_app/config.py:216`
  - `src/psychoanalyst_app/config.py:238`
- LLM service logs raw prompts/contexts/responses/chunks:
  - `src/psychoanalyst_app/services/llm_service.py:168`
  - `src/psychoanalyst_app/services/llm_service.py:173`
  - `src/psychoanalyst_app/services/llm_service.py:193`

Impact:
- Extra disk IO and log growth on small laptops.
- Increased risk of persisting sensitive conversation data by default.

Recommendation:
1. Make detailed LLM call logging opt-in (`LLM_CALL_LOGGING_ENABLED=false` by default).
2. Add redaction/sampling modes for prompts and responses.
3. Keep concise operational logs on by default; full payload logs only in explicit debug mode.

### F-003 (P1) Configuration Drift: Multiple Settings Are Unused or Not Wired
Evidence:
- Declared but not consumed effectively:
  - `src/psychoanalyst_app/config.py:148`
  - `src/psychoanalyst_app/config.py:149`
  - `src/psychoanalyst_app/config.py:152`
  - `src/psychoanalyst_app/config.py:153`
- DB executor factory ignores pool config and timeout settings:
  - `src/psychoanalyst_app/container/service_container.py:282`
- Connection row_factory is mutated but not restored:
  - `src/psychoanalyst_app/services/db/executor.py:58`
  - `src/psychoanalyst_app/services/db/executor.py:63`
  - `src/psychoanalyst_app/services/db/executor.py:66`

Impact:
- Misleading knobs reduce trust in configuration.
- Harder to reason about performance tuning and runtime behavior.

Recommendation:
1. Either wire these settings into runtime or remove them.
2. Restore original `row_factory` when returning pooled connections.
3. Add tests that prove config knobs change behavior.

### F-004 (P1) Hotspot Modules Are Too Large and Blend Responsibilities
Evidence:
- Very large modules:
  - `src/psychoanalyst_app/orchestration/orchestrator_helpers.py` (1,188 lines)
  - `src/psychoanalyst_app/agents/trio_reflection_agent.py` (1,129 lines)
  - `src/psychoanalyst_app/container/service_container.py` (737 lines)
- Agent path performing DB side effects while building prompt context:
  - `src/psychoanalyst_app/agents/trio_psychoanalyst_agent.py:448`
- TODO placeholders in core decision logic:
  - `src/psychoanalyst_app/agents/trio_assessment_agent.py:209`
  - `src/psychoanalyst_app/agents/trio_assessment_agent.py:211`
  - `src/psychoanalyst_app/agents/trio_psychoanalyst_agent.py:350`

Impact:
- Harder reviews, higher regression risk, slower onboarding.

Recommendation:
1. Split orchestrator helper responsibilities into focused modules:
   - session lifecycle
   - response transitions
   - persistence adapters
2. Keep agents closer to deterministic decision/prompt logic; shift side effects to orchestration/services.
3. Replace TODO placeholders with explicit implementations or explicit non-support behavior.

### F-005 (P1) API/State Update Logic Still Has Duplication Across Layers
Evidence:
- HTTP route merge logic duplicates profile merge behavior:
  - `src/psychoanalyst_app/api/user_routes.py:191`
  - `src/psychoanalyst_app/api/user_routes.py:250`
  - `src/psychoanalyst_app/orchestration/profile_helpers.py:24`
- Version service bypasses centralized API client:
  - `frontend/src/services/versionService.ts:38`
  - `frontend/src/services/versionService.ts:60`
- Frontend context still carries deprecated compatibility state/actions:
  - `frontend/src/contexts/AppContext.tsx:5`
  - `frontend/src/contexts/AppContext.tsx:44`

Impact:
- Multiple update paths increase drift risk and maintenance cost.

Recommendation:
1. Reuse `merge_user_profile`/shared normalization in user routes.
2. Move `versionService` to `apiClient`.
3. Finish removal of deprecated AppContext compatibility shims.

### F-006 (P1) Workflow Policy Is Ambiguous (Docker-Only vs Local-Opt-In)
Evidence:
- Makefile exposes a large local command surface:
  - `Makefile:44`
  - `Makefile:158`
  - `Makefile:281`
- Docs repeatedly advertise local command alternatives:
  - `docs/design-principles.md:108`
  - `docs/README.md:271`
  - `docs/README.md:521`

Impact:
- Mixed guidance increases onboarding friction and support burden.

Recommendation:
1. Decide one primary workflow (Docker-only or hybrid).
2. Keep one path as primary and label the other as explicitly unsupported/deprecated.
3. Update `Makefile`, `docs/README.md`, and `docs/design-principles.md` in one change-set.

### F-007 (P2) Documentation Surface Is Large Relative to Code and Contains Drift Risk
Evidence:
- Docs volume is high (`~62k` lines) vs source (`~20k` lines) and includes many archived/legacy files.
- Primary docs are long:
  - `docs/README.md` (720 lines)
  - `docs/design-principles.md` (710 lines)
  - `docs/ARCHITECTURE.md` (587 lines)

Impact:
- Contributors must sift through too much material to find canonical guidance.

Recommendation:
1. Promote a strict “active docs set” and keep others as archive-only.
2. Add freshness metadata and ownership on high-traffic docs.
3. Keep architecture docs concise and link deep dives instead of duplicating guidance.

## Prioritized Improvement Backlog

### P0 (Immediate)
1. Dependency/artifact slimming and package-data cleanup (F-001).
2. Logging default hardening for local/privacy-safe operation (F-002).

P0 implementation status (2026-02-14):
- Completed F-001:
  - Removed unused heavyweight/legacy dependencies from `pyproject.toml` and `requirements.in`.
  - Regenerated `requirements.txt` and `requirements-dev.txt`.
  - Removed committed runtime vector DB artifacts and added ignore coverage.
  - Removed stale package-data and mypy override entries.
- Completed F-002:
  - Added opt-in LLM payload logging (`LLM_CALL_LOGGING_ENABLED=false` by default).
  - Added redaction/truncation controls and chunk logging toggle.
  - Wired settings through container/service construction.
  - Added unit tests covering disabled logging default and redaction behavior.

### P1 (Next)
1. Wire/remove drifted config knobs; fix executor `row_factory` handling (F-003).
2. Refactor hotspot modules and remove TODO placeholders in core flows (F-004).
3. Eliminate duplicated profile/API paths and deprecated frontend shims (F-005).
4. Resolve Docker-only vs local policy drift across code and docs (F-006).

P1 implementation status (2026-02-14):
- Completed F-003:
  - Wired DB pool size/timeout settings from `Settings` into `TrioSQLiteExecutor`.
  - Added connection-acquire timeout handling and row-factory restoration in pooled connections.
  - Removed unused settings `MAX_CONCURRENT_SESSIONS` and `SESSION_TIMEOUT_MINUTES` from config and `.env.example`.
  - Added unit tests covering executor timeout/row-factory behavior and container wiring.
- Completed F-004 (incremental extraction + TODO cleanup):
  - Added shared profile persistence helper (`profile_persistence.py`) and reused it across orchestrator paths.
  - Replaced assessment TODO placeholders with deterministic rank-based scoring and key-topic extraction fallback logic.
  - Replaced psychoanalyst topic-detection TODO with explicit helper fallback behavior.
  - Added unit tests for assessment scoring/topic behavior.
- Completed F-005:
  - Reused `merge_user_profile` in `PUT/PATCH /api/user/profile` routes.
  - Updated merge semantics so explicit `null` clears optional fields while preserving required defaults.
  - Switched frontend `versionService` network calls to shared `apiClient`.
  - Removed deprecated `AppContext` `state/actions` compatibility shims.
- Completed F-006:
  - Updated `Makefile` so `local-*` targets are deprecation wrappers to Docker targets.
  - Updated `docs/README.md` and `docs/design-principles.md` to Docker-first workflow guidance.

### P2 (Later)
1. Documentation consolidation and active-doc governance (F-007).

P2 implementation status (2026-02-14):
- Completed F-007:
  - Added `docs/DOCS_GOVERNANCE.md` with active/supporting/archive policy and required metadata contract.
  - Consolidated `docs/README.md` into a canonical navigation index with explicit active-doc boundaries.
  - Added ownership/freshness/source metadata front matter to all active docs.
  - Added `scripts/validate_docs_metadata.py` and wired `make validate-docs`.
  - Added CI workflow `.github/workflows/docs-governance.yml` for metadata/index validation.

## Deliverables
1. This document updated with final findings and a prioritized improvement backlog.
2. A companion implementation plan in `docs/plans/` for approved P0/P1 items.
3. Validation log (tests/commands run and outcomes).

## Findings Log
| ID | Area | Evidence | Impact | Priority | Recommendation |
|---|---|---|---|---|---|
| F-001 | Dependencies + artifacts | `pyproject.toml:18`, `pyproject.toml:24`, `pyproject.toml:49`, `src/psychoanalyst_app/data/vector_db/chroma.sqlite3` | Higher runtime/build weight and confusion | P0 | Remove unused deps/artifacts, align package data |
| F-002 | Logging defaults | `src/psychoanalyst_app/config.py:216`, `src/psychoanalyst_app/services/llm_service.py:168` | Disk/privacy overhead on local machines | P0 | Make detailed logs opt-in + redact |
| F-003 | Config drift | `src/psychoanalyst_app/config.py:148`, `src/psychoanalyst_app/container/service_container.py:282` | Misleading tunables and harder ops tuning | P1 | Wire or remove unused settings |
| F-004 | Module boundaries | `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`, `src/psychoanalyst_app/agents/trio_assessment_agent.py:209` | Higher cognitive load, regression risk | P1 | Split modules + remove TODO placeholders |
| F-005 | API/state duplication | `src/psychoanalyst_app/api/user_routes.py:191`, `frontend/src/services/versionService.ts:38` | Drift risk across backend/frontend | P1 | Centralize merge and API client usage |
| F-006 | Workflow policy drift | `Makefile:44`, `docs/README.md:521` | Onboarding and support friction | P1 | Unify Docker/local policy and docs |
| F-007 | Docs sprawl | `docs/README.md`, `docs/design-principles.md`, `docs/ARCHITECTURE.md` | Discoverability and consistency risk | P2 | Curate active docs and archive boundaries |

## Validation Log
- Static inventory and hotspot scan:
  - `rg --files`, `wc -l`, `du -sh`
  - `rg -n "TODO|FIXME|XXX|HACK"`
- Dependency usage scan:
  - `rg -n "\\b(torchvision|torchaudio|jwt|passlib|bcrypt|chromadb)\\b"`
- Boundary and duplication review:
  - `sed -n`/`nl -ba` on orchestration, agents, API routes, frontend services/hooks
- CI/contract guardrail check (read-only):
  - `.github/workflows/type-safety.yml`
- Test execution:
  - `docker compose run --rm -v /home/fabian/Projects/llm_psychology/psychoanalyst_app:/app api uv run pytest tests/unit/test_llm_service.py -q`
  - `docker compose run --rm -v /home/fabian/Projects/llm_psychology/psychoanalyst_app:/app api uv run pytest tests/unit/test_llm_key_rotation.py tests/unit/test_llm_service.py -q`
  - `docker compose run --rm -v /home/fabian/Projects/llm_psychology/psychoanalyst_app:/app api uv run pytest tests/unit/test_llm_cache_service.py -q`
  - `make test-dev` -> `265 passed, 1 skipped, 1 deselected`
  - `docker compose run --rm -v /home/fabian/Projects/llm_psychology/psychoanalyst_app:/app api uv run pytest tests/unit/test_db_executor.py tests/unit/test_service_container.py tests/unit/test_profile_helpers.py tests/unit/test_user_routes.py tests/unit/test_trio_assessment_agent.py tests/unit/test_process_messages.py -q`
  - `docker compose run --rm -v /home/fabian/Projects/llm_psychology/psychoanalyst_app:/app frontend sh -lc 'cd frontend && npm run test -- src/services/__tests__/versionService.test.ts src/contexts/__tests__/AppContext.test.tsx --runInBand'`
  - `make test-dev` -> `272 passed, 1 skipped, 1 deselected`
  - `docker compose run --rm -v /home/fabian/Projects/llm_psychology/psychoanalyst_app:/app frontend sh -lc 'cd frontend && npm run type-check'` -> fails on pre-existing `MUI Grid size` typing errors in `frontend/src/components/Dashboard.tsx` and `frontend/src/pages/AssessmentPage.tsx` (unrelated to this change-set).
  - `make validate-docs` -> pass (`Documentation metadata validation passed. Validated active docs: 11`).

## Decision Log
- 2026-02-14: Created local-lean architecture assessment plan and pre-scan candidate improvement list.
- 2026-02-14: Completed in-depth local-lean architecture assessment and prioritized findings F-001..F-007.
- 2026-02-14: Adopted active-doc governance with YAML front matter metadata and automated validation.
