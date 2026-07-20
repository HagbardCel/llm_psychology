---
owner: engineering
status: active
last_reviewed: 2026-05-31
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

## Legacy supporting reference pending Phase 7 rewrite
These documents describe retired or deletion-pending architecture, contracts, and
workflow. They are retained temporarily for migration context and are not
canonical for the supported Jung runtime.

- [Design Principles](design-principles.md)
- [Architecture](ARCHITECTURE.md)
- [User Journey](user_journey.md)
- [Session Lifecycle](session_lifecycle.md)
- [HTTP API Contract](contracts/HTTP_API_CONTRACT.md)
- [WebSocket Protocol](WEBSOCKET_PROTOCOL.md)
- [Type System](TYPE_SYSTEM.md)
- [Data Models](data-models.md)
- [Agents](agents/README.md)

## Historical Documentation
Do not keep completed plans, stale assessments, migration notes, or legacy
guides in the working tree. Delete historical documentation after its durable
guidance has been incorporated into active docs; use Git history when old
context is needed.

## Docker-First Documentation Commands
Run documentation checks through Docker:

```bash
make validate-docs
```

## Docker-First Test Commands
Run tests through Docker; do not run Python or Node directly on the host.

### Default Deterministic Tests
By default, tests use mocked LLM services and skip tests marked `real_llm`.
Use these for normal development and pre-commit checks:

```bash
make test-target
make test-unit
make test-integration
make docker-test-one TEST=tests/unit/jung/test_workflow.py
```

Equivalent direct pytest-in-Docker form:

```bash
docker compose --profile test run --rm test pytest tests/unit/jung/test_workflow.py
```

### Real LLM Tests
Real LLM tests are marked `real_llm` and are skipped unless pytest receives
`--no-mocks`. Use this only when the required API keys or local model servers
are available:

```bash
docker compose --profile test run --rm test pytest -m real_llm --no-mocks
```

For a single real-LLM test through the Makefile, include `--no-mocks` in `TEST`:

```bash
make docker-test-one TEST="tests/smoke/jung/test_phase3_local_llm.py --no-mocks"
```

### Local LM Studio Smoke Test
The local-model smoke is intentionally opt-in via `make smoke-target-local-llm`
(or the Phase 3 smoke target it aliases). Start an OpenAI-compatible server on
the host, set the `PHASE3_SMOKE_*` environment variables as needed, then run:

```bash
make smoke-target-local-llm
```

## Governance
Documentation policy, metadata requirements, and review cadence:

- [Documentation Governance](DOCS_GOVERNANCE.md)
