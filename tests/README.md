# Psychoanalyst Test Suite

This directory contains a comprehensive test suite for the psychoanalyst application, designed to ensure reliability, maintainability, and proper functionality of all components.

## Test Structure

```
tests/
├── conftest.py          # Pytest configuration and fixtures
├── README.md            # This file
├── run_tests.py         # Test runner script
├── unit/                # Unit tests for individual components
│   ├── test_db_service.py
│   ├── test_llm_service.py
│   ├── test_rag_service.py
│   ├── test_style_service.py
│   ├── test_intake_agent.py
│   ├── test_assessment_agent.py
│   ├── test_psychoanalyst_agent.py
│   └── test_reflection_agent.py
├── integration/         # Integration tests for component interactions
│   └── test_complete_session_flow.py
└── (legacy test files)  # Old script-style tests (to be removed)
```

## Test Types

### Unit Tests
- **Purpose**: Test individual components in isolation
- **Location**: `tests/unit/`
- **Coverage**: 
  - DatabaseService: All CRUD operations and user status logic
  - LLMService: API interactions and response handling
  - RAGService: Knowledge retrieval and management
  - StyleService: Therapy style pack loading and management
  - Agents: Individual agent logic with mocked dependencies

### Integration Tests
- **Purpose**: Test interactions between multiple components
- **Location**: `tests/integration/`
- **Coverage**:
  - Complete session flow (intake → assessment → therapy → reflection)
  - Resume flow integration with database service
  - Performance testing with multiple sessions
  - Error handling across component boundaries

## Key Features

### Mock-Based Testing
All external dependencies are properly mocked:
- **LLM Service**: Mocked to avoid API calls and ensure deterministic tests
- **Database**: Temporary in-memory databases for each test
- **RAG Service**: Mocked knowledge retrieval
- **UI**: Mock UI for simulating user interactions

### Test Fixtures
The `conftest.py` file provides reusable fixtures:
- `temp_db_path`: Temporary database file
- `db_service`: Database service with temporary database
- `mock_llm_service`: Mocked LLM service
- `mock_rag_service`: Mocked RAG service
- Sample data fixtures for common test scenarios

## Running Tests

### Using Makefile (Recommended)
```bash
# Run all tests
make test

# Run unit tests only
make test-unit

# Run integration tests only
make test-integration
```

### Using Pytest Directly
```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/unit/test_db_service.py

# Run tests with specific markers
pytest -m unit
pytest -m integration

# Run tests matching a keyword
pytest -k "database"
```

### Using Test Runner Script
```bash
# Run all tests
python tests/run_tests.py --all

# Run unit tests
python tests/run_tests.py --unit

# Run tests for specific service
python tests/run_tests.py --service db

# Run tests for specific agent
python tests/run_tests.py --agent intake
```

## Test Markers

- `@pytest.mark.unit`: Unit tests
- `@pytest.mark.integration`: Integration tests
- `@pytest.mark.asyncio`: Async tests
- `@pytest.mark.skip`: Skipped tests

## Best Practices Implemented

1. **Isolation**: Each test runs with its own temporary database
2. **Deterministic**: No external API calls or network dependencies
3. **Fast**: Tests complete quickly due to mocking
4. **Comprehensive**: Covers happy paths, edge cases, and error conditions
5. **Readable**: Clear test names and structured test classes
6. **Maintainable**: Proper use of fixtures and mock objects

## Coverage Areas

### Database Service
- User profile CRUD operations
- Session management
- Therapy plan handling
- User status determination
- Error handling

### LLM Service
- Response generation with and without context
- Structured response handling
- Error handling and fallback mechanisms

### RAG Service
- Knowledge retrieval with filtering
- Source-based knowledge access
- Error handling

### Style Service
- Style pack loading and validation
- Component retrieval
- Knowledge source management

### Agents
- **Intake Agent**: User profile collection, conversation management
- **Assessment Agent**: Therapy style recommendations, plan creation
- **Psychoanalyst Agent**: Session conduct, time management, style awareness
- **Reflection Agent**: Plan creation and updates, session summarization

## Legacy Test Files

The following script-style test files are deprecated and will be removed:
- `test_db_writing.py`
- `test_user_profile_creation.py`
- `test_short_session.py`

These have been replaced with proper unit and integration tests that are:
- Automated and deterministic
- Part of the continuous testing pipeline
- Faster and more reliable
- Better structured for maintenance

## Future Improvements

1. **Test Coverage**: Add coverage reporting with `pytest-cov`
2. **CI/CD Integration**: Set up automated testing on code changes
3. **Performance Tests**: Add more comprehensive performance benchmarks
4. **UI Tests**: Expand testing for the textual UI components
5. **Edge Case Coverage**: Add more tests for boundary conditions
