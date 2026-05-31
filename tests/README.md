# Therapist Test Suite

The backend test suite for the therapist app. Everything runs inside Docker
(see [`AGENTS.md`](../AGENTS.md) for the canonical commands) and uses Trio as
the async runtime.

## Layout

```
tests/
├── conftest.py            # Shared fixtures (settings, DB, mock services)
├── test_entry_points.py   # Smoke tests for CLI entry points
├── test_trio_validation.py# Cross-cutting Trio invariants
├── unit/                  # Pure unit tests (default suite)
├── integration/           # Cross-component tests against real services
└── real_llm/              # Tests that hit a real LLM (opt-in only)
```

- `unit/`: Fast, deterministic, mock-driven tests for individual modules
  (agents, repos, services, helpers, route handlers). This is the default
  `make docker-test` suite.
- `integration/`: Trio-based flows that exercise multiple layers (HTTP API,
  WebSocket protocol, orchestration, persistence). They use a temp SQLite DB
  and mocked LLMs.
- `real_llm/`: Smoke tests that talk to a real model (Gemini, LM Studio, etc.).
  Skipped by default. Use these only when validating LLM-side behavior.

## Running tests (Docker-only)

```bash
make test-validate                          # Full backend suite (unit + integration)
make docker-test                            # Same as above
make docker-test-one TEST=tests/unit/test_foo.py
docker compose run --rm api pytest tests/unit/test_foo.py::test_bar
```

For the frontend:

```bash
make docker-test-frontend                                       # Vitest unit tests
docker compose run --rm frontend npm run lint                   # ESLint
docker compose run --rm frontend npx playwright install --with-deps  # one-time
docker compose run --rm frontend npm run test:e2e               # Playwright E2E
```

## Conventions

- All async tests use `pytest-trio` (`@pytest.mark.trio`). Do not introduce
  `asyncio` tests.
- Each test creates an isolated SQLite database via `tmp_path` fixtures; never
  mutate `data/*.db` from a test.
- LLM calls are mocked. Add a `real_llm/` test only when the behavior under
  test is intrinsic to the model.
- Markers: `@pytest.mark.unit`, `@pytest.mark.integration`. CI runs unit and
  integration by default.
- Keep tests deterministic: avoid wall-clock dependencies, fix random seeds,
  freeze time when needed.

## Adding new tests

1. Pick the closest existing module under `unit/` or `integration/`.
2. Reuse fixtures from `conftest.py`; add new ones there if they are shared.
3. Prefer asserting on observable behavior (DB state, HTTP responses, WS
   messages) over internal implementation details.
4. Run `make docker-test-one TEST=...` for fast feedback before
   `make test-validate`.

## Related documentation

- [Architecture overview](../docs/ARCHITECTURE.md)
- [Foundation stabilization plan](../docs/reference/FOUNDATION_STABILIZATION_PLAN.md)
- [HTTP / WebSocket contracts](../docs/contracts/)
