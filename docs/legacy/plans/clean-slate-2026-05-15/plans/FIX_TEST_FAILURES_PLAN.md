# Fix Test Failures Plan

## 1. Executive Summary
This plan addresses the test failures identified in the backend test suite (`make test`). The failures stem from recent refactors (renaming `Session` to `SessionBlock`), missing methods in the database service facade, incorrect mocking of async generators, and race conditions in WebSocket registration during session transitions.

## 2. Identified Issues & Root Causes

### 2.1. ImportError: `Session` vs `SessionBlock`
**Symptoms:** `ImportError: cannot import name 'Session' from 'psychoanalyst_app.models.data_models'`
**Root Cause:** The `Session` model was renamed to `SessionBlock` in `src/psychoanalyst_app/models/data_models.py`, but several test files were not updated.
**Affected Files:**
- `tests/integration/test_trio_orchestration.py`
- `tests/integration/test_session_timer_endpoint.py`
- `tests/load_test_runner.py`

### 2.2. TypeError: Async Generator Mocking
**Symptoms:** `TypeError: 'async for' requires an object with __aiter__ method, got Mock` and `TypeError: object Mock can't be used in 'await' expression`
**Root Cause:**
1. `mock_llm_service` in `tests/conftest.py` mocked `stream_response` as a function returning a list, not an async generator.
2. `test_trio_orchestration.py` used `Mock()` for websockets, which are not awaitable when `ws.send()` is called.
**Affected Files:**
- `tests/conftest.py`
- `tests/integration/test_trio_orchestration.py`

### 2.3. AttributeError: Missing Service Methods
**Symptoms:**
- `AttributeError: 'TrioDatabaseService' object has no attribute 'get_recent_sessions'`
- `AttributeError: 'TrioDatabaseService' object has no attribute 'update_session_tier2'`
**Root Cause:** The `TrioDatabaseService` facade was missing delegation methods for `sessions_repo.get_recent_session_blocks` and `sessions_repo.update_session_block_tier2`, which are required by `TrioPsychoanalystAgent` and `OrchestratorHelpers`.
**Affected Files:**
- `src/psychoanalyst_app/services/trio_db_service.py`

### 2.4. RuntimeError: WebSocket Registration Race Condition
**Symptoms:** `RuntimeError: No WebSocket registered for session block ... when sending workflow_next_action`
**Root Cause:**
1. `TrioAgentOrchestrator.emit_workflow_next_action` enforces `require_websocket=True` by default.
2. During server-initiated session transitions (e.g., Intake -> Assessment), the backend creates a new session block and emits an action *before* the client (and `ws_handler`) has a chance to reconnect/register for the new session ID.
3. `start_session_block` was not migrating the existing user connection to the new session block.
**Affected Files:**
- `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`
- `src/psychoanalyst_app/api/workflow_routes.py`

### 2.5. ValueError: Persisting to Enriched Session
**Symptoms:** `ValueError: Failed to persist message` / `Session block ... not saved because it is already enriched`
**Root Cause:** In `test_natural_patient_flow.py`, a race condition allows `_send_initial_greeting` to try adding a message to a session block that has concurrently been ended and enriched (made immutable). This seems specific to the tight timing of the test environment.

## 3. Implementation Plan

### Phase 1: Fix Model Imports (Completed)
- [x] Replace `from psychoanalyst_app.models.data_models import Session` with `SessionBlock`.
- [x] Update instantiation `Session(...)` to `SessionBlock(...)` in all test files.

### Phase 2: Fix Mocks (Completed)
- [x] Update `tests/conftest.py`: Define `mock_stream_response` as an `async def` that `yields` chunks.
- [x] Update `tests/integration/test_trio_orchestration.py`: Use `AsyncMock()` for websockets and ensure `ws.closed = False`.

### Phase 3: Update TrioDatabaseService (Completed)
- [x] Add `get_recent_sessions` to `TrioDatabaseService` (delegating to `sessions_repo.get_recent_session_blocks`).
- [x] Add `update_session_tier2` to `TrioDatabaseService` (delegating to `sessions_repo.update_session_block_tier2`).

### Phase 4: Improve WebSocket Robustness (Completed)
- [x] Update `start_session_block` in `orchestrator_helpers.py` to automatically register the user's existing websocket for the new session block ID.
- [x] Update `end_session_block`, `_run_assessment_job`, and `_run_reflection_job` to call `_emit_next_action` with `require_websocket=False` to prevent crashes when users disconnect.
- [x] Update `select_therapy_style` in `workflow_routes.py` to use `require_websocket=False`.

## 4. Verification
- Run `make test` (backend tests).
- Verify `tests/integration/test_trio_orchestration.py` passes.
- Verify `tests/integration/test_session_timer_endpoint.py` passes.
- Verify `tests/integration/test_console_ui_patient_flow.py` passes.
