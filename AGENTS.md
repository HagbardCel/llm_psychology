# Codex Agent Guide

## Project Structure
- `src/jung/`: Supported asyncio application (API, composition, workflow, phases, LLM, persistence, client).
- `tests/`: Pytest suites; `make test` collects `tests/unit` and `tests/integration`.
- `data/`: SQLite databases (`local/jung.db`, `usertest/jung.db`).
- `docs/`: Architecture, contracts, and guides (see Active Docs in `docs/README.md`).

## Documentation Map (Read First)
- `docs/README.md`: Doc index and canonical navigation.
- `docs/ui-scope.md`: Supported frontend policy (`jung-console`).
- `docs/refactor/target-architecture.md`: Current runtime architecture.
- `docs/refactor/api-v1-contract.md`: Supported external HTTP/WebSocket API.
- `docs/refactor/workflow-specification.md`: Supported Jung workflow.

## Key Entry Points (Code)
- `src/jung/api/app.py`: FastAPI server factory and `jung-api` CLI.
- `src/jung/composition.py`: Typed composition root.
- `src/jung/config.py`: Environment-backed application settings.
- `src/jung/client/terminal.py`: Supported `jung-console` client.
- `src/jung/application.py`: Application use cases.

## Command Execution

Native `uv` is the canonical local workflow. Docker is used for packaging and
CI parity, not as a requirement for day-to-day development.

Canonical native workflow:

```bash
uv sync --locked
uv run jung-api
uv run jung-console --api-url http://127.0.0.1:8000
uv run pytest -m "not real_llm" tests/unit tests/integration
```

Equivalent `make` targets: `make sync`, `make run-api`, `make run-console`,
`make test`.

Docker packaging/CI helpers:

- Build images: `make dev-install`
- Start backend: `make docker-up` (or `make run-server`)
- Backend shell: `make docker-shell`
- One-off backend command: `docker compose run --rm api <command>`
- Supported frontend: `make ui-console` (`jung-console`)
- Manual usertest: `make ui-console-test`

## Tests

The ordinary test tree (`tests/unit` + `tests/integration`) is authoritative;
there are no separate Phase-numbered validator scripts.

- Default suite: `make test` (`tests/unit` + `tests/integration`, not `real_llm`)
- Unit: `make test-unit`
- Integration: `make test-integration`
- Single path: `make docker-test-one TEST=tests/unit/jung/...` (or
  `uv run pytest tests/unit/jung/...` natively)
- Deterministic console probe: `make probe-console` (E2E once; not part of `make test`)
- Release-candidate validation: `make finalization-check`

## Core Developer Guidance
- The supported runtime is asyncio FastAPI under `src/jung` (ADR 0002).
- Clients use `/api/v1` only; do not import application internals from clients.
- Do not add Trio/asyncio compatibility adapters to target code.
- Prefer existing utilities and services before adding new ones.
- If docs conflict with this guide, follow this guide and update the docs you touched.
- If HTTP/WS contracts or API-facing models change, update the active API v1 contract docs.
- Add deterministic tests for new behavior.

## Active Scope
Treat the Jung backend, workflow, persistence, `/api/v1` contracts, LLM gateway, deterministic tests, and `jung-console` probes as the main product.

- Maintain `jung-console` as the only supported frontend.
- Do not recreate, repair, test, or optimize removed UIs unless explicitly requested.
- Do not add multi-frontend orchestration modes.
- Prefer Jung unit/integration tests and the v1 console probe.

## Foundation Failure Policy
Do not hide workflow, LLM, persistence, protocol, or contract failures behind fallback behavior unless explicitly requested.

- Prefer fail-fast, diagnostic errors with preserved workflow state and deterministic tests.
- Treat fallbacks as product decisions; document and test them when they are intentionally added.
- Workflow probes must not convert real backend failures into passes.
- For LLM structured-output failures, preserve enough bounded diagnostic context to identify the phase, schema, provider, model, and parse failure without leaking full prompts or transcripts by default.

## Version Control Guidelines
- Branch from `main` using `feat/<topic>` or `fix/<topic>`.
- Keep commits small and scoped; use conventional prefixes (`feat:`, `fix:`, `docs:`).
- Run `make test` (or `uv run pytest -m "not real_llm" tests/unit tests/integration`) before committing.
- Avoid force pushes to shared branches; rebase only on local branches.
