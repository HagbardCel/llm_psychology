# Codex Agent Guide

## Project Structure
- `src/`: Core Python app (agents, orchestration, services, models, styles, server).
- `frontend/`: React + TypeScript UI (Vite, MUI).
- `console-ui/`: Terminal WebSocket client.
- `tests/`: Pytest unit/integration suites.
- `data/`: SQLite DBs, vector DBs, domain knowledge.
- `schemas/` and `migrations/`: JSON schema outputs and DB migrations.
- `docs/`: Architecture, guides, reference material.

## Documentation Map (Read First)
- `docs/README.md`: Doc index and pointers to deeper references.
- `docs/design-principles.md`: Non-negotiable architecture rules, layering, and workflow invariants.
- `docs/ARCHITECTURE.md`: System overview, orchestration flow, and component responsibilities.
- `docs/user_journey.md`: Expected user flow and endpoint usage by client.
- `docs/session_lifecycle.md`: Session orchestration details and state transitions.

## Contracts and Data Models (Source of Truth)
- `docs/contracts/HTTP_API_CONTRACT.md`: HTTP endpoints, DTO shapes, and error format.
- `docs/WEBSOCKET_PROTOCOL.md`: WebSocket message envelope and event contract.
- `docs/data-models.md`: Domain model inventory and DTO mappings.
- `docs/TYPE_SYSTEM.md`: Schema and frontend type generation pipeline.

## Key Entry Points (Code)
- `src/psychoanalyst_app/trio_server.py`: Server composition, HTTP routing, WS registration.
- `src/psychoanalyst_app/api/*_routes.py`: HTTP endpoints by domain.
- `src/psychoanalyst_app/api/ws_handler.py`: WebSocket handler and message routing.
- `src/psychoanalyst_app/orchestration/`: Workflow engine, orchestrator, conversation manager.
- `frontend/src/services/apiClient.ts`: Web HTTP client.
- `frontend/src/services/websocketService.ts`: Web WS client.
- `console-ui/src/console_client.py`: Console UI client behavior.

## Docker-Only Command Execution
Run all commands inside containers. Do not run Python or Node on the host.

- Build images: `make dev-install`
- Start services: `make docker-up` (or `make ui-web` / `make ui-console`)
- Backend shell: `make docker-shell`
- One-off backend command: `docker compose run --rm api <command>`
- One-off frontend command: `docker compose run --rm frontend <command>`
- Usertest config: `ENV_FILE=.env.usertest docker compose up api frontend`

### Common Runtime Commands (Containerized)
- Server: `docker compose up --build api`
- Standalone CLI: `docker compose run --rm api python -m psychoanalyst_app`
- Console UI: `make ui-console`
- Web UI: `make ui-web`

## Tests (Docker-Only)
- Backend full suite: `make test-validate` or `make docker-test`
- Backend single test: `make docker-test-one TEST=tests/unit/test_file.py`
- Frontend unit tests: `make docker-test-frontend`
- Frontend lint: `docker compose run --rm frontend npm run lint`
- E2E tests: `docker compose run --rm frontend npx playwright install --with-deps` (once),
  then `docker compose run --rm frontend npm run test:e2e`

## Core Developer Guidance
- Trio is the async runtime; do not introduce asyncio.
- Keep agents as pure business logic; orchestration owns workflow transitions.
- Prefer existing utilities and services before adding new ones (see `docs/design-principles.md`).
- If docs conflict with this guide, follow this guide and update the docs you touched.
- If you change HTTP/WS contracts or API-facing models, update the contract docs and regenerate schemas/types.
- When models change, regenerate schemas and frontend types.
- Add tests for new behavior; keep deterministic tests in the default suite.

## Schema and Type Generation (Containerized)
- Generate JSON schemas: `docker compose run --rm api python scripts/generate_schemas.py`
- Validate schemas: `docker compose run --rm api python scripts/validate_schemas.py`
- Generate frontend types: `docker compose run --rm frontend npm run generate:types`

## Version Control Guidelines
- Branch from `main` using `feat/<topic>` or `fix/<topic>`.
- Keep commits small and scoped; use conventional prefixes (`feat:`, `fix:`, `docs:`).
- Run Docker-based tests before committing.
- Avoid force pushes to shared branches; rebase only on local branches.
- PRs should include a clear description, testing notes, and screenshots for UI changes.
