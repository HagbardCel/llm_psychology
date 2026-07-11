---
owner: engineering
status: proposed
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Target workflow, recovery, and concurrency semantics
---

# Target Workflow Specification

> Target specification only. Legacy `WorkflowState`, jobs, and next actions remain current behavior until cutover.

## Stages

| Stage | Valid progression |
|---|---|
| `SETUP` | complete profile → `INTAKE` |
| `INTAKE` | accepted intake completion → `ASSESSMENT` |
| `ASSESSMENT` | completed operation → `STYLE_SELECTION` |
| `STYLE_SELECTION` | select style → `READY` |
| `READY` | start session → `THERAPY` |
| `THERAPY` | end session → `POST_SESSION` |
| `POST_SESSION` | completed operation → `READY` |

Failed operations do not advance stage. Stale `RUNNING` operations return to `PENDING` at startup. `ChatTurn` is not an operation: pending turns become retryable failures at startup because token generation cannot resume exactly.

## Concurrency

One application mutation lock protects revision-sensitive acceptance/completion transactions; LLM work runs outside it. One active generation, one active session, and one workflow operation are permitted. Conflicting mutations return `busy`.

Existing chat idempotency is evaluated before revision checks. New commands atomically validate their expected revision; later revisions do not invalidate an accepted command.

## Legacy mapping

Legacy user status/workflow state becomes `Stage`; assessment, plan-update, and reflection job hierarchy becomes `Operation`; generic `next_action`, state signatures, and `REFLECTION_IN_PROGRESS` are deleted. Client-visible recovery uses snapshot/history rather than token replay.
