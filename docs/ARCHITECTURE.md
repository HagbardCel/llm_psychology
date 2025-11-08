# Architecture Documentation

## Overview

The Virtual LLM-Driven Psychoanalyst is a therapy application built on a clean, modular architecture that separates business logic from interface concerns. The system uses an **orchestration-based architecture** with streaming LLM responses for real-time user interactions.

## Architecture Principles

1. **Separation of Concerns**: Agents contain pure business logic; gateways handle I/O
2. **Unified API**: All client interfaces (local, console, web) use the same backend
3. **Streaming First**: Real-time streaming of LLM responses for better UX
4. **State Machine**: Workflow driven by explicit state transitions
5. **Scalability**: Designed to support multiple concurrent users

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Client Interfaces                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐     │
│  │  Local   │  │ Console  │  │  Web Frontend        │     │
│  │   CLI    │  │    UI    │  │  (React + Socket.IO) │     │
│  └──────────┘  └──────────┘  └──────────────────────┘     │
└──────────┬──────────┬─────────────────┬───────────────────┘
           │          │                 │
           ▼          ▼                 ▼
     ┌────────────────────────────────────────┐
     │      Unified Server (Port 8000)        │
     │  ┌──────────────────────────────────┐  │
     │  │     HTTP REST API Endpoints      │  │
     │  │   /api/user/*, /api/sessions/*   │  │
     │  └──────────────────────────────────┘  │
     │  ┌──────────────────────────────────┐  │
     │  │   WebSocket Server (Socket.IO)   │  │
     │  │   Real-time bidirectional comms  │  │
     │  └──────────────────────────────────┘  │
     └────────────────┬───────────────────────┘
                      │
                      ▼
     ┌────────────────────────────────────────┐
     │         WebSocket Gateway              │
     │  Handles: chat_message, session_start  │
     │  Streams: LLM responses chunk-by-chunk │
     └────────────────┬───────────────────────┘
                      │
                      ▼
     ┌────────────────────────────────────────┐
     │       Agent Orchestrator               │
     │  • Routes messages to agents           │
     │  • Manages workflow transitions        │
     │  • Coordinates streaming responses     │
     └───┬────────────┬───────────────┬───────┘
         │            │               │
         ▼            ▼               ▼
    ┌─────────┐ ┌──────────────┐ ┌──────────────┐
    │Workflow │ │Conversation  │ │Agent Factory │
    │ Engine  │ │  Manager     │ │ (Agents)     │
    └─────────┘ └──────────────┘ └──────────────┘
         │            │               │
         │            │               │
         ▼            ▼               ▼
    ┌──────────────────────────────────────────┐
    │          Service Layer                    │
    │  ┌──────────┐ ┌──────────┐ ┌──────────┐ │
    │  │Database  │ │   LLM    │ │   RAG    │ │
    │  │ Service  │ │ Service  │ │ Service  │ │
    │  └──────────┘ └──────────┘ └──────────┘ │
    └──────────────────────────────────────────┘
```

## Core Components

### 1. Orchestration Layer

The orchestration layer coordinates all therapy workflows and agent interactions.

#### WorkflowEngine (`src/orchestration/workflow_engine.py`)

**Purpose**: Manages the therapy workflow state machine

**Responsibilities**:
- Track user's current workflow state
- Validate state transitions
- Map states to appropriate agents
- Persist state changes to database

**Workflow States**:
```python
class WorkflowState(Enum):
    NEW = "new"                                    # New user
    INTAKE_IN_PROGRESS = "intake_in_progress"      # Collecting user info
    INTAKE_COMPLETE = "intake_complete"            # Ready for assessment
    ASSESSMENT_IN_PROGRESS = "assessment_in_progress"  # Analyzing needs
    ASSESSMENT_COMPLETE = "assessment_complete"    # Ready for therapy
    THERAPY_IN_PROGRESS = "therapy_in_progress"    # Active therapy session
    REFLECTION_IN_PROGRESS = "reflection_in_progress"  # Post-session reflection
    PLAN_COMPLETE = "plan_complete"                # Ready for next session
```

**State Transitions**:
```
NEW → INTAKE_IN_PROGRESS → INTAKE_COMPLETE
  → ASSESSMENT_IN_PROGRESS → ASSESSMENT_COMPLETE
  → THERAPY_IN_PROGRESS → REFLECTION_IN_PROGRESS
  → PLAN_COMPLETE → THERAPY_IN_PROGRESS (cycle)
```

#### ConversationManager (`src/orchestration/conversation_manager.py`)

**Purpose**: Manages conversation context and streaming responses

**Responsibilities**:
- Stream LLM responses chunk-by-chunk
- Maintain conversation context and history
- Integrate RAG (Retrieval-Augmented Generation)
- Manage session time and extensions
- Persist messages to database

**Key Features**:
- Real-time streaming of LLM outputs
- RAG context injection for therapy-style-specific knowledge
- Session time tracking with extension support
- Message history preservation

#### AgentOrchestrator (`src/orchestration/agent_orchestrator.py`)

**Purpose**: Main coordination layer that routes requests to agents

**Responsibilities**:
- Route messages to correct agents based on workflow state
- Coordinate agent responses with workflow transitions
- Manage user profile creation
- Handle session lifecycle (start, extend, end)
- Cache agent instances for performance

**Message Flow**:
```
User Message
    ↓
Get User State (WorkflowEngine)
    ↓
Get Current Agent (State → Agent Mapping)
    ↓
Load Conversation Context
    ↓
Agent.process_message() → AgentResponse
    ↓
Stream Response (ConversationManager)
    ↓
Handle State Transition (if needed)
```

### 2. Agents

Agents are pure business logic components that process user inputs and return structured responses.

#### Base Agent Pattern

All agents implement a common pattern:

```python
async def process_message(
    self, message: str, context: ConversationContext
) -> AgentResponse:
    """
    Process user message and return agent response.

    Returns:
        AgentResponse with:
        - content: Prompt for LLM
        - next_action: "continue" | "transition" | "offer_extension"
        - next_state: Target workflow state (if transitioning)
        - metadata: Additional context
    """
```

#### IntakeAgent (`src/agents/intake_agent.py`)

**Purpose**: Collect initial user information

**Key Topics**:
- Name, age, profession (gathered from profile)
- Current concerns and symptoms
- Therapy goals and expectations
- Previous therapy experience

**Completion Criteria**:
- All core topics covered
- Sufficient context for assessment

#### AssessmentAgent (`src/agents/assessment_agent.py`)

**Purpose**: Analyze intake data and recommend therapy styles

**Process**:
1. Generate 3 therapy style recommendations with reasoning
2. Present options to user
3. Await user selection
4. Create initial therapy plan

**Outputs**:
- TherapyStyleRecommendation objects
- Initial TherapyPlan with selected style

#### PsychoanalystAgent (`src/agents/psychoanalyst_agent.py`)

**Purpose**: Conduct main therapy sessions

**Features**:
- Style-specific prompts (Freud, Jung, CBT)
- RAG-enhanced responses using domain knowledge
- Session time awareness
- Extension offering when time running low

**Interaction Pattern**:
- Initial greeting based on therapy plan
- Continuation prompts with RAG context
- Time-aware responses
- Graceful session closing

#### ReflectionAgent (`src/agents/reflection_agent.py`)

**Purpose**: Post-session reflection and plan updates

**Process**:
1. Review session transcript
2. Identify progress and insights
3. Update therapy plan
4. Prepare for next session

### 3. Gateway Layer

Gateways connect client interfaces to the orchestration layer.

#### WebSocketGateway (`src/gateways/websocket_gateway.py`)

**Purpose**: Handle real-time WebSocket communication

**Events Handled**:
- `chat_message`: User sends message → streaming response
- `session_request`: Start new therapy session
- `user_status_request`: Get current workflow state
- `style_selection`: User selects therapy style
- `session_extension`: Extend session time

**Events Emitted**:
- `chat_response_chunk`: Streaming LLM chunks
- `session_started`: Session creation confirmed
- `user_status`: Workflow state update
- `typing_start`/`typing_stop`: Typing indicators
- `error`: Error messages

**Streaming Pattern**:
```python
# Receive message
await sio.emit("typing_start", room=sid)

# Stream chunks as they arrive
async for chunk in orchestrator.process_message(...):
    await sio.emit("chat_response_chunk", {
        "chunk": chunk,
        "is_complete": False
    }, room=sid)

# Signal completion
await sio.emit("chat_response_chunk", {
    "chunk": "",
    "is_complete": True,
    "full_response": full_response
}, room=sid)
await sio.emit("typing_stop", room=sid)
```

### 4. Service Layer

Services provide low-level functionality to the system.

#### DatabaseService (`src/services/db_service.py`)

**Purpose**: SQLite database abstraction

**Operations**:
- User profile CRUD
- Session management
- Message persistence
- Therapy plan storage
- Workflow state tracking

#### LLMService (`src/services/llm_service.py`)

**Purpose**: Google Gemini API integration

**Features**:
- Streaming response generation
- Context-aware prompts
- Token management
- Error handling and retries

#### RAGService (`src/services/rag_service.py`)

**Purpose**: ChromaDB vector store for domain knowledge

**Features**:
- Semantic search over therapy knowledge
- Style-specific knowledge filtering (Freud, Jung, CBT)
- Embedding generation
- Relevance scoring

## Data Models

### Core Models (`src/orchestration/models.py`)

```python
@dataclass
class ConversationContext:
    session_id: str
    user_profile: UserProfile
    therapy_plan: Optional[TherapyPlan]
    message_history: List[Message]
    topics_covered: List[str]
    session_start_time: datetime
    duration_minutes: int
    extensions_used: int
    max_extensions: int

    @property
    def is_time_up(self) -> bool

    @property
    def time_remaining_minutes(self) -> int

    @property
    def can_extend(self) -> bool

@dataclass
class AgentResponse:
    content: str              # Prompt for LLM
    next_action: str          # "continue" | "transition" | "offer_extension"
    next_state: Optional[WorkflowState]
    metadata: Dict[str, Any]
```

## API Endpoints

### HTTP REST API

```
GET  /health                        - Health check
GET  /api/user/status               - Get user workflow state
POST /api/user/profile              - Create user profile
GET  /api/sessions                  - List user sessions
GET  /api/sessions/{id}             - Get session with transcript
POST /api/sessions                  - Create new session
POST /api/sessions/{id}/extend      - Extend session time
GET  /api/therapy/styles            - List therapy styles
GET  /api/therapy/plan              - Get therapy plan
POST /api/therapy/plan              - Create/update therapy plan
```

### WebSocket Events

```
Client → Server:
  - chat_message          Send message, receive streaming response
  - session_request       Start new session
  - user_status_request   Get current state
  - style_selection       Select therapy style
  - session_extension     Request time extension
  - typing_start/stop     Typing indicators
  - ping                  Connection test

Server → Client:
  - chat_response_chunk   Streaming message chunks
  - session_started       Session created
  - user_status           Workflow state
  - style_selected        Style confirmed
  - session_extended      Time extended
  - typing_start/stop     Therapist typing
  - error                 Error occurred
  - pong                  Connection OK
```

## Deployment

### Production Setup

```yaml
# docker-compose.yml
services:
  unified-server:
    build: .
    ports:
      - "8000:8000"
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - DATABASE_PATH=/app/data/psychoanalyst.db
    volumes:
      - ./data:/app/data
```

### Starting the Server

```bash
# Development
python src/unified_server.py

# Production
docker-compose up unified-server
```

## Testing

### Test Structure

```
tests/
├── unit/
│   ├── test_workflow_engine.py       # State machine tests
│   ├── test_conversation_manager.py  # Streaming & context tests
│   ├── test_agent_orchestrator.py    # Orchestration tests
│   └── test_websocket_gateway.py     # WebSocket tests
└── integration/
    └── test_orchestration_flow.py    # End-to-end workflow tests
```

### Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/

# Specific component
pytest tests/unit/test_workflow_engine.py -v
```

## Performance Considerations

### Streaming Latency

- First chunk typically arrives in <100ms
- Subsequent chunks stream in real-time
- No buffering delays

### Concurrent Users

- Agent instances cached per user/session
- State machine supports multiple concurrent users
- Database connection pooling (future enhancement)

### Scalability

Current architecture supports:
- Multiple concurrent WebSocket connections
- Session isolation per user
- Stateless HTTP API

Future enhancements:
- Redis for session state (horizontal scaling)
- Message queue for async processing
- Load balancing across instances

## Security

### Current Implementation

- User authentication via tokens (WebSocket)
- Session isolation
- Input validation on API endpoints
- Error handling with safe error messages

### Future Enhancements

- JWT-based authentication
- Rate limiting
- Encryption at rest (database)
- HTTPS/WSS in production
- Audit logging

## Development Guidelines

### Adding a New Agent

1. Create agent class extending `BaseConversationalAgent`
2. Implement `process_message()` method
3. Add agent to `ServiceContainer`
4. Add state-to-agent mapping in `WorkflowEngine`
5. Add workflow events and transitions
6. Create unit tests

### Adding a New API Endpoint

1. Add route in `UnifiedServer._setup_http_routes()`
2. Implement handler method
3. Use orchestrator for business logic
4. Return JSON response
5. Add error handling
6. Document in this file

### Adding a New WebSocket Event

1. Add event handler in `WebSocketGateway`
2. Extract and validate data
3. Use orchestrator for processing
4. Emit response events
5. Add to frontend WebSocket service
6. Update TypeScript types

## Troubleshooting

### Common Issues

**WebSocket won't connect**:
- Check CORS configuration in `UnifiedServer`
- Verify Socket.IO client version compatibility
- Check authentication token

**Streaming not working**:
- Verify `chat_response_chunk` handler in frontend
- Check LLM service streaming implementation
- Verify network allows SSE/WebSocket

**State transition failed**:
- Check workflow state in database
- Verify transition is valid in `WorkflowEngine`
- Check logs for `InvalidStateTransitionError`

## Monitoring

### Logging

```python
import logging
logger = logging.getLogger(__name__)

# Logs to stdout/stderr
logger.info("User connected")
logger.error("Error processing message", exc_info=True)
```

### Metrics (Future)

- Active connections count
- Message throughput
- Average response latency
- Error rates by endpoint
- State transition counts

## Migration from Legacy

The legacy architecture had UI-coupled agents. The new architecture:

**Before**:
- Agents directly interacted with UI
- Full session management in each agent
- No central orchestration

**After**:
- Agents return prompts (pure business logic)
- Orchestrator handles session management
- Streaming handled by ConversationManager
- State machine coordinates workflow

**Backward Compatibility**:
- Agents still support legacy `conduct_session()` method
- Can be removed in future major version

---

**Last Updated**: 2025-01-08
**Version**: 2.0 (Orchestration Architecture)
