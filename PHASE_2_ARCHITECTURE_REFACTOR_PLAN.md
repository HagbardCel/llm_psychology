# Phase 2: Web Frontend Architecture Refactor - Detailed Implementation Plan

**Date**: 2025-12-02
**Based On**: [ARCHITECTURE_ASSESSMENT.md](ARCHITECTURE_ASSESSMENT.md) Section 7
**Duration**: 2-3 weeks (10-15 working days)
**Goal**: Refactor web frontend to match console client's thin-client architecture pattern
**Target**: Reduce from ~5,000 lines to ~1,500 lines of focused presentation logic

---

## TABLE OF CONTENTS

1. [Overview](#overview)
2. [Prerequisites (Phase 1 Completion)](#prerequisites)
3. [Architecture Changes](#architecture-changes)
4. [Detailed Task Breakdown](#detailed-task-breakdown)
5. [File-by-File Migration Plan](#file-by-file-migration-plan)
6. [Testing Strategy](#testing-strategy)
7. [Risk Mitigation](#risk-mitigation)
8. [Rollback Plan](#rollback-plan)
9. [Success Criteria](#success-criteria)

---

## OVERVIEW

### Current State (Before Phase 2)
- **Lines of Code**: ~5,000 (56 TypeScript files)
- **Architecture**: Thick client with substantial business logic duplication
- **State Management**: React Context + localStorage
- **Navigation**: Client-side routing with route guards
- **Backend Dependency**: ~60%

### Target State (After Phase 2)
- **Lines of Code**: ~1,500 (estimated 25-30 TypeScript files)
- **Architecture**: Thin client, pure presentation layer
- **State Management**: Server state cache only (React Query/SWR)
- **Navigation**: Backend-driven routing
- **Backend Dependency**: 100%

### Key Principles
1. **Backend as Single Source of Truth**: All state lives in backend
2. **No Business Logic in Frontend**: Components only render and collect input
3. **Backend-Driven Navigation**: Server tells client where to go
4. **Zero Data Duplication**: No localStorage persistence, only cache
5. **Type Safety**: Use Phase 1 generated types

---

## PREREQUISITES

### Phase 1 Must Be Complete
Before starting Phase 2, verify these Phase 1 deliverables exist:

- [ ] **API Client Layer**: `frontend/src/services/apiClient.ts`
  - Centralized HTTP client with error handling
  - Retry logic implemented
  - Type-safe request/response handling

- [ ] **WebSocket Protocol Documentation**: `docs/WEBSOCKET_PROTOCOL.md`
  - All message types documented
  - Examples included
  - Version specified

- [ ] **Backend Endpoint**: `/api/workflow/next-action`
  - Returns navigation instructions
  - Includes display configuration
  - Handles all workflow states

- [ ] **Generated Types**: `frontend/src/types/api.ts`
  - Auto-generated from OpenAPI spec
  - Build process integrated
  - All backend models represented

### Verification Commands
```bash
# Verify API client exists
test -f frontend/src/services/apiClient.ts && echo "✓ API Client exists"

# Verify WebSocket docs exist
test -f docs/WEBSOCKET_PROTOCOL.md && echo "✓ WebSocket docs exist"

# Verify backend endpoint
curl -X POST http://localhost:8000/api/workflow/next-action \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","current_route":"/"}' \
  && echo "✓ Backend endpoint exists"

# Verify type generation works
cd frontend && npm run generate-types && echo "✓ Type generation works"
```

---

## ARCHITECTURE CHANGES

### Before: Thick Client Architecture

```
┌─────────────────────────────────────────┐
│         Web Frontend (React)            │
├─────────────────────────────────────────┤
│                                         │
│  ┌───────────────────────────────────┐ │
│  │   Business Logic Layer            │ │
│  │  - Workflow state machine         │ │
│  │  - Agent selection                │ │
│  │  - Route guards                   │ │
│  │  - Data validation                │ │
│  └───────────────────────────────────┘ │
│                                         │
│  ┌───────────────────────────────────┐ │
│  │   State Management                │ │
│  │  - React Context API              │ │
│  │  - localStorage persistence       │ │
│  │  - Client-side session cache      │ │
│  └───────────────────────────────────┘ │
│                                         │
│  ┌───────────────────────────────────┐ │
│  │   Presentation Layer              │ │
│  │  - React components               │ │
│  │  - UI rendering                   │ │
│  └───────────────────────────────────┘ │
│                                         │
└─────────────────────────────────────────┘
              │
              ▼
     Backend (partial sync)
```

### After: Thin Client Architecture

```
┌─────────────────────────────────────────┐
│            Backend (Trio)               │
├─────────────────────────────────────────┤
│  - All business logic                   │
│  - Workflow state machine               │
│  - Agent orchestration                  │
│  - Navigation instructions              │
│  - Data validation                      │
│  - Session management                   │
└─────────────────────────────────────────┘
              │
              │ REST API + WebSocket
              ▼
┌─────────────────────────────────────────┐
│         Web Frontend (React)            │
├─────────────────────────────────────────┤
│                                         │
│  ┌───────────────────────────────────┐ │
│  │   Presentation Layer ONLY         │ │
│  │  - React components               │ │
│  │  - User input collection          │ │
│  │  - Display backend responses      │ │
│  │  - Streaming LLM responses        │ │
│  └───────────────────────────────────┘ │
│                                         │
│  ┌───────────────────────────────────┐ │
│  │   Thin State Layer                │ │
│  │  - React Query (server cache)     │ │
│  │  - WebSocket connection           │ │
│  │  - UI state only (theme, etc)     │ │
│  └───────────────────────────────────┘ │
│                                         │
└─────────────────────────────────────────┘
```

---

## DETAILED TASK BREAKDOWN

### Week 1: Remove localStorage and Implement Server State (Days 1-5)

#### Day 1: Setup React Query Infrastructure

**Task 1.1**: Install and configure React Query
```bash
cd frontend
npm install @tanstack/react-query @tanstack/react-query-devtools
```

**Task 1.2**: Create QueryClient provider (`frontend/src/providers/QueryProvider.tsx`)
```typescript
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      cacheTime: 1000 * 60 * 10, // 10 minutes
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
});

export function QueryProvider({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
```

**Task 1.3**: Wrap App with QueryProvider
- Update `frontend/src/main.tsx`
- Add QueryProvider above existing providers

**Files Modified**: 3 files
**Testing**: Verify React Query DevTools appears in UI

---

#### Day 2: Create Custom Hooks for Server State

**Task 2.1**: User profile hook (`frontend/src/hooks/useUserProfile.ts`)
```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/apiClient';
import type { User, UserProfileUpdate } from '../types/api';

export function useUserProfile(userId: string) {
  return useQuery({
    queryKey: ['user', userId],
    queryFn: () => api.get<User>(`/api/user/profile?user_id=${userId}`),
    enabled: !!userId,
  });
}

export function useUpdateUserProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: UserProfileUpdate) =>
      api.post<User>('/api/user/profile', data),
    onSuccess: (data) => {
      queryClient.setQueryData(['user', data.userId], data);
      queryClient.invalidateQueries({ queryKey: ['user'] });
    },
  });
}
```

**Task 2.2**: Session history hook (`frontend/src/hooks/useSessionHistory.ts`)
```typescript
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/apiClient';
import type { Session } from '../types/api';

export function useSessionHistory(userId: string) {
  return useQuery({
    queryKey: ['sessions', userId],
    queryFn: () => api.get<Session[]>(`/api/sessions?user_id=${userId}`),
    enabled: !!userId,
  });
}

export function useSession(sessionId: string) {
  return useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => api.get<Session>(`/api/sessions/${sessionId}`),
    enabled: !!sessionId,
  });
}
```

**Task 2.3**: Therapy plan hook (`frontend/src/hooks/useTherapyPlan.ts`)
```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/apiClient';
import type { TherapyPlan } from '../types/api';

export function useTherapyPlan(userId: string) {
  return useQuery({
    queryKey: ['therapyPlan', userId],
    queryFn: () => api.get<TherapyPlan>(`/api/therapy/plan?user_id=${userId}`),
    enabled: !!userId,
  });
}

export function useCreateTherapyPlan() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { userId: string; selectedStyle: string }) =>
      api.post<TherapyPlan>('/api/therapy/plan', data),
    onSuccess: (data, variables) => {
      queryClient.setQueryData(['therapyPlan', variables.userId], data);
      queryClient.invalidateQueries({ queryKey: ['user', variables.userId] });
    },
  });
}
```

**Task 2.4**: Workflow navigation hook (`frontend/src/hooks/useWorkflowNavigation.ts`)
```typescript
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/apiClient';
import type { WorkflowAction } from '../types/api';

export function useWorkflowNextAction(userId: string, currentRoute: string) {
  return useQuery({
    queryKey: ['workflow', 'next-action', userId, currentRoute],
    queryFn: () =>
      api.post<WorkflowAction>('/api/workflow/next-action', {
        user_id: userId,
        current_route: currentRoute,
      }),
    enabled: !!userId,
    staleTime: 0, // Always check for workflow changes
  });
}
```

**Files Created**: 4 new hook files
**Testing**: Unit tests for each hook

---

#### Day 3: Remove localStorage from AppContext

**Task 3.1**: Audit localStorage usage
```bash
cd frontend
grep -r "localStorage" src/ --include="*.ts" --include="*.tsx"
```

**Task 3.2**: Refactor AppContext (`frontend/src/contexts/AppContext.tsx`)

**Before**:
```typescript
const [user, setUser] = useState<User | null>(() => {
  const stored = localStorage.getItem('user_profile');
  return stored ? JSON.parse(stored) : null;
});

useEffect(() => {
  if (user) {
    localStorage.setItem('user_profile', JSON.stringify(user));
  }
}, [user]);
```

**After**:
```typescript
// Remove ALL localStorage code
// User state comes from React Query only
const userId = sessionStorage.getItem('current_user_id'); // Session-only
const { data: user, isLoading } = useUserProfile(userId || '');
```

**Task 3.3**: Update AppContext to remove:
- `localStorage.getItem('user_profile')`
- `localStorage.setItem('user_profile', ...)`
- `localStorage.getItem('app_state')`
- `localStorage.setItem('app_state', ...)`
- `localStorage.getItem('therapy_plan')`
- `localStorage.setItem('therapy_plan', ...)`
- `SCHEMA_VERSION` constant (no longer needed)
- `loadFromLocalStorage()` function
- `saveToLocalStorage()` function

**Task 3.4**: Keep only UI preferences in localStorage:
- Theme (dark/light)
- Font size
- Sidebar collapsed state

**Files Modified**: 1 file (AppContext.tsx)
**Lines Removed**: ~150-200 lines
**Testing**: Ensure app still works without localStorage persistence

---

#### Day 4: Update Components to Use React Query Hooks

**Task 4.1**: Refactor Dashboard (`frontend/src/components/Dashboard.tsx`)

**Remove**:
- `getNextRoute()` function
- `getButtonText()` function
- `shouldShowContinue()` function
- Direct user state manipulation

**Add**:
```typescript
import { useWorkflowNextAction } from '../hooks/useWorkflowNavigation';
import { useUserProfile } from '../hooks/useUserProfile';

function Dashboard() {
  const navigate = useNavigate();
  const userId = getCurrentUserId(); // Helper function

  const { data: user } = useUserProfile(userId);
  const { data: nextAction } = useWorkflowNextAction(userId, '/');

  const handleContinue = () => {
    if (nextAction?.route) {
      navigate(nextAction.route);
    }
  };

  return (
    <div>
      <h1>{nextAction?.display?.title || 'Dashboard'}</h1>
      <p>{nextAction?.display?.description}</p>
      {nextAction?.display?.primary_action && (
        <button onClick={handleContinue}>
          {nextAction.display.primary_action.label}
        </button>
      )}
    </div>
  );
}
```

**Task 4.2**: Refactor ProfilePage (`frontend/src/pages/ProfilePage.tsx`)

**Remove**:
- Direct fetch() calls
- localStorage updates
- Client-side validation logic (keep UI validation only)

**Add**:
```typescript
import { useUserProfile, useUpdateUserProfile } from '../hooks/useUserProfile';

function ProfilePage() {
  const userId = getCurrentUserId();
  const { data: user, isLoading } = useUserProfile(userId);
  const updateProfile = useUpdateUserProfile();

  const handleSubmit = async (formData: UserProfileUpdate) => {
    await updateProfile.mutateAsync(formData);
    // React Query automatically updates cache
  };

  if (isLoading) return <LoadingSpinner />;

  return <ProfileForm user={user} onSubmit={handleSubmit} />;
}
```

**Task 4.3**: Refactor SessionHistoryPage (`frontend/src/pages/SessionHistoryPage.tsx`)

**Remove**:
- localStorage session cache
- Direct fetch() calls

**Add**:
```typescript
import { useSessionHistory } from '../hooks/useSessionHistory';

function SessionHistoryPage() {
  const userId = getCurrentUserId();
  const { data: sessions, isLoading, error } = useSessionHistory(userId);

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorDisplay error={error} />;

  return <SessionList sessions={sessions || []} />;
}
```

**Task 4.4**: Refactor AssessmentPage (`frontend/src/pages/AssessmentPage.tsx`)

**Remove**:
- Style recommendations hardcoded descriptions
- Direct fetch() calls
- localStorage therapy plan cache

**Add**:
```typescript
import { useCreateTherapyPlan } from '../hooks/useTherapyPlan';
import { useWorkflowNextAction } from '../hooks/useWorkflowNavigation';

function AssessmentPage() {
  const userId = getCurrentUserId();
  const createPlan = useCreateTherapyPlan();
  const { data: nextAction } = useWorkflowNextAction(userId, '/assessment');

  const handleSelectStyle = async (style: string) => {
    await createPlan.mutateAsync({ userId, selectedStyle: style });
    // Backend will update user status, React Query will refetch
    // nextAction will automatically update with new route
  };

  // Render based on backend instructions
  return (
    <div>
      <h1>{nextAction?.display?.title}</h1>
      {/* Display options provided by backend */}
    </div>
  );
}
```

**Files Modified**: 4 major components
**Lines Removed**: ~300-400 lines
**Testing**: Integration tests for each page

---

#### Day 5: Remove Duplicate Type Definitions

**Task 5.1**: Audit type definitions
```bash
cd frontend/src
find . -name "*.ts" -o -name "*.tsx" | xargs grep -l "^export interface\|^export type"
```

**Task 5.2**: Delete duplicate files
- Delete `frontend/src/types/index.ts` (replaced by generated `api.ts`)
- Delete `frontend/src/types/websocket.ts` (use generated types)
- Keep only UI-specific types (e.g., component props, UI state)

**Task 5.3**: Update imports throughout codebase
```typescript
// Before
import { User, Session } from '../types/index';

// After
import { User, Session } from '../types/api'; // Generated
```

**Task 5.4**: Create minimal UI types file (`frontend/src/types/ui.ts`)
```typescript
// Only UI-specific types, NOT data models
export interface LoadingState {
  isLoading: boolean;
  error: Error | null;
}

export interface ComponentProps {
  // Component-specific props only
}
```

**Files Deleted**: 2-3 files
**Files Modified**: ~20 files (import updates)
**Lines Removed**: ~200-300 lines
**Testing**: TypeScript compilation must succeed

---

### Week 2: Backend-Driven Navigation (Days 6-10)

#### Day 6: Remove Client-Side Route Guards

**Task 6.1**: Identify all route guards
```bash
cd frontend/src
grep -r "RequireAuth\|RequireStatus\|ProtectedRoute" --include="*.tsx"
```

**Task 6.2**: Remove route guard components
- Delete `frontend/src/components/RequireStatus.tsx`
- Delete `frontend/src/components/RequireAuth.tsx` (if exists)
- Delete `frontend/src/components/ProtectedRoute.tsx` (if exists)

**Task 6.3**: Simplify routing in App.tsx
```typescript
// Before
<Route path="/intake" element={
  <RequireStatus status={[UserStatus.INTAKE_IN_PROGRESS]}>
    <IntakePage />
  </RequireStatus>
} />

// After
<Route path="/intake" element={<IntakePage />} />
```

**Task 6.4**: Add single root guard (optional, for auth only)
```typescript
function App() {
  const userId = getCurrentUserId();

  if (!userId) {
    return <LoginPage />;
  }

  return (
    <Routes>
      {/* All routes accessible, backend controls flow */}
      <Route path="/" element={<Dashboard />} />
      <Route path="/intake" element={<IntakePage />} />
      <Route path="/assessment" element={<AssessmentPage />} />
      {/* ... */}
    </Routes>
  );
}
```

**Files Deleted**: 2-3 route guard components
**Files Modified**: 1 file (App.tsx)
**Lines Removed**: ~100-150 lines
**Testing**: Ensure all routes still accessible

---

#### Day 7: Implement Backend-Driven Navigation

**Task 7.1**: Create navigation hook (`frontend/src/hooks/useBackendNavigation.ts`)
```typescript
import { useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useWorkflowNextAction } from './useWorkflowNavigation';

export function useBackendNavigation(userId: string) {
  const navigate = useNavigate();
  const location = useLocation();
  const { data: nextAction } = useWorkflowNextAction(userId, location.pathname);

  useEffect(() => {
    if (nextAction?.action === 'navigate' && nextAction.route !== location.pathname) {
      navigate(nextAction.route);
    }
  }, [nextAction, navigate, location.pathname]);

  return nextAction;
}
```

**Task 7.2**: Add to Dashboard and all pages
```typescript
function Dashboard() {
  const userId = getCurrentUserId();
  const nextAction = useBackendNavigation(userId);

  // Component automatically navigates when backend says so
  return (
    <div>
      <h1>{nextAction?.display?.title || 'Dashboard'}</h1>
      {/* ... */}
    </div>
  );
}
```

**Task 7.3**: Remove all client-side navigation logic
```bash
# Find and remove:
cd frontend/src
grep -r "navigate(" --include="*.tsx" | grep -v "useNavigate\|import"
```

**Examples to remove**:
```typescript
// DELETE: Client deciding where to go
if (user.status === UserStatus.INTAKE_COMPLETE) {
  navigate('/assessment');
}

// DELETE: Manual workflow routing
const handleComplete = () => {
  navigate('/therapy');
};

// KEEP: User-initiated navigation (back button, menu clicks)
<button onClick={() => navigate(-1)}>Back</button>
```

**Files Modified**: All page components (~8-10 files)
**Lines Removed**: ~150-200 lines
**Testing**: Navigation works based on backend state

---

#### Day 8: Remove Workflow Logic from Components

**Task 8.1**: Identify workflow logic in components
```bash
cd frontend/src
grep -r "switch.*status\|UserStatus\.\|WorkflowState\." --include="*.tsx"
```

**Task 8.2**: Remove status-based rendering logic

**Before** (Dashboard.tsx):
```typescript
function getNextRoute(status: UserStatus): string {
  switch (status) {
    case UserStatus.PROFILE_ONLY:
      return '/profile';
    case UserStatus.INTAKE_IN_PROGRESS:
      return '/intake';
    case UserStatus.INTAKE_COMPLETE:
      return '/assessment';
    case UserStatus.PLAN_COMPLETE:
      return '/therapy';
    default:
      return '/';
  }
}

function getButtonText(status: UserStatus): string {
  switch (status) {
    case UserStatus.PROFILE_ONLY:
      return 'Complete Profile';
    case UserStatus.INTAKE_IN_PROGRESS:
      return 'Continue Intake';
    // ... 8 cases
  }
}
```

**After**:
```typescript
// All removed - backend provides this via nextAction.display
function Dashboard() {
  const nextAction = useBackendNavigation(getCurrentUserId());

  return (
    <div>
      <h1>{nextAction?.display?.title}</h1>
      <p>{nextAction?.display?.description}</p>
      <button onClick={() => handleAction(nextAction)}>
        {nextAction?.display?.primary_action?.label}
      </button>
    </div>
  );
}
```

**Task 8.3**: Remove agent selection logic (if any exists in frontend)

**Task 8.4**: Remove topic tracking/management from intake components

**Files Modified**: 5-8 components
**Lines Removed**: ~400-600 lines
**Testing**: All workflow transitions work correctly

---

#### Day 9: Simplify State Management

**Task 9.1**: Remove AppContext business logic

**Before** (AppContext.tsx - ~300 lines):
```typescript
export interface AppContextType {
  user: User | null;
  setUser: (user: User) => void;
  therapyPlan: TherapyPlan | null;
  setTherapyPlan: (plan: TherapyPlan) => void;
  sessions: Session[];
  setSessions: (sessions: Session[]) => void;
  currentSession: Session | null;
  setCurrentSession: (session: Session | null) => void;
  // ... 15+ more fields
}
```

**After** (AppContext.tsx - ~50 lines):
```typescript
export interface AppContextType {
  // Only UI state
  theme: 'light' | 'dark';
  setTheme: (theme: 'light' | 'dark') => void;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<'light' | 'dark'>(() =>
    localStorage.getItem('theme') as 'light' | 'dark' || 'light'
  );
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    localStorage.setItem('theme', theme);
  }, [theme]);

  return (
    <AppContext.Provider value={{ theme, setTheme, sidebarOpen, setSidebarOpen }}>
      {children}
    </AppContext.Provider>
  );
}
```

**Task 9.2**: Remove AuthContext fake authentication
- Delete `frontend/src/contexts/AuthContext.tsx`
- Use real session from backend (from Phase 1 auth work)
- Store only `session_id` in sessionStorage (not localStorage)

**Task 9.3**: Update all components using contexts
```typescript
// Before
const { user, setUser, therapyPlan, sessions } = useAppContext();

// After
const { theme, setTheme } = useAppContext(); // Only UI state
const userId = getCurrentUserId();
const { data: user } = useUserProfile(userId); // Server state
const { data: therapyPlan } = useTherapyPlan(userId); // Server state
const { data: sessions } = useSessionHistory(userId); // Server state
```

**Files Modified**: 2 context files, ~15 components
**Files Deleted**: 1 file (AuthContext.tsx if fake)
**Lines Removed**: ~400-600 lines
**Testing**: All components render correctly

---

#### Day 10: WebSocket Integration Cleanup

**Task 10.1**: Review WebSocket service (`frontend/src/services/websocketService.ts`)

**Task 10.2**: Ensure WebSocket only handles realtime events
- Keep: `chat_response_chunk`, `session_started`, `session_ended`, `typing_indicator`
- Remove: Any state management or localStorage updates

**Task 10.3**: Integrate with React Query for state updates
```typescript
// In websocketService.ts
const handleMessage = (message: WebSocketMessage) => {
  switch (message.type) {
    case 'state_change':
      // Invalidate React Query cache to refetch
      queryClient.invalidateQueries({ queryKey: ['user', message.data.user_id] });
      queryClient.invalidateQueries({ queryKey: ['workflow', 'next-action'] });
      break;

    case 'chat_response_chunk':
      // Just emit event, component handles display
      eventEmitter.emit('chat_chunk', message.data);
      break;
  }
};
```

**Task 10.4**: Remove any duplicate WebSocket message type definitions
- Use types from generated `api.ts` or WebSocket protocol doc

**Files Modified**: 2 files
**Lines Removed**: ~50-100 lines
**Testing**: WebSocket messages handled correctly

---

### Week 3: Testing, Cleanup, and Documentation (Days 11-15)

#### Day 11: Component Testing

**Task 11.1**: Update existing tests to remove localStorage mocks
```typescript
// Before
beforeEach(() => {
  localStorage.setItem('user_profile', JSON.stringify(mockUser));
});

// After
beforeEach(() => {
  // Mock React Query instead
  queryClient.setQueryData(['user', 'test-user'], mockUser);
});
```

**Task 11.2**: Add tests for new hooks
```typescript
// tests/hooks/useUserProfile.test.ts
describe('useUserProfile', () => {
  it('fetches user profile from API', async () => {
    const { result } = renderHook(() => useUserProfile('test-user'), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockUser);
  });
});
```

**Task 11.3**: Add integration tests for navigation
```typescript
// tests/integration/navigation.test.tsx
describe('Backend-driven navigation', () => {
  it('navigates to intake when backend returns intake route', async () => {
    mockNextAction({ action: 'navigate', route: '/intake' });

    render(<App />, { wrapper: createAppWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/Intake Session/)).toBeInTheDocument();
    });
  });
});
```

**Test Coverage Goal**: >80%

**Files Created**: 10-15 test files
**Testing Time**: Full day for comprehensive testing

---

#### Day 12: Integration Testing

**Task 12.1**: Test complete user flows
- New user: Profile → Intake → Assessment → Therapy
- Returning user: Dashboard → Continue therapy
- Session history viewing
- Therapy plan updates

**Task 12.2**: Test WebSocket integration
- Message streaming
- State changes trigger navigation
- Connection resilience

**Task 12.3**: Test error handling
- Network failures
- API errors
- WebSocket disconnections

**Task 12.4**: Test with real backend
```bash
# Start backend
cd /app
make docker-run

# Run frontend
cd frontend
npm run dev

# Manual testing checklist
```

**Manual Testing Checklist**:
- [ ] New user can complete full workflow
- [ ] Returning user continues from correct state
- [ ] Navigation works without manual intervention
- [ ] No console errors
- [ ] No localStorage warnings
- [ ] React Query DevTools shows correct cache
- [ ] WebSocket messages handled properly
- [ ] All API calls succeed
- [ ] Error states display correctly
- [ ] Loading states display correctly

---

#### Day 13: Code Cleanup

**Task 13.1**: Remove dead code
```bash
cd frontend/src
# Find unused exports
npx ts-prune

# Remove unused imports
npx eslint --fix .
```

**Task 13.2**: Delete unused files
- Old type definition files
- Removed components
- Unused utilities
- Legacy state management files

**Task 13.3**: Code formatting
```bash
cd frontend
npm run format
npm run lint --fix
```

**Task 13.4**: Final file count verification
```bash
cd frontend/src
find . -name "*.ts" -o -name "*.tsx" | wc -l
# Target: 25-30 files (down from 56)

cloc src/
# Target: ~1,500 lines (down from ~5,000)
```

**Expected Deletions**:
- ~25-30 files removed
- ~3,500 lines removed
- ~15 components simplified

---

#### Day 14: Documentation

**Task 14.1**: Update README (`frontend/README.md`)
```markdown
# Frontend Architecture

## Overview
Thin client React application following backend-driven architecture pattern.

## Principles
- Backend is single source of truth
- No business logic in frontend
- Server state managed by React Query
- Backend-driven navigation
- WebSocket for realtime updates

## Key Technologies
- React 18
- React Router 6
- TanStack React Query v5
- TypeScript (generated types)
- Vite

## State Management
- **Server State**: React Query (user, sessions, therapy plans)
- **UI State**: React Context (theme, sidebar)
- **Session State**: sessionStorage (current user ID only)

## Navigation
Backend controls all navigation via `/api/workflow/next-action` endpoint.
Components render based on backend instructions.

## Development

### Start Dev Server
\`\`\`bash
npm run dev
\`\`\`

### Generate Types
\`\`\`bash
npm run generate-types
\`\`\`

### Testing
\`\`\`bash
npm test                  # Run all tests
npm run test:coverage     # Coverage report
\`\`\`

## Architecture Diagrams
See `/docs/ARCHITECTURE_ASSESSMENT.md` for detailed diagrams.
```

**Task 14.2**: Create migration notes (`docs/PHASE_2_MIGRATION_NOTES.md`)
- What changed
- Why it changed
- How to work with new architecture
- Common patterns
- Troubleshooting

**Task 14.3**: Update component documentation
- Add JSDoc comments to components
- Document props interfaces
- Include usage examples

**Task 14.4**: Create architecture decision record
```markdown
# ADR: Thin Client Architecture

## Status
Implemented (Phase 2)

## Context
Web frontend had substantial business logic duplication with backend.

## Decision
Refactor to thin client pattern matching console UI architecture.

## Consequences
- 70% reduction in code
- Single source of truth
- Easier maintenance
- Backend controls all workflow
```

---

#### Day 15: Performance Optimization and Final Review

**Task 15.1**: Performance audit
```bash
cd frontend
npm run build
npm run preview

# Check bundle size
npx vite-bundle-visualizer
```

**Task 15.2**: Optimize React Query settings
```typescript
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // Tune based on data freshness needs
      cacheTime: 1000 * 60 * 10,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
    },
  },
});
```

**Task 15.3**: Code splitting (if needed)
```typescript
// Lazy load pages
const IntakePage = lazy(() => import('./pages/IntakePage'));
const AssessmentPage = lazy(() => import('./pages/AssessmentPage'));
```

**Task 15.4**: Final review checklist
- [ ] All tests passing
- [ ] No TypeScript errors
- [ ] No ESLint warnings
- [ ] Bundle size acceptable (<500KB)
- [ ] Lighthouse score >90
- [ ] No console errors/warnings
- [ ] All documentation updated
- [ ] Migration guide complete

**Task 15.5**: Team demo
- Demonstrate thin client architecture
- Show React Query DevTools
- Walk through navigation flow
- Compare before/after metrics

---

## FILE-BY-FILE MIGRATION PLAN

### Files to DELETE (30+ files)

#### Context/State Management
- `frontend/src/contexts/AuthContext.tsx` - Fake auth removed
- `frontend/src/contexts/SessionContext.tsx` - Server state only
- `frontend/src/contexts/TherapyContext.tsx` - Server state only

#### Route Guards
- `frontend/src/components/RequireStatus.tsx` - No client-side guards
- `frontend/src/components/RequireAuth.tsx` - Simplified auth
- `frontend/src/components/ProtectedRoute.tsx` - Backend controls access

#### Type Definitions
- `frontend/src/types/index.ts` - Use generated types
- `frontend/src/types/websocket.ts` - Use protocol types
- `frontend/src/types/session.ts` - Use generated types

#### Utilities
- `frontend/src/utils/statusHelpers.ts` - Workflow logic in backend
- `frontend/src/utils/navigationHelpers.ts` - Backend-driven navigation
- `frontend/src/utils/storageHelpers.ts` - No localStorage persistence

#### Legacy Components
- Any components with embedded business logic

### Files to MODIFY (20+ files)

#### Core App Files
1. **`frontend/src/main.tsx`**
   - Add QueryProvider
   - Remove localStorage initialization
   - Lines: 40 → 25 (-15)

2. **`frontend/src/App.tsx`**
   - Remove route guards
   - Simplify routing
   - Add backend navigation
   - Lines: 150 → 80 (-70)

#### Pages
3. **`frontend/src/pages/Dashboard.tsx`**
   - Remove workflow logic (getNextRoute, getButtonText, etc.)
   - Use useBackendNavigation hook
   - Render based on backend instructions
   - Lines: 200 → 80 (-120)

4. **`frontend/src/pages/ProfilePage.tsx`**
   - Remove fetch() calls
   - Use useUserProfile hook
   - Remove localStorage updates
   - Lines: 180 → 100 (-80)

5. **`frontend/src/pages/IntakePage.tsx`**
   - Remove topic tracking logic
   - Use WebSocket for streaming only
   - Backend controls completion
   - Lines: 250 → 120 (-130)

6. **`frontend/src/pages/AssessmentPage.tsx`**
   - Remove style recommendations hardcoded
   - Use useTherapyPlan hook
   - Backend provides style options
   - Lines: 220 → 100 (-120)

7. **`frontend/src/pages/SessionHistoryPage.tsx`**
   - Remove localStorage cache
   - Use useSessionHistory hook
   - Lines: 150 → 80 (-70)

8. **`frontend/src/pages/TherapySession.tsx`**
   - Streaming display only
   - Remove session state management
   - Lines: 300 → 150 (-150)

#### Components
9. **`frontend/src/components/Dashboard.tsx`** (if separate from page)
   - Remove workflow rendering logic
   - Lines: 180 → 70 (-110)

10. **`frontend/src/components/SessionHeader.tsx`**
    - Use server state only
    - Lines: 80 → 40 (-40)

11. **`frontend/src/components/MessageHistory.tsx`**
    - Remove localStorage cache
    - Lines: 120 → 80 (-40)

#### Contexts (Simplified)
12. **`frontend/src/contexts/AppContext.tsx`**
    - Keep only UI state (theme, sidebar)
    - Remove all data state
    - Lines: 300 → 50 (-250)

#### Services
13. **`frontend/src/services/websocketService.ts`**
    - Integrate with React Query
    - Remove localStorage updates
    - Lines: 200 → 150 (-50)

14. **`frontend/src/services/apiClient.ts`** (Already done in Phase 1)
    - Verify implementation
    - Lines: ~150

#### Hooks (New)
15. **`frontend/src/hooks/useUserProfile.ts`** (CREATE)
    - Lines: +60

16. **`frontend/src/hooks/useSessionHistory.ts`** (CREATE)
    - Lines: +50

17. **`frontend/src/hooks/useTherapyPlan.ts`** (CREATE)
    - Lines: +60

18. **`frontend/src/hooks/useWorkflowNavigation.ts`** (CREATE)
    - Lines: +40

19. **`frontend/src/hooks/useBackendNavigation.ts`** (CREATE)
    - Lines: +30

20. **`frontend/src/hooks/useWebSocket.ts`** (MODIFY)
    - Integrate with React Query
    - Lines: 100 → 80 (-20)

### Files to CREATE (10+ files)

#### Hooks
1. `frontend/src/hooks/useUserProfile.ts` - User data fetching
2. `frontend/src/hooks/useSessionHistory.ts` - Session data fetching
3. `frontend/src/hooks/useTherapyPlan.ts` - Therapy plan management
4. `frontend/src/hooks/useWorkflowNavigation.ts` - Workflow state
5. `frontend/src/hooks/useBackendNavigation.ts` - Auto navigation

#### Providers
6. `frontend/src/providers/QueryProvider.tsx` - React Query setup

#### Types (Minimal)
7. `frontend/src/types/ui.ts` - UI-only types

#### Tests
8. `frontend/src/hooks/__tests__/useUserProfile.test.ts`
9. `frontend/src/hooks/__tests__/useSessionHistory.test.ts`
10. `frontend/src/hooks/__tests__/useTherapyPlan.test.ts`
11. `frontend/src/hooks/__tests__/useWorkflowNavigation.test.ts`
12. `frontend/src/__tests__/integration/navigation.test.tsx`

#### Documentation
13. `docs/PHASE_2_MIGRATION_NOTES.md`
14. `docs/ADR_THIN_CLIENT.md`

---

## TESTING STRATEGY

### Unit Tests (Day 11)

**Hook Tests**:
```typescript
// frontend/src/hooks/__tests__/useUserProfile.test.ts
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useUserProfile } from '../useUserProfile';

describe('useUserProfile', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it('fetches user profile successfully', async () => {
    const wrapper = ({ children }) => (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );

    const { result } = renderHook(() => useUserProfile('test-user'), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(expect.objectContaining({
      userId: 'test-user',
      name: expect.any(String),
    }));
  });

  it('handles error state', async () => {
    // Mock API error
    const wrapper = ({ children }) => (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );

    const { result } = renderHook(() => useUserProfile('invalid'), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeDefined();
  });
});
```

**Component Tests**:
```typescript
// frontend/src/pages/__tests__/Dashboard.test.tsx
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import Dashboard from '../Dashboard';

describe('Dashboard', () => {
  it('renders backend navigation instructions', async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(['workflow', 'next-action', 'test-user', '/'], {
      action: 'navigate',
      route: '/intake',
      display: {
        title: 'Start Your Intake',
        description: 'Let\'s gather some information',
        primary_action: { label: 'Begin Intake', type: 'session_request' },
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Dashboard />
        </BrowserRouter>
      </QueryClientProvider>
    );

    expect(screen.getByText('Start Your Intake')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Begin Intake' })).toBeInTheDocument();
  });
});
```

### Integration Tests (Day 12)

**Full User Flow Test**:
```typescript
// frontend/src/__tests__/integration/userFlow.test.tsx
describe('New user flow', () => {
  it('completes full workflow from profile to therapy', async () => {
    const { user } = render(<App />);

    // 1. Fill profile
    await user.type(screen.getByLabelText('Name'), 'John Doe');
    await user.type(screen.getByLabelText('Age'), '35');
    await user.click(screen.getByRole('button', { name: 'Continue' }));

    // 2. Backend should navigate to intake
    await waitFor(() => {
      expect(screen.getByText(/Intake Session/)).toBeInTheDocument();
    });

    // 3. Complete intake
    await user.type(screen.getByPlaceholderText('Type your message'), 'I want help with anxiety');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    // 4. Wait for intake completion (mocked)
    await waitFor(() => {
      expect(screen.getByText(/Assessment/)).toBeInTheDocument();
    });

    // 5. Select therapy style
    await user.click(screen.getByText('Cognitive Behavioral Therapy'));

    // 6. Backend should navigate to therapy
    await waitFor(() => {
      expect(screen.getByText(/Therapy Session/)).toBeInTheDocument();
    });
  });
});
```

**WebSocket Integration Test**:
```typescript
// frontend/src/__tests__/integration/websocket.test.tsx
describe('WebSocket integration', () => {
  it('handles state change message and triggers navigation', async () => {
    const mockWS = new MockWebSocket();
    render(<App />);

    // Simulate state change from backend
    mockWS.sendMessage({
      type: 'state_change',
      data: {
        previous_state: 'INTAKE_IN_PROGRESS',
        new_state: 'INTAKE_COMPLETE',
        next_action: {
          type: 'navigate',
          route: '/assessment',
          message: 'Great! Let\'s move to assessment.',
        },
      },
    });

    // Should automatically navigate
    await waitFor(() => {
      expect(screen.getByText(/Assessment/)).toBeInTheDocument();
    });
  });
});
```

### Manual Testing Checklist (Day 12)

**Test Environment Setup**:
```bash
# Terminal 1: Start backend
cd /app
make docker-run

# Terminal 2: Start frontend
cd frontend
npm run dev

# Terminal 3: Monitor logs
docker-compose logs -f backend
```

**Test Cases**:

1. **New User Flow**
   - [ ] Open http://localhost:5173
   - [ ] Should auto-navigate to /profile
   - [ ] Fill profile form
   - [ ] Click "Continue"
   - [ ] Should auto-navigate to /intake
   - [ ] Complete intake conversation
   - [ ] Should auto-navigate to /assessment
   - [ ] Select therapy style
   - [ ] Should auto-navigate to /therapy
   - [ ] No manual navigation required

2. **Returning User Flow**
   - [ ] Open http://localhost:5173 with existing user ID
   - [ ] Should land on Dashboard
   - [ ] Dashboard shows "Continue Therapy" button
   - [ ] Click button
   - [ ] Should navigate to correct page based on status

3. **WebSocket Streaming**
   - [ ] Start therapy session
   - [ ] Type message and send
   - [ ] Should see streaming response character by character
   - [ ] No lag or stuttering
   - [ ] Typing indicator shows while LLM responds

4. **Error Handling**
   - [ ] Kill backend server
   - [ ] Try to send message
   - [ ] Should show error state
   - [ ] Restart backend
   - [ ] Should reconnect automatically

5. **State Persistence**
   - [ ] Complete intake
   - [ ] Refresh page
   - [ ] Should stay at same workflow state
   - [ ] No localStorage errors in console

6. **Navigation Guards Removed**
   - [ ] Manually navigate to /therapy before completing intake
   - [ ] Should either redirect or show appropriate message
   - [ ] Backend controls access, not frontend

### Test Coverage Goals

**Overall Target**: 80%+

**Per Category**:
- Hooks: 90%+
- Components: 75%+
- Services: 85%+
- Integration: 70%+

**Critical Paths**: 100%
- User profile creation/update
- Session creation/continuation
- WebSocket message handling
- Navigation flow

---

## RISK MITIGATION

### Risk 1: Breaking Existing Functionality

**Probability**: Medium
**Impact**: High

**Mitigation**:
1. **Incremental approach**: Migrate one page at a time
2. **Feature flags**: Keep old code temporarily with flag
3. **Parallel testing**: Test both old and new flows
4. **Rollback plan**: Git branches for easy revert

**Monitoring**:
```typescript
// Add temporary logging
useEffect(() => {
  console.log('[MIGRATION] Dashboard rendered with nextAction:', nextAction);
}, [nextAction]);
```

### Risk 2: Data Loss from localStorage Removal

**Probability**: Low
**Impact**: High

**Mitigation**:
1. **Migration script**: Convert localStorage to backend
2. **Backup**: Warn users to complete in-progress sessions
3. **Graceful degradation**: Handle missing data
4. **Schema version check**: Clear incompatible data

**Migration Script**:
```typescript
// Run once on app load during transition period
function migrateLocalStorageToBackend() {
  const userProfile = localStorage.getItem('user_profile');
  if (userProfile) {
    const user = JSON.parse(userProfile);
    // Send to backend
    api.post('/api/user/profile', user)
      .then(() => {
        localStorage.removeItem('user_profile');
        console.log('[MIGRATION] User profile migrated to backend');
      });
  }
}
```

### Risk 3: Backend Load Increase

**Probability**: Low
**Impact**: Medium

**Mitigation**:
1. **React Query caching**: Reduce redundant requests
2. **Backend caching**: Add Redis if needed
3. **Rate limiting**: Protect backend endpoints
4. **Load testing**: Test with concurrent users

**React Query Optimization**:
```typescript
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 min cache
      cacheTime: 1000 * 60 * 10, // 10 min keep in memory
      refetchOnWindowFocus: false, // Reduce refetches
    },
  },
});
```

### Risk 4: Type Drift Between Backend and Frontend

**Probability**: Low (if Phase 1 complete)
**Impact**: Medium

**Mitigation**:
1. **Automated type generation**: Part of build process
2. **CI/CD check**: Fail build if types out of sync
3. **Pre-commit hook**: Generate types before commit

**Build Integration**:
```json
{
  "scripts": {
    "prebuild": "npm run generate-types",
    "generate-types": "openapi-typescript http://localhost:8000/openapi.json -o src/types/api.ts"
  }
}
```

### Risk 5: WebSocket Message Handling Changes

**Probability**: Low
**Impact**: Medium

**Mitigation**:
1. **Protocol versioning**: Check version in messages
2. **Backward compatibility**: Handle old and new formats
3. **Comprehensive testing**: Test all message types

### Risk 6: Navigation Loops

**Probability**: Low
**Impact**: Medium

**Mitigation**:
1. **Navigation guards**: Prevent infinite loops
2. **Backend validation**: Ensure valid state transitions
3. **Logging**: Track navigation events

**Loop Prevention**:
```typescript
const lastNavigationRef = useRef<string>('');

useEffect(() => {
  if (nextAction?.route && nextAction.route !== location.pathname) {
    if (lastNavigationRef.current === nextAction.route) {
      console.error('[NAVIGATION] Loop detected:', nextAction.route);
      return;
    }
    lastNavigationRef.current = nextAction.route;
    navigate(nextAction.route);
  }
}, [nextAction, location.pathname, navigate]);
```

---

## ROLLBACK PLAN

### Emergency Rollback (Critical Issues)

**Trigger Conditions**:
- App completely broken
- Data loss occurring
- Security vulnerability introduced

**Steps**:
```bash
# 1. Revert to Phase 1 complete
git revert HEAD~N  # N = number of Phase 2 commits

# 2. Redeploy
cd frontend
npm install
npm run build

# 3. Clear user caches (if needed)
# Add banner: "Please refresh your browser"
```

### Partial Rollback (Specific Features)

**Scenario**: Backend-driven navigation causing issues, but React Query works fine

**Steps**:
1. **Disable backend navigation** temporarily:
```typescript
// In useBackendNavigation.ts
const ENABLE_BACKEND_NAVIGATION = false; // Feature flag

export function useBackendNavigation(userId: string) {
  if (!ENABLE_BACKEND_NAVIGATION) {
    return null; // Fallback to client-side routing
  }
  // ... rest of implementation
}
```

2. **Re-enable client-side routing** temporarily
3. **Fix backend issues**
4. **Re-enable backend navigation**

### Data Recovery

**If localStorage was cleared prematurely**:
```typescript
// Emergency recovery endpoint
// Backend provides user data based on session ID
async function recoverUserData(sessionId: string) {
  const response = await api.get(`/api/recovery/user?session_id=${sessionId}`);
  return response.data;
}
```

### Communication Plan

**During Rollback**:
1. **Status page**: Update immediately
2. **User notification**: Banner in app
3. **Team notification**: Slack/email
4. **Incident report**: Document what happened

---

## SUCCESS CRITERIA

### Quantitative Metrics

| Metric | Baseline (Before) | Target (After) | Measurement Method |
|--------|-------------------|----------------|-------------------|
| **Frontend LOC** | ~5,000 | ~1,500 (70% reduction) | `cloc frontend/src` |
| **TypeScript Files** | 56 | 25-30 (50% reduction) | `find frontend/src -name "*.ts*" | wc -l` |
| **localStorage Usage** | 8 keys | 2 keys (theme, UI prefs only) | Audit code |
| **API Call Sites** | 15+ | 1 (apiClient) | `grep -r "fetch(" src/` |
| **Type Definition Files** | 3 files | 1 file (generated) | Count files |
| **State Management Files** | 5 contexts | 1 context (UI only) | Count files |
| **Route Guard Components** | 3 | 0 | Find components |
| **Workflow Logic Functions** | 8+ | 0 | Grep for status switches |
| **Bundle Size** | ~800KB | ~400KB (50% reduction) | `npm run build` |
| **Test Coverage** | Unknown | 80%+ | `npm run test:coverage` |

### Qualitative Metrics

**Architecture**:
- [ ] Web frontend matches console UI pattern
- [ ] Backend controls all navigation
- [ ] Zero business logic in components
- [ ] Single source of truth (backend)
- [ ] Types auto-generated from backend

**Code Quality**:
- [ ] No TypeScript errors
- [ ] No ESLint warnings
- [ ] All tests passing
- [ ] No console errors/warnings

**User Experience**:
- [ ] Navigation feels seamless
- [ ] No perceivable latency increase
- [ ] Error states handled gracefully
- [ ] Loading states clear

**Developer Experience**:
- [ ] Easier to add new features
- [ ] Clearer code structure
- [ ] Better debugging
- [ ] Comprehensive documentation

### Performance Metrics

**Load Time**:
- First Contentful Paint: <1s
- Time to Interactive: <2s
- Bundle size: <500KB

**Runtime**:
- React Query cache hit rate: >90%
- WebSocket message latency: <100ms
- Navigation transition: <200ms

### Acceptance Tests

**Must Pass Before Phase 2 Complete**:

1. **Full User Flow** (10 min)
   - Complete profile → intake → assessment → therapy
   - No manual navigation required
   - Backend drives entire flow

2. **State Persistence** (5 min)
   - Complete intake
   - Refresh page
   - Resume at correct state

3. **WebSocket Streaming** (5 min)
   - Send message
   - Receive streaming response
   - No lag or errors

4. **Error Handling** (10 min)
   - Network failure
   - API error
   - WebSocket disconnect
   - All handled gracefully

5. **Type Safety** (2 min)
   - `npm run type-check` passes
   - No TypeScript errors

6. **Test Suite** (5 min)
   - `npm test` passes
   - Coverage >80%

---

## IMPLEMENTATION CHECKLIST

### Week 1: localStorage and Server State

- [ ] Day 1: React Query infrastructure
  - [ ] Install dependencies
  - [ ] Create QueryProvider
  - [ ] Integrate into app
  - [ ] DevTools working

- [ ] Day 2: Custom hooks
  - [ ] useUserProfile hook
  - [ ] useSessionHistory hook
  - [ ] useTherapyPlan hook
  - [ ] useWorkflowNavigation hook

- [ ] Day 3: Remove localStorage
  - [ ] Audit localStorage usage
  - [ ] Remove from AppContext
  - [ ] Keep only UI preferences
  - [ ] Test without localStorage

- [ ] Day 4: Update components
  - [ ] Dashboard refactored
  - [ ] ProfilePage refactored
  - [ ] SessionHistoryPage refactored
  - [ ] AssessmentPage refactored

- [ ] Day 5: Remove duplicate types
  - [ ] Delete old type files
  - [ ] Update imports
  - [ ] Use generated types
  - [ ] TypeScript compiles

### Week 2: Backend-Driven Navigation

- [ ] Day 6: Remove route guards
  - [ ] Delete guard components
  - [ ] Simplify App.tsx routing
  - [ ] Test all routes accessible

- [ ] Day 7: Backend navigation
  - [ ] Create useBackendNavigation hook
  - [ ] Integrate into pages
  - [ ] Test auto-navigation

- [ ] Day 8: Remove workflow logic
  - [ ] Remove status switches
  - [ ] Remove route helpers
  - [ ] Components render backend data

- [ ] Day 9: Simplify state
  - [ ] Refactor AppContext (UI only)
  - [ ] Remove AuthContext (if fake)
  - [ ] Update all consumers

- [ ] Day 10: WebSocket cleanup
  - [ ] Review websocketService
  - [ ] Integrate with React Query
  - [ ] Remove localStorage updates

### Week 3: Testing and Polish

- [ ] Day 11: Unit tests
  - [ ] Hook tests
  - [ ] Component tests
  - [ ] Update existing tests

- [ ] Day 12: Integration tests
  - [ ] Full user flow tests
  - [ ] WebSocket tests
  - [ ] Error handling tests
  - [ ] Manual testing

- [ ] Day 13: Code cleanup
  - [ ] Remove dead code
  - [ ] Delete unused files
  - [ ] Format and lint
  - [ ] Verify metrics

- [ ] Day 14: Documentation
  - [ ] Update README
  - [ ] Migration notes
  - [ ] Component docs
  - [ ] ADR created

- [ ] Day 15: Performance and review
  - [ ] Performance audit
  - [ ] Optimize React Query
  - [ ] Final review
  - [ ] Team demo

---

## DEPENDENCIES

### External Dependencies (Phase 1)

**Required Before Phase 2**:
1. API client layer exists
2. WebSocket protocol documented
3. `/api/workflow/next-action` endpoint working
4. Type generation from OpenAPI works

### Internal Dependencies (During Phase 2)

**Task Dependencies**:
- React Query infrastructure → All Day 2-5 tasks
- Custom hooks created → Component refactoring
- localStorage removed → State management simplification
- Route guards removed → Backend navigation implementation

**Critical Path**:
```
Day 1 (React Query) → Day 2 (Hooks) → Day 3 (Remove localStorage) → Day 4 (Update components)
                                    ↓
Day 6 (Remove guards) → Day 7 (Backend navigation) → Day 8 (Remove workflow logic)
                                    ↓
Day 11 (Tests) → Day 12 (Integration) → Day 13 (Cleanup) → Day 14 (Docs) → Day 15 (Review)
```

---

## TIMELINE SUMMARY

| Week | Focus | Key Deliverables | Risk Level |
|------|-------|------------------|------------|
| **Week 1** | localStorage removal & server state | React Query integrated, custom hooks, components using server state | Medium |
| **Week 2** | Backend-driven navigation | Route guards removed, navigation automated, workflow logic removed | Medium-High |
| **Week 3** | Testing & polish | All tests passing, documentation complete, performance optimized | Low |

**Total Duration**: 15 working days (3 weeks)
**Estimated Effort**: 1 developer full-time

---

## NEXT STEPS

1. **Review this plan** with team
2. **Verify Phase 1 completion** (all prerequisites met)
3. **Create branch**: `feature/phase-2-architecture-refactor`
4. **Start Day 1**: Install React Query and create infrastructure
5. **Daily standups**: Review progress and blockers
6. **Weekly demos**: Show progress to stakeholders

---

**Plan created by**: Claude Code
**Date**: 2025-12-02
**Based on**: [ARCHITECTURE_ASSESSMENT.md](ARCHITECTURE_ASSESSMENT.md) Section 7
**Next Phase**: Phase 3 - Type Safety & Authentication
