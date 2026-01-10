# SESSION_END_CONTROL_IMPLEMENTATION_PLAN

## Goal
Make agent-driven session endings actually terminate sessions and allow the agent to decide when to transition workflow vs. end the session. Ensure clients consistently exit or rebind when `session_ended` is emitted.

## Current Symptoms
- Agent copy says the session is over, but the session stays active and the UI remains in chat mode.
- When users confirm they want to finish, the session sometimes keeps going or flips back to workflow prompts.
- Web UI ignores `session_ended` entirely, so it never closes the session.

## Why This Is Happening (Root Causes)
1) **Agents signal closure but do not request `end_session`.**
   - `src/psychoanalyst_app/agents/trio_intake_agent.py` sets `next_action="continue"` when time is up, even though the message says the session ends.
   - `src/psychoanalyst_app/agents/trio_psychoanalyst_agent.py` uses `next_action="transition"` on time-up, which advances workflow but does not end the session.

2) **Agent actions are not fully wired.**
   - `next_action="offer_extension"` is emitted by `TrioPsychoanalystAgent`, but `AgentResponseHandler` has no handling for it, so the session never transitions to an explicit end/continue decision.

3) **Session end events are not treated as final by clients.**
   - `frontend/src/services/websocketService.ts` does not handle `session_ended` at all.
   - `console-ui/src/console_client.py` checks `workflow_interrupt_requested` before `session_end_requested`, so a `workflow_next_action` arriving before `session_ended` can keep the loop running.

4) **Server emits workflow events during end-session, which can override shutdown.**
   - `SessionLifecycleManager.end_session` emits `workflow_next_action` before sending `session_ended`, and `process_message` always emits another `workflow_next_action` after handling the agent response. This can race with client shutdown behavior.

## Proposed Behavior
- If an agent indicates the session should end (time-up, user chose finish, intake complete), the server emits `session_ended` and the client exits or disconnects.
- If an agent indicates a workflow transition without ending (e.g., moving to therapy immediately), the server transitions and rebinds the session accordingly.
- `offer_extension` becomes a real branch: ask the user to extend, then either increment extension time or end the session.

## Implementation Plan

### Phase 1: Backend Agent Actions
1) **Make session-ending agent decisions explicit.**
   - `src/psychoanalyst_app/agents/trio_intake_agent.py`:
     - When intake completes, return `next_action="end_session"` while keeping `workflow_event=WorkflowEvent.COMPLETE_INTAKE` so state transitions but the session ends.
     - When time is up mid-intake, return `next_action="end_session"` with no workflow event (keep state `INTAKE_IN_PROGRESS`).
   - `src/psychoanalyst_app/agents/trio_psychoanalyst_agent.py`:
     - When time is up, switch to a closing prompt and return `next_action="end_session"` (let `SessionLifecycleManager.end_session` move to `REFLECTION_IN_PROGRESS`).
     - Keep `next_action="transition"` only for true workflow moves that should not end the current session.

2) **Attach an explicit end reason to agent responses.**
   - Use `metadata` to pass `end_reason` or `session_end_reason` and update `AgentResponseHandler` to forward it to `SessionLifecycleManager.end_session` so client messaging is accurate.

### Phase 2: Orchestrator and Session Lifecycle
3) **Handle `offer_extension` and explicit extension responses.**
   - Add action handling in `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`:
     - On `offer_extension`, send a direct prompt asking the user to extend (5 minutes) and set a sentinel (metadata or conversation state) that the next user message is a choice.
     - Add parsing in `TrioPsychoanalystAgent.process_message` (similar to assessment continuation parsing) for "yes/no" replies to decide whether to extend or end.
     - Increment `context.extensions_used` when accepted.

4) **Avoid extra `workflow_next_action` emissions after end-session.**
   - Teach `process_message` (or `finalize_agent_response`) to skip the post-response `emit_workflow_next_action` when `next_action == "end_session"`.
   - Consider removing pre/post `emit_workflow_next_action` inside `SessionLifecycleManager.end_session` (or gating it) to avoid sending new prompts after `session_ended`.

5) **Keep the WebSocket open across sessions.**
   - Do not close the WS after `session_ended`; the same connection should persist across multiple sessions.
   - Ensure clients stop chat input and transition UI state without disconnecting.

### Phase 3: Client Handling
6) **Front-end: handle `session_ended`.**
   - `frontend/src/services/websocketService.ts`: add a `session_ended` case and callback.
   - `frontend/src/hooks/useWebSocket.ts` and the UI consumers: clear session state, disable chat input, and disconnect or prompt for restart.

7) **Console UI: prioritize session shutdown.**
   - `console-ui/src/console_client.py`: check `session_end_requested` before `workflow_interrupt_requested` in `_chat_loop`.
   - Ignore workflow prompts after `session_ended` and close the WS cleanly.

### Phase 4: Docs and Tests
8) **Docs updates.**
   - `docs/session_lifecycle.md` and `docs/WEBSOCKET_PROTOCOL.md`: clarify that agent-driven ends must emit `session_ended` and that clients should close/disconnect on receipt.

9) **Tests.**
   - Backend: add/update unit tests for `AgentResponseHandler` end-session flow and time-up handling in `TrioPsychoanalystAgent`.
   - Frontend: add a test for `WebSocketService` to ensure `session_ended` dispatches to the callback and disconnects.

## Acceptance Criteria
- When an agent says the session is ending (intake time-up, therapy time-up, or assessment finish), the server emits `session_ended` and clients exit.
- User-confirmed "finish" choices end the session without extra workflow prompts re-opening the chat.
- Extension offers are handled end-to-end (prompt, user choice, extend or end).
- Web UI and console both shut down cleanly on `session_ended`.

## Open Questions
- WebSocket should remain open across sessions (no server-side close on `session_ended`).
- Extension usage should remain in-memory (session context only).
