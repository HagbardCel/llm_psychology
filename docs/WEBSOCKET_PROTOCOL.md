# WebSocket Protocol Specification

**Version**: 1.2.1
**Date**: 2025-12-22
**Last Verified**: 2025-12-22
**Status**: Active
**Maintainer**: Backend Team

---

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
     │  2. Server validates/creates user          │
     │     <connected> message                    │
     │<────────────────────────────────────────────┤
     │                                             │
     │  3. Client requests session                │
     │     <session_request> message              │
     ├────────────────────────────────────────────>│
     │                                             │
     │  4. Server creates session                 │
     │     <session_started> message              │
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

- **Client → Server**: Imperative (requests action): `session_request`, `chat_message`, `end_session`
- **Server → Client**: Descriptive (states or events): `connected`, `session_started`, `chat_response_chunk`,
  `typing_start`, `typing_stop`, `assessment_recommendations`, `session_ended`, `error`

---

## Client → Server Messages
Only the message types listed in this section are handled by the server. Other client message types are ignored.

### `session_request`

Request to start a new therapy session.

**Payload**:
```json
{
  "type": "session_request",
  "data": {
    "session_type": "therapy"  // Optional: "therapy" | "intake" | "assessment"
  }
}
```

**Server Response**: `session_started` message

**Behavior**:
- `session_type` (optional) tells the backend which workflow agent to start.
  - Defaults to `"therapy"` if omitted
  - `"intake"` → Intake agent and workflow transition to INTAKE_IN_PROGRESS
  - `"assessment"` → Assessment agent and workflow transition to ASSESSMENT_IN_PROGRESS
  - `"therapy"` → Therapy agent and workflow transition to THERAPY_IN_PROGRESS
- If user already has an active session, server switches to new session
- Previous session WebSocket registration is cleaned up
- Session ID is tracked on server side

**Example**:
```json
{
  "type": "session_request",
  "data": {
    "session_type": "assessment"
  }
}
```

**Error Cases**:
- None (always creates new session)

---

### `chat_message`

Send user message during active session.

**Prerequisites**: Must have active session (sent `session_request` first)

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
- **No active session**: Server closes connection with code 1002: "First message must be session_request"
- **Empty message**: Silently ignored

---

### `end_session`

Request to end the active session.

**Prerequisites**: Must have active session (sent `session_request` first)

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
- Server updates workflow state as needed (e.g., therapy → reflection).
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
- If user doesn't exist, auto-creates profile with status PROFILE_ONLY

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
- Ready to send `session_request`

---

### `session_started`

Sent after successful session creation.

**Trigger**: Client sent `session_request`

**Payload**:
```json
{
  "type": "session_started",
  "data": {
    "session_id": string,           // Unique session identifier (UUID)
    "user_id": string,              // User identifier
    "agent_type": string,           // Current agent (INTAKE, ASSESSMENT, PSYCHOANALYST, etc.)
    "workflow_state": string,       // Current workflow state
    "created_at": string,           // ISO 8601 timestamp
    "has_initial_message": boolean  // Whether therapist will send automatic greeting
  }
}
```

**Behavior**:
- Confirms session created
- Provides session metadata
- If `has_initial_message: true`, therapist will send initial greeting automatically

**Example**:
```json
{
  "type": "session_started",
  "data": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "user-123",
    "agent_type": "INTAKE",
    "workflow_state": "INTAKE_IN_PROGRESS",
    "created_at": "2025-12-02T10:30:00.000Z",
    "has_initial_message": true
  }
}
```

**Client Handling**:
- Store `session_id` for subsequent messages
- Display agent type to user (optional)
- If `has_initial_message: true`, wait for initial `chat_response_chunk` before accepting user input
- Update UI to "session active" state

---

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
    "workflow_state": "ASSESSMENT_COMPLETE"
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
    "message": string  // Human-readable error message
  }
}
```

**Example**:
```json
{
  "type": "error",
  "data": {
    "message": "Failed to generate response. Please try again."
  }
}
```

**Client Handling**:
- Display error to user
- Log error for debugging
- Allow user to retry
- Do not disconnect

---

## Connection Management

### Connection Lifecycle

1. **Connection**: Client connects with `user_id` query parameter
2. **Authentication**: Server validates/creates user profile
3. **Confirmation**: Server sends `connected` message
4. **Session Creation**: Client sends `session_request` when ready
5. **Active Session**: Client sends `chat_message`, receives `chat_response_chunk`
6. **Disconnection**: Either party can close connection

### Close Codes

| Code | Reason | Meaning |
|------|--------|---------|
| 1000 | Normal Closure | Clean disconnect |
| 1002 | Protocol Error | Missing user_id or session_request |
| 1011 | Internal Error | Server-side error |

### Reconnection Strategy

Clients should implement exponential backoff:
- **Initial delay**: 1 second
- **Max attempts**: 5
- **Backoff multiplier**: 2x
- **Max delay**: 30 seconds

**Reconnection Behavior**:
- On reconnection, client must send `session_request` again
- Previous session context is maintained on server
- Client should re-fetch session history if needed

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
- Error message: "First message must be session_request"

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

# Send session request
> {"type":"session_request","data":{}}

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
- **Solution**: Send `session_request` first

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
| 1.2.1 | 2025-12-22 | Trimmed documentation to implemented message types and updated references |
| 1.1.0 | 2025-12-16 | Added session_type contract for `session_request` and new `assessment_recommendations` event |
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
