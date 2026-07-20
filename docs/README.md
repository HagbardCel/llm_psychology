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
canonical for the supported Phase 6C runtime.

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
docker compose --profile test run --rm test pytest tests/unit/test_llm_service.py
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
make docker-test-one TEST="tests/real_llm/test_file.py --no-mocks"
```

### Local LM Studio Smoke Test
The LM Studio smoke test is intentionally double opt-in:
- `--no-mocks` disables the global `real_llm` skip.
- `RUN_LMSTUDIO_SMOKE=1` confirms that the test should call a host-local model.

Start LM Studio on the host with the OpenAI-compatible server listening on
`localhost:1234`, then run:

```bash
docker compose --profile test run --rm \
  -e RUN_LMSTUDIO_SMOKE=1 \
  test pytest tests/real_llm/test_lmstudio_local_smoke.py --no-mocks
```

The test container reaches the host service at
`http://host.docker.internal:1234/v1`.

## Governance
Documentation policy, metadata requirements, and review cadence:

- [Documentation Governance](DOCS_GOVERNANCE.md)
