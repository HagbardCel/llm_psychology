# Database

> Exact executable DDL lives in
> [`src/jung/persistence/schema.sql`](../src/jung/persistence/schema.sql).
> This document explains the relational model and invariants without copying the
> SQL. Schema initialization and version checks live in
> [`_sqlite_support.py`](../src/jung/persistence/_sqlite_support.py) and
> [`SQLiteStore.initialize`](../src/jung/persistence/sqlite_store.py).
> Manual database reset is documented in
> [Safety and Data Handling](safety-and-data.md).

## Relational model

```text
profile ──current_plan_id────► plans
                               │ ▲
                               │ └──supersedes_plan_id
                               │
sessions ──plan_id────────────►│
   ▲                           │
   └──── plans.source_session_id
   │
   ├── messages ◄── grounded_patient_turns.message_id
   └── operations
```

Durable ownership:

- `messages` own exact patient/therapist wording;
- `sessions.review_json` owns the complete supervisor record for a completed therapy session;
- `plans` own applied treatment state only;
- `grounded_patient_turns` own only selected message-ID references;
- `profile` owns editable user fields and the current plan pointer.

There is no `chat_turns` table. `client_message_id` is stored on every message.
A completed exchange is a `user` row and an `assistant` row sharing
`(session_id, client_message_id)`.

## Table overview

| Table | Purpose | Key relationships | Important constraints |
|---|---|---|---|
| `profile` | Singleton user-editable profile and current plan pointer | `current_plan_id` → `plans` | `singleton_id = 1` |
| `sessions` | Intake and therapy sessions; completed therapy may store `review_json` | `plan_id` → `plans` | at most one open session globally; intake must have null `plan_id`; therapy must have non-null `plan_id`; therapy sessions must not carry intake JSON; `review_json` only on ended therapy sessions |
| `plans` | Immutable plan revisions (treatment state only) | `source_session_id` → `sessions`; `supersedes_plan_id` → `plans` | unique `version`; unique `source_session_id`; at most one successor per superseded plan |
| `messages` | Durable transcript | `session_id` → `sessions` | unique `(session_id, sequence)`; roles `user`/`assistant`; required `client_message_id`; unique `(session_id, client_message_id, role)` |
| `grounded_patient_turns` | Selected patient-message references for cross-session memory | `message_id` → `messages` | primary key is the message ID; no copied text |
| `operations` | Assessment and post-session background work | `source_session_id` → `sessions` | unique `(kind, source_session_id)`; at most one current pending/running/failed operation globally |

## DDL-enforced invariants

These guarantees are encoded in SQL (including partial unique indexes that use
constant expressions and are therefore **database-global**):

- `profile` is a singleton (`singleton_id = 1`);
- at most one open session globally (`ended_at IS NULL`);
- intake sessions must have null `plan_id`; therapy sessions must have non-null `plan_id`;
- `review_json` is null or the session is ended therapy;
- unique message sequence within a session;
- message roles are `user` or `assistant` only;
- message acceptance is idempotent by `(session_id, client_message_id, role)`;
- plan versions are unique and ≥ 1; non-empty `focus` and `current_progress`;
- one source session creates at most one plan revision (`source_session_id` unique);
- a non-null `supersedes_plan_id` may be referenced by at most one successor plan;
- grounded patient turns reference existing messages;
- operations are idempotent by `(kind, source_session_id)`;
- at most one operation whose status is `pending`, `running`, or `failed` globally;
- operation status fields are coupled to `result_json` / error columns via CHECK constraints;
- session kinds are `intake` or `therapy`; therapy rows must not store intake JSON.

## Store/application persistence invariants

These relationships and policies are maintained by `SQLiteStore` and the
application rather than claimed as pure SQL guarantees:

- plan revisions are immutable as a programming model (new revision rows, never in-place mutation of plan content);
- workflow `Stage` is **derived** from durable profile, session, plan, and operation state (not persisted); impossible present-state combinations raise `InvariantViolation`;
- `POST_SESSION` derivation requires `source_session.plan_id == profile.current_plan_id`; post-session completion therefore extends that validated current/source plan;
- valid command acceptance is application/workflow policy over derived `WorkflowFacts`;
- an open session may have at most one trailing unanswered `USER`; a new user message is rejected until that ID is retried (see [workflow.md](workflow.md));
- assistant persistence requires an unanswered latest user message in the same session with the matching `client_message_id`;
- multi-table use cases such as assessment completion and post-session completion commit atomically in store methods;
- post-session completion resolves `review.analysis.patient_turn_citations` against source-session messages (unique cited sequences; role `user`), inserts their message IDs into `grounded_patient_turns`, writes `review_json`, optionally creates a plan revision, and completes the operation in one transaction;
- grounded message listing order is `sessions.started_at ASC`, `sessions.id ASC`, `messages.sequence ASC`; the `grounded_patient_turns` table may grow without a retention cap — prompt projection, not deletion, bounds LLM context;
- `SQLiteStore` owns SQL transaction boundaries (`BEGIN IMMEDIATE`) and commit/rollback; it does not own optimistic concurrency checks or snapshot-revision increments;
- `TherapyApplication` serializes mutations and validates commands against authoritative state before calling the store;
- missing singleton `profile` is corruption, not a legitimate `SETUP` state.

## JSON-owned documents

JSON TEXT columns hold validated documents owned by specific subsystems:

| Column | Owner |
|---|---|
| `sessions.review_json` | Typed `SessionReview` from post-session (analysis, briefing, plan recommendation, backend-authored generation metadata) |
| `sessions.intake_record_json` | Intake processor |
| `plans.themes_json`, `goals_json`, `planned_interventions_json`, `revision_recommendations_json` | Plan revision material |
| `operations.result_json` | Assessment: structured assessment result. Post-session: compact completion metadata (`plan_id`, `plan_version`); review and grounding live in their relational owners |

## Connection and transaction policy

- Each synchronous store operation opens and closes its own SQLite connection.
- Connections enable WAL, `foreign_keys=ON`, and a 5-second busy timeout.
- Writes use `BEGIN IMMEDIATE`.
- Async application code calls whole store operations via `asyncio.to_thread()`; no connection is shared across threads.
- The API/application process is the sole product-level SQLite writer; clients never write the database directly.

## Initialization and schema compatibility

Schema compatibility is guarded by `PRAGMA user_version` against the code-owned
`SCHEMA_VERSION` (schema v7). Migrations are not supported.

Initialization behavior:

- a fresh `user_version = 0` database with **no user-created tables** is initialized: schema created, singleton `profile` row seeded, version set;
- a `user_version = 0` database that already contains any user-created table is rejected;
- a database with an unsupported code-owned schema version is rejected (including schema v6);
- there is no migration path — reset by stopping the application and removing `jung.db` plus `-wal`/`-shm` sidecars (see [safety-and-data.md](safety-and-data.md)).

## Derived workflow stage

`Stage` is not stored. `SQLiteStore.load_snapshot_facts()` loads durable signals and
`workflow.derive_stage(...)` computes the current stage. Impossible present-state
combinations (for example open session + current operation, incomplete profile with
progress, orphan plans without `current_plan_id`) raise `InvariantViolation`.
