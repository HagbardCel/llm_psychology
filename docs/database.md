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
   ├── operations
   └── chat_turns ──user/assistant_message_id──► messages
```

`client_message_id` lives on `chat_turns` (acceptance idempotency), not
redundantly on `messages`. Message `client_message_id` in API read models is
derived from the owning turn.

## Table overview

| Table | Purpose | Key relationships | Important constraints |
|---|---|---|---|
| `app_state` | Singleton workflow stage and snapshot revision | — | `singleton_id = 1` |
| `profile` | Singleton user-editable profile plus optional derived JSON and current plan pointer | `current_plan_id` → `plans` | `singleton_id = 1` |
| `sessions` | Intake and therapy sessions | `plan_id` → `plans` | at most one open session globally; therapy sessions must not carry intake JSON |
| `plans` | Immutable plan revisions | `source_session_id` → `sessions`; `supersedes_plan_id` → `plans` | unique `version`; unique `source_session_id`; at most one successor per superseded plan |
| `messages` | Durable transcript turns | `session_id` → `sessions` | unique `(session_id, sequence)`; roles `user`/`assistant`/`system` |
| `operations` | Assessment and post-session background work | `source_session_id` → `sessions` | unique `(kind, source_session_id)`; at most one current pending/running/failed operation globally |
| `chat_turns` | Chat acceptance and generation lifecycle | `session_id` → `sessions`; `user_message_id` / `assistant_message_id` → `messages` | unique `(session_id, client_message_id)`; at most one pending turn globally; unique user/assistant message ownership |

## DDL-enforced invariants

These guarantees are encoded in SQL (including partial unique indexes that use
constant expressions and are therefore **database-global**):

- `app_state` and `profile` are singletons (`singleton_id = 1`);
- at most one open session globally (`ended_at IS NULL`);
- unique message sequence within a session;
- plan versions are unique and ≥ 1; non-empty `focus` and `current_progress`;
- one source session creates at most one plan revision (`source_session_id` unique);
- a non-null `supersedes_plan_id` may be referenced by at most one successor plan;
- operations are idempotent by `(kind, source_session_id)`;
- at most one operation whose status is `pending`, `running`, or `failed` globally;
- chat acceptance is idempotent by `(session_id, client_message_id)`;
- at most one chat turn with status `pending` globally;
- `user_message_id` is unique; a non-null `assistant_message_id` is unique;
- operation and chat status fields are coupled to `result_json` / assistant message / error columns via CHECK constraints;
- session kinds are `intake` or `therapy`; therapy rows must not store intake JSON.

## Store/application persistence invariants

These relationships and policies are maintained by `SQLiteStore` and the
application rather than claimed as pure SQL guarantees:

- plan revisions are immutable as a programming model (new revision rows, never in-place mutation of plan content);
- valid workflow stage transitions and command acceptance are application/workflow policy;
- store APIs create turn-owned user/assistant messages with the owning turn's session and expected roles; these cross-table semantic relationships are application/store invariants rather than SQL constraints (foreign keys only guarantee that the referenced message exists);
- multi-table use cases such as assessment completion and post-session completion commit atomically in store methods;
- transaction orchestration and revision increments are application-owned.

## JSON-owned documents

JSON TEXT columns hold validated documents owned by specific subsystems:

| Column | Owner |
|---|---|
| `sessions.briefing_json` | Post-session / session artifacts |
| `sessions.intake_record_json` | Intake processor |
| `plans.themes_json`, `goals_json`, `planned_interventions_json`, `revision_recommendations_json` | Plan revision material |
| `plans.session_briefing_json` | Immutable copy of source-session briefing at plan creation |
| `profile.derived_profile_json` | Post-session derived profile merge |
| `operations.result_json` | Assessment or post-session structured result |

## Connection and transaction policy

- Each synchronous store operation opens and closes its own SQLite connection.
- Connections enable WAL, `foreign_keys=ON`, and a 5-second busy timeout.
- Writes use `BEGIN IMMEDIATE`.
- Async application code calls whole store operations via `asyncio.to_thread()`; no connection is shared across threads.
- The API/application process is the sole product-level SQLite writer; clients never write the database directly.

## Initialization and schema compatibility

Schema compatibility is guarded by `PRAGMA user_version` against the code-owned
`SCHEMA_VERSION`. Migrations are not supported.

Initialization behavior:

- a fresh `user_version = 0` database with no Jung tables is initialized: schema created, singleton `app_state` and `profile` rows seeded, version set;
- a `user_version = 0` database that already contains Jung tables is rejected;
- a database with an unsupported code-owned schema version is rejected;
- there is no migration path — reset by stopping the application and removing `jung.db` plus `-wal`/`-shm` sidecars (see [safety-and-data.md](safety-and-data.md)).
