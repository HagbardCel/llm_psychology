# Real LLM Test Failure Debugging Plan

## Issue Summary

**Test**: `tests/integration/test_natural_patient_flow.py::test_natural_patient_flow --no-mocks`
**Status**: ✅ Server initialization fixed, ❌ New issue with real LLM
**Error**: `AssertionError: Failed to complete Assessment. Current state: WorkflowState.ASSESSMENT_IN_PROGRESS`

## Root Cause Analysis

### The Failure Sequence

1. ✅ **Intake Phase Completes** - User provides information, transitions to ASSESSMENT
2. ✅ **Assessment Agent Provides Recommendations** - CBT, Freud, Jung recommendations generated
3. ✅ **User Selects CBT** - "I'd like to try CBT" message sent
4. ✅ **Assessment Agent Calls Planning Agent** - `create_initial_plan_with_style()` called
5. ❌ **RAG Retrieval Gets Cancelled** - During plan creation, RAG call is interrupted
6. ❌ **Plan Creation Fails** - Therapy plan is never created
7. ❌ **State Never Transitions** - Remains in `ASSESSMENT_IN_PROGRESS` instead of `ASSESSMENT_COMPLETE`

### Evidence from Debug Output

```
DEBUG: _get_relevant_knowledge style=cbt
DEBUG: self.rag_service type: <class 'services.rag_service.RAGService'>
DEBUG: knowledge_source=cbt.md
DEBUG: calling rag_service.retrieve_relevant_knowledge with filter
DEBUG: _get_relevant_knowledge CANCELLED  ⚠️ PROBLEM HERE
```

**Critical Finding**: The RAG retrieval is cancelled, but NOT by the 30-second timeout in [trio_planning_agent.py:468](src/agents/trio_planning_agent.py#L468). The cancellation comes from a **parent scope**.

### Why This Doesn't Happen with Mocks

With mocks:
- LLM calls return instantly
- RAG calls are mocked (no actual vector search)
- Total processing time: ~2 seconds
- Everything completes before any timeouts

With real LLM:
- Gemini API calls take 5-15 seconds
- RAG retrieval with real embeddings: 2-5 seconds
- Plan creation involves multiple sequential LLM calls
- Total processing time: 20-30+ seconds
- **Something cancels the operation before completion**

## Problem Diagnosis

### Location: [src/agents/trio_planning_agent.py:460-502](src/agents/trio_planning_agent.py#L460-L502)

```python
async def _get_relevant_knowledge(self, session_text: str, therapy_style: str | None):
    try:
        with trio.move_on_after(30) as cancel_scope:  # 30 second timeout
            if therapy_style and style_service.get_style_pack(therapy_style):
                return await trio.to_thread.run_sync(
                    self.rag_service.retrieve_relevant_knowledge,
                    session_text,
                    3,
                    knowledge_source,  # ⚠️ Filtered retrieval taking longer
                )
        # ...
    except trio.Cancelled:  # ⚠️ This is being caught!
        print("DEBUG: _get_relevant_knowledge CANCELLED")
        raise
```

**Issue**: `trio.Cancelled` is raised, meaning a **parent nursery is cancelling** the operation.

### Possible Cancellation Sources

#### 1. **WebSocket Message Handler Timeout** (Most Likely)
**Location**: Test's message flow doesn't wait for completion

The test sends "I'd like to try CBT" and immediately continues:
```python
# Test sends CBT selection
await ws.send_message(json.dumps({...}))
await trio.sleep(2 if not use_real_llm else 5)  # Only 5 seconds!

# Then immediately checks state
with trio.move_on_after(10):  # Another 10 seconds
    while state != ASSESSMENT_COMPLETE:
        await trio.sleep(0.5)
```

**Problem**: The message processing happens asynchronously via WebSocket streaming. The test doesn't wait for the **actual processing** to complete - it just waits for the stream to start.

#### 2. **WebSocket Receiver Nursery Cancellation**
**Location**: [test_natural_patient_flow.py:298-312](tests/integration/test_natural_patient_flow.py#L298-L312)

```python
async def websocket_receiver(ws):
    try:
        while True:
            message = await ws.get_message()
            # Process message...
    except Exception:
        pass  # Silently swallows exceptions

async with open_websocket_url(ws_url) as ws:
    async with trio.open_nursery() as nursery:
        nursery.start_soon(websocket_receiver, ws)
        # ... test continues ...
        # Eventually: nursery.cancel_scope.cancel()  ⚠️ Cancels everything!
```

**Problem**: When the test finishes (even if waiting for state), the nursery gets cancelled, which propagates to all child tasks including ongoing message processing.

#### 3. **Concurrent Message Processing**
**Issue**: Test sends multiple messages rapidly. If messages overlap, the conversation manager might cancel previous operations.

#### 4. **Real LLM Timing**
With real Gemini API:
- Assessment recommendations: ~10-15 seconds
- Plan creation RAG retrieval: ~3-5 seconds
- Plan creation LLM call: ~5-10 seconds
- **Total**: 18-30 seconds

Test only gives: 5s sleep + 10s polling = **15 seconds max**

## Proposed Solutions

### Solution 1: Increase Test Timeouts (QUICK FIX)

**Estimated Time**: 15 minutes
**Risk**: Low
**Effectiveness**: May not fix root cause

**Changes**:

```python
# In test_natural_patient_flow.py

# After sending CBT selection
await trio.sleep(2 if not use_real_llm else 15)  # Increase from 5 to 15

# Check for transition with longer timeout
with trio.move_on_after(30 if use_real_llm else 10):  # Increase from 10 to 30
    while True:
        state = await orchestrator.get_user_state(user_id)
        if state == WorkflowState.ASSESSMENT_COMPLETE:
            break
        await trio.sleep(0.5)
```

**Pros**:
- ✅ Simple, minimal changes
- ✅ Gives real LLM operations time to complete

**Cons**:
- ❌ Doesn't fix cancellation issue
- ❌ Tests become slower
- ❌ Might still fail under load

---

### Solution 2: Wait for Message Processing Completion (RECOMMENDED)

**Estimated Time**: 1-2 hours
**Risk**: Medium
**Effectiveness**: Addresses root cause

**Problem**: Test doesn't wait for message processing to complete - it just sends and continues.

**Implementation**:

#### 2a. Add Message Acknowledgment System

```python
# In trio_server.py - WebSocket handler
async def _handle_chat_message_ws(self, raw_message: str, session_id: str, user_id: str):
    try:
        # ... existing code ...

        # Stream response chunks
        async for chunk in self.orchestrator.process_message(...):
            await websocket.send(json.dumps({
                "type": "chat_response_chunk",
                "data": {"chunk": chunk, "is_complete": False},
            }))

        # Send completion AFTER all processing (including state transitions)
        await websocket.send(json.dumps({
            "type": "chat_response_chunk",
            "data": {"chunk": "", "is_complete": True},
        }))

        # NEW: Send processing_complete after state transitions
        await websocket.send(json.dumps({
            "type": "processing_complete",
            "data": {
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
            },
        }))
```

```python
# In test - wait for processing_complete
async def wait_for_message_processed(ws, timeout=60):
    """Wait for message processing to complete."""
    with trio.move_on_after(timeout):
        while True:
            message = await ws.get_message()
            data = json.loads(message)
            if data.get("type") == "processing_complete":
                return True
            await trio.sleep(0.1)
    return False

# Use in test
await ws.send_message(json.dumps({"type": "chat_message", ...}))
assert await wait_for_message_processed(ws, timeout=60 if use_real_llm else 10)
```

**Pros**:
- ✅ Fixes root cause - test waits for actual completion
- ✅ Explicit acknowledgment of processing
- ✅ Better test reliability

**Cons**:
- ❌ Requires server changes
- ❌ More complex test code

---

### Solution 3: Shield Critical Operations from Cancellation

**Estimated Time**: 1 hour
**Risk**: Low
**Effectiveness**: Prevents cancellation during plan creation

**Implementation**:

```python
# In trio_planning_agent.py - create_initial_plan method

async def create_initial_plan(
    self, intake_session: Session, selected_style: str | None = None
) -> TherapyPlan:
    """Create initial therapy plan (shielded from cancellation)."""
    print("DEBUG: TrioPlanningAgent.create_initial_plan started")

    # Shield the entire plan creation from cancellation
    async with trio.CancelScope(shield=True):
        # Analyze session context
        session_text = self._format_session_for_analysis(intake_session)
        session_context = self._analyze_session_context(intake_session)

        # Get relevant knowledge (with its own timeout)
        relevant_knowledge = await self._get_relevant_knowledge(
            session_text, selected_style
        )

        # Generate plan details
        plan_details = await self._generate_initial_plan_details(
            intake_session, session_context, strategy, relevant_knowledge
        )

        # Save plan
        therapy_plan = TherapyPlan(...)
        await self.db_service.save_therapy_plan(therapy_plan)

        return therapy_plan
```

**Pros**:
- ✅ Prevents cancellation during critical operations
- ✅ Ensures plan creation completes
- ✅ Minimal test changes needed

**Cons**:
- ❌ Might delay test completion if operation takes too long
- ❌ Could mask other timing issues

---

### Solution 4: Event-Based State Transition Notification (CLEANEST)

**Estimated Time**: 2-3 hours
**Risk**: Medium-High
**Effectiveness**: Best long-term solution

**Implementation**:

```python
# Create event system for state transitions
class WorkflowEventBus:
    def __init__(self):
        self._channels = {}

    async def send_event(self, user_id: str, event: WorkflowEvent):
        """Send event to all subscribers for this user."""
        if user_id in self._channels:
            await self._channels[user_id].send(event)

    def subscribe(self, user_id: str) -> trio.MemoryReceiveChannel:
        """Subscribe to events for a user."""
        send_channel, receive_channel = trio.open_memory_channel(100)
        self._channels[user_id] = send_channel
        return receive_channel

# In TrioWorkflowEngine
async def transition_state(self, user_id: str, new_state: WorkflowState):
    """Transition user to new state and notify subscribers."""
    # ... update state in DB ...

    # Notify subscribers
    await self.event_bus.send_event(user_id, WorkflowEvent(
        event_type="state_transition",
        user_id=user_id,
        new_state=new_state,
        timestamp=datetime.now(),
    ))

# In test
event_channel = test_server["orchestrator"].workflow_engine.event_bus.subscribe(user_id)

# Send message
await ws.send_message(...)

# Wait for specific state transition event
with trio.fail_after(30):
    async for event in event_channel:
        if event.new_state == WorkflowState.ASSESSMENT_COMPLETE:
            break
```

**Pros**:
- ✅ Elegant, event-driven design
- ✅ No polling needed
- ✅ Immediate notification of state changes
- ✅ Decoupled test and implementation

**Cons**:
- ❌ Significant architectural change
- ❌ Requires changes across multiple components
- ❌ Higher implementation time

---

## Comparison Matrix

| Solution | Time | Complexity | Reliability | Long-term Value |
|----------|------|------------|-------------|-----------------|
| 1. Increase Timeouts | 15min | Low | Medium | Low |
| 2. Message Acknowledgment | 1-2h | Medium | High | High |
| 3. Shield Operations | 1h | Low | Medium-High | Medium |
| 4. Event-Based System | 2-3h | High | Very High | Very High |

## Recommended Approach

**Phase 1 (Immediate)**: Solution 3 (Shield Operations)
- Quick win to prevent cancellation
- Minimal changes
- Gets tests passing with real LLM

**Phase 2 (Next Sprint)**: Solution 2 (Message Acknowledgment)
- Better test reliability
- Explicit completion signals
- Moderate effort

**Phase 3 (Future)**: Solution 4 (Event-Based System)
- Best architecture
- Reusable for other tests
- Consider for major refactor

## Additional Improvements

### 1. Add Timeout Configuration

```python
# In config.py
class Settings:
    # ... existing settings ...
    PLAN_CREATION_TIMEOUT: int = 60  # seconds
    RAG_RETRIEVAL_TIMEOUT: int = 30  # seconds
    LLM_GENERATION_TIMEOUT: int = 45  # seconds
```

### 2. Add Better Logging

```python
# In planning agent
logger.info(f"Starting plan creation for {selected_style} (may take 20-30s)")
logger.info(f"RAG retrieval started for {knowledge_source}")
logger.info(f"RAG retrieval completed: {len(results)} results")
logger.info(f"Plan creation completed: {plan_id}")
```

### 3. Add Progress Indicators

```python
# Stream progress updates during long operations
await websocket.send(json.dumps({
    "type": "progress_update",
    "data": {
        "stage": "rag_retrieval",
        "message": "Retrieving relevant therapy knowledge...",
    },
}))
```

## Testing Strategy

### Step 1: Reproduce Consistently
```bash
# Run multiple times to confirm failure pattern
for i in {1..5}; do
    pytest tests/integration/test_natural_patient_flow.py --no-mocks -v
done
```

### Step 2: Add Instrumentation
```python
# Add timing logs to understand bottlenecks
import time
start = time.time()
result = await operation()
print(f"Operation took {time.time() - start:.2f}s")
```

### Step 3: Implement Solution
Choose solution based on timeline and requirements

### Step 4: Verify Fix
```bash
# Test with real LLM multiple times
pytest tests/integration/test_natural_patient_flow.py --no-mocks -v -x
```

### Step 5: Performance Testing
```bash
# Measure actual timing with real LLM
pytest tests/integration/test_natural_patient_flow.py --no-mocks -v --durations=0
```

## Expected Outcomes

After implementing recommended solution:
1. ✅ Test passes reliably with `--no-mocks`
2. ✅ Plan creation completes without cancellation
3. ✅ State transitions to `ASSESSMENT_COMPLETE`
4. ✅ Test runtime: 60-90 seconds (acceptable for integration test)

## Files to Modify

**Solution 3 (Shield Operations)**:
1. [src/agents/trio_planning_agent.py](src/agents/trio_planning_agent.py) - Add shield to create_initial_plan
2. [tests/integration/test_natural_patient_flow.py](tests/integration/test_natural_patient_flow.py) - Increase timeouts

**Solution 2 (Message Acknowledgment)**:
1. [src/trio_server.py](src/trio_server.py) - Add processing_complete message
2. [tests/integration/test_natural_patient_flow.py](tests/integration/test_natural_patient_flow.py) - Wait for acknowledgment
3. [tests/integration/test_console_ui_patient_flow.py](tests/integration/test_console_ui_patient_flow.py) - Same pattern

## Priority

**HIGH** - Blocks real LLM testing and validation of production behavior.

## Next Steps

1. Review this plan and choose solution based on time constraints
2. Implement chosen solution
3. Test with real LLM (multiple runs)
4. Update other integration tests if needed
5. Document real LLM test expectations and timing
