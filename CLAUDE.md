# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## General Guidance

- Follow a test-driven development approach
- When the user reports an issue, first check why this issue has not been identified through a failed unit test. If required, add a test to ensure this does not happen again.
- Focus on lean and maintable code
- Do NOT keep any legacy code. When implementing changes fully focus on the new structure and do not care about comptabibility with older interfaces.
- Before introducing any new function, check very carefully, if there is an existing function that could fulfill the same purpose.
- Before every git commit, ensure that all new compontents have proper units and where applicable integration tests and that they run succesfully.

## Project Overview

This is a Virtual LLM-Driven Psychoanalyst application that provides a terminal-based therapeutic experience using Large Language Models and Retrieval-Augmented Generation (RAG). The main application is located in the `psychoanalyst_app/` directory.

## Development Commands

### Essential Commands (run from psychoanalyst_app/ directory)

```bash
# Development setup
make dev-install          # Install development dependencies
make sync                 # Sync environment with locked requirements

# Code quality
make format               # Format code with black
make lint                 # Lint code with ruff

# Testing (Hybrid Approach)
# DevContainer testing (90% of development)
make test-dev             # Quick tests in devContainer (RECOMMENDED)
make test                 # Run all tests in devContainer
make test-unit            # Run unit tests only
make test-integration     # Run integration tests only
pytest -v                 # Run tests with verbose output
pytest tests/unit/test_db_service.py  # Run specific test file

# Docker isolated testing (pre-commit & CI/CD)
make test-validate        # Full isolated test suite before committing
make docker-test          # Same as test-validate
make install-hooks        # Install pre-commit hook for automated testing

# Running the application
make run                  # Run server locally with Python
make docker-run           # Run server with Docker Compose

# Build and dependency management
make requirements         # Generate locked requirements from .in files
pip-compile requirements.in  # Update production dependencies
pip-compile requirements-dev.in  # Update development dependencies
```

### Docker Commands

```bash
docker-compose up --build    # Build and start application server
docker-compose down          # Stop containers
```

## Architecture Overview

### Agent-Based Workflow
The application uses a sequential agent pattern:
- **IntakeAgent**: Gathers initial user information
- **AssessmentAgent**: Analyzes intake data and recommends therapy styles
- **PsychoanalystAgent**: Conducts main conversational sessions
- **ReflectionAgent**: Updates therapy plans based on session outcomes

### Core Services
- **DatabaseService**: SQLite-based persistence for sessions and user data
- **LLMService**: Abstraction for Google Gemini API calls
- **RAGService**: ChromaDB-based knowledge retrieval system
- **StyleService**: Manages therapy style configurations (Freud, Jung, CBT)

### Data Flow
1. Configuration loaded from `config.py` and `.env` file
2. Services initialized with database and vector store connections
3. User status determines workflow entry point (intake, assessment, or session)
4. Sessions are immutable records stored in SQLite
5. RAG system provides context-aware responses using domain knowledge

### Key Directories
- `src/agents/`: Core agent implementations (all Trio-based)
  - `trio_*_agent.py`: All 6 production agents using structured concurrency
- `src/services/`: Service layer abstractions
  - `trio_db_service.py`: Trio database service with thread-based SQLite operations
  - `llm_service.py`: LLM service abstraction for Google Gemini
  - `rag_service.py`: RAG service using ChromaDB
  - `style_service.py`: Therapy style configuration management
- `src/orchestration/`: Workflow and state management (all Trio-based)
  - `trio_workflow_engine.py`: State machine for user workflow
  - `trio_conversation_manager.py`: Message handling and LLM streaming
  - `trio_agent_orchestrator.py`: Agent lifecycle and coordination
  - `models.py`: Workflow state and event definitions
- `src/models/`: Pydantic data models and schemas
- `src/styles/`: Therapy style configurations with prompts and knowledge
- `src/ui/`: Base UI abstractions
- `console-ui/`: Trio-based console client for patient interaction
- `tests/`: Comprehensive test suite with unit and integration tests
  - `tests/integration/`: Integration tests for full workflows
  - `tests/unit/`: Unit tests for individual components
  - **Status**: 126 tests passing, 3 skipped

### Trio Architecture (CURRENT PRODUCTION SYSTEM)

**Status**: ✅ **Complete Trio Migration** (2025-11-17)
- ✅ Server and all agents (2025-11-15)
- ✅ Console client UI (2025-11-17)
- ✅ All tests passing (126 tests, 3 skipped)
- ✅ Zero asyncio legacy code remaining

**Documentation**: See `TRIO_FINAL_STATUS.md` for comprehensive details

The entire application now uses **Trio's structured concurrency**. This provides:
- Automatic task supervision and cleanup
- No orphaned tasks possible
- Proper error propagation across task boundaries
- Deterministic shutdown behavior
- Simplified code (eliminated ~50 lines of manual cleanup)

**Stack**:
- **Server**: Quart (Flask-like) + Hypercorn (ASGI server with Trio support)
- **WebSocket**: Quart's built-in WebSocket with `trio.open_nursery()` for structured concurrency
- **Console Client**: `trio-websocket` for WebSocket connections, `httpx` for HTTP API calls
- **Database**: TrioDatabaseService with `trio.to_thread.run_sync()` for SQLite operations
- **Agents**: All 6 agents using Trio (`trio_*_agent.py`)
- **Orchestration**: Complete Trio-based workflow engine and conversation manager
- **Testing**: pytest-trio (126 tests passing, 3 skipped)

**Entry Points**:
- **Server**: `src/server.py` → `src/trio_server.py`
- **Console Client**: `console-ui/main.py` → `console-ui/src/console_client.py`

**Key Trio Patterns**:
```python
# Structured concurrency with nurseries
async def handle_request():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(task1)
        nursery.start_soon(task2)
    # Both tasks guaranteed to complete or be cancelled

# Blocking operations delegated to threads
result = await trio.to_thread.run_sync(blocking_function, arg1, arg2)
```

**Agent Integration**:
- Orchestrator creates and caches agent instances per user
- Agents return `AgentResponse` with content and next state
- Automatic state transitions based on agent responses
- All agents use `trio.to_thread.run_sync()` for LLM/RAG calls

**Testing Trio Code**:
```bash
# Run Trio tests only
pytest tests/integration/test_trio_*.py -v -m trio

# Run specific Trio test
pytest tests/integration/test_trio_orchestration.py::test_full_orchestration_flow -v

# Run console UI tests
pytest tests/integration/test_console_ui_patient_flow.py -v
```

## Configuration

- **Environment**: Requires Google Gemini API key in `.env` file
- **Database**: SQLite at `data/psychoanalyst.db`
- **Vector DB**: ChromaDB at `data/vector_db/`
- **Domain Knowledge**: Markdown files in `data/domain_knowledge/`

## Console Client

The console client (`console-ui/`) provides a Trio-based terminal interface for patients to interact with the therapy system.

**Architecture**:
- **Runtime**: Pure Trio (structured concurrency)
- **WebSocket**: `trio-websocket` library (matches server implementation)
- **HTTP**: `httpx.AsyncClient` for REST API calls
- **User Input**: Non-blocking via `trio.to_thread.run_sync(input, ...)`
- **Resource Management**: Automatic cleanup via context managers

**Features**:
- Real-time streaming responses from therapist
- Automatic reconnection handling
- Session state management
- Typing indicators
- Error handling with graceful degradation

**Running**:
```bash
cd console-ui
python main.py
```

**Dependencies**:
- `trio>=0.32.0`: Structured concurrency runtime
- `trio-websocket>=0.12.2`: WebSocket client
- `httpx>=0.28.1`: HTTP client

## Code Standards

The project follows strict code quality standards defined in `.clinerules/`:
- **Formatting**: Black with 88-character line length
- **Linting**: Ruff with comprehensive rule set
- **Type Checking**: mypy with strict settings
- **Testing**: pytest with fixtures and mocking
- **Documentation**: Google-style docstrings

## Testing Philosophy

This project uses a **hybrid testing approach**:

### DevContainer Testing (Primary)
- **Purpose**: Fast iteration during active development
- **Environment**: VSCode devContainer with pytest
- **Usage**: TDD workflows, debugging, quick validation
- **Benefits**: Instant feedback, IDE integration, debugger support
- **Commands**: `make test-dev`, `make test`, `pytest`

### Docker Isolated Testing (Validation)
- **Purpose**: Pre-commit validation and CI/CD
- **Environment**: Isolated Docker container with read-only mounts
- **Usage**: Before commits, CI/CD pipelines, clean-room testing
- **Benefits**: Complete isolation, guaranteed clean state, prevents test pollution
- **Commands**: `make test-validate`, `make docker-test`

### Recommended Workflow
1. **Development**: Run tests in devContainer (`make test-dev`) for instant feedback
2. **Debugging**: Use VSCode Test Explorer and debugger
3. **Before Commit**: Run isolated tests (`make test-validate`)
4. **Automation**: Install pre-commit hooks (`make install-hooks`)

### Pre-Commit Hooks
Install automated testing that runs before every commit:
```bash
make install-hooks
```

This runs the full test suite in isolated Docker before allowing commits, ensuring code quality.

## User Status Flow

The application manages state through `UserStatus` enum:
- `PROFILE_ONLY`: New user, needs intake
- `INTAKE_COMPLETE`: Intake done, needs assessment  
- `PLAN_COMPLETE`: Ready for therapy sessions

Sessions are resumable - the application detects existing state and continues from the appropriate point.

## Style System

Therapy styles are modular and located in `src/styles/`. Each style contains:
- `description.txt`: Style overview
- `knowledge.md`: Theoretical knowledge for RAG
- `*_prompt.txt`: Agent-specific prompts

Currently implemented: Freud, Jung, CBT.
