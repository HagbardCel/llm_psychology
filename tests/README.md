# Jung Test Suite

Supported tests for the asyncio Jung runtime. Native `uv` is the supported
developer workflow. General developer workflow and release commands are
documented in [`docs/development.md`](../docs/development.md).

## Layout

Generic pytest options and collection hooks live in the repo-root `conftest.py`
so that suites outside `tests/` (notably `evals/`) can reuse `--no-mocks` and
the `real_llm` gate.

```
tests/
├── support/                 # Cross-suite helpers (API fixtures, local-model clients)
├── unit/                    # Fast, deterministic, no I/O
│   ├── architecture/        # Import-boundary checks over src/jung
│   ├── domain/              # Domain models, workflow transitions, grounding types
│   ├── application/         # Application invariants and worker-error classification
│   ├── phases/              # intake / assessment / therapy / post_session logic
│   ├── llm/                 # Gateway, policies, structured output, adapter, tracing
│   ├── client/              # Console rendering, one-shot chat stream, correlation
│   ├── api/                 # Contracts, error mapping, one-shot WS adapter
│   └── smoke/               # Unit tests for the smoke helpers themselves
├── integration/             # Real SQLite, real ASGI app, real client transport
│   ├── store/               # SQLite persistence semantics
│   ├── application/         # Use cases over a real store with fake LLMs
│   ├── api/                 # HTTP + WebSocket over the real app
│   └── client/              # jung-console API client against the real app
├── e2e/                     # Deterministic jung-console workflow probe
└── smoke/                   # Opt-in local-model compatibility (make smoke-local-llm)
```

`evals/` sits beside `tests/` and holds the opt-in real-model suites. See
[`evals/README.md`](../evals/README.md).

`tests/support/local_llm.py` owns connection and client construction shared by
every real-model suite; suite-specific acceptance policy stays in that suite.

Pytest discovery under `tests/unit` and `tests/integration` is authoritative.
There is no Makefile path allowlist. Console E2E lives under `tests/e2e` and
runs as part of `make check` after `make test` (also available via
`make probe-console` alone).

## Ownership rule

**Each invariant has exactly one exhaustive owning layer. Every higher layer
proves only that the invariant survives its own boundary.**

An owning layer enumerates the cases: edge values, error branches, ordering,
concurrency, malformed input. A higher layer takes one representative case and
asserts that its boundary (SQL, use case, HTTP/WS, transport, terminal) does
not lose or corrupt the behavior. If a test at a higher layer is re-deriving
the case matrix of a lower layer, it belongs one layer down.

This keeps the failure signal legible: when an invariant breaks, the owning
layer fails with a precise message, and the boundary layers fail only when the
boundary itself is the problem.

Tests protect current contracts, invariants, and observable behavior. Do not
retain permanent tests whose sole purpose is to prove that a superseded module,
field, dependency, filename, schema version, or architecture remains absent.
Temporary deletion gates may be used during a cutover and must be removed when
the cutover closes. Negative assertions remain appropriate when absence itself
is part of the current contract or behavior. When a superseded-name assertion
was guarding a bounded current surface, prefer an exact positive inventory of
that surface's membership rather than leaving the invariant unguarded.

When reviewing a test hit during archaeology, ask: is this a current invariant,
a positive inventory, or a prove-gone tombstone? Delete only the third category.

### One-owner examples

| Invariant | Exhaustive owner | Higher layers |
| --- | --- | --- |
| Chat message idempotency / unanswered retry | `integration/store/test_store_chat.py` — `(session_id, client_message_id, role)` uniqueness, unanswered-user guards, assistant attach | `stream_message` cases in `integration/application/test_application_chat.py`; one-shot WS round-trip in `integration/api/test_websocket_chat.py` and `JungChatConnection.stream` in `integration/client/`; one journey step in `e2e/` |
| Error sanitization | `unit/application/test_invariants.py` (`_classify_work_error`) and `unit/api/test_error_mapping.py` | `integration/api/test_http_errors.py` asserts the wire response carries the public code and no internals |
| Generated HTTP schema and route surface | `integration/api/test_openapi.py` — operation inventory, common headers/error responses, snapshot response types, docs exposure | none; the generated schema is itself the boundary |
| SQLite schema/CHECK/singleton constraints | `integration/store/test_store_schema.py` — fresh/current init, CHECK constraints, singleton indexes | `integration/store/test_store_chat.py` for message idempotency semantics |
| Citation grounding | `unit/phases/post_session/test_evidence_validation.py` — every rejection and resolution rule | `integration/application/` asserts a grounded result is persisted and read back intact |
| Worker-error classification | `unit/application/test_invariants.py` | `integration/application/test_application_operations.py` asserts a failed operation surfaces the classified code |
| Workflow transitions | `unit/domain/test_workflow.py` — the full legal/illegal transition matrix | `integration/store/test_store_workflow.py` for persisted stage changes; one `e2e/` journey |

### Do not test Pydantic at every layer

Field types, required-ness, and constraint validation are owned by the model's
own unit test. Do not re-assert them in application, API, client, or E2E tests.
At a boundary, assert what that boundary adds: the field crossed the wire,
survived a round-trip through SQLite, or reached the terminal renderer.

## Real-model suites: smoke, evals, eval-report

Three different questions, three different owners. None of them run in
`make test` or `make check`.

| Surface | Question | Failure means |
| --- | --- | --- |
| `make smoke-local-llm` (`tests/smoke/`) | Can this server and model run our paths at all — streaming works, structured output parses, latency is within budget? | The model or server is incompatible with the runtime |
| `make evals` (`evals/test_hard_invariants.py`) | Does the model honor the contractual behavior the product depends on — no system-prompt disclosure, no objective hijack, citations resolve to authoritative turns? | The model is unsuitable, or a prompt/validation regression let something through |
| `make eval-report` (`evals/behavioral_report.py`) | What does the model actually say in crisis, medical-advice, delusion, and dependency scenarios? | Nothing — the report exits non-zero only if it could not be produced |

Smoke deliberately does **not** assert grounding or negation behavior; those
are hard-eval invariants. Report scenarios deliberately assert nothing about
semantic quality; they exist for human review under `logs/evals/`.

## Running tests

```bash
make test                                   # unit + integration (not real_llm)
make test-unit
make test-integration
make check                                  # format, lint, docs-links, test, probe-console
make probe-console                          # Deterministic jung-console E2E once
```

Opt-in real-model entry points and the full release gate are documented in
[`docs/development.md`](../docs/development.md).

## Conventions

- Prefer deterministic fakes over live model calls.
- Mark opt-in live-model tests with `real_llm`; hard evals also carry `eval`.
- `real_llm` tests skip unless `--no-mocks` is passed.
- Keep import-boundary tests durable and directory-discovered; express package/layer dependency direction, not filename freezes or private-helper layout rules.
- Never read environment variables or construct clients at import time.
