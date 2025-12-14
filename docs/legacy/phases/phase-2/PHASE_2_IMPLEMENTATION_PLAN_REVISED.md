# Phase 2 Implementation Plan: Testing & Foundation (REVISED)

## Goal

Establish a comprehensive testing foundation for the existing frontend codebase before proceeding with new feature development. This phase ensures code quality, enables confident refactoring, and prevents regressions.

## Why This Phase is Critical

**Per CLAUDE.md:**
> "Before every git commit, ensure that all new components have proper units and where applicable integration tests and that they run successfully."

**Current Reality:**
- WebSocketService: ✅ Tested (10 tests passing)
- AuthContext: ✅ Tested (10 tests passing)
- AppContext: ❌ 0% coverage
- TherapySession: ❌ 0% coverage
- Dashboard: ❌ 0% coverage
- MessageHistory: ❌ 0% coverage
- SessionHistoryPage: ❌ 0% coverage
- Other components: ❌ 0% coverage

**Without this foundation:**
- Cannot safely refactor code
- No confidence in changes
- Regressions go undetected
- Technical debt accumulates

---

## Prerequisites Completed (Phase 0 & Phase 1)

✅ **Phase 0 Blockers Resolved:**
- Socket.IO replaced with native WebSocket
- Data models aligned with backend
- Jest test infrastructure working
- Environment configuration documented
- TypeScript compilation passing

✅ **Phase 1 Integration:**
- CORS configured in backend
- Session synchronization implemented
- AuthContext created and tested
- SessionHistoryPage updated with shared types

---

## Task Breakdown

### Task 2.1: AppContext Reducer Tests ⚠️ CRITICAL

**Priority:** HIGHEST - Core state management, 0% coverage

#### File to Create
`frontend/src/contexts/__tests__/AppContext.test.tsx`

#### Coverage Requirements
- **Target:** 90%+ of reducer logic
- **Rationale:** AppContext manages all application state; bugs here affect everything

#### Test Specifications

##### 1. Reducer Action Tests

Test each action type:

```typescript
describe('AppContext Reducer', () => {
  describe('SET_USER action', () => {
    it('should set user in state', () => {});
    it('should preserve other state when setting user', () => {});
    it('should handle null user', () => {});
  });

  describe('SET_CURRENT_SESSION action', () => {
    it('should set current session', () => {});
    it('should clear current session when null', () => {});
  });

  describe('UPDATE_SESSION action', () => {
    it('should update existing session in sessions array', () => {});
    it('should update current session if IDs match', () => {});
    it('should throw error if session not found', () => {});
  });

  describe('ADD_SESSION action', () => {
    it('should add new session to sessions array', () => {});
    it('should not add duplicate session', () => {});
  });

  describe('SET_THERAPY_PLAN action', () => {
    it('should set therapy plan', () => {});
    it('should handle null therapy plan', () => {});
  });

  describe('CLEAR_ALL action', () => {
    it('should reset all state to initial values', () => {});
  });
});
```

##### 2. AppProvider Integration Tests

```typescript
describe('AppProvider', () => {
  it('should provide initial state to children', () => {});
  it('should load state from localStorage on mount', () => {});
  it('should persist state to localStorage on changes', () => {});
  it('should handle corrupted localStorage data', () => {});
  it('should provide actions to children', () => {});
});
```

##### 3. localStorage Integration

```typescript
describe('localStorage persistence', () => {
  it('should save user to localStorage when SET_USER called', () => {});
  it('should save sessions to localStorage when updated', () => {});
  it('should save therapy plan to localStorage when set', () => {});
  it('should clear localStorage on CLEAR_ALL', () => {});
  it('should handle localStorage quota exceeded', () => {});
});
```

##### 4. Schema Migration Tests

```typescript
describe('Schema migration', () => {
  it('should detect old schema version', () => {});
  it('should clear data when schema version < 2', () => {});
  it('should preserve data when schema version is current', () => {});
});
```

#### Acceptance Criteria
- [ ] All reducer actions have test coverage
- [ ] localStorage integration tested
- [ ] Schema migration logic tested
- [ ] Coverage >= 90%
- [ ] All tests passing
- [ ] No console errors in tests

---

### Task 2.2: TherapySession Component Tests ⚠️ HIGH

**Priority:** HIGH - Core user-facing component, complex logic

#### File to Create
`frontend/src/components/__tests__/TherapySession.test.tsx`

#### Coverage Requirements
- **Target:** 70%+ of component logic
- **Focus:** User interactions, WebSocket integration, state management

#### Test Specifications

##### 1. Rendering Tests

```typescript
describe('TherapySession - Rendering', () => {
  it('should render without crashing', () => {});
  it('should render session header with therapy style', () => {});
  it('should render connection status', () => {});
  it('should render message history', () => {});
  it('should render message input', () => {});
  it('should show loading state while session initializing', () => {});
});
```

##### 2. WebSocket Integration Tests

```typescript
describe('TherapySession - WebSocket Integration', () => {
  it('should connect to WebSocket on mount', () => {});
  it('should use auth token from AuthContext', () => {});
  it('should request therapy session when agent type is PSYCHOANALYST', () => {});
  it('should handle session_started event', () => {});
  it('should update session with server session ID', () => {});
  it('should set session ready flag on session_started', () => {});
  it('should disable input until session ready', () => {});
  it('should show error on session initialization timeout', () => {});
});
```

##### 3. Message Sending Tests

```typescript
describe('TherapySession - Message Sending', () => {
  it('should send message via WebSocket', () => {});
  it('should add user message to transcript immediately', () => {});
  it('should disable input while message sending', () => {});
  it('should show error when WebSocket disconnected', () => {});
  it('should not send empty messages', () => {});
});
```

##### 4. Streaming Response Tests

```typescript
describe('TherapySession - Streaming Responses', () => {
  it('should accumulate streaming chunks', () => {});
  it('should display streaming message in UI', () => {});
  it('should add final message on stream complete', () => {});
  it('should reset streaming state after completion', () => {});
  it('should handle streaming errors gracefully', () => {});
});
```

##### 5. Session Management Tests

```typescript
describe('TherapySession - Session Management', () => {
  it('should load session by ID on mount', () => {});
  it('should handle session not found error', () => {});
  it('should end session and update status', () => {});
  it('should clear current session on end', () => {});
});
```

##### 6. Error Handling Tests

```typescript
describe('TherapySession - Error Handling', () => {
  it('should display error in snackbar', () => {});
  it('should auto-dismiss error after 6 seconds', () => {});
  it('should allow manual error dismissal', () => {});
  it('should handle WebSocket errors', () => {});
});
```

#### Mocking Strategy

```typescript
// Mock dependencies
jest.mock('../contexts/AppContext');
jest.mock('../contexts/AuthContext');
jest.mock('../hooks/useWebSocket');
jest.mock('../hooks/useTypingIndicator');

// Mock implementations
const mockSendChatMessage = jest.fn();
const mockRequestSession = jest.fn();
const mockUseWebSocket = {
  connectionStatus: { isConnected: true, isConnecting: false },
  sendChatMessage: mockSendChatMessage,
  requestSession: mockRequestSession,
  isConnected: true,
  // ... other methods
};
```

#### Acceptance Criteria
- [ ] All major user flows tested
- [ ] WebSocket integration tested with mocks
- [ ] Streaming responses tested
- [ ] Error states tested
- [ ] Coverage >= 70%
- [ ] All tests passing

---

### Task 2.3: Dashboard Component Tests ⚠️ MEDIUM

**Priority:** MEDIUM - Important user-facing component

#### File to Create
`frontend/src/components/__tests__/Dashboard.test.tsx`

#### Coverage Requirements
- **Target:** 70%+ of component logic

#### Test Specifications

##### 1. Rendering Tests

```typescript
describe('Dashboard - Rendering', () => {
  it('should render without crashing', () => {});
  it('should display user greeting with name', () => {});
  it('should show workflow progress for user status', () => {});
  it('should display recent sessions', () => {});
  it('should show quick actions', () => {});
  it('should render therapy plan if exists', () => {});
});
```

##### 2. User Status Display Tests

```typescript
describe('Dashboard - User Status', () => {
  it('should show correct progress for PROFILE_ONLY', () => {});
  it('should show correct progress for INTAKE_IN_PROGRESS', () => {});
  it('should show correct progress for INTAKE_COMPLETE', () => {});
  it('should show correct progress for ASSESSMENT_COMPLETE', () => {});
  it('should show correct progress for PLAN_COMPLETE', () => {});
  it('should display appropriate next steps for each status', () => {});
});
```

##### 3. Session Creation Tests

```typescript
describe('Dashboard - Session Creation', () => {
  it('should create new session on button click', () => {});
  it('should navigate to session page after creation', () => {});
  it('should handle session creation errors', () => {});
  it('should disable button while creating session', () => {});
});
```

##### 4. Recent Sessions Display

```typescript
describe('Dashboard - Recent Sessions', () => {
  it('should display up to 5 recent sessions', () => {});
  it('should show session date and message count', () => {});
  it('should navigate to session on click', () => {});
  it('should show empty state when no sessions', () => {});
  it('should format session timestamps correctly', () => {});
});
```

#### Acceptance Criteria
- [ ] All user status values tested
- [ ] Session creation flow tested
- [ ] Recent sessions display tested
- [ ] Navigation tested
- [ ] Coverage >= 70%
- [ ] All tests passing

---

### Task 2.4: MessageHistory Component Tests

**Priority:** MEDIUM - Display component, less complex logic

#### File to Create
`frontend/src/components/__tests__/MessageHistory.test.tsx`

#### Coverage Requirements
- **Target:** 70%+ of component logic

#### Test Specifications

```typescript
describe('MessageHistory', () => {
  describe('Rendering', () => {
    it('should render without crashing', () => {});
    it('should render all messages in order', () => {});
    it('should display user messages on right', () => {});
    it('should display assistant messages on left', () => {});
    it('should format timestamps correctly', () => {});
  });

  describe('Streaming', () => {
    it('should display streaming message', () => {});
    it('should show typing indicator during streaming', () => {});
    it('should append streaming content to last message', () => {});
  });

  describe('Auto-scrolling', () => {
    it('should scroll to bottom on new message', () => {});
    it('should scroll to bottom during streaming', () => {});
    it('should handle long message history', () => {});
  });

  describe('Loading State', () => {
    it('should show loading spinner when isLoading true', () => {});
    it('should hide messages during loading', () => {});
  });

  describe('Empty State', () => {
    it('should show empty state when no messages', () => {});
    it('should not show empty state during loading', () => {});
  });
});
```

#### Acceptance Criteria
- [ ] Message rendering tested
- [ ] Streaming display tested
- [ ] Auto-scroll behavior tested
- [ ] Coverage >= 70%
- [ ] All tests passing

---

### Task 2.5: SessionHistoryPage Component Tests

**Priority:** LOW - Recently updated, simple logic

#### File to Create
`frontend/src/pages/__tests__/SessionHistoryPage.test.tsx`

#### Coverage Requirements
- **Target:** 70%+ of component logic

#### Test Specifications

```typescript
describe('SessionHistoryPage', () => {
  describe('Data Fetching', () => {
    it('should fetch sessions on mount', () => {});
    it('should not fetch if no user', () => {});
    it('should parse ISO date strings to Date objects', () => {});
    it('should handle fetch errors', () => {});
    it('should display error message on failure', () => {});
  });

  describe('Loading State', () => {
    it('should show skeleton loaders while loading', () => {});
    it('should hide skeleton after data loaded', () => {});
    it('should hide skeleton on error', () => {});
  });

  describe('Session Display', () => {
    it('should display all sessions', () => {});
    it('should show session date and time', () => {});
    it('should show message count', () => {});
    it('should show topic count', () => {});
    it('should handle sessions with no topics', () => {});
  });

  describe('Navigation', () => {
    it('should navigate to session on click', () => {});
    it('should pass correct session ID to route', () => {});
  });

  describe('Empty State', () => {
    it('should show empty state when no sessions', () => {});
    it('should display helpful message in empty state', () => {});
  });
});
```

#### Acceptance Criteria
- [ ] API fetching tested with mocks
- [ ] Date parsing tested
- [ ] Error handling tested
- [ ] Coverage >= 70%
- [ ] All tests passing

---

### Task 2.6: Additional Component Tests (As Time Permits)

#### Files to Create (Priority Order)

1. `frontend/src/components/__tests__/SessionHeader.test.tsx`
   - Session title display
   - Therapy style display
   - Menu/settings buttons
   - End session button

2. `frontend/src/components/__tests__/MessageInput.test.tsx`
   - Text input handling
   - Send button behavior
   - Disabled state
   - Character limit (if any)
   - Multi-line input

3. `frontend/src/components/__tests__/ConnectionStatus.test.tsx`
   - Status indicator colors
   - Status text display
   - Variant rendering (chip vs inline)

4. `frontend/src/hooks/__tests__/useTypingIndicator.test.tsx`
   - Typing start/stop callbacks
   - Timeout behavior
   - Debouncing logic

---

### Task 2.7: TypeScript Strict Mode Audit

**Priority:** MEDIUM - Type safety critical for maintainability

#### Objectives

1. **Verify Strict Mode Enabled**
   - ✅ Already confirmed: `tsconfig.json` has `"strict": true`

2. **Audit for `any` Types**

   ```bash
   # Find all usage of 'any' type in source code
   grep -rn ": any" frontend/src --include="*.ts" --include="*.tsx"
   ```

3. **Replace `any` with Proper Types**

   Priority files (in order):
   - `websocketService.ts` - Any remaining `any` in callbacks
   - `TherapySession.tsx` - Line 68, 100, 117 have `any` types
   - `SessionHistoryPage.tsx` - Line 45, 50 have `any` types
   - `AppContext.tsx` - Check reducer for `any` types

4. **Add Missing Interface Types**

   For all API responses:
   ```typescript
   // frontend/src/types/api.ts (new file)
   export interface SessionsResponse {
     sessions: Session[];
   }

   export interface ProfileResponse {
     user: User;
     profile: Profile;
   }

   // ... more as needed
   ```

#### Acceptance Criteria
- [ ] All API responses have typed interfaces
- [ ] No `any` types except where truly necessary (DOM events, etc.)
- [ ] TypeScript compiles with zero errors
- [ ] No new type suppressions (@ts-ignore, @ts-expect-error)

---

### Task 2.8: Integration Test - WebSocket Event Flow

**Priority:** HIGH - Critical path testing

#### File to Create
`frontend/src/__tests__/integration/websocket-session-flow.test.tsx`

#### Test Specifications

```typescript
describe('WebSocket Session Flow Integration', () => {
  it('should complete full session lifecycle', async () => {
    // 1. Render TherapySession
    // 2. Mock WebSocket connection
    // 3. Trigger session_started event
    // 4. Verify session ID updated
    // 5. Send user message
    // 6. Receive streaming response
    // 7. Verify message added to transcript
    // 8. End session
    // 9. Verify session status updated
  });

  it('should handle connection failure gracefully', async () => {
    // Test error recovery
  });

  it('should reconnect and resume session', async () => {
    // Test reconnection logic
  });
});
```

#### Acceptance Criteria
- [ ] Full session flow tested end-to-end
- [ ] Error scenarios tested
- [ ] Reconnection tested
- [ ] All tests passing

---

## Testing Infrastructure Improvements

### Update Test Scripts

**File:** `frontend/package.json`

Add convenience scripts:

```json
{
  "scripts": {
    "test": "jest",
    "test:watch": "jest --watch",
    "test:coverage": "jest --coverage",
    "test:ci": "jest --ci --coverage --maxWorkers=2",
    "test:unit": "jest --testPathIgnorePatterns=integration",
    "test:integration": "jest --testPathPattern=integration",
    "test:verbose": "jest --verbose"
  }
}
```

### Configure Coverage Thresholds

**File:** `frontend/jest.config.js`

Update coverage thresholds to be realistic:

```javascript
coverageThreshold: {
  global: {
    branches: 70,    // Lowered from 80
    functions: 70,   // Lowered from 80
    lines: 75,       // Lowered from 80
    statements: 75,  // Lowered from 80
  },
  // Per-directory thresholds
  './src/contexts/': {
    branches: 85,
    functions: 90,
    lines: 90,
    statements: 90,
  },
  './src/services/': {
    branches: 80,
    functions: 85,
    lines: 85,
    statements: 85,
  },
}
```

### Add Coverage Exclusions

Update `.coveragePathIgnorePatterns`:

```javascript
coveragePathIgnorePatterns: [
  '/node_modules/',
  '/dist/',
  '/.vite/',
  'setupTests.ts',
  'vite.config.ts',
  'main.tsx',
  '.d.ts',
]
```

---

## Verification Plan

### Automated Verification

After each task, run:

```bash
# Run all tests
npm test

# Check coverage
npm run test:coverage

# Verify TypeScript
npm run build
```

### Success Criteria by Task

| Task | Success Metric |
|------|----------------|
| 2.1 AppContext | 90%+ coverage, all tests pass |
| 2.2 TherapySession | 70%+ coverage, all tests pass |
| 2.3 Dashboard | 70%+ coverage, all tests pass |
| 2.4 MessageHistory | 70%+ coverage, all tests pass |
| 2.5 SessionHistoryPage | 70%+ coverage, all tests pass |
| 2.6 Additional Components | 70%+ coverage each |
| 2.7 TypeScript Audit | Zero `any` types in src/ |
| 2.8 Integration Tests | All scenarios pass |

### Overall Phase 2 Success Criteria

**Must achieve ALL of these:**

- [ ] ✅ Overall test coverage >= 75%
- [ ] ✅ All critical components have tests (AppContext, TherapySession, Dashboard)
- [ ] ✅ All tests passing (0 failures)
- [ ] ✅ TypeScript compilation with zero errors
- [ ] ✅ No `any` types in production code
- [ ] ✅ Coverage thresholds met per jest.config.js
- [ ] ✅ Integration tests demonstrate critical paths work
- [ ] ✅ `npm run test:ci` succeeds

**Nice to have:**
- [ ] 80%+ overall coverage
- [ ] All components have tests (not just critical ones)
- [ ] E2E tests with Playwright (future phase)

---

## Risk Mitigation

### Risk: Tests Take Longer Than Expected

**Mitigation:**
- Prioritize critical components first (AppContext, TherapySession)
- Can defer lower-priority components to future phase
- 75% coverage is acceptable; 100% is not required

### Risk: Discover Bugs While Writing Tests

**Mitigation:**
- This is GOOD - finding bugs is the purpose of testing
- Fix bugs as discovered
- Add tests that verify the fix

### Risk: Mocking is Complex

**Mitigation:**
- Use `@testing-library/react` best practices
- Mock at the boundary (hooks, services)
- Don't mock internal implementation details
- Keep mocks simple and focused

---

## Timeline Estimate

**Total Estimated Effort:** 5-7 days

| Task | Estimated Time |
|------|----------------|
| 2.1 AppContext Tests | 1-1.5 days |
| 2.2 TherapySession Tests | 1.5-2 days |
| 2.3 Dashboard Tests | 1 day |
| 2.4 MessageHistory Tests | 0.5 day |
| 2.5 SessionHistoryPage Tests | 0.5 day |
| 2.6 Additional Components | 0.5-1 day |
| 2.7 TypeScript Audit | 0.5 day |
| 2.8 Integration Tests | 0.5-1 day |

---

## Next Steps After Phase 2

Once Phase 2 is complete and all success criteria are met:

1. **Proceed to Phase 3: Feature Completion**
   - Implement Profile, Intake, Assessment pages
   - Build navigation infrastructure
   - ALL new code must have tests written first (TDD)

2. **Continuous Integration**
   - Add GitHub Actions workflow to run tests on every PR
   - Enforce coverage thresholds in CI
   - Block merges if tests fail

3. **Documentation**
   - Update README with testing instructions
   - Document mocking strategies
   - Add contribution guidelines requiring tests

---

## Notes

- This phase establishes the foundation for sustainable development
- Following CLAUDE.md guidance: tests before commits
- Tests are not overhead; they're insurance against bugs
- Well-tested code is easier to refactor and maintain
- Phase 3 (Feature Completion) will be FASTER with this foundation in place

---

**Assessment Date:** 2025-11-30
**Plan Version:** 2.0 (Revised)
**Supersedes:** PHASE_2_IMPLEMENTATION_PLAN.md (original feature-first approach)
