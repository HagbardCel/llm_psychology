# Phase 2 — Configuration Simplification (Local Mode) Implementation Plan

**Source assessment**: `docs/assessments/project/CODEBASE_ASSESSMENT_2025-12-22_LOCAL_LEAN.md` (Phase 2 — Configuration Simplification)  
**Scope**: Backend config + DI, HTTP auth removal, minimal client/contract alignment.  
**Execution constraint**: Docker-only commands (see `AGENTS.md`).  
**Primary goal**: One config source, no auth overhead, keep virtual user IDs for local testing.

---

## Objective

Simplify configuration and runtime behavior by:
- removing module-level configuration usage in favor of container-provided settings,
- removing authentication flows entirely for local usage,
- preserving user_id-based virtual users without tokens.

This phase should **not** change core orchestration logic, workflow state transitions, or WS payload shapes.

---

## Non-goals (Explicitly Out of Scope)

- Refactoring orchestration internals or agent logic (Phase 3).
- WebSocket protocol changes (Phase 1).
- RAG/style pack changes (Phase 4).
- Major UX changes beyond removing auth flows.

---

## Alignment With `docs/design-principles.md`

- **Trio-first** runtime remains unchanged; only config and auth boundaries change.
- **Gateway/orchestration/services layering** remains intact; no cross-layer shortcuts.
- **Contracts** are updated when endpoints change; schemas and types are regenerated.

---

## Phase 2 Scope (What We Touch)

Backend:
- `src/psychoanalyst_app/config.py`
- `src/psychoanalyst_app/server.py`
- `src/psychoanalyst_app/main.py`
- `src/psychoanalyst_app/e2e_server.py`
- `src/psychoanalyst_app/trio_server.py`
- `src/psychoanalyst_app/container/service_container.py`
- `src/psychoanalyst_app/api/*_routes.py`
- `src/psychoanalyst_app/api/auth_middleware.py`
- `src/psychoanalyst_app/api/auth_routes.py`
- `src/psychoanalyst_app/services/auth_service.py`
- `src/psychoanalyst_app/models/auth_models.py`
- `src/psychoanalyst_app/services/db/repos/auth_repo.py`
- `src/psychoanalyst_app/services/migration_service.py`
- `src/psychoanalyst_app/models/http_models.py` (auth DTOs removal)

Docs + Contracts:
- `docs/contracts/HTTP_API_CONTRACT.md`
- `docs/user_journey.md`
- `docs/ARCHITECTURE.md` (if auth is mentioned)

Frontend (minimal cleanup to match auth removal):
- `frontend/src/services/apiClient.ts`
- any auth-specific pages/services if present

---

## Key Decisions (Locked)

### D2.1 Auth removal strategy

**Decision**: remove auth middleware, routes, service, models, DB tables, and config flags entirely.  
Rationale: Local-only usage with virtual users does not need tokens or passwords; removing auth reduces surface area and drift.

### D2.2 Virtual user identity source

**Decision**: standardize on a `user_id` passed explicitly by clients.  
- HTTP: accept `user_id` via query param for GETs and in JSON body for POST/PUT/PATCH.
- WS: keep `user_id` as query parameter (`/ws?user_id=...`).

If any endpoint currently expects a user_id from auth context, update it to use the explicit value.

### D2.3 Settings lifecycle and logging

**Decision**: construct a `Settings` instance at each entry point and pass it through:
- `setup_logging(settings)` (or `setup_logging(settings, ...)`)
- `ServiceContainer(settings)`
- `run_trio_server(config=settings, ...)`

Remove module-level `settings = Settings()` usage from runtime paths.

---

## Implementation Plan

### P2.1 Remove module-level settings usage and standardize entry points

Tasks:
- Replace `from psychoanalyst_app.config import settings` usage in:
  - `src/psychoanalyst_app/server.py`
  - `src/psychoanalyst_app/main.py`
  - `src/psychoanalyst_app/e2e_server.py`
  with explicit `Settings()` instantiation in `main()`.
- Update `setup_logging(...)` to accept a `Settings` instance (or accept explicit values) so it no longer depends on a module-level singleton.
- Update `ServiceContainer` to require a `Settings` argument (no implicit `Settings()` creation).

Acceptance criteria:
- Entry points are the only place that instantiate `Settings()`.
- No runtime module depends on `config.settings` directly.
- `rg "from psychoanalyst_app.config import settings" src` returns zero matches.

---

### P2.2 Remove authentication plumbing

Tasks:
- Remove `AuthService` usage and registration from `ServiceContainer`.
- Remove `auth_middleware` and `auth_routes` registration from `TrioServer`.
- Delete or deprecate:
  - `src/psychoanalyst_app/api/auth_middleware.py`
  - `src/psychoanalyst_app/api/auth_routes.py`
  - `src/psychoanalyst_app/services/auth_service.py`
  - `src/psychoanalyst_app/models/auth_models.py`
  - `src/psychoanalyst_app/services/db/repos/auth_repo.py`
- Update `src/psychoanalyst_app/models/http_models.py` to remove auth DTOs.
- Remove auth config fields from `Settings` in `src/psychoanalyst_app/config.py`.

Acceptance criteria:
- No auth endpoints or auth middleware remain in the HTTP server setup.
- `rg "auth_" src` only finds references in historical docs/tests (or zero after cleanup).
- `Settings` contains no JWT or auth-related fields.

---

### P2.3 Update HTTP routes to use explicit user_id

Tasks:
- Remove `require_auth` decorators from HTTP routes.
- Introduce a helper for consistent user_id retrieval (query param for GETs, body for mutating endpoints). Keep validation error messages consistent.
- Ensure all user/session/therapy/workflow endpoints derive user_id via this helper and do not depend on auth context.

Acceptance criteria:
- All user-specific endpoints work with explicit user_id and do not require `Authorization` headers.
- Error responses are consistent when user_id is missing.

---

### P2.4 Database migration alignment

Tasks:
- Remove auth table migration(s) from `MigrationService`.
- Document the expectation that local development can delete the SQLite DB if needed (no explicit migration required).

Acceptance criteria:
- New DBs do not create auth tables.
- Legacy auth tables are acceptable to drop by recreating the local DB.

---

### P2.5 Contract + docs updates

Tasks:
- Remove auth endpoints from `docs/contracts/HTTP_API_CONTRACT.md`.
- Update affected endpoint descriptions to remove auth requirements.
- Update `docs/user_journey.md` to reflect no login flow.
- Update any other docs that mention tokens/auth.

Acceptance criteria:
- Contract docs match the new public endpoints and request shapes.
- Docs contain no references to JWT or login.

---

### P2.6 Frontend alignment (minimal)

Tasks:
- Remove auth token storage, login/logout flows, and auth API calls if present.
- Ensure `apiClient` does not add `Authorization` headers.
- Generate/persist a `user_id` client-side (localStorage) and pass it on requests consistently.

Acceptance criteria:
- Frontend can perform core flows without any auth UI or token storage.
- All API requests include user_id in the expected location.

---

## Testing (Docker-only)

- Backend unit smoke: `docker compose run --rm api pytest tests/unit/test_trio_server.py`
- Orchestration integration: `docker compose run --rm api pytest tests/integration/test_trio_orchestration.py`
- HTTP contract sanity (if tests exist): `docker compose run --rm api pytest tests/integration/test_http_contract.py`
- Frontend lint: `docker compose run --rm frontend npm run lint`

---

## Acceptance Summary (Phase 2 Done When...)

- There is one explicit settings instance per entry point, passed through DI.
- Authentication code paths are removed from backend and docs.
- All user-specific endpoints accept explicit user_id and work without tokens.
- Contract docs and frontend behavior match the new unauthenticated flow.

---

## Open Questions

Resolved:
- Use a single helper (e.g., `get_user_id(request)`) in `api/` to centralize user_id extraction for less duplication and easier maintenance.
- No explicit migration needed; drop auth tables by recreating the local DB when necessary.
