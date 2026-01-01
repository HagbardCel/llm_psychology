# Console UI Profile Selection Login Plan

## Plan Review (Completeness Check)

This plan is complete for a console-only login selector, but it needs a few clarifications:
- The console should load the selected profile data after login (use `GET /api/user/profile` once the session exists).
- `POST /api/user/login` should return the same response shape as `/api/user/register` so the console can reuse session + workflow handling.
- The profile list endpoint should return a lightweight summary DTO and be ordered by `updated_at` so the newest profiles appear first.
- The console startup flow must move user_id generation into the "Create new profile" path, not before selection.

The detailed steps below include these adjustments.

## Goals

- Add a console startup flow that lets a user pick an existing profile or create a new one.
- Keep backend-driven workflow rules intact (no workflow changes from the console).
- Reuse existing session + workflow APIs by adding a minimal "login existing profile" endpoint.

## Non-Goals

- No password-based auth or token system.
- No web UI changes (console-first only).
- No workflow rule changes or new agent behavior.

## Current Behavior (Baseline)

- Console generates a random `user_id` on startup.
- Console immediately registers a new profile via `POST /api/user/register`.
- WebSocket connects using that new `user_id`.

## Target User Flow (Console)

1. Start console UI.
2. Fetch existing profiles from `GET /api/user/profiles`.
3. Render a numbered list plus a final option:
   - `N+1. Create new profile`
4. User inputs a number.
5. If existing profile chosen:
   - Call `POST /api/user/login` with the selected `user_id`.
   - Store `session_id`, `workflow_next_action`.
   - Call `GET /api/user/profile` to load the profile data.
6. If "Create new profile" chosen:
   - Generate a new UUID user_id.
  - Prompt for required fields (`name`, `primary_language`).
   - Call `POST /api/user/register`.
   - Store `session_id`, `workflow_next_action`.
   - Optionally call `GET /api/user/profile` to confirm the stored profile.
7. Connect WebSocket with the selected `user_id`.
8. Continue existing workflow handling (`/api/user/status`, `/api/workflow/next`, etc).

## Backend Changes

### 1) Data Access

- `src/psychoanalyst_app/services/db/repos/users_repo.py`
  - Add `list_user_profiles(...)` to return profile summaries.
  - SQL: `SELECT user_id, name, status, primary_language, updated_at FROM user_profiles ORDER BY updated_at DESC`.
- `src/psychoanalyst_app/services/trio_db_service.py`
  - Expose `list_user_profiles()` on the service facade.

### 2) DTOs / Schemas

- `src/psychoanalyst_app/models/http_models.py`
  - Add `UserProfileSummaryDTO` with:
    - `user_id`, `name`, `status`, `primary_language`, `updated_at`
  - Add `UserProfileListResponseDTO` with:
    - `profiles: list[UserProfileSummaryDTO]`
  - Add `UserLoginRequestDTO` with:
    - `user_id`

### 3) HTTP API Endpoints

- `src/psychoanalyst_app/api/user_routes.py`
  - `GET /api/user/profiles`
    - No session required.
    - Returns `UserProfileListResponseDTO`.
  - `POST /api/user/login`
    - No session required.
    - Input `UserLoginRequestDTO`.
    - If profile missing: return 404.
    - Create a new session with `orchestrator.start_session(...)`.
    - Return `UserRegisterResponseDTO` (session + workflow_next_action).

### 4) Orchestrator / Workflow

- No workflow changes.
- Ensure `start_session(...)` is called with `send_initial_message=False` to match register behavior.

## Console UI Changes

### 1) Startup Flow Refactor

- `console-ui/main.py`
  - Stop generating `user_id` before selection.
  - Let `ConsoleClient` control user_id creation when needed.

- `console-ui/src/console_client.py`
  - Add `_fetch_profiles()` to call `GET /api/user/profiles`.
  - Add `_select_or_create_profile()`:
    - Render numbered list of existing profiles.
    - Append "Create new profile" as the last option.
    - Accept numeric input only; re-prompt on invalid input.
    - Branch to either `_login_existing_profile(...)` or `_create_new_profile(...)`.
  - Add `_login_existing_profile(user_id)`:
    - Call `POST /api/user/login`.
    - Store `session_id`, `workflow_next_action`, `user_id`.
    - Call `GET /api/user/profile` and store results (at least for logging).
  - Rename `_register_user()` to `_create_new_profile()` and only use for the create-new path.
  - Update `run()` to call `_select_or_create_profile()` before WebSocket connect.

### 2) Output / UX

- If no profiles exist, show a message and default to "Create new profile".
- If profile list call fails, warn the user and default to "Create new profile".
- After profile selection, print the chosen profile name + status before connecting WS.

## Documentation Updates

- `docs/contracts/HTTP_API_CONTRACT.md`
  - Add `UserProfileSummaryDTO`, `UserProfileListResponseDTO`, `UserLoginRequestDTO`.
  - Add endpoint descriptions for `GET /api/user/profiles` and `POST /api/user/login`.
- `docs/user_journey.md`
  - Add a pre-login step in the sequence diagram and "Endpoint Usage by Client".
- `docs/session_lifecycle.md`
  - Clarify that session creation may be triggered by login for existing profiles.

## Tests

### Backend

- Add unit test for list profiles ordering in `tests/unit` (repo-level test).
- Add integration tests:
  - `GET /api/user/profiles` returns profiles ordered by `updated_at DESC`.
  - `POST /api/user/login` returns 404 for unknown user_id.
  - `POST /api/user/login` returns a session for existing user_id.

### Console

- Update `tests/integration/test_console_ui_patient_flow.py`:
  - Seed at least one profile.
  - Confirm list display and numeric selection path.
  - Confirm "Create new profile" still works end-to-end.

## Schema + Type Generation

If DTOs change, run (Docker-only):
- `docker compose run --rm api python scripts/generate_schemas.py`
- `docker compose run --rm api python scripts/validate_schemas.py`
- `docker compose run --rm frontend npm run generate:types`

## Acceptance Criteria

- Console startup shows numbered list of existing profiles plus "Create new profile".
- Selecting an existing profile logs in and loads profile data without re-registering.
- Selecting "Create new profile" creates a new profile and proceeds as before.
- The WebSocket connects using the selected user_id and the workflow continues normally.
- New API endpoints are documented and tested.
