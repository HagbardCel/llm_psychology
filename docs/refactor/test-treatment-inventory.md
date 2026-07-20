---
owner: engineering
status: accepted
last_reviewed: 2026-07-20
review_cycle_days: 30
source_of_truth_for: Refactor test treatment plan and Phase 6D allowlist decisions
---

# Test Treatment Inventory

Test retirement actions are recorded in the Phase 6 [deletion manifest](deletion-manifest.toml) (`action` and `evidence` fields). See [deletion-inventory.md](deletion-inventory.md) for the overview.

## Historical treatment summary

| Existing test area | Test action | Reason / target home |
|---|---|---|
| intake merge durable behavior | port | Jung-native merge in `tests/unit/jung/phases/intake/test_merge.py` |
| Jung intake merge coverage (`test_merge.py`) | retain | preserves ported merge behavior |
| legacy intake merge test file (`test_intake_record_merge.py`) | delete after port | superseded by Jung-native merge test |
| planning analysis durable behavior | delete (intentionally superseded) | heuristic `assess_update_necessity` / recommendation helpers are not target invariants; Jung derives plan revision from `PlanPatch` / `plan_patch_is_noop` |
| legacy planning analysis test file | delete | no Jung port; see Phase 6D classification below |
| note-taker patch, reflection snapshots | port | pure helpers become phase tests |
| LLM structured output, phase metadata, prompts, fake LLM | retain | gateway/phase seam remains (`test_recording_fake_llm.py`) |
| profile merge and immutable plan/history linkage | rewrite_application | target commands and SQLite transactions own it |
| console workflow/probe tests | rewrite_api | `jung-console` + `tests/e2e/test_console_v1_workflow.py` |
| characterization harness | delete_with_component | aggregate `tests/characterization/` removed in 6D |
| Trio/agent/orchestration/user-route tests | delete_with_component | attic outside supported surface; removed in 6D |

## Phase 6D — planning-analysis classification

Legacy file: `tests/unit/test_planning_analysis.py` (four assertions).

| Assertion | Classification |
|---|---|
| Short session without material signal → `assess_update_necessity` is False | Intentionally superseded (heuristic gate not in target) |
| Short session with risk indicator → True | Intentionally superseded |
| Theme recommendations suppress normalized duplicates | Intentionally superseded (deleted planning helper) |
| Goal progression suppressed on declining trend | Intentionally superseded |

**Manifest outcome:** `action = "delete"` (no replacements). Existing Jung coverage of empty/material `PlanPatch` no-op semantics in post-session processor tests is sufficient; no new Jung test required.

## Phase 6D — probe assertion audit

Legacy probes (generic / deterministic / intake-note) vs target coverage:

| Legacy concern | Classification |
|---|---|
| Intake patch generation and completion | Represented — Jung intake tests + v1 E2E |
| Assessment, style selection, therapy, post-session | Represented — v1 E2E + phase/application tests |
| Persisted profile, plan, sessions, transcripts, operations | Represented — v1 E2E store/API assertions |
| Plan revision after therapy | Represented — v1 E2E plan version linkage |
| Intake-note probe diagnostics / `logs/workflow-probes` DB dumps | Intentionally retired |

**Outcome:** no new target-native persistence assertion required. Delete all legacy probe overlays/scripts/Make targets; retain `probe-console-v1-deterministic` and `smoke-target-local-llm`.

## Phase 6D — supported test allowlist (decision record)

Implemented in the Phase 6 validator during WP5. Do not expand without execution/import evidence.

### Roots (collected by canonical gates)

| Root | Execution evidence |
|---|---|
| `tests/unit/jung/` | `make test-target`, `make test-unit` |
| `tests/integration/jung/` | `make test-target`, `make test-integration` |
| `tests/smoke/jung/` | `make smoke-target-local-llm` / phase-3 local-LLM smoke |

### Individually allowlisted files

| File | Evidence |
|---|---|
| `tests/conftest.py` | Collected as pytest root conftest for supported suites |
| `tests/e2e/test_console_v1_workflow.py` | `make probe-console-v1-deterministic` / finalization-check |
| `tests/e2e/conftest.py` | Support for e2e suite (imports `jung_api_fixtures`) |
| `tests/jung_api_fixtures.py` | Imported by e2e, integration Jung API/client tests, `test_recording_fake_llm.py` |
| `tests/console_probe_support.py` | Imported by e2e probe and `tests/unit/jung/client/test_console_probe_support.py` |
| `tests/unit/test_validate_refactor_phase_5.py` | `TARGET_SUPPORT_TESTS` via `make test-target` |
| `tests/unit/test_validate_refactor_phase_6.py` | `TARGET_SUPPORT_TESTS` via `make test-target` |
| `tests/unit/test_validate_docs_metadata.py` | `TARGET_SUPPORT_TESTS` via `make test-target` |
| `tests/unit/test_recording_fake_llm.py` | `TARGET_SUPPORT_TESTS` via `make test-target` |
| `tests/unit/test_measure_codebase.py` | `TARGET_SUPPORT_TESTS` via `make test-target` |
| `tests/__init__.py` | Package marker for `tests` imports |
| `tests/integration/__init__.py` | Package marker (if retained after attic deletion) |

## Phase 6D — attic deletion (filesystem inventory)

All Python under `tests/` outside the allowlist is deleted in WP4 (forbidden-import files and non-importing dead attic alike). Aggregate trees:

- `tests/characterization/`
- `tests/real_llm/` (legacy patient-flow only; Jung smoke is `tests/smoke/jung/`)

Individual legacy unit/integration/entry-point tests importing `psychoanalyst_app` / Trio / LangChain are deleted with the package excision. Non-Python fixtures under deleted trees are removed with those trees.
