# Virtual LLM-Driven Psychoanalyst

A sophisticated therapeutic application that provides terminal-based and web-based psychoanalytic experiences using Large Language Models and Retrieval-Augmented Generation (RAG). Built on a clean **orchestration-based architecture** with **real-time streaming** responses, the system offers personalized therapy sessions with multiple therapeutic approaches including Freudian, Jungian, and Cognitive Behavioral Therapy styles.

## ✨ What's New (v2.0 - Orchestration Architecture)

The system has been completely redesigned with a clean architecture that separates business logic from I/O concerns:

- **🚀 Real-Time Streaming**: LLM responses stream chunk-by-chunk for immediate feedback
- **🎯 Orchestration Layer**: Central coordination of all therapy workflows
- **🔄 State Machine**: Explicit workflow states with validated transitions
- **🌐 Unified API**: All clients (web, console, local) use the same backend
- **📦 Pure Business Logic**: Agents are now testable, reusable components
- **🧪 Comprehensive Tests**: 1,900+ lines of unit and integration tests
- **📚 Complete Documentation**: Architecture guide, quick start, and API reference

## 🎯 Features

- **Triple Interface Support**: Choose between standalone terminal, networked console, or modern React web interface
- **Streaming Responses**: Real-time word-by-word responses for natural conversation flow
- **Agent-Based Workflow**: Sequential therapeutic process (Intake → Assessment → Sessions → Reflection)
- **RAG-Enhanced Responses**: Context-aware therapy using domain knowledge and ChromaDB vector storage
- **Multiple Therapy Styles**: Freudian, Jungian, and CBT approaches with style-specific prompts
- **Session Continuity**: Resume sessions across different interfaces with shared database
- **WebSocket + REST API**: Real-time bidirectional communication with HTTP fallback
- **Secure Data Persistence**: SQLite database with immutable session records
- **Local & Private**: All data stored locally on your machine

## 🏗️ Architecture (v2.0)

### Orchestration Layer
- **WorkflowEngine**: State machine managing therapy workflow transitions
- **ConversationManager**: Handles streaming, context, and RAG integration
- **AgentOrchestrator**: Coordinates agents and routes messages

### Gateway Layer
- **WebSocketGateway**: Real-time bidirectional communication with streaming
- **REST API**: HTTP endpoints for session management and user operations

### Agent Layer (Pure Business Logic)
- **IntakeAgent**: Gathers initial user information and preferences
- **AssessmentAgent**: Analyzes intake data and recommends optimal therapy styles
- **PsychoanalystAgent**: Conducts main conversational therapeutic sessions
- **ReflectionAgent**: Updates therapy plans based on session outcomes and progress

### Service Layer
- **DatabaseService**: SQLite-based persistence for sessions and user profiles
- **LLMService**: Google Gemini API integration with streaming support
- **RAGService**: ChromaDB-powered knowledge retrieval for contextual responses
- **StyleService**: Manages therapy style configurations and prompts

### Workflow States
```
NEW → INTAKE_IN_PROGRESS → INTAKE_COMPLETE
  → ASSESSMENT_IN_PROGRESS → ASSESSMENT_COMPLETE
  → THERAPY_IN_PROGRESS → REFLECTION_IN_PROGRESS
  → PLAN_COMPLETE → THERAPY_IN_PROGRESS (cycle)
```

**See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed documentation**

## 📋 Prerequisites

### Environment Setup
1. **Google Gemini API Key**: Required for LLM functionality
   ```bash
   # Create .env file in project root
   echo "GOOGLE_API_KEY=your_api_key_here" > .env
   ```
   Get your API key from [Google AI Studio](https://aistudio.google.com/)

2. **Docker**: Required for web interface (optional for CLI)

## 🎨 Choosing Your Interface

This application supports **three interface modes**, each optimized for different use cases:

### 🖥️ **1. Standalone Terminal UI**
**Best for**: Quick local use, development, single-user sessions

**Characteristics**:
- Direct Python execution (no Docker needed)
- Single process, runs entirely locally
- Fastest startup time
- Access via direct terminal I/O

**How to run**:
```bash
# Normal mode (45 min sessions, production database)
python src/main.py
# OR
make ui-standalone

# Usertest mode (10 min sessions, test database)
make ui-standalone-test
```

---

### 💻 **2. Console UI Service**
**Best for**: Testing WebSocket communication, networked architecture, multi-user scenarios

**Characteristics**:
- WebSocket-based terminal client
- Networked architecture with separate API server
- Terminal interface but with client-server separation
- Tests the same infrastructure used by web UI

**How to run**:
```bash
# Normal mode
make ui-console

# Usertest mode
make ui-console-test
```

**Access**: Terminal client connects automatically to API server

---

### 🌐 **3. Web UI**
**Best for**: End users, modern experience, PWA features

**Characteristics**:
- React-based browser interface
- Progressive Web App (PWA) capabilities
- Material-UI design system
- Real-time WebSocket communication

**How to run**:
```bash
# Normal mode
make ui-web

# Usertest mode
make ui-web-test
```

**Access**: Open browser to http://localhost:5173

---

### 🎯 **Run All Modes Simultaneously**
For development or comparison testing:

```bash
# Normal mode
make ui-all

# Usertest mode
make ui-all-test
```

---

### 🔄 **Interactive Launcher**
Not sure which mode to use? Run the interactive launcher:

```bash
./start.sh
```

The launcher will guide you through:
1. Selecting UI mode (standalone, console, web, or all)
2. Choosing environment (normal or usertest)
3. Starting the appropriate services

---

### 📊 **Normal vs Usertest Mode**

| Feature | Normal Mode | Usertest Mode |
|---------|------------|---------------|
| **Configuration** | `.env` | `.env.usertest` |
| **Session Duration** | 45 minutes | 10 minutes |
| **Database** | `psychoanalyst.db` | `psychoanalyst_usertest.db` |
| **Vector DB** | `vector_db/` | `vector_db_usertest/` |
| **Use Case** | Production, real sessions | Testing, experimentation |
| **Log Level** | INFO | DEBUG |

---

### 🗺️ **Quick Reference Table**

| What You Want | Command | Notes |
|---------------|---------|-------|
| Quick local test | `python src/main.py` | No Docker, fastest |
| Test WebSocket | `make ui-console` | Terminal with networking |
| Use web interface | `make ui-web` | Browser-based |
| Try everything | `make ui-all` | All UIs at once |
| Short test sessions | `make ui-*-test` | Any mode + usertest |
| Guided setup | `./start.sh` | Interactive menu |

---

## 🖥️ Standalone Terminal UI (Detailed)

### Quick Start
```bash
cd /app
python src/main.py
```

### Alternative Methods
```bash
# Using Make
make run

# Using Docker Compose
make docker-run
# OR
docker-compose run --rm app python src/main.py
```

### Development Setup
```bash
make dev-install    # Install development dependencies
make sync          # Sync environment with requirements
```

## 🌐 Web Interface (React-Based)

### Quick Start

#### Development Mode (Recommended for Development)
```bash
cd /app
./todos/start-web-development.sh
```
**Access at**: http://localhost:5173

#### Production Mode
```bash
cd /app
./todos/start-web-production.sh
```
**Access at**: http://localhost:3000

#### Stop Services
```bash
./todos/stop-web.sh
```

### Alternative Methods

#### Using Make Commands
```bash
cd /app

# Development mode with hot reload
make -f todos/Makefile.web web-dev

# Production mode
make -f todos/Makefile.web web-prod

# Stop all services
make -f todos/Makefile.web web-stop

# View logs
make -f todos/Makefile.web web-logs
```

#### Direct Docker Compose
```bash
# Development
docker-compose -f todos/docker-compose.web-dev.yml up --build

# Production
docker-compose -f todos/docker-compose.web.yml up --build
```

### Web Interface Access Points
- **Frontend (Dev)**: http://localhost:5173 - React development server with hot reload
- **Frontend (Prod)**: http://localhost:3000 - Nginx-served optimized build
- **API Server**: http://localhost:8000 - REST endpoints for session management
- **Unified Server**: http://localhost:8000 - REST API + WebSocket real-time communication

### Web Architecture
- **Frontend**: React 18 + TypeScript + Vite + Material-UI
- **Features**: Progressive Web App (PWA), real-time WebSocket communication
- **Backend**: FastAPI REST server + WebSocket server
- **Integration**: Shared SQLite database with terminal interface

## 🔧 Development Commands

### Code Quality
```bash
make format         # Format code with black
make lint           # Lint with ruff  
make test           # Run all tests
make test-unit      # Unit tests only
make test-integration  # Integration tests only
```

### Dependency Management
```bash
make requirements   # Generate locked requirements
pip-compile requirements.in      # Update production deps
pip-compile requirements-dev.in  # Update dev deps
```

## 🧪 Testing

The project provides multiple testing workflows for different purposes.

### Testing Philosophy: Hybrid Approach

This project uses a **hybrid testing strategy** that balances speed and reliability:

1. **DevContainer Testing** (90% of tests) - Fast iteration during development
2. **Docker Isolated Testing** (10% of tests) - Pre-commit validation and CI/CD

### DevContainer Testing (Active Development)

**For daily development work:**

```bash
# Quick tests in devContainer (RECOMMENDED for development)
make test-dev

# Run all tests
make test

# Run specific test types
make test-unit          # Unit tests only
make test-integration   # Integration tests only

# Run specific test file
pytest tests/unit/test_db_service.py -v

# Run with coverage
pytest --cov=src --cov-report=html

# Debug tests (use VSCode Test Explorer)
# - Tests auto-discover on save
# - Set breakpoints and debug interactively
# - See test results in sidebar
```

**Why devContainer for development?**
- ⚡ **Instant feedback**: No Docker build time
- 🐛 **Easy debugging**: VSCode debugger integration
- 🔄 **TDD-friendly**: Run tests every few minutes
- 📊 **Test Explorer**: Visual test runner in VSCode

### Docker Isolated Testing (Pre-Commit & CI/CD)

**For validation before commits:**

```bash
# Full isolated test suite (recommended before committing)
make test-validate

# Or use the docker-test command directly
make docker-test

# Run specific test in Docker
make docker-test-one TEST=tests/unit/test_db_service.py

# Reset test database
make docker-test-reset
```

**Why Docker for validation?**
- 🔒 **Complete isolation**: Clean environment every time
- 🛡️ **Prevents pollution**: Read-only source mounts
- ✅ **Pre-commit ready**: Automated testing before commits
- 🤖 **CI/CD compatible**: Perfect for GitHub Actions

### Setting Up Pre-Commit Hooks

Automatically run tests before every commit:

```bash
# Install the pre-commit hook
make install-hooks

# Now every commit will:
# 1. Run full test suite in isolated Docker
# 2. Block commit if tests fail
# 3. Ensure code quality

# To skip the hook (not recommended):
git commit --no-verify
```

### User Testing Mode (Manual Testing)

When you want to manually test the application with test settings (shorter sessions, separate database):

**Option 1: Local execution with test environment**
```bash
# Set up .env.usertest first (copy from .env.example and add your API key)
APP_ENV=testing python src/main.py
```

**Option 2: Docker user-test mode (RECOMMENDED)**
```bash
# Start app in user-test mode
make docker-usertest

# This provides:
# - Separate test database: data/psychoanalyst_usertest.db
# - Shorter session duration: 10 minutes (vs 45 min production)
# - Debug logging enabled
# - No impact on production data
```

**Configure user-test mode:**
1. Copy your API key to `.env.usertest`:
   ```bash
   # Edit .env.usertest and set:
   GEMINI_API_KEY=your_actual_api_key_here
   ```
2. Adjust test settings if needed (session duration, logging, etc.)

### Clean Test Data

```bash
# Clean all test databases
make clean-testdb

# Clean everything including caches
make clean
```

### When to Use What

| Scenario | Command | Why |
|----------|---------|-----|
| **Active development (TDD, debugging)** | `make test-dev` | Instant feedback in devContainer |
| **Run all tests locally** | `make test` | Full test suite in devContainer |
| **Pre-commit validation** | `make test-validate` | Isolated Docker environment |
| **CI/CD pipeline** | `make docker-test` | Same as test-validate |
| **Manually test with shorter sessions** | `make docker-usertest` | Real app with test settings |
| **Quick manual test without Docker** | `APP_ENV=testing python src/main.py` | Lightweight, fast startup |
| **Install automated testing on commits** | `make install-hooks` | Set up pre-commit hooks |
| **Clean test data** | `make clean-testdb` | Remove test databases |

### Recommended Workflow

```
┌─────────────────────────────────────────────────────────┐
│                   Development Cycle                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  1. Write code in VSCode devContainer                   │
│     ↓                                                    │
│  2. Run tests in devContainer (make test-dev)           │
│     ↓                                                    │
│  3. Debug failures with VSCode debugger                 │
│     ↓                                                    │
│  4. Repeat until all tests pass                         │
│     ↓                                                    │
│  5. Before commit: make test-validate                   │
│     ↓                                                    │
│  6. If tests pass → git commit                          │
│                                                          │
└─────────────────────────────────────────────────────────┘

With pre-commit hooks installed (make install-hooks):
  Step 5 happens automatically!
```

### Test Configuration Files

- `.env.test` - Automated testing (pre-configured for pytest)
- `.env.usertest` - Manual testing mode (copy your API key here)
- `pytest.ini` - Pytest configuration and markers

### Test Structure

```
tests/
├── unit/               # Fast, isolated unit tests
│   ├── test_db_service.py
│   ├── test_llm_service.py
│   └── ...
├── integration/        # End-to-end integration tests
│   ├── test_complete_session_flow.py
│   └── ...
└── conftest.py        # Shared pytest fixtures
```

## 📊 User Workflow

### Status Progression
1. **PROFILE_ONLY**: New user → Intake process
2. **INTAKE_COMPLETE**: Assessment to recommend therapy style  
3. **PLAN_COMPLETE**: Ready for therapeutic sessions

### Session Types
- **Initial Intake**: Gather background, preferences, therapeutic goals
- **Style Assessment**: Analyze intake data, recommend Freud/Jung/CBT approach
- **Therapy Sessions**: Ongoing conversations with chosen therapeutic style
- **Reflection Updates**: Agent updates therapy plan based on session progress

## 🤝 Interface Switching

Both interfaces share the same SQLite database, enabling seamless switching:

1. **Start session in CLI**: `python src/main.py`
2. **Switch to web**: Access http://localhost:5173 (same user profile)
3. **Resume conversations**: All session history maintained
4. **Switch back to CLI**: Full continuity preserved

## 🏥 Therapy Styles

Each style includes specialized prompts and knowledge bases:

- **Freudian**: Classical psychoanalysis, unconscious exploration, dream analysis
- **Jungian**: Analytical psychology, archetypes, individuation process  
- **CBT**: Cognitive behavioral therapy, thought patterns, practical techniques

Style selection occurs during assessment phase and can be updated through reflection.

## 🗂️ Project Structure

```
/app/
├── src/                        # Core application code
│   ├── agents/                # Therapeutic agents (Intake, Assessment, etc.)
│   ├── services/              # Service layer (DB, LLM, RAG, Style)
│   ├── models/                # Pydantic data models
│   ├── styles/                # Therapy style configs and prompts
│   ├── ui/                    # User interface implementations
│   ├── unified_server.py      # Unified HTTP + WebSocket server
│   ├── server.py              # Server entry point
│   └── main.py                # CLI application entry point
├── frontend/                   # React web application
│   ├── src/                   # React components and logic
│   ├── Dockerfile             # Production frontend container
│   ├── Dockerfile.dev         # Development frontend container
│   └── nginx.conf             # Production web server config
├── tests/                      # Test suite (unit + integration)
├── data/                      # Runtime data directory
│   ├── psychoanalyst.db       # SQLite database
│   ├── vector_db/             # ChromaDB vector storage
│   └── domain_knowledge/       # Therapeutic knowledge base
├── todos/                     # Web interface deployment configs
│   ├── docker-compose.web*.yml
│   ├── start-web-*.sh
│   └── Makefile.web
└── .env                       # Environment variables
```

## 🔍 Troubleshooting

### General Issues
```bash
# Check Docker status
docker info

# Check port availability  
netstat -tulpn | grep -E ':(3000|5173|8000)'

# View service logs
make -f todos/Makefile.web web-logs
```

### Web Interface Issues
```bash
# Test API connectivity
curl http://localhost:8000/health

# Rebuild frontend with no cache
docker-compose -f todos/docker-compose.web-dev.yml build frontend-dev --no-cache

# Permission fixes
chmod +x todos/*.sh
```

### Database Issues
```bash
# Check database directory
ls -la data/

# Reset database (removes all data)
rm -f data/psychoanalyst.db
```

### Test Mode
See the [Testing](#-testing) section above for comprehensive testing documentation.

Quick reference:
```bash
# Automated tests
make test

# Manual testing with test settings
make docker-usertest
```

## 📈 Next Steps

1. **First Run**: Start with CLI interface: `python src/main.py`
2. **Web Experience**: Launch web interface: `./todos/start-web-development.sh`
3. **Explore Styles**: Try different therapeutic approaches during assessment
4. **Integration Testing**: Switch between interfaces during active sessions
5. **Production Deployment**: Use production web mode for stable hosting

## 📚 Documentation

Comprehensive documentation is available in the `docs/` directory:

- **[Architecture Guide](docs/ARCHITECTURE.md)**: Deep dive into system design, orchestration layer, agents, and data flow
- **[Quick Start Guide](docs/QUICKSTART.md)**: Get up and running in minutes with step-by-step instructions
- **[Development Guide](CLAUDE.md)**: Contributing, testing, and development workflows
- **API Reference**: REST and WebSocket API documentation (see Architecture Guide)

### Key Topics

- **Orchestration Architecture**: How the workflow engine, conversation manager, and agent orchestrator work together
- **Streaming Responses**: Real-time LLM output delivery
- **State Machine**: Workflow states and valid transitions
- **RAG Integration**: How domain knowledge enhances therapy sessions
- **Testing**: Comprehensive test suite with 1,900+ lines of tests
- **Deployment**: Production setup and scaling considerations

## 🆘 Support

- **Health Checks**: http://localhost:8000/health
- **Clean Reset**: `make -f todos/Makefile.web web-clean`
- **Terminal Fallback**: `python src/main.py` always available
- **Logs**: `make -f todos/Makefile.web web-logs`

---

*This application provides a unique combination of traditional psychoanalytic approaches with modern AI capabilities, offering users flexibility in how they engage with therapeutic content while maintaining professional therapeutic frameworks and data continuity.*
