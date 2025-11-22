# Async LLM Service Refactoring Plan

**Version:** 2.0
**Date:** 2025-11-12
**Status:** Planning
**Priority:** High (Fixes WebSocket disconnections)

---

## Executive Summary

This document outlines a comprehensive plan to refactor the `LLMService` from synchronous blocking calls to a fully asynchronous, non-blocking architecture with native streaming and automatic retries. This refactoring will resolve the critical WebSocket disconnection issue where clients time out during long-running LLM API calls and improve service resilience.

**Problem:** Synchronous LLM API calls block the asyncio event loop, preventing WebSocket heartbeat messages and causing client disconnections. The service also lacks resilience to transient API errors.

**Solution:** Convert `LLMService` to a pure `async`/`await` pattern with native streaming support. Implement exponential backoff and retries for all API calls using the `tenacity` library. All legacy synchronous code will be removed.

**Impact:** 8 files modified, ~20-25 test cases added/updated, estimated 4-6 hours implementation.

---

## Table of Contents

1. [Problem Analysis](#1-problem-analysis)
2. [Technical Approach](#2-technical-approach)
3. [Implementation Phases](#3-implementation-phases)
4. [Testing Strategy](#4-testing-strategy)
5. [Migration Guide](#5-migration-guide)
6. [Rollout Plan](#6-rollout-plan)
7. [Risks and Mitigation](#7-risks-and-mitigation)
8. [Success Criteria](#8-success-criteria)
9. [Appendices](#9-appendices)

---

## 1. Problem Analysis

### 1.1 Current State

**Blocking Calls Identified:**

| File | Line | Method | Impact |
|------|------|--------|--------|
| `conversation_manager.py` | 139 | `generate_response()` | HIGH - Main streaming path |
| `base_agent.py` | 68 | `generate_response()` | MEDIUM - Session initialization |
| `intake_agent.py` | 376, 439, 451 | `generate_response()` | MEDIUM - Intake flow |
| `psychoanalyst_agent.py` | 408, 465 | `generate_response()` | MEDIUM - Therapy sessions |

**Current Architecture:**

```
User Message → WebSocket Gateway → Agent Orchestrator
  → Conversation Manager → LLMService.generate_response() [BLOCKS EVENT LOOP]
    → LangChain ChatGoogleGenerativeAI.invoke() [Synchronous HTTP]
      → Gemini API (5-30 seconds)
```

### 1.2 Root Cause

The root cause is the synchronous nature of the `llm.invoke()` call inside an `async` application. This blocks the entire Python process, preventing the `asyncio` event loop from handling other tasks, such as the WebSocket ping/pong mechanism required to keep the connection alive.

**Timeline of Disconnection:**
1. Client sends message (t=0s)
2. Server calls blocking LLM API (t=0.1s)
3. Event loop blocked for 10-30 seconds
4. WebSocket ping/pong fails (t=10s)
5. Client timeout and disconnect (t=15s)
6. Server completes LLM call (t=20s) - but client is already gone
7. Client reconnects, losing context

### 1.3 User Impact

- **Frequent Disconnections:** Users are constantly disconnected during conversations.
- **Poor User Experience:** Sessions are interrupted, context is lost, and the application feels unreliable.
- **Data Loss:** Messages sent just before a disconnection may be lost.

---

## 2. Technical Approach

### 2.1 Design Principles

1.  **Async-First:** All I/O-bound operations, especially LLM calls, must be truly asynchronous.
2.  **Native Streaming:** Utilize the LLM provider's native streaming API for real-time feedback.
3.  **Resilience:** Automatically retry failed API calls with exponential backoff.
4.  **Clean API:** Remove all legacy synchronous code; no backward compatibility layer.
5.  **Testability:** Ensure high test coverage with `pytest-asyncio` and `AsyncMock`.

### 2.2 Technology Choices

-   **Async LLM Calls:** Use LangChain's native `ainvoke()` and `astream()` methods from `ChatGoogleGenerativeAI`.
-   **Retry Logic:** Use the `tenacity` library to add robust retry mechanisms to all LLM API calls.

### 2.3 Architecture Changes

**Target Architecture:**

```
User Message → WebSocket Gateway → Agent Orchestrator
  → Conversation Manager → await LLMService.stream_response()
    → @retry → await ChatGoogleGenerativeAI.astream() [Non-blocking]
      → Gemini API (streaming)
        → yield chunk1, chunk2, chunk3... (real-time)
```

**Key Changes:**
1.  `LLMService` becomes fully asynchronous.
2.  `generate_response()` and `stream_response()` are now `async` methods.
3.  All callers must use the `await` keyword.
4.  The fake chunking in `ConversationManager` is replaced with a direct call to the native streaming method.
5.  All synchronous LLM-related methods are removed.

### 2.4 Future Architectural Improvements

While not in the scope of this immediate refactoring, a future improvement would be to define a generic `LLMServiceInterface` ABC (Abstract Base Class). `LLMService` would then become `GoogleLLMService`, an implementation of that interface. This would make it easier to add other LLM providers (e.g., `AnthropicLLMService`) in the future by simply creating new implementations of the interface, promoting a more modular design.

---

## 3. Implementation Phases

### Phase 1: LLMService Core Refactoring

**Duration:** 2-3 hours

#### 3.1.1 Update LLMService Class

**File:** `src/services/llm_service.py`

**Changes:**

```python
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from exceptions import LLMServiceError
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

# Define specific, retryable exception types if possible. For now, use a broad base.
# In a real scenario, you might catch google.api_core.exceptions.ResourceExhausted
RETRYABLE_EXCEPTIONS = (Exception)

class LLMService:
    """Service for handling resilient, async LLM API calls with native streaming."""

    def __init__(self, api_key: str, model_name: str):
        """
        Initialize the LLM service.

        Args:
            api_key: Google Gemini API key.
            model_name: Name of the LLM model to use, passed from config.
        """
        self.api_key = api_key
        self.model_name = model_name
        self.llm = ChatGoogleGenerativeAI(
            model=self.model_name,
            google_api_key=self.api_key,
            temperature=0.7,
            streaming=True,
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying LLM call: attempt {retry_state.attempt_number}, waiting {retry_state.next_action.sleep}s..."
        )
    )
    async def generate_response(
        self, prompt: str, context: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """
        Generate a response from the LLM asynchronously with retries.

        Args:
            prompt: The prompt to send to the LLM.
            context: Optional conversation history.

        Returns:
            The LLM's complete response.

        Raises:
            LLMServiceError: If LLM generation fails after all retries.
        """
        try:
            messages = self._build_messages(prompt, context)
            response = await self.llm.ainvoke(messages)
            logger.info(f"Generated LLM response for prompt: {prompt[:100]}...")
            return response.content
        except Exception as e:
            logger.error(f"Error generating LLM response: {e}", exc_info=True)
            raise LLMServiceError(f"LLM generation failed: {e}") from e

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying LLM stream: attempt {retry_state.attempt_number}, waiting {retry_state.next_action.sleep}s..."
        )
    )
    async def stream_response(
        self, prompt: str, context: Optional[List[Dict[str, str]]] = None
    ) -> AsyncIterator[str]:
        """
        Stream LLM response chunks in real-time with retries.

        Args:
            prompt: The prompt to send to the LLM.
            context: Optional conversation history.

        Yields:
            Response chunks as they're generated by the LLM.

        Raises:
            LLMServiceError: If streaming fails after all retries.
        """
        try:
            messages = self._build_messages(prompt, context)
            logger.info(f"Starting LLM stream for prompt: {prompt[:100]}...")
            chunk_count = 0
            async for chunk in self.llm.astream(messages):
                if hasattr(chunk, 'content') and chunk.content:
                    chunk_count += 1
                    yield chunk.content
            logger.info(f"LLM stream complete: {chunk_count} chunks")
        except Exception as e:
            logger.error(f"Error streaming LLM response: {e}", exc_info=True)
            raise LLMServiceError(f"LLM streaming failed: {e}") from e

    def _build_messages(
        self, prompt: str, context: Optional[List[Dict[str, str]]] = None
    ) -> List:
        """Build message list for LLM API."""
        messages = []
        if context:
            for msg in context:
                if msg["role"] == "system":
                    messages.append(SystemMessage(content=msg["content"]))
                elif msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    messages.append(AIMessage(content=msg["content"]))
        messages.append(HumanMessage(content=prompt))
        return messages

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
    )
    async def generate_structured_response(
        self, prompt: str, output_format: str
    ) -> Dict[str, Any]:
        """
        Generate a structured response from the LLM asynchronously with retries.

        Args:
            prompt: The prompt to send to the LLM.
            output_format: Description of the expected output format.

        Returns:
            Structured response dictionary.

        Raises:
            LLMServiceError: If generation fails after all retries.
        """
        try:
            structured_prompt = f"""
            {prompt}

            Please provide your response in JSON format with the following structure:
            {output_format}

            Respond ONLY with valid JSON. Do not include any other text.
            """
            response = await self.llm.ainvoke([HumanMessage(content=structured_prompt)])
            return {"raw_response": response.content.strip()}
        except Exception as e:
            logger.error(f"Error generating structured LLM response: {e}", exc_info=True)
            raise LLMServiceError(f"Structured response generation failed: {e}") from e
```

---

### Phase 2: Conversation Manager Updates

**Duration:** 1 hour

#### 3.2.1 Update ConversationManager

**File:** `src/orchestration/conversation_manager.py`

**Changes:** The `_stream_llm_response` method is simplified to be a direct pass-through to the now fully async and resilient `LLMService`.

```python
async def _stream_llm_response(
    self, prompt: str, conversation_history: list
) -> AsyncIterator[str]:
    """
    Stream response from LLM service using native async streaming.

    Args:
        prompt: The prompt to send.
        conversation_history: Previous conversation messages.

    Yields:
        Response chunks as generated by LLM.

    Raises:
        LLMServiceError: If streaming fails.
    """
    try:
        # Use native async streaming - NO MORE BLOCKING!
        async for chunk in self.llm_service.stream_response(
            prompt, conversation_history
        ):
            yield chunk
    except Exception as e:
        logger.error(f"Error in LLM streaming: {e}", exc_info=True)
        raise
```

---

### Phase 3: Agent Updates

**Duration:** 1 hour

**Change:** All calls to `llm_service.generate_response()` must now be `await`ed.

#### 3.3.1 Update BaseAgent

**File:** `src/agents/base_agent.py`

```python
# BEFORE
initial_response = self.llm_service.generate_response(initial_prompt)

# AFTER
initial_response = await self.llm_service.generate_response(initial_prompt)
```

#### 3.3.2 Update IntakeAgent

**File:** `src/agents/intake_agent.py`

```python
# BEFORE
initial_response = self.llm_service.generate_response(initial_prompt)
response = self.llm_service.generate_response(formatted_prompt, context)
closing_response = self.llm_service.generate_response(closing_prompt)

# AFTER
initial_response = await self.llm_service.generate_response(initial_prompt)
response = await self.llm_service.generate_response(formatted_prompt, context)
closing_response = await self.llm_service.generate_response(closing_prompt)
```

#### 3.3.3 Update PsychoanalystAgent

**File:** `src/agents/psychoanalyst_agent.py`

```python
# BEFORE
return self.llm_service.generate_response(response_prompt, context_messages)
return self.llm_service.generate_response(closing_prompt)

# AFTER
return await self.llm_service.generate_response(response_prompt, context_messages)
return await self.llm_service.generate_response(closing_prompt)
```

---

### Phase 4: Testing Infrastructure

**Duration:** 2-3 hours

#### 3.4.1 Update Test Fixtures

**File:** `tests/conftest.py`

**Changes:** The mock service is updated to only provide `AsyncMock`s for the async methods.

```python
@pytest.fixture
def mock_llm_service():
    """Mock LLM service with async methods."""
    llm = Mock()

    llm.generate_response = AsyncMock(
        return_value="This is a mocked async response."
    )

    async def mock_stream():
        chunks = ["This ", "is ", "a ", "mocked ", "streaming ", "response."]
        for chunk in chunks:
            yield chunk
    llm.stream_response = mock_stream

    llm.generate_structured_response = AsyncMock(
        return_value={"key": "value"}
    )

    return llm
```

#### 3.4.2 Update Async LLMService Tests

**File:** `tests/unit/test_llm_service.py`

**Changes:** Tests are updated to call the new method names and the deprecation test is removed. A new test for the retry logic is added.

```python
# ... (existing async tests, with s/_async// on method names) ...

    @patch('tenacity.nap.time.sleep', return_value=None) # Don't actually sleep
    async def test_generate_response_retry_logic(self, mock_sleep, llm_service):
        """Test that generate_response retries on failure."""
        with patch.object(
            llm_service.llm, 'ainvoke', new_callable=AsyncMock
        ) as mock_ainvoke:
            # Fail twice, then succeed
            mock_ainvoke.side_effect = [
                Exception("API connection failed"),
                Exception("API still down"),
                AIMessage(content="Finally worked."),
            ]

            response = await llm_service.generate_response("Test prompt")

            assert response == "Finally worked."
            assert mock_ainvoke.call_count == 3
```

#### 3.4.3 Update Integration Test for Streaming

**File:** `tests/integration/test_streaming_websocket.py`

**Changes:** The concurrent test case is now fully implemented.

```python
# ... (existing test_websocket_streaming_no_disconnect test) ...

@pytest.mark.asyncio
async def test_concurrent_streams_no_blocking(
    test_server,
):
    """
    Test that multiple concurrent streaming requests don't block each other.
    """
    import socketio
    import asyncio

    async def run_client_session(user_id: str, message: str) -> str:
        """Simulates a single client connecting, sending a message, and streaming the response."""
        client = socketio.AsyncClient(logger=True, engineio_logger=True)
        auth = {'user_id': user_id, 'token': 'test_token'}
        full_response = []
        session_started = asyncio.Event()
        stream_finished = asyncio.Event()

        @client.on('session_started')
        def on_session_started(data):
            session_started.set()

        @client.on('chat_response_chunk')
        def on_chunk(data):
            full_response.append(data['chunk'])
            if data.get('is_complete'):
                stream_finished.set()

        await client.connect(test_server['ws_url'], auth=auth, transports=['websocket'])
        await client.emit('message', {'type': 'session_request', 'data': {'session_type': 'therapy'}})
        await asyncio.wait_for(session_started.wait(), timeout=5)
        
        session_id = client.get_sid()
        await client.emit('message', {'type': 'chat_message', 'data': {'message': message, 'session_id': session_id}})
        
        await asyncio.wait_for(stream_finished.wait(), timeout=15)
        await client.disconnect()
        return "".join(full_response)

    # Mock the LLM service to return a unique response for each client
    llm_service = test_server['container'].get('llm_service')
    
    async def slow_stream_responder(*args, **kwargs):
        prompt = args[0]
        if "Client 1" in prompt:
            response_text = "Response for client 1."
        elif "Client 2" in prompt:
            response_text = "Response for client 2."
        else:
            response_text = "Generic response."
        
        for word in response_text.split():
            await asyncio.sleep(0.2) # Simulate work
            yield word + " "

    llm_service.stream_response = slow_stream_responder

    # Run two clients concurrently
    start_time = asyncio.get_event_loop().time()
    results = await asyncio.gather(
        run_client_session("user1", "Message from Client 1"),
        run_client_session("user2", "Message from Client 2"),
    )
    end_time = asyncio.get_event_loop().time()

    # If blocking, total time would be > (0.2 * num_words * num_clients)
    # Non-blocking should be closer to (0.2 * num_words)
    assert (end_time - start_time) < 3.0 # Should be ~1.6s, well under 3s
    
    # Check that each client got its correct, unique response
    assert "Response for client 1." in results[0]
    assert "Response for client 2." in results[1]
```

---

## 5. Migration Guide

This refactoring involves breaking changes and requires a "cut-over" migration. There is no backward compatibility layer.

### 5.1 Code Migration Checklist

**For Developers:**

- [ ] Add `tenacity` to `requirements.in` and run `make dev-install`.
- [ ] Replace all `llm_service.generate_response(...)` calls with `await llm_service.generate_response(...)`.
- [ ] Replace all `llm_service.generate_structured_response(...)` calls with `await llm_service.generate_structured_response(...)`.
- [ ] Update `conversation_manager` to call `llm_service.stream_response(...)` directly.
- [ ] Update all test mocks and fixtures to use `AsyncMock` for the new async methods.
- [ ] Run the full test suite: `make test`.

### 5.2 Breaking Changes

-   **Method Removal:** The synchronous `generate_response` and `generate_structured_response` methods in `LLMService` have been **removed**.
-   **Async-Only API:** All methods in `LLMService` are now `async` and must be called with `await`.
-   **Method Rename:** The concept of `stream_response_async` has been renamed to `stream_response`.

---

## 6. Rollout Plan

The rollout plan remains largely the same, but the emphasis is on ensuring all parts of the codebase are updated simultaneously due to the lack of a backward compatibility layer.

**Day 1-2: Development & Testing**
- Implement all code changes as described above.
- Run `make test` continuously until all unit and integration tests pass.

**Day 3: Staging & Validation**
- Deploy the `main` branch to a staging environment.
- Perform manual testing with the console UI and web UI.
- Run automated load tests simulating 10+ concurrent users to validate the non-blocking behavior.

**Day 4: Deployment**
- Merge to `main` and deploy to production.
- Monitor logs and performance metrics closely.

---

## 7. Risks and Mitigation

| Risk | Severity | Probability | Mitigation |
|------|----------|-------------|------------|
| LangChain async API changes | Medium | Low | Pin `langchain-google-genai` version in `requirements.in`. |
| Breaking existing tests | High | High | This is guaranteed. A dedicated effort to update all tests is part of the plan. |
| Gemini API rate limits | Low | Medium | **Mitigated.** The new `LLMService` has built-in exponential backoff and retries. |
| Residual blocking calls | Medium | Low | Use `PYTHONASYNCIODEBUG=1` during testing and monitor event loop lag metrics. |

---

## 8. Success Criteria

### 8.1 Functional Requirements

-   ✅ WebSocket disconnections due to LLM blocking are eliminated (<1% rate).
-   ✅ The application gracefully handles transient LLM API errors.
-   ✅ All existing functionality is preserved and works asynchronously.
-   ✅ All tests pass.

### 8.2 Performance Requirements

-   ✅ Time to first chunk for streaming responses: < 1.5 seconds.
-   ✅ Event loop lag remains < 50ms during concurrent LLM streams.
-   ✅ The system supports 10+ concurrent streaming users without mutual blocking.

---

## 9. Appendices

### Appendix A: File Change Summary

| File | Lines Changed | Type |
|------|---------------|------|
| `src/services/llm_service.py` | ~200 | Major Rewrite |
| `src/orchestration/conversation_manager.py` | ~30 | Simplification |
| `src/agents/base_agent.py` | 1 | Add `await` |
| `src/agents/intake_agent.py` | 3 | Add `await` |
| `src/agents/psychoanalyst_agent.py` | 2 | Add `await` |
| `tests/conftest.py` | ~20 | Update mocks |
| `tests/unit/test_llm_service.py` | ~100 | Update tests, add retry test |
| `tests/integration/test_streaming_websocket.py` | ~100 | Implement concurrent test |
| **TOTAL** | **~456 lines** | **8 files** |

### Appendix B: Dependencies

**Required Package Versions:**
```txt
# requirements.in
langchain-google-genai==2.0.0  # Or latest stable with async support
langchain==0.3.0               # Or latest stable
tenacity==8.2.3                # For robust retry logic
aiohttp==3.9.0
pytest-asyncio==0.21.0
```

---
**End of Plan Document**
