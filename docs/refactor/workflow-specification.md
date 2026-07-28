---
owner: engineering
status: active
last_reviewed: 2026-07-21
review_cycle_days: 30
source_of_truth_for: Supported workflow, recovery, and concurrency semantics
---

# Workflow Specification

> This document governs the supported Jung workflow runtime. Wire DTO shapes live in the [API v1 Contract](api-v1-contract.md).

## Stages

| Stage | Entry condition | Exit condition | Edit policy |
|---|---|---|---|
| `SETUP` | fresh database | complete profile → `INTAKE` | profile fields editable |
| `INTAKE` | complete profile | processor accepts complete intake → assessment operation / `ASSESSMENT` | profile editable; intake chat accepted |
| `ASSESSMENT` | assessment operation pending/running | complete → `STYLE_SELECTION` | no profile/style/session/chat edits |
| `STYLE_SELECTION` | recommendations and assessment result durable | valid style + initial plan → `READY` | only style selection |
| `READY` | no active session/operation | start session → `THERAPY` | profile is read-only; start session only |
| `THERAPY` | one active session | end active session → post-session operation / `POST_SESSION` | therapy chat and end only |
| `POST_SESSION` | operation pending/running | complete revision → `READY` | no user edits |

Intake is complete only when the durable record meets the processor's required slot/evidence policy. Intake completion is an internal application transition caused by an accepted intake chat result, not a client command.

## Command matrix

| Stage | `update_profile` | `send_message` | `select_style` | `start_session` | `end_session` | `retry_operation` |
|---|---|---|---|---|---|---|
| `SETUP` | yes | no | no | no | no | no |
| `INTAKE` | yes | yes | no | no | no | no |
| `ASSESSMENT` | no | no | no | no | no | failed assessment only |
| `STYLE_SELECTION` | no | no | yes | no | no | no |
| `READY` | no | no | no | yes | no | no |
| `THERAPY` | no | yes | no | no | active session only | no |
| `POST_SESSION` | no | no | no | no | no | failed post-session only |

All non-table combinations return `invalid_command`. Commands atomically compare `expected_revision`; stale values return `state_conflict` with a snapshot. Chat idempotency is evaluated first. Conflicting mutation, session, operation, or generation returns `busy`.

## Transition table

| Current stage | Command/event | Preconditions | Atomic persisted changes | Resulting stage |
|---|---|---|---|---|
| `SETUP` | `update_profile` completes profile | profile passes validation | profile saved; revision incremented | `INTAKE` |
| `INTAKE` | intake completion (processor) | intake record meets evidence policy | assessment `Operation` created `PENDING`; revision incremented | `ASSESSMENT` |
| `ASSESSMENT` | operation completes | structured assessment result valid; includes initial plan material | assessment result saved; operation `COMPLETE`; revision incremented | `STYLE_SELECTION` |
| `STYLE_SELECTION` | `select_style` | style valid; assessment result contains initial plan material | selected style + initial immutable plan; revision incremented | `READY` |
| `READY` | `start_session` | no active session/operation/generation | therapy session row; revision incremented | `THERAPY` |
| `THERAPY` | `end_session` | active session matches command | session ended; post-session `Operation` `PENDING`; revision incremented | `POST_SESSION` |
| `POST_SESSION` | operation completes | post-session patch valid | profile/plan revisions saved; operation `COMPLETE`; revision incremented | `READY` |

Failed operations and failed chat turns **never** advance stage. Retry reuses the same durable record.

## Operation lifecycle

```text
PENDING → RUNNING → COMPLETE
                  ↘ FAILED
```

1. **Creation transaction**: persist workflow mutation, create `PENDING` operation keyed by `(kind, source_session_id)`, increment revision.
2. **Start**: supervisor marks `RUNNING` outside the acceptance transaction.
3. **Completion transaction**: validate structured result; atomically persist result artifacts, mark `COMPLETE`, advance stage when applicable, increment revision.
4. **Failure**: persist stable error code and retryability; leave stage unchanged.
5. **Retry**: eligible only for `llm_unavailable`, `llm_timeout`, or classified transient infrastructure failures; increments attempt on the same operation row; never duplicates plan/result rows.
6. **Idempotency**: `(kind, source_session_id)` is unique; duplicate acceptance returns the existing operation.

## ChatTurn lifecycle

```text
PENDING → COMPLETE
        ↘ FAILED
```

1. **Acceptance transaction**: validate stage/session/revision; resolve `(session_id, client_message_id)`; persist user message + `PENDING` turn; increment revision; schedule generation.
2. **Generation**: supervisor streams tokens through `EventStream`; tokens are ephemeral.
3. **Completion transaction**: persist assistant message; mark turn `COMPLETE`; increment revision; emit completion notifications.
4. **Failure**: mark turn `FAILED` with retryability; user message remains durable; stage unchanged; increment revision when failure occurs after acceptance.
5. **Duplicate client message**: same ID never creates a second user message; pending/complete/failed paths return the stored outcome.
6. **During active generation**: conflicting distinct `send_message` returns `busy`; same idempotent resubmit returns in-progress or stored completion.

A pending turn cannot resume token generation exactly after crash; startup converts stale pending turns to retryable `FAILED` while preserving the user message.

## Startup and shutdown recovery

At startup, before accepting mutations:

- stale `RUNNING` operations → `PENDING`, scheduled by supervisor;
- stale pending/running chat turns → retryable `FAILED`;
- completed operations/turns are not rerun.

On shutdown:

- stop accepting new commands;
- wait a bounded interval for accepted work;
- leave in-flight durable work recoverable;
- never mark an in-flight operation successful without validated completion.

A connected client is only an observer: supervisor-owned generation continues after disconnect and notifications fan out to all observers.
