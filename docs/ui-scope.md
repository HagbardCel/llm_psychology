---
owner: engineering
status: active
last_reviewed: 2026-05-31
review_cycle_days: 90
source_of_truth_for: Supported frontend scope and archived UI policy
---

# UI Scope

## Supported Frontend

The only actively maintained frontend is `console-ui`.

It connects to the backend through the public HTTP/WebSocket interface and is
used for manual sessions, contract integration testing, and deterministic
workflow probes.

## Archived Frontends

The following surfaces are archived and not maintained on `main`:

- React/Vite web frontend
- standalone in-process terminal UI
- browser E2E and Playwright tooling
- multi-UI startup modes
- web-only helper scripts and task notes formerly stored under `todos/`
- React-specific implementation notes formerly stored under
  `docs/features/frontend-improvements/`

The preserved UI state is available at:

- branch: `archive/ui-state-2026-05-31`
- tag: `archive-ui-state-2026-05-31`
- commit: `0e6ddd9efd7b89c5c9852d093dd94967bc68723b`

Restoring an archived UI is a porting task: restore its former Compose,
Makefile, generation, CI, and documentation wiring together with the UI files.

## Agent Policy

Coding agents must not recreate, repair, test, or optimize archived UIs unless
explicitly instructed.

Default development priority:

1. backend workflow correctness
2. persistence correctness
3. LLM service reliability
4. HTTP/WebSocket contract stability
5. `console-ui` compatibility
6. workflow-probe reliability
