---
owner: engineering
status: active
last_reviewed: 2026-02-14
review_cycle_days: 90
source_of_truth_for: Documentation entrypoint and canonical navigation
---

# Documentation Index

## Start Here
Use this order if you are new to the codebase:

1. `docs/design-principles.md` for architecture invariants and implementation rules.
2. `docs/ARCHITECTURE.md` for component boundaries and runtime flow.
3. `docs/user_journey.md` for end-to-end user and protocol flow.
4. `docs/session_lifecycle.md` for workflow/session ownership details.
5. `docs/contracts/HTTP_API_CONTRACT.md` and `docs/WEBSOCKET_PROTOCOL.md` for API contracts.
6. `docs/TYPE_SYSTEM.md` for schema/type generation pipeline.

## Active Docs (Canonical)
These docs are the only canonical, actively governed set.

- [Documentation Index](README.md)
- [Design Principles](design-principles.md)
- [Architecture](ARCHITECTURE.md)
- [User Journey](user_journey.md)
- [Session Lifecycle](session_lifecycle.md)
- [HTTP API Contract](contracts/HTTP_API_CONTRACT.md)
- [WebSocket Protocol](WEBSOCKET_PROTOCOL.md)
- [Type System](TYPE_SYSTEM.md)
- [Data Models](data-models.md)
- [Agents](agents/README.md)
- [Assessments Index](assessments/README.md)

## Supporting Documentation
Use these for focused implementation work; active docs remain the source of truth.

- `docs/current_issues/`: active troubleshooting and known issues.
- `docs/features/`: feature-level implementation details.
- `docs/plans/`: implementation plans in progress.
- `docs/assessments/`: architecture, testing, UX and project assessments.
- `docs/todo/`: tactical worklists.

## Archive and Legacy
These paths are historical context, not canonical guidance:

- `docs/archive/`
- `docs/legacy/`

When archive content conflicts with active docs, follow active docs.

## Docker-First Documentation Commands
Run documentation checks through Docker:

```bash
make validate-docs
make validate-schemas
make generate-schemas
```

## Governance
Documentation policy, metadata requirements, and review cadence:

- [Documentation Governance](DOCS_GOVERNANCE.md)
