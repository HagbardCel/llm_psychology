# Phase 3 Implementation Plan: Orchestration & Agent Cleanup

Reference: `docs/assessments/project/CODEBASE_ASSESSMENT_2025-12-22_LOCAL_LEAN.md` (Phase 3)

## Goals
- Reduce orchestration complexity without changing behavior for core flows.
- Replace stacktrace-yielding error behavior with lean logging and re-raise.
- Centralize profile creation logic so WS and HTTP paths behave consistently.
- Remove legacy-mode methods and compatibility paths in agents.

## Scope
- `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py`
- `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`
- `src/psychoanalyst_app/orchestration/profile_helpers.py`
- `src/psychoanalyst_app/api/ws_handler.py`
- `src/psychoanalyst_app/agents/trio_assessment_agent.py`
- `src/psychoanalyst_app/agents/trio_psychoanalyst_agent.py`
- Supporting tests under `tests/`

## Non-goals
- Changing workflow logic, state transitions, or WS protocol semantics.
- Implementing TODOs in assessment/psychoanalyst agents (scoring, topic detection).
- RAG or style-pack refactors (handled in later phases).

## Key Decisions to Confirm Before Coding
- **Profile creation semantics**: auto-created WS profiles should remain `PROFILE_ONLY` and not advance workflow; only explicit profile creation via HTTP or intake should advance.
- **Workflow transitions**: the orchestrator should perform all workflow transitions; helper utilities should never advance workflow.
- **Error surface**: `process_message` should log and re-raise only (no client error chunk).

## Implementation Steps

### 1) Map existing behavior and test coverage
- Review current orchestration flow and WS handling for error paths.
- Identify tests that assert workflow transitions on profile creation:
  - `tests/integration/test_trio_orchestration.py`
- Capture any assumptions about auto profile creation in WS vs orchestrator.

### 2) Refactor `TrioAgentOrchestrator.process_message`
Goal: break into focused helpers while preserving behavior.

Proposed helper breakdown (move helpers into `orchestrator_helpers.py`):
- `_ensure_session(user_id, session_id) -> str`
- `_record_user_message(session_id, message) -> None`
- `_ensure_profile_for_new_state(user_id, state) -> None`
- `_resolve_agent_and_context(user_id, session_id, state) -> (agent, context)`
- `_stream_agent_response(agent, message, context) -> AsyncIterator[str]`
- `_finalize_agent_response(user_id, session_id, agent_response) -> None`

Notes:
- Keep the public signature and streaming behavior the same.
- Maintain the NEW-state placeholder profile logic, but route it through the unified helper (step 4).
- Do not alter `AgentResponseHandler` behavior except for signature changes if needed.

### 3) Replace stacktrace-yielding error handling
Goal: lean logging + re-raise only.

Changes:
- Remove the `try/except` in `process_message` that yields stacktraces.
- Add narrow logging around the helpers to include `user_id`, `session_id`, and `state` if available.
- Let exceptions propagate to the WS/HTTP caller.

Follow-up in WS path:
- Keep `_handle_chat_message_ws` lean: log and return without sending an error chunk.
- Ensure no stacktraces are sent to clients.

Tests:
- Add/adjust a unit test to assert that `process_message` exceptions propagate (and no stacktrace chunk is yielded).
- If a WS error chunk is added, add an integration test that validates the minimal error message.

### 4) Consolidate profile creation
Goal: one shared path for profile creation and updates across WS + HTTP.

Proposed change:
- Add a helper in `src/psychoanalyst_app/orchestration/profile_helpers.py`:
  - `ensure_user_profile(trio_db_service, user_id, defaults)`
  - This should use `merge_user_profile` and never advance workflow (orchestrator-owned).

Apply updates:
- `src/psychoanalyst_app/api/ws_handler.py`: replace the manual `UserProfile(...)` creation with the helper (no workflow advance).
- `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py`: reuse the helper for NEW-state placeholder creation.
- Keep `create_user_profile` for explicit profile updates, but perform any transitions inside the orchestrator after the helper returns.

Tests:
- Add a unit test for the new helper to verify profile merge defaults and status.
- Update or add an integration test ensuring WS auto-profiles remain `PROFILE_ONLY` and do not advance workflow unless explicitly updated.

### 5) Remove legacy agent code paths
Goal: eliminate unused compatibility code.

Targets:
- `src/psychoanalyst_app/agents/trio_psychoanalyst_agent.py`
  - Remove `get_initial_prompt_legacy` and any references.
  - Remove legacy-mode wording in docstrings/comments.
  - Drop unused constructor args (e.g., `conversation_manager`) if not used.
- `src/psychoanalyst_app/agents/trio_assessment_agent.py`
  - Remove legacy-mode wording in docstrings/comments.
  - Ensure constructor signature matches actual usage in `ServiceContainer`.

Tests:
- Update any tests that instantiate agents with removed params.
- Ensure all agent integration tests still pass.

### 6) Validation and regression checks
- Run the most relevant tests in Docker:
  - `make docker-test-one TEST=tests/integration/test_trio_orchestration.py`
  - `make docker-test-one TEST=tests/unit/test_trio_agent_orchestrator.py`
- If WS error handling changes, run the WS protocol integration test suite.

## Acceptance Criteria
- `TrioAgentOrchestrator.process_message` is decomposed into helpers; behavior is unchanged for normal flows.
- Stacktraces are no longer sent to clients; errors are logged and re-raised.
- WS profile creation uses the shared helper and matches HTTP profile semantics.
- Legacy agent methods and compatibility code paths are removed.
- All relevant tests pass, with updates made for any signature changes.

## Risks and Mitigations
- **Behavior drift during refactor**: mitigate with stepwise extraction and targeted tests.
- **Unexpected workflow transitions on auto-profile creation**: ensure `advance_workflow=False` for WS and NEW-state placeholder paths.
- **Client-visible error regressions**: decide and document minimal error handling in WS handler.

## Rollback Plan
- Keep refactor steps small and atomic so that reverting individual commits is straightforward.
- If WS behavior changes unexpectedly, revert only the WS/profile helper change and restore the prior profile creation logic.
