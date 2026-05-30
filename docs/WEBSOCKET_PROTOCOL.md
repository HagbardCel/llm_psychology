---
owner: engineering
status: active
last_reviewed: 2026-02-14
review_cycle_days: 90
source_of_truth_for: WebSocket message envelope, event semantics, and versioned protocol references
---

# WebSocket Protocol Specification

**Version**: 1.2.3
**Date**: 2025-12-29
**Last Verified**: 2026-02-14
**Status**: Active
**Maintainer**: Backend Team

---

## Source of Truth

- Machine-readable protocol inventory: `schemas/ws_protocol.json`
- Generated constants:
  - `src/psychoanalyst_app/utils/ws_protocol.py`
  - `console-ui/src/websocket_protocol.py`
  - `frontend/src/types/ws_protocol.generated.ts`
- Regeneration command (Docker): `docker compose run --rm -v "$PWD:/app" api python scripts/generate_ws_protocol.py`

## Overview

This document defines the WebSocket message protocol between therapy clients (console UI, web frontend) and the backend server. All messages are JSON-encoded and follow a consistent structure.

**Endpoint**: `ws://<host>:<port>/ws?user_id=<user_id>`

**Query Parameters**:
- `user_id` (required): User identifier

---

## Connection Flow

```
┌──────────┐                                  ┌──────────┐
│  Client  │                                  │  Server  │
└────┬─────┘                                  └────┬─────┘
     │                                             │
     │  1. Connect with user_id query param       │
     ├────────────────────────────────────────────>│
     │                                             │
     │  2. Server validates user profile          │
     │     <connected> message                    │
     │<────────────────────────────────────────────┤
     │                                             │
     │  3. Server creates/resumes session         │
     │     <session_started> message              │
     │<────────────────────────────────────────────┤
     │                                             │
     │  4. Server emits workflow next action      │
     │     <workflow_next_action> message         │
     │<────────────────────────────────────────────┤
     │                                             │
     │  5. Client sends chat messages             │
     │     <chat_message> message                 │
     ├────────────────────────────────────────────>│
     │                                             │
     │  6. Server streams LLM response            │
     │     <chat_response_chunk> messages         │
     │<────────────────────────────────────────────┤
     │     (multiple chunks)                      │
     │<────────────────────────────────────────────┤
     │     <chat_response_chunk is_complete=true> │
     │<────────────────────────────────────────────┤
     │                                             │
```

If the user profile does not exist, the server sends an `error` message and closes
the connection with code `1008` (`profile_not_found`). Clients must register first
via `POST /api/user/register`.

Reconnects and page refreshes use the same connection flow. Clients must treat
the latest `session_started.session_id` as authoritative and replace any locally
cached active session id with that value. After `session_started`, the server
emits `workflow_next_action`; if that action is `select_therapy_style`, the
server also emits the latest persisted `assessment_recommendations` when
available.

---

## Message Format

All messages follow this structure:

```json
{
  "type": "<message_type>",
  "data": { /* type-specific payload */ }
}
```

### Message Type Naming Convention

- **Client → Server**: Imperative (requests action): `chat_message`, `end_session`
- **Server → Client**: Descriptive (states or events): `connected`, `session_started`, `chat_response_chunk`,
  `typing_start`, `typing_stop`, `assessment_recommendations`, `session_ended`, `error`

---

## Client → Server Messages
Only the message types listed in this section are handled by the server. Other client message types are ignored.

### `chat_message`

Send user message during active session.

**Prerequisites**: Must have active session (auto-created on connect after registration). Session binding is implicit; do not include `session_id` in client payloads.

**Payload**:
```json
{
  "type": "chat_message",
  "data": {
    "message": string  // User's message text (required, non-empty)
  }
}
```

**Server Response**: Stream of `chat_response_chunk` messages

**Behavior**:
- Server validates session exists
- Empty messages are ignored
- Message is added to session transcript
- LLM generates streaming response

**Example**:
```json
{
  "type": "chat_message",
  "data": {
    "message": "I've been feeling anxious lately."
  }
}
```

**Error Cases**:
- **No active session**: Server closes connection with code 1002: "No active session"
- **Empty message**: Silently ignored

---

### `end_session`

Request to end the active session.

**Prerequisites**: Must have active session

**Payload**:
```json
{
  "type": "end_session",
  "data": {
    "reason": string  // Optional: client-supplied reason
  }
}
```

**Server Response**: `session_ended` message

**Behavior**:
- Server updates workflow state as needed (e.g., `therapy_in_progress` → `plan_update_in_progress`).
- Server emits `session_ended` to confirm shutdown and client should exit.

**Example**:
```json
{
  "type": "end_session",
  "data": {
    "reason": "User ended session"
  }
}
```

**Error Cases**:
- **No active session**: Server closes connection with code 1002: "No active session to end"

---

## Server → Client Messages

### `connected`

Sent immediately after successful WebSocket connection.

**Trigger**: Client connects to WebSocket endpoint

**Payload**:
```json
{
  "type": "connected",
  "data": {
    "user_id": string,      // User identifier
    "name": string,          // User's display name
    "status": string         // UserStatus enum value
  }
}
```

**Behavior**:
- Confirms connection established
- Provides user profile information
- If user profile is missing, server sends `error` and closes the connection

**Example**:
```json
{
  "type": "connected",
  "data": {
    "user_id": "user-123",
    "name": "John Doe",
    "status": "INTAKE_IN_PROGRESS"
  }
}
```

**Client Handling**:
- Store user information
- Update connection status to "connected"
- Ready to receive `session_started` (session is created/resumed)

---

### `session_started`

Sent after successful session creation or resume.

**Trigger**: WebSocket connect (auto-session after registration)

**Payload**:
```json
{
  "type": "session_started",
  "data": {
    "session_id": string,           // Unique session identifier (UUID)
    "user_id": string,              // User identifier
    "agent_type": string,           // Current agent (INTAKE, ASSESSMENT, PSYCHOANALYST, etc.)
    "workflow_state": string,       // Current workflow state
    "created_at": string            // ISO 8601 timestamp
  }
}
```

**Behavior**:
- Confirms session created
- Provides session metadata
- For chat-ready workflow steps, the backend will send an initial greeting before accepting user input

**Example**:
```json
{
  "type": "session_started",
  "data": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "user-123",
    "agent_type": "INTAKE",
    "workflow_state": "INTAKE_IN_PROGRESS",
    "created_at": "2025-12-02T10:30:00.000Z"
  }
}
```

**Client Handling**:
- Store `session_id` for subsequent HTTP requests, replacing any stale locally
  cached session id
- Display agent type to user (optional)
- Wait for the initial `chat_response_chunk` before accepting user input in chat flows
- Update UI to "session active" state

---

### `workflow_next_action`

Sent on WebSocket connect and whenever the backend reevaluates the required workflow step (after agent output persistence, session end, or step completion true events).

**Payload**: `WorkflowNextActionDTO`

```json
{
  "type": "workflow_next_action",
  "data": {
    "user_id": "user-123",
    "workflow_state": "INTAKE_IN_PROGRESS",
    "required_action": "wait",
    "required_fields": [],
    "defaults": null,
    "prompt": "Continue your intake session.",
    "blocking": false,
    "timestamp": "2025-12-22T14:30:00Z",
    "session_id": "session-456",
    "state_signature": "09b2...",
    "emission_source": "process_message_final_emit"
  }
}
```

**Behavior**:
- Informs clients what backend step should happen next (complete profile, select a therapy style, start intake, continue therapy, or wait).
- `initial_plan_complete` and `plan_update_complete` both use `required_action="continue_therapy"`; the prompt distinguishes first therapy start from post-reflection resumption.
- Always includes the latest workflow state and recommended fields to collect.
- Includes a stable `state_signature` for equivalent workflow instructions. Unlike
  `timestamp`, it remains unchanged when the backend reevaluates the same state.
- Includes `emission_source` on pushed events so protocol traces identify the
  backend path that produced an event.
- `blocking` indicates whether the UI must satisfy this action before other workflows continue.
- Sent after `session_started` so clients can render the appropriate onboarding form.

**Client Handling**:
- Render forms based on `required_action` (`complete_profile` → show profile form, `select_therapy_style` → show style picker, `start_intake`/`continue_therapy` → show the session UI, `wait` → show progress state).
- Use `required_fields` to dynamically drive data collection and `defaults` to prefill fields.
- Display the `prompt` as the wait/status notice when `required_action` is `wait`.
- Ignore duplicate displays that do not change `state_signature`.
- Do not send `chat_message` while `required_action` is `wait`.
- Do not enable chat input until the automatic initial greeting has finished.

### `chat_response_chunk`

Streaming LLM response (multiple messages per response).

**Trigger**: Client sent `chat_message` OR automatic initial greeting

**Payload**:
```json
{
  "type": "chat_response_chunk",
  "data": {
    "chunk": string,         // Text fragment (can be empty on final chunk)
    "is_complete": boolean   // True on final chunk only
  }
}
```

**Behavior**:
- Server sends multiple chunks in sequence
- Each chunk contains a portion of the response
- Final chunk has `is_complete: true` and typically empty `chunk`
- Chunks arrive in real-time as LLM generates text

**Example Sequence**:
```json
// Chunk 1
{
  "type": "chat_response_chunk",
  "data": { "chunk": "I understand ", "is_complete": false }
}

// Chunk 2
{
  "type": "chat_response_chunk",
  "data": { "chunk": "that you're ", "is_complete": false }
}

// Chunk 3
{
  "type": "chat_response_chunk",
  "data": { "chunk": "feeling anxious. ", "is_complete": false }
}

// Final chunk
{
  "type": "chat_response_chunk",
  "data": { "chunk": "", "is_complete": true }
}
```

**Client Handling**:
- Display typing indicator when first chunk arrives
- Accumulate chunks into complete message
- Display chunks in real-time for streaming effect
- When `is_complete: true`, hide typing indicator and finalize message
- Add complete message to chat history
- Re-enable user input

**Performance Considerations**:
- Chunks may arrive rapidly (every 50-200ms)
- Client should batch UI updates if needed
- Buffer size typically 10-50 characters per chunk

---

### `session_ended`

Indicates the server has ended the active session.

**Trigger**: Client sent `end_session` or agent ended the session.

**Payload**:
```json
{
  "type": "session_ended",
  "data": {
    "reason": string,          // Human-readable reason
    "workflow_state": string   // Workflow state after ending the session
  }
}
```

**Behavior**:
- Confirms the session is over and workflow state was updated.

**Example**:
```json
{
  "type": "session_ended",
  "data": {
    "reason": "User ended session",
    "workflow_state": "plan_update_in_progress"
  }
}
```

**Client Handling**:
- Exit the chat UI (console should terminate its loop).
- Optionally show the final workflow state to the user.

---

### `assessment_recommendations`

Structured therapy style recommendations emitted at the end of the assessment chat.

**Trigger**: Assessment agent completes analysis and is waiting for the user to select a style.

**Payload**:
```json
{
  "type": "assessment_recommendations",
  "data": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "user-123",
    "recommendations": [
      {
        "style_id": "freud",
        "explanation": "Grounded in your interest in exploring unconscious conflicts.",
        "score": 0.82
      }
    ]
  }
}
```

**Behavior**:
- Sent once per assessment flow when the backend is awaiting a therapy style selection.
- Recommendations are ordered by backend relevance score.
- Message does **not** pause streaming; it is emitted alongside the chat transcript.

**Client Handling**:
- Switch UI from chat mode → selection mode using these recommendations.
- Display `style_id` (snake case) as the canonical identifier when submitting the user's selection.
- Ignore duplicate messages (idempotent).

---

### `typing_start`

Indicates therapist is generating response.

**Status**: Supported by server, optional for clients

**Payload**:
```json
{
  "type": "typing_start",
  "data": {}
}
```

**Behavior**:
- Sent before LLM generation begins for initial greetings or background streaming.
- Not guaranteed for every response (chat streaming may rely on `chat_response_chunk` only).

**Client Handling**: Display typing indicator UI

---

### `typing_stop`

Indicates therapist finished generating response.

**Status**: Supported by server, optional for clients

**Payload**:
```json
{
  "type": "typing_stop",
  "data": {}
}
```

**Behavior**:
- Sent after LLM generation completes for initial greetings or background streaming.
- Not guaranteed for every response (chat streaming may rely on `is_complete: true` instead).

**Client Handling**: Hide typing indicator UI

---

### `error`

Error message from server.

**Trigger**: Server-side error during message processing

**Payload**:
```json
{
  "type": "error",
  "data": {
    "code": string,    // Stable machine-readable code when available
    "message": string  // Human-readable error message
  }
}
```

**Example**:
```json
{
  "type": "error",
  "data": {
    "code": "internal_error",
    "message": "Failed to generate response. Please try again."
  }
}
```

**Client Handling**:
- Display error to user
- Log error for debugging
- Allow user to retry
- Do not disconnect

**Workflow Guard Codes**:
- `chat_disabled_initial_greeting`: wait for the automatic initial greeting to finish before sending chat.
- `chat_disabled_workflow_wait`: re-fetch `workflow_next_action`; chat is disabled while the backend action is `wait`.

---

## Connection Management

### Connection Lifecycle

1. **Connection**: Client connects with `user_id` query parameter
2. **Authentication**: Server validates existing user profile (register first)
3. **Confirmation**: Server sends `connected` message
4. **Session Creation**: Server auto-creates/resumes and sends `session_started`
5. **Active Session**: Client sends `chat_message`, receives `chat_response_chunk`
6. **Disconnection**: Either party can close connection

### Close Codes

| Code | Reason | Meaning |
|------|--------|---------|
| 1000 | Normal Closure | Clean disconnect |
| 1002 | Protocol Error | Missing user_id or no active session |
| 1008 | Policy Violation | Profile not found (register required) |
| 1011 | Internal Error | Server-side error |

### Reconnection Strategy

Clients should implement exponential backoff:
- **Initial delay**: 1 second
- **Max attempts**: 5
- **Backoff multiplier**: 2x
- **Max delay**: 30 seconds

**Reconnection Behavior**:
- On reconnection, the server rebinds an active session and emits `session_started`
- The emitted `session_started.session_id` is the active session for subsequent
  HTTP requests, even if it differs from local storage
- Previous session context is maintained on server where the workflow supports it
- Client should re-fetch session history and workflow-scoped data if needed

---

## Message Ordering & Guarantees

### Ordering Guarantees

- ✅ **Server guarantees**: Messages sent to a client arrive in order
- ✅ **Client guarantees**: Messages sent to server are processed in order
- ✅ **Session isolation**: Messages are isolated per session

### Delivery Guarantees

- **At-most-once**: WebSocket provides at-most-once delivery
- **No retries**: Failed messages are not automatically retried
- **Client responsibility**: Clients should detect failures and retry if needed

---

## Error Handling

### Server-Side Errors

**Invalid JSON**:
- Server logs warning
- Connection remains open
- No error message sent to client

**Unknown Message Type**:
- Server ignores message
- Connection remains open
- No error message sent to client

**Missing Session**:
- Server closes connection with code 1002
- Error message: "No active session"

**LLM Generation Failure**:
- Server may send an `error` message (primarily for background streaming flows)
- Connection remains open
- Client can retry

### Client-Side Errors

**Connection Failure**:
- Client should implement reconnection with exponential backoff
- Display connection status to user

**Message Parse Failure**:
- Client should log error
- Ignore malformed message
- Continue processing subsequent messages

---

## Security Considerations

### Authentication

- **Current**: User ID passed as query parameter (development only)
- **Production**: Should continue using explicit `user_id` identifiers for sessions

### Data Privacy

- All messages contain user data
- WebSocket should use WSS (TLS) in production
- Session IDs are UUIDs (not guessable)

### Rate Limiting

- **Current**: No rate limiting implemented
- **Recommendation**: Add per-user rate limits
- **Suggested**: 10 messages per minute per user

---

## Testing & Debugging

### Manual Testing with `wscat`

```bash
# Install wscat
npm install -g wscat

# Connect to server
wscat -c "ws://localhost:8000/ws?user_id=test-user"

# Send chat message
> {"type":"chat_message","data":{"message":"Hello"}}
```

### Debug Logging

**Server Side**:
```python
logger.info(f"WebSocket message: {msg_type} from user: {user_id}")
```

**Client Side**:
```typescript
console.log('[WS]', message.type, message.data);
```

### Common Issues

**Issue**: Client receives no response to `chat_message`
- **Cause**: No active session
- **Solution**: Reconnect (auto-session will resume)

**Issue**: Connection closes immediately
- **Cause**: Missing `user_id` query parameter
- **Solution**: Add `?user_id=<id>` to WebSocket URL

**Issue**: Chunks appear out of order
- **Cause**: WebSocket guarantees in-order delivery, likely client-side issue
- **Solution**: Check client message queue implementation

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.2.3 | 2025-01-10 | Auto-session on connect; `session_request` removed |
| 1.2.2 | 2025-12-29 | session_started before workflow_next_action |
| 1.2.1 | 2025-12-22 | Trimmed documentation to implemented message types and updated references |
| 1.1.0 | 2025-12-16 | Added `assessment_recommendations` event |
| 1.0.0 | 2025-12-02 | Initial protocol specification |

---

## References

### Implementation Files

- **Backend Handler**: [src/psychoanalyst_app/api/ws_handler.py](../src/psychoanalyst_app/api/ws_handler.py)
- **Message Helpers**: [src/psychoanalyst_app/utils/ws_messages.py](../src/psychoanalyst_app/utils/ws_messages.py)
- **Console UI Client**: [console-ui/src/console_client.py](../console-ui/src/console_client.py)
- **Web Frontend Service**: [frontend/src/services/websocketService.ts](../frontend/src/services/websocketService.ts)
- **Backend Models**: [src/psychoanalyst_app/orchestration/models.py](../src/psychoanalyst_app/orchestration/models.py)

### Related Documentation

- [ARCHITECTURE.md](../ARCHITECTURE.md) - System architecture overview
- [design-principles.md](../design-principles.md) - Architecture and workflow invariants

---

## Contact & Support

For questions about this protocol:
- Review implementation files listed in References
- Check existing WebSocket handlers in codebase
- Test with `wscat` for manual verification

---

**Document Maintainer**: Backend Team
**Last Updated**: 2025-12-22
**Next Review**: After Phase 1 completion
