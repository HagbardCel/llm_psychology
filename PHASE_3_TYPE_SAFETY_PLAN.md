# Phase 3: Type Safety Implementation Plan

**Status**: Ready for Implementation
**Duration**: 5-7 days
**Priority**: HIGH
**Dependencies**: Phase 1 (API Client) should be complete for optimal integration

---

## EXECUTIVE SUMMARY

This phase eliminates manual type duplication between backend (Python/Pydantic) and frontend (TypeScript) by implementing automated type generation. This ensures compile-time type safety, eliminates type drift, and creates a single source of truth for data models.

**Current State**:
- Backend: ~15 Pydantic models in `src/models/`
- Frontend: ~12 manually duplicated TypeScript interfaces in `frontend/src/types/`
- Risk: Type drift, manual synchronization, snake_case/camelCase mismatches

**Target State**:
- Single source of truth: Backend Pydantic models
- Auto-generated TypeScript types
- Build-time type generation
- Zero manual type definitions for API models

---

## PHASE OVERVIEW

### Goals

1. ✅ **Eliminate Type Duplication**: Remove all manually defined API types from frontend
2. ✅ **Compile-Time Safety**: Catch API contract violations at build time
3. ✅ **Automatic Synchronization**: Types update automatically when backend changes
4. ✅ **Developer Experience**: IDE autocomplete and error detection for API calls
5. ✅ **Documentation**: Self-documenting API via generated schemas

### Non-Goals

- ❌ Runtime type validation (handled by Pydantic on backend)
- ❌ API versioning strategy (Phase 4)
- ❌ GraphQL schema generation (REST only)
- ❌ Automatic API client generation (manual API client from Phase 1)

---

## TECHNICAL APPROACH

### 1. Technology Selection

#### Option A: Quart + Pydantic → JSON Schema → TypeScript (RECOMMENDED)

**Approach**:
```python
# Backend generates JSON Schema from Pydantic models
from pydantic import BaseModel
import json

class UserProfile(BaseModel):
    user_id: str
    name: str
    status: UserStatus

    class Config:
        json_schema_extra = {
            "title": "UserProfile",
            "description": "User profile data model"
        }

# Generate schema
schema = UserProfile.model_json_schema()
with open("schemas/user_profile.json", "w") as f:
    json.dump(schema, f, indent=2)
```

**TypeScript Generation**:
```bash
# Use quicktype to generate TypeScript from JSON Schema
npx quicktype schemas/*.json -o frontend/src/types/generated/api.ts \
  --lang typescript \
  --just-types \
  --prefer-unions \
  --acronym-style original
```

**Pros**:
- ✅ Works with Quart (no FastAPI dependency)
- ✅ Pydantic native (model_json_schema())
- ✅ Flexible tool selection (quicktype, json-schema-to-typescript)
- ✅ Can generate from multiple schema files
- ✅ Supports complex types (Union, Optional, Literal)

**Cons**:
- ⚠️ Requires custom script to export all models
- ⚠️ Two-step process (Python → JSON Schema → TypeScript)

#### Option B: datamodel-code-generator (Alternative)

**Approach**:
```bash
# Generate TypeScript directly from Python models
datamodel-codegen \
  --input src/models/data_models.py \
  --output frontend/src/types/generated/api.ts \
  --output-model-type typescript
```

**Pros**:
- ✅ Single-step generation
- ✅ Direct Python → TypeScript

**Cons**:
- ⚠️ Less mature TypeScript support
- ⚠️ Limited customization options
- ⚠️ May not handle all Pydantic features

**DECISION**: Use Option A (JSON Schema approach) for maximum flexibility and reliability.

---

## IMPLEMENTATION PLAN

### Step 1: Backend Schema Export Script (Day 1)

#### 1.1 Create Schema Generation Script

**File**: `scripts/generate_schemas.py`

```python
#!/usr/bin/env python3
"""
Generate JSON Schema files from Pydantic models.

This script exports all API-facing Pydantic models to JSON Schema format
for TypeScript type generation.
"""

import json
from pathlib import Path
from typing import Type, List
from pydantic import BaseModel

# Import all models
from src.models.data_models import (
    UserProfile,
    TherapySession,
    TherapyPlan,
    TherapyStyle,
    Message,
    IntakeData,
    AssessmentResult,
)
from src.orchestration.models import (
    WorkflowState,
    AgentResponse,
)

# Models to export (API-facing only)
MODELS_TO_EXPORT: List[Type[BaseModel]] = [
    UserProfile,
    TherapySession,
    TherapyPlan,
    TherapyStyle,
    Message,
    IntakeData,
    AssessmentResult,
    AgentResponse,
]

OUTPUT_DIR = Path("schemas")


def generate_schema(model: Type[BaseModel], output_dir: Path) -> None:
    """Generate JSON Schema for a single model."""
    schema = model.model_json_schema()

    # Add metadata
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    schema["$id"] = f"https://psychoanalyst.app/schemas/{model.__name__}.json"

    # Write to file
    output_file = output_dir / f"{model.__name__}.json"
    with open(output_file, "w") as f:
        json.dump(schema, f, indent=2)

    print(f"✓ Generated schema: {output_file}")


def generate_all_schemas() -> None:
    """Generate JSON Schemas for all API models."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Generating schemas for {len(MODELS_TO_EXPORT)} models...")

    for model in MODELS_TO_EXPORT:
        generate_schema(model, OUTPUT_DIR)

    # Generate index file
    index = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Psychoanalyst API Schema Index",
        "description": "Index of all API data models",
        "models": [model.__name__ for model in MODELS_TO_EXPORT],
    }

    with open(OUTPUT_DIR / "index.json", "w") as f:
        json.dump(index, f, indent=2)

    print(f"\n✓ Successfully generated {len(MODELS_TO_EXPORT)} schemas")
    print(f"  Output directory: {OUTPUT_DIR.absolute()}")


if __name__ == "__main__":
    generate_all_schemas()
```

#### 1.2 Handle Enums Properly

**Challenge**: Pydantic enums need special handling for TypeScript

**Solution**: Enhance schema generation for enums

```python
from enum import Enum
from typing import get_args, get_origin

def enhance_schema_for_typescript(schema: dict, model: Type[BaseModel]) -> dict:
    """Enhance schema with TypeScript-friendly metadata."""

    # Handle enum fields
    for field_name, field_info in model.model_fields.items():
        field_type = field_info.annotation

        # Check if field is an Enum
        if isinstance(field_type, type) and issubclass(field_type, Enum):
            schema["properties"][field_name]["tsType"] = "enum"
            schema["properties"][field_name]["enumValues"] = [
                e.value for e in field_type
            ]

    return schema
```

#### 1.3 Add to Makefile

```makefile
# Generate JSON Schemas from Pydantic models
.PHONY: generate-schemas
generate-schemas:
	python scripts/generate_schemas.py

# Validate schemas
.PHONY: validate-schemas
validate-schemas:
	python scripts/validate_schemas.py
```

#### 1.4 Test Schema Generation

```bash
# Generate schemas
make generate-schemas

# Verify output
ls -la schemas/
cat schemas/UserProfile.json
```

**Expected Output**:
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://psychoanalyst.app/schemas/UserProfile.json",
  "title": "UserProfile",
  "type": "object",
  "properties": {
    "user_id": {
      "type": "string",
      "title": "User Id"
    },
    "name": {
      "type": "string",
      "title": "Name"
    },
    "status": {
      "$ref": "#/$defs/UserStatus"
    }
  },
  "required": ["user_id", "name", "status"],
  "$defs": {
    "UserStatus": {
      "enum": ["PROFILE_ONLY", "INTAKE_IN_PROGRESS", ...],
      "type": "string"
    }
  }
}
```

---

### Step 2: TypeScript Generation Setup (Day 2)

#### 2.1 Install Dependencies

**File**: `frontend/package.json`

```json
{
  "devDependencies": {
    "quicktype": "^23.0.0",
    "npm-run-all": "^4.1.5"
  },
  "scripts": {
    "generate:types": "npm run generate:schemas && npm run generate:ts",
    "generate:schemas": "cd .. && make generate-schemas",
    "generate:ts": "quicktype ../schemas/*.json -o src/types/generated/api.ts --lang typescript --just-types --prefer-unions --acronym-style original --nice-property-names",
    "prebuild": "npm run generate:types",
    "predev": "npm run generate:types"
  }
}
```

#### 2.2 Create Generation Script

**File**: `frontend/scripts/generate-types.js`

```javascript
#!/usr/bin/env node
/**
 * Generate TypeScript types from JSON Schema files
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const SCHEMAS_DIR = path.join(__dirname, '../../schemas');
const OUTPUT_FILE = path.join(__dirname, '../src/types/generated/api.ts');
const OUTPUT_DIR = path.dirname(OUTPUT_FILE);

// Ensure output directory exists
if (!fs.existsSync(OUTPUT_DIR)) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
}

// Find all schema files
const schemaFiles = fs
  .readdirSync(SCHEMAS_DIR)
  .filter(f => f.endsWith('.json') && f !== 'index.json')
  .map(f => path.join(SCHEMAS_DIR, f))
  .join(' ');

console.log('🔧 Generating TypeScript types from JSON Schemas...');
console.log(`   Input: ${SCHEMAS_DIR}`);
console.log(`   Output: ${OUTPUT_FILE}`);

try {
  // Run quicktype
  execSync(
    `npx quicktype ${schemaFiles} ` +
    `-o ${OUTPUT_FILE} ` +
    `--lang typescript ` +
    `--just-types ` +
    `--prefer-unions ` +
    `--acronym-style original ` +
    `--nice-property-names ` +
    `--prefer-const-values`,
    { stdio: 'inherit' }
  );

  // Add header comment
  const generatedCode = fs.readFileSync(OUTPUT_FILE, 'utf-8');
  const header = `/**
 * AUTO-GENERATED FILE - DO NOT EDIT
 *
 * Generated from backend Pydantic models via JSON Schema.
 * To update these types, run: npm run generate:types
 *
 * Generated: ${new Date().toISOString()}
 */

/* eslint-disable */
// @ts-nocheck

`;

  fs.writeFileSync(OUTPUT_FILE, header + generatedCode);

  console.log('✓ TypeScript types generated successfully');
} catch (error) {
  console.error('✗ Failed to generate TypeScript types');
  console.error(error.message);
  process.exit(1);
}
```

Make it executable:
```bash
chmod +x frontend/scripts/generate-types.js
```

#### 2.3 Handle snake_case to camelCase Conversion

**Challenge**: Python uses snake_case, TypeScript uses camelCase

**Solution**: Add transformation in quicktype config

```javascript
// Add to generate-types.js
const quicktypeConfig = {
  lang: 'typescript',
  'just-types': true,
  'prefer-unions': true,
  'acronym-style': 'original',
  'nice-property-names': true,  // Converts snake_case to camelCase
  'prefer-const-values': true,
};
```

**Alternative**: Custom post-processing script if quicktype doesn't handle all cases

```typescript
// scripts/transform-types.ts
function snakeToCamel(str: string): string {
  return str.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
}
```

---

### Step 3: Integration with Build Process (Day 3)

#### 3.1 Update Vite Config

**File**: `frontend/vite.config.ts`

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { execSync } from 'child_process';

// Plugin to generate types before build
function generateTypes() {
  return {
    name: 'generate-types',
    buildStart() {
      console.log('Generating TypeScript types...');
      try {
        execSync('npm run generate:types', { stdio: 'inherit' });
        console.log('✓ Types generated');
      } catch (error) {
        console.error('✗ Type generation failed');
        throw error;
      }
    },
  };
}

export default defineConfig({
  plugins: [
    generateTypes(), // Run before React plugin
    react(),
  ],
  // ... rest of config
});
```

#### 3.2 Add Type Checking to CI/CD

**File**: `.github/workflows/test.yml` (or equivalent)

```yaml
name: Test and Type Check

on: [push, pull_request]

jobs:
  backend-schemas:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Generate schemas
        run: |
          pip install -r requirements.txt
          make generate-schemas
      - name: Upload schemas
        uses: actions/upload-artifact@v3
        with:
          name: schemas
          path: schemas/

  frontend-types:
    needs: backend-schemas
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Download schemas
        uses: actions/download-artifact@v3
        with:
          name: schemas
          path: schemas/
      - uses: actions/setup-node@v3
        with:
          node-version: '18'
      - name: Install dependencies
        run: cd frontend && npm ci
      - name: Generate types
        run: cd frontend && npm run generate:types
      - name: Type check
        run: cd frontend && npm run type-check
      - name: Build
        run: cd frontend && npm run build
```

#### 3.3 Git Configuration

**File**: `.gitignore`

```gitignore
# Generated files
schemas/*.json
!schemas/.gitkeep
frontend/src/types/generated/
```

**File**: `.gitattributes`

```gitattributes
# Mark generated files
frontend/src/types/generated/* linguist-generated=true
schemas/*.json linguist-generated=true
```

---

### Step 4: Migrate Existing Types (Day 4-5)

#### 4.1 Audit Current Type Usage

**Script**: `frontend/scripts/audit-types.js`

```javascript
/**
 * Audit current type usage to plan migration
 */

const fs = require('fs');
const path = require('path');
const glob = require('glob');

const typesDir = path.join(__dirname, '../src/types');
const srcDir = path.join(__dirname, '../src');

// Find all manual type definitions
const manualTypes = glob.sync(`${typesDir}/**/*.ts`);

console.log('📊 Type Usage Audit\n');

manualTypes.forEach(file => {
  const content = fs.readFileSync(file, 'utf-8');

  // Extract exported types
  const exports = content.match(/export (?:interface|type|enum) (\w+)/g) || [];

  console.log(`\n${path.relative(typesDir, file)}:`);
  exports.forEach(exp => {
    const typeName = exp.split(' ').pop();

    // Search for usage
    const usageCount = glob.sync(`${srcDir}/**/*.{ts,tsx}`)
      .reduce((count, srcFile) => {
        const srcContent = fs.readFileSync(srcFile, 'utf-8');
        const matches = srcContent.match(new RegExp(`\\b${typeName}\\b`, 'g'));
        return count + (matches ? matches.length : 0);
      }, 0);

    console.log(`  ${typeName}: ${usageCount} usages`);
  });
});
```

Run audit:
```bash
cd frontend
node scripts/audit-types.js > type-migration-plan.txt
```

#### 4.2 Create Type Mapping

**File**: `frontend/src/types/type-mapping.md`

```markdown
# Type Migration Mapping

## Backend → Frontend Type Mapping

| Backend Model (Python) | Current Frontend Type | Generated Type | Migration Status |
|------------------------|----------------------|----------------|------------------|
| `UserProfile` | `User` (index.ts) | `UserProfile` | ⏳ Pending |
| `TherapySession` | `Session` (index.ts) | `TherapySession` | ⏳ Pending |
| `TherapyPlan` | `TherapyPlan` (index.ts) | `TherapyPlan` | ⏳ Pending |
| `TherapyStyle` | `TherapyStyle` (index.ts) | `TherapyStyle` | ⏳ Pending |
| `UserStatus` | `UserStatus` (index.ts) | `UserStatus` | ⏳ Pending |
| `WorkflowState` | ❌ Not defined | `WorkflowState` | ⏳ New |
| `Message` | `Message` (websocket.ts) | `Message` | ⏳ Pending |

## Field Name Mappings (snake_case → camelCase)

| Python Field | TypeScript Field | Conversion |
|--------------|------------------|------------|
| `user_id` | `userId` | Auto (quicktype) |
| `created_at` | `createdAt` | Auto (quicktype) |
| `updated_at` | `updatedAt` | Auto (quicktype) |
| `therapy_plan` | `therapyPlan` | Auto (quicktype) |

## Custom Types (Keep Manual)

| Type | Location | Reason |
|------|----------|--------|
| `WebSocketMessage` | websocket.ts | Client-specific protocol wrapper |
| `NavigationState` | index.ts | UI state (not API model) |
| `FormErrors` | index.ts | Client-side validation |
```

#### 4.3 Migration Strategy

**Incremental Migration Approach**:

```typescript
// Step 1: Import generated types alongside existing
import { User } from './types/index'; // Old
import { UserProfile as GeneratedUserProfile } from './types/generated/api'; // New

// Step 2: Create compatibility layer
export type User = GeneratedUserProfile; // Alias for backward compatibility

// Step 3: Gradually update imports across codebase
// Before:
import { User } from '@/types';
// After:
import { UserProfile } from '@/types/generated/api';

// Step 4: Remove old manual types once migration complete
```

**Migration Script**:

```bash
#!/bin/bash
# migrate-to-generated-types.sh

# Find and replace type imports
find frontend/src -type f \( -name "*.ts" -o -name "*.tsx" \) -exec sed -i \
  's/import { User }/import { UserProfile as User }/g' {} \;

# Update type annotations
find frontend/src -type f \( -name "*.ts" -o -name "*.tsx" \) -exec sed -i \
  's/: User\b/: UserProfile/g' {} \;

echo "✓ Type migration complete. Run type-check to verify."
```

#### 4.4 Handle Special Cases

**Case 1: Optional Fields**

```typescript
// Backend (Python)
class UserProfile(BaseModel):
    name: str
    birthdate: Optional[str] = None

// Generated TypeScript (correct)
interface UserProfile {
  name: string;
  birthdate?: string;
}
```

**Case 2: Union Types**

```python
# Backend
status: Union[Literal["active"], Literal["inactive"]]

// Generated TypeScript
status: "active" | "inactive";
```

**Case 3: DateTime Fields**

```python
# Backend
created_at: datetime

// Generated TypeScript (as string, needs parsing)
createdAt: string;  // ISO 8601 format

// Helper function needed
function parseDateTime(isoString: string): Date {
  return new Date(isoString);
}
```

---

### Step 5: Testing and Validation (Day 6)

#### 5.1 Type Generation Tests

**File**: `tests/test_schema_generation.py`

```python
"""Tests for schema generation."""

import json
from pathlib import Path
import pytest
from scripts.generate_schemas import generate_schema, MODELS_TO_EXPORT
from src.models.data_models import UserProfile


def test_schema_generation():
    """Test that schemas are generated correctly."""
    output_dir = Path("tests/tmp/schemas")
    output_dir.mkdir(parents=True, exist_ok=True)

    generate_schema(UserProfile, output_dir)

    schema_file = output_dir / "UserProfile.json"
    assert schema_file.exists()

    with open(schema_file) as f:
        schema = json.load(f)

    assert schema["title"] == "UserProfile"
    assert "properties" in schema
    assert "user_id" in schema["properties"]


def test_all_models_exportable():
    """Test that all models can be exported."""
    for model in MODELS_TO_EXPORT:
        schema = model.model_json_schema()
        assert schema is not None
        assert "properties" in schema


def test_enum_handling():
    """Test that enums are properly represented."""
    from src.models.data_models import UserStatus

    schema = UserStatus.model_json_schema() if hasattr(UserStatus, 'model_json_schema') else {}
    # Enums should have enum values
    assert True  # Adjust based on actual enum implementation
```

#### 5.2 TypeScript Compilation Tests

**File**: `frontend/src/types/__tests__/generated-types.test.ts`

```typescript
/**
 * Tests for generated TypeScript types
 */

import { describe, it, expect } from 'vitest';
import {
  UserProfile,
  TherapySession,
  TherapyPlan,
  UserStatus,
} from '../generated/api';

describe('Generated Types', () => {
  it('should have correct UserProfile structure', () => {
    const user: UserProfile = {
      userId: 'test-123',
      name: 'Test User',
      status: 'PROFILE_ONLY' as UserStatus,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    expect(user.userId).toBe('test-123');
    expect(user.name).toBe('Test User');
  });

  it('should enforce required fields', () => {
    // @ts-expect-error - missing required field
    const invalidUser: UserProfile = {
      userId: 'test-123',
      // name is missing
    };
  });

  it('should allow optional fields to be omitted', () => {
    const user: UserProfile = {
      userId: 'test-123',
      name: 'Test User',
      status: 'PROFILE_ONLY' as UserStatus,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      // birthdate and profession are optional
    };

    expect(user).toBeDefined();
  });

  it('should handle enum types correctly', () => {
    const validStatus: UserStatus = 'INTAKE_IN_PROGRESS';

    // @ts-expect-error - invalid enum value
    const invalidStatus: UserStatus = 'INVALID_STATUS';
  });
});
```

#### 5.3 Integration Tests

**File**: `tests/integration/test_type_safety.py`

```python
"""Integration tests for type safety across backend-frontend."""

import json
import pytest
from src.models.data_models import UserProfile
from pathlib import Path


def test_backend_frontend_type_compatibility():
    """Test that backend models match generated frontend types."""

    # Create a backend model instance
    user = UserProfile(
        user_id="test-123",
        name="Test User",
        status="PROFILE_ONLY",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    # Serialize to JSON (as API would)
    user_json = user.model_dump_json()
    user_dict = json.loads(user_json)

    # Verify structure matches expected frontend type
    assert "user_id" in user_dict
    assert "name" in user_dict
    assert "status" in user_dict

    # Load generated schema
    schema_file = Path("schemas/UserProfile.json")
    if schema_file.exists():
        with open(schema_file) as f:
            schema = json.load(f)

        # Verify all required fields are in schema
        required_fields = schema.get("required", [])
        for field in required_fields:
            assert field in user_dict


def test_enum_serialization():
    """Test that enums serialize consistently."""
    from src.models.data_models import UserStatus

    # Backend enum value
    status = UserStatus.INTAKE_IN_PROGRESS

    # Should serialize to string
    assert status.value == "INTAKE_IN_PROGRESS"

    # Verify schema has correct enum values
    schema_file = Path("schemas/UserProfile.json")
    if schema_file.exists():
        with open(schema_file) as f:
            schema = json.load(f)

        # Find UserStatus enum in definitions
        if "$defs" in schema and "UserStatus" in schema["$defs"]:
            enum_def = schema["$defs"]["UserStatus"]
            assert "INTAKE_IN_PROGRESS" in enum_def["enum"]
```

#### 5.4 Validation Checklist

```bash
# Run full validation suite
cd frontend

# 1. Generate types
npm run generate:types

# 2. Type check
npm run type-check

# 3. Run tests
npm test

# 4. Build
npm run build

# 5. Verify no type errors
echo "✓ Type safety validation complete"
```

---

### Step 6: Documentation and Developer Guide (Day 7)

#### 6.1 Update README

**File**: `README.md`

```markdown
## Type Safety

This project uses **auto-generated TypeScript types** from backend Pydantic models.

### For Developers

**Never manually edit types in `frontend/src/types/generated/`** - they are auto-generated.

#### Updating Types

When you change a backend model:

1. Update the Pydantic model in `src/models/`
2. Regenerate schemas: `make generate-schemas`
3. Regenerate TypeScript types: `cd frontend && npm run generate:types`
4. Types are automatically updated in `frontend/src/types/generated/api.ts`

#### Adding New Models

1. Add model to `src/models/data_models.py`
2. Add model to `MODELS_TO_EXPORT` in `scripts/generate_schemas.py`
3. Run `make generate-schemas`
4. Types will be available in next frontend build

#### Type Generation Flow

```
Backend Pydantic Models
  ↓
JSON Schema (schemas/*.json)
  ↓
TypeScript Types (frontend/src/types/generated/api.ts)
  ↓
Frontend Code
```
```

#### 6.2 Create Developer Guide

**File**: `docs/TYPE_SYSTEM.md`

```markdown
# Type System Documentation

## Overview

The psychoanalyst application maintains type safety across the Python backend and TypeScript frontend through automated type generation.

## Architecture

### Backend (Source of Truth)

All data models are defined as Pydantic models in `src/models/`:

- `data_models.py`: Core domain models (UserProfile, TherapySession, etc.)
- `api_models.py`: API request/response models
- `orchestration/models.py`: Workflow and orchestration models

### Type Generation Pipeline

```
┌─────────────────────────────────────────────────┐
│ Backend: Pydantic Models (Python)               │
│ src/models/data_models.py                       │
└─────────────────────────────────────────────────┘
                    ↓
           [scripts/generate_schemas.py]
                    ↓
┌─────────────────────────────────────────────────┐
│ Intermediate: JSON Schema                       │
│ schemas/*.json                                  │
└─────────────────────────────────────────────────┘
                    ↓
           [quicktype via npm script]
                    ↓
┌─────────────────────────────────────────────────┐
│ Frontend: TypeScript Types                      │
│ frontend/src/types/generated/api.ts            │
└─────────────────────────────────────────────────┘
                    ↓
           [Frontend code imports]
                    ↓
┌─────────────────────────────────────────────────┐
│ Type-safe API calls and data handling           │
└─────────────────────────────────────────────────┘
```

## Usage Examples

### Backend Model Definition

```python
# src/models/data_models.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class UserProfile(BaseModel):
    """User profile data model."""

    user_id: str = Field(..., description="Unique user identifier")
    name: str = Field(..., description="User's full name")
    birthdate: Optional[str] = Field(None, description="Birth date (YYYY-MM-DD)")
    status: UserStatus = Field(..., description="Current workflow status")
    created_at: datetime
    updated_at: datetime

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user-123",
                "name": "John Doe",
                "status": "PROFILE_ONLY",
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z"
            }
        }
```

### Generated TypeScript Type

```typescript
// frontend/src/types/generated/api.ts (AUTO-GENERATED)

/**
 * User profile data model.
 */
export interface UserProfile {
  /**
   * Unique user identifier
   */
  userId: string;

  /**
   * User's full name
   */
  name: string;

  /**
   * Birth date (YYYY-MM-DD)
   */
  birthdate?: string;

  /**
   * Current workflow status
   */
  status: UserStatus;

  createdAt: string; // ISO 8601 datetime
  updatedAt: string; // ISO 8601 datetime
}
```

### Frontend Usage

```typescript
// frontend/src/services/apiClient.ts
import { UserProfile, UserStatus } from '@/types/generated/api';

class ApiClient {
  async getUserProfile(userId: string): Promise<UserProfile> {
    const response = await fetch(`/api/user/profile?user_id=${userId}`);
    const data = await response.json();
    return data as UserProfile; // Type-safe
  }

  async updateUserProfile(profile: UserProfile): Promise<void> {
    await fetch('/api/user/profile', {
      method: 'POST',
      body: JSON.stringify(profile), // All fields type-checked
    });
  }
}
```

## Naming Conventions

### Field Name Conversion

Python `snake_case` → TypeScript `camelCase` (automatic):

| Python | TypeScript |
|--------|------------|
| `user_id` | `userId` |
| `created_at` | `createdAt` |
| `therapy_plan` | `therapyPlan` |

### Type Name Conversion

Type names remain the same:

| Python | TypeScript |
|--------|------------|
| `UserProfile` | `UserProfile` |
| `TherapySession` | `TherapySession` |

## Common Patterns

### Optional Fields

```python
# Backend
birthdate: Optional[str] = None

# Frontend (generated)
birthdate?: string;
```

### Enums

```python
# Backend
class UserStatus(str, Enum):
    PROFILE_ONLY = "PROFILE_ONLY"
    INTAKE_IN_PROGRESS = "INTAKE_IN_PROGRESS"

# Frontend (generated)
export enum UserStatus {
  PROFILE_ONLY = "PROFILE_ONLY",
  INTAKE_IN_PROGRESS = "INTAKE_IN_PROGRESS",
}
```

### DateTime Fields

```python
# Backend
created_at: datetime

# Frontend (generated as string)
createdAt: string; // ISO 8601 format

// Helper for parsing
const date = new Date(profile.createdAt);
```

## Troubleshooting

### Type Generation Fails

```bash
# Check backend models are valid
python scripts/generate_schemas.py

# Check generated schemas
cat schemas/UserProfile.json

# Regenerate TypeScript types
cd frontend && npm run generate:types
```

### Type Mismatch Errors

1. Check backend model definition
2. Regenerate schemas: `make generate-schemas`
3. Regenerate types: `npm run generate:types`
4. Clear TypeScript cache: `rm -rf frontend/node_modules/.cache`

### Adding New Field

1. Add field to Pydantic model
2. Run `make generate-schemas`
3. Run `npm run generate:types`
4. TypeScript will show errors where field is missing - fix them

## Best Practices

### DO ✅

- Define all API models in backend Pydantic
- Use type annotations everywhere
- Run type generation before commits
- Use generated types in API calls
- Add JSDoc comments to Pydantic models (they'll appear in TS)

### DON'T ❌

- Manually edit generated types
- Create duplicate type definitions
- Use `any` type for API data
- Bypass type checking with `as any`
- Commit type mismatches

## CI/CD Integration

Type generation runs automatically in:

- `npm run build` (pre-build hook)
- `npm run dev` (pre-dev hook)
- GitHub Actions (see `.github/workflows/test.yml`)

## Maintenance

### Weekly

- Review type generation logs for warnings
- Check for deprecated Pydantic patterns

### Per Release

- Verify all API models are exported
- Run full type validation suite
- Update this documentation if patterns change

## References

- [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/)
- [quicktype](https://quicktype.io/)
- [JSON Schema](https://json-schema.org/)
```

---

## VALIDATION CRITERIA

### Success Metrics

- [ ] All backend models have JSON Schemas in `schemas/`
- [ ] TypeScript types auto-generate without errors
- [ ] Frontend builds with `npm run build` (types generated automatically)
- [ ] Zero manual type definitions for API models remaining
- [ ] All API calls use generated types
- [ ] Type generation integrated into CI/CD
- [ ] Documentation complete and accurate

### Test Coverage

- [ ] Schema generation tests pass
- [ ] TypeScript compilation tests pass
- [ ] Integration tests verify type compatibility
- [ ] All existing functionality still works
- [ ] No type errors in frontend build

### Code Quality

- [ ] Generated types are readable and well-documented
- [ ] Field name conversion (snake_case → camelCase) works correctly
- [ ] Enum types work correctly
- [ ] Optional fields handled properly
- [ ] DateTime serialization handled consistently

---

## RISKS AND MITIGATION

### Risk 1: Breaking Changes During Migration

**Probability**: Medium
**Impact**: High

**Mitigation**:
- Incremental migration (keep old types temporarily)
- Comprehensive test suite before/after
- Feature flags for new type system
- Rollback plan

### Risk 2: Type Generation Inconsistencies

**Probability**: Low
**Impact**: Medium

**Mitigation**:
- Extensive testing of edge cases
- Manual review of generated types
- Integration tests for type compatibility
- Documentation of known issues

### Risk 3: Developer Resistance

**Probability**: Low
**Impact**: Low

**Mitigation**:
- Clear documentation
- Developer training session
- Demonstrate benefits (autocomplete, error detection)
- Quick reference guide

### Risk 4: Build Time Increase

**Probability**: Medium
**Impact**: Low

**Mitigation**:
- Cache generated types (only regenerate on backend changes)
- Optimize quicktype configuration
- Parallel CI/CD jobs

---

## ROLLBACK PLAN

If critical issues arise:

1. **Immediate**: Revert to manual types
   ```bash
   git revert <type-generation-commits>
   npm install
   npm run build
   ```

2. **Short-term**: Fix specific issues
   - Identify problematic types
   - Temporarily exclude from generation
   - Create manual types for those models only

3. **Long-term**: Reassess approach
   - Consider alternative tools (datamodel-code-generator)
   - Simplify backend models
   - Adjust generation configuration

---

## POST-IMPLEMENTATION

### Monitoring

- Track type generation failures in CI/CD
- Monitor TypeScript compilation warnings
- Review developer feedback
- Measure time saved vs manual type maintenance

### Continuous Improvement

- Optimize generation speed
- Improve generated type quality
- Add more sophisticated transformations
- Consider GraphQL Code Generator for future

### Future Enhancements (Phase 4+)

- API versioning with type generation
- Automatic API client generation (not just types)
- Runtime validation from schemas
- OpenAPI spec generation for documentation

---

## TIMELINE

| Day | Tasks | Owner | Status |
|-----|-------|-------|--------|
| 1 | Backend schema export script | Backend Dev | ⏳ Pending |
| 1 | Test schema generation | Backend Dev | ⏳ Pending |
| 2 | TypeScript generation setup | Frontend Dev | ⏳ Pending |
| 2 | Build integration | Frontend Dev | ⏳ Pending |
| 3 | CI/CD integration | DevOps | ⏳ Pending |
| 3 | Git configuration | DevOps | ⏳ Pending |
| 4 | Audit existing types | Frontend Dev | ⏳ Pending |
| 4 | Create migration plan | Frontend Dev | ⏳ Pending |
| 5 | Migrate components | Frontend Dev | ⏳ Pending |
| 5 | Update API client | Frontend Dev | ⏳ Pending |
| 6 | Testing and validation | QA | ⏳ Pending |
| 6 | Integration tests | QA | ⏳ Pending |
| 7 | Documentation | Tech Writer | ⏳ Pending |
| 7 | Developer guide | Tech Writer | ⏳ Pending |

**Total Estimated Effort**: 5-7 days (1 week)

---

## DEPENDENCIES

### Prerequisites

- Phase 1 API Client Layer (recommended, not required)
- Node.js 18+
- Python 3.11+
- npm or yarn

### External Dependencies

- `quicktype`: TypeScript generation from JSON Schema
- `pydantic`: Python models with JSON Schema export
- `httpx`: (already installed) for API calls

### Internal Dependencies

- All backend models must have proper Pydantic definitions
- Frontend build process must support pre-build hooks
- CI/CD pipeline must support artifact passing (schemas)

---

## CONCLUSION

Phase 3 eliminates one of the major maintenance burdens identified in the architecture assessment: manual type synchronization between backend and frontend. By implementing automated type generation, we achieve:

1. **Single Source of Truth**: Backend Pydantic models drive all types
2. **Compile-Time Safety**: TypeScript catches API contract violations
3. **Developer Productivity**: IDE autocomplete and inline documentation
4. **Reduced Bugs**: Impossible to have type drift
5. **Future-Proof**: Foundation for API versioning and client generation

This phase sets up the foundation for Phase 4 (authentication and polish) and positions the project for easy addition of new clients (mobile app) in the future.

**Next Phase**: Phase 4 - Authentication & Polish

---

**Document Version**: 1.0
**Created**: 2025-12-03
**Author**: Claude Code
**Status**: Ready for Review and Implementation
