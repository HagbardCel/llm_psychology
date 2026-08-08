# Codex Agent Guide

## Project Structure
- `src/jung/`: Supported asyncio application (API, composition, workflow, phases, LLM, persistence, client).
- `tests/`: Pytest suites; `make test` collects `tests/unit` and `tests/integration`.
- `evals/`: Opt-in real-model evaluations (`make evals`, `make eval-report`).
- `data/`: SQLite databases (`local/jung.db`, `usertest/jung.db`).
- `docs/`: Canonical documentation (see Active Docs in `docs/README.md`).

## Documentation Map (Read First)
- `docs/README.md`: Doc index and canonical navigation.
- `docs/safety-and-data.md`: Product safety, data handling, and network exposure.
- `docs/development.md`: Setup, commands, and configuration guidance.
- `docs/architecture.md`: Runtime architecture, tech stack, and source layout.
- `docs/workflow.md`: Workflow, recovery, and command-conflict semantics.
- `docs/database.md`: Persistence model and invariants.
- `docs/api-v1.md`: Supported external HTTP/WebSocket API.

Canonical documentation governs product architecture, runtime behavior, and
contracts. `AGENTS.md` contains agent-specific workflow constraints. If this
file restates a product fact inconsistently with canonical documentation, the
canonical documentation wins and `AGENTS.md` must be corrected.

## Key Entry Points (Code)
- `src/jung/api/app.py`: FastAPI server factory and `jung-api` CLI.
- `src/jung/composition.py`: Typed composition root.
- `src/jung/config.py`: Environment-backed application settings.
- `src/jung/client/terminal.py`: Supported `jung-console` client.
- `src/jung/application.py`: Application use cases.

## Commands

Native `uv` is the normal local workflow. Docker is used for packaging and
runtime smoke, not as a requirement for day-to-day development.

See [docs/development.md](docs/development.md) for the comprehensive command
reference (`make sync`, `make run-api`, `make run-console`, `make test`,
optional Docker targets, and the release gate).

## Tests

The ordinary test tree (`tests/unit` + `tests/integration`) is authoritative.
Each invariant has one exhaustive owning layer; higher layers only prove
boundary survival. See `tests/README.md` for the layout and ownership rules.
See `evals/README.md` before adding a real-model eval.

## Core Developer Guidance
- The supported runtime is asyncio FastAPI under `src/jung`.
- Clients use `/api/v1` only; do not import application internals from clients.
- Do not add Trio/asyncio compatibility adapters to runtime code.
- Prefer existing utilities and services before adding new ones.
- If HTTP/WS contracts or API-facing models change, update `docs/api-v1.md`.
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
- Run `make test` (or `uv run --locked pytest -m "not real_llm" tests/unit tests/integration`) before committing.
- Avoid force pushes to shared branches; rebase only on local branches.
