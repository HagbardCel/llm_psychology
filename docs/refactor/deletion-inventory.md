---
owner: engineering
status: supporting
last_reviewed: 2026-07-20
review_cycle_days: 30
source_of_truth_for: Phase 6 deletion manifest overview
---

# Deletion Inventory

> **Authoritative source:** [`deletion-manifest.toml`](deletion-manifest.toml). This page is a human overview only; do not duplicate item lists here.

Phase 5 exit evidence: `make validate-refactor-phase-5`. Phase 6C cutover completed `owner_pr = "6C"`. Phase 6D deleted the remaining legacy package, `console-ui/`, legacy probes, and orphaned tests, then marked the manifest `completed`. Phase 6 execution follows [architecture-refactor-roadmap.md § Phase 6](architecture-refactor-roadmap.md#phase-6--cutover-and-legacy-deletion). See also [phase-6c-implementation-plan.md](phase-6c-implementation-plan.md).

## Manifest lifecycle

| Validator stage | Required manifest `status` |
|-----------------|----------------------------|
| `cutover` | `active` |
| `final` | `completed` |

## Closure semantics

Phase 6 is finished when the manifest has `status = "completed"`, every Phase 6 item is `complete` with `confidence = confirmed`, all action semantics are satisfied, and no `discovery-needed` item remains. The historical manifest and this overview are retained for audit; they are not physically erased.

## Sunset

- **Phase 7:** remove remaining transitional Phase 2–6 validators and refactor plans once durable guidance is incorporated into canonical docs.

Phase 7 packaging, native tooling, Compose reduction, and dual-contract documentation cleanup are tracked in the roadmap, not in the Phase 6 manifest.

## Closure evidence

Manual local-model smoke is recorded here after the Phase 6D closure commit (not CI).

| Field | Value |
|---|---|
| Date | 2026-07-20 |
| Tested commit/tree | Phase 6D closed working tree on base `46c684d` (uncommitted closure) |
| Command | `make smoke-target-local-llm` with `PHASE3_SMOKE_SERVER=llama.cpp`, `PHASE3_SMOKE_BASE_URL=http://host.docker.internal:8080/v1`, `PHASE3_SMOKE_MODEL=ggml-org/Qwen3.6-35B-A3B-MTP-GGUF`, `PHASE3_SMOKE_STRUCTURED_MODE=json_schema`, `PHASE3_SMOKE_STRICT_ACCEPTANCE=1` |
| Model and server | `ggml-org/Qwen3.6-35B-A3B-MTP-GGUF` via llama.cpp OpenAI-compatible at `http://host.docker.internal:8080/v1` |
| Result | Passed — 3/3 (`therapy`, `assessment`, `post_session`); strict acceptance budgets met (~270s wall) |
