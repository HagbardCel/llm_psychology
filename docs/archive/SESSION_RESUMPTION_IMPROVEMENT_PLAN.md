### **Improvement and Correction Plan for Session Resumption**

This plan is divided into three phases: critical bug fixing, architectural realignment, and comprehensive testing to ensure a robust and correct implementation.

---

### **Phase 1: Critical Bug Fixes & Database Correction**

**Objective:** Address the fatal database bug to make the feature functional on new installations.

#### **Task 1.1: Correct Database Schema Initialization**

*   **File:** `src/services/trio_db_service.py`
*   **Method:** `_sync_initialize`
*   **Action:** Modify the `CREATE TABLE IF NOT EXISTS therapy_plans` SQL statement to include the `session_briefing` column.

    **Current (Incorrect) Schema:**
    ```sql
    CREATE TABLE IF NOT EXISTS therapy_plans (
        plan_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        plan_details TEXT NOT NULL,
        version INTEGER NOT NULL,
        selected_therapy_style TEXT
    )
    ```

    **Required (Correct) Schema:**
    ```sql
    CREATE TABLE IF NOT EXISTS therapy_plans (
        plan_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        plan_details TEXT NOT NULL,
        version INTEGER NOT NULL,
        selected_therapy_style TEXT,
        session_briefing TEXT -- Add this line
    )
    ```

#### **Task 1.2: Correct Reflection Agent Error Handling**

*   **File:** `src/agents/trio_reflection_agent.py`
*   **Method:** `process_reflection`
*   **Action:** Remove the top-level `try...except` block that catches all exceptions. This will ensure that errors (like the briefing generation failure) propagate up to the orchestrator, adhering to the fail-fast principle.

    **Current (Incorrect) Logic:**
    ```python
    try:
        # ... main logic ...
        try:
            # ... briefing generation ...
            raise  # This re-raise is caught by the outer block
        except Exception as briefing_error:
            logger.error(...)
            raise
    except Exception as e:
        # This block prevents errors from propagating. It must be removed.
        return AgentResponse(
            content="...",
            metadata={"error": str(e)},
        )
    ```

    **Required (Correct) Logic:**
    The method should be refactored to let exceptions propagate naturally. The inner `try...except` around the briefing generation can remain if you want specific logging, but the outer block must be removed.

---

### **Phase 2: Architectural Realignment**

**Objective:** Refactor the agent and server to match the original, cleaner architecture where the agent is responsible for streaming.

#### **Task 2.1: Implement `stream_initial_greeting` in Psychoanalyst Agent**

*   **File:** `src/agents/trio_psychoanalyst_agent.py`
*   **Action:** Create the `stream_initial_greeting` async generator method as specified in the plan. This method will contain the logic to build the prompt and stream the LLM response.

    **Implementation:**
    ```python
    # In TrioPsychoanalystAgent class
    from typing import AsyncIterator
    from orchestration.models import ConversationContext # Or necessary models

    async def stream_initial_greeting(
        self,
        user_profile: UserProfile,
        therapy_plan: TherapyPlan
    ) -> AsyncIterator[str]:
        """
        Stream the initial greeting for a resuming therapy session.
        """
        if not therapy_plan or not therapy_plan.session_briefing:
            raise ValueError("Therapy plan with session briefing is required for greeting generation.")

        briefing = therapy_plan.session_briefing
        status = self.get_briefing_status(briefing)

        # Build the prompt using the existing helper method
        system_prompt = await self._build_resumption_prompt(
            user_profile,
            therapy_plan,
            briefing,
            status
        )

        # Create a temporary context for the conversation manager
        temp_context = ConversationContext(
            session_id="greeting_generation",
            user_profile=user_profile,
            therapy_plan=therapy_plan,
            message_history=[],
            # ... other required fields
        )

        # Use the conversation manager to stream the response
        logger.info(f"Streaming initial greeting for user {user_profile.user_id}")
        async for chunk in self.conversation_manager.stream_response(
            system_prompt,
            temp_context,
            use_rag=False
        ):
            yield chunk
    ```

#### **Task 2.2: Refactor Server to Use the New Agent Method**

*   **File:** `src/trio_server.py`
*   **Action:**
    1.  Create the `_send_resumption_greeting` method as originally planned.
    2.  Update `_handle_session_request_ws` to call this new method, removing the "empty message" workaround.

    **Implementation:**

    1.  **Create `_send_resumption_greeting`:**
        ```python
        # In TrioServer class
        async def _send_resumption_greeting(
            self,
            user_id: str,
            session_id: str,
            send_channel
        ) -> None:
            """
            Send contextual resumption greeting by streaming from the Psychoanalyst Agent.
            Raises exceptions on failure (fail-fast).
            """
            logger.info(f"Generating resumption greeting for user {user_id}")
            therapy_plan = await self.db_service.get_latest_therapy_plan(user_id)
            if not therapy_plan or not therapy_plan.session_briefing:
                raise ValueError(f"Therapy plan with session briefing not found for user {user_id}")

            user_profile = await self.db_service.get_user_profile(user_id)
            if not user_profile:
                raise ValueError(f"User profile not found for user {user_id}")

            # Get the agent from the orchestrator
            agent = await self.orchestrator.get_or_create_agent("PSYCHOANALYST", user_id)

            # Stream the greeting directly from the agent
            async for chunk in agent.stream_initial_greeting(user_profile, therapy_plan):
                await send_channel.send({
                    "type": "chat_response_chunk",
                    "data": {"chunk": chunk, "session_id": session_id, "is_complete": False, ...}
                })
            
            # Send completion marker
            await send_channel.send({
                "type": "chat_response_chunk",
                "data": {"chunk": "", "session_id": session_id, "is_complete": True, ...}
            })
            logger.info(f"Successfully streamed resumption greeting for user {user_id}")
        ```

    2.  **Update `_handle_session_request_ws`:**
        ```python
        # In _handle_session_request_ws method
        # ... (after sending session_started message) ...

        if has_initial_message:
            if state == WorkflowState.PLAN_COMPLETE:
                try:
                    # Call the new, correct method
                    await self._send_resumption_greeting(user_id, session_id, send_channel)
                except Exception as e:
                    logger.error(f"Error sending resumption greeting: {e}", exc_info=True)
                    # Propagate error to the websocket reader's handler
                    raise
            else:
                # ... handle NEW user case ...
        ```

---

### **Phase 3: Comprehensive Testing**

**Objective:** Implement the missing tests to ensure correctness, prevent regressions, and validate the end-to-end flow.

#### **Task 3.1: Create Database Unit Test**

*   **File:** `tests/unit/test_trio_db_service.py`
*   **Action:** Create this file and add the `test_save_and_load_therapy_plan_with_briefing` test case from the plan to verify that a plan with a `session_briefing` can be saved and retrieved correctly.

#### **Task 3.2: Create Agent Unit Tests**

*   **File:** `tests/unit/test_trio_reflection_agent.py`
*   **Action:** Create this file and add the `test_generate_session_briefing` test case to validate the structure and content of the generated briefing.
*   **File:** `tests/unit/test_trio_psychoanalyst_agent.py`
*   **Action:** Create this file and add the `test_build_resumption_prompt` test case to ensure the LLM prompt is built correctly from a briefing.

#### **Task 3.3: Create End-to-End Integration Test**

*   **File:** `tests/integration/test_session_resumption.py`
*   **Action:** Create this file and implement the `test_complete_session_resumption_flow` test. This is the most critical test, as it will simulate a full user journey:
    1.  Conduct a session.
    2.  Trigger reflection and confirm a briefing is saved.
    3.  Start a new session and confirm a contextual greeting is received.

#### **Task 3.4: Create Streaming Integration Test**

*   **File:** `tests/integration/test_trio_websocket.py`
*   **Action:** Add the `test_greeting_streams_progressively` test case to this existing file. This test must use a real WebSocket client to connect to the server and assert that multiple `chat_response_chunk` messages are received over a non-zero interval, proving that the greeting is streamed, not sent in a single batch.
