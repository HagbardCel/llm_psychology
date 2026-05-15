---
owner: engineering
status: supporting
last_reviewed: 2026-02-22
review_cycle_days: 180
source_of_truth_for: Coding-style examples and anti-pattern callouts
---

# Coding Standards and Anti-Patterns

This companion guide holds practical style examples and anti-pattern reminders
that were previously embedded in `docs/design-principles.md`.

## Coding Standards

### Python Standards

#### Naming Conventions
```python
# Classes: PascalCase
class TrioIntakeAgent: ...

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
Always use type hints (checked by mypy strict mode):
```python
# GOOD
def calculate_score(responses: list[str]) -> float:
    ...

# BAD
def calculate_score(responses):
    ...
```

#### Error Handling
Be specific with exceptions:
```python
# GOOD
try:
    profile = await db.get_user_profile(user_id)
except UserNotFoundError:
    profile = await db.create_user_profile(user_id)
```

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
Use functional components and hooks. Avoid class components.

### Testing Standards

#### Arrange-Act-Assert Pattern
```python
async def test_intake_agent_extracts_name():
    # Arrange
    agent = TrioIntakeAgent(llm_service=MockLLMService())
    message = "Hi, I'm Alice"

    # Act
    response = await agent.process(message)

    # Assert
    assert response.user_data["name"] == "Alice"
```

#### Mocking Strategy
- Mock external services (LLM API, vector DB)
- Use real database for integration tests (with fixtures)
- Don't mock what you own (internal components)

## Anti-Patterns to Avoid

### 1. God Objects
Problem: One class does too much.  
Solution: Split responsibilities.

```python
# BAD: God object
class TherapySystem:
    def handle_websocket(self, ws): ...
    def manage_database(self): ...
    def call_llm(self, prompt): ...
    def update_ui(self): ...

# GOOD: Single responsibility
class WebSocketGateway: ...
class TrioDatabaseService: ...
class LLMService: ...
class UIRenderer: ...
```

### 2. Leaky Abstractions
Problem: Implementation details leak through interfaces.  
Solution: Hide complexity behind clean APIs.

```python
# BAD: SQL details leak
agent.execute_query("SELECT * FROM users WHERE id = ?", user_id)

# GOOD: Clean abstraction
agent.get_user_profile(user_id)
```

### 3. Premature Optimization
Problem: Optimizing before measuring.  
Solution: Profile first, then optimize. Keep code simple initially.

### 4. Callback Hell
Problem: Nested callbacks.  
Solution: Use Trio structured concurrency (`async`/`await`).

```python
# BAD: Callback pyramid
def process_message(msg, callback):
    get_user(msg.user_id, lambda user:
        get_session(user.session_id, lambda session:
            callback(session)))

# GOOD: Sequential async code
async def process_message(msg):
    user = await get_user(msg.user_id)
    session = await get_session(user.session_id)
    return session
```
