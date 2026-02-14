# Intended vs Actual Alignment — Testing & Design Assessment
**Date:** 2026-02-02  
**Scope:** Backend (Trio orchestration + agents), Console UI workflow handling, and end-to-end workflow confidence  
**Primary references:** `docs/design-principles.md`, `docs/user_journey.md`, `docs/session_lifecycle.md`, `docs/current_issues/*`

## Executive Summary

Two currently observed user-facing failures highlight a broader “intended vs actual” drift problem:

1. **Abrupt intake end** (`docs/current_issues/abrupt_intake_end.md`): the system can transition into the next workflow phase while the user is still being asked a question, causing the UI to show a prompt that cannot be answered in-context.
2. **Therapy style selection not working** (`docs/current_issues/select_assessment_style.md`): the Console UI leaks backend API instructions to the user and does not implement the workflow’s `select_therapy_style` action as a first-class UI step.

The key strategy to close the gap is to make the **workflow contract executable**:
- enforce *turn-boundary invariants* in the orchestrator/agents, and
- enforce *required_action handling* in each client (console + web),
then back that with **small, deterministic regression tests** that fail on the exact drift modes above.

## Current State (What Exists Today)

### Design intent (from `docs/design-principles.md`)
- Trio-first structured concurrency; no “fire-and-forget”.
- Clean boundaries: agents = business logic; orchestration = workflow transitions; gateways = I/O.
- Backend-driven workflow state machine; clients render based on `WorkflowNextActionDTO.required_action`.
- Deterministic tests should prefer fakes/stubs over real LLM/RAG calls.

### Evidence of drift in implementation
- **Console UI** prints an API instruction instead of performing the workflow step:
  - `console-ui/src/console_client.py` currently renders assessment recommendations and then prints:
    - “To select a style, submit POST /api/workflow/select_therapy_style …”
  - It also only explicitly handles `required_action == "wait"` and does not treat `select_therapy_style` as a UI step.
- **Intake agent completion logic** can signal workflow completion while still prompting to continue:
  - `src/psychoanalyst_app/agents/trio_intake_agent.py` builds a continuation prompt and may also set `WorkflowEvent.COMPLETE_INTAKE`, which triggers orchestration transitions and background assessment.
  - This matches the failure mode: a “last question” appears, then the workflow advances and the client shows an assessment/wait state.

### Test suite signal quality (high-level)
- Strong baseline coverage exists for contracts, orchestration wiring, and deterministic “natural flow”:
  - `tests/integration/test_websocket_protocol_contract.py`
  - `tests/integration/test_trio_orchestration.py`
  - `tests/integration/test_natural_patient_flow.py`
- However, there are gaps specifically around **client conformance to `required_action`** and around **turn-boundary workflow invariants**.

## Gap Analysis (Why “Green Tests” ≠ “Working UX”)

### Gap A — No enforceable “turn boundary” rule for transitions
**Intended:** A workflow transition should never strand the user mid-turn (e.g., asking a question then immediately moving to a non-chat “wait” action).  
**Observed risk:** An agent can emit `workflow_event` that causes transition while its generated text still expects a user response.

**Impact:** This produces the exact “abrupt end” experience: the UI is ready for input, but the backend has already advanced to a non-input step.

### Gap B — Clients are not tested against the workflow contract they are meant to implement
**Intended:** Clients render forms/actions based on `required_action` (profile completion, style selection, chat, wait).  
**Observed risk:** Console UI can remain “green” even when it doesn’t implement required actions (because current tests mostly validate backend behavior, not client behavior).

**Impact:** Users are told to call HTTP endpoints (a contract leak) and the selection step fails in practice.

### Gap C — Some tests are high-maintenance / low-signal
There is at least one large integration test that uses multiple `trio.sleep(...)` calls and manually forces workflow transitions/plan creation, which can:
- pass while bypassing the true workflow contract, and/or
- fail intermittently for timing reasons.

## Recommendations (Prioritized)

### Priority 0 — Encode “turn boundary” semantics into AgentResponse/Orchestrator
Goal: make it *impossible* to transition to a new workflow phase while presenting a question that expects user input.

Concrete options (choose one and make it a standard):
1. **Add explicit semantics to `AgentResponse`** (preferred):
   - e.g., `expects_user_reply: bool` and/or `response_kind: "prompt" | "closing" | "info"`.
   - Or keep it in `metadata` but enforce it centrally.
2. **Guard transitions in `AgentResponseHandler.handle(...)`**:
   - If `workflow_event` indicates completion and `expects_user_reply=True`, delay the transition until the next user message boundary (or refuse the transition and log).
3. **Make completion responses deterministic and non-interactive**:
   - For intake completion: return a direct, non-question closing message (or an LLM prompt that is explicitly “no questions” + validator/sanitizer).

This directly prevents the “ask one last question → transition immediately” failure mode.

### Priority 1 — Fix intake completion prompt selection and completion criteria
Goal: intake completion should not reuse “continue conversation” prompts.

Recommendations:
- When intake is complete, use a dedicated closing prompt (`CLOSING_PROMPT` exists in `src/psychoanalyst_app/prompts/intake_prompts.py`).
- Re-evaluate completion criteria:
  - avoid a pure “80% topics” threshold if some topics are effectively mandatory for safety/clinical completeness;
  - consider “mandatory topics” + “coverage threshold” rather than threshold alone.

### Priority 1 — Make Console UI a first-class workflow client
Goal: Console UI must implement the same backend-driven workflow contract as the Web UI.

Recommendations:
- Implement `required_action == "select_therapy_style"` in `console-ui/src/console_client.py`:
  - show a numeric picker using the cached `assessment_recommendations`,
  - POST selection via `/api/workflow/select_therapy_style`,
  - then re-render based on the returned/next `workflow_next_action`.
- Remove all user-facing strings that instruct calling raw backend endpoints.

### Priority 2 — Add regression tests tied to the two current issues
Goal: every “current issue” has a deterministic test that fails before the fix and passes after.

Proposed tests:
- **Backend unit/integration (abrupt intake end):**
  - Unit: `TrioIntakeAgent` completion returns the closing prompt and does not request more input.
  - Integration: run a short intake that triggers completion; assert the final emitted message is “closing” (non-question) *before* workflow advances to `wait`.
- **Console UI (style selection):**
  - Unit: feed `assessment_recommendations` + `workflow_next_action(select_therapy_style)` into the console client handler; assert it prompts for a choice and issues the correct API call (mock HTTP client).
  - Optional integration: deterministic server + scripted console selection; assert workflow advances to therapy.

### Priority 3 — Expand deterministic E2E coverage for the full golden workflow
Current deterministic Playwright coverage (`frontend/e2e/golden-path.spec.ts`) stops at intake chat streaming.

Add at least one deterministic E2E spec covering:
`profile → intake → assessment wait → recommendations → style selection → therapy start`

This is the single highest-leverage “green tests ⇒ working app” signal for real users.

## Tests With Low Additional Value (Candidates to Remove or Rewrite)

These are not “delete immediately”, but they should be evaluated through the lens:
“Does this fail only when user-facing behavior is broken?”

### Strong candidates to rewrite (or remove if not maintained)
- `tests/integration/test_console_ui_patient_flow.py`
  - Uses many `trio.sleep(...)` calls (timing sensitivity).
  - Manually forces workflow transitions and manually creates a therapy plan (bypasses the workflow contract).
  - Recommendation: split into smaller, event-driven tests that validate real client workflow behavior; if that’s not feasible, move it to a slower/manual suite.

### Candidates to fix or temporarily disable if out-of-sync
- `tests/unit/test_trio_intake_agent.py`
  - The intent is valuable (it targets the “closing prompt on completion” invariant), but it appears drifted from current `ConversationContext` construction (`session_id` vs `session_block_id`).
  - Recommendation: fix it to match current models and keep it, because it directly guards the “abrupt intake end” regression class.

### Optional consolidation
- Version checks exist both as unit tests and API integration tests:
  - `tests/unit/test_version.py` and `tests/integration/test_version_endpoints.py`
  - Keeping both is defensible (logic vs wiring), but if suite time becomes an issue, pick one and rely on deterministic E2E for end-to-end validation.

## Success Metrics (How We Know Alignment Improved)

- **Workflow invariants covered:** explicit tests for “no transition while expecting user input” for intake completion and for therapy style selection.
- **Client conformance:** both console and web clients handle every `required_action` value in the contract.
- **Flake rate:** no reliance on fixed sleeps in default suites; event-driven waits with bounded timeouts.
- **Confidence:** a single deterministic golden-path E2E test covers the full “new user → therapy start” workflow.

