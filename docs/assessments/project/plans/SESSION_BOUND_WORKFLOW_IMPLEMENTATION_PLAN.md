# Session-Bound Workflow Implementation Plan

## Objective
Ensure that once a user_id exists/has been selected, all client interactions are
bound to a defined conversation session (session_id). The only time a client is
outside a session is before user_id creation/selection (pre-login).

## Definitions
- **Session**: A conversation session represented by `Session`/`session_id` and
  managed by `TrioConversationManager`. This is not an HTTP login session.
- **Session-bound**: Workflow updates and step-completion endpoints require a
  valid `session_id` that belongs to the user.

## Scope
- Backend orchestration, HTTP/WS contracts, session management.
- Frontend + console UI session binding.
- Schemas/types, tests, and documentation.

## Non-Goals
- Changing persistence schema unless strictly required.
- Adding new user authentication flows.

## Decisions To Confirm (Before Coding)
1) **Auto-session on WS connect**: On WS connect, create a session immediately
   and emit `session_started` before `workflow_next_action`.
2) **Session binding for HTTP**: Require `session_id` in
   `/api/workflow/complete_profile` and `/api/workflow/select_therapy_style`.
3) **Active session lookup**: Use in-memory user_id -> session_id mapping (no DB
   schema changes).

These are confirmed; proceed with the steps below.

---

## Phase 1: Backend Session Binding

### 1. Add active-session tracking (single concurrent session)
- Add an in-memory mapping (user_id -> session_id) in orchestration, preferably
  in `TrioConversationManager` or a new small registry class.
- Enforce **one active session per user**:
  - If a session exists, either block new creation or cleanly end the old session
    before creating a new one (pick one and document it).
- Update session creation/end flows to keep the mapping in sync:
  - On session create: record the mapping.
  - On session end: clear the mapping.
- Provide lookup methods:
  - `get_active_session_id(user_id)`
  - `is_session_active(user_id, session_id)`

Files:
- `src/psychoanalyst_app/orchestration/trio_conversation_manager.py`
- `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`
- `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py`

### 2. Bind WS connections to a session on connect
- In `ws_handler.py`, after validating user_id:
  - Ensure a session exists for this user (create one if none active).
  - **Select session type based on current workflow state** (resume the correct
    stage):
    - If last state is therapy-related, start a therapy session.
    - If last state is intake-related, start an assessment session next.
    - Otherwise, map `WorkflowState` -> session type explicitly.
  - Register the websocket against that session_id immediately.
  - Emit `session_started` (if new) before `workflow_next_action`.
- Keep the `session_id` for subsequent chat messages.

Workflow state -> session type mapping (explicit):

| WorkflowState | Session Type | Notes |
| --- | --- | --- |
| NEW | intake | Start intake for new users. |
| INTAKE_IN_PROGRESS | intake | Resume intake session. |
| INTAKE_COMPLETE | assessment | Intake completed, assessment should start next. |
| ASSESSMENT_IN_PROGRESS | assessment | Resume assessment session. |
| ASSESSMENT_COMPLETE | therapy | Assessment done, therapy starts next. |
| THERAPY_IN_PROGRESS | therapy | Resume therapy session. |
| REFLECTION_IN_PROGRESS | therapy | Reflection is backend-only; therapy resumes next. |
| PLAN_COMPLETE | therapy | Plan is ready; therapy continues next. |

Files:
- `src/psychoanalyst_app/api/ws_handler.py`
- `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`

### 3. Emit workflow_next_action using session_id
- Add an overload or new method to emit next action by session_id.
- Update any calls to `emit_workflow_next_action` to use session_id
  whenever available (WS connect, agent response, session end).

Files:
- `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py`
- `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`

---

## Phase 2: Step-Completion Endpoint Binding

### 4. Add workflow-specific request DTOs
Create dedicated DTOs that include `session_id`:
- `WorkflowCompleteProfileRequestDTO`
  - `user_id`, `session_id`, profile fields
- `WorkflowSelectTherapyStyleRequestDTO`
  - `user_id`, `session_id`, `selected_therapy_style`

Files:
- `src/psychoanalyst_app/models/http_models.py`
- `schemas/*` (regenerate)
- `frontend/src/types/*` (regenerate)

### 5. Require session_id on step completion endpoints
- Update `/api/workflow/complete_profile` and `/api/workflow/select_therapy_style`
  to parse the new DTOs and validate:
  - `session_id` exists
  - `session_id` belongs to `user_id`
  - A websocket is registered for the session (if required)
- After persistence, emit `workflow_next_action` to the active session.

Files:
- `src/psychoanalyst_app/api/workflow_routes.py`
- `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py`

### 6. Enforce state transitions in orchestrator
- Ensure `create_therapy_plan` transitions via `workflow_engine` instead of
  directly setting `UserStatus`.
- Validate current workflow state for step completion:
  - Profile completion should be allowed only in NEW/INTAKE states.
  - Style selection should be allowed only after ASSESSMENT_COMPLETE.
- Ensure a newly auto-created session resumes at the **correct stage** based on
  workflow state (do not reset to intake if user is already past it).

Files:
- `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py`
- `src/psychoanalyst_app/orchestration/trio_workflow_engine.py`

---

## Phase 3: Frontend Session Binding

### 7. Capture session_id from WS
- Update WebSocket handlers to persist `session_id` from `session_started`.
- Ensure WS connect happens immediately after user_id is chosen.

Files:
- `frontend/src/services/websocketService.ts`
- `frontend/src/contexts/*` or wherever user/session state is stored

### 8. Include session_id in workflow calls
- Update workflow mutations to include session_id:
  - `complete_profile`
  - `select_therapy_style`
- Surface a clear error if session_id is missing.

Files:
- `frontend/src/services/api.ts`
- `frontend/src/hooks/useUserProfile.ts`
- `frontend/src/hooks/useTherapyPlan.ts`

### 9. Consume WS workflow_next_action
- Add a WS subscription that updates React Query cache for
  `['workflow', 'next', userId]` whenever a `workflow_next_action` event arrives.

Files:
- `frontend/src/hooks/useWorkflowNavigation.ts`
- `frontend/src/contexts/*` or a new hook

---

## Phase 4: Console UI Binding

### 10. Persist session_id and include in step completion
- Capture `session_id` from `session_started`.
- Include session_id in `/workflow/complete_profile` and
  `/workflow/select_therapy_style` payloads.

Files:
- `console-ui/src/console_client.py`

---

## Phase 5: Docs, Schemas, and Types

### 11. Update contract docs
- `docs/contracts/HTTP_API_CONTRACT.md`
  - Add session_id to workflow step requests.
  - Clarify session requirement after user_id selection.
- `docs/WEBSOCKET_PROTOCOL.md`
  - Document `session_started` ordering and session-bound workflow events.
- `docs/user_journey.md`, `docs/ARCHITECTURE.md`, `docs/QUICKSTART.md`
  - Remove legacy endpoint references.
  - Describe session-bound onboarding flow.

### 12. Regenerate schemas and frontend types
- [x] `docker compose run --rm api python scripts/generate_schemas.py`
- [x] `docker compose run --rm frontend npm run generate:types`

---

## Phase 6: Tests

### 13. Backend unit tests
- Add tests for new DTO validation and state gating.
- Extend `test_workflow_next_action` if action values or prompts change.

Files:
- `tests/unit/test_workflow_next_action.py`
- New: `tests/unit/test_workflow_routes.py`

### 14. Integration tests
- WS connect returns `session_started` then `workflow_next_action`.
- Step completion with valid session_id triggers `workflow_next_action`.
- Missing/invalid session_id returns `400`.
- Update existing tests that still call `POST /api/therapy/plan`.

Files:
- `tests/integration/*`

---

## Acceptance Criteria
- After user_id selection, the client always has a session_id.
- Only one active session exists per user at any time.
- Auto-created sessions resume at the correct stage based on workflow state.
- Workflow step completion endpoints require session_id and emit
  `workflow_next_action` to that session.
- WS clients receive `session_started` and `workflow_next_action` on connect.
- Orchestrator alone advances workflow state (no direct UserStatus mutation).
- Docs and contracts reflect session-bound behavior; legacy endpoints removed.

## Validation (Docker Only)
- `make docker-test-one TEST=tests/unit/test_workflow_routes.py`
- `make docker-test-one TEST=tests/integration/test_websocket_protocol_contract.py`
- `make docker-test-one TEST=tests/integration/test_trio_flow.py`
- `make docker-test-frontend`
