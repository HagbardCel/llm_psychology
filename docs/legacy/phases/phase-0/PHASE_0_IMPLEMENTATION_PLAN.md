# Phase 0 Implementation Plan: Critical Blockers

## Goal

Resolve the fundamental protocol incompatibility between frontend (Socket.IO) and backend (Native WebSockets) and align data models to enable basic communication.

## User Review Required

> [!IMPORTANT]
> This phase involves **removing** `socket.io-client` and rewriting the `WebSocketService` to use the native `WebSocket` API.
> This is a breaking change for the frontend networking layer.
> **All existing localStorage data will be cleared** (no production users exist).

---

## Backend WebSocket Protocol Reference

### Connection
- **URL Format:** `ws://localhost:8000/ws?user_id=<user_id>`
- **Query Parameter:** `user_id` is **required** (backend will close connection if missing)

### Message Formats

#### Messages FROM Backend TO Frontend

**1. Connection Confirmed:**
```json
{
  "type": "connected",
  "data": {
    "user_id": "user123",
    "name": "John Doe",
    "status": "PROFILE_ONLY"
  }
}
```

**2. Session Started:**
```json
{
  "type": "session_started",
  "data": {
    "session_id": "sess_abc123",
    "agent_type": "INTAKE",
    "workflow_state": "intake_in_progress",
    "created_at": "2025-11-29T12:00:00.000Z",
    "user_id": "user123",
    "has_initial_message": true
  }
}
```

**3. Chat Response Chunk (Streaming):**
```json
{
  "type": "chat_response_chunk",
  "data": {
    "chunk": "Hello, how are you ",
    "is_complete": false
  }
}
```

**4. Chat Response Complete:**
```json
{
  "type": "chat_response_chunk",
  "data": {
    "chunk": "",
    "is_complete": true
  }
}
```

**5. Typing Indicator:**
```json
{
  "type": "typing_start"
}
```

#### Messages FROM Frontend TO Backend

**1. Session Request (MUST be first message):**
```json
{
  "type": "session_request"
}
```

**2. Chat Message:**
```json
{
  "type": "chat_message",
  "data": {
    "message": "Hello, I need help with anxiety"
  }
}
```

---

## Proposed Changes

### 1. Protocol Migration (Socket.IO → Native WebSocket)

#### [MODIFY] `frontend/package.json`

**Remove:**
- `socket.io-client` (line 28)

**Add:**
- `ts-jest@^29.1.0` (needed for test infrastructure)
- `@types/jest@^29.5.0` (if not already present)

```bash
cd frontend
npm uninstall socket.io-client
npm install -D ts-jest@^29.1.0 @types/jest@^29.5.0
```

---

#### [MODIFY] `frontend/src/services/websocketService.ts`

**Complete rewrite to use native WebSocket API.**

**Key Changes:**
1. Replace `import { io, Socket } from 'socket.io-client'` with native `WebSocket`
2. Update connection URL construction to include query parameter:
   ```typescript
   const wsUrl = `${this.config.url.replace(/^http/, 'ws')}/ws?user_id=${encodeURIComponent(this.config.userId)}`;
   this.socket = new WebSocket(wsUrl);
   ```
3. Replace Socket.IO event handlers with native WebSocket events:
   - `socket.on('connect')` → `socket.onopen`
   - `socket.on('message')` → `socket.onmessage`
   - `socket.on('disconnect')` → `socket.onclose`
   - `socket.on('error')` → `socket.onerror`
4. Update message sending:
   ```typescript
   sendMessage(type: string, data: Record<string, any> = {}): void {
     const message = { type, data };
     this.socket?.send(JSON.stringify(message));
   }
   ```
5. Update message receiving:
   ```typescript
   this.socket.onmessage = (event) => {
     const message = JSON.parse(event.data);
     this.handleMessage(message);
   };
   ```
6. Implement manual reconnection logic (Socket.IO did this automatically):
   - Exponential backoff: `delay = baseDelay * Math.pow(2, attempt - 1)`
   - Max attempts: 5 (from config)
   - Store reconnect timer to clean up properly

**Message Type Handlers:**
- `connected` → Update connection status, extract user info
- `session_started` → Call `onSessionStartedEvent` callback
- `chat_response_chunk` → Call `onStreamingChunk` callback
- `typing_start` → Log or show typing indicator

**Connection Lifecycle:**
1. `connect()` → Create WebSocket, attach handlers, wait for `onopen`
2. `onopen` → Set `isConnected = true`, reset reconnect attempts
3. `onclose` → Trigger reconnection if not intentional disconnect
4. `onerror` → Log error, update connection status

---

#### [MODIFY] `frontend/vite.config.ts`

**REMOVE the Socket.IO proxy entirely.**

```diff
proxy: {
  '/api': {
    target: process.env.VITE_API_URL || 'http://localhost:8000',
    changeOrigin: true
  },
- '/socket.io': {
-   target: process.env.VITE_WEBSOCKET_URL || 'http://localhost:8000',
-   changeOrigin: true,
-   ws: true
- }
}
```

**Reason:** Native WebSocket connections bypass HTTP proxy. Frontend will connect directly using `ws://` protocol.

---

#### [MODIFY] `frontend/src/hooks/useWebSocket.ts`

**Update WebSocket URL construction:**

```typescript
// Line 44: Update default URL to use ws:// protocol
const {
  url = 'ws://localhost:8000',  // Changed from http://
  // ...
```

**No proxy dependency:** The hook will pass the full WebSocket URL directly to the service.

---

### 2. Data Model Alignment

#### [MODIFY] `frontend/src/types/index.ts`

**1. Update `UserStatus` Enum:**
```typescript
export enum UserStatus {
  PROFILE_ONLY = 'PROFILE_ONLY',
  INTAKE_IN_PROGRESS = 'INTAKE_IN_PROGRESS',        // NEW
  INTAKE_COMPLETE = 'INTAKE_COMPLETE',
  ASSESSMENT_IN_PROGRESS = 'ASSESSMENT_IN_PROGRESS',  // NEW
  ASSESSMENT_COMPLETE = 'ASSESSMENT_COMPLETE',        // NEW
  THERAPY_IN_PROGRESS = 'THERAPY_IN_PROGRESS',        // NEW
  REFLECTION_IN_PROGRESS = 'REFLECTION_IN_PROGRESS',  // NEW
  PLAN_COMPLETE = 'PLAN_COMPLETE'
}
```

**2. Update `AgentType` Enum:**
```typescript
export enum AgentType {
  INTAKE = 'INTAKE',
  ASSESSMENT = 'ASSESSMENT',
  PSYCHOANALYST = 'PSYCHOANALYST',
  PLANNING = 'PLANNING',      // NEW
  REFLECTION = 'REFLECTION'
}
```

**3. Add `Topic` Interface (if not exists):**
```typescript
export interface Topic {
  name: string;
  status: 'pending' | 'covered' | 'partially_covered';
}
```

**4. Update `Message` Interface:**
```typescript
export interface Message {
  id: string;
  content: string;
  role: 'user' | 'assistant';  // CHANGED from sender: 'user' | 'agent'
  timestamp: Date;
  sessionId: string;
}
```

**5. Update `Session` Interface:**
```typescript
export interface Session {
  id: string;
  userId: string;
  agentType: AgentType;
  therapyStyle?: TherapyStyle;
  status: SessionStatus;
  startTime: Date;
  endTime?: Date;
  transcript: Message[];       // CHANGED from messages: Message[]
  topics: Topic[];             // NEW - add this field
  metadata?: Record<string, any>;
}
```

---

#### [MODIFY] `frontend/src/types/websocket.ts`

**Update `ChatMessage` interface:**
```typescript
export interface ChatMessage {
  message: string;
  role: 'user' | 'assistant';  // CHANGED from sender: 'user' | 'therapist'
  timestamp: string;
  id?: string;
}
```

---

#### [MODIFY] `frontend/src/components/TherapySession.tsx`

**Update ALL references to match new data model:**

**Lines 29, 53, 128, 183:** Change `messages` to `transcript`:
```typescript
// Line 29:
const messages = currentSession?.transcript || [];

// Line 53:
transcript: [...currentSession.transcript, agentMessage],

// Line 128:
transcript: [...currentSession.transcript, agentMessage],

// Line 183:
transcript: [...currentSession.transcript, userMessage],
```

**Lines 43-49, 117-124:** Change `sender` to `role`:
```typescript
const agentMessage: Message = {
  id: generateMessageId(),
  content: finalContent,
  role: 'assistant',        // CHANGED from sender: 'agent'
  timestamp: new Date(),
  sessionId: currentSession.id,
};

const userMessage: Message = {
  id: generateMessageId(),
  content,
  role: 'user',            // CHANGED from sender: 'user'
  timestamp: new Date(),
  sessionId: currentSession.id,
};
```

---

#### [MODIFY] `frontend/src/components/MessageHistory.tsx`

**Line 79:** Update message rendering logic:
```typescript
const isUser = message.role === 'user';  // CHANGED from message.sender === 'user'
```

---

#### [MODIFY] `frontend/src/components/Dashboard.tsx`

**Line 209:** Update message count display:
```typescript
{session.transcript.length} messages  // CHANGED from session.messages.length
```

**Lines 317-328:** Update `getProgressValue` function to handle new UserStatus values:
```typescript
function getProgressValue(status: UserStatus): number {
  switch (status) {
    case UserStatus.PROFILE_ONLY:
      return 20;
    case UserStatus.INTAKE_IN_PROGRESS:
      return 35;
    case UserStatus.INTAKE_COMPLETE:
      return 50;
    case UserStatus.ASSESSMENT_IN_PROGRESS:
      return 65;
    case UserStatus.ASSESSMENT_COMPLETE:
      return 80;
    case UserStatus.PLAN_COMPLETE:
      return 100;
    default:
      return 0;
  }
}
```

**Lines 330-343:** Update `getSessionIcon` to handle `PLANNING` agent:
```typescript
function getSessionIcon(agentType: AgentType) {
  switch (agentType) {
    case AgentType.INTAKE:
      return <AssessmentIcon />;
    case AgentType.ASSESSMENT:
      return <TrendingUpIcon />;
    case AgentType.PSYCHOANALYST:
      return <PsychologyIcon />;
    case AgentType.PLANNING:         // NEW
      return <ScheduleIcon />;       // NEW
    case AgentType.REFLECTION:
      return <HistoryIcon />;
    default:
      return <PsychologyIcon />;
  }
}
```

**Lines 345-358:** Update `getSessionTitle` to handle `PLANNING` agent:
```typescript
function getSessionTitle(agentType: AgentType): string {
  switch (agentType) {
    case AgentType.INTAKE:
      return 'Intake Session';
    case AgentType.ASSESSMENT:
      return 'Assessment Session';
    case AgentType.PSYCHOANALYST:
      return 'Therapy Session';
    case AgentType.PLANNING:        // NEW
      return 'Planning Session';    // NEW
    case AgentType.REFLECTION:
      return 'Reflection Session';
    default:
      return 'Session';
  }
}
```

---

#### [MODIFY] `frontend/src/contexts/AppContext.tsx`

**Update reducer to use `transcript` field:**

```typescript
// Lines 32-36: ADD_SESSION action
case 'ADD_SESSION':
  return {
    ...state,
    sessions: [...state.sessions, action.payload],
    currentSession: action.payload
  };

// Lines 37-46: UPDATE_SESSION action
case 'UPDATE_SESSION':
  return {
    ...state,
    sessions: state.sessions.map(session =>
      session.id === action.payload.id ? action.payload : session
    ),
    currentSession: state.currentSession?.id === action.payload.id
      ? action.payload
      : state.currentSession
  };
```

**Add localStorage clear on first load (handles schema migration):**

```typescript
// In loadStoredData() useEffect, add at the top:
useEffect(() => {
  const loadStoredData = async () => {
    try {
      dispatch({ type: 'SET_LOADING', payload: true });

      // CLEAR OLD SCHEMA DATA - no production users exist
      // This can be removed after Phase 0 deployment
      const schemaVersion = getItem<number>('schemaVersion');
      if (!schemaVersion || schemaVersion < 2) {
        localStorage.clear();
        setItem('schemaVersion', 2);
        console.log('Cleared old localStorage schema');
      }

      const storedUser = getItem<User>('user');
      // ... rest of existing code
```

---

### 3. Environment Configuration

#### [NEW] `frontend/.env.example`

Create this file with documented environment variables:

```env
# Backend API base URL (HTTP)
VITE_API_URL=http://localhost:8000

# WebSocket URL (WS protocol)
VITE_WEBSOCKET_URL=ws://localhost:8000

# Development mode
VITE_DEV_MODE=true
```

#### [NEW or UPDATE] `frontend/README.md`

Add environment setup section:

```markdown
## Environment Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Configure environment variables:
   - `VITE_API_URL`: Backend HTTP API URL (default: `http://localhost:8000`)
   - `VITE_WEBSOCKET_URL`: Backend WebSocket URL (default: `ws://localhost:8000`)

3. For production deployment, update `.env` with production URLs.

## CORS Requirements

The backend must allow CORS from the frontend origin:
- **Development:** Frontend runs on `http://localhost:5173`, backend on `http://localhost:8000`
- **Production:** Configure backend CORS to allow production frontend origin
```

---

## Verification Plan

### Automated Tests

#### [NEW] `frontend/src/services/__tests__/websocketService.test.ts`

Create unit tests for native WebSocket implementation:

```typescript
import { WebSocketService } from '../websocketService';

// Mock WebSocket
class MockWebSocket {
  onopen: (() => void) | null = null;
  onmessage: ((event: any) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((error: any) => void) | null = null;

  send = jest.fn();
  close = jest.fn();
}

global.WebSocket = MockWebSocket as any;

describe('WebSocketService', () => {
  test('constructs WebSocket URL with query parameter', () => {
    const service = new WebSocketService({
      url: 'ws://localhost:8000',
      userId: 'test-user',
      authToken: 'test-token'
    });

    service.connect();

    // Verify WebSocket created with correct URL
    expect(global.WebSocket).toHaveBeenCalledWith(
      expect.stringContaining('ws://localhost:8000/ws?user_id=test-user')
    );
  });

  test('sends messages as JSON', () => {
    const service = new WebSocketService({
      url: 'ws://localhost:8000',
      userId: 'test-user',
      authToken: 'test-token'
    });

    service.connect();
    // Trigger onopen
    const ws = service['socket'];
    ws.onopen?.();

    service.sendMessage('chat_message', { message: 'Hello' });

    expect(ws.send).toHaveBeenCalledWith(
      JSON.stringify({
        type: 'chat_message',
        data: { message: 'Hello' }
      })
    );
  });

  test('handles incoming messages', () => {
    const onMessage = jest.fn();
    const service = new WebSocketService({
      url: 'ws://localhost:8000',
      userId: 'test-user',
      authToken: 'test-token'
    });

    service.onMessageReceived(onMessage);
    service.connect();

    const ws = service['socket'];
    ws.onmessage?.({
      data: JSON.stringify({
        type: 'connected',
        data: { user_id: 'test-user' }
      })
    });

    expect(onMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'connected'
      })
    );
  });

  test('implements reconnection with exponential backoff', () => {
    jest.useFakeTimers();

    const service = new WebSocketService({
      url: 'ws://localhost:8000',
      userId: 'test-user',
      authToken: 'test-token',
      reconnectDelay: 1000
    });

    service.connect();
    const ws = service['socket'];

    // Trigger disconnect
    ws.onclose?.();

    // First reconnect attempt after 1s
    jest.advanceTimersByTime(1000);
    expect(global.WebSocket).toHaveBeenCalledTimes(2);

    // Second reconnect attempt after 2s (exponential backoff)
    ws.onclose?.();
    jest.advanceTimersByTime(2000);
    expect(global.WebSocket).toHaveBeenCalledTimes(3);

    jest.useRealTimers();
  });
});
```

**Test Coverage Target:** 80%+ of WebSocketService

---

### Manual Verification

#### Prerequisites
1. **Backend Running:** `cd /app && python -m psychoanalyst_app.server`
2. **Frontend Running:** `cd /app/frontend && npm run dev`

#### Test Steps

**1. Connection Establishment**

- Open browser to `http://localhost:5173`
- Open DevTools → Network → WS tab
- Verify WebSocket connection appears with URL: `ws://localhost:8000/ws?user_id=<user_id>`
- **Expected:** Status shows "101 Switching Protocols" (green)
- **Expected:** Console logs "WebSocket connected"

**2. Connection Confirmed Message**

- In WS tab, click the WebSocket connection
- Check Messages tab
- **Expected:** First message from server:
  ```json
  {
    "type": "connected",
    "data": {
      "user_id": "default_user",
      "name": "default_user",
      "status": "PROFILE_ONLY"
    }
  }
  ```

**3. Session Request**

- Navigate to `/session` route
- **Expected:** Frontend automatically sends:
  ```json
  {
    "type": "session_request"
  }
  ```
- **Expected:** Backend responds with:
  ```json
  {
    "type": "session_started",
    "data": {
      "session_id": "sess_...",
      "agent_type": "INTAKE",
      "workflow_state": "intake_in_progress",
      ...
    }
  }
  ```

**4. Chat Message Flow**

- Type "Hello" in the chat input and send
- **Expected:** Frontend sends:
  ```json
  {
    "type": "chat_message",
    "data": {
      "message": "Hello"
    }
  }
  ```
- **Expected:** Backend responds with multiple chunks:
  ```json
  { "type": "chat_response_chunk", "data": { "chunk": "Hello ", "is_complete": false } }
  { "type": "chat_response_chunk", "data": { "chunk": "there! ", "is_complete": false } }
  { "type": "chat_response_chunk", "data": { "chunk": "", "is_complete": true } }
  ```
- **Expected:** Message appears in chat UI with correct sender distinction (user vs assistant)

**5. Reconnection Test**

- With session active, stop backend: `Ctrl+C`
- **Expected:** Frontend console shows "WebSocket disconnected"
- **Expected:** Connection status indicator shows "Disconnected" or "Reconnecting"
- Restart backend
- **Expected:** Frontend reconnects automatically within 5 seconds
- **Expected:** Connection status shows "Connected"

**6. Data Model Validation**

- Send a message and receive response
- Open DevTools → Application → Local Storage → `http://localhost:5173`
- Inspect `sessions` key
- **Expected:** Session object has `transcript` field (not `messages`)
- **Expected:** Messages in transcript have `role` field (not `sender`)
- **Expected:** Message roles are `'user'` or `'assistant'`

---

## Rollback Plan

If Phase 0 deployment fails:

1. **Revert Git Commits:**
   ```bash
   git revert <phase-0-commit-hash>
   git push
   ```

2. **Reinstall Socket.IO (if needed):**
   ```bash
   cd frontend
   npm install socket.io-client@^4.7.0
   ```

3. **Restore Vite Config:**
   - Add back `/socket.io` proxy configuration

4. **Clear Browser Cache:**
   - Users must clear localStorage manually or via browser settings

---

## Success Criteria

Phase 0 is complete when:

- ✅ Frontend connects to backend WebSocket successfully with `user_id` query parameter
- ✅ `connected` message received and parsed correctly
- ✅ `session_request` sends and `session_started` response received
- ✅ Chat messages send and streaming responses display correctly
- ✅ Messages display with correct user/assistant distinction
- ✅ Sessions saved to localStorage with `transcript` (not `messages`)
- ✅ Reconnection works automatically after disconnect
- ✅ All TypeScript compilation succeeds with no errors
- ✅ `npm test` runs without configuration errors (tests may be minimal)
- ✅ `.env.example` exists and documents all environment variables

---

## Estimated Effort

- **Protocol Migration:** 4-6 hours
- **Data Model Alignment:** 2-3 hours
- **Testing Infrastructure:** 1-2 hours
- **Verification & Bug Fixes:** 2-3 hours

**Total:** 9-14 hours (1.5-2 days)

---

## Notes

- This plan assumes **no production users exist** - all localStorage will be cleared
- Backend code does not need changes - it already uses native WebSockets
- Socket.IO is **completely removed** - no hybrid approach
- After Phase 0, frontend and backend will use identical message formats
- All file paths are relative to `/app/frontend/` unless otherwise specified
