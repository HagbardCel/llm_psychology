# Jung Target Test Suite

Supported tests for the asyncio Jung runtime. Docker is the canonical
reproducible workflow; native `uv run pytest` remains supported.

## Layout

```
tests/
├── conftest.py              # Generic pytest options and collection hooks
├── unit/jung/               # Deterministic Jung unit tests
├── integration/jung/        # Jung API / application / store integration tests
├── smoke/jung/              # Opt-in local-model smoke (make smoke-target-local-llm)
├── e2e/                     # Deterministic jung-console workflow probe
├── jung_api_fixtures.py     # Shared API fixtures for probes and e2e
└── console_probe_support.py # Probe helpers used by jung-console e2e
```

Remaining files under `tests/` that target `psychoanalyst_app` are deletion-pending
legacy coverage retained until Phase 6D and are not part of `make test-target`.

## Running tests

Docker-first:

```bash
make test-target                            # Complete supported suite
make test-unit                              # tests/unit/jung + support tests
make test-integration                       # tests/integration/jung
make docker-test-one TEST=tests/unit/jung/...
make probe-console-v1-deterministic         # Deterministic jung-console probe
make finalization-check                     # Release-candidate gate
```

Bare `docker compose --profile test run test` runs the core Jung unit and
integration trees (with asyncio overrides). `make test-target` runs the complete
supported suite, including validator and support tests.

Native alternative (core Jung trees):

```bash
uv run pytest \
  -o trio_mode=false \
  -o asyncio_mode=auto \
  -m "not real_llm" \
  tests/unit/jung \
  tests/integration/jung
```

## Conventions

- Target async tests use asyncio (`@pytest.mark.asyncio` / `asyncio_mode=auto`).
- Prefer asserting on observable behavior (HTTP/WebSocket responses, store state)
  over internal implementation details.
- Keep tests deterministic: avoid wall-clock dependencies and live LLM calls in
  the default suite. Use `tests/smoke/jung/` with `--no-mocks` only when validating
  a real local model.

## Related documentation

- [AGENTS.md](../AGENTS.md)
- [Target architecture](../docs/refactor/target-architecture.md)
- [API v1 contract](../docs/refactor/api-v1-contract.md)
