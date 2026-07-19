---
owner: engineering
status: active
last_reviewed: 2026-07-16
review_cycle_days: 30
source_of_truth_for: Phase 6 deletion manifest overview
---

# Deletion Inventory

> **Authoritative source:** [`deletion-manifest.toml`](deletion-manifest.toml). This page is a human overview only; do not duplicate item lists here.

Phase 5 exit evidence: `make validate-refactor-phase-5`. Phase 6 execution follows [architecture-refactor-roadmap.md § Phase 6](architecture-refactor-roadmap.md#phase-6--cutover-and-legacy-deletion).

## Manifest lifecycle

| Validator stage | Required manifest `status` |
|-----------------|----------------------------|
| `pre-cutover` | `active` |
| `cutover` | `active` |
| `final` | `completed` |

## Closure semantics

Phase 6 is finished when the manifest has `status = "completed"`, every Phase 6 item is `complete` with `confidence = confirmed`, all action semantics are satisfied, and no `discovery-needed` item remains. The historical manifest and this overview are retained for audit; they are not physically erased.

## Sunset

- **Final Phase 6 cleanup:** delete `scripts/validate_refactor_phase_1.py` and `tests/unit/test_validate_refactor_phase_1.py`, then mark the manifest completed.
- **Phase 7:** remove remaining transitional Phase 2–6 validators and refactor plans once durable guidance is incorporated into canonical docs.

Phase 7 packaging, native tooling, Compose reduction, and dual-contract documentation cleanup are tracked in the roadmap, not in the Phase 6 manifest.
