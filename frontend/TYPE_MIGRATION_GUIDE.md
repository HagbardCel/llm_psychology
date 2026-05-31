# Type Migration Guide: Manual → Generated Types

**Date**: 2025-12-03
**Status**: In Progress

---

## AUDIT RESULTS

### Summary Statistics

- **Total manual types**: 15
- **Mappable to generated**: 7 types (444 total usages)
- **Client-only types**: 8 types (100 total usages)
- **Unused types**: 0

---

## TYPE MAPPING

### Mappable Types (Backend API Models)

These types have equivalents in the generated `api.ts` and should be migrated:

| Manual Type | Generated Type | Usage Count | Files Affected |
|-------------|----------------|-------------|----------------|
| `User` | `UserProfile` | 69 | 15 |
| `UserStatus` | `UserStatus` | 106 | 13 |
| `Message` | `Message` | 25 | 7 |
| `Session` | `Session` | 130 | 18 |
| `TherapyPlan` | `TherapyPlan` | 10 | 4 |
| `WorkflowNextAction` | `WorkflowNextActionResponse` | 4 | 2 |
| `Topic` | `Topic` | 0 | 0 |

**Total**: 344 usages across 59 files

### Client-Only Types (Keep as Manual)

These types are UI-specific and have no backend equivalents:

| Type | Purpose | Usage Count |
|------|---------|-------------|
| `AgentType` | Frontend agent type enum | 38 |
| `TherapyStyle` | Frontend therapy style enum | 27 |
| `SessionStatus` | Frontend session status | 33 |
| `AppState` | React state management | 0 |
| `ApiResponse<T>` | Generic API wrapper | 0 |
| `LocalStorageData` | Browser storage schema | 0 |
| `UserPreferences` | UI preferences | 0 |
| `TherapyStyleInfo` | UI display data | 2 |

**Keep these**: They represent client-side concerns, not API models

---

## MIGRATION STRATEGY

### Phase 1: Compatibility Layer (Non-Breaking)

Create type aliases in `types/index.ts` that map to generated types:

```typescript
// Import generated types
import {
  UserProfile as GeneratedUserProfile,
  UserStatus as GeneratedUserStatus,
  Message as GeneratedMessage,
  Session as GeneratedSession,
  TherapyPlan as GeneratedTherapyPlan,
  WorkflowNextActionResponse,
  Topic as GeneratedTopic,
} from './generated/api';

// Re-export with familiar names (backward compatibility)
export type User = GeneratedUserProfile;
export type UserStatus = GeneratedUserStatus;
export type Message = GeneratedMessage;
export type Session = GeneratedSession;
export type TherapyPlan = GeneratedTherapyPlan;
export type WorkflowNextAction = WorkflowNextActionResponse;
export type Topic = GeneratedTopic;

// Keep client-only types as-is
export enum AgentType { /* ... */ }
export enum TherapyStyle { /* ... */ }
export enum SessionStatus { /* ... */ }
export interface AppState { /* ... */ }
export interface ApiResponse<T> { /* ... */ }
export interface LocalStorageData { /* ... */ }
export interface UserPreferences { /* ... */ }
export interface TherapyStyleInfo { /* ... */ }
```

**Benefits**:
- ✅ Zero breaking changes (existing imports still work)
- ✅ Types automatically sync with backend
- ✅ Can migrate gradually

### Phase 2: Field Name Alignment (Completed)

We removed quicktype’s camelCase transformation flags, so generated DTOs now keep the backend’s snake_case keys (`user_id`, `session_id`, `created_at`, …). Manual types should simply reference those keys. If you need camelCase in UI state, derive it explicitly inside the component/hook rather than altering the API DTO.

### Phase 3: Gradual Import Updates (Optional)

Once compatibility layer is in place, optionally update imports:

```typescript
// Before (still works)
import { User, UserStatus } from '@/types';

// After (explicit about generated types)
import { UserProfile, UserStatus } from '@/types/generated/api';
```

**Note**: This step is optional since compatibility layer works

---

## FIELD MAPPING

### User / UserProfile

| Manual Field | Generated Field | Notes |
|--------------|-----------------|-------|
| `id`, `userId` | `user_id` | Prefer keeping `user_id` everywhere. Derive camelCase only when needed for UI state. |
| `name` | `name` | Same |
| `email` | ❌ Not in backend | Keep client-only |
| `data_of_birth` | `data_of_birth` | ISO string; treat as `string \| null` |
| `profession` | `profession` | Optional string |
| `status` | `status` | Enum |
| `createdAt` / `updatedAt` | `created_at` / `updated_at` | Use snake_case + ISO string |

### Message

| Manual Field | Generated Field | Notes |
|--------------|-----------------|-------|
| `id`, `sessionId` | ❌ Client-only | Continue adding optional UI identifiers |
| `content`, `role` | same | Direct match |
| `timestamp` | `timestamp` | ISO string (no `Date` inference) |
| `agent` | `agent` | Optional string |

### Session

| Manual Field | Generated Field | Notes |
|--------------|-----------------|-------|
| `id`, `userId` | `session_id`, `user_id` | Keep DTO keys (`session_id`, `user_id`) |
| `transcript`, `topics` | same | Already aligned |
| `agentType`, `therapyStyle`, `status`, `startTime`, `endTime`, `metadata` | Client-only | Keep as optional UI extensions |
| `timestamp` | `timestamp` | ISO string |

### TherapyPlan

| Manual Field | Generated Field | Notes |
|--------------|-----------------|-------|
| `id`, `userId` | `plan_id`, `user_id` | Keep DTO keys |
| `therapyStyle` | `selected_therapy_style` | Use backend name or derive alias locally |
| `sessionCount` | Client-only | Keep optional UI field |
| Other plan fields | same | Already aligned (snake_case) |

---

## IMPLEMENTATION STEPS

### Step 1: Re-export DTOs + add UI extensions (✅)

File: `frontend/src/types/index.ts`

```typescript
// Import generated types
import type {
  UserProfile as GeneratedUserProfile,
  UserStatus as GeneratedUserStatus,
  Message as GeneratedMessage,
  Session as GeneratedSession,
  TherapyPlan as GeneratedTherapyPlan,
  Topic as GeneratedTopic,
  WorkflowNextActionResponse,
} from './generated/api';

// Re-export generated DTOs directly
export type User = GeneratedUserProfile;
export type UserStatus = GeneratedUserStatus;
export type Topic = GeneratedTopic;
export type WorkflowNextAction = WorkflowNextActionResponse;

// Extend DTOs with optional UI-only metadata
export interface Message extends GeneratedMessage {
  id?: string;
  sessionId?: string;
}

export interface Session extends GeneratedSession {
  agentType?: AgentType;
  therapyStyle?: TherapyStyle;
  status?: SessionStatus;
  startTime?: Date;
  endTime?: Date;
  metadata?: Record<string, any>;
}

export interface TherapyPlan extends GeneratedTherapyPlan {
  sessionCount?: number;
}

// Keep all client-only types
export enum AgentType { /* existing */ }
export enum TherapyStyle { /* existing */ }
export enum SessionStatus { /* existing */ }
export interface AppState { /* existing */ }
export interface ApiResponse<T> { /* existing */ }
export interface LocalStorageData { /* existing */ }
export interface UserPreferences { /* existing */ }
export interface TherapyStyleInfo { /* existing */ }
```

### Step 2: Update Call Sites

- Treat API data as snake_case. Example: `user.user_id`, not `user.userId`.
- When camelCase is needed for UI-only state, derive it inside the component/hook (`const userId = user.user_id`) rather than mutating the DTO.
- Update selectors, hooks, and React Query keys that previously referenced camelCase names.

### Step 3: Validate

Run `npm run type-check` (or `npm run dev`) to surface any remaining camelCase references. TypeScript will highlight places that still expect renamed fields.

---

## TESTING STRATEGY

### Unit Tests

Add focused tests that ensure UI-only extensions coexist with DTO keys:

```typescript
import type { Session } from '@/types';
import { AgentType } from '@/types';

it('supports UI metadata without redefining DTO fields', () => {
  const session: Session = {
    session_id: 'session-1',
    user_id: 'user-1',
    timestamp: new Date().toISOString(),
    transcript: [],
    topics: [],
  };

  session.agentType = AgentType.THERAPIST;
  expect(session.user_id).toBe('user-1');
});
```

### Integration Tests

Use existing React Query hooks / API clients directly with generated types and assert snake_case data is passed through unchanged:

```typescript
import type { UserProfile } from '@/types/generated/api';

it('passes backend payloads through untouched', async () => {
  const response: UserProfile = await api.user.createProfile({
    user_id: 'user-123',
    name: 'Test User'
  });

  expect(response.user_id).toBe('user-123');
});
```

---

## ROLLBACK PLAN

If issues arise:

1. **Keep old types temporarily**:
   ```typescript
   // Old types
   export interface UserOld { /* ... */ }

   // New types
   export type User = UserProfile;
   ```

2. **Use feature flag**:
   ```typescript
   const USE_GENERATED_TYPES = false;

   export type User = typeof USE_GENERATED_TYPES extends true
     ? UserProfile
     : UserOld;
   ```

3. **Revert imports**:
   ```bash
   git revert <migration-commit>
   ```

---

## BENEFITS

✅ **Single Source of Truth**: Backend models drive frontend types
✅ **Auto-sync**: Types update when backend changes
✅ **Type Safety**: Compile-time validation of API contracts
✅ **Less Code**: Remove ~130 lines of manual type definitions
✅ **No Breaking Changes**: Compatibility layer preserves existing code

---

## TIMELINE

- **Day 4**: Re-export DTOs + add UI extensions (non-breaking)
- **Day 5**: Update call sites to snake_case + run tests
- **Optional**: Gradually import directly from `generated/api`

---

## STATUS

- [x] Audit completed
- [x] Compatibility layer updated to snake_case DTOs
- [x] Call sites updated / type-check clean
- [ ] Tests passing
- [ ] Documentation updated
