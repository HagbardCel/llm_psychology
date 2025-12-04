# Phase 1 Implementation Plan: Foundation

**Version**: 1.0
**Date**: 2025-12-02
**Estimated Duration**: 1 week (5 working days)
**Priority**: Critical
**Based on**: [ARCHITECTURE_ASSESSMENT.md](ARCHITECTURE_ASSESSMENT.md)

---

## Overview

Phase 1 establishes the foundation for refactoring the web frontend to match the console UI's thin-client architecture pattern. This phase focuses on creating infrastructure components that enable backend-driven navigation and proper client-server separation.

### Goals

1. ✅ Eliminate scattered `fetch()` calls with unified API client
2. ✅ Document WebSocket protocol as single source of truth
3. ✅ Remove fake authentication (temporary measure)
4. ✅ Enable backend-driven navigation with `/api/workflow/next-action` endpoint

### Non-Goals

- Full frontend refactoring (Phase 2)
- Type generation from backend (Phase 3)
- Real authentication implementation (Phase 4)
- Removing localStorage entirely (Phase 2)

---

## Task 1: Implement API Client Layer

**Priority**: 🔥 Critical
**Effort**: 1-2 days
**Dependencies**: None

### Objective

Create a centralized, type-safe API client to replace scattered `fetch()` calls across 15+ components. This provides consistent error handling, request configuration, and a foundation for future enhancements (retry logic, request interceptors, etc.).

### Current State Analysis

**Problems**:
- 15+ locations with raw `fetch()` calls
- Inconsistent error handling patterns
- Mixed base URLs: `import.meta.env.VITE_API_URL` vs relative paths
- No retry logic
- Difficult to test
- No request/response logging

**Example of Current Pattern** ([ProfilePage.tsx:56](frontend/src/pages/ProfilePage.tsx#L56)):
```typescript
const response = await fetch(`${import.meta.env.VITE_API_URL}/api/user/profile`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(userData)
});
```

**Locations Requiring Updates**:
- [frontend/src/pages/ProfilePage.tsx](frontend/src/pages/ProfilePage.tsx)
- [frontend/src/pages/AssessmentPage.tsx](frontend/src/pages/AssessmentPage.tsx)
- [frontend/src/pages/SessionHistoryPage.tsx](frontend/src/pages/SessionHistoryPage.tsx)
- [frontend/src/pages/SettingsPage.tsx](frontend/src/pages/SettingsPage.tsx)
- [frontend/src/contexts/AppContext.tsx](frontend/src/contexts/AppContext.tsx) (placeholder `refreshSessions()`)

### Technical Design

#### 1.1 Create API Client Class

**File**: `frontend/src/services/apiClient.ts`

```typescript
/**
 * Centralized API client for backend communication
 * Provides type-safe methods for all backend endpoints
 */

// Types
export interface ApiError extends Error {
  status: number;
  statusText: string;
  body?: any;
}

export interface ApiClientConfig {
  baseUrl: string;
  timeout?: number;
  headers?: Record<string, string>;
}

// Error class
export class ApiRequestError extends Error implements ApiError {
  status: number;
  statusText: string;
  body?: any;

  constructor(status: number, statusText: string, body?: any) {
    super(`HTTP ${status}: ${statusText}`);
    this.name = 'ApiRequestError';
    this.status = status;
    this.statusText = statusText;
    this.body = body;
  }
}

// Main API client
export class ApiClient {
  private baseUrl: string;
  private timeout: number;
  private defaultHeaders: Record<string, string>;

  constructor(config: ApiClientConfig) {
    this.baseUrl = config.baseUrl || import.meta.env.VITE_API_URL || 'http://localhost:8000';
    this.timeout = config.timeout || 30000;
    this.defaultHeaders = {
      'Content-Type': 'application/json',
      ...config.headers
    };
  }

  /**
   * Generic request method with timeout and error handling
   */
  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;

    // Create abort controller for timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeout);

    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          ...this.defaultHeaders,
          ...options.headers
        },
        signal: controller.signal
      });

      clearTimeout(timeoutId);

      // Handle non-OK responses
      if (!response.ok) {
        let errorBody;
        try {
          errorBody = await response.json();
        } catch {
          errorBody = await response.text();
        }
        throw new ApiRequestError(response.status, response.statusText, errorBody);
      }

      // Parse response
      const contentType = response.headers.get('content-type');
      if (contentType?.includes('application/json')) {
        return await response.json();
      }

      // For non-JSON responses, return text
      return await response.text() as unknown as T;

    } catch (error) {
      clearTimeout(timeoutId);

      if (error instanceof ApiRequestError) {
        throw error;
      }

      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new Error(`Request timeout after ${this.timeout}ms`);
      }

      throw new Error(`Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  }

  // HTTP method helpers
  async get<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, { method: 'GET' });
  }

  async post<T>(endpoint: string, data?: any): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined
    });
  }

  async put<T>(endpoint: string, data?: any): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'PUT',
      body: data ? JSON.stringify(data) : undefined
    });
  }

  async delete<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, { method: 'DELETE' });
  }
}

// Create singleton instance
export const apiClient = new ApiClient({
  baseUrl: import.meta.env.VITE_API_URL
});
```

#### 1.2 Create Type-Safe API Methods

**File**: `frontend/src/services/api.ts`

```typescript
/**
 * Type-safe API methods for all backend endpoints
 * Uses the underlying apiClient for actual HTTP calls
 */

import { apiClient } from './apiClient';
import {
  User,
  Session,
  TherapyPlan,
  TherapyStyle,
  WorkflowNextAction
} from '../types';

export interface CreateUserProfileRequest {
  user_id: string;
  name: string;
  birthdate?: string;
  profession?: string;
}

export interface CreateSessionRequest {
  user_id: string;
}

export interface CreateTherapyPlanRequest {
  user_id: string;
  therapy_style: string;
}

export interface WorkflowNextActionRequest {
  user_id: string;
  current_route?: string;
}

export interface HealthCheckResponse {
  status: string;
  timestamp: string;
  database: string;
}

/**
 * User API
 */
export const userApi = {
  async getStatus(userId: string): Promise<{ user_id: string; workflow_state: string; timestamp: string }> {
    return apiClient.get(`/api/user/status?user_id=${encodeURIComponent(userId)}`);
  },

  async createProfile(data: CreateUserProfileRequest): Promise<User> {
    return apiClient.post('/api/user/profile', data);
  }
};

/**
 * Session API
 */
export const sessionApi = {
  async getSessions(userId: string): Promise<Session[]> {
    return apiClient.get(`/api/sessions?user_id=${encodeURIComponent(userId)}`);
  },

  async getSession(sessionId: string): Promise<Session> {
    return apiClient.get(`/api/sessions/${sessionId}`);
  },

  async createSession(data: CreateSessionRequest): Promise<Session> {
    return apiClient.post('/api/sessions', data);
  },

  async extendSession(sessionId: string): Promise<void> {
    return apiClient.post(`/api/sessions/${sessionId}/extend`);
  }
};

/**
 * Therapy API
 */
export const therapyApi = {
  async getStyles(): Promise<TherapyStyle[]> {
    return apiClient.get('/api/therapy/styles');
  },

  async getPlan(userId: string): Promise<TherapyPlan | null> {
    return apiClient.get(`/api/therapy/plan?user_id=${encodeURIComponent(userId)}`);
  },

  async createPlan(data: CreateTherapyPlanRequest): Promise<TherapyPlan> {
    return apiClient.post('/api/therapy/plan', data);
  }
};

/**
 * Workflow API (NEW - Phase 1)
 */
export const workflowApi = {
  async getNextAction(data: WorkflowNextActionRequest): Promise<WorkflowNextAction> {
    return apiClient.post('/api/workflow/next-action', data);
  }
};

/**
 * Health check API
 */
export const healthApi = {
  async check(): Promise<HealthCheckResponse> {
    return apiClient.get('/health');
  }
};

// Export combined API object
export const api = {
  user: userApi,
  session: sessionApi,
  therapy: therapyApi,
  workflow: workflowApi,
  health: healthApi
};
```

#### 1.3 Update Type Definitions

**File**: `frontend/src/types/index.ts` (add to existing types)

```typescript
// Add to existing types

export interface WorkflowNextAction {
  action: 'navigate' | 'wait' | 'display' | 'error';
  route?: string;
  reason?: string;
  display?: {
    title: string;
    description?: string;
    primary_action?: {
      label: string;
      type: string;
    };
  };
  error?: string;
}

export interface TherapyStyle {
  style: string;
  name: string;
  description: string;
}
```

### Implementation Steps

#### Step 1.1: Create API Client Infrastructure (Day 1, 4 hours)

- [ ] Create `frontend/src/services/apiClient.ts`
- [ ] Implement `ApiClient` class with error handling
- [ ] Implement timeout mechanism
- [ ] Add request/response logging (console.log in development)
- [ ] Test with health check endpoint

**Testing**:
```typescript
// Test in browser console
import { apiClient } from './services/apiClient';

// Should succeed
const health = await apiClient.get('/health');
console.log('Health:', health);

// Should fail with proper error
try {
  await apiClient.get('/api/nonexistent');
} catch (error) {
  console.log('Expected error:', error.message);
}
```

#### Step 1.2: Create Type-Safe API Methods (Day 1, 4 hours)

- [ ] Create `frontend/src/services/api.ts`
- [ ] Implement all API method groups (user, session, therapy)
- [ ] Add TypeScript interfaces for request/response types
- [ ] Update `frontend/src/types/index.ts` with missing types
- [ ] Test each API method against running backend

**Testing**:
```bash
# Start backend
cd /app
make docker-run

# In another terminal, test frontend API
cd /app/frontend
npm run dev
# Test in browser console
```

#### Step 1.3: Migrate ProfilePage (Day 2, 2 hours)

- [ ] Replace `fetch()` in [ProfilePage.tsx:56](frontend/src/pages/ProfilePage.tsx#L56)
- [ ] Update error handling to use `ApiRequestError`
- [ ] Test profile creation flow
- [ ] Verify error messages display correctly

**Before**:
```typescript
const response = await fetch(`${import.meta.env.VITE_API_URL}/api/user/profile`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(userData)
});
if (!response.ok) {
  throw new Error(`HTTP ${response.status}: ${await response.text()}`);
}
const updatedUser = await response.json();
```

**After**:
```typescript
import { api } from '../services/api';
import { ApiRequestError } from '../services/apiClient';

try {
  const updatedUser = await api.user.createProfile({
    user_id: user?.id || `user_${Date.now()}`,
    ...formData
  });
  authActions.updateUser(updatedUser);
} catch (error) {
  if (error instanceof ApiRequestError) {
    setError(`Failed to save profile: ${error.body?.detail || error.statusText}`);
  } else {
    setError(error instanceof Error ? error.message : 'Unknown error');
  }
}
```

#### Step 1.4: Migrate Remaining Components (Day 2, 4 hours)

- [ ] Migrate [AssessmentPage.tsx](frontend/src/pages/AssessmentPage.tsx)
- [ ] Migrate [SessionHistoryPage.tsx](frontend/src/pages/SessionHistoryPage.tsx)
- [ ] Migrate [SettingsPage.tsx](frontend/src/pages/SettingsPage.tsx)
- [ ] Update [AppContext.tsx](frontend/src/contexts/AppContext.tsx) `refreshSessions()` placeholder

**For each component**:
1. Replace raw `fetch()` with `api.*` calls
2. Update error handling
3. Test functionality
4. Verify error messages

#### Step 1.5: Add Unit Tests (Day 2, 2 hours)

**File**: `frontend/src/services/__tests__/apiClient.test.ts`

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApiClient, ApiRequestError } from '../apiClient';

describe('ApiClient', () => {
  let client: ApiClient;

  beforeEach(() => {
    client = new ApiClient({ baseUrl: 'http://test.example.com' });
    global.fetch = vi.fn();
  });

  it('should make successful GET request', async () => {
    const mockData = { status: 'ok' };
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockData,
      headers: new Headers({ 'content-type': 'application/json' })
    });

    const result = await client.get('/health');
    expect(result).toEqual(mockData);
    expect(global.fetch).toHaveBeenCalledWith(
      'http://test.example.com/health',
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('should throw ApiRequestError on HTTP error', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({ detail: 'Resource not found' }),
      headers: new Headers({ 'content-type': 'application/json' })
    });

    await expect(client.get('/nonexistent')).rejects.toThrow(ApiRequestError);
  });

  it('should handle timeout', async () => {
    const slowClient = new ApiClient({
      baseUrl: 'http://test.example.com',
      timeout: 100
    });

    (global.fetch as any).mockImplementationOnce(
      () => new Promise((resolve) => setTimeout(resolve, 200))
    );

    await expect(slowClient.get('/slow')).rejects.toThrow('Request timeout');
  });
});
```

### Acceptance Criteria

- [ ] All components use `api.*` methods instead of raw `fetch()`
- [ ] No `fetch()` calls remain in pages or components (except WebSocketService)
- [ ] Consistent error handling across all API calls
- [ ] Base URL configured in single location
- [ ] API client has >80% test coverage
- [ ] Error messages are user-friendly
- [ ] Timeout protection works correctly
- [ ] All existing functionality still works

### Files to Create/Modify

**New Files**:
- `frontend/src/services/apiClient.ts` (~200 lines)
- `frontend/src/services/api.ts` (~150 lines)
- `frontend/src/services/__tests__/apiClient.test.ts` (~100 lines)

**Modified Files**:
- `frontend/src/types/index.ts` (+20 lines)
- `frontend/src/pages/ProfilePage.tsx` (~10 line change)
- `frontend/src/pages/AssessmentPage.tsx` (~10 line change)
- `frontend/src/pages/SessionHistoryPage.tsx` (~10 line change)
- `frontend/src/pages/SettingsPage.tsx` (~10 line change)
- `frontend/src/contexts/AppContext.tsx` (~5 line change)

---

## Task 2: Document WebSocket Protocol

**Priority**: ⚠️ High
**Effort**: 4 hours
**Dependencies**: None

### Objective

Create comprehensive documentation of the WebSocket message protocol as the single source of truth for client-server real-time communication. This prevents protocol drift between console UI and web frontend.

### Current State Analysis

**Problems**:
- Message types scattered across code
- Console UI and web frontend handle different subsets
- No version management
- No formal specification

**Message Types Observed**:

**Client → Server**:
- `session_request` - Request new therapy session
- `chat_message` - User message to therapist

**Server → Client**:
- `connected` - Connection confirmation
- `session_started` - Session created
- `chat_response_chunk` - Streaming LLM response
- `typing_start` / `typing_stop` - Typing indicators
- `user_status` - User status update (web only?)
- `error` - Error message

### Technical Design

See full protocol specification in the implementation plan document.

### Implementation Steps

#### Step 2.1: Create Protocol Documentation (Day 3, 3 hours)

- [ ] Create `docs/WEBSOCKET_PROTOCOL.md` with comprehensive specification
- [ ] Document all current message types with examples
- [ ] Add sequence diagrams for common flows
- [ ] Document error handling expectations
- [ ] Add reconnection strategy guidelines

#### Step 2.2: Add Protocol Constants (Day 3, 1 hour)

- [ ] Update `frontend/src/types/websocket.ts` with message type constants
- [ ] Create `console-ui/src/websocket_protocol.py`
- [ ] Update console UI to use constants instead of strings
- [ ] Update web frontend to use constants instead of strings

#### Step 2.3: Validate Implementation (Day 3, 1 hour)

- [ ] Review [trio_server.py](src/trio_server.py) WebSocket handler
- [ ] Verify all message types are documented
- [ ] Check for undocumented messages
- [ ] Cross-reference with console UI and web frontend

### Acceptance Criteria

- [ ] Complete protocol documentation in `docs/WEBSOCKET_PROTOCOL.md`
- [ ] All message types documented with examples
- [ ] Constants defined in both frontend and console UI
- [ ] No hardcoded message type strings in code
- [ ] Protocol version specified
- [ ] Reconnection strategy documented
- [ ] Sequence diagrams for common flows

---

## Task 3: Remove Fake Authentication

**Priority**: ⚠️ High
**Effort**: 4 hours
**Dependencies**: None

### Objective

Remove fake authentication from web frontend and implement temporary user ID prompt until real authentication is added in Phase 4. This prevents security false sense and clarifies that authentication is not implemented.

### Current State Analysis

**Problem**: [AuthContext.tsx:39-54](frontend/src/contexts/AuthContext.tsx#L39-L54)

```typescript
// Auto-login with default user for development
const defaultUser: User = {
  id: 'default_user',
  name: 'Default User',
  status: UserStatus.PROFILE_ONLY,
  // ...
};
const defaultToken = 'dev_token_' + Date.now();
```

**Issues**:
- False sense of security
- Auto-creates fake users
- Fake tokens that look real
- No actual backend validation
- Confusing for developers

### Implementation Steps

#### Step 3.1: Simplify AuthContext (Day 4, 1 hour)

- [ ] Remove fake user/token generation from [AuthContext.tsx](frontend/src/contexts/AuthContext.tsx)
- [ ] Simplify to only manage `userId` string
- [ ] Remove unnecessary User object complexity
- [ ] Update type definitions

#### Step 3.2: Create User ID Prompt (Day 4, 2 hours)

- [ ] Create `frontend/src/pages/UserIdPromptPage.tsx`
- [ ] Add warning message about temporary auth
- [ ] Implement simple form validation
- [ ] Style with Material-UI

#### Step 3.3: Update App Routing (Day 4, 1 hour)

- [ ] Update `frontend/src/App.tsx` routing logic
- [ ] Show UserIdPromptPage when no userId
- [ ] Update all components using `useAuth()` to use `userId` instead of `user`
- [ ] Test complete flow

### Acceptance Criteria

- [ ] No fake authentication code remains
- [ ] UserIdPromptPage displays on first visit
- [ ] Clear warning that auth is not implemented
- [ ] User ID stored in localStorage
- [ ] All components work with simplified auth
- [ ] Logout clears user ID
- [ ] No false sense of security

---

## Task 4: Add `/api/workflow/next-action` Endpoint

**Priority**: 🔥 Critical
**Effort**: 1-2 days
**Dependencies**: None

### Objective

Implement backend endpoint that tells frontend what to do next based on current user state. This is the foundation for backend-driven navigation and eliminates frontend workflow logic.

### Implementation Steps

#### Step 4.1: Backend Models (Day 5, 1 hour)

- [ ] Create `src/models/api_models.py` with Pydantic models
- [ ] Define `WorkflowNextActionRequest`
- [ ] Define `WorkflowNextActionResponse`
- [ ] Define `WorkflowDisplayAction`

#### Step 4.2: Backend Endpoint (Day 5, 3 hours)

- [ ] Add route to [trio_server.py](src/trio_server.py)
- [ ] Implement `_get_next_action()` handler
- [ ] Implement `_determine_next_action()` logic
- [ ] Map all WorkflowState values to navigation actions
- [ ] Add error handling

#### Step 4.3: Backend Testing (Day 5, 2 hours)

- [ ] Write unit tests for all workflow states
- [ ] Test error cases (missing user_id, invalid state)
- [ ] Run tests: `pytest tests/unit/test_workflow_next_action.py -v`

#### Step 4.4: Frontend Integration (Day 5, 2 hours)

- [ ] Update [Dashboard.tsx](frontend/src/components/Dashboard.tsx) to use endpoint
- [ ] Remove client-side `getNextRoute()` logic
- [ ] Remove client-side `getButtonText()` logic
- [ ] Test with backend running
- [ ] Verify all workflow states navigate correctly

#### Step 4.5: Integration Testing (Day 5, 2 hours)

- [ ] Test complete user flow: profile → intake → assessment → therapy
- [ ] Verify backend controls navigation at each step
- [ ] Test error cases
- [ ] Test with both console UI and web frontend
- [ ] Verify consistency

### Acceptance Criteria

- [ ] `/api/workflow/next-action` endpoint implemented
- [ ] All WorkflowState values mapped to actions
- [ ] Frontend Dashboard uses endpoint instead of local logic
- [ ] Unit tests for all workflow states pass
- [ ] Integration tests pass
- [ ] No frontend workflow decision logic remains
- [ ] Backend controls all navigation
- [ ] Console UI and web frontend have consistent navigation

---

## Testing Strategy

### Unit Testing

**Backend**:
- [ ] Test API client error handling
- [ ] Test workflow endpoint with all states
- [ ] Test error cases (invalid input, missing user)

**Frontend**:
- [ ] Test ApiClient class methods
- [ ] Test timeout handling
- [ ] Test error response parsing

### Integration Testing

- [ ] Test complete user flow end-to-end
- [ ] Test navigation controlled by backend
- [ ] Test error handling across API calls
- [ ] Test WebSocket protocol compliance

### Manual Testing

- [ ] Start backend: `make docker-run`
- [ ] Start frontend: `cd frontend && npm run dev`
- [ ] Test profile creation
- [ ] Test therapy session flow
- [ ] Test error messages
- [ ] Test backend-driven navigation
- [ ] Compare console UI vs web frontend behavior

---

## Rollout Plan

### Day 1: API Client Infrastructure
- Morning: Create ApiClient class
- Afternoon: Create type-safe API methods
- **Deliverable**: Working API client with tests

### Day 2: API Client Migration
- Morning: Migrate ProfilePage and AssessmentPage
- Afternoon: Migrate remaining components, add tests
- **Deliverable**: All components using unified API client

### Day 3: WebSocket Protocol Documentation
- Morning: Create comprehensive protocol docs
- Afternoon: Add constants, validate implementation
- **Deliverable**: Protocol specification document

### Day 4: Remove Fake Authentication
- Morning: Simplify AuthContext, create UserIdPromptPage
- Afternoon: Update routing, migrate components
- **Deliverable**: No fake auth, clear temporary solution

### Day 5: Backend-Driven Navigation
- Morning: Implement backend endpoint with tests
- Afternoon: Frontend integration, integration testing
- **Deliverable**: Backend controls workflow navigation

---

## Success Metrics

### Quantitative
- [ ] Zero `fetch()` calls outside of apiClient
- [ ] 100% of workflow states have next-action mapping
- [ ] >80% test coverage for new code
- [ ] All existing tests still pass
- [ ] Zero ESLint/TypeScript errors

### Qualitative
- [ ] Consistent error handling across app
- [ ] Clear protocol documentation
- [ ] No fake security tokens
- [ ] Backend controls navigation
- [ ] Code is more maintainable

---

## Risk Mitigation

### Risk: Breaking existing functionality
**Mitigation**:
- Comprehensive testing before/after each task
- Run full test suite after each migration
- Manual testing of critical flows

### Risk: Frontend/backend API mismatch
**Mitigation**:
- Type-safe API methods
- Unit tests for all endpoints
- Integration tests for full flows

### Risk: WebSocket protocol drift
**Mitigation**:
- Central protocol documentation
- Constants instead of strings
- Version management

### Risk: User experience disruption
**Mitigation**:
- Maintain all existing functionality
- Clear messaging about temporary auth
- Gradual rollout

---

## Dependencies & Prerequisites

### Required
- ✅ Backend running on port 8000
- ✅ Frontend dev server on port 5173
- ✅ Database initialized
- ✅ LLM service configured

### Tools
- ✅ Python 3.11+
- ✅ Node.js 18+
- ✅ pytest (backend testing)
- ✅ Vitest/Jest (frontend testing)
- ✅ TypeScript compiler

---

## Next Steps After Phase 1

After completing Phase 1, proceed to:

1. **Phase 2**: Refactor Web Frontend (Weeks 2-3)
   - Remove localStorage as data store
   - Implement React Query/SWR
   - Remove workflow logic from components
   - Remove duplicate type definitions

2. **Phase 3**: Type Safety (Week 4)
   - Generate OpenAPI spec from backend
   - Auto-generate TypeScript types
   - Integrate into build process

3. **Phase 4**: Authentication & Polish (Week 5)
   - Implement real authentication
   - Schema versioning
   - Integration tests for both clients
   - Performance optimization

---

## Appendix

### Related Documents
- [ARCHITECTURE_ASSESSMENT.md](ARCHITECTURE_ASSESSMENT.md) - Full architecture analysis
- [CLAUDE.md](CLAUDE.md) - Project development guidelines

### Key Files Reference
- Backend Server: [src/trio_server.py](src/trio_server.py)
- Orchestrator: [src/orchestration/trio_agent_orchestrator.py](src/orchestration/trio_agent_orchestrator.py)
- Workflow Engine: [src/orchestration/trio_workflow_engine.py](src/orchestration/trio_workflow_engine.py)
- Console Client: [console-ui/src/console_client.py](console-ui/src/console_client.py)
- Web Frontend Service: [frontend/src/services/websocketService.ts](frontend/src/services/websocketService.ts)

---

**Document Status**: Ready for Implementation
**Last Updated**: 2025-12-02
**Next Review**: After Phase 1 completion
