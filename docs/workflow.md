# Workflow Specification

> This document governs the supported Jung workflow runtime. Wire DTO shapes and
> public errors live in the [API v1 Contract](api-v1.md). Runtime synchronization
> structure lives in [Architecture](architecture.md). Database reset and data
> erasure live in [Safety and Data Handling](safety-and-data.md).

## Stages

Stage is a **derived workflow view** over durable profile, session, plan, and
operation rows. It is not independently mutable persistent state.

| Stage | Entry condition | Exit condition | Edit policy |
|---|---|---|---|
| `SETUP` | fresh database / incomplete profile | complete profile + open intake session → `INTAKE` | profile fields editable (may be incomplete) |
| `INTAKE` | open intake session | processor accepts complete intake → assessment operation / `ASSESSMENT` | profile fields editable, but profile must remain complete; intake chat accepted |
| `ASSESSMENT` | current assessment operation `PENDING` / `RUNNING` / `FAILED` | complete → `STYLE_SELECTION` | no profile/style/session/chat edits; failed assessment may retry |
| `STYLE_SELECTION` | completed assessment and no plans | valid style + initial plan → `READY` | only style selection |
| `READY` | current plan; no active session/operation | start session → `THERAPY` | profile is read-only; start session only |
| `THERAPY` | one active therapy session | end active session → post-session operation / `POST_SESSION` | therapy chat and end only |
| `POST_SESSION` | current post-session operation `PENDING` / `RUNNING` / `FAILED` | complete revision → `READY` | no user edits; failed post-session may retry |

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

All non-table combinations return `invalid_command`. Commands are serialized
server-side and evaluated against authoritative state at execution time; there
is no client revision token. Chat message idempotency is evaluated first.
Conflicting mutation, session, operation, or generation returns `busy`.

While chat generation holds the generation lock, snapshot assembly masks
`available_commands` to empty (asynchronous observers may see no commands), and
public workflow commands that check the lock return `busy`.

Sequential valid `update_profile` commands are last-writer-wins: each accepted
write replaces the stored profile. During `INTAKE`, profile fields remain
editable, but the profile must remain complete once `INTAKE` has begun; an
incomplete profile update returns `invalid_command`.

## Transition table

| Current stage | Command/event | Preconditions | Atomic persisted changes | Resulting stage |
|---|---|---|---|---|
| `SETUP` | `update_profile` completes profile | profile passes validation | profile saved + open intake session created | `INTAKE` |
| `INTAKE` | intake completion (processor) | intake record meets evidence policy | assessment `Operation` created `PENDING` | `ASSESSMENT` |
| `ASSESSMENT` | operation completes | structured assessment result valid; includes initial plan material | assessment result saved; operation `COMPLETE` | `STYLE_SELECTION` |
| `STYLE_SELECTION` | `select_style` | style valid; assessment result contains initial plan material | selected style + initial immutable plan | `READY` |
| `READY` | `start_session` | no active session/operation/generation | therapy session row | `THERAPY` |
| `THERAPY` | `end_session` | active session matches command | session ended; post-session `Operation` `PENDING` | `POST_SESSION` |
| `POST_SESSION` | operation completes | post-session patch valid | profile/plan revisions saved; operation `COMPLETE` | `READY` |

Failed operations and unanswered chat messages **never** advance stage. Operation
retry reuses the same durable operation row. Chat retry reuses the same
`(session_id, client_message_id)` user message.

## Operation lifecycle

```text
PENDING → RUNNING → COMPLETE
                  ↘ FAILED
```

1. **Creation transaction**: persist workflow mutation, create `PENDING` operation keyed by `(kind, source_session_id)`.
2. **Runtime scheduling**: best-effort after durable acceptance; a `PENDING` operation remains authoritative and recoverable if immediate task creation is unavailable.
3. **Start**: the application marks `RUNNING` outside the acceptance transaction.
4. **Completion transaction**: validate structured result; atomically persist result artifacts, mark `COMPLETE`, advance stage when applicable.
5. **Failure**: persist stable error code and retryability; leave stage unchanged.
6. **Retry**: eligible only for `llm_unavailable`, `llm_timeout`, or classified transient infrastructure failures; increments attempt on the same operation row; never duplicates plan/result rows.
7. **Idempotency**: `(kind, source_session_id)` is unique; duplicate acceptance returns the existing operation.

## Message-native chat

Durable chat truth is **messages only**. There is no `ChatTurn` / `chat_turns`
row. Each message has role `user` or `assistant`, a required
`client_message_id`, and uniqueness on `(session_id, client_message_id, role)`.
A completed exchange is a user message and an assistant message sharing the same
`client_message_id`.

Generation is request-owned: the HTTP `POST /api/v1/chat` stream that issues
the chat attempt drives `TherapyApplication.stream_message` until a terminal
result or disconnect. Tokens are ephemeral. Chat is not scheduled as the
application's owned operation task.

### Acceptance and streaming

1. **New message**: validate stage/session; reject if the open session already
   ends with an unanswered `USER`; acquire the generation lock; persist the user
   message; stream tokens; on success persist the assistant message and emit
   `message_completed`; on an ordinary post-acceptance failure before durable
   assistant completion emit `message_failed` (user message remains durable;
   stage unchanged).
2. **Idempotent complete**: same `(session_id, client_message_id)` already has
   user and assistant with matching content → yield `message_completed` with the
   durable pair (no regeneration).
3. **Content conflict**: same ID with different content → `invalid_command`.
4. **During active generation**: a distinct new chat attempt or conflicting
   workflow command returns `busy`.

### Unanswered user and retry

An **open** session may have at most one trailing unanswered `USER`. The client
must `/retry` (retransmit) the **same** `client_message_id` and content before
sending another chat message.

Retry is structurally eligible only when:

- the session is still open and is the active session;
- stage is `INTAKE` or `THERAPY` matching the session kind;
- that user message is still the latest message in the session.

Otherwise retry returns `invalid_command` (“not eligible for retry”).

Ending therapy (`/quit` / `end_session`) may leave a trailing `USER` on a
**closed** session. That message is not retryable and is not treated as an
unresolved diagnostic problem.

### Disconnect and crash

Disconnect cancels the request-owned generation attempt. The durable user
message may remain unanswered on an open session and must be retried with the
same ID. There is no pending-turn row to convert on startup.

## Startup and shutdown recovery

At startup, before accepting mutations:

- stale `RUNNING` operations → `PENDING`, then scheduled by the application;
- completed operations are not rerun;
- chat has no supervised recovery — unanswered open-session user messages remain
  for explicit client retry.

On shutdown:

- stop accepting new commands;
- wait a bounded interval for the **currently owned operation task**;
- leave any durable `PENDING`/in-flight operation recoverable for the next startup;
- never mark an in-flight operation successful without validated completion;
- in-flight chat is cancelled with its HTTP stream request.

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
