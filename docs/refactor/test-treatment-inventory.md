---
owner: engineering
status: accepted
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Refactor test treatment plan
---

# Test Treatment Inventory

Test retirement actions are recorded in the `Test action` column of [Deletion Inventory](deletion-inventory.md). Allowed values are `retain`, `port`, `rewrite_application`, `rewrite_api`, `delete_with_component`, and `delete_redundant`.

| Existing test area | Test action | Reason / target home |
|---|---|---|
| intake record merge, completeness, evidence provenance, turn persistence | retain | durable domain behavior; `phases/intake` and store tests |
| note-taker patch, planning analysis/extractors, reflection snapshots | port | pure helpers become phase tests |
| LLM structured output, phase metadata, prompts, fake LLM | retain | gateway/phase seam remains |
| profile merge and immutable plan/history linkage | rewrite_application | target commands and SQLite transactions own it; Phase 2 `SQLiteStore` covers profile/plan linkage |
| console workflow/probe tests | rewrite_api | console becomes the reference v1 client |
| characterization test semantics | rewrite_api | rewrite to `/api/v1` black-box coverage in Phase 5 |
| `tests/characterization/legacy_client.py` harness | delete_with_component | removed with legacy API at cutover |
| `test_service_container`, Trio server/DB/orchestrator/managers | delete_with_component | tests only legacy wiring |
| user routes/login/version negotiation/generated legacy WS protocol | delete_with_component | removed product contract |
| job tree, next action, workflow event/action routing | rewrite_application | snapshot and `Operation` replace representations |
| planning/memory/reflection agent wiring tests | delete_with_component | wiring-only tests removed with legacy orchestration |
| planning/memory/reflection durable behavior | port | phase helper and store tests own durable outcomes |
| duplicate low-level serialization and route mocks | delete_redundant | target contract/integration tests cover durable behavior |
