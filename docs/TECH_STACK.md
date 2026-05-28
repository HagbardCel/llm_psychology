# Technology Stack

This document outlines the technologies used in the Virtual LLM-Driven Psychoanalyst application, rationale for technology choices, and version requirements.

**Last Updated:** 2026-05-16
**Last Verified:** 2026-05-16
**System Version:** 2.0 (Trio Architecture)

## 📊 Stack Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend Layer                        │
│  React 19 + TypeScript + Material-UI + Vite            │
└─────────────────────────────────────────────────────────┘
                            │
                    WebSocket + REST API
                            │
┌─────────────────────────────────────────────────────────┐
│                    Backend Layer                         │
│  Python 3.11 + Trio + Quart + Hypercorn                │
└─────────────────────────────────────────────────────────┘
                            │
├───────────────┬───────────────┬───────────────┬─────────┤
│               │               │               │         │
┌───────┐  ┌────────┐  ┌──────────┐  ┌────────┐  ┌──────┐
│SQLite │  │ No-op  │  │Google    │  │Pydantic│  │Trio  │
│  DB   │  │  RAG   │  │Gemini API│  │Schemas │  │ Core │
└───────┘  └────────┘  └──────────┘  └────────┘  └──────┘
```

---

## 🔧 Core Technologies

### Backend Runtime

#### Python 3.11+
**Purpose:** Primary backend language
**Version:** 3.11 or higher
**Rationale:**
- Modern async/await syntax with excellent Trio support
- Strong type hints support for Pydantic models
- Rich ecosystem for ML/AI libraries
- Excellent tooling (pytest, black, ruff)

#### Trio 0.32.0+
**Purpose:** Structured concurrency runtime
**Version:** 0.32.0 or higher
**Rationale:**
- **Structured concurrency**: Automatic task supervision and cleanup
- **No orphaned tasks**: Guarantees all tasks complete or are cancelled
- **Error propagation**: Errors bubble up through nursery boundaries
- **Deterministic shutdown**: Clean, predictable teardown behavior
- **Replaced asyncio**: Eliminated 50+ lines of manual cleanup code

**Key Features Used:**
- `trio.open_nursery()` for task spawning
- `trio.to_thread.run_sync()` for blocking operations (SQLite, LLM calls)
- Memory channels for inter-task communication
- Cancel scopes for timeout handling

---

### Web Framework

#### Quart 0.19.0+
**Purpose:** Async web framework (Flask-like API)
**Version:** 0.19.0 or higher
**Rationale:**
- Flask-familiar API with async support
- Native WebSocket support
- Trio compatibility via Hypercorn
- Easy migration path for Flask developers

#### Hypercorn
**Purpose:** ASGI server with Trio support
**Rationale:**
- Trio worker mode for structured concurrency
- Production-ready ASGI server
- WebSocket support
- HTTP/2 support

---

### Database & Storage

#### SQLite 3
**Purpose:** Primary data persistence
**Database File:** `data/psychoanalyst.db`
**Rationale:**
- Serverless, zero-configuration
- ACID compliance for data integrity
- File-based (easy backup/restore)
- Perfect for single-user therapeutic application
- Mature Python support via `sqlite3` stdlib

**Schema Management:**
- Versioned migrations via `MigrationService`
- Schema defined in `src/services/trio_db_service.py`
- Migration scripts in `src/services/migration_service.py`

#### RAG Backend
**Purpose:** Retrieval boundary for agent prompt context
**Current Backend:** `RAG_BACKEND=none`
**Rationale:**
- Keeps the core product path lightweight and deterministic
- Avoids large optional ML/vector dependencies during finalization
- Leaves local vector retrieval as a future extension after core validation

---

### AI/ML Services

#### Configurable LLM Providers
**Purpose:** Large Language Model for therapeutic conversations
**APIs:** Google Gemini, Ollama, and OpenAI-compatible local servers such as LM Studio
**Rationale:**
- High-quality conversational AI
- Streaming response support
- Gemini supports hosted models and native structured output
- Ollama and LM Studio support private local inference for development and testing
- Local providers avoid external API calls but require user-managed model quality,
  hardware, and safety review

**Alternative Considerations:**
- OpenAI GPT-4: More expensive, similar quality
- Anthropic Claude: Good alternative, different API
- Local models: Privacy benefits but higher resource requirements and less
  consistent structured output

**Multi-Model Support:**
The application supports configuring different models for different agents:
- Each agent can use a dedicated model via environment variables
- Falls back to `MODEL_NAME` if agent-specific model is not configured
- Enables cost optimization by using cheaper models for simpler tasks
- Example: Use a smaller local model for intake and a larger local model for therapy
- Select the backend with `LLM_PROVIDER=gemini|ollama|lmstudio|openai_compatible`
  and optionally `LLM_BASE_URL`. The default local backend is a llama.cpp
  OpenAI-compatible server at `http://host.docker.internal:8080/v1`.

#### Sentence Transformers
**Purpose:** Text embeddings for RAG
**Model:** all-MiniLM-L6-v2
**Rationale:**
- Lightweight embedding model
- Fast inference on CPU
- Good quality for semantic search
- Open source

---

### Data Validation & Serialization

#### Pydantic 2.0+
**Purpose:** Data validation and serialization
**Rationale:**
- Type-safe data models
- Automatic validation
- JSON schema generation (for TypeScript types)
- FastAPI-style data modeling
- Excellent error messages

**Key Models:**
- `UserProfile`
- `SessionData`
- `TherapyPlan`
- `AgentResponse`
- WebSocket message types

---

## 🎨 Frontend Technologies

### Core Framework

#### Node.js 26
**Purpose:** Frontend runtime and package tooling
**Version:** 26.x with npm 11+
**Rationale:**
- Current runtime baseline before production launch
- Aligns local, Docker, test, and production frontend builds
- Supports current Vite, Vitest, React, and TypeScript tooling

#### React 19.2+
**Purpose:** UI framework
**Version:** 19.2.0 or higher
**Rationale:**
- Component-based architecture
- Excellent TypeScript support
- Rich ecosystem
- Current React rendering and testing behavior
- Hooks for state management

#### TypeScript 6.0+
**Purpose:** Type-safe JavaScript
**Version:** 6.0 or higher
**Rationale:**
- Compile-time type checking
- Better IDE support
- Safer refactoring
- Self-documenting code
- Integration with generated types from backend

---

### UI Library

#### Material-UI (MUI) 7.3+
**Purpose:** Component library
**Version:** 7.3.0 or higher
**Rationale:**
- Professional, accessible components
- Theming system
- Responsive design built-in
- Good documentation
- Active maintenance

**Components Used:**
- Navigation drawer
- Cards for session display
- Text fields for user input
- Loading indicators
- Dialog modals

---

### Build Tools

#### Vite 8+
**Purpose:** Build tool and dev server
**Version:** 8.0.0 or higher
**Rationale:**
- Extremely fast HMR (Hot Module Replacement)
- Modern build pipeline
- ESM-native
- Plugin ecosystem
- Better than Create React App for modern projects

#### Vitest
**Purpose:** Frontend unit test runner
**Version:** 4.1.0 or higher
**Rationale:**
- Shares the Vite transform pipeline
- Native TypeScript and ESM support
- Lower configuration overhead than a separate Jest/ts-jest stack

---

### State Management & Data Fetching

#### TanStack Query (React Query) 5.90+
**Purpose:** Server state management
**Version:** 5.90.11 or higher
**Rationale:**
- Excellent caching
- Automatic refetching
- Optimistic updates
- Dev tools
- WebSocket integration support

#### React Context API
**Purpose:** Application state management
**Rationale:**
- Built-in to React
- Simple for our use case
- No additional dependencies needed
- Good for user/session state, theme, etc.

---

### HTTP & WebSocket

#### Axios 1.5+
**Purpose:** HTTP client
**Version:** 1.5.0 or higher
**Rationale:**
- Promise-based API
- Interceptors for request headers
- Request/response transformation
- Better error handling than fetch

#### Native WebSocket API
**Purpose:** Real-time bidirectional communication
**Rationale:**
- Browser-native (no library needed)
- Streaming LLM responses
- Lower latency than polling
- Automatic reconnection (custom wrapper)

---

## 🧪 Testing & Quality

### Backend Testing

#### pytest 8.0+
**Purpose:** Python test framework
**Version:** 8.0 or higher
**Rationale:**
- Industry standard for Python
- Excellent fixture system
- Plugin ecosystem
- Parametrized tests

#### pytest-trio
**Purpose:** Trio async test support
**Rationale:**
- Native Trio test support
- Async fixture support
- Proper nursery handling in tests

#### pytest-cov
**Purpose:** Code coverage reporting
**Rationale:**
- Integration with pytest
- HTML reports
- Coverage metrics

---

### Frontend Testing

#### Vitest 4.1+
**Purpose:** JavaScript and React unit test framework
**Version:** 4.1.0 or higher
**Rationale:**
- Uses the same Vite transform path as the application
- Native ESM and TypeScript support
- Jest-compatible mocking APIs through `vi`
- Coverage support through V8

#### React Testing Library 13.4+
**Purpose:** Component testing
**Version:** 13.4.0 or higher
**Rationale:**
- Tests user behavior, not implementation
- Encourages accessible components
- Simpler than Enzyme
- Official React team recommendation

#### Playwright 1.40+
**Purpose:** End-to-end testing
**Version:** 1.40.0 or higher
**Rationale:**
- Cross-browser testing
- Auto-wait functionality
- Network mocking
- Debugging tools
- Better than Cypress for our use case

---

### Code Quality

#### Black
**Purpose:** Python code formatter
**Configuration:** 88 character line length
**Rationale:**
- Opinionated (no configuration debates)
- Deterministic formatting
- Industry standard

#### Ruff
**Purpose:** Python linter
**Rationale:**
- Extremely fast (Rust-based)
- Replaces Flake8, isort, and more
- Comprehensive rule set
- Auto-fix capabilities

#### ESLint 10.4+
**Purpose:** JavaScript/TypeScript linter
**Version:** 10.4.0 or higher
**Rationale:**
- TypeScript support
- React-specific rules
- Customizable rules
- Auto-fix support

#### Prettier 3.0+
**Purpose:** Frontend code formatter
**Version:** 3.0.0 or higher
**Rationale:**
- Consistent formatting
- Multi-language support
- Editor integration

---

## 🔄 Type Generation Pipeline

### Backend → Frontend Type Safety

```
Pydantic Models (Python)
        ↓
JSON Schema Generation (make generate-schemas, Docker)
        ↓
TypeScript Type Generation (quicktype)
        ↓
TypeScript Interfaces (frontend/src/types/generated/)
```

#### quicktype 23.0+
**Purpose:** JSON Schema to TypeScript conversion
**Version:** 23.0.0 or higher
**Rationale:**
- Accurate type generation
- Handles complex schemas
- CLI integration
- Active maintenance

**Workflow:**
```bash
# Backend generates schemas
make generate-schemas

# Frontend generates TypeScript types
docker compose run --rm -v "$PWD/schemas:/schemas" frontend npm run generate:ts
# Local alternative:
# cd frontend && npm run generate:types
```

---

## 🐳 DevOps & Infrastructure

### Containerization

#### Docker 24.0+
**Purpose:** Containerization
**Version:** 24.0 or higher
**Rationale:**
- Consistent environments
- Isolation
- Easy deployment
- Development parity with production

#### Docker Compose 2.0+
**Purpose:** Multi-container orchestration
**Version:** 2.0 or higher
**Rationale:**
- Simple local development setup
- Service definition in YAML
- Network management
- Volume management

---

### Development Tools

#### uv
**Purpose:** Fast Python package installer
**Rationale:**
- 10-100x faster than pip
- Pip-compatible
- Better dependency resolution
- Lockfile support

#### VSCode DevContainer
**Purpose:** Development environment
**Rationale:**
- Consistent developer experience
- Pre-configured tools
- Isolated from host system
- Extensions bundled

---

## 📦 Key Dependencies Summary

### Backend
```
trio>=0.32.0              # Structured concurrency
quart>=0.19.0             # Web framework
hypercorn>=0.16.0         # ASGI server
pydantic>=2.0.0           # Data validation
google-generativeai       # Gemini API
chromadb>=0.4.0           # Vector database
pytest>=8.0.0             # Testing
```

### Frontend
```
react@^18.2.0                      # UI framework
typescript@^5.0.0                  # Type safety
@mui/material@^5.14.0              # UI components
vite@^4.4.0                        # Build tool
@tanstack/react-query@^5.90.11    # Data fetching
@playwright/test@^1.40.0          # E2E testing
```

---

## 🔄 Technology Evolution

### Major Changes

#### Phase 4: Asyncio → Trio Migration (2025-11)
**Reason:** Structured concurrency benefits
**Impact:** Eliminated manual cleanup, improved reliability
**Migration:** All agents, services, and orchestration layer

#### Phase 3: Type Generation (2025-11)
**Reason:** Frontend/backend type mismatches
**Impact:** Zero type bugs between layers
**Implementation:** Pydantic → JSON Schema → TypeScript

#### Phase 2: Orchestration Architecture (2025-10)
**Reason:** Tight coupling in monolithic design
**Impact:** Testable, reusable business logic
**Implementation:** Workflow engine, conversation manager, agent orchestrator

---

## 🎯 Technology Selection Criteria

When evaluating new technologies, we prioritize:

1. **Maintainability**: Active development, good documentation
2. **Type Safety**: Strong typing to prevent runtime errors
3. **Testing Support**: Easy to test, good tooling
4. **Performance**: Adequate for our use case
5. **Community**: Active community, ecosystem support
6. **Learning Curve**: Reasonable for team skill level
7. **Licensing**: Compatible with our project license

---

## 📚 Related Documentation

- [Architecture Overview](ARCHITECTURE.md) - System design
- [Design Principles](DESIGN_PRINCIPLES.md) - Architectural patterns
- [Development Guide](QUICKSTART.md) - Getting started
- [Type System](TYPE_SYSTEM.md) - Type generation details
- [WebSocket Protocol](WEBSOCKET_PROTOCOL.md) - Real-time communication
