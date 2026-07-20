# Jung Target Test Suite

Supported tests for the asyncio Jung runtime. Native `uv` is the canonical
developer workflow; Docker remains available for reproducible CI/runtime images.

## Layout

```
tests/
├── conftest.py              # Generic pytest options and collection hooks
├── unit/                    # Unit tests (jung/ + support scripts)
├── integration/jung/        # Jung API / application / store integration tests
├── smoke/jung/              # Opt-in local-model smoke (make smoke-local-llm)
├── e2e/                     # Deterministic jung-console workflow probe
├── jung_api_fixtures.py     # Shared API fixtures for probes and e2e
└── console_probe_support.py # Probe helpers used by jung-console e2e
```

Pytest discovery under `tests/unit` and `tests/integration` is authoritative.
There is no Makefile path allowlist. Console E2E lives under `tests/e2e` and is
run separately via `make probe-console`.

## Running tests

```bash
make test                                   # unit + integration (not real_llm)
make test-unit
make test-integration
make docker-test-one TEST=tests/unit/jung/...
make probe-console                          # Deterministic jung-console E2E once
make finalization-check                     # Release gate (format/lint/docs/test/probe/compose)
```

Native alternative:

```bash
uv run --locked pytest -m "not real_llm" tests/unit tests/integration
```

## Conventions

- Prefer deterministic fakes over live model calls.
- Mark opt-in live-model tests with `real_llm`.
- Keep import-boundary tests durable and directory-discovered.
