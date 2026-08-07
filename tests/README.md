# Jung Target Test Suite

Supported tests for the asyncio Jung runtime. Native `uv` is the canonical
developer workflow; Docker remains available for reproducible CI/runtime images.

## Layout

Generic pytest options and collection hooks live in the repo-root `conftest.py`
so that suites outside `tests/` can reuse `--no-mocks` and the `real_llm` gate.

```
tests/
├── support/                 # Cross-suite helpers (API fixtures, local-model clients)
├── unit/                    # Unit tests, grouped by the code area they cover
├── integration/             # API / application / store / client integration tests
├── e2e/                     # Deterministic jung-console workflow probe
└── smoke/                   # Opt-in local-model smoke (make smoke-local-llm)
```

`tests/support/local_llm.py` owns connection and client construction shared by
every real-model suite; suite-specific acceptance policy stays in that suite.

Pytest discovery under `tests/unit` and `tests/integration` is authoritative.
There is no Makefile path allowlist. Console E2E lives under `tests/e2e` and is
run separately via `make probe-console`.

## Running tests

```bash
make test                                   # unit + integration (not real_llm)
make test-unit
make test-integration
make probe-console                          # Deterministic jung-console E2E once
make finalization-check                     # Release gate (format/lint/docs/test/probe/compose)
```

Native equivalent:

```bash
uv run --locked pytest -m "not real_llm" tests/unit tests/integration
uv run --locked pytest tests/unit/...
```

## Conventions

- Prefer deterministic fakes over live model calls.
- Mark opt-in live-model tests with `real_llm`.
- Keep import-boundary tests durable and directory-discovered.
