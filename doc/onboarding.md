# Virtual LLM-Driven Psychoanalyst - Developer Onboarding Guide

## Table of Contents
1. [Project Overview](#project-overview)
2. [Architecture & Design Approach](#architecture--design-approach)
3. [Project Structure](#project-structure)
4. [Core Components](#core-components)
5. [Data Models & Persistence](#data-models--persistence)
6. [Agent System](#agent-system)
7. [Services Layer](#services-layer)
8. [Development Workflow](#development-workflow)
9. [Testing](#testing)
10. [Deployment & Setup](#deployment--setup)
11. [Extending the Application](#extending-the-application)

## Project Overview

The Virtual LLM-Driven Psychoanalyst is a sophisticated application that simulates a psychotherapy experience using Large Language Models (LLMs) and Retrieval-Augmented Generation (RAG) techniques. The application provides a personalized, context-aware conversational experience that evolves over multiple sessions.

### Key Features
- **Multi-Agent Architecture**: Distinct agents handle different phases of the therapeutic process
- **Personalized Experience**: User profiles with name, birthdate, and profession for tailored interactions
- **Persistent Memory**: SQLite database stores session history and therapy plans
- **Domain Knowledge Integration**: RAG system incorporates psychological theories (Freud, Jung)
- **Local & Private**: All data remains on the user's machine
- **Dockerized Deployment**: Consistent environment across development and production

## Architecture & Design Approach

### Multi-Agent System
The application follows a multi-agent architecture where each agent has a specific responsibility:
- **Intake Agent**: Handles initial user interaction and profile collection
- **Psychoanalyst Agent**: Conducts the main therapeutic conversations
- **Reflection Agent**: Analyzes sessions and creates/refines therapy plans

### Data-Driven Design
All components are designed around well-defined data models using Pydantic, ensuring type safety and clear data contracts between components.

### Service-Oriented Architecture
Core functionality is encapsulated in reusable services:
- **LLM Service**: Abstracts LLM interactions
- **Database Service**: Handles all data persistence
- **RAG Service**: Manages domain knowledge retrieval

### Separation of Concerns
Each module has a single responsibility, making the system modular and maintainable.

### UI Abstraction Architecture
The application uses an abstract UI layer to decouple the presentation logic from the core application logic. This design allows for multiple UI implementations while maintaining a consistent interface:

- **`BaseUI`**: Abstract base class defining the UI interface contract
- **`TextualUI`**: Concrete implementation using the Textual framework for enhanced terminal interaction
- **Future UIs**: New implementations can be added by inheriting from `BaseUI`

This abstraction enables swapping UI implementations without modifying agent or service code.

## Project Structure

```
psychoanalyst_app/
├── doc/                           # Documentation (this file)
├── src/                           # Source code
│   ├── main.py                    # Application entry point
│   ├── config.py                  # Configuration management
│   ├── agents/                    # Agent implementations
│   │   ├── intake_agent.py        # Initial user interaction
│   │   ├── psychoanalyst_agent.py # Main conversation logic
│   │   └── reflection_agent.py    # Plan analysis and refinement
│   ├── services/                  # Core services
│   │   ├── llm_service.py         # LLM abstraction
│   │   ├── db_service.py          # Database operations
│   │   └── rag_service.py         # RAG system management
│   ├── ui/                        # User interface implementations
│   │   ├── __init__.py            # UI package init
│   │   ├── base_ui.py             # Abstract UI base class
│   │   └── textual_ui.py          # Textual TUI implementation
│   ├── utils/                     # Utility functions and models
│   │   ├── data_models.py         # Pydantic data models
│   │   └── embedding_utils.py     # Text embedding utilities
│   └── data/                      # Data storage
│       ├── domain_knowledge/      # Psychological theory markdown files
│       ├── vector_db/             # ChromaDB vector database
│       └── psychoanalyst.db       # SQLite session database
├── tests/                         # Unit and integration tests
├── Dockerfile                     # Docker image definition
├── docker-compose.yml             # Docker orchestration
├── requirements.txt               # Python dependencies
└── .env                           # Environment variables
```

## Core Components

### Main Application (`src/main.py`)
The entry point orchestrates the entire application flow:
1. Initializes all services
2. Checks for existing therapy plans
3. Routes to appropriate workflow (intake or session)
4. Manages the session loop

### Configuration (`src/config.py`)
Centralized configuration management using environment variables:
- Loads `.env` file for API keys and paths
- Defines database and vector database locations
- Manages application metadata

## Data Models & Persistence

### Pydantic Models (`src/utils/data_models.py`)
Strongly-typed data structures ensure data integrity:

#### UserProfile
```python
class UserProfile(BaseModel):
    user_id: str
    name: str
    birthdate: Optional[datetime] = None
    profession: Optional[str] = None
    created_at: datetime
    updated_at: datetime
```

#### Message
```python
class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
```

#### Session
```python
class Session(BaseModel):
    session_id: str
    user_id: str
    timestamp: datetime
    transcript: List[Message]
```

#### TherapyPlan
```python
class TherapyPlan(BaseModel):
    plan_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    plan_details: Dict[str, Any]
    version: int
```

#### DomainKnowledgeChunk
```python
class DomainKnowledgeChunk(BaseModel):
    id: str
    content: str
    source: str
    embedding: Optional[List[float]] = None
```

### Database Service (`src/services/db_service.py`)
SQLite-based persistence layer with the following tables:

#### Sessions Table
- `session_id` (TEXT, Primary Key)
- `user_id` (TEXT)
- `timestamp` (TEXT)
- `transcript` (TEXT - JSON serialized)

#### Therapy Plans Table
- `plan_id` (TEXT, Primary Key)
- `user_id` (TEXT)
- `created_at` (TEXT)
- `updated_at` (TEXT)
- `plan_details` (TEXT - JSON serialized)
- `version` (INTEGER)

#### User Profiles Table
- `user_id` (TEXT, Primary Key)
- `name` (TEXT, Not Null)
- `birthdate` (TEXT, Optional)
- `profession` (TEXT, Optional)
- `created_at` (TEXT, Not Null)
- `updated_at` (TEXT, Not Null)

## Agent System

### Intake Agent (`src/agents/intake_agent.py`)
**Responsibility**: First-time user interaction and profile collection

#### Key Methods:
- `_collect_user_profile()`: Interactive profile collection
- `conduct_intake()`: Initial conversation session

#### Workflow:
1. Collect user profile information (name, birthdate, profession)
2. Store profile in database
3. Conduct initial therapeutic conversation
4. Save session to database

### Psychoanalyst Agent (`src/agents/psychoanalyst_agent.py`)
**Responsibility**: Main therapeutic conversation sessions

#### Key Methods:
- `conduct_session(therapy_plan)`: Session conversation loop

#### Workflow:
1. Retrieve user profile for personalization
2. Load therapy plan and domain knowledge
3. Conduct personalized conversation
4. Save session to database

### Reflection Agent (`src/agents/reflection_agent.py`)
**Responsibility**: Session analysis and therapy plan management

#### Key Methods:
- `create_initial_plan(intake_session)`: Generate first therapy plan
- `update_plan(session, current_plan)`: Refine existing plan
- `generate_session_summary(session)`: Create session summaries

#### Workflow:
1. Analyze session transcripts
2. Retrieve relevant domain knowledge
3. Generate or update therapy plans
4. Store plans in database

## Services Layer

### LLM Service (`src/services/llm_service.py`)
**Responsibility**: Abstract LLM interactions using LangChain

#### Key Methods:
- `generate_response(prompt, context)`: Basic LLM response generation
- `generate_structured_response(prompt, output_format)`: JSON-structured responses
- `create_prompt_template(template, input_variables)`: Prompt template management
- `run_prompt_chain(prompt_template, inputs)`: Template-based generation

#### Features:
- Google Gemini integration via LangChain
- Context-aware conversation handling
- Prompt template system for consistency

### RAG Service (`src/services/rag_service.py`)
**Responsibility**: Domain knowledge retrieval using ChromaDB

#### Key Methods:
- `_load_domain_knowledge()`: Initialize knowledge base
- `retrieve_relevant_knowledge(query, n_results)`: Find relevant content
- `get_knowledge_by_source(source)`: Retrieve by source file

#### Features:
- ChromaDB vector database integration
- Sentence transformer embeddings
- Domain knowledge chunking and storage

### Embedding Utilities (`src/utils/embedding_utils.py`)
**Responsibility**: Text embedding generation and similarity calculation

#### Key Methods:
- `generate_embedding(text)`: Single text embedding
- `generate_embeddings(texts)`: Multiple text embeddings
- `get_similarity(embedding1, embedding2)`: Cosine similarity

#### Features:
- SentenceTransformer model integration
- NumPy-based similarity calculations

## Development Workflow

### Setting Up Development Environment

1. **Clone Repository**:
   ```bash
   git clone <repository-url>
   cd psychoanalyst_app
   ```

2. **Environment Configuration**:
   ```bash
   cp .env.example .env
   # Edit .env with your Google Gemini API key
   ```

3. **Docker Development**:
   ```bash
   # Build and run
   docker-compose up --build
   
   # Interactive development
   docker-compose run --rm app python src/main.py
   ```

4. **Local Development** (without Docker):
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   python src/main.py
   ```

### Code Organization Guidelines

1. **New Agents**: Create in `src/agents/` with clear responsibility boundaries
2. **New Services**: Implement in `src/services/` for reusable functionality
3. **Data Models**: Add to `src/utils/data_models.py` with proper typing
4. **Configuration**: Use `src/config.py` for new settings
5. **Domain Knowledge**: Add markdown files to `src/data/domain_knowledge/`
6. **New UI Implementations**: Create in `src/ui/` following the `BaseUI` interface

## Testing

### Test Structure
Tests are organized in the `tests/` directory:
- `test_basic_functionality.py`: Core component tests
- `test_services.py`: Service layer tests
- `test_agents.py`: Agent behavior tests

### Running Tests

**Docker Environment**:
```bash
docker-compose run --rm app python -m pytest tests/
```

**Local Environment**:
```bash
python -m pytest tests/
```

### Test Coverage Areas
- Data model validation
- Database operations
- Service functionality
- Agent workflows
- Embedding utilities

## Deployment & Setup

### Prerequisites
- Docker and Docker Compose
- Google Gemini API key

### Production Deployment Steps

1. **Environment Setup**:
   ```bash
   # Create .env file
   echo "GOOGLE_API_KEY=your_api_key_here" > .env
   ```

2. **Build and Deploy**:
   ```bash
   docker-compose up -d
   ```

3. **Data Persistence**:
   - SQLite database: `src/data/psychoanalyst.db`
   - Vector database: `src/data/vector_db/`
   - Both are mounted as volumes for persistence

### Configuration Options
- **API Key**: Required for LLM functionality
- **Model Selection**: Configurable in `LLMService`
- **Database Paths**: Defined in `Config` class
- **Domain Knowledge**: Markdown files in `domain_knowledge/`

## Extending the Application

### Adding New Domain Knowledge
1. Add markdown files to `src/data/domain_knowledge/`
2. The RAG service automatically loads new content
3. Content is chunked and embedded for retrieval

### Creating New Agents
1. Create new agent class in `src/agents/`
2. Inherit from base agent pattern
3. Implement specific functionality
4. Integrate in `main.py` workflow

### Adding User Profile Fields
1. Update `UserProfile` model in `data_models.py`
2. Modify database schema in `db_service.py`
3. Update intake collection in `intake_agent.py`
4. Use new fields in relevant agents

### Customizing LLM Behavior
1. Modify prompts in agent classes
2. Adjust temperature and model parameters in `llm_service.py`
3. Create new prompt templates for consistency
4. Implement custom response parsing

### Enhancing RAG System
1. Improve chunking strategy in `rag_service.py`
2. Add new embedding models in `embedding_utils.py`
3. Implement advanced retrieval algorithms
4. Add user session history to RAG context

### Creating New UI Implementations
1. Create new UI class in `src/ui/` that inherits from `BaseUI`
2. Implement all abstract methods (`display_message`, `get_user_input`, `display_system_status`, `run`)
3. Update `src/main.py` to use the new UI implementation
4. Maintain the async interface for consistency with the TextualUI

## Best Practices

### Code Quality
- Use type hints consistently
- Follow existing naming conventions
- Maintain clear docstrings for all functions
- Keep functions focused on single responsibilities

### Data Management
- Always handle database connections properly
- Use transactions for multi-step operations
- Validate data before storage
- Implement proper error handling

### LLM Integration
- Design prompts for consistency
- Handle API errors gracefully
- Cache responses when appropriate
- Monitor token usage

### Security
- Never commit API keys
- Validate user inputs
- Sanitize database queries
- Protect sensitive user data

## Troubleshooting

### Common Issues

**API Key Errors**:
- Verify `.env` file contains valid key
- Check key has proper permissions
- Ensure key is not expired

**Database Issues**:
- Check file permissions on data directory
- Verify database file is not corrupted
- Ensure sufficient disk space

**Docker Problems**:
- Check Docker daemon is running
- Verify sufficient system resources
- Review container logs for errors

### Debugging Tips
- Use print statements for quick debugging
- Enable detailed logging in services
- Test components in isolation
- Use Docker logs for container issues

## Future Enhancements

### Planned Features
- Enhanced user record RAG implementation
- Advanced session analysis capabilities
- Multi-language support
- Web interface development
- Additional psychological frameworks

### Architecture Improvements
- Asynchronous processing for better performance
- Plugin system for extensible functionality
- Advanced analytics and reporting
- Integration with external APIs

This onboarding guide provides a comprehensive overview of the Virtual LLM-Driven Psychoanalyst application. New developers should start by understanding the multi-agent architecture and data flow, then explore individual components in detail.
