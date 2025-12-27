# Phase 2 Implementation Plan — Workflow Navigation Consistency

Source: `docs/assessments/project/CODEBASE_ASSESSMENT_2025-12-16.md` (“Phase 2 — Workflow Navigation Consistency”).

## 0) Outcome (Definition of Done)

- A user can progress end-to-end: **Profile → Intake → Assessment → Style selection → Therapy** without manual hacks, broken routes, or stale UI state.
- All “where should I go next?” logic is **centralized and consistent** (one canonical source of truth).
- Frontend pages do not rely on nonexistent events (e.g. `assessment-complete`) or nonexistent routes (e.g. `/session/current`, `/session/new` unless implemented).
- This consistency holds across **all clients** that drive the workflow:
  - Web frontend (`frontend/`)
  - Console UI (`console-ui/`)
  - Deterministic E2E run of the web frontend (`src/psychoanalyst_app/e2e_server.py` running the same backend)

## 1) Decision Gate: Backend-driven vs Frontend-driven routing

### Option A (recommended): backend-driven navigation (keep `/api/workflow/next-action`)

Why this fits the current code:
- Endpoint exists: `src/trio_server.py::_get_next_action()` and mapping in `_determine_next_action()`.
- Hook exists: `frontend/src/hooks/useWorkflowNavigation.ts::useWorkflowNextAction()`.
- Already used in `frontend/src/components/Dashboard.tsx` and `frontend/src/pages/ProfilePage.tsx`.

Cost:
- Requires completing the remaining integration: `IntakePage`, `AssessmentPage`, and route/WS protocol alignment.

### Option B: frontend-driven mapping (remove `/api/workflow/next-action`)

Only choose this if you explicitly do *not* want backend-controlled flow. If chosen:
- Delete the endpoint + hook.
- Add a single frontend mapping table keyed by `UserStatus` from `useUserProfile()`.

This plan proceeds with **Option A**.

## 2) Canonical Route Contract (single source of truth)

### 2.1 Define the canonical set of “workflow pages”

These are the routes the backend is allowed to return via `WorkflowNextActionResponse.route`:
- `/profile`
- `/intake`
- `/assessment`
- `/dashboard`
- `/session/new` (new session entry route) **or** replace with a different explicit route (see 2.2)

### 2.2 Resolve “start therapy session” routing

Problem today:
- Frontend references `/session/new` and `/session/current`, but the router only defines `/session/:sessionId`.
  - `frontend/src/components/shared/WorkflowStepper.tsx` uses `/session/new`
  - `frontend/src/components/NavigationDrawer.tsx` uses `/session/current`

Decision:
- Implement a real route for starting a new session (recommended: `/session/new`).
  - Add `<Route path="/session/new" element={<TherapySession />}>` in `frontend/src/App.tsx`.
  - Remove `/session/current` references (or implement it as a redirect to `/session/new`).

Then update the backend mapping to use it:
- Change `WorkflowState.PLAN_COMPLETE` in `src/trio_server.py::_determine_next_action()` from `"/dashboard"` to `"/session/new"` (or the chosen “new session” route).

Acceptance:
- No code references non-existent routes.
- “Continue” from Dashboard brings the user to the correct next workflow page.

## 3) Backend Work Items

### 3.1 Make WebSocket session creation respect `session_type`

Problem today:
- Frontend sends `{"type":"session_request","data":{"session_type":"therapy|intake|assessment"}}`
  (`frontend/src/services/websocketService.ts`)
- Backend ignores it and always starts the default session type:
  `src/trio_server.py` calls `self.orchestrator.start_session(user_id, send_initial_message=True)`

Implementation:
- In `src/trio_server.py` WebSocket handler, read `message["data"]["session_type"]` and pass it to:
  - `TrioAgentOrchestrator.start_session(user_id, session_type=..., send_initial_message=True)`

Acceptance:
- Visiting `/intake` starts an INTAKE session and advances status to `INTAKE_IN_PROGRESS`.
- Visiting `/assessment` starts an ASSESSMENT session and advances status appropriately.
- Visiting `/session/new` starts a THERAPY session.

### 3.2 Deliver “assessment recommendations” to the frontend (remove DOM event hack)

Problem today:
- `frontend/src/pages/AssessmentPage.tsx` listens for a browser event `assessment-complete` that is never emitted.
- The Assessment agent produces recommendations in `AgentResponse.metadata["recommendations"]` (`src/agents/trio_assessment_agent.py`), but the orchestrator does not forward metadata to clients.

Implementation (minimal, WS-based):
- Add a new server→client WS message type, e.g.:
  - `assessment_recommendations` with payload `{ recommendations: [{style_id, explanation, score}], session_id, user_id }`
- When the orchestrator receives an `AgentResponse` with `next_action == "await_selection"`:
  - Send the `assessment_recommendations` message to the session websocket
  - Keep streaming the formatted chat content as today

Suggested insertion point:
- `src/orchestration/trio_agent_orchestrator.py::_handle_agent_response()` in the `elif action == "await_selection":` block, using the existing websocket registered in `TrioConversationManager.websockets[session_id]`.

Acceptance:
- AssessmentPage can switch to selection mode deterministically without parsing chat text.
- No frontend reliance on `window.addEventListener('assessment-complete', ...)`.

### 3.3 (Optional, only if needed) Send `user_status` updates over WebSocket

If polling/React Query refetch is not sufficient UX-wise, add:
- WS message type `user_status` (already defined on the frontend) emitted after workflow transitions.

Implementation sketch:
- After `self.workflow_engine.transition(...)` in `src/orchestration/trio_agent_orchestrator.py::_handle_agent_response()`, send:
  `{"type":"user_status","data":{"user_id":..., "status":..., "workflow_state":...}}`

Acceptance:
- Frontend can invalidate `['user', userId]` and `['workflow','next-action',userId,*]` immediately on status change.

### 3.4 Use `current_route` meaningfully (tighten backend contract)

Today `WorkflowNextActionRequest.current_route` is accepted but not used.

Implementation:
- In `src/trio_server.py::_determine_next_action()`:
  - If `current_route` already matches the target `route`, return `action="wait"` or `action="display"` (depending on UX) instead of “navigate to the same place”.
  - If `current_route` is not a known workflow route, return `navigate` to the canonical route for the current state.

Acceptance:
- The frontend can rely on `nextAction.action` semantics (navigate vs wait/display) without special-casing.

## 4) Web Frontend Work Items (`frontend/`)

### 4.1 Add a single “workflow enforcement” layer

Goal: any workflow page self-corrects when the user is on the wrong route.

Implementation (recommended):
- Add a small component or hook (e.g. `frontend/src/hooks/useEnforceWorkflowNavigation.ts` or `frontend/src/components/WorkflowGate.tsx`) that:
  - Reads `userId` via `useCurrentUserId()`
  - Reads `location.pathname` via `useLocation()`
  - Calls `useWorkflowNextAction(userId, location.pathname)`
  - If `nextAction.action === "navigate"` and `nextAction.route !== location.pathname`, `navigate(nextAction.route, { replace: true })`

Where to apply:
- Prefer wrapping all protected routes inside `Layout` (or inside `ProtectedRoute`) so every page gets consistent enforcement without duplicating logic.

Acceptance:
- Directly visiting `/assessment` as a new user redirects to `/profile`.
- Directly visiting `/session/new` before plan completion redirects to `/intake` or `/assessment` depending on state.

### 4.2 Make `TherapySession` support non-therapy session types (intake/assessment)

Problem today:
- `frontend/src/components/TherapySession.tsx` always calls `requestSession('therapy')`.

Implementation:
- Add a prop such as `sessionType?: 'therapy' | 'intake' | 'assessment'` (aligned with backend values).
- Update IntakePage / AssessmentPage / “new session route” to render `TherapySession` with the appropriate `sessionType`.

Acceptance:
- IntakePage uses `sessionType="intake"`.
- AssessmentPage uses `sessionType="assessment"` while in chat mode.
- Therapy uses `sessionType="therapy"`.

### 4.3 Refactor `IntakePage` to be backend-driven

Replace:
- Manual status warning
- Manual “Proceed to Assessment” button logic (or keep as an optional UX affordance, but not required for correctness)

With:
- The workflow enforcement layer handling redirects.
- Optional: show a success banner when the status flips, but route changes should still work without clicking anything.

Acceptance:
- When intake completes, user is routed to `/assessment` consistently (automatic or via a single “Continue” that uses `nextAction.route`).

### 4.4 Refactor `AssessmentPage` to be backend-driven + WS-driven recommendations

Replace:
- DOM event listener `assessment-complete`
- Hard-coded post-plan navigation to `/dashboard`

With:
- Listen for the new WS message `assessment_recommendations` and switch to selection mode.
- After `createPlan`, refetch `useWorkflowNextAction` and navigate to the backend-provided route (likely `/session/new`).

Acceptance:
- After recommendations are generated, the selection UI appears.
- After selecting a style, navigation goes to the backend-chosen next page (no hard-coded routing).

### 4.5 Remove/align legacy route references

Update:
- `frontend/src/components/NavigationDrawer.tsx`: remove `/session/current` or make it route to `/session/new`.
- `frontend/src/components/shared/WorkflowStepper.tsx`: ensure the “Therapy” step route exists (prefer `/session/new`).

Acceptance:
- No route constants in the UI point to paths not present in `frontend/src/App.tsx`.

### 4.6 React Query invalidation on WS status updates (only if implementing 3.3)

If backend starts emitting `user_status`:
- In the WS integration layer (`frontend/src/hooks/useWebSocket.ts` usage sites), attach `onUserStatus` to:
  - `invalidateQueries(['user', userId])`
  - `invalidateQueries(['workflow','next-action', userId])` (and/or a broader partial-key invalidation)

Acceptance:
- Workflow redirects happen quickly after backend transitions without manual refresh.

## 5) Console UI Work Items (`console-ui/`)

The console client does not have “routes”, but it still participates in the same workflow. Phase 2 should ensure it:
- Starts the correct `session_type` (intake/assessment/therapy) when appropriate
- Doesn’t break when new WS message types are introduced
- Can complete the same end-to-end workflow as the web UI (even if via prompts/menus rather than navigation)

### 5.1 Use backend workflow decisioning (same source of truth)

Implementation options:
- Preferred: call `POST /api/workflow/next-action` and treat `route` as a symbolic step (e.g. `/intake` means “start intake session”).
- Alternate: call `GET /api/user/status` and map status → step locally (duplicated mapping; keep in sync with backend mapping table).

Concrete tasks:
- Add a small “workflow loop” in `console-ui/src/console_client.py`:
  - Fetch next action (preferred) after connect and after any session completes
  - If action is `navigate` to `/profile`: prompt user to complete profile via HTTP, then re-check
  - If action is `navigate` to `/intake`: request WS session with `session_type="intake"`
  - If action is `navigate` to `/assessment`: request WS session with `session_type="assessment"`
  - If action is `navigate` to `/session/new`: request WS session with `session_type="therapy"`

Acceptance:
- Console can progress through the same workflow steps without relying on hard-coded assumptions like “always start therapy”.

### 5.2 Align WebSocket protocol changes

If the backend adds new server→client message types (e.g. `assessment_recommendations`, optional `user_status`):
- Update constants in `console-ui/src/websocket_protocol.py`.
- Update `console-ui/src/console_client.py::_handle_websocket_message()`:
  - Either handle the new messages (e.g. show recommendations and prompt for a selection) **or** explicitly ignore them without noisy “Unknown message type” warnings.

Acceptance:
- Console output stays clean; new backend messages don’t cause warning spam or break the chat loop.

### 5.3 Assessment selection UX (only if console supports assessment selection)

If you want the console to complete assessment → plan selection:
- On receiving `assessment_recommendations`, display the list and prompt the user to choose.
- Submit the selection via the existing HTTP endpoint used by the web UI:
  - `POST /api/therapy/plan` with `therapy_style`
- Re-check workflow next action and proceed to therapy.

Acceptance:
- Console can complete “assessment recommendations → style pick → plan creation” without parsing chat text.

## 5) Test/Validation Plan

### 5.1 Manual smoke flows (local)

- New user (web):
  - Go to `/dashboard` → redirected to `/profile`
  - Save profile → redirected to `/intake`
  - Complete intake → routed to `/assessment`
  - Complete assessment → selection UI appears
  - Choose style → routed to `/session/new`
  - Session starts and chat works

- Deep-link hardening (web):
  - While in `INTAKE_IN_PROGRESS`, visit `/session/new` → redirected to `/intake`
  - After plan creation, visit `/intake` → redirected to `/session/new`

### 5.2 Manual smoke flows (console)

- Connect and authenticate.
- If profile required, create/update it in-console (HTTP) and continue.
- Verify the console starts the correct session types in sequence:
  - Intake (`session_type="intake"`)
  - Assessment (`session_type="assessment"`)
  - Therapy (`session_type="therapy"`)
- If implementing assessment recommendations in console:
  - Receive and render recommendations
  - Choose a style
  - Verify plan is created and the next action becomes therapy

### 5.2 Automated checks (recommended additions)

Backend:
- Add a small unit/contract test for `/api/workflow/next-action` mapping correctness (table-driven over states).

Frontend:
- Add a test for the workflow enforcement component/hook (redirect behavior given a mocked `useWorkflowNextAction` response).

## 6) Suggested Execution Order (minimizes rework)

1. Implement `/session/new` route and eliminate route drift (2.2, 4.5).
2. Backend: honor `session_type` for WS session creation (3.1) + frontend `TherapySession` prop (4.2).
3. Backend: emit `assessment_recommendations` WS message (3.2) + frontend `AssessmentPage` consumption (4.4).
4. Add workflow enforcement layer and remove per-page hacks (4.1, 4.3, 4.4).
5. Optional: WS `user_status` for faster UI updates (3.3, 4.6).
6. Tighten `current_route` semantics (3.4) once the flow is stable (ensure console callers are either supported or documented).

## 7) Deliverables Checklist

- Backend
  - `src/trio_server.py` reads `session_type` and passes through
  - `src/orchestration/trio_agent_orchestrator.py` emits `assessment_recommendations` (and optionally `user_status`)
  - `docs/WEBSOCKET_PROTOCOL.md` updated with new message(s) (if the repo treats docs as canonical)
- Frontend
  - `frontend/src/App.tsx` includes a “new therapy session” route (`/session/new`)
  - `frontend/src/components/TherapySession.tsx` accepts `sessionType`
  - `frontend/src/pages/IntakePage.tsx` and `frontend/src/pages/AssessmentPage.tsx` rely on backend-driven navigation + WS message(s)
  - `frontend/src/components/NavigationDrawer.tsx` and `frontend/src/components/shared/WorkflowStepper.tsx` routes aligned
- Console UI
  - `console-ui/src/console_client.py` uses backend next-action (or a documented status→step mapping) and requests the correct `session_type`
  - `console-ui/src/websocket_protocol.py` and `console-ui/src/console_client.py` updated for any new WS message types (handle or explicitly ignore)
