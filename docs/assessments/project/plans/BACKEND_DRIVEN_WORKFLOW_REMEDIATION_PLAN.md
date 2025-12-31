# Backend-Driven Workflow Remediation Plan (Session-Bound + Assessment Wait UX)

## Objective
Close the remaining gaps in the backend-driven workflow migration and session-bound workflow plan. Ensure the backend is the single source of truth for workflow state and session type, remove legacy plan creation from agents, align schemas/types/tests/docs with the new DTOs, and make the client clearly display "Assessment in progress" while waiting.

## Scope
- Backend orchestration, session enforcement, assessment job flow, and HTTP/WS contracts.
- Frontend and console UI updates to remove session-type requests and to show wait messaging.
- Schemas, generated frontend types, tests, and documentation.

## Non-Goals
- Introducing new authentication/login flows.
- Changing persistence schema unless explicitly required to store assessment outputs.
- Redesigning agent reasoning logic beyond removing persistence side effects.

## Decisions (Confirmed)
1) Session type is always derived by the backend from `WorkflowState`. Clients never request a session type.
2) Assessment runs as a backend-only job. Clients should show "Assessment in progress" while the job runs.
3) Therapy plan creation happens only via `/api/workflow/select_therapy_style` (step completion endpoint).

## Implementation Phases

### Phase 0: Read/Confirm Current Contracts and Workflow
- [x] Review `docs/design-principles.md`, `docs/contracts/HTTP_API_CONTRACT.md`, `docs/WEBSOCKET_PROTOCOL.md`.
- [x] Confirm expected post-intake behavior: assessment runs automatically, then `select_therapy_style` is required.
- [x] Confirm whether assessment recommendations must be persisted or can be delivered via WS-only events.

### Phase 1: Backend Session Enforcement (No Client Session Type)
Goal: Backend selects session type for all session creations, regardless of WS messages.

- [x] WS handler: ignore any client-provided session type.
  - File: `src/psychoanalyst_app/api/ws_handler.py`
  - Use `session_type_for_workflow_state()` for any new session.
  - Optional: if a `session_request` arrives, treat it as "start or resume the correct backend session".
- [x] HTTP session creation: derive session type from workflow state.
  - File: `src/psychoanalyst_app/api/session_routes.py`
  - Replace default session creation with `session_type_for_workflow_state()`.
- [x] Update WS protocol docs to remove or deprecate `session_request` session type input.
  - File: `docs/WEBSOCKET_PROTOCOL.md`

### Phase 2: Assessment Job Flow + "Assessment in Progress" Messaging
Goal: After intake ends, assessment runs in the backend; clients show a wait prompt until it completes.

- [x] When intake session ends, transition to `INTAKE_COMPLETE` and then start assessment job.
  - File: `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`
  - Add a background task that:
    1) Transitions to `ASSESSMENT_IN_PROGRESS`.
    2) Runs assessment using stored intake transcript/context.
    3) Transitions to `ASSESSMENT_COMPLETE` on success.
    4) Emits `workflow_next_action` after each transition.
- [x] Ensure `resolve_next_action()` returns `wait` with a clear "Assessment in progress" prompt for:
  - `WorkflowState.INTAKE_COMPLETE`
  - `WorkflowState.ASSESSMENT_IN_PROGRESS`
  - File: `src/psychoanalyst_app/orchestration/workflow_next_action.py`
- [x] If assessment recommendations are produced, emit them via WS when ready.
  - File: `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`

### Phase 3: Remove Agent-Side Plan Persistence
Goal: Agents return structured outputs only; they do not create therapy plans or persist Tier 3/4 data.

- [x] Remove therapy plan creation from assessment agent selection flow.
  - File: `src/psychoanalyst_app/agents/trio_assessment_agent.py`
  - Replace `process_selection()` logic with a response that instructs the user to use the UI step.
  - Do not call `create_initial_plan_with_style()` or save Tier 3/4 data from the agent.
- [x] Ensure only `/api/workflow/select_therapy_style` persists therapy plans.
  - File: `src/psychoanalyst_app/api/workflow_routes.py`

### Phase 4: Update Contracts, Schemas, and Generated Types
Goal: Schemas and generated frontend types reflect `WorkflowNextActionDTO` and step-completion DTOs.

- [x] Update or add schema generation targets for:
  - `WorkflowNextActionDTO`
  - `WorkflowCompleteProfileRequestDTO`
  - `WorkflowSelectTherapyStyleRequestDTO`
  - Files: `src/psychoanalyst_app/models/api_models.py`, `src/psychoanalyst_app/models/http_models.py`
- [x] Remove or deprecate old workflow navigation schemas (`WorkflowNextActionRequest/Response`).
  - Files: `schemas/WorkflowNextActionRequest.json`, `schemas/WorkflowNextActionResponse.json`
- [x] Regenerate schemas:
  - `docker compose run --rm api python scripts/generate_schemas.py`
  - `docker compose run --rm api python scripts/validate_schemas.py`
- [x] Regenerate frontend types:
  - `docker compose run --rm frontend npm run generate:types`

### Phase 5: Frontend + Console UI Updates (No Session Requests)
Goal: Clients never request session types; show wait messaging during assessment.

- [x] Remove `requestSession()` from the frontend WebSocket service and hooks.
  - Files: `frontend/src/services/websocketService.ts`, `frontend/src/hooks/useWebSocket.ts`
- [x] Remove the `SESSION_REQUEST` type from frontend WS types and tests.
  - Files: `frontend/src/types/websocket.ts`, `frontend/src/services/__tests__/websocketService.test.ts`
- [x] Ensure the UI displays the wait prompt consistently when `required_action === "wait"`.
  - Files: `frontend/src/pages/AssessmentPage.tsx` (already shows),
    plus add a banner on `frontend/src/components/Dashboard.tsx` or layout.
- [x] Console UI: remove session request command path or replace it with "reconnect to resume".
  - Files: `console-ui/src/console_client.py`

### Phase 6: Tests
Goal: Update integration coverage to match new endpoints and WS behavior.

- [x] Replace legacy `POST /api/therapy/plan` integration tests with workflow endpoint tests.
  - File: `tests/integration/test_trio_flow.py`
  - Create a session and register a dummy WS before calling `/api/workflow/select_therapy_style`.
- [x] Add WS contract test to ensure `workflow_next_action` follows `session_started`.
  - File: `tests/integration/test_websocket_protocol_contract.py`
- [x] Add unit tests for assessment job transitions and wait prompts (if new code added).
  - File: `tests/unit/test_workflow_next_action.py`
  - New: `tests/unit/test_workflow_routes.py`

### Phase 7: Documentation Updates
Goal: Docs reflect the new workflow endpoints and session-driven behavior.

- [x] Update Quickstart to use workflow endpoints (no legacy `POST /api/user/profile`).
  - File: `docs/QUICKSTART.md`
- [x] Fix HTTP contract: remove stray `/api/therapy/plan` errors and include `GET /api/workflow/next`.
  - File: `docs/contracts/HTTP_API_CONTRACT.md`
- [x] Add `/api/workflow/next` to architecture endpoints and clarify session_request deprecation.
  - File: `docs/ARCHITECTURE.md`
- [x] Update WS protocol to state session type is backend-derived and clients must not request it.
  - File: `docs/WEBSOCKET_PROTOCOL.md`

## Acceptance Criteria
- Clients never send or rely on a session type; backend derives session type from `WorkflowState`.
- `workflow_next_action` emits `required_action: "wait"` with "Assessment in progress" while assessment runs.
- Assessment agent no longer creates therapy plans or persists Tier 3/4 data.
- Schemas and generated frontend types match `WorkflowNextActionDTO` + step completion request DTOs.
- Tests no longer call `POST /api/therapy/plan`; new workflow endpoint tests pass.
- Docs and contracts reflect the current API behavior.

## Validation (Docker Only)
- `make docker-test-one TEST=tests/unit/test_workflow_next_action.py`
- `make docker-test-one TEST=tests/unit/test_workflow_routes.py`
- `make docker-test-one TEST=tests/integration/test_trio_flow.py`
- `make docker-test-one TEST=tests/integration/test_websocket_protocol_contract.py`
- `make docker-test-frontend`

### Latest Validation Results (2025-12-30)
- Schemas generated and validated via docker compose (schemas mounted for validation).
- Frontend types regenerated.
- `make docker-test` passed (242 passed, 2 skipped, 1 warning).
- `make docker-test-frontend` passed (all 268 tests).

## Notes for Junior Developers
- Follow backend-driven rules: do not advance workflow in agents or clients.
- When updating schema/type generation, regenerate both JSON schemas and frontend types.
- Keep changes small and test each phase before moving on.
