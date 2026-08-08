---
owner: engineering
status: active
last_reviewed: 2026-08-08
review_cycle_days: 30
source_of_truth_for: Persistence relational model, invariants, and schema compatibility
---

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
   ├── messages
   └── operations
```

Durable chat truth is `messages` only. There is no `chat_turns` table.
`client_message_id` is stored on every message. A completed exchange is a
`user` row and an `assistant` row sharing `(session_id, client_message_id)`.

## Table overview

| Table | Purpose | Key relationships | Important constraints |
|---|---|---|---|
| `app_state` | Singleton workflow stage | — | `singleton_id = 1` |
| `profile` | Singleton user-editable profile plus optional derived JSON and current plan pointer | `current_plan_id` → `plans` | `singleton_id = 1` |
| `sessions` | Intake and therapy sessions | `plan_id` → `plans` | at most one open session globally; therapy sessions must not carry intake JSON |
| `plans` | Immutable plan revisions | `source_session_id` → `sessions`; `supersedes_plan_id` → `plans` | unique `version`; unique `source_session_id`; at most one successor per superseded plan |
| `messages` | Durable transcript | `session_id` → `sessions` | unique `(session_id, sequence)`; roles `user`/`assistant`; required `client_message_id`; unique `(session_id, client_message_id, role)` |
| `operations` | Assessment and post-session background work | `source_session_id` → `sessions` | unique `(kind, source_session_id)`; at most one current pending/running/failed operation globally |

## DDL-enforced invariants

These guarantees are encoded in SQL (including partial unique indexes that use
constant expressions and are therefore **database-global**):

- `app_state` and `profile` are singletons (`singleton_id = 1`);
- at most one open session globally (`ended_at IS NULL`);
- unique message sequence within a session;
- message roles are `user` or `assistant` only;
- message acceptance is idempotent by `(session_id, client_message_id, role)`;
- plan versions are unique and ≥ 1; non-empty `focus` and `current_progress`;
- one source session creates at most one plan revision (`source_session_id` unique);
- a non-null `supersedes_plan_id` may be referenced by at most one successor plan;
- operations are idempotent by `(kind, source_session_id)`;
- at most one operation whose status is `pending`, `running`, or `failed` globally;
- operation status fields are coupled to `result_json` / error columns via CHECK constraints;
- session kinds are `intake` or `therapy`; therapy rows must not store intake JSON.

## Store/application persistence invariants

These relationships and policies are maintained by `SQLiteStore` and the
application rather than claimed as pure SQL guarantees:

- plan revisions are immutable as a programming model (new revision rows, never in-place mutation of plan content);
- valid workflow stage transitions and command acceptance are application/workflow policy;
- an open session may have at most one trailing unanswered `USER`; a new user message is rejected until that ID is retried (see [workflow.md](workflow.md));
- assistant persistence requires an unanswered latest user message in the same session with the matching `client_message_id`;
- multi-table use cases such as assessment completion and post-session completion commit atomically in store methods;
- `SQLiteStore` owns SQL transaction boundaries (`BEGIN IMMEDIATE`) and commit/rollback; it does not own optimistic concurrency checks or snapshot-revision increments;
- `TherapyApplication` serializes mutations and validates commands against authoritative state before calling the store;
- `app_state.updated_at` means the last persisted workflow-stage change.

## JSON-owned documents

JSON TEXT columns hold validated documents owned by specific subsystems:

| Column | Owner |
|---|---|
| `sessions.briefing_json` | Post-session / session artifacts |
| `sessions.intake_record_json` | Intake processor |
| `plans.themes_json`, `goals_json`, `planned_interventions_json`, `revision_recommendations_json` | Plan revision material |
| `plans.session_briefing_json` | Immutable copy of source-session briefing at plan creation |
| `profile.derived_profile_json` | Post-session derived profile merge |
| `operations.result_json` | Assessment: structured assessment result. Post-session: compact completion metadata (`plan_id`, `plan_version`, `profile_changed`); summary/briefing/profile/plan artifacts are persisted elsewhere |

## Connection and transaction policy

- Each synchronous store operation opens and closes its own SQLite connection.
- Connections enable WAL, `foreign_keys=ON`, and a 5-second busy timeout.
- Writes use `BEGIN IMMEDIATE`.
- Async application code calls whole store operations via `asyncio.to_thread()`; no connection is shared across threads.
- The API/application process is the sole product-level SQLite writer; clients never write the database directly.

## Initialization and schema compatibility

Schema compatibility is guarded by `PRAGMA user_version` against the code-owned
`SCHEMA_VERSION` (schema v5). Migrations are not supported.

Initialization behavior:

- a fresh `user_version = 0` database with no Jung tables is initialized: schema created, singleton `app_state` and `profile` rows seeded, version set;
- a `user_version = 0` database that already contains Jung tables is rejected;
- a database with an unsupported code-owned schema version is rejected;
- there is no migration path — reset by stopping the application and removing `jung.db` plus `-wal`/`-shm` sidecars (see [safety-and-data.md](safety-and-data.md)).
