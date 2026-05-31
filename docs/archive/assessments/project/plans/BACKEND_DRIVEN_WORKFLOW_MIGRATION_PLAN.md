# Backend-Driven Workflow Migration Plan (No Legacy Compatibility)

## Objective
Migrate the system to a backend-driven workflow model where the orchestrator owns all
state transitions and required actions, while user interfaces decide how to collect
inputs. This plan removes all legacy compatibility paths (no dual support).

## Scope
- Backend orchestration, HTTP/WS contracts, agents, validation, and persistence.
- Frontend and console UI integrations.
- Tests, schemas, and documentation updates.

## Non-Goals
- No backward compatibility for existing HTTP endpoints.
- No changes to data storage schema unless explicitly required.
- No redesign of agent reasoning logic beyond structured outputs.

## Key Principles
- Orchestrator is the single source of truth for workflow state and required action.
- Agents produce structured outputs only; they do not advance workflow or persist.
- Clients request or receive required actions from the backend and submit inputs
  through new step-completion endpoints.

## Contracts (Source of Truth)
Update contract docs before implementation so changes are traceable.

### 1) Workflow Next Action DTO
Add a new DTO in `docs/contracts/HTTP_API_CONTRACT.md` and
`docs/WEBSOCKET_PROTOCOL.md`:

```
WorkflowNextActionDTO
- user_id: str
- workflow_state: WorkflowState
- required_action: str
- required_fields: list[str]
- defaults: dict (optional)
- prompt: str | null
- blocking: bool
- timestamp: datetime
```

Example `required_action` values:
- `complete_profile`
- `select_therapy_style`
- `start_intake`
- `continue_therapy`
- `wait`

### 2) New HTTP Endpoints
Replace legacy profile/plan endpoints with explicit step-completion endpoints:

- `GET /api/workflow/next?user_id=...` -> `WorkflowNextActionDTO`
- `POST /api/workflow/complete_profile`
  - Payload: `{ user_id, ...profile_fields }`
- `POST /api/workflow/select_therapy_style`
  - Payload: `{ user_id, selected_therapy_style }`

### 3) New WS Event
Add a WS event `workflow_next_action` with `WorkflowNextActionDTO` payload.

## Implementation Plan

### Phase A: Backend Core Logic

1) Create next-action resolver
- Add `src/psychoanalyst_app/orchestration/workflow_next_action.py`.
- Implement `resolve_next_action(profile, plan, state, session) -> WorkflowNextActionDTO`.
- Enforce completeness rules (profile required fields + defaults).
- Define required fields for each action (e.g., profile fields, style selection).

2) Orchestrator integration
- Add a method to `TrioAgentOrchestrator` to compute and emit next action.
- Emit next action on:
  - WS connect
  - After agent output is persisted
  - After step-completion endpoints succeed
  - After state transition
- Ensure no helper functions advance workflow. Transitions stay in orchestrator.

3) Agent output handling
- Ensure intake/planning/assessment agents return structured payloads only.
- Orchestrator validates payload type, persists, then uses resolver to
  determine next action.

### Phase B: HTTP/WS Layer

4) Implement new HTTP endpoints
- Create `src/psychoanalyst_app/api/workflow_routes.py` with:
  - `GET /api/workflow/next`
  - `POST /api/workflow/complete_profile`
  - `POST /api/workflow/select_therapy_style`
- Validate inputs (Pydantic DTOs).
- Persist data and transition workflow if completeness criteria met.
- Return updated `WorkflowNextActionDTO` after each call.

5) Update WS handler
- On connect, send `workflow_next_action`.
- After handling messages or step completion, emit updated action.
- Keep error handling lean; do not send stacktraces.

6) Remove legacy routes
- Delete or disable:
  - `POST /api/user/profile`
  - `POST /api/therapy/plan`
- Update any imports, tests, or documentation that reference them.

### Phase C: UI Migration

7) Frontend
- Add a `useWorkflowNextAction` hook that subscribes to WS and can fallback
  to `GET /api/workflow/next`.
- Render UI based on `required_action` and `workflow_state`.
- Replace profile/plan HTTP calls with step-completion endpoints.
- Ensure forms still collect inputs locally; only submit to new endpoints.

8) Console UI
- Subscribe to `workflow_next_action`.
- Prompt user for fields based on `required_fields`.
- Submit data via step-completion endpoints.

### Phase D: Schema and Type Generation

9) Update models and schemas
- Add DTO models for `WorkflowNextActionDTO` and step-completion requests.
- Generate schemas and frontend types.

### Phase E: Tests

10) Unit tests
- `resolve_next_action` for all states and completeness combinations.
- Orchestrator emits expected action after profile/plan persistence.
- Agent structured outputs validated and persisted correctly.

11) Integration tests
- WS connect returns `workflow_next_action`.
- Completing profile advances state and updates action.
- Selecting style creates plan and updates action.
- Ensure no legacy endpoints are used in UI tests.

## Detailed Task Checklist (Junior-Friendly)

### Backend Tasks
- [ ] Add `workflow_next_action.py` with resolver function and tests.
- [ ] Add Pydantic DTOs for next action and step-completion payloads.
- [ ] Add `workflow_routes.py` with new endpoints and tests.
- [ ] Update `ws_handler.py` to send `workflow_next_action`.
- [ ] Update `trio_agent_orchestrator.py` to emit `workflow_next_action`.
- [ ] Remove legacy endpoints and their tests.
- [ ] Update contract docs (`HTTP_API_CONTRACT.md`, `WEBSOCKET_PROTOCOL.md`).

### Frontend Tasks
- [ ] Add hook `useWorkflowNextAction` for WS + HTTP fallback.
- [ ] Update pages to render based on `required_action`.
- [ ] Replace API calls to legacy endpoints with new step-completion endpoints.
- [ ] Update frontend types from generated schemas.

### Console UI Tasks
- [ ] Subscribe to `workflow_next_action` and display prompts.
- [ ] Route user input to new step-completion endpoints.

## Validation and Testing Commands (Docker Only)
- `make docker-test-one TEST=tests/unit/test_workflow_next_action.py`
- `make docker-test-one TEST=tests/integration/test_workflow_endpoints.py`
- `make docker-test-one TEST=tests/integration/test_websocket_protocol_contract.py`
- `make docker-test-frontend`

## Acceptance Criteria
- UI does not call `POST /api/user/profile` or `POST /api/therapy/plan`.
- Orchestrator is the only component that advances workflow state.
- `workflow_next_action` is sent on WS connect and after any completion event.
- Profile completeness gating prevents premature transitions.
- All relevant tests pass.

## Rollback Strategy
- Keep changes in small commits so each phase can be reverted independently.
- If UI migration fails, restore legacy endpoints and UI calls temporarily.
- Ensure contract docs reflect the currently deployed behavior.
