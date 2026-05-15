---
owner: engineering
status: active
last_reviewed: 2026-02-14
review_cycle_days: 90
source_of_truth_for: Backend schema to frontend type generation pipeline and rules
---

# Type System Documentation

**Last Verified:** 2026-02-14

## Overview

The psychoanalyst application uses an **automated type generation system** that maintains type safety between the Python backend and TypeScript frontend. Backend Pydantic models are the single source of truth, with TypeScript types auto-generated via JSON Schema.

Canonical contract naming:
- Session model: `Session`
- Session identifier field: `session_id`
- Legacy `SessionBlock` / `session_block_id` names are deprecated and must not appear in generated API artifacts.

**Docker-only note:** run all commands in this guide via Docker targets/containers. Do not run Python or Node directly on the host.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    BACKEND (Source of Truth)                 │
│                                                              │
│  Pydantic Models (src/psychoanalyst_app/models/)                              │
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
│           FRONTEND TYPE EXTENSIONS (Manual Add-ons)          │
│                                                              │
│  frontend/src/types/index.ts                                │
│  ├─ Re-export generated DTOs directly (snake_case)         │
│  ├─ Add optional UI-only fields on top of DTOs             │
│  └─ Define client-only enums/interfaces                    │
└─────────────────────────────────────────────────────────────┘
                           ↓
                  [Frontend Components]
```

## Key Principles

### 1. Single Source of Truth

**Backend Pydantic models** are the authoritative definition for all data structures that cross the API boundary.

```python
# Backend: src/psychoanalyst_app/models/data_models.py
class UserProfile(BaseModel):
    """Represents a user's personal information."""
    user_id: str
    name: str
    data_of_birth: datetime | None = None
    status: UserStatus = UserStatus.PROFILE_ONLY
    created_at: datetime
    updated_at: datetime
```

This automatically generates:

```typescript
// Frontend: src/types/generated/api.ts (AUTO-GENERATED)
export interface UserProfile {
    user_id: string;
    name: string;
    data_of_birth?: string | null;  // ISO 8601 string
    profession?: string | null;
    status: UserStatus;
    created_at: string;
    updated_at: string;
}
```

### 2. Automatic Synchronization

Type generation happens automatically:

- **During development**: `make ui-web` (frontend container)
- **During build**: `docker compose run --rm frontend npm run build`
- **In CI/CD**: GitHub Actions workflow
- **On demand**: `docker compose run --rm -v "$PWD/schemas:/schemas" frontend npm run generate:ts`

### 3. Frontend Extensions (UI-only data)

`frontend/src/types/index.ts` re-exports the generated DTOs so the rest of the UI can continue to import `User`, `Session`, etc. Those aliases keep the backend’s snake_case keys and simply layer on optional client-only fields (e.g., `agentType`, derived timestamps, or view-model metadata). No renaming or conversion is needed anymore.

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
# src/psychoanalyst_app/models/data_models.py
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

3. **Frontend gets updated automatically** on next Docker-based `make ui-web` or `docker compose run --rm frontend npm run build`

4. **TypeScript will show errors** where the new field is missing - fix them!

### For Frontend Developers

#### Using Generated Types

```typescript
// Import from types/index.ts (snake_case DTO aliases)
import { User, UserStatus, Message } from '@/types';

// Use DTO keys directly
const user: User = {
  user_id: 'user-123',
  name: 'Test User',
  status: 'PROFILE_ONLY',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};
```

#### Working with API Responses

Use the generated DTOs directly—responses already arrive in snake_case with ISO strings:

```typescript
import type { Session } from '@/types/generated/api';

async function fetchSessions(userId: string): Promise<Session[]> {
  const response = await fetch(`/api/sessions?user_id=${userId}`);
  if (!response.ok) throw new Error('Failed to load sessions');
  return response.json() as Promise<Session[]>;
}
```

#### Handling Type Updates

When backend types change:

1. **Run type generation**:

```bash
docker compose run --rm -v "$PWD/schemas:/schemas" frontend npm run generate:types
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

### Field Name Conventions

We no longer rename API fields. JSON keys stay `snake_case` from backend → schema → generated TypeScript → frontend code. Examples:

| Backend (Python) | Generated TypeScript | Notes |
|------------------|----------------------|-------|
| `user_id` | `user_id` | Preserved |
| `session_id` | `session_id` | Preserved |
| `created_at` | `created_at` | Preserved |
| `updated_at` | `updated_at` | Preserved |

Client code should treat these as canonical wire keys; camelCase is reserved for UI-only state.

### Type Conversions

| Backend (Python) | Frontend (TypeScript) | Notes |
|------------------|------------------------|-------|
| `str` | `string` | ✓ Direct mapping |
| `int` | `number` | ✓ Direct mapping |
| `float` | `number` | ✓ Direct mapping |
| `bool` | `boolean` | ✓ Direct mapping |
| `datetime` | `string` | ISO 8601 string (no auto Date) |
| `Optional[T]` | `T \| null` or `T?` | ✓ Handled |
| `List[T]` | `T[]` | ✓ Array mapping |
| `Dict[str, Any]` | `Record<string, any>` | ✓ Object mapping |
| `Enum` | `type = "val1" \| "val2"` | ✓ Union type |

### Generated vs Manual Types

| Type Category | Location | Maintenance |
|---------------|----------|-------------|
| **API Models** (User, Session, etc.) | `generated/api.ts` | ✅ Auto-generated |
| **Frontend Re-exports + UI fields** | `types/index.ts` | 📝 Manual (adds optional props) |
| **UI Types** (AgentType, AppState) | `types/index.ts` | 📝 Manual |

## Commands Reference

### Backend

```bash
# Generate JSON schemas from Pydantic models
make generate-schemas

# Validate generated schemas
make validate-schemas

# Run schema generation tests
docker compose run --rm api pytest tests/unit/test_schema_generation.py -v
```

### Frontend

```bash
# Generate TypeScript types from schemas
docker compose run --rm -v "$PWD/schemas:/schemas" frontend npm run generate:types

# Run type generation only (no schema generation)
docker compose run --rm -v "$PWD/schemas:/schemas" frontend npm run generate:ts

# Type check without building
docker compose run --rm frontend npm run type-check

# Run type-safety tests
docker compose run --rm frontend npm test src/types/__tests__
```

### Full Pipeline

```bash
# Complete type generation pipeline
make generate-schemas
docker compose run --rm -v "$PWD/schemas:/schemas" frontend npm run generate:ts

# Or let the build do it automatically
docker compose run --rm frontend npm run build
```

## Testing

### Unit Tests

Add lightweight type-safety tests to ensure our UI extensions line up with the generated DTOs:

```typescript
// src/types/__tests__/type-safety.test.ts
import type { Session } from '../index';
import { AgentType } from '../index';

it('allows UI metadata on sessions without breaking DTO fields', () => {
  const session: Session = {
    session_id: 'session-123',
    user_id: 'user-123',
    timestamp: new Date().toISOString(),
    transcript: [],
    topics: [],
  };

  session.agentType = AgentType.INTAKE;
  expect(session.user_id).toBe('user-123');
});
```

### Integration Tests

Verify type compatibility:

```typescript
// src/types/__tests__/type-safety.test.ts
import type { UserProfile } from '../generated/api';

it('accepts backend JSON without conversion', () => {
  const apiResponse: UserProfile = {
    user_id: 'api-123',
    name: 'API User',
    status: 'THERAPY_IN_PROGRESS',
    data_of_birth: null,
    profession: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  expect(apiResponse.user_id).toBe('api-123');
});
```

## Troubleshooting

### Generated Types Not Found

**Problem**: `Cannot find module '@/types/generated/api'`

**Solution**:
```bash
docker compose run --rm -v "$PWD/schemas:/schemas" frontend npm run generate:types
```

### Type Mismatch Errors

**Problem**: TypeScript errors after backend model changes

**Solution**:
1. Regenerate types: `docker compose run --rm -v "$PWD/schemas:/schemas" frontend npm run generate:types`
2. Check what changed: `git diff src/types/generated/api.ts`
3. Update your code to match new types

### Field Name Mismatches

**Problem**: Backend uses `user_id` but a component still reads `userId`

**Solution**: Update the component to use the canonical snake_case key (or derive your own camelCase helper inside the component). No automatic renaming occurs, so the DTO surface stays aligned across backend/client/tests.

### Build Fails with Type Errors

**Problem**: `docker compose run --rm frontend npm run build` fails with type errors

**Solution**:
1. Run `docker compose run --rm frontend npm run type-check` to see all errors
2. Fix type mismatches
3. Ensure generated types are up to date
4. Check that backend schemas are valid

### Stale Generated Types

**Problem**: Generated types don't reflect latest backend changes

**Solution**:
```bash
# Force regeneration
docker compose run --rm -v "$PWD:/app" frontend sh -lc "rm -f src/types/generated/api.ts && npm run generate:types"
```

## Best Practices

### DO ✅

- **Define API models in backend Pydantic**
- **Use generated types for API data**
- **Add JSDoc comments to Pydantic models** (they appear in TypeScript)
- **Run type generation before committing**
- **Keep API DTOs snake_case in the UI; convert only when deriving UI-specific state**
- **Add lightweight type-safety tests for UI extensions**

### DON'T ❌

- **Don't manually edit generated types** (`generated/api.ts`)
- **Don't duplicate type definitions** between backend and frontend
- **Don't use `any` for API data**
- **Don't commit generated files** (they're in `.gitignore`)
- **Don't bypass type checking** with `as any`
- **Don't rename API fields in-flight unless you truly need a derived UI model**

### Recommended Workflow

1. **Backend change**: Modify Pydantic model
2. **Generate schemas**: `make generate-schemas`
3. **Frontend build**: `make ui-web` (auto-generates types in Docker)
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
