---
owner: engineering
status: active
last_reviewed: 2026-07-20
review_cycle_days: 90
source_of_truth_for: Supported frontend scope and API-only client policy
---

# UI Scope

## Supported Reference Frontend

`jung-console` is the supported reference frontend. It is used for manual
sessions, `/api/v1` contract integration, and deterministic workflow probes.

All clients interact with the backend exclusively through `/api/v1`; clients
must not import backend application, workflow, persistence, or domain internals.

## Development Priority

1. backend workflow and persistence correctness
2. LLM service reliability
3. `/api/v1` contract stability
4. `jung-console` and target API-contract compatibility
5. deterministic workflow-probe reliability
