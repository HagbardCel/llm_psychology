# Phase 2 Architectural Improvements - Revised Approach

This document captures the recommended improvements for Phase 2 of the Session Resumption Implementation Plan.

## Overview

The original Phase 2 plan proposed implementing `stream_initial_greeting` in the Psychoanalyst Agent and refactoring the server to use it. This revision provides a cleaner, simpler architecture that avoids code smells and maintains proper separation of concerns.

---

## Task 2.1: Implement `stream_initial_greeting` in Psychoanalyst Agent

### Original Approach Issues

1. **Dummy session_id**: Creating a temp context with `session_id="greeting_generation"` is a code smell
2. **Wrong responsibility**: The `ConversationManager.stream_response()` expects a real conversation context, not a greeting-only pseudo-context
3. **Violation of separation of concerns**: The agent shouldn't need to know about ConversationContext internals

### Revised Implementation

**File:** `src/agents/trio_psychoanalyst_agent.py`

```python
async def stream_initial_greeting(
    self,
    user_profile: UserProfile,
    therapy_plan: TherapyPlan
) -> AsyncIterator[str]:
    """
    Stream the initial greeting for a resuming therapy session.

    This method generates a contextual greeting based on the session briefing
    stored in the therapy plan. It streams the response directly from the LLM
    without involving the conversation manager.

    Args:
        user_profile: The user's profile
        therapy_plan: The therapy plan with session_briefing

    Returns:
        AsyncIterator yielding greeting text chunks

    Raises:
        ValueError: If therapy plan or session_briefing is missing
    """
    if not therapy_plan or not therapy_plan.session_briefing:
        raise ValueError("Therapy plan with session briefing required for greeting generation")

    briefing = therapy_plan.session_briefing
    status = self.get_briefing_status(briefing)

    # Build the system prompt using existing helper method
    system_prompt = await self._build_resumption_prompt(
        user_profile,
        therapy_plan,
        briefing,
        status
    )

    # Stream directly from LLM service without involving conversation manager
    # This is a one-off greeting, not part of ongoing conversation
    logger.info(f"Streaming initial greeting for user {user_profile.user_id}")

    # Use trio.to_thread.run_sync to handle the synchronous LLM streaming
    # Note: This assumes LLMService has a stream_response method
    async for chunk in trio.to_thread.run_sync(
        self.llm_service.stream_response,
        system_prompt,
        []  # No message history for initial greeting
    ):
        yield chunk
```

### Rationale

- **No dummy contexts**: Avoids creating fake ConversationContext objects
- **Direct LLM streaming**: Simpler, cleaner approach - greeting is not part of ongoing conversation
- **Clear separation**: Greeting generation is distinct from conversation management
- **Reuses existing logic**: Leverages `_build_resumption_prompt` and `get_briefing_status`

---

## Task 2.2: Refactor Server to Use the New Agent Method

### Original Approach Issues

1. **Orchestrator involvement**: Line 161 in original plan calls `get_or_create_agent` which involves orchestrator unnecessarily
2. **Over-engineering**: The greeting is a simple one-off operation, doesn't need full orchestrator context

### Revised Implementation

**File:** `src/trio_server.py`

#### Step 1: Create `_send_resumption_greeting` Method

```python
async def _send_resumption_greeting(
    self,
    user_id: str,
    session_id: str,
    send_channel
) -> None:
    """
    Send contextual resumption greeting by streaming from the Psychoanalyst Agent.

    This method creates a minimal agent instance just for greeting generation,
    without involving the full orchestrator machinery.

    Args:
        user_id: The user's ID
        session_id: The current session ID
        send_channel: Trio memory channel for sending WebSocket messages

    Raises:
        ValueError: If therapy plan or user profile not found
        Exception: Any errors during greeting generation (fail-fast)
    """
    logger.info(f"Generating resumption greeting for user {user_id}")

    # Fetch required data
    therapy_plan = await self.db_service.get_latest_therapy_plan(user_id)
    if not therapy_plan or not therapy_plan.session_briefing:
        raise ValueError(
            f"Therapy plan with session briefing not found for user {user_id}. "
            "Cannot generate contextual greeting."
        )

    user_profile = await self.db_service.get_user_profile(user_id)
    if not user_profile:
        raise ValueError(f"User profile not found for user {user_id}")

    # Create a minimal agent instance for greeting generation
    # No need for orchestrator or conversation manager - just generating a greeting
    agent = TrioPsychoanalystAgent(
        llm_service=self.llm_service,
        db_service=self.db_service,
        rag_service=self.rag_service,
        user_context=None,  # Not needed for greeting
        conversation_manager=None  # Not needed for greeting
    )

    # Stream the greeting directly from the agent
    try:
        async for chunk in agent.stream_initial_greeting(user_profile, therapy_plan):
            await send_channel.send({
                "type": "chat_response_chunk",
                "data": {
                    "chunk": chunk,
                    "session_id": session_id,
                    "is_complete": False,
                    "timestamp": datetime.now().isoformat()
                }
            })

        # Send completion marker
        await send_channel.send({
            "type": "chat_response_chunk",
            "data": {
                "chunk": "",
                "session_id": session_id,
                "is_complete": True,
                "timestamp": datetime.now().isoformat()
            }
        })

        logger.info(f"Successfully streamed resumption greeting for user {user_id}")

    except Exception as e:
        logger.error(f"Error streaming resumption greeting: {e}", exc_info=True)
        raise  # Fail-fast: propagate errors to caller
```

#### Step 2: Update `_handle_session_request_ws`

Replace the current "empty message" workaround (lines 341-382 in current implementation) with:

```python
# Around line 341 in current code
if has_initial_message:
    if state == WorkflowState.PLAN_COMPLETE:
        # Contextual resumption greeting for returning users
        logger.info(f"Sending contextual resumption greeting for user {user_id}")

        try:
            # Call the new, clean method
            await self._send_resumption_greeting(user_id, session_id, send_channel)
            # Early return - greeting is complete
            return

        except Exception as e:
            logger.error(f"Error sending resumption greeting: {e}", exc_info=True)
            # Fail-fast: propagate error
            raise

    elif state == WorkflowState.NEW:
        # Simple welcome for NEW users (keep existing logic)
        logger.info(f"Sending initial greeting for NEW user {user_id}")
        welcome_message = (
            "Hello! Welcome to your virtual therapy session. "
            "I'm here to support you through this journey. "
            "To begin, could you please tell me your name?"
        )
        # ... existing streaming logic ...
```

### Benefits of Revised Approach

1. **Simpler**: No orchestrator involvement for a simple greeting
2. **Cleaner separation**: Greeting generation is isolated from conversation flow
3. **Easier to test**: Can test greeting generation independently
4. **Fail-fast**: Errors propagate properly without complex error handling
5. **Maintainable**: Clear, single-purpose methods

---

## Implementation Notes

### LLM Service Streaming

The revised approach assumes `LLMService` has a `stream_response` method. If this doesn't exist, you'll need to:

1. Add streaming support to `LLMService`, or
2. Fall back to non-streaming generation with simulated streaming

Example fallback:
```python
# If LLMService doesn't support streaming
response = await trio.to_thread.run_sync(
    self.llm_service.generate_response,
    system_prompt,
    []
)

# Simulate streaming by yielding chunks
chunk_size = 50
for i in range(0, len(response), chunk_size):
    yield response[i:i+chunk_size]
    await trio.sleep(0.05)  # Small delay for progressive rendering
```

### Testing Considerations

The revised architecture is easier to test:

```python
# Test greeting generation in isolation
async def test_stream_initial_greeting():
    agent = TrioPsychoanalystAgent(mock_llm, mock_db, mock_rag)

    chunks = []
    async for chunk in agent.stream_initial_greeting(user_profile, therapy_plan):
        chunks.append(chunk)

    assert len(chunks) > 0
    full_greeting = "".join(chunks)
    assert "your previous session" in full_greeting.lower()
```

---

## Migration Path

1. Implement `stream_initial_greeting` in `TrioPsychoanalystAgent`
2. Add unit tests for the new method
3. Implement `_send_resumption_greeting` in `TrioServer`
4. Update `_handle_session_request_ws` to use new method
5. Add integration test for full flow
6. Remove old "empty message" workaround

---

## Comparison: Original vs. Revised

| Aspect | Original Approach | Revised Approach |
|--------|------------------|------------------|
| **Orchestrator** | Involved via `get_or_create_agent` | Not involved |
| **ConversationContext** | Creates dummy context | Not needed |
| **ConversationManager** | Used for streaming | Not involved |
| **Complexity** | Higher (more moving parts) | Lower (direct streaming) |
| **Testability** | Harder (needs mocking orchestrator) | Easier (simple unit test) |
| **Code smell** | Dummy session_id | None |
| **Separation of concerns** | Violated (agent knows about context) | Clean (agent just generates greeting) |

---

## Conclusion

The revised approach provides a cleaner, simpler architecture that:
- Eliminates code smells (dummy contexts)
- Reduces complexity (no orchestrator for simple task)
- Improves testability (isolated methods)
- Maintains fail-fast behavior (proper error propagation)
- Preserves existing logic (reuses `_build_resumption_prompt`)

This approach should be used instead of the original Phase 2 plan.
