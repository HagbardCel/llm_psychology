---
owner: engineering
status: active
last_reviewed: 2026-07-16
review_cycle_days: 30
source_of_truth_for: Planned legacy deletion inventory
---

# Deletion Inventory

> Phase 6 cutover inventory. Everything under a filesystem deletion root is deleted unless listed in **Exceptions**. Make targets and CI workflows are removed in the PRs noted below.

Phase 5 exit evidence: `make validate-refactor-phase-5`. Phase 6 execution follows [architecture-refactor-roadmap.md § Phase 6](architecture-refactor-roadmap.md#phase-6--cutover-and-legacy-deletion).

Allowed **Treatment** values: `reimplement_minimal`, `port_then_delete`, `retain_outside_root`, `retain_test`.

Allowed **Status** values: `planned`, `in_progress`, `complete`.

For `retain_outside_root`, the **Path** column is the original legacy item; **Evidence** names the destination and test coverage.

## Closure semantics

`status: completed` in frontmatter means Phase 6 deletion is finished: no planned or in-progress exceptions remain, no deletion root is still present, no legacy Make target remains, and no deletable workflow file remains. The historical audit list itself is **not** physically erased.

## Filesystem deletion roots

- `src/psychoanalyst_app/`
- `console-ui/`
- `schemas/ws_protocol.json`
- `docker-compose.probe-deterministic.yml`
- `docker-compose.probe-intake-notes.yml`
- `scripts/probe_deterministic.sh`
- `scripts/probe_intake_notes.sh`
- `scripts/generate_ws_protocol.py`
- `scripts/check_architecture_budgets.py`
- `scripts/validate_schemas.py`

### Notes

`scripts/validate_schemas.py` is deleted only if it solely serves legacy schema generation.

## Legacy Make targets

- `characterization-smoke`
- `characterization-full`
- `characterization-test`
- `probe-console-deterministic`
- `probe-console-intake-notes`
- `generate-schemas`
- `validate-schemas`
- `generate-ws-protocol`
- `validate-generated-contracts`
- `validate-architecture`
- `finalization-check-full`
- `test-real-llm`
- `test-validate-no-mocks`
- `reset-usertest`
- `reset-foundation-db`

### Notes

- `test-real-llm` is replaced by `smoke-target-local-llm` in 6B.
- `test-validate-no-mocks` is retired or retargeted in 6B.
- `reset-usertest` is replaced by `reset-manual-test` in 6B.
- `reset-foundation-db` is replaced by `reset-jung-db` in 6B.

## Legacy CI workflows

- `.github/workflows/architecture-governance.yml`
- `.github/workflows/type-safety.yml`

## Legacy CI workflow edits

- `.github/workflows/release-candidate-validation.yml`

### Notes

In 6C: remove `phase-1-evidence` job; retain `finalization-check`.

## Exceptions

| Path | Treatment | Owner PR | Status | Evidence |
|---|---|---|---|---|
| `src/psychoanalyst_app/tools/db_backup.py` | reimplement_minimal | 6B | planned | `src/jung/tools/db_backup.py`; `tests/unit/jung/tools/test_db_backup.py` |
| `src/psychoanalyst_app/agents/intake/record_merge.py` | port_then_delete | 6D | planned | `src/jung/phases/intake/`; intake processor tests if gap found |
| `src/psychoanalyst_app/agents/planning/analysis.py` | port_then_delete | 6D | planned | `src/jung/phases/`; audit before deletion |
| `tests/unit/test_intake_record_merge.py` | retain_test | 6D | planned | target intake tests or delete as redundant |
| `tests/unit/test_planning_analysis.py` | retain_test | 6D | planned | target phase tests or delete as redundant |
| `tests/unit/test_measure_codebase.py` | retain_test | 6A | complete | `scripts/measure_codebase.py`; included in `test-target` |
| `tests/unit/test_validate_refactor_phase_1.py` | retain_test | 6A | complete | `scripts/validate_refactor_phase_1.py`; Phase 1 gate only |
| `tests/unit/test_validate_refactor_phase_5.py` | retain_test | 6A | complete | `test-target` support |
| `tests/unit/test_recording_fake_llm.py` | retain_test | 6A | complete | `test-target` support |
| `tests/e2e/test_console_v1_workflow.py` | retain_test | 6A | complete | `probe-console-v1-deterministic` |
