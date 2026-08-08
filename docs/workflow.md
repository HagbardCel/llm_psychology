---
owner: engineering
status: active
last_reviewed: 2026-08-08
review_cycle_days: 30
source_of_truth_for: Supported workflow, recovery, and command-conflict semantics
---

# Workflow Specification

> This document governs the supported Jung workflow runtime. Wire DTO shapes and
> public errors live in the [API v1 Contract](api-v1.md). Runtime synchronization
> structure lives in [Architecture](architecture.md). Database reset and data
> erasure live in [Safety and Data Handling](safety-and-data.md).

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
5. **Duplicate client message**: same ID never creates a second user message. `PENDING` and `COMPLETE` return the durable turn; a non-retryable `FAILED` turn raises its stored failure; a retryable `FAILED` turn may, after generation availability, structural eligibility, and revision checks, reset the **same** durable turn to `PENDING` and regenerate. See [API v1](api-v1.md) for the full precedence list.
6. **During active generation**: conflicting distinct `send_message` returns `busy`; same idempotent resubmit returns in-progress or stored completion.

A pending turn cannot resume token generation exactly after crash; startup converts stale pending turns to retryable `FAILED` while preserving the user message.

## Startup and shutdown recovery

At startup, before accepting mutations:

- stale `RUNNING` operations → `PENDING`, scheduled by supervisor;
- stale **pending** chat turns → retryable `FAILED`;
- completed operations/turns are not rerun.

On shutdown:

- stop accepting new commands;
- wait a bounded interval for accepted work;
- leave in-flight durable work recoverable;
- never mark an in-flight operation successful without validated completion.

A connected client is only an observer: supervisor-owned generation continues after disconnect and notifications fan out to all observers.

## Post-session grounding

Persist durable factual evidence only when the backend can objectively ground it. Model-generated interpretations may remain in session-scoped summaries, briefings, intervention descriptions, and treatment-plan recommendations, but must never be promoted to durable profile facts or model-controlled evidence status.

### Ownership

| Information | Owner |
|---|---|
| Session summary | Analysis call |
| Intervention / patient-turn sequence citations | Analysis call |
| Next-session narrative and continuity | Update call |
| Plan patch | Update call |
| Durable profile patch | Processor, composed from resolved citations + message IDs |

### Input validation

`PostSessionInput` rejects transcripts whose sequences are not unique and strictly increasing, whose message IDs are not unique, or whose turn content is empty after whitespace normalization, before any LLM call. Those defects never enter the structured-output correction loop.

### Non-conversational sessions

Transcripts that lack either a user turn or an assistant turn take a deterministic zero-call path:

- empty transcript
- user-only transcript
- assistant-only transcript

Each variant produces a speculation-free summary/briefing, empty intervention evidence, an empty profile patch, and an empty plan patch. User-only summaries do not embed patient message text; the source session history remains authoritative.

### Evidence layers

| Layer | Representation |
|---|---|
| Model output | Sequence-only citations (`intervention_citations`, `patient_turn_citations`) |
| Validator | Verifies turn identity, role, and chronology; one intervention per therapist turn |
| Resolver | Attaches full whitespace-normalized authoritative turn content + message IDs |
| Durable profile | `grounded_patient_turns` with source message ID, sequence, and full normalized content |
| LLM-facing profile context | Normalized turn content only (no internal message IDs); whole items or omit |
| Interpretive reasoning | Session analysis and briefing only |

**Normalized** means whitespace-collapsed (`" ".join(text.split())`), not byte-for-byte identical source text.

Provider models cite sequences only. The backend resolves complete authoritative turns. Model-selected substrings are never persisted.

Intervention status is derived as `delivered` or `response_cited` from whether a later user turn was cited. `response_cited` means a chronologically later user turn was selected — not that the turn semantically responded to the intervention. `intervention_description` remains a model-generated interpretation made auditable by its grounded citation.

Patient-turn citations select patient-authored turns whose complete wording should be retained as durable cross-session context; cite sparingly, especially safety-relevant clarifications or negations where partial wording could reverse meaning, and omit when nothing qualifies. Patient-turn citations are unique by patient sequence. Durable turns are unique by authoritative source message ID. Merge keeps existing entries stable and appends new source messages. LLM profile projection is an allowlist of `grounded_patient_turns` only; unknown keys are dropped at merge and never re-enter prompts.

The same patient turn may intentionally appear both as intervention `patient_content` and as a durable patient-turn selection. Context packing treats them as separate atoms under one shared budget.

Malformed stored `grounded_patient_turns` (including explicit `null`) fail fast as an internal application error during post-session merge or therapy context assembly. They are not LLM-correctable and are not silently omitted.

Accumulation of grounded turns across sessions is currently unbounded; retention policy is a deliberate follow-up.

### Failure behavior

After an unrecoverable validation, LLM, or derived-profile storage failure, the operation transitions to `FAILED`, but no session summary, briefing, derived-profile update, or plan revision is persisted.
