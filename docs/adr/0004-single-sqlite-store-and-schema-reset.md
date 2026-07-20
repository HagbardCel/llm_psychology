---
owner: engineering
status: accepted
last_reviewed: 2026-07-20
review_cycle_days: 30
source_of_truth_for: Target SQLite ownership and reset policy
---

# ADR 0004: One SQLiteStore and schema reset

## Decision

`SQLiteStore` exposes synchronous use-case methods. Each method opens/closes one short-lived `sqlite3` connection; schema initialization enables WAL; each connection enables foreign keys and a 5-second busy timeout. Writes use one `BEGIN IMMEDIATE` transaction and async callers invoke the entire method through `asyncio.to_thread()`.

The schema has `app_state`, `profile`, `sessions`, normalized `messages`, immutable `plans`, `operations`, and `chat_turns`. No ORM, pool, executor, repositories, migration compatibility, or shared cross-thread connection is used.

## Consequences

Application mutation locking is primary serialization; SQLite locking is a fallback. Multi-table completion methods own their whole transaction. At cutover, optionally archive the existing database if its contents should be retained, then recreate the database from the target schema. No compatibility migration or application-level backup/restore tooling is maintained.
