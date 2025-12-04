# Type System Documentation

## Overview

The psychoanalyst application uses an **automated type generation system** that maintains type safety between the Python backend and TypeScript frontend. Backend Pydantic models are the single source of truth, with TypeScript types auto-generated via JSON Schema.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    BACKEND (Source of Truth)                 │
│                                                              │
│  Pydantic Models (src/models/)                              │
│  ├─ data_models.py      - Core domain models                │
│  ├─ api_models.py       - API request/response models       │
│  └─ orchestration/      - Workflow models                   │
│     └─ models.py                                            │
└─────────────────────────────────────────────────────────────┘
                           ↓
                  [scripts/generate_schemas.py]
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                    JSON SCHEMAS (Intermediate)               │
│                                                              │
│  schemas/*.json                                             │
│  ├─ UserProfile.json    - 20 schema files                  │
│  ├─ Message.json                                           │
│  ├─ Session.json                                           │
│  └─ index.json          - Schema index                     │
└─────────────────────────────────────────────────────────────┘
                           ↓
              [frontend/scripts/generate-types.js]
              [quicktype - TypeScript generation]
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                GENERATED TYPESCRIPT (Auto)                   │
│                                                              │
│  frontend/src/types/generated/api.ts                        │
│  └─ 20+ TypeScript interfaces/types (~438 lines)           │
└─────────────────────────────────────────────────────────────┘
                           ↓
                    [import & extend]
                           ↓
┌─────────────────────────────────────────────────────────────┐
│              COMPATIBILITY LAYER (Manual)                    │
│                                                              │
│  frontend/src/types/index.ts                                │
│  ├─ Re-export generated types with familiar names          │
│  ├─ Extend with client-only fields                         │
│  ├─ Map field names (userid → id)                          │
│  └─ Define UI-specific types                               │
└─────────────────────────────────────────────────────────────┘
                           ↓
                  [Frontend Components]
```

## Key Principles

### 1. Single Source of Truth

**Backend Pydantic models** are the authoritative definition for all data structures that cross the API boundary.

```python
# Backend: src/models/data_models.py
class UserProfile(BaseModel):
    """Represents a user's personal information."""
    user_id: str
    name: str
    birthdate: datetime | None = None
    status: UserStatus = UserStatus.PROFILE_ONLY
    created_at: datetime
    updated_at: datetime
```

This automatically generates:

```typescript
// Frontend: src/types/generated/api.ts (AUTO-GENERATED)
export interface UserProfile {
    userid: string;
    name: string;
    birthdate?: Date | null;
    status?: UserStatus;
    createdAt: Date;
    updatedAt: Date;
}
```

### 2. Automatic Synchronization

Type generation happens automatically:

- **During development**: `npm run dev` (pre-hook)
- **During build**: `npm run build` (pre-hook)
- **In CI/CD**: GitHub Actions workflow
- **On demand**: `npm run generate:types`

### 3. Backward Compatibility

The compatibility layer ensures existing code continues to work:

```typescript
// frontend/src/types/index.ts (Compatibility Layer)
import type { UserProfile as GeneratedUserProfile } from './generated/api';

export interface User extends Omit<GeneratedUserProfile, 'userid'> {
  id: string;              // Maps from userid
  email?: string;          // Client-only field
  lastActiveAt?: Date;     // Client-only field
}
```

### 4. Client-Only Types

UI-specific types remain manually defined:

```typescript
// These are NOT in the backend
export enum AgentType {
  INTAKE = 'INTAKE',
  PSYCHOANALYST = 'PSYCHOANALYST',
  // ...
}

export interface AppState {
  user: User | null;
  currentSession: Session | null;
  // ...
}
```

## Usage Guide

### For Backend Developers

#### Adding a New Model

1. **Define the Pydantic model**:

```python
# src/models/data_models.py
class NewModel(BaseModel):
    """Description of the model."""

    field_one: str = Field(..., description="Field description")
    field_two: int
    optional_field: str | None = None
```

2. **Export to schemas**:

```python
# scripts/generate_schemas.py
MODELS_TO_EXPORT: List[Type[BaseModel]] = [
    # ... existing models
    NewModel,  # Add here
]
```

3. **Generate schemas**:

```bash
make generate-schemas
```

4. **Verify**:

```bash
make validate-schemas
ls schemas/NewModel.json
```

The frontend will automatically pick up the new type on next build!

#### Modifying an Existing Model

1. **Update the Pydantic model**:

```python
class UserProfile(BaseModel):
    user_id: str
    name: str
    new_field: str  # Added field
    # ...
```

2. **Regenerate schemas**:

```bash
make generate-schemas
```

3. **Frontend gets updated automatically** on next `npm run dev` or `npm run build`

4. **TypeScript will show errors** where the new field is missing - fix them!

### For Frontend Developers

#### Using Generated Types

```typescript
// Import from types/index.ts (compatibility layer)
import { User, UserStatus, Message } from '@/types';

// Use just like before
const user: User = {
  id: 'user-123',
  name: 'Test User',
  status: 'PROFILE_ONLY',
  createdAt: new Date(),
  updatedAt: new Date(),
};
```

#### Working with API Responses

If backend field names differ, use converters:

```typescript
import { toUser, fromUser } from '@/types/converters';
import type { UserProfile } from '@/types/generated/api';

// Backend returns UserProfile with 'userid'
async function fetchUser(id: string): Promise<User> {
  const response = await fetch(`/api/users/${id}`);
  const profile: UserProfile = await response.json();

  // Convert to frontend User type
  return toUser(profile);
}
```

#### Handling Type Updates

When backend types change:

1. **Run type generation**:

```bash
cd frontend
npm run generate:types
```

2. **TypeScript will show errors** where types don't match

3. **Fix the errors** - your IDE will guide you!

4. **Commit the changes** (don't commit generated files)

#### Creating Client-Only Types

For UI-specific types, add them to `types/index.ts`:

```typescript
// frontend/src/types/index.ts

// Client-only type (not from backend)
export interface MyUIState {
  isModalOpen: boolean;
  selectedTab: number;
  // ...
}
```

## Type Mapping Reference

### Field Name Conversions

Backend snake_case → Frontend camelCase (automatic):

| Backend (Python) | Frontend (TypeScript) | Notes |
|------------------|------------------------|-------|
| `user_id` | `userid` | ⚠️ quicktype limitation |
| `created_at` | `createdAt` | ✓ Converted |
| `updated_at` | `updatedAt` | ✓ Converted |
| `session_id` | `sessionid` | ⚠️ quicktype limitation |

**Workaround for limitations**: Compatibility layer maps `userid` → `id`

### Type Conversions

| Backend (Python) | Frontend (TypeScript) | Notes |
|------------------|------------------------|-------|
| `str` | `string` | ✓ Direct mapping |
| `int` | `number` | ✓ Direct mapping |
| `float` | `number` | ✓ Direct mapping |
| `bool` | `boolean` | ✓ Direct mapping |
| `datetime` | `Date` | ✓ Serialized as ISO string |
| `Optional[T]` | `T \| null` or `T?` | ✓ Handled |
| `List[T]` | `T[]` | ✓ Array mapping |
| `Dict[str, Any]` | `Record<string, any>` | ✓ Object mapping |
| `Enum` | `type = "val1" \| "val2"` | ✓ Union type |

### Generated vs Manual Types

| Type Category | Location | Maintenance |
|---------------|----------|-------------|
| **API Models** (User, Session, etc.) | `generated/api.ts` | ✅ Auto-generated |
| **Compatibility Layer** | `types/index.ts` | 📝 Manual (extends generated) |
| **UI Types** (AgentType, AppState) | `types/index.ts` | 📝 Manual |
| **Type Converters** | `types/converters.ts` | 📝 Manual |

## Commands Reference

### Backend

```bash
# Generate JSON schemas from Pydantic models
make generate-schemas

# Validate generated schemas
make validate-schemas

# Run schema generation tests
pytest tests/unit/test_schema_generation.py -v
```

### Frontend

```bash
# Generate TypeScript types from schemas
npm run generate:types

# Run type generation only (no schema generation)
npm run generate:ts

# Type check without building
npm run type-check

# Run type converter tests
npm test src/types/__tests__
```

### Full Pipeline

```bash
# Complete type generation pipeline
make generate-schemas
cd frontend && npm run generate:ts

# Or let the build do it automatically
cd frontend && npm run build
```

## Testing

### Unit Tests

Test type converters:

```typescript
// src/types/__tests__/converters.test.ts
import { toUser, fromUser } from '../converters';

it('should convert UserProfile to User', () => {
  const profile: UserProfile = {
    userid: 'test-123',
    name: 'Test User',
    status: 'PROFILE_ONLY',
    createdAt: new Date(),
    updatedAt: new Date(),
  };

  const user = toUser(profile);
  expect(user.id).toBe('test-123');
});
```

### Integration Tests

Verify type compatibility:

```typescript
// src/types/__tests__/type-safety.test.ts
it('should maintain type safety with API responses', () => {
  const apiResponse = {
    userid: 'api-123',
    name: 'API User',
    status: 'THERAPY_IN_PROGRESS',
    createdAt: new Date(),
    updatedAt: new Date(),
  };

  const user: User = {
    ...apiResponse,
    id: apiResponse.userid,
  };

  expect(user.id).toBe('api-123');
});
```

## Troubleshooting

### Generated Types Not Found

**Problem**: `Cannot find module '@/types/generated/api'`

**Solution**:
```bash
cd frontend
npm run generate:types
```

### Type Mismatch Errors

**Problem**: TypeScript errors after backend model changes

**Solution**:
1. Regenerate types: `npm run generate:types`
2. Check what changed: `git diff src/types/generated/api.ts`
3. Update your code to match new types

### Field Name Mismatches

**Problem**: Backend uses `user_id` but frontend expects `id`

**Solution**: Use the compatibility layer or converters

```typescript
import { toUser } from '@/types/converters';
const user = toUser(backendProfile);
```

### Build Fails with Type Errors

**Problem**: `npm run build` fails with type errors

**Solution**:
1. Run `npm run type-check` to see all errors
2. Fix type mismatches
3. Ensure generated types are up to date
4. Check that backend schemas are valid

### Stale Generated Types

**Problem**: Generated types don't reflect latest backend changes

**Solution**:
```bash
# Force regeneration
cd frontend
rm src/types/generated/api.ts
npm run generate:types
```

## Best Practices

### DO ✅

- **Define API models in backend Pydantic**
- **Use generated types for API data**
- **Add JSDoc comments to Pydantic models** (they appear in TypeScript)
- **Run type generation before committing**
- **Use type converters for field name mapping**
- **Test type conversions in unit tests**

### DON'T ❌

- **Don't manually edit generated types** (`generated/api.ts`)
- **Don't duplicate type definitions** between backend and frontend
- **Don't use `any` for API data**
- **Don't commit generated files** (they're in `.gitignore`)
- **Don't bypass type checking** with `as any`

### Recommended Workflow

1. **Backend change**: Modify Pydantic model
2. **Generate schemas**: `make generate-schemas`
3. **Frontend build**: `npm run dev` (auto-generates types)
4. **Fix type errors**: Update frontend code as needed
5. **Test**: Run tests to verify
6. **Commit**: Commit source files (not generated)

## CI/CD Integration

### GitHub Actions Workflow

`.github/workflows/type-safety.yml` validates types:

1. **Backend Job**: Generate and validate schemas
2. **Frontend Job**: Generate TypeScript types and build
3. **Consistency Job**: Run type validation tests

### Pre-commit Hooks

Install hooks for automatic validation:

```bash
make install-hooks
```

This runs:
- Schema generation
- Type generation
- Type checking
- Tests

## Migration Guide

For migrating existing manual types to generated types, see:
- [TYPE_MIGRATION_GUIDE.md](../frontend/TYPE_MIGRATION_GUIDE.md)

## Additional Resources

- [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/)
- [quicktype Documentation](https://quicktype.io/)
- [JSON Schema Reference](https://json-schema.org/)
- [TypeScript Handbook](https://www.typescriptlang.org/docs/handbook/intro.html)

## Support

For issues or questions:
1. Check this documentation
2. Check [TYPE_MIGRATION_GUIDE.md](../frontend/TYPE_MIGRATION_GUIDE.md)
3. Check [PHASE_3_IMPLEMENTATION_STATUS.md](../PHASE_3_IMPLEMENTATION_STATUS.md)
4. Review type generation tests
5. Create an issue with `type-system` label
