---
owner: engineering
status: active
last_reviewed: 2026-08-08
review_cycle_days: 90
source_of_truth_for: Documentation entrypoint and canonical navigation
---

# Documentation Index

## Start Here
Use this order if you are new to the codebase:

1. This index for canonical documentation navigation.
2. [Safety and Data Handling](safety-and-data.md) for product safety and data-handling guidance.
3. [Development](development.md) for setup, commands, and configuration guidance.
4. [Architecture](architecture.md) for runtime architecture, tech stack, and source layout.
5. [Workflow Specification](workflow.md) for stages, recovery, and command-conflict semantics.
6. [Database](database.md) and [API v1 Contract](api-v1.md) as needed for persistence and the public contract.

## Active Docs (Canonical)
These docs are the only canonical, actively governed set.

- [Documentation Index](README.md)
- [Safety and Data Handling](safety-and-data.md)
- [Development](development.md)
- [Architecture](architecture.md)
- [Workflow Specification](workflow.md)
- [Database](database.md)
- [API v1 Contract](api-v1.md)

## Historical Documentation
Do not keep completed plans, stale assessments, migration notes, or superseded
guides in the working tree. Delete historical documentation after its durable
guidance has been incorporated into active docs; use Git history when old
context is needed.

## Documentation Commands

```bash
make validate-docs
```

## Governance
Documentation policy, ownership matrix, metadata requirements, and review cadence:

- [Documentation Governance](DOCS_GOVERNANCE.md)
