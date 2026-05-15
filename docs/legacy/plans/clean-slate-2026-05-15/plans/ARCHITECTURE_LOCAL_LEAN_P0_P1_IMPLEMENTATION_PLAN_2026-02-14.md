# Architecture Local-Lean P0/P1 Implementation Plan (2026-02-14)

## Purpose
Companion implementation/closure plan for:
- `docs/assessments/architecture/ARCHITECTURE_ASSESSMENT_PLAN_2026-02-14_LOCAL_LEAN.md`

This plan is executed as a **gap-only closure** for approved P0/P1 findings (F-001..F-006), validating that prior implementation remains compliant and defining exact remediation defaults if drift appears.

## Scope
- P0:
  - F-001 Dependency/artifact slimming and package-data cleanup.
  - F-002 Logging-default hardening for local/privacy-safe operation.
- P1:
  - F-003 Config drift cleanup and DB executor correctness.
  - F-004 Hotspot first-pass decomposition and TODO removal.
  - F-005 API/state duplication cleanup across backend/frontend.
  - F-006 Docker-first workflow alignment.

## Constraints
1. Docker-first command execution only.
2. No HTTP/WS contract shape changes unless explicitly documented and regenerated.
3. Keep behavior deterministic and test-backed.
4. Do not revert unrelated user working-tree changes.

## Verification Matrix
| Finding | Required State | Source of Truth | Verification Commands | Pass Condition | Drift Remediation Default |
|---|---|---|---|---|---|
| F-001 | Removed unused heavy deps; runtime vector DB artifacts not tracked in source; stale package-data/mypy entries cleaned | `pyproject.toml`, `requirements*.in/txt`, `.gitignore` | `rg -n "torchvision|torchaudio|PyJWT|passlib|bcrypt|chromadb|jwt" ...`, `ls -la src/psychoanalyst_app/data/vector_db || true`, `rg -n "vector_db|chroma.sqlite3|data_level0.bin" .gitignore`, `rg -n "\[tool.setuptools.package-data\]|\[\[tool.mypy.overrides\]\]|chromadb" pyproject.toml` | No removed deps found; vector-db source path absent; ignore rules present; stale override not present | Remove drifted deps/config, refresh lockfiles in Docker, restore ignore coverage |
| F-002 | LLM payload logging is opt-in with redact/truncate/chunk controls wired to service construction | `src/psychoanalyst_app/config.py`, `src/psychoanalyst_app/container/factories/llm.py`, `src/psychoanalyst_app/services/llm_service.py` | `rg -n "LLM_CALL_LOGGING_..." ...` and `rg -n "llm_call_logging_..." ...` | Flags exist; defaults are local-safe; wiring into `LLMService` is present | Re-introduce flags and wire-through in factory + tests |
| F-003 | Unused session knobs removed; executor row_factory restoration retained; timeout/pool behavior remains wired | `src/psychoanalyst_app/config.py`, `.env.example`, `src/psychoanalyst_app/services/db/executor.py`, `src/psychoanalyst_app/container/service_container.py` | `rg -n "MAX_CONCURRENT_SESSIONS|SESSION_TIMEOUT_MINUTES" ...`, `rg -n "row_factory|connection_timeout_seconds|max_pool_size" ...` | Removed knobs absent; row_factory restored after connection context; pool/timeout hooks present | Rewire settings and restore executor semantics with unit coverage |
| F-004 | First-pass hotspot decomposition intact; no TODO/FIXME placeholders in core code paths | `src/psychoanalyst_app/orchestration/helpers/*`, `src/psychoanalyst_app/agents/reflection/*`, whole repo scan | `rg -n "TODO|FIXME|XXX|HACK" src frontend/src console-ui/src tests ...` | No markers found in scanned paths | Replace placeholders with explicit deterministic behavior |
| F-005 | User routes use shared profile merge; frontend version service uses shared api client path | `src/psychoanalyst_app/api/user_routes.py`, `frontend/src/services/versionService.ts`, `frontend/src/contexts/AppContext.tsx` | `rg -n "merge_user_profile|parse_date_of_birth" ...`, `rg -n "apiClient|fetch\(" ...`, targeted AppContext inspect | Shared merge helper present; version service uses `apiClient`; no deprecated compatibility shim surface | Refactor back to centralized helpers/client + tests |
| F-006 | Makefile local targets are deprecation wrappers to Docker; docs emphasize Docker-first workflow | `Makefile`, `docs/README.md`, `docs/design-principles.md` | `rg -n "local-" Makefile`, `rg -n "Docker-first|Docker-only|local-" docs/...` | `local-*` targets are wrappers; Docker-first guidance present | Normalize Makefile wrappers and docs wording |

## Execution Order
1. Preflight working-tree snapshot.
2. Run F-001..F-006 verification commands.
3. If drift found: remediate only affected finding(s), then re-run finding checks.
4. Run governance validations:
   - `make validate-architecture`
   - `make validate-docs`
5. Record closure status and residual risks.

## Execution Evidence (2026-02-14)

### Preflight
- `git status --short` showed unrelated existing changes in docs/tests; no reversions performed.

### F-001
- `rg -n "torchvision|torchaudio|PyJWT|passlib|bcrypt|chromadb|jwt" pyproject.toml requirements.in requirements-dev.in requirements.txt requirements-dev.txt || true`
  - Result: no matches.
- `ls -la src/psychoanalyst_app/data/vector_db || true`
  - Result: path absent (`No such file or directory`).
- `rg -n "vector_db|chroma.sqlite3|data_level0.bin" .gitignore || true`
  - Result: ignore coverage present for vector DB paths.
- `rg -n "\[tool.setuptools.package-data\]|\[\[tool.mypy.overrides\]\]|chromadb" pyproject.toml`
  - Result: package-data and mypy override blocks present; no stale `chromadb` override entry.

Status: PASS.

### F-002
- `rg -n "LLM_CALL_LOGGING_ENABLED|LLM_CALL_LOGGING_REDACT|LLM_CALL_LOGGING_MAX_FIELD_CHARS|LLM_CALL_LOGGING_INCLUDE_CHUNKS" src/psychoanalyst_app/config.py src/psychoanalyst_app/container/factories/llm.py src/psychoanalyst_app/services/llm_service.py`
  - Result: all logging controls present in config and factory wiring.

Status: PASS.

### F-003
- `rg -n "MAX_CONCURRENT_SESSIONS|SESSION_TIMEOUT_MINUTES" src/psychoanalyst_app/config.py .env.example || true`
  - Result: no matches.
- `rg -n "row_factory|connection_timeout_seconds|max_pool_size" src/psychoanalyst_app/services/db/executor.py src/psychoanalyst_app/container/service_container.py`
  - Result: row_factory restoration logic present in executor.

Status: PASS.

### F-004
- `rg -n "TODO|FIXME|XXX|HACK" src frontend/src console-ui/src tests -g '!**/coverage/**' -g '!**/node_modules/**' || true`
  - Result: no matches.

Status: PASS.

### F-005
- `rg -n "merge_user_profile|parse_date_of_birth" src/psychoanalyst_app/api/user_routes.py`
  - Result: `merge_user_profile` usage present in PUT/PATCH handling.
- `rg -n "apiClient|fetch\(" frontend/src/services/versionService.ts`
  - Result: shared `apiClient` usage present; no direct `fetch(` usage.
- Targeted inspect: `frontend/src/contexts/AppContext.tsx`
  - Result: UI-only context surface; no deprecated compatibility `state/actions` shim API.

Status: PASS.

### F-006
- `rg -n "local-" Makefile`
  - Result: local targets present as explicit deprecation wrappers to Docker targets.
- `rg -n "Docker-first|Docker-only|local-" docs/README.md docs/design-principles.md || true`
  - Result: Docker-only guidance present (`docs/design-principles.md`).

Status: PASS.

### Governance Validation
- `make validate-architecture`
  - Result: PASS (`Architecture checks passed. Validated budgets: 10; method budgets: 7`).
- `make validate-docs`
  - Result: PASS (`Documentation metadata validation passed. Validated active docs: 11`).

## Pass/Fail Summary
- F-001: PASS
- F-002: PASS
- F-003: PASS
- F-004: PASS
- F-005: PASS
- F-006: PASS

## Residual Risks
1. Assessment evidence links to historical point-in-time values; future drift can occur without periodic re-run.
2. Unrelated working-tree changes were intentionally left untouched and may affect future validation context.

## Completion Record
- Status: **Completed**
- Completion date: **2026-02-14**
- Outcome: P0/P1 compliance for this assessment is verified as currently satisfied; no additional remediation required in this run.

## Out of Scope
- P2+ work (docs governance follow-up and deeper decomposition/hardening) remains tracked in:
  - `docs/assessments/architecture/ARCHITECTURE_ASSESSMENT_PLAN_2026-02-14_LOCAL_LEAN.md`
