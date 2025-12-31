# Workflow Gaps Remediation Implementation Plan

## Objective
Close the remaining gaps in the backend-driven, session-bound workflow by:
- Enforcing session_id on all post user_id interactions (including `/api/workflow/next`).
- Moving workflow transitions fully into the orchestrator.
- Ensuring therapy plan updates are emitted by the reflection agent and persisted by the orchestrator.
- Skipping agent greetings when the workflow is in a `wait` state, while still notifying the user.

## Decisions (Confirmed)
1) All post user_id interactions must include `session_id`, including `GET /api/workflow/next`.
2) The reflection agent provides plan updates; the orchestrator saves them.
3) Greetings are skipped if the workflow action is `wait`; a brief status notice must still be sent.
4) WebSocket message flows use implicit session binding (no `session_id` in WS payloads).
5) `/api/therapy/styles` is treated as a post user_id endpoint and requires `session_id`.

## Scope
- Backend: orchestration, HTTP/WS contracts, session enforcement, workflow transitions.
- Frontend + console UI: session_id propagation and wait-state behavior.
- Schemas/types, tests, and documentation.

## Non-Goals
- New auth/login flows.
- Database schema changes unless required for state tracking.
- Large redesigns of UI flows.

## Pre-Work Checklist
- Read `docs/design-principles.md` and `docs/contracts/HTTP_API_CONTRACT.md`.
- Review current workflow helpers:
  - `src/psychoanalyst_app/api/workflow_routes.py`
  - `src/psychoanalyst_app/api/ws_handler.py`
  - `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`
  - `src/psychoanalyst_app/orchestration/process_messages.py`
- Confirm Docker-only command usage (no host Python/Node).

---

## Phase 1: Contract + DTO Updates (Session-Bound Everywhere)

### 1.1 Add session_id to workflow next action request
Goal: `GET /api/workflow/next` requires `session_id`.

Steps:
1) Add a request DTO for workflow-next query parameters.
   - File: `src/psychoanalyst_app/models/http_models.py`
   - Create `WorkflowNextActionRequestDTO` with:
     - `user_id: str`
     - `session_id: str`
   - Use `Field(..., min_length=1)` for both.
2) Update `workflow_routes.get_next_action` to parse and validate `session_id`.
   - File: `src/psychoanalyst_app/api/workflow_routes.py`
   - Read `user_id` and `session_id` from query parameters.
   - Validate that session is active and belongs to user (reuse `_validate_session`).
   - If invalid/missing, return 400.
3) Update `docs/contracts/HTTP_API_CONTRACT.md`:
   - Document `session_id` as required query param for `GET /api/workflow/next`.
   - Add `WorkflowNextActionRequestDTO` section (or document query explicitly).
4) Update `schemas/` generation:
   - File: `src/psychoanalyst_app/schemas/generate_schemas.py`
   - Add `WorkflowNextActionRequestDTO` to schema list.
5) Regenerate schemas and frontend types (Docker commands).

Acceptance:
- Missing or invalid `session_id` returns 400.
- Valid requests return `WorkflowNextActionDTO`.

### 1.2 Enforce session_id on post user_id endpoints
Goal: all endpoints used after user_id selection require `session_id` (except session creation/WS connect).

Steps:
1) Inventory endpoints used after user_id selection (from `docs/user_journey.md` and frontend usage):
   - `/api/user/status` (GET)
   - `/api/user/profile` (GET, PATCH, PUT)
   - `/api/workflow/next` (GET)
   - `/api/workflow/complete_profile` (POST)
   - `/api/workflow/select_therapy_style` (POST)
   - `/api/sessions` (GET)
   - `/api/sessions/<id>` (GET)
   - `/api/sessions/<id>/timer` (GET)
   - `/api/therapy/plan` (GET)
   - `/api/therapy/styles` (GET) (optional, but include if called after session is active)
2) Define allowed exceptions:
   - `POST /api/sessions` (creates session_id).
   - `WS /ws?user_id=...` (creates session_id).
3) Add a shared validation helper for session_id:
   - File: `src/psychoanalyst_app/api/request_utils.py`
   - Add `require_session_id()` to read from query or JSON (depending on endpoint).
   - Add `validate_session_for_user(server, user_id, session_id)` or reuse `_validate_session` in each route.
4) Apply validation in each endpoint:
   - Files: `src/psychoanalyst_app/api/user_routes.py`, `src/psychoanalyst_app/api/session_routes.py`, `src/psychoanalyst_app/api/therapy_routes.py`, `src/psychoanalyst_app/api/workflow_routes.py`.
   - For GET endpoints, read `session_id` from query params.
   - For PATCH/PUT/POST, read from JSON payload.
   - Return 400 on missing/invalid session_id.
5) Update docs:
   - `docs/contracts/HTTP_API_CONTRACT.md` for each endpoint.
   - `docs/user_journey.md` to note session_id requirement.
   - `docs/QUICKSTART.md` examples to include `session_id`.

Acceptance:
- Every post user_id endpoint rejects missing/invalid session_id.
- Session creation endpoints remain usable without session_id.

---

## Phase 2: Orchestrator-Owned Transitions (No Agent-Driven State Changes)

### 2.1 Introduce explicit workflow events from agents
Goal: agents signal intent; orchestrator decides transitions.

Steps:
1) Extend `AgentResponse` to carry a workflow event (not a state).
   - File: `src/psychoanalyst_app/orchestration/models.py`
   - Add `workflow_event: WorkflowEvent | None = None`
   - Keep `next_state` temporarily for compatibility, but mark as deprecated in comments.
2) Update `direct_agent_response` helper to accept `workflow_event`.
3) Update agents to set `workflow_event` instead of `next_state`:
   - Intake agent:
     - When name collected: `WorkflowEvent.START_INTAKE`
     - When intake completed: `WorkflowEvent.COMPLETE_INTAKE`
     - File: `src/psychoanalyst_app/agents/trio_intake_agent.py`
   - Assessment agent:
     - No direct transitions; keep `workflow_event = None`.
   - Other agents:
     - Remove `next_state` usage unless they are truly workflow events.
4) Update `finalize_agent_response`:
   - File: `src/psychoanalyst_app/orchestration/process_messages.py`
   - Remove reliance on `agent_response.next_state`.
   - Use `agent_response.workflow_event` for gating only (no transition here).

Acceptance:
- Agents no longer set `next_state`.
- All workflow changes are driven by orchestrator logic.

### 2.2 Centralize transitions in the orchestrator
Goal: orchestrator performs transitions using workflow events + gating rules.

Steps:
1) Update `AgentResponseHandler.handle`:
   - File: `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`
   - If `agent_response.workflow_event` is set:
     - Load current state.
     - Apply gating rules before transition (profile completeness, allowed state).
     - Compute next state with `workflow_engine.get_next_state(...)`.
     - Call `workflow_engine.transition(...)`.
     - Emit `workflow_next_action` afterward.
2) Replace `next_state` transitions:
   - Remove the block that transitions on `agent_response.next_state`.
3) Gating rules to implement:
   - START_INTAKE only allowed if profile is complete (`is_profile_complete`).
   - COMPLETE_INTAKE allowed only if intake completion criteria met (from agent metadata if needed).
4) Ensure assessment job starts only when the workflow transitions to `INTAKE_COMPLETE`:
   - Move `_run_assessment_job` kickoff to the new event handler.
   - Avoid transitioning to `INTAKE_COMPLETE` in `end_session` unless an event triggers it.

Acceptance:
- No transitions happen directly from agent `next_state`.
- Intake completion triggers assessment job via orchestrator.

### 2.3 Enforce profile completeness before auto-session transitions
Goal: prevent auto-session creation from advancing workflow when profile is incomplete.

Steps:
1) Add a profile-completeness guard in session creation:
   - File: `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`
   - In `SessionLifecycleManager.start_session`, before transitioning to
     `INTAKE_IN_PROGRESS`, load the user profile and verify `is_profile_complete`.
   - If incomplete, do not transition; keep state as `NEW` and return session info
     without changing workflow state.
2) Ensure `resolve_next_action` returns `complete_profile` for incomplete profiles
   (already true); verify WS connect uses that action to drive UI.
3) Add unit test coverage:
   - File: `tests/unit/test_workflow_next_action.py`
   - Add a test that `NEW` + incomplete profile does not transition on session start.

Acceptance:
- Auto-session creation never advances workflow when profile is incomplete.
- `complete_profile` remains the required action until profile completion occurs.

---

## Phase 3: Therapy Plan Persistence Rules

### 3.1 Remove generic plan persistence from agent responses
Goal: only orchestrator saves therapy plan updates.

Steps:
1) Remove plan persistence from `finalize_agent_response`:
   - File: `src/psychoanalyst_app/orchestration/process_messages.py`
   - Delete the block that saves `therapy_plan` outputs.
2) Verify that reflection-driven plan updates remain persisted:
   - File: `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`
   - `run_reflection` already persists `therapy_plan_output`.
3) Update the reflection agent contract:
   - Ensure reflection agent returns plan updates in `metadata["therapy_plan_output"]`.
   - Confirm orchestrator handles `plan_update_applied` flag correctly.

Acceptance:
- Only reflection (or explicit workflow endpoints) results in plan persistence.
- No other agent path writes therapy plans.

### 3.2 Ensure plan creation only happens via workflow endpoint
Goal: `/api/workflow/select_therapy_style` is the only plan creation path.

Steps:
1) Confirm `create_therapy_plan` is only called from `workflow_routes`.
2) Remove any remaining plan creation from agents or orchestration helpers.
3) Update docs to reflect this rule.

Acceptance:
- All plan creation flows go through workflow endpoint.

### 3.3 Remove agent-side profile persistence
Goal: ensure agents emit structured outputs only; persistence stays in orchestrator/services.

Steps:
1) Identify all direct DB writes in agents:
   - File: `src/psychoanalyst_app/agents/reflection/helpers.py`
   - Confirm no other agents write via `db_service.update_*`.
2) Replace direct profile updates with structured payloads:
   - Emit a `StructuredUserProfileOutput` in reflection agent metadata.
   - Persist via `finalize_agent_response` (or a new orchestrator-owned persistence step).
3) Update tests to assert profile updates are persisted by orchestrator, not agents.

Acceptance:
- Agents no longer call `db_service.update_user_profile(...)`.
- Profile updates happen via orchestrator persistence only.

---

## Phase 4: Wait-State Greetings and Status Notice

### 4.1 Skip greetings when required_action is `wait`
Goal: prevent auto greetings during wait states; still notify user.

Steps:
1) Adjust WS connection flow:
   - File: `src/psychoanalyst_app/api/ws_handler.py`
   - Do NOT call `ensure_session_for_user(..., send_initial_message=True)` unconditionally.
   - Create session first without greeting.
   - Compute `WorkflowNextActionDTO`.
   - If `required_action == "wait"`, skip greeting.
   - If not wait, trigger a greeting explicitly (see step 2).
2) Add a method to trigger greetings after session start:
   - File: `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`
   - Add a `send_initial_greeting(session_id)` method in `SessionLifecycleManager`.
   - Call this method from the WS handler when needed.
3) Status notification:
   - Use the `workflow_next_action` prompt as the status notice.
   - Ensure both web and console UIs display the prompt when `required_action == "wait"`.

Acceptance:
- No initial greeting is streamed while required_action is `wait`.
- Users still see a short status prompt immediately.

### 4.2 Display wait-status prompts in active session views
Goal: ensure the “brief status notification” is visible even on the therapy session screen.

Steps:
1) Add a lightweight banner for wait prompts in the therapy session UI:
   - File: `frontend/src/components/TherapySession.tsx`
   - Subscribe to `workflow_next_action` from `WebSocketContext`.
   - If `required_action == "wait"`, render a small alert/banner above the transcript.
2) Confirm the dashboard and assessment pages already display wait prompts
   (keep current behavior).
3) Add a small UI test or snapshot update to confirm the banner appears.

Acceptance:
- When `required_action == "wait"`, a status notice is visible in TherapySession.

---

## Phase 5: Frontend + Console UI Updates

### 5.1 Frontend: include session_id everywhere
Steps:
1) Ensure session_id is captured on `session_started`.
   - File: `frontend/src/contexts/WebSocketContext.tsx`
2) Update API calls to include session_id:
   - `useWorkflowNextAction`: add `session_id` query param.
     - File: `frontend/src/hooks/useWorkflowNavigation.ts`
   - Profile requests (GET/PATCH) include `session_id`.
     - File: `frontend/src/hooks/useUserProfile.ts`
   - Session history and session detail calls include `session_id`.
     - Files: `frontend/src/services/apiClient.ts` or caller hooks.
   - Therapy plan/styling requests include `session_id`.
     - Files: `frontend/src/hooks/useTherapyPlan.ts`, `frontend/src/pages/AssessmentPage.tsx`
3) Update error messages for missing session_id to be user-friendly.
4) Ensure `/api/therapy/styles` includes session_id in request:
   - File: `frontend/src/services/api.ts` and any callers.
   - Add session_id query param and block if missing.

### 5.2 Console UI: include session_id everywhere
Steps:
1) Update all HTTP calls to add `session_id`:
   - File: `console-ui/src/console_client.py`
2) Use `required_fields` when prompting for profile completion.
   - For any missing field, prompt the user and include in payload.
3) Ensure `/api/therapy/styles` includes session_id (query param).

### 5.3 HTTP-only flow: ensure session exists before calling workflow/status endpoints
Goal: prevent HTTP-only clients from calling session-bound endpoints without a session.

Steps:
1) Update docs and examples to show the required order:
   - Connect via WS OR call `POST /api/sessions` to create a session.
   - Use returned `session_id` for all subsequent requests.
2) Frontend safety:
   - Block `useWorkflowNextAction`, `useUserProfile`, and `useTherapyPlan` calls
     until `currentSessionId` is present.
   - If session is missing, prompt the user to reconnect or create a session.
3) Console safety:
   - If no `session_id` is present, print a clear message and avoid HTTP calls
     that require it.

Acceptance:
- No HTTP client calls session-bound endpoints without a session_id.
- Docs show a correct “session-first” flow.

Acceptance:
- All client requests include session_id after session_started.

---

## Phase 6: Docs, Schemas, and Types

Steps:
1) Update docs:
   - `docs/contracts/HTTP_API_CONTRACT.md`
   - `docs/WEBSOCKET_PROTOCOL.md`
     - Remove "allow session requests" wording for `start_intake`/`continue_therapy`.
     - Clarify implicit session binding on WS.
     - Clarify wait-state greeting skip + status notice.
   - `docs/ARCHITECTURE.md`
     - Update endpoint list to include session_id requirements.
     - Note implicit WS session binding and wait/greeting behavior.
   - `docs/session_lifecycle.md` (if it describes the handshake/auto-session flow)
   - `docs/user_journey.md`
   - `docs/QUICKSTART.md`
2) Regenerate schemas:
   - `docker compose run --rm api python scripts/generate_schemas.py`
   - `docker compose run --rm api python scripts/validate_schemas.py`
3) Regenerate frontend types:
   - `docker compose run --rm frontend npm run generate:types`

---

## Phase 7: Tests

### Backend unit tests
- Add/extend tests for:
  - Session_id validation on `GET /api/workflow/next`.
  - Session_id validation on other post user_id endpoints.
  - Orchestrator transitions using workflow events.
  - Wait-state prompt returns `required_action: wait`.

### Backend integration tests
- WebSocket connect:
  - `session_started` then `workflow_next_action`.
  - No greeting when `required_action == wait`.
  - Greeting present when not wait.
- Workflow endpoints:
  - All return 400 when session_id missing/invalid.

### Frontend tests
- Update tests that mock workflow next action or session_id.
- Update WebSocket service tests for wait/greeting behavior if needed.

Commands (Docker-only):
- `make docker-test-one TEST=tests/unit/test_workflow_next_action.py`
- `make docker-test-one TEST=tests/unit/test_workflow_routes.py`
- `make docker-test-one TEST=tests/integration/test_trio_flow.py`
- `make docker-test-frontend`

---

## Acceptance Criteria
- All post user_id endpoints require and validate session_id.
- Workflow transitions are orchestrator-owned; agents no longer set `next_state`.
- Reflection agent plan updates are persisted only by orchestrator logic.
- No initial greeting is sent when `required_action == "wait"`, but users see a status notice.
- Docs/contracts/schemas/types are updated and tests pass.

---

## Risks and Mitigations
- Risk: Breaking existing clients by adding session_id requirements.
  - Mitigation: Update all UI clients and docs in the same change set.
- Risk: Transition logic regression when removing agent `next_state`.
  - Mitigation: Add unit tests for each workflow event and gating rule.

---

## Implementation Order (Suggested for Juniors)
1) Contract + DTO updates, schema regeneration.
2) Backend enforcement for session_id.
3) Orchestrator transition refactor.
4) Plan persistence cleanup.
5) Wait-state greeting logic.
6) Frontend + console updates.
7) Tests and documentation.
