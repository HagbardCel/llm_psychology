# Phase 1 — Contract Stabilization (Detailed Implementation Plan)

Source: `docs/assessments/project/CODEBASE_ASSESSMENT_2025-12-16.md` (Phase 1 — Contract Stabilization)

## Objective

Make the backend HTTP API and all clients (web frontend, console UI, tests/E2E) agree on request/response shapes, status codes, and field naming so that:
- generated TypeScript types represent the *actual* wire contract, and
- the UI no longer depends on placeholders or ad-hoc response bodies.

This must hold across all frontends/clients in the repo (web frontend, console UI, and any other clients that call HTTP endpoints).

## Non-goals (Phase 1)

- Refactor workflow routing / “backend-driven navigation” behavior (Phase 2).
- DI cleanup, agent factory consolidation, true streaming, or module splits (Phases 3+).
- Hardening/security beyond what’s necessary to stabilize the contract.

## Phase 1 Scope (Contract Surfaces)

**Backend**
- HTTP endpoints (used by one or more clients):
  - `src/trio_server.py`:
    - `GET /health`
    - `GET /api/user/profile`
    - `POST /api/user/profile`
    - `GET /api/user/status`
    - `GET /api/sessions`
    - `GET /api/sessions/<session_id>`
    - `POST /api/sessions`
    - `GET /api/sessions/<session_id>/timer`
    - `GET /api/therapy/plan`
    - `POST /api/therapy/plan`
  - `src/api/version_routes.py`:
    - `GET /api/version`
    - `POST /api/version/check`
  - `src/api/auth_routes.py`:
    - `POST /api/auth/register`
    - `POST /api/auth/login`
    - `GET /api/auth/me`
    - `POST /api/auth/logout`
  - Additional endpoints used by non-web clients (must remain compatible):
    - The endpoints listed above (version/auth/timer) are part of “Phase 1 compatibility” even if the web frontend does not call them.
- API DTO definitions (new module; see below)
- Schema generation pipeline: `scripts/generate_schemas.py` → `schemas/*.json`
- Backend tests covering HTTP contract

**Clients**
- Web frontend:
  - Type generation: `frontend/scripts/generate-types.js` → `frontend/src/types/generated/api.ts`
  - API bindings: `frontend/src/services/api.ts` and hooks/components using sessions/plan/profile data
- Console UI:
  - Auth + version negotiation: `console-ui/src/auth.py`, `console-ui/src/version_check.py`
  - Session timer polling: `console-ui/src/console_client.py`

**Out of scope but must not regress**
- WebSocket protocol surface (shared by console UI and web frontend): `docs/WEBSOCKET_PROTOCOL.md` and `tests/integration/test_websocket_protocol_contract.py`

## Key Decisions (Lock These First)

### D1) Field naming: snake_case end-to-end

**Decision (locked)**: Use `snake_case` keys end-to-end for the HTTP contract (`user_id`, `session_id`, `plan_id`, `created_at`, …).

**Frontend implication**: Remove quicktype `--nice-property-names` so generated TS preserves JSON keys (and delete/avoid `userid`/`sessionid`/`planid` mapping layers).

**Consequence**: Frontend code treats API DTOs as snake_case; camelCase is reserved for *pure client/UI state* only.

### D2) Date/time representation on the wire

**Decision (locked)**: The HTTP wire contract uses ISO 8601 strings for all datetimes, and frontend types keep them as `string` (no `Date` inference, no runtime decoding).

**Frontend implication**: Add quicktype `--no-date-times` so generated TS uses `string` for `date-time` fields.

## Contract Matrix (Authoritative)

The authoritative contract spec lives in `docs/contracts/HTTP_API_CONTRACT.md` and should be kept up to date as implementation proceeds.

Phase 1 should still use this quick matrix as a checklist for the endpoints most affected by the “DTO + schema + typegen” work:

| Endpoint | Request | Success response | Errors |
|---|---|---|---|
| `GET /api/user/profile?user_id=...` | query: `user_id` | `200 UserProfileDTO` | `400 {error}` (missing), `404 {error}` (not found) |
| `POST /api/user/profile` | `CreateUserProfileRequestDTO` | `201 UserProfileDTO` | `400 {error}` |
| `GET /api/user/status?user_id=...` | query: `user_id` | `200 UserStatusDTO` (or existing shape, but stable) | `400 {error}`, `404 {error}` |
| `GET /api/sessions?user_id=...` | query: `user_id` | `200 SessionDTO[]` | `400 {error}` |
| `GET /api/sessions/<id>` | n/a | `200 SessionDTO` | `404 {error}` |
| `POST /api/sessions` | `CreateSessionRequestDTO` | `201 SessionDTO` | `400 {error}`, `404 {error}` |
| `GET /api/therapy/plan?user_id=...` | query: `user_id` | `200 TherapyPlanDTO \| null` | `400 {error}` |
| `POST /api/therapy/plan` | `CreateTherapyPlanRequestDTO` | `201 TherapyPlanDTO` | `400 {error}`, `404 {error}` |

Notes:
- Align `POST /api/sessions` with `GET /api/sessions/<id>`: returning an ad-hoc “created” object breaks contract reuse.
- Fix placeholders:
  - `src/trio_server.py:_get_therapy_plan` currently returns a “not implemented” message.
  - `src/trio_server.py:_create_therapy_plan` currently returns a `UserProfile` while the frontend expects a `TherapyPlan`.

## Backend Work Plan

### B1) Introduce explicit HTTP DTOs (stop returning internal models directly)

Create a new module, e.g. `src/models/http_models.py`, containing *API-facing* DTOs:
- `UserProfileDTO`
- `SessionDTO` (+ nested `MessageDTO`, `TopicDTO` as needed)
- `TherapyPlanDTO`
- Request DTOs (to validate incoming payloads):
  - `CreateUserProfileRequestDTO`
  - `CreateSessionRequestDTO`
  - `CreateTherapyPlanRequestDTO`

Rules:
- DTOs must be stable and reflect what the frontend needs (avoid dumping DB-only/internal fields).
- Use Pydantic serialization intended for JSON (`model_dump(mode="json")`) consistently.

Deliverables:
- DTO module implemented and imported by the server routes.
- DTOs added to schema generation (see B3) so TS generation follows.

### B2) Make HTTP endpoints return DTOs consistently

Update `src/trio_server.py`:

Sessions
- `GET /api/sessions` returns `SessionDTO[]` serialized in JSON mode.
- `GET /api/sessions/<id>` returns `SessionDTO` in JSON mode.
- `POST /api/sessions` returns the *created* `SessionDTO` (not a custom `{status:"created"}` payload).
  - Implementation approach: after `orchestrator.start_session(...)`, load the newly created session via `db_service.get_session(session_id)` and return it.

Therapy plan
- `GET /api/therapy/plan` implemented using `db_service.get_latest_therapy_plan(user_id)` (or equivalent).
- `POST /api/therapy/plan` returns `TherapyPlanDTO` (not `UserProfile`).

User profile/status
- Ensure profile responses are stable DTOs and use JSON mode.
- Ensure `GET /api/user/status` has a stable response shape (either DTO or a clearly defined JSON object) and is covered by contract tests.

Deliverables:
- No placeholder responses consumed by the frontend.
- All date/time fields serialize as ISO strings.
- Errors are consistent: `{ "error": "<message>" }` with appropriate status codes.

### B3) Align schema generation with DTOs

Update `scripts/generate_schemas.py` to generate schemas for the *HTTP DTOs* rather than internal storage models.

Concrete tasks:
- Add the new DTO models to the `pydantic_models` list.
- Include request/response models used by other clients (even if the web frontend does not currently call them), e.g.:
  - `src/models/version_models.py` (`VersionInfo`, `VersionCheckRequest`, `VersionCheckResponse`)
  - `src/models/auth_models.py` (`LoginRequest`, `RegisterRequest`, `LoginResponse`)
- Decide whether to keep internal models in schemas:
  - Option A (recommended): schemas are *API-only*; internal models are not exported.
  - Option B: keep both, but ensure frontend generation only includes the API DTO schema files.
- Regenerate committed `schemas/*.json` and update `tests/unit/test_schema_generation.py` expectations accordingly.

Deliverables:
- `schemas/*.json` represent the HTTP contract, not DB internals.
- `tests/unit/test_schema_generation.py` continues to enforce “committed schemas are up-to-date”.

### B4) Add/adjust backend contract tests for HTTP endpoints

Update existing tests and add missing ones:
- Update `tests/integration/test_trio_flow.py` session creation assertions to match `SessionDTO`.
- Add tests for:
  - `GET /api/sessions` returns list with expected keys and ISO datetime strings.
  - `GET /api/therapy/plan` returns the latest plan (and the chosen “no plan” behavior: `null` vs `404`).
  - `POST /api/therapy/plan` returns `TherapyPlanDTO` and persists to DB.
- Consider adding a “minimal contract” test that asserts *field naming* (snake_case) for key DTOs.

Deliverables:
- Integration tests cover all endpoints in the contract matrix.
- Contract tests fail on drift (shape changes) rather than downstream UI failures.

## Client Work Plan

Phase 1 changes must be rolled out without breaking the console UI.

### Web frontend (typegen + UI)

#### F1) Update type generation to stop renaming fields

Update `frontend/scripts/generate-types.js`:
- Remove `--nice-property-names`.
- Add `--no-date-times` so `date-time` fields remain `string`.

Deliverables:
- `frontend/src/types/generated/api.ts` uses snake_case keys matching backend JSON.
- Generated types are used directly by API calls and hooks (no “userid → id” mapping required).

#### F2) Remove/replace the compatibility layer

- Delete or deprecate:
  - `frontend/src/types/converters.ts`
  - `frontend/src/types/index.ts` mappings that reference `userid`, `sessionid`, `planid`
- Replace with:
  - Direct imports from `frontend/src/types/generated/api.ts` for API DTOs
  - Separate “UI-only” types if needed (e.g., `LocalStorageData`, view models)

Deliverables:
- Frontend types are simpler: API DTOs stay API-shaped; UI state is separate.

#### F3) Update API bindings and usage sites to match DTOs

Update `frontend/src/services/api.ts`:
- Ensure `createSession()` return type matches the new `SessionDTO`.
- Ensure `getPlan()` and `createPlan()` match `TherapyPlanDTO` and handle “no plan” semantics consistently.

Update the UI pages/hook usage involved in Phase 1 exit criteria:
- Dashboard/History/Session detail: session timestamp + transcript fields render correctly.
- Plan creation flow: `POST /api/therapy/plan` result is used correctly (and no longer expects a profile object).

Deliverables:
- “Integration drift” issues are eliminated for these pages without custom mappings.

### Console UI (compatibility)

Phase 1 should not require console UI code changes, but it must remain compatible with the updated backend.

Deliverables:
- `console-ui/src/version_check.py` works against the updated backend (`GET /api/version`, `POST /api/version/check`).
- `console-ui/src/auth.py` works against the updated backend (`/api/auth/register`, `/api/auth/login`, `/api/auth/me`).
- `console-ui/src/console_client.py` timer polling remains compatible (`GET /api/sessions/<session_id>/timer`).

## Recommended PR Breakdown (Minimize Rework)

1) **PR 1 — Lock the contract**
   - Keep `docs/contracts/HTTP_API_CONTRACT.md` authoritative and update it as Phase 1 implementation proceeds.
   - Apply the locked D1/D2 decisions in schema + type generation.

2) **PR 2 — Backend DTOs + endpoint fixes (server + tests)**
   - Add `src/models/http_models.py` DTOs.
   - Implement `GET /api/therapy/plan` and fix `POST /api/therapy/plan` response type.
   - Make sessions endpoints return DTOs in JSON mode.
   - Update/add integration tests for these endpoints.

3) **PR 3 — Schema pipeline aligns to DTOs**
   - Update `scripts/generate_schemas.py` to output DTO schemas.
   - Regenerate committed `schemas/*.json`.
   - Update schema generation tests.

4) **PR 4 — Frontend typegen + UI alignment**
   - Update `frontend/scripts/generate-types.js` (remove `--nice-property-names`; add `--no-date-times`).
   - Regenerate `frontend/src/types/generated/api.ts`.
   - Remove converters layer and update API bindings + affected components.

## Validation Checklist (Phase 1 Exit Criteria)

Backend
- `GET /api/therapy/plan` is implemented and used; no placeholder endpoint responses are required by the UI.
- `POST /api/therapy/plan` returns a therapy plan DTO (and persists it).
- Session endpoints return consistent DTO shapes and serialize datetimes predictably.
- `GET /api/version` + `POST /api/version/check` continue to work without auth.
- Auth endpoints used by console remain compatible (`/api/auth/register`, `/api/auth/login`, `/api/auth/me`).
- `GET /api/sessions/<session_id>/timer` response shape remains compatible with the console UI.

Frontend
- Dashboard, History, Session detail show correct session dates and transcripts.
- No dependency on `userid`/`sessionid`/`planid` renaming hacks.

Tests
- Backend integration tests cover the contract matrix endpoints.
- Schema generation tests pass and prevent committed-schema drift.
- Console compatibility tests still pass:
  - `tests/integration/test_version_endpoints.py`
  - `tests/integration/test_console_client_auth.py`
  - `tests/integration/test_session_timer_endpoint.py`
  - `tests/integration/test_websocket_protocol_contract.py`

## Risks & Mitigations

- **Large diff due to typegen change**: Do typegen changes in a dedicated PR and keep it mechanical.
- **Datetime mismatch (`Date` vs string)**: Decide D2 up front; add one “datetime sanity” test for each DTO response.
- **Schema churn breaks CI type-safety workflow**: Land schema changes and frontend typegen updates together (or temporarily allow both schema sets until the transition is complete).
