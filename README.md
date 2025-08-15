# Virtual LLM-Driven Psychoanalyst App

This application provides a virtual psychoanalyst experience, running locally in your terminal. It uses Large Language Models (LLMs) and a Retrieval-Augmented Generation (RAG) system to provide context-aware, personalized conversations.

## Features

- **Local & Private:** All data is stored locally on your machine.
- **Dockerized:** Easy setup and consistent environment.
- **Domain Knowledge RAG:** Utilizes a curated knowledge base of psychological theories.
- **Sequential Agent Workflow:** Employs distinct agents for intake, conversation, and reflection.

## Getting Started

### Prerequisites

- Docker and Docker Compose
- A Google Gemini API key (for now)

### Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd psychoanalyst_app
    ```

2.  **Configure Environment Variables:**
    Create a `.env` file in the project root and add your API key:
    ```env
    GOOGLE_API_KEY=your_actual_google_gemini_api_key_here
    ```
    **Important:** Replace `your_actual_google_gemini_api_key_here` with your real Google Gemini API key. You can get one from [Google AI Studio](https://aistudio.google.com/).

3.  **Build and Run with Docker:**
    ```bash
    docker-compose up --build
    ```

4.  **For Interactive Mode (to actually use the app):**
    ```bash
    docker-compose run --rm app python src/main.py
    ```

## Project Structure

```
psychoanalyst_app/
├── src/
│   ├── main.py                     # Main application entry point
│   ├── config.py                   # Configuration settings
│   ├── agents/
│   │   ├── intake_agent.py         # Handles initial user interaction
│   │   ├── psychoanalyst_agent.py  # Core conversational logic
│   │   └── reflection_agent.py     # Designs and refines the therapy plan
│   ├── services/
│   │   ├── llm_service.py          # Abstraction for LLM API calls
│   │   ├── db_service.py           # Handles all SQLite database operations
│   │   └── rag_service.py          # Orchestrates domain knowledge RAG
│   ├── utils/
│   │   ├── data_models.py          # Pydantic models for session data, plans, etc.
│   │   └── embedding_utils.py      # Functions for text embedding
│   └── data/
│       ├── domain_knowledge/       # Raw text files for psychological RAG
│       ├── vector_db/              # Local persistence for the vector database
│       └── psychoanalyst.db        # SQLite database file
├── tests/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env
```

## How It Works

1.  **Initialization:** The application loads configuration, initializes services, and checks for an existing therapy plan.
2.  **Intake (First Run):** If no plan exists, the `IntakeAgent` gathers baseline information.
3.  **Reflection:** The `ReflectionAgent` analyzes the intake and creates the initial therapy plan.
4.  **Session Loop:**
    - The `PsychoanalystAgent` conducts the conversation, guided by the plan and domain knowledge RAG.
    - After the session, the `ReflectionAgent` updates the therapy plan based on the new conversation.
5.  **Data Persistence:** Sessions and therapy plans are stored in a local SQLite database.

## Development

This project follows modern Python development practices with structured guidelines and tooling.

### Modern Development Workflow

The project now includes comprehensive development tooling:

- **Dependency Management**: Uses `pip-tools` with `requirements.in` and `requirements-dev.in`
- **Code Formatting**: `black` for automatic code formatting
- **Linting**: `ruff` for fast, comprehensive linting
- **Type Checking**: `mypy` for static type checking
- **Testing**: `pytest` with proper fixtures and mocking strategies
- **Configuration**: `pydantic-settings` for robust configuration management

### Development Setup

This project includes a devcontainer configuration for consistent development environment. See [.devcontainer/README.md](.devcontainer/README.md) for setup instructions.

#### Devcontainer Improvements

The devcontainer has been optimized to prevent crashes:

- **Memory Management**: Removed memory limits that were causing container termination
- **Security**: Uses a non-root user (`appuser`) instead of root
- **Performance**: Includes a `.dockerignore` file to optimize build context
- **Startup Optimization**: Eliminated redundant dependency installation on every startup
- **Separation of Concerns**: Uses a dedicated `dev` service that stays running for development, separate from the application runtime

To use the improved devcontainer:

1. Open the project in VS Code with Remote - Containers extension installed
2. Run "Remote-Containers: Reopen in Container" from the Command Palette
3. The container will build and start with the optimized configuration

1.  **Create a virtual environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

2.  **Install development dependencies:**
    ```bash
    # Install pip-tools first
    pip install pip-tools
    
    # Install locked dependencies
    pip-sync requirements.txt requirements-dev.txt
    
    # Or generate and install from .in files
    make requirements
    make sync
    ```

3.  **Set up environment variables:**
    Create a `.env` file with your API key.

4.  **Development Commands:**
    ```bash
    # Format code
    make format
    
    # Lint code
    make lint
    
    # Run tests
    make test
    
    # Run the application
    make run
    ```

### Running Tests

```bash
# Run tests with pytest
make test

# Or directly
docker-compose run --rm app python -m pytest tests/
```

### Code Quality

The project enforces code quality through:

- **Structured Logging**: Using Python's `logging` module instead of `print()`
- **Custom Exceptions**: Specific exception classes for different error types
- **Type Hints**: Comprehensive type annotations throughout the codebase
- **Modular Architecture**: Clear separation of concerns with dedicated modules
- **Prompt Engineering Guidelines**: Standardized approach to LLM prompt management

### Project Structure

```
psychoanalyst_app/
├── src/
│   ├── main.py                     # Main application entry point
│   ├── config.py                   # Configuration settings (pydantic-settings)
│   ├── exceptions.py               # Custom exception classes
│   ├── models/                     # Data models (moved from utils)
│   ├── agents/                     # Core agent logic
│   │   ├── intake_agent.py         
│   │   ├── assessment_agent.py     
│   │   ├── psychoanalyst_agent.py  
│   │   └── reflection_agent.py     
│   ├── services/                   # Service layer
│   │   ├── llm_service.py          
│   │   ├── db_service.py           
│   │   ├── rag_service.py          
│   │   └── style_service.py        
│   ├── styles/                     # Therapy style configurations
│   ├── ui/                         # User interface
│   └── data/                       # Persistent data storage
├── tests/                          # Test suite
├── .clinerules/                    # AI collaboration guidelines
├── Dockerfile
├── docker-compose.yml
├── requirements.in                 # Direct dependencies
├── requirements-dev.in             # Development dependencies
├── requirements.txt                # Locked production dependencies
├── requirements-dev.txt            # Locked development dependencies
├── pyproject.toml                  # Tool configuration
├── Makefile                        # Development commands
└── .env
```

### AI Collaboration Guidelines

The project includes `.clinerules/` directory with guidelines for AI-assisted development:

- **rules.md**: General project architecture and Docker usage guidelines
- **prompt-engineering.md**: LLM prompt development best practices
- **python-style-guide.md**: Code formatting, linting, and style conventions

This ensures consistent, high-quality contributions whether working alone or with AI assistance.

## Troubleshooting

- **API Key Error:** Make sure you have a valid Google Gemini API key in your `.env` file.
- **Docker Permission Issues:** Make sure you have proper permissions to run Docker commands.
- **Port Conflicts:** If you see port conflicts, modify the `docker-compose.yml` file.
- **Devcontainer Crashes:** If the devcontainer crashes during startup:
  - Ensure you're using the latest configuration with optimized memory settings
  - Check that Docker has sufficient resources allocated (at least 4GB RAM recommended)
  - Try rebuilding the container with "Remote-Containers: Rebuild Container" command
  - Clear Docker cache if issues persist: `docker system prune -a`
