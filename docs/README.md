---
owner: engineering
status: active
last_reviewed: 2026-07-20
review_cycle_days: 90
source_of_truth_for: Documentation entrypoint and canonical navigation
---

# Documentation Index

## Start Here
Use this order if you are new to the codebase:

1. This index for canonical documentation navigation.
2. `docs/ui-scope.md` for the supported frontend policy.
3. `docs/refactor/target-architecture.md` for the supported runtime architecture.
4. `docs/refactor/api-v1-contract.md` for the public client contract.
5. `docs/refactor/workflow-specification.md` for workflow, recovery, and concurrency semantics.

## Active Docs (Canonical)
These docs are the only canonical, actively governed set.

- [Documentation Index](README.md)
- [UI Scope](ui-scope.md)
- [Target Architecture](refactor/target-architecture.md)
- [API v1 Contract](refactor/api-v1-contract.md)
- [Workflow Specification](refactor/workflow-specification.md)

## Completed Refactor Record
The architecture refactor is complete. Measurement methodology, checkpoint
metrics, and acceptance evidence are recorded in
[Refactor Completion](refactor/refactor-completion.md).

## Historical Documentation
Do not keep completed plans, stale assessments, migration notes, or legacy
guides in the working tree. Delete historical documentation after its durable
guidance has been incorporated into active docs; use Git history when old
context is needed.

## Documentation Commands

```bash
make validate-docs
```

## Test Commands

By default, tests use mocked LLM services and skip tests marked `real_llm`.

```bash
make test
make test-unit
make test-integration
make probe-console
```

Native equivalent:

```bash
uv run --locked pytest -m "not real_llm" tests/unit tests/integration
```

### Local-model smoke
Real LLM / local-model smoke is intentionally opt-in via `make smoke-local-llm`.
Start an OpenAI-compatible server on the host, set the `LOCAL_LLM_SMOKE_*`
environment variables as needed, then run:

```bash
make smoke-local-llm
```

## Governance
Documentation policy, metadata requirements, and review cadence:

- [Documentation Governance](DOCS_GOVERNANCE.md)
