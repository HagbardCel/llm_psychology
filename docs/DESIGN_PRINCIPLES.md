# Design Principles & Patterns

This document outlines the core design principles, architectural patterns, and coding standards that guide development of the Virtual LLM-Driven Psychoanalyst application.

**Last Updated:** 2025-12-04
**Architecture Version:** 2.0 (Trio-based Orchestration)

---

## 🎯 Core Principles

### 1. Structured Concurrency First

**Principle:** All concurrent operations use Trio's structured concurrency model.

**Why:**
- Automatic task supervision prevents orphaned tasks
- Errors propagate deterministically through nursery boundaries
- Shutdown behavior is predictable and clean
- Code is easier to reason about

**Implementation:**
```python
# ✅ GOOD: Structured concurrency
async def handle_request():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(task1)
        nursery.start_soon(task2)
    # Both tasks guaranteed to complete or be cancelled

# ❌ BAD: Fire-and-forget tasks (asyncio style)
async def handle_request():
    asyncio.create_task(task1())  # Orphan risk
    asyncio.create_task(task2())  # No supervision
```

**Key Patterns:**
- Use `trio.open_nursery()` for spawning concurrent tasks
- Use `trio.to_thread.run_sync()` for blocking operations (SQLite, file I/O)
- Never let tasks escape their nursery scope
- Use cancel scopes for timeouts

---

### 2. Separation of Concerns (Clean Architecture)

**Principle:** Business logic is completely independent of I/O concerns.

**Why:**
- Business logic is testable without I/O
- Agents can be reused across different interfaces (CLI, web, API)
- Changes to UI don't affect core logic
- Clear boundaries improve maintainability

**Architecture Layers:**
```
┌─────────────────────────────────────┐
│     Gateway Layer (I/O)             │  ← WebSocket, REST, CLI
│  - WebSocketGateway                 │
│  - REST endpoints                   │
│  - Console UI                       │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│   Orchestration Layer (Business)    │  ← Workflow coordination
│  - WorkflowEngine                   │
│  - ConversationManager              │
│  - AgentOrchestrator                │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│      Agent Layer (Domain Logic)     │  ← Pure business logic
│  - IntakeAgent                      │
│  - AssessmentAgent                  │
│  - PsychoanalystAgent               │
│  - ReflectionAgent                  │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│    Service Layer (Infrastructure)   │  ← External dependencies
│  - DatabaseService                  │
│  - LLMService                       │
│  - RAGService                       │
└─────────────────────────────────────┘
```

**Rules:**
- Agents never do I/O directly (no WebSocket, no HTTP)
- Orchestration layer never contains domain logic
- Gateway layer only handles I/O and delegates to orchestration
- Services provide clean abstractions over external dependencies

---

### 3. Type Safety Throughout

**Principle:** Strong typing at every layer, from database to UI.

**Why:**
- Catch bugs at compile time, not runtime
- Self-documenting interfaces
- Safe refactoring
- IDE autocomplete and tooling support

**Implementation:**
```python
# Backend: Pydantic models
class UserProfile(BaseModel):
    user_id: str
    name: str
    preferences: dict[str, Any]

# Frontend: Generated TypeScript types
interface UserProfile {
    user_id: string;
    name: string;
    preferences: Record<string, any>;
}
```

**Type Pipeline:**
```
Pydantic (Python) → JSON Schema → TypeScript → Frontend
```

**Rules:**
- All data models use Pydantic
- No `Any` types without justification
- Auto-generate frontend types from backend schemas
- Use `mypy --strict` for type checking

---

### 4. Immutable Data Flows

**Principle:** Data flows in one direction; avoid bidirectional coupling.

**Why:**
- Easier to trace data changes
- Reduces hidden dependencies
- Simpler debugging
- Better for testing

**Pattern:**
```
User Input → Gateway → Orchestrator → Agent → Service
                ↓
User Output ← Gateway ← Orchestrator ← Agent ← Service
```

**Rules:**
- Agents return `AgentResponse`, never modify input directly
- Database records are append-only (sessions are immutable)
- State transitions are explicit and validated
- No circular dependencies between layers

---

### 5. Test-Driven Development

**Principle:** Write tests first, then implement.

**Why:**
- Tests define expected behavior
- Prevents over-engineering
- Ensures testability of design
- Catches regressions early

**Approach:**
```python
# 1. Write the test
def test_intake_agent_collects_name():
    agent = IntakeAgent(llm_service=MockLLM())
    response = await agent.process("My name is Alice")
    assert response.user_data["name"] == "Alice"

# 2. Implement to pass the test
class IntakeAgent:
    async def process(self, message: str) -> AgentResponse:
        # Implementation...
```

**Standards:**
- Unit test coverage > 80%
- Integration tests for critical flows
- Mock external services (LLM, database) for unit tests
- Real services for integration tests

---

## 🏗️ Architectural Patterns

### State Machine Pattern

**Usage:** Workflow management
**Implementation:** `WorkflowEngine` in `src/orchestration/trio_workflow_engine.py`

**States:**
```
NEW → INTAKE_IN_PROGRESS → INTAKE_COMPLETE
  → ASSESSMENT_IN_PROGRESS → ASSESSMENT_COMPLETE
  → THERAPY_IN_PROGRESS → REFLECTION_IN_PROGRESS
  → PLAN_COMPLETE → THERAPY_IN_PROGRESS (cycle)
```

**Rules:**
- All transitions are explicit and validated
- Invalid transitions raise `WorkflowError`
- State is persisted in database
- No hidden state changes

**Benefits:**
- Clear workflow visualization
- Easy to add new states
- Prevents invalid transitions
- Audit trail of state changes

---

### Strategy Pattern

**Usage:** Therapy style selection
**Implementation:** `StyleService` with style-specific prompts

**Example:**
```python
class TherapySession:
    def __init__(self, style: str):
        self.style_config = style_service.load_style(style)

    async def respond(self, message: str):
        # Use style-specific prompts and knowledge
        prompt = self.style_config.get_prompt("session")
        return await llm_service.generate(prompt, message)
```

**Benefits:**
- Easy to add new therapy styles
- Style-specific behavior encapsulated
- Runtime style switching
- No conditionals in core logic

---

### Repository Pattern

**Usage:** Data access abstraction
**Implementation:** `TrioDatabaseService`

**Example:**
```python
class TrioDatabaseService:
    async def get_user_profile(self, user_id: str) -> UserProfile:
        # Encapsulates SQL details
        return await trio.to_thread.run_sync(
            self._get_user_profile_sync, user_id
        )
```

**Benefits:**
- Database implementation can change without affecting agents
- Easy to mock for testing
- Centralized query logic
- Thread-safe access to SQLite

---

### Observer Pattern (Streaming)

**Usage:** Real-time LLM response streaming
**Implementation:** `ConversationManager` with async generators

**Example:**
```python
async def stream_response(self, prompt: str):
    async for chunk in llm_service.stream(prompt):
        yield chunk  # Observer gets immediate updates
```

**Benefits:**
- Progressive rendering of responses
- Lower perceived latency
- Cancellable operations
- Better UX

---

### Dependency Injection

**Usage:** Service composition
**Implementation:** `ServiceContainer`

**Example:**
```python
class ServiceContainer:
    def __init__(self):
        self.db_service = TrioDatabaseService()
        self.llm_service = LLMService()
        self.rag_service = RAGService()

    def create_agent(self, agent_type: str):
        # Inject dependencies
        if agent_type == "intake":
            return IntakeAgent(
                llm_service=self.llm_service,
                rag_service=self.rag_service
            )
```

**Benefits:**
- Easy testing (inject mocks)
- Loose coupling
- Single place to configure services
- Clear dependency graph

---

## 💻 Coding Standards

### Python Standards

#### Naming Conventions
```python
# Classes: PascalCase
class IntakeAgent: ...

# Functions: snake_case
async def process_message(msg: str): ...

# Constants: UPPER_SNAKE_CASE
MAX_SESSION_DURATION = 45 * 60

# Private: _leading_underscore
def _internal_helper(): ...
```

#### Docstrings
Use Google-style docstrings:
```python
async def process_message(user_id: str, message: str) -> AgentResponse:
    """Process a user message through the appropriate agent.

    Args:
        user_id: Unique identifier for the user
        message: User's input message

    Returns:
        AgentResponse containing reply and state transition

    Raises:
        WorkflowError: If user is in invalid state for messaging
    """
```

#### Type Hints
Always use type hints:
```python
# ✅ GOOD
def calculate_score(responses: list[str]) -> float:
    ...

# ❌ BAD
def calculate_score(responses):
    ...
```

#### Error Handling
Be specific with exceptions:
```python
# ✅ GOOD
try:
    profile = await db.get_user_profile(user_id)
except UserNotFoundError:
    profile = await db.create_user_profile(user_id)

# ❌ BAD
try:
    profile = await db.get_user_profile(user_id)
except Exception:  # Too broad
    profile = None
```

---

### TypeScript Standards

#### Naming Conventions
```typescript
// Interfaces: PascalCase
interface UserProfile { }

// Functions: camelCase
function processMessage(msg: string): void { }

// Constants: UPPER_SNAKE_CASE
const MAX_RETRIES = 3;

// React components: PascalCase
function TherapySession() { }
```

#### React Patterns
Use functional components and hooks:
```typescript
// ✅ GOOD: Functional component with hooks
function SessionView() {
  const [messages, setMessages] = useState<Message[]>([]);

  useEffect(() => {
    // Side effects
  }, []);

  return <div>{messages}</div>;
}

// ❌ BAD: Class components (legacy)
class SessionView extends React.Component { }
```

---

### Testing Standards

#### Arrange-Act-Assert Pattern
```python
async def test_intake_agent_extracts_name():
    # Arrange
    agent = IntakeAgent(llm_service=MockLLMService())
    message = "Hi, I'm Alice"

    # Act
    response = await agent.process(message)

    # Assert
    assert response.user_data["name"] == "Alice"
```

#### Test Naming
```python
# Format: test_<component>_<scenario>_<expected_result>
def test_workflow_engine_invalid_transition_raises_error(): ...
def test_conversation_manager_streams_response_chunks(): ...
def test_database_service_creates_user_profile_when_missing(): ...
```

#### Mocking Strategy
- Mock external services (LLM API, vector DB)
- Use real database for integration tests (with fixtures)
- Don't mock what you own (internal components)

---

## 🚫 Anti-Patterns to Avoid

### 1. God Objects
**Problem:** One class does too much
**Solution:** Split responsibilities

```python
# ❌ BAD: God object
class TherapySystem:
    def handle_websocket(self, ws): ...
    def manage_database(self): ...
    def call_llm(self, prompt): ...
    def update_ui(self): ...

# ✅ GOOD: Single responsibility
class WebSocketGateway: ...
class DatabaseService: ...
class LLMService: ...
class UIRenderer: ...
```

### 2. Leaky Abstractions
**Problem:** Implementation details leak through interfaces
**Solution:** Hide complexity behind clean APIs

```python
# ❌ BAD: SQL details leak
agent.execute_query("SELECT * FROM users WHERE id = ?", user_id)

# ✅ GOOD: Clean abstraction
agent.get_user_profile(user_id)
```

### 3. Premature Optimization
**Problem:** Optimizing before measuring
**Solution:** Profile first, then optimize

```python
# ❌ BAD: Complex caching without need
@lru_cache(maxsize=10000)  # Overkill?
def get_user_name(user_id):
    return db.query_name(user_id)

# ✅ GOOD: Simple first, optimize if needed
def get_user_name(user_id):
    return db.query_name(user_id)
    # Add caching only if profiling shows this is slow
```

### 4. Callback Hell
**Problem:** Nested callbacks
**Solution:** Use structured concurrency

```python
# ❌ BAD: Callback pyramid
def process_message(msg, callback):
    get_user(msg.user_id, lambda user:
        get_session(user.session_id, lambda session:
            update_session(session, lambda result:
                callback(result))))

# ✅ GOOD: Sequential async code
async def process_message(msg):
    user = await get_user(msg.user_id)
    session = await get_session(user.session_id)
    result = await update_session(session)
    return result
```

---

## 📚 Further Reading

- [Architecture Overview](ARCHITECTURE.md) - System design
- [Tech Stack](TECH_STACK.md) - Technology choices
- [Type System](TYPE_SYSTEM.md) - Type generation pipeline
- [WebSocket Protocol](WEBSOCKET_PROTOCOL.md) - Real-time communication spec

---

## 🔄 Living Document

These principles evolve as we learn. When patterns change:

1. Update this document
2. Add rationale for the change
3. Update code to match new patterns
4. Document in git commit message

**Last Major Update:** 2025-11-17 (Trio migration complete)
