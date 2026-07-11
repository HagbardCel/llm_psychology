---
owner: engineering
status: accepted
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Target single-user and API ownership decision
---

# ADR 0001: Single-user API modular monolith

## Context

The running system has user-scoped routes and a console-specific integration path. The target is a local application for one real user.

## Decision

The target has one profile and at most one active session. `/api/v1` is the only client boundary; the API process is the only SQLite writer and owns workflow, LLM execution, recovery, and concurrency. Tests select isolated databases or data directories rather than creating domain users.

## Consequences

Target routes, DTOs, persistence, caches, and commands contain no `user_id`, registration, login, or user lookup. Console and future web clients use the same API. Microservices and frontend-owned workflow state are rejected.

## Invariants

- Clients do not import backend internals or write SQLite.
- A second connected client may observe state but cannot bypass command serialization.
- This decision applies after cutover; legacy behavior remains unchanged during Phase 1.

## Follow-up

Implement the target API in Phase 5 and delete multi-user plumbing in Phase 6.
