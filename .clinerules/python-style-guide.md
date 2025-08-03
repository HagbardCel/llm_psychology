# Python Style Guide

## Code Formatting

### Formatter: Black
Use `black` as the primary code formatter to ensure consistent formatting across the codebase.

```bash
# Install black
pip install black

# Format all Python files
black .

# Format specific files
black src/main.py src/agents/*.py
```

Configuration (`.black` or in `pyproject.toml`):
```toml
[tool.black]
line-length = 88
target-version = ['py310']
```

## Linting

### Linter: Ruff
Use `ruff` for fast, comprehensive linting that catches errors and enforces best practices.

```bash
# Install ruff
pip install ruff

# Run linting
ruff check .

# Auto-fix common issues
ruff check --fix .
```

Configuration (`.ruff.toml` or in `pyproject.toml`):
```toml
[tool.ruff]
line-length = 88
target-version = "py310"

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "C",    # mccabe
    "B",    # bugbear
    "UP",   # pyupgrade
]
```

## Naming Conventions

### General Rules
- Use `snake_case` for variables, functions, and method names
- Use `PascalCase` for class names
- Use `UPPER_CASE` for constants
- Use descriptive names that clearly indicate purpose

### Examples
```python
# Good
user_session = Session()
MAX_RETRIES = 3
def conduct_intake_session():
    pass

# Avoid
us = Session()
maxRetries = 3
def intake():
    pass
```

## Type Hinting

### Mandatory Type Hints
All function signatures must include type hints for parameters and return values.

```python
# Good
def conduct_session(self, therapy_plan: TherapyPlan, duration_minutes: int, ui: ConsoleUI) -> Session:
    pass

# Avoid
def conduct_session(self, therapy_plan, duration_minutes, ui):
    pass
```

### Import Types
Use `from __future__ import annotations` at the top of files to enable forward references and cleaner type hints.

## Docstrings

### Style: Google Style
Follow Google's Python style guide for docstrings.

```python
def conduct_intake(self, ui: ConsoleUI) -> Session:
    """Conduct the initial intake session with the user.
    
    Args:
        ui: The console UI interface for user interaction.
        
    Returns:
        Session: The completed intake session object.
        
    Raises:
        IntakeError: If the intake process fails to complete.
    """
    pass
```

## Dependency Management

### pip-tools Workflow
Use `pip-tools` to manage dependencies with exact version pinning.

```bash
# Install pip-tools
pip install pip-tools

# Define direct dependencies
# requirements.in
langchain
langchain-google-genai
chromadb
# ... other dependencies

# Compile to exact versions
pip-compile requirements.in

# Install dependencies
pip-sync requirements.txt
```

### Development Dependencies
Separate development dependencies in `requirements-dev.in`:
```bash
# requirements-dev.in
pytest
black
ruff
mypy
```

## Error Handling

### Custom Exceptions
Define custom exception classes for specific error conditions:

```python
class PsychoanalystError(Exception):
    """Base exception for psychoanalyst application."""
    pass

class DatabaseError(PsychoanalystError):
    """Raised when database operations fail."""
    pass

class LLMServiceError(PsychoanalystError):
    """Raised when LLM service calls fail."""
    pass
```

### Exception Handling
- Catch specific exceptions rather than using broad `except` clauses
- Log errors appropriately with context
- Provide meaningful error messages to users when appropriate

## Logging

### Standard Library Logging
Use Python's built-in `logging` module:

```python
import logging

logger = logging.getLogger(__name__)

logger.info("Starting therapy session")
logger.error("Failed to connect to LLM service: %s", error_message)
```

### Log Levels
- `DEBUG`: Detailed information for diagnosing problems
- `INFO`: General information about program execution
- `WARNING`: Something unexpected happened, but the program can continue
- `ERROR`: A serious problem that prevented a function from completing
- `CRITICAL`: A very serious error that may cause the program to stop

## Testing

### pytest Framework
Use `pytest` for testing with fixtures and parametrization.

### Test Structure
- Use descriptive test function names
- Follow the Arrange-Act-Assert pattern
- Mock external dependencies
- Test both happy paths and error conditions

### Example
```python
def test_intake_agent_conduct_intake(mock_llm_service, mock_db_service):
    """Test that intake agent correctly conducts intake session."""
    # Arrange
    agent = IntakeAgent(mock_llm_service, mock_db_service)
    
    # Act
    session = agent.conduct_intake(mock_ui)
    
    # Assert
    assert isinstance(session, Session)
    mock_llm_service.call.assert_called()
