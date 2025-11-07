# Project Guidelines for Virtual LLM-Driven Psychoanalyst

## Core Architecture Principles

### 1. Modularity and Separation of Concerns

The application follows a strict separation of concerns with clearly defined module responsibilities:

- **`src/agents/`**: Contains the core application logic and workflow orchestration. Each agent has a specific, well-defined role.
- **`src/services/`**: Handles specific, isolated tasks (e.g., database queries, LLM calls, RAG operations). These are the "tools" used by agents.
- **`src/ui/`**: Manages all user interaction, completely decoupled from core logic.
- **`src/models/`**: Defines data structures used throughout the application.
- **`src/config/`**: Provides configuration settings.
- **`src/styles/`**: Contains self-contained modules for different therapeutic approaches.

### 2. Agent Responsibilities

Each agent has a distinct role in the therapy workflow:

- **`IntakeAgent`**: Handles the initial user interaction to gather baseline information.
- **`AssessmentAgent`**: Analyzes intake data to recommend therapy styles and create initial plans.
- **`PsychoanalystAgent`**: Conducts the main conversational sessions based on the therapy plan.
- **`ReflectionAgent`**: Updates and refines the therapy plan based on session outcomes.

Agents should not directly interact with external systems; they must use appropriate services.

### 3. Service Abstractions

All interactions with external systems (LLM APIs, databases, vector stores) must go through dedicated services in `src/services/`. This ensures:
- Testability through mocking
- Consistent error handling
- Clear separation of concerns
- Reusability across agents

### 4. Data Immutability

Session transcripts stored in the database are immutable records. They should never be modified after creation. Any analysis or updates should be stored in separate records or fields.

### 5. State Management

The application uses `UserStatus` to manage workflow state:
- `PROFILE_ONLY`: New user, no data exists
- `INTAKE_COMPLETE`: Intake session completed, needs assessment
- `PLAN_COMPLETE`: Therapy plan exists, ready for sessions

Agents should check the current status and handle resumption appropriately.

## Docker Usage Guidelines

### Dockerfile
- Defines the base application environment
- Installs Python dependencies
- Sets up the working directory
- Declares volumes for persistent data

### docker-compose.yml
- Orchestrates the application service
- Mounts data volumes for SQLite and vector database persistence
- Loads environment variables from `.env`

### Running the Application
```bash
# Build and start the application
docker-compose up --build

# Run in detached mode
docker-compose up -d

# Stop the application
docker-compose down
```

## Logging and Error Handling

### Structured Logging
Use Python's `logging` module with appropriate levels (DEBUG, INFO, WARNING, ERROR) for consistent, searchable logs.

### Custom Exceptions
Define and use custom exception classes for specific error conditions to enable granular error handling.

## Security Considerations

- Never commit `.env` files containing API keys
- Use environment variables for all sensitive configuration
- Validate and sanitize all user inputs
