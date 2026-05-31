---
owner: engineering
status: active
last_reviewed: 2026-05-31
review_cycle_days: 90
source_of_truth_for: Supported frontend scope and removed-UI policy
---

# UI Scope

## Supported Frontend

The only actively maintained frontend is `console-ui`.

It connects to the backend through the public HTTP/WebSocket interface and is
used for manual sessions, contract integration testing, and deterministic
workflow probes.

## Removed Frontends

Former frontend implementations are not maintained on `main`. Restoring one is
separate product work and must not be mixed into foundation-stabilization
changes.

## Agent Policy

Coding agents must not recreate, repair, test, or optimize removed UIs unless
explicitly instructed.

Default development priority:

1. backend workflow correctness
2. persistence correctness
3. LLM service reliability
4. HTTP/WebSocket contract stability
5. `console-ui` compatibility
6. workflow-probe reliability
