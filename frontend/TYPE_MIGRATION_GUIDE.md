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

### Phase 2: Field Name Adjustment

Handle field name mismatches (snake_case → camelCase):

**Issue**: Generated types have `userid` instead of `userId`

**Solution 1**: Type extension

```typescript
// Extend generated type with better field names
export interface User extends Omit<GeneratedUserProfile, 'userid'> {
  userId: string;
}
```

**Solution 2**: Utility function

```typescript
// Convert generated type to expected format
export function toUser(profile: GeneratedUserProfile): User {
  return {
    ...profile,
    userId: profile.userid,
    id: profile.userid,
  };
}
```

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

| Manual Field | Generated Field | Type | Notes |
|--------------|-----------------|------|-------|
| `id` | `userid` | string | **Mismatch** |
| `name` | `name` | string | ✓ Match |
| `email` | ❌ Not in backend | string? | **Client-only** |
| `birthdate` | `birthdate` | Date? | ✓ Match |
| `profession` | `profession` | string? | ✓ Match |
| `status` | `status` | UserStatus | ✓ Match |
| `createdAt` | `createdAt` | Date | ✓ Match |
| `lastActiveAt` | ❌ Not in backend | Date | **Client-only** |
| ❌ Not in manual | `updatedAt` | Date | **New field** |

**Action Required**:
- Map `userid` → `id` (compatibility layer)
- Handle `email` as client-only field
- Handle `lastActiveAt` as client-only field

### Message

| Manual Field | Generated Field | Type | Notes |
|--------------|-----------------|------|-------|
| `id` | ❌ Not in backend | string | **Client-only** |
| `content` | `content` | string | ✓ Match |
| `role` | `role` | string | ✓ Match |
| `timestamp` | `timestamp` | Date | ✓ Match |
| `sessionId` | ❌ Not in backend | string | **Client-only** |

**Action Required**:
- Extend generated type with `id` and `sessionId` for client use

### Session

| Manual Field | Generated Field | Type | Notes |
|--------------|-----------------|------|-------|
| `id` | `sessionid` | string | **Mismatch** |
| `userId` | `userid` | string | **Mismatch** |
| `agentType` | ❌ Not in backend | AgentType | **Client-only** |
| `therapyStyle` | ❌ Not in backend | TherapyStyle? | **Client-only** |
| `status` | ❌ Not in backend | SessionStatus | **Client-only** |
| `startTime` | ❌ Not in backend | Date | **Client-only** |
| `endTime` | ❌ Not in backend | Date? | **Client-only** |
| `transcript` | `transcript` | Message[] | ✓ Match |
| `topics` | `topics` | Topic[] | ✓ Match |
| `metadata` | ❌ Not in backend | object? | **Client-only** |
| ❌ Not in manual | `timestamp` | Date | **New field** |

**Action Required**:
- Extend generated Session with client-only fields
- Map `sessionid` → `id`, `userid` → `userId`

### TherapyPlan

| Manual Field | Generated Field | Type | Notes |
|--------------|-----------------|------|-------|
| `id` | ❌ Not in backend | string | Check `plan_id` |
| `userId` | ❌ Not in backend | string | Check `user_id` |
| `therapyStyle` | `selectedTherapyStyle` | string? | **Different name** |
| `goals` | ❌ Not in backend | string[] | **Client-only** |
| `sessionCount` | ❌ Not in backend | number | **Client-only** |
| `createdAt` | `createdAt` | Date | ✓ Match |
| `updatedAt` | `updatedAt` | Date | ✓ Match |
| ❌ Not in manual | `planDetails` | object | **New field** |
| ❌ Not in manual | `version` | number | **New field** |
| ❌ Not in manual | `sessionBriefing` | object? | **New field** |

**Action Required**:
- Map field names
- Extend with client-only fields

---

## IMPLEMENTATION STEPS

### Step 1: Create Compatibility Layer ✅

File: `frontend/src/types/index.ts`

```typescript
// Import generated types
import type {
  UserProfile,
  UserStatus as GeneratedUserStatus,
  Message as GeneratedMessage,
  Session as GeneratedSession,
  TherapyPlan as GeneratedTherapyPlan,
  Topic as GeneratedTopic,
  WorkflowNextActionResponse,
} from './generated/api';

// Re-export generated types with extensions
export interface User extends Omit<UserProfile, 'userid'> {
  id: string;  // Map from userid
  email?: string;  // Client-only
  lastActiveAt?: Date;  // Client-only
}

export type { GeneratedUserStatus as UserStatus };

export interface Message extends GeneratedMessage {
  id?: string;  // Client-only
  sessionId?: string;  // Client-only
}

export interface Session extends Omit<GeneratedSession, 'sessionid' | 'userid'> {
  id: string;  // Map from sessionid
  userId: string;  // Map from userid
  agentType?: AgentType;  // Client-only
  therapyStyle?: TherapyStyle;  // Client-only
  status?: SessionStatus;  // Client-only
  startTime?: Date;  // Client-only
  endTime?: Date;  // Client-only
  metadata?: Record<string, any>;  // Client-only
}

export interface TherapyPlan extends Omit<GeneratedTherapyPlan, 'planId' | 'userId'> {
  id: string;  // Map from planId
  userId: string;  // Map from userId
  therapyStyle?: string;  // From selectedTherapyStyle
  goals?: string[];  // Client-only
  sessionCount?: number;  // Client-only
}

export type { GeneratedTopic as Topic };
export type WorkflowNextAction = WorkflowNextActionResponse;

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

### Step 2: Add Type Converters

File: `frontend/src/types/converters.ts`

```typescript
import type { UserProfile } from './generated/api';
import type { User } from './index';

export function toUser(profile: UserProfile): User {
  return {
    ...profile,
    id: profile.userid,
  };
}

export function fromUser(user: User): UserProfile {
  const { id, email, lastActiveAt, ...rest } = user;
  return {
    ...rest,
    userid: id,
  };
}

// Similar converters for other types as needed
```

### Step 3: Test Compatibility

Run type check to ensure no breaks:

```bash
npm run type-check
```

### Step 4: Update API Client (if needed)

If API responses use different field names, add converters:

```typescript
async function getUserProfile(userId: string): Promise<User> {
  const profile = await api.get<UserProfile>(`/api/user/profile?user_id=${userId}`);
  return toUser(profile);
}
```

---

## TESTING STRATEGY

### Unit Tests

Test type converters:

```typescript
describe('Type Converters', () => {
  it('should convert UserProfile to User', () => {
    const profile: UserProfile = {
      userid: 'user-123',
      name: 'Test User',
      status: 'PROFILE_ONLY',
      createdAt: new Date(),
      updatedAt: new Date(),
    };

    const user = toUser(profile);
    expect(user.id).toBe('user-123');
    expect(user.name).toBe('Test User');
  });
});
```

### Integration Tests

Verify API responses work with new types:

```typescript
it('should fetch and convert user profile', async () => {
  const user = await getUserProfile('user-123');
  expect(user).toHaveProperty('id');
  expect(user).toHaveProperty('name');
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

- **Day 4**: Create compatibility layer (non-breaking)
- **Day 5**: Add type converters and test
- **Optional**: Gradually update imports to generated types

---

## STATUS

- [x] Audit completed
- [ ] Compatibility layer created
- [ ] Type converters added
- [ ] Tests passing
- [ ] Documentation updated

