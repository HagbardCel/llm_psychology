# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

# Testing
make test                 # Run all tests
make test-unit            # Run unit tests only
make test-integration     # Run integration tests only
pytest -v                 # Run tests with verbose output
pytest tests/unit/test_db_service.py  # Run specific test file

# Running the application
make run                  # Run locally with Python
make docker-run           # Run with Docker Compose
docker-compose run --rm app python src/main.py  # Interactive mode

# Build and dependency management
make requirements         # Generate locked requirements from .in files
pip-compile requirements.in  # Update production dependencies
pip-compile requirements-dev.in  # Update development dependencies
```

### Docker Commands

```bash
docker-compose up --build    # Build and start application
docker-compose run --rm app python src/main.py  # Run interactively
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
- `src/agents/`: Core agent implementations
- `src/services/`: Service layer abstractions
- `src/models/`: Pydantic data models
- `src/styles/`: Therapy style configurations with prompts and knowledge
- `src/ui/`: User interface implementations
- `tests/`: Comprehensive test suite with unit and integration tests

## Configuration

- **Environment**: Requires Google Gemini API key in `.env` file
- **Database**: SQLite at `data/psychoanalyst.db`
- **Vector DB**: ChromaDB at `data/vector_db/`
- **Domain Knowledge**: Markdown files in `data/domain_knowledge/`

## Code Standards

The project follows strict code quality standards defined in `.clinerules/`:
- **Formatting**: Black with 88-character line length
- **Linting**: Ruff with comprehensive rule set
- **Type Checking**: mypy with strict settings
- **Testing**: pytest with fixtures and mocking
- **Documentation**: Google-style docstrings

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