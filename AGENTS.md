# Codex Agent Guide

## Project Structure
- `src/`: Core Python app (agents, orchestration, services, models, styles, server).
- `console-ui/`: Supported terminal HTTP/WebSocket client and workflow probes.
- `tests/`: Pytest unit/integration suites.
- `data/`: SQLite DBs, vector DBs, domain knowledge.
- `schemas/` and `migrations/`: JSON schema outputs and DB migrations.
- `docs/`: Architecture, guides, reference material.

## Documentation Map (Read First)
- `docs/README.md`: Doc index and pointers to deeper references.
- `docs/ui-scope.md`: Active frontend policy.
- `docs/design-principles.md`: Non-negotiable architecture rules, layering, and workflow invariants.
- `docs/ARCHITECTURE.md`: System overview, orchestration flow, and component responsibilities.
- `docs/user_journey.md`: Expected user flow and endpoint usage.
- `docs/session_lifecycle.md`: Session orchestration details and state transitions.

## Contracts and Data Models (Source of Truth)
- `docs/contracts/HTTP_API_CONTRACT.md`: HTTP endpoints, DTO shapes, and error format.
- `docs/WEBSOCKET_PROTOCOL.md`: WebSocket message envelope and event contract.
- `docs/data-models.md`: Domain model inventory and DTO mappings.
- `docs/TYPE_SYSTEM.md`: Backend schema and protocol-generation pipeline.

## Key Entry Points (Code)
- `src/psychoanalyst_app/trio_server.py`: Server composition, HTTP routing, WS registration.
- `src/psychoanalyst_app/api/*_routes.py`: HTTP endpoints by domain.
- `src/psychoanalyst_app/api/ws_handler.py`: WebSocket handler and message routing.
- `src/psychoanalyst_app/orchestration/`: Workflow engine, orchestrator, conversation manager.
- `console-ui/src/console_client.py`: Supported frontend behavior.
- `console-ui/src/workflow_probe/`: Full-stack workflow probes.

## Docker-Only Command Execution
Run all commands inside containers. Do not run Python or Node on the host.

- Build images: `make dev-install`
- Start backend: `make docker-up`
- Backend shell: `make docker-shell`
- One-off backend command: `docker compose run --rm api <command>`
- Supported frontend: `make ui-console`
- Manual cloud usertest: `make ui-console-test`

## Tests (Docker-Only)
- Backend full suite: `make test-validate` or `make docker-test`
- Backend single test: `make docker-test-one TEST=tests/unit/test_file.py`
- Deterministic full-stack probe: `make probe-console-deterministic`
- Release-candidate validation: `make finalization-check`

## Core Developer Guidance
- Trio is the async runtime; do not introduce asyncio.
- Keep agents as pure business logic; orchestration owns workflow transitions.
- Prefer existing utilities and services before adding new ones.
- If docs conflict with this guide, follow this guide and update the docs you touched.
- If HTTP/WS contracts or API-facing models change, update contract docs and regenerate schemas/protocol constants.
- Add deterministic tests for new behavior.

## Active Scope
Until foundation stabilization is complete, treat the backend, workflow engine, persistence model, API DTOs, WebSocket protocol, schema generation, LLM abstraction, deterministic tests, and workflow probes as the main product.

- Maintain `console-ui` as the only supported frontend.
- Do not recreate, repair, test, or optimize removed frontends unless explicitly requested.
- Do not add multi-frontend orchestration modes.
- Prefer backend, protocol, workflow-probe, and console-client tests.

## Foundation Failure Policy
During foundation stabilization, do not hide workflow, LLM, persistence, protocol, or contract failures behind fallback behavior unless explicitly requested.

- Prefer fail-fast, diagnostic errors with preserved workflow state and deterministic tests.
- Treat fallbacks as product decisions; document and test them when they are intentionally added.
- Workflow probes may improve artifact generation and observability, but must not convert real backend failures into passes.
- For LLM structured-output failures, preserve enough bounded diagnostic context to identify the phase, schema, provider, model, and parse failure without leaking full prompts or transcripts by default.

## Schema and Protocol Generation (Containerized)
- Generate JSON schemas: `make generate-schemas`
- Validate generated schemas: `make validate-schemas`
- Generate WS constants: `make generate-ws-protocol`
- Validate committed WS constants: `make validate-generated-contracts`

## Version Control Guidelines
- Branch from `main` using `feat/<topic>` or `fix/<topic>`.
- Keep commits small and scoped; use conventional prefixes (`feat:`, `fix:`, `docs:`).
- Run Docker-based tests before committing.
- Avoid force pushes to shared branches; rebase only on local branches.
