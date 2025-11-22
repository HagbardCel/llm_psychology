# Failing Tests Analysis

**Generated**: 2025-11-16
**Test Suite Status**: 113 passing (92.6%), 6 failing, 3 skipped
**Total Tests**: 122

This document provides a comprehensive analysis of the 6 remaining failing tests after the Trio migration test remediation effort.

---

## Summary

| Test | Category | Priority | Complexity |
|------|----------|----------|------------|
| test_websocket_chat_message_handler | Integration | High | Medium |
| test_websocket_structured_concurrency_cleanup | Integration | Medium | Low |
| test_init_with_temp_directories | Unit | Low | Low |
| test_update_therapy_plan_with_briefing | Unit | High | Medium |
| test_briefing_generation_failure_propagates | Unit | High | Low |
| test_process_reflection_updates_plan_with_briefing | Unit | High | Low |

---

## 1. test_websocket_chat_message_handler

**File**: `tests/integration/test_trio_websocket.py:114-156`
**Test Type**: Integration
**Priority**: High
**Estimated Fix Time**: 30 minutes

### What's Being Tested
Tests the WebSocket chat message handler's ability to process user messages and stream LLM responses through Trio memory channels. This validates the core conversational functionality of the therapy application.

### Why It's Important
This is a critical test for the main user interaction flow:
- Validates WebSocket message handling with structured concurrency
- Tests streaming response functionality (core feature for real-time chat)
- Ensures conversation manager integrates correctly with WebSocket handlers
- Verifies Trio memory channel communication pattern

### Failure Reason
**Error**: `TypeError: object Mock can't be used in 'await' expression`
**Location**: `src/orchestration/trio_conversation_manager.py:140`
**Root Cause**: The mock LLM service in `conftest.py` doesn't implement async streaming

```python
# From error log:
ERROR orchestration.trio_conversation_manager:trio_conversation_manager.py:150
Error in LLM streaming: object Mock can't be used in 'await' expression

# Failing code in trio_conversation_manager.py:140
chunks = await self.llm_service.generate_response_stream(
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
```

The test creates a real session and calls the chat handler, which triggers the conversation manager's streaming response. The conversation manager tries to call `await self.llm_service.generate_response_stream()`, but the mock LLM service only has a synchronous generator function, not an async method.

### Fix Suggestions

**Option 1: Add async streaming to mock (Recommended)**
Update `conftest.py` to include async streaming method:

```python
@pytest.fixture
def mock_llm_service():
    llm_service = Mock()

    # Existing non-streaming mock
    llm_service.generate_response = Mock(return_value=json.dumps(briefing_response))

    # ADD: Async streaming mock
    async def mock_stream_response(*args, **kwargs):
        """Mock streaming response that yields chunks."""
        chunks = ["Hello ", "there! ", "This ", "is ", "a ", "mock ", "response."]
        for chunk in chunks:
            yield chunk

    llm_service.generate_response_stream = mock_stream_response  # ADD THIS LINE

    return llm_service
```

**Option 2: Mock the conversation manager's streaming method**
Instead of mocking the LLM service, mock the conversation manager's `_stream_llm_response` method directly in the test.

**Option 3: Use AsyncMock**
Replace the Mock with AsyncMock from unittest.mock:
```python
from unittest.mock import AsyncMock
llm_service.generate_response_stream = AsyncMock(return_value=iter(["chunk1", "chunk2"]))
```

**Recommended**: Option 1 - it's the most realistic and tests the full integration path.

---

## 2. test_websocket_structured_concurrency_cleanup

**File**: `tests/integration/test_trio_websocket.py:337-364`
**Test Type**: Integration
**Priority**: Medium
**Estimated Fix Time**: 15 minutes

### What's Being Tested
Validates that Trio's structured concurrency properly cleans up tasks when an error occurs in one task within a nursery. Tests the fundamental guarantee of Trio: all tasks are either completed or cancelled, preventing orphaned tasks.

### Why It's Important
This test validates critical Trio behavior:
- Ensures no orphaned tasks or resource leaks
- Confirms cleanup code (finally blocks) executes even when errors occur
- Verifies structured concurrency guarantees that prevent common async bugs
- Tests error propagation through Trio nurseries

### Failure Reason
**Error**: Test expects `pytest.raises(ValueError)` but Trio wraps exceptions in `ExceptionGroup`
**Root Cause**: Trio's structured concurrency wraps multiple exceptions in ExceptionGroup, which is correct behavior since Python 3.11

```python
# Test code (line 357-360)
with pytest.raises(ValueError):
    async with trio.open_nursery() as nursery:
        nursery.start_soon(failing_task)
        nursery.start_soon(normal_task)

# Actual error raised:
ExceptionGroup: Exceptions from Trio nursery (1 sub-exception)
  +---------------- 1 ----------------
    | ValueError: Intentional error for testing
```

The test assertion is outdated - it expects a bare ValueError, but Trio correctly wraps it in ExceptionGroup per PEP 654.

### Fix Suggestions

**Option 1: Use pytest.raises with ExceptionGroup (Recommended)**
Update the test to expect ExceptionGroup:

```python
@pytest.mark.trio
@pytest.mark.integration
async def test_websocket_structured_concurrency_cleanup(trio_server):
    """Test that structured concurrency properly cleans up on error."""
    send_channel, receive_channel = trio.open_memory_channel(10)

    cleanup_called = []

    async def failing_task():
        try:
            await trio.sleep(0.1)
            raise ValueError("Intentional error for testing")
        finally:
            cleanup_called.append("failing_task")

    async def normal_task():
        try:
            await trio.sleep(1)  # Should be cancelled
        finally:
            cleanup_called.append("normal_task")

    # UPDATED: Expect ExceptionGroup instead of bare ValueError
    with pytest.raises(ExceptionGroup) as exc_info:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(failing_task)
            nursery.start_soon(normal_task)

    # Verify the ValueError is inside the ExceptionGroup
    assert any(isinstance(e, ValueError) for e in exc_info.value.exceptions)

    # Verify both tasks ran their cleanup
    assert "failing_task" in cleanup_called
    assert "normal_task" in cleanup_called
```

**Option 2: Extract the inner exception**
Use Trio's exception handling utilities to extract the ValueError.

**Recommended**: Option 1 - it correctly tests Trio's actual behavior and is more future-proof.

---

## 3. test_init_with_temp_directories

**File**: `tests/unit/test_rag_service.py:89`
**Test Type**: Unit (Integration section)
**Priority**: Low
**Estimated Fix Time**: 10 minutes

### What's Being Tested
Tests RAG service initialization with temporary directories, verifying that the service correctly creates and initializes ChromaDB collections for domain knowledge.

### Why It's Important
- Validates RAG service can initialize with custom directories (important for testing)
- Tests domain knowledge collection creation
- Ensures knowledge sources are properly loaded

However, this is marked as an integration test despite being in the unit test file, and may be testing internal implementation details rather than public API.

### Failure Reason
**Error**: `AttributeError: 'RAGService' object has no attribute 'domain_collection'`
**Root Cause**: The test expects an attribute that doesn't exist in the RAGService implementation

```python
# Test code (line 89)
assert rag_service.domain_collection is not None

# Error
AttributeError: 'RAGService' object has no attribute 'domain_collection'
```

The RAGService implementation may have changed to not expose `domain_collection` as a public attribute, or the attribute was never intended to be public.

### Fix Suggestions

**Option 1: Remove the test (Recommended for cleanup)**
If `domain_collection` is an internal implementation detail:
- Check if there's another integration test that validates RAG initialization
- If yes, remove this test as it's testing implementation details
- If no, refactor to test public API behavior instead

**Option 2: Update test to use public API**
Replace attribute check with behavioral test:
```python
async def test_init_with_temp_directories(self):
    """Test that RAG service initializes correctly with temp directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = Config()
        config.VECTOR_DB_PATH = tmpdir

        rag_service = RAGService(config)

        # Test behavior, not internal state
        results = rag_service.retrieve_relevant_knowledge("test query")
        assert isinstance(results, list)  # Should return results even if empty
```

**Option 3: Fix the attribute name**
Check the RAGService source code to find the correct attribute name:
```bash
grep -n "collection" src/services/rag_service.py
```

**Recommended**: Option 1 if coverage exists elsewhere, otherwise Option 2 to test behavior.

---

## 4. test_update_therapy_plan_with_briefing

**File**: `tests/unit/test_trio_db_service.py:118-147`
**Test Type**: Unit
**Priority**: High
**Estimated Fix Time**: 20 minutes

### What's Being Tested
Tests the database service's ability to update an existing therapy plan with a new session briefing. This validates the core session resumption feature where briefings are stored and updated.

### Why It's Important
This is critical for the session resumption feature:
- Validates therapy plan update functionality
- Tests session briefing persistence (key feature for continuity)
- Ensures database operations handle complex nested JSON (briefing contains multiple layers)
- Tests transaction integrity for updates

### Failure Reason
**Error**: `UNIQUE constraint failed: therapy_plans.plan_id`
**Secondary Error**: `database is locked` during cleanup
**Root Cause**: Test is trying to INSERT a plan instead of UPDATE, causing constraint violation

```python
# From error log (line 444):
ERROR services.trio_db_service:trio_db_service.py:394
Error saving therapy plan: UNIQUE constraint failed: therapy_plans.plan_id

# Traceback (line 447):
File "/app/tests/../src/services/trio_db_service.py", line 373, in _sync_save_therapy_plan
    cursor.execute('''
sqlite3.IntegrityError: UNIQUE constraint failed: therapy_plans.plan_id
```

The test likely:
1. Creates and saves a therapy plan with `save_therapy_plan()`
2. Modifies the plan in memory (adds briefing)
3. Tries to save again with `save_therapy_plan()` instead of using an update method
4. Database tries to INSERT instead of UPDATE, causing constraint error

The database lock error is a symptom of the failed transaction not being properly rolled back.

### Fix Suggestions

**Option 1: Use update method if it exists (Recommended)**
Check if TrioDatabaseService has a dedicated update method:
```python
async def test_update_therapy_plan_with_briefing(test_db_service):
    # Create initial plan
    plan = TherapyPlan(...)
    await test_db_service.save_therapy_plan(plan)

    # Update with briefing
    plan.session_briefing = {...}
    success = await test_db_service.update_therapy_plan(plan)  # Use update, not save

    assert success is True
```

**Option 2: Implement UPDATE logic in save_therapy_plan**
If save_therapy_plan should handle both INSERT and UPDATE:
```python
# In trio_db_service.py _sync_save_therapy_plan:
cursor.execute('''
    INSERT INTO therapy_plans (...) VALUES (...)
    ON CONFLICT(plan_id) DO UPDATE SET
        session_briefing = excluded.session_briefing,
        updated_at = excluded.updated_at
    ...
''')
```

**Option 3: Delete and re-insert in test**
Crude but functional for testing:
```python
await test_db_service.delete_therapy_plan(plan.plan_id)
await test_db_service.save_therapy_plan(plan)
```

**Investigation needed**: Check `src/services/trio_db_service.py` to see:
1. Does `save_therapy_plan` support upsert (INSERT OR REPLACE)?
2. Is there a dedicated `update_therapy_plan` method?
3. What's the intended update pattern?

**Recommended**: Option 1 or 2 depending on what exists in the codebase.

---

## 5. test_briefing_generation_failure_propagates

**File**: `tests/unit/test_trio_reflection_agent.py:185-249`
**Test Type**: Unit
**Priority**: High
**Estimated Fix Time**: 5 minutes

### What's Being Tested
Tests that briefing generation failures propagate correctly (fail-fast behavior) rather than being silently swallowed. This validates error handling in the reflection agent's session briefing generation process.

### Why It's Important
This is a critical test for error handling:
- Ensures errors don't get swallowed (bug fix validation)
- Tests fail-fast behavior (important for debugging)
- Validates exception propagation through async call stack
- Prevents silent failures that would corrupt therapy plan data

This test specifically validates a bug fix where errors were being caught and logged but not propagated, making debugging difficult.

### Failure Reason
**Error**: `AttributeError: IN_SESSION`
**Root Cause**: Test uses non-existent WorkflowState enum value

```python
# Test code (line 240-243):
context = ConversationContext(
    session_id="test_session",
    user_profile=UserProfile(...),
    therapy_plan=therapy_plan,
    message_history=[],
    workflow_state=WorkflowState.IN_SESSION  # ERROR: This doesn't exist
)

# Error (line 545-547):
File "/usr/local/lib/python3.11/enum.py", line 786, in __getattr__
    raise AttributeError(name) from None
AttributeError: IN_SESSION
```

The WorkflowState enum has these values:
- NEW
- INTAKE_IN_PROGRESS
- INTAKE_COMPLETE
- ASSESSMENT_IN_PROGRESS
- ASSESSMENT_COMPLETE
- THERAPY_IN_PROGRESS  ← Should use this
- REFLECTION_IN_PROGRESS
- PLAN_COMPLETE

### Fix Suggestions

**Simple fix - Update enum value:**
```python
# In test_trio_reflection_agent.py, line 240
context = ConversationContext(
    session_id="test_session",
    user_profile=UserProfile(...),
    therapy_plan=therapy_plan,
    message_history=[],
    workflow_state=WorkflowState.THERAPY_IN_PROGRESS  # FIXED
)
```

**Alternative**: Use REFLECTION_IN_PROGRESS if that's more semantically correct for testing reflection agent.

**Recommended**: Use `WorkflowState.THERAPY_IN_PROGRESS` - quick one-line fix.

---

## 6. test_process_reflection_updates_plan_with_briefing

**File**: `tests/unit/test_trio_reflection_agent.py:254-319`
**Test Type**: Unit
**Priority**: High
**Estimated Fix Time**: 5 minutes

### What's Being Tested
Integration test of the full reflection workflow - validates that the reflection agent successfully processes a session, generates a briefing, and updates the therapy plan in the database.

### Why It's Important
This is a comprehensive end-to-end test for the reflection agent:
- Tests complete reflection workflow (session → briefing → plan update)
- Validates database integration (plan retrieval and update)
- Ensures briefing is properly persisted
- Tests workflow state transitions
- Verifies metadata propagation

This test ensures the session resumption feature works end-to-end.

### Failure Reason
**Error**: `AttributeError: IN_SESSION` (same as test #5)
**Root Cause**: Same enum value error

```python
# Test code (line 297-303):
context = ConversationContext(
    session_id=sample_session.session_id,
    user_profile=user_profile,
    therapy_plan=sample_therapy_plan,
    message_history=[],
    workflow_state=WorkflowState.IN_SESSION  # ERROR: Same as test #5
)

# Error (line 638-642):
AttributeError: IN_SESSION
```

### Fix Suggestions

**Same fix as test #5:**
```python
# In test_trio_reflection_agent.py, line 302
context = ConversationContext(
    session_id=sample_session.session_id,
    user_profile=user_profile,
    therapy_plan=sample_therapy_plan,
    message_history=[],
    workflow_state=WorkflowState.THERAPY_IN_PROGRESS  # FIXED
)
```

**Recommended**: Use `WorkflowState.THERAPY_IN_PROGRESS` - identical fix to test #5.

---

## Fix Priority Recommendation

### Immediate Fixes (< 10 minutes total)
1. **test_briefing_generation_failure_propagates** - Change `IN_SESSION` → `THERAPY_IN_PROGRESS`
2. **test_process_reflection_updates_plan_with_briefing** - Same enum fix

**Impact**: Fixes 2 critical tests for session resumption feature with trivial changes

### High Priority (30-60 minutes total)
3. **test_websocket_chat_message_handler** - Add async streaming to mock LLM service
4. **test_update_therapy_plan_with_briefing** - Investigate and fix database update logic

**Impact**: Fixes core WebSocket streaming and database persistence

### Medium Priority (20 minutes)
5. **test_websocket_structured_concurrency_cleanup** - Update to expect ExceptionGroup

**Impact**: Validates Trio cleanup guarantees

### Low Priority (Consider removing)
6. **test_init_with_temp_directories** - Remove if redundant, or refactor to test behavior

**Impact**: Low - may be testing implementation details

---

## Batch Fix Script

For the two quick enum fixes, create this script:

```bash
#!/bin/bash
# fix_workflow_state_enum.sh

# Fix test_briefing_generation_failure_propagates
sed -i 's/workflow_state=WorkflowState.IN_SESSION/workflow_state=WorkflowState.THERAPY_IN_PROGRESS/g' \
  tests/unit/test_trio_reflection_agent.py

echo "Fixed WorkflowState enum references in test_trio_reflection_agent.py"
```

---

## Testing After Fixes

```bash
# Test individual fixes
pytest tests/unit/test_trio_reflection_agent.py::test_briefing_generation_failure_propagates -v
pytest tests/unit/test_trio_reflection_agent.py::test_process_reflection_updates_plan_with_briefing -v

# Test WebSocket fixes
pytest tests/integration/test_trio_websocket.py::test_websocket_chat_message_handler -v
pytest tests/integration/test_trio_websocket.py::test_websocket_structured_concurrency_cleanup -v

# Full validation
make test-validate
```

---

## Expected Outcome

After all fixes:
- **Target**: 117 passing (95.9%), 0 failing, 5 skipped
- **Improvement**: +4 tests fixed from current state
- **Alternative (if test #6 removed)**: 116 passing (95.1%), 0 failing, 6 skipped

This would represent **98%+ pass rate** for non-skipped tests, meeting the project quality bar.
