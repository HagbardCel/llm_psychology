# Frontend Implementation Assessment & Plan

## Executive Summary

**STATUS: NON-FUNCTIONAL - CRITICAL BLOCKERS PRESENT**

The frontend is built on a modern stack (React 18, Vite, MUI, TypeScript) with clean separation of concerns. However, it is **currently non-functional** due to a critical WebSocket protocol incompatibility with the backend. The frontend uses Socket.IO while the backend implements native WebSockets, making communication impossible.

Beyond this blocker, there are significant data model mismatches, broken test configuration, and missing core integration points that must be resolved before feature development can proceed.

**Recommendation:** Address Phase 0 blockers immediately before any feature work.

## Architecture Review

### Strengths
- **Modern Stack:** React 18, Vite, and TypeScript provide a performant and type-safe foundation.
- **UI Framework:** Material UI (MUI) ensures a consistent and accessible design system.
- **State Management:** `AppContext` with `useReducer` is appropriate for the current complexity.
- **Code Organization:** Clean separation into components, contexts, hooks, and services.
- **PWA Ready:** `vite-plugin-pwa` is already configured for progressive web app capabilities.

### Critical Weaknesses
- **Protocol Incompatibility:** Frontend uses Socket.IO, backend uses native WebSockets - **completely incompatible**.
- **Data Model Mismatches:** Frontend and backend have divergent type definitions for core entities (Session, UserStatus, AgentType, Message).
- **Broken Test Config:** Jest configuration references missing `ts-jest` dependency, tests cannot run.
- **No Environment Config:** Missing `.env.example` and documentation for required environment variables.
- **Integration Gaps:** Event handling incomplete, API response structures don't match expectations.

## Gap Analysis

### Phase 0: BLOCKERS (Application Cannot Function)

#### 1. WebSocket Protocol Incompatibility 🚨 CRITICAL
**Location:** [frontend/package.json:28](frontend/package.json#L28), [frontend/src/services/websocketService.ts:5](frontend/src/services/websocketService.ts#L5)

- **Frontend:** Uses `socket.io-client` library with Socket.IO protocol
- **Backend:** Uses Quart native WebSockets at `/ws` endpoint
- **Impact:** Frontend cannot establish connection to backend - application is non-functional
- **Root Cause:** Socket.IO is not just WebSockets; it has proprietary handshake, heartbeat, and transport negotiation

**Fix Options:**
- **Option A (Recommended):** Replace Socket.IO client with native WebSocket
- **Option B:** Add Socket.IO server library to backend (breaks Trio architecture)

#### 2. Data Model Mismatches 🚨 HIGH
**Impact:** Even if WebSocket connection works, data synchronization will fail

##### Session Structure Mismatch
- **Frontend** [types/index.ts:24-34](frontend/src/types/index.ts#L24-L34): Uses `messages: Message[]`
- **Backend** [models/data_models.py:48-55](src/models/data_models.py#L48-L55): Uses `transcript: list[Message]`

##### UserStatus Enum Incomplete
- **Frontend:** 3 statuses (`PROFILE_ONLY`, `INTAKE_COMPLETE`, `PLAN_COMPLETE`)
- **Backend:** 8 statuses including `INTAKE_IN_PROGRESS`, `ASSESSMENT_IN_PROGRESS`, `ASSESSMENT_COMPLETE`, `THERAPY_IN_PROGRESS`, `REFLECTION_IN_PROGRESS`
- **Impact:** Cannot track user workflow state correctly, state transitions will fail

##### AgentType Enum Missing Values
- **Frontend** [types/index.ts:36-41](frontend/src/types/index.ts#L36-L41): Missing `PLANNING` agent
- **Backend:** Has 6 agents including `PlanningAgent`
- **Impact:** Cannot handle planning agent sessions

##### Message Sender Field Mismatch
- **Frontend:** Uses `sender: 'user' | 'agent'`
- **Backend:** Uses `role: 'user' | 'assistant'`
- **Impact:** Message rendering will fail or display incorrectly

#### 3. Jest Configuration Broken 🚨 MEDIUM
**Location:** [frontend/jest.config.js:8](frontend/jest.config.js#L8), [frontend/package.json](frontend/package.json)

- Configuration references `ts-jest` transform
- `ts-jest` is **not in package.json** dependencies
- Running `npm test` fails immediately with missing dependency
- 80% coverage threshold with 0 tests would cause failure
- Setup file exists at [frontend/src/setupTests.ts](frontend/src/setupTests.ts) but test runner won't start

**Fix:** Add `ts-jest` to devDependencies and verify test infrastructure works

#### 4. Missing Environment Configuration 🚨 MEDIUM
**Impact:** No documentation for deployment, developers must guess configuration

- No `.env.example` file
- [vite.config.ts:38-46](frontend/vite.config.ts#L38-L46) hardcodes localhost fallbacks
- `VITE_API_URL` and `VITE_WEBSOCKET_URL` are undocumented
- No CORS configuration documented (frontend:5173, backend:8000)

### Phase 1: Critical Integration Issues

#### 1. Session Started Event Not Captured
**Location:** [TherapySession.tsx:66-69](frontend/src/components/TherapySession.tsx#L66-L69)

```typescript
const handleSessionStarted = (event: any) => {
  console.log('Therapy session started:', event);
  // TODO: Update session state with session_id from event
};
```

- Backend sends `session_started` event with `session_id`
- Frontend logs it but never updates state
- **Impact:** Session IDs don't sync, subsequent messages fail

#### 2. SessionHistoryPage API Response Mismatch
**Location:** [SessionHistoryPage.tsx:38-43](frontend/src/pages/SessionHistoryPage.tsx#L38-L43)

- Frontend expects direct array: `const data = await response.json();`
- Backend likely wraps in `{success, data, error}` structure per API patterns
- **Impact:** History page will show "no sessions" even when data exists

#### 3. Hardcoded Authentication (BLOCKER for Multi-User)
**Location:** [TherapySession.tsx:82](frontend/src/components/TherapySession.tsx#L82)

```typescript
authToken: 'temp_token', // TODO: Use real auth token
```

- No auth context or token management
- User ID defaults to `'default_user'`
- **Impact:** Cannot support multiple users, no session security

#### 4. WebSocket URL Configuration
**Location:** [vite.config.ts:42-46](frontend/vite.config.ts#L42-L46)

- Proxy configured for `/socket.io` path
- Backend WebSocket is at `/ws` path
- **Impact:** Even after fixing protocol, proxy won't route correctly

### Phase 2: Missing Core Features

#### 1. No Test Coverage
- Zero test files in `src/` directory
- WebSocketService untested (reconnection logic, event handling)
- AppContext reducer untested (state management)
- Components untested (TherapySession, Dashboard)
- **Impact:** No confidence in refactoring, regressions undetected

#### 2. Missing Workflow Pages
Routes exist in [App.tsx:66-72](frontend/src/App.tsx#L66-L72) but show placeholder text:
- Settings (`/settings`)
- About (`/about`)
- Profile Setup (`/profile`)
- Intake Assessment (`/intake`)
- Therapy Assessment (`/assessment`)
- Progress Tracking (`/progress`)
- Session Scheduling (`/schedule`)

**Impact:** Users cannot complete intake/assessment workflows

#### 3. Incomplete UI Components
TODOs in [TherapySession.tsx](frontend/src/components/TherapySession.tsx):
- Navigation Drawer (line 220)
- Settings Modal (line 224)

### Phase 3: UX & Polish Issues

#### 1. Error Handling Insufficient
- Generic error messages in Snackbar
- No retry mechanisms for failed connections
- No offline detection or graceful degradation

#### 2. Loading States Basic
- Simple `CircularProgress` spinners
- No skeleton loaders for better perceived performance
- No optimistic UI updates

#### 3. Mobile Responsiveness Unknown
- No responsive testing documented
- MUI provides responsive components but implementation not verified

## Improvement Plan

### Phase 0: Fix Blockers (REQUIRED - DO FIRST)

**Estimated Effort:** 2-3 days
**Priority:** CRITICAL - Application cannot function without these fixes

#### Task 0.1: Replace Socket.IO with Native WebSocket
**Files:** `frontend/src/services/websocketService.ts`, `frontend/package.json`

1. Remove `socket.io-client` from package.json
2. Rewrite `WebSocketService` class to use native `WebSocket` API
3. Update connection URL from Socket.IO handshake to `ws://` protocol
4. Maintain existing callback structure (onStreamingChunk, onSessionStarted, etc.)
5. Preserve reconnection logic with exponential backoff
6. Update [vite.config.ts](frontend/vite.config.ts) proxy from `/socket.io` to `/ws`

**Acceptance Criteria:**
- WebSocket connects successfully to backend `/ws` endpoint
- Can send/receive JSON messages
- Reconnection works after disconnect

#### Task 0.2: Align Data Models with Backend
**Files:** `frontend/src/types/index.ts`, `frontend/src/types/websocket.ts`

1. **UserStatus Enum:**
   - Add missing statuses: `INTAKE_IN_PROGRESS`, `ASSESSMENT_IN_PROGRESS`, `ASSESSMENT_COMPLETE`, `THERAPY_IN_PROGRESS`, `REFLECTION_IN_PROGRESS`

2. **Session Interface:**
   - Rename `messages` to `transcript` OR add adapter layer
   - Add `topics: Topic[]` field

3. **Message Interface:**
   - Change `sender: 'user' | 'agent'` to `role: 'user' | 'assistant'`
   - OR add mapping layer in WebSocketService

4. **AgentType Enum:**
   - Add `PLANNING = 'PLANNING'`

**Acceptance Criteria:**
- TypeScript compiles without errors
- All enum values match backend exactly
- Session data structure compatible with backend responses

#### Task 0.3: Fix Jest Test Infrastructure
**Files:** `frontend/package.json`, `frontend/jest.config.js`

1. Add `ts-jest` to devDependencies: `npm install -D ts-jest @types/jest`
2. Verify jest.config.js transform configuration
3. Run `npm test` to confirm no configuration errors
4. Lower or remove coverage thresholds temporarily (no tests yet)
5. Create one basic smoke test to verify infrastructure works

**Acceptance Criteria:**
- `npm test` runs without dependency errors
- Can execute TypeScript test files
- Test runner starts successfully

#### Task 0.4: Create Environment Configuration
**Files:** `frontend/.env.example`, `README.md`

1. Create `.env.example` with:
   ```
   VITE_API_URL=http://localhost:8000
   VITE_WEBSOCKET_URL=ws://localhost:8000
   ```
2. Document environment variables in frontend README
3. Add note about CORS requirements (frontend:5173, backend:8000)
4. Update vite.config.ts to use env vars properly

**Acceptance Criteria:**
- `.env.example` exists and is documented
- Developers know what to configure
- Development setup instructions are clear

---

### Phase 1: Critical Integration Fixes (HIGH PRIORITY)

**Estimated Effort:** 3-4 days
**Priority:** HIGH - Required for basic functionality

#### Task 1.1: Implement Session Started Event Handling
**File:** `frontend/src/components/TherapySession.tsx`

1. Update `handleSessionStarted` to capture `session_id` from event
2. Update current session state with server-provided session_id
3. Ensure subsequent messages use correct session_id
4. Add error handling if session_id is missing

**Acceptance Criteria:**
- Session ID from backend is captured and stored
- Messages reference correct session ID
- Session state syncs with backend

#### Task 1.2: Fix SessionHistoryPage API Response Handling
**File:** `frontend/src/pages/SessionHistoryPage.tsx`

1. Verify backend API response structure at `/api/sessions`
2. Update response parsing to match actual structure
3. Add error handling for malformed responses
4. Add loading states

**Acceptance Criteria:**
- Session history loads correctly from backend
- Handles empty state gracefully
- Error messages are helpful

#### Task 1.3: Implement Authentication Context
**Files:** New `frontend/src/contexts/AuthContext.tsx`, update `TherapySession.tsx`

1. Create `AuthContext` with user ID and token management
2. Store auth data in localStorage
3. Provide login/logout methods (even if mocked initially)
4. Update `useWebSocket` to pull token from AuthContext
5. Remove hardcoded `'temp_token'` and `'default_user'`

**Acceptance Criteria:**
- No hardcoded auth values in components
- Auth state is manageable
- Can switch between users (even if simulated)

#### Task 1.4: Verify and Document CORS Configuration
**Files:** Backend `src/trio_server.py`, frontend documentation

1. Test cross-origin requests from frontend:5173 to backend:8000
2. Document required CORS headers in backend
3. Add CORS middleware if needed
4. Test WebSocket CORS (Origin header)

**Acceptance Criteria:**
- Frontend can make API calls to backend without CORS errors
- WebSocket connections work cross-origin
- CORS configuration is documented

---

### Phase 2: Testing & Foundation (MEDIUM PRIORITY)

**Estimated Effort:** 5-7 days
**Priority:** MEDIUM - Required before feature expansion

#### Task 2.1: WebSocket Service Tests
**File:** New `frontend/src/services/websocketService.test.ts`

1. Test connection success and failure
2. Test message sending
3. Test reconnection logic with exponential backoff
4. Test event callbacks (onStreamingChunk, onSessionStarted)
5. Mock WebSocket API

**Coverage Target:** 80%+ of WebSocketService

#### Task 2.2: AppContext Reducer Tests
**File:** New `frontend/src/contexts/AppContext.test.tsx`

1. Test all action types (SET_USER, SET_CURRENT_SESSION, etc.)
2. Test state transitions
3. Test localStorage integration
4. Test error handling

**Coverage Target:** 90%+ of reducer logic

#### Task 2.3: Component Integration Tests
**Files:** New test files for key components

1. `TherapySession.test.tsx` - Message sending, streaming, session management
2. `Dashboard.test.tsx` - User status display, session creation
3. `SessionHistoryPage.test.tsx` - Fetching and displaying history
4. `Navigation.test.tsx` - Routing and navigation

**Coverage Target:** 70%+ of component logic

#### Task 2.4: Add TypeScript Strict Mode Compliance
**File:** `frontend/tsconfig.json`

1. Enable strict mode if not already enabled
2. Fix any type errors that emerge
3. Remove `any` types from WebSocket callbacks
4. Add proper typing for all API responses

**Acceptance Criteria:**
- No TypeScript errors in strict mode
- No `any` types except where truly necessary
- All API responses have typed interfaces

---

### Phase 3: Feature Completion (LOWER PRIORITY)

**Estimated Effort:** 2-3 weeks
**Priority:** LOW - Only after Phases 0-2 complete

#### Task 3.1: Implement Intake Assessment Page
**File:** New `frontend/src/pages/IntakeAssessmentPage.tsx`

1. Build form for intake questions
2. Integrate with IntakeAgent via WebSocket
3. Save responses to backend
4. Navigate to assessment on completion

#### Task 3.2: Implement Therapy Assessment Page
**File:** New `frontend/src/pages/TherapyAssessmentPage.tsx`

1. Display therapy style options (Freud, Jung, CBT)
2. Show style descriptions from backend
3. Allow style selection
4. Create therapy plan via API

#### Task 3.3: Implement Profile Setup Page
**File:** New `frontend/src/pages/ProfileSetupPage.tsx`

1. Form for user profile (name, birthdate, profession)
2. POST to `/api/user/profile`
3. Update user status to INTAKE_IN_PROGRESS
4. Navigate to intake page

#### Task 3.4: Implement Progress Tracking Page
**File:** New `frontend/src/pages/ProgressTrackingPage.tsx`

1. Fetch therapy plan and session history
2. Display progress metrics
3. Show topic coverage
4. Visualize session frequency

#### Task 3.5: Implement Settings Page
**File:** New `frontend/src/pages/SettingsPage.tsx`

1. User preferences (theme, notifications, fontSize)
2. Session preferences
3. Account management
4. Export data option

#### Task 3.6: Implement Navigation Drawer & Settings Modal
**File:** `frontend/src/components/TherapySession.tsx`, new components

1. Create `NavigationDrawer.tsx` component
2. Create `SettingsModal.tsx` component
3. Wire up menu click handlers
4. Persist drawer state

---

### Phase 4: Polish & Optimization (FUTURE)

**Priority:** FUTURE - Nice to have

#### Task 4.1: Enhanced Loading States
1. Replace spinners with MUI Skeleton loaders
2. Add transition animations between pages
3. Implement optimistic UI updates

#### Task 4.2: Improved Error Handling
1. Add retry mechanisms for failed connections
2. Offline detection and graceful degradation
3. More specific error messages with recovery actions

#### Task 4.3: Mobile Responsiveness Testing
1. Test all pages on mobile viewports
2. Optimize touch targets
3. Add mobile-specific UI adaptations

#### Task 4.4: PWA Enhancement
1. Configure offline caching for session history
2. Add install prompt
3. Background sync for pending messages

---

## Testing Strategy

### Required Test Coverage (Phase 2)
- **Services:** 80%+ (WebSocketService, API clients)
- **Contexts/Reducers:** 90%+ (AppContext, AuthContext)
- **Components:** 70%+ (TherapySession, Dashboard, pages)
- **Overall:** 75%+

### Test Types
1. **Unit Tests:** Pure functions, reducers, utilities
2. **Integration Tests:** Components with contexts, WebSocket integration
3. **E2E Tests (Future):** Full user workflows with Playwright/Cypress

### Test Infrastructure
- **Framework:** Jest with ts-jest
- **Testing Library:** @testing-library/react
- **Mocking:** Mock WebSocket API, mock fetch for API calls
- **CI Integration:** Run tests in CI pipeline before deploy

---

## Success Criteria

### Phase 0 Complete When:
- ✅ Frontend connects to backend WebSocket successfully
- ✅ Data models match exactly (no type errors)
- ✅ `npm test` runs without errors
- ✅ Environment configuration is documented

### Phase 1 Complete When:
- ✅ Sessions sync between frontend and backend
- ✅ Session history loads correctly
- ✅ No hardcoded auth values
- ✅ CORS works for all endpoints

### Phase 2 Complete When:
- ✅ 75%+ test coverage achieved
- ✅ All critical paths have integration tests
- ✅ TypeScript strict mode with no errors
- ✅ CI tests pass

### Phase 3 Complete When:
- ✅ All workflow pages implemented
- ✅ Users can complete full journey (profile → intake → assessment → therapy)
- ✅ All placeholder routes removed
- ✅ Navigation and settings functional

---

## Risk Mitigation

### High Risk: Backend Changes During Frontend Work
- **Mitigation:** Establish contract/schema for WebSocket messages and API responses
- **Mitigation:** Use TypeScript interfaces as contracts shared between teams
- **Mitigation:** Version API endpoints if breaking changes needed

### Medium Risk: Test Infrastructure Takes Longer Than Expected
- **Mitigation:** Start with smoke tests, expand coverage incrementally
- **Mitigation:** Prioritize testing critical paths first
- **Mitigation:** Consider test-driven development for new features

### Low Risk: MUI Components Don't Meet Needs
- **Mitigation:** MUI is mature and well-documented, unlikely to be limiting
- **Mitigation:** Can create custom components if needed
- **Mitigation:** Large community for support

---

## Notes

- This assessment was conducted on 2025-11-29
- Backend is fully Trio-native using Quart + Hypercorn + native WebSockets
- Frontend was likely developed against an older asyncio+Socket.IO backend version
- **Priority:** Fix Phase 0 blockers before ANY feature work
