---
owner: engineering
status: active
last_reviewed: 2026-05-31
review_cycle_days: 90
source_of_truth_for: Runtime architecture boundaries and component responsibilities
---

# Architecture Documentation

Documentation governance for this file is defined in `DOCS_GOVERNANCE.md`.
Current stabilization priorities and client support tiers are defined in
`docs/reference/FOUNDATION_STABILIZATION_PLAN.md`.

## Overview

The local therapist tool separates business logic from interface concerns. It
uses an **orchestration-based architecture** with streaming LLM responses for
real-time user interactions on a local laptop.

## Architecture Principles

1. **Separation of Concerns**: Agents contain pure business logic; gateways handle I/O
2. **Unified API**: The supported console client uses the public backend contract
3. **Streaming First**: Real-time streaming of LLM responses for better UX
4. **State Machine**: Workflow driven by explicit state transitions
5. **Local Reliability**: Keep session isolation correct without adding hosted deployment complexity

During foundation stabilization, maintenance priority is backend-first:
- Tier 0 is the backend, workflow/session lifecycle, persistence, HTTP DTOs, WebSocket protocol, schema/type pipeline, LLM abstraction, and deterministic tests.
- Tier 1 is the WebSocket console UI, the only maintained frontend and the canonical integration client.
- Removed UI surfaces must not be recreated unless explicitly requested; see
  `docs/ui-scope.md`.

The runtime therapy agent role is `THERAPIST`. The modality is stored and
transported separately as `selected_therapy_style` (`cbt`, `freud`, or `jung`).
Therapy plans are immutable revisions: profiles point to the current revision,
while sessions retain the historical revision effective at session start.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Supported Client Interface                  │
│                  ┌──────────────────────┐                    │
│                  │      Console UI      │                    │
│                  │  (HTTP + WebSocket)  │                    │
│                  └──────────────────────┘                    │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
     ┌────────────────────────────────────────┐
     │      Unified Server (Port 8000)        │
     │  ┌──────────────────────────────────┐  │
     │  │     HTTP REST API Endpoints      │  │
     │  │   /api/user/*, /api/sessions/*   │  │
     │  └──────────────────────────────────┘  │
     │  ┌──────────────────────────────────┐  │
     │  │     Native WebSocket Server      │  │
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

#### TrioWorkflowEngine (`src/psychoanalyst_app/orchestration/trio_workflow_engine.py`)

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
    PLAN_UPDATE_COMPLETE = "plan_update_complete"                # Ready for next session
```

**State Transitions**:
```
NEW → INTAKE_IN_PROGRESS → INTAKE_COMPLETE
  → ASSESSMENT_IN_PROGRESS → ASSESSMENT_COMPLETE
  → THERAPY_IN_PROGRESS → REFLECTION_IN_PROGRESS
  → PLAN_UPDATE_COMPLETE → THERAPY_IN_PROGRESS (cycle)
```

#### TrioConversationManager (`src/psychoanalyst_app/orchestration/trio_conversation_manager.py`)

**Purpose**: Manages conversation context and streaming responses

**Responsibilities**:
- Stream LLM responses chunk-by-chunk
- Maintain conversation context and history
- Preserve an optional no-op retrieval extension point
- Manage session time and extensions
- Persist messages to database

**Key Features**:
- Real-time streaming of LLM outputs
- Deterministic no-op retrieval until a local extension is deliberately added
- Session time tracking with extension support
- Message history preservation

#### TrioAgentOrchestrator (`src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py`)

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

#### TrioIntakeAgent (`src/psychoanalyst_app/agents/intake/agent.py`)

**Purpose**: Collect initial user information

**Key Topics**:
- Name, age, profession (gathered from profile)
- Current concerns and symptoms
- Therapy goals and expectations
- Previous therapy experience

**Completion Criteria**:
- All core topics covered
- Sufficient context for assessment

#### TrioAssessmentAgent (`src/psychoanalyst_app/agents/assessment/agent.py`)

**Purpose**: Analyze intake data and recommend therapy styles

**Process**:
1. Generate 3 therapy style recommendations with reasoning
2. Present options to user
3. Await user selection
4. Create initial therapy plan

**Outputs**:
- TherapyStyleRecommendation objects
- Initial TherapyPlan with selected style

#### TrioTherapistAgent (`src/psychoanalyst_app/agents/therapist/agent.py`)

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

#### TrioReflectionAgent (`src/psychoanalyst_app/agents/reflection/agent.py`)

**Purpose**: Post-session reflection and plan updates

**Process**:
1. Review session transcript
2. Identify progress and insights
3. Update therapy plan
4. Prepare for next session

### 3. Gateway Layer

Gateways connect client interfaces to the orchestration layer.

Client support during foundation stabilization:
- The console UI is the only maintained frontend and validates registration, WebSocket connection, workflow-next-action emission, streaming, session ending, and style selection.
- Workflow probes use the same public HTTP/WebSocket boundary.
- Archived UI surfaces must not be recreated unless explicitly approved.

#### WebSocket Handler (`src/psychoanalyst_app/api/ws_handler.py`)

**Purpose**: Handle real-time WebSocket communication

**Notes**:
- WebSocket payloads are implicitly bound to the active session; clients do not send `session_id` in WS messages.
- Initial greetings are skipped when `workflow_next_action.required_action` is `wait`; the wait prompt acts as the status notice.

**Events Handled**:
- `chat_message`: User sends message → streaming response
- `end_session`: End active session

**Events Emitted**:
- `chat_response_chunk`: Streaming LLM chunks
- `session_started`: Session creation confirmed
- `workflow_next_action`: Workflow state update
- `typing_start`/`typing_stop`: Typing indicators
- `connected`: Connection established
- `session_ended`: Session ended
- `assessment_recommendations`: Assessment recommendations
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

#### TrioDatabaseService (`src/psychoanalyst_app/services/trio_db_service.py`)

**Purpose**: SQLite database abstraction

**Operations**:
- User profile CRUD
- Session management
- Message persistence
- Therapy plan storage
- Workflow state tracking

#### LLMService (`src/psychoanalyst_app/services/llm_service.py`)

**Purpose**: LLM provider integration for Gemini, Ollama, and OpenAI-compatible
local servers such as LM Studio

**Features**:
- Streaming response generation
- Context-aware prompts
- Provider selection via configuration
- Native Gemini structured output and JSON-validated local structured output
- Token management
- Error handling and retries

#### RAGService (`src/psychoanalyst_app/services/rag.py`)

**Purpose**: No-op retrieval boundary for the current release

**Features**:
- Keeps agent/orchestration call sites stable while retrieval is disabled
- Returns empty retrieval results deterministically
- Defers local vector retrieval to a future extension

## Data Models

For the full model inventory and DTO mappings, see `docs/data-models.md`.

### Core Models (`src/psychoanalyst_app/orchestration/models.py`)

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
    next_state: Optional[WorkflowState]  # Deprecated; use workflow_event
    workflow_event: Optional[WorkflowEvent]
    metadata: Dict[str, Any]
```

## API Endpoints

### HTTP REST API

```
GET  /health                        - Health check
POST /api/user/register             - Register profile + start session
GET  /api/user/status               - Get user workflow state (user-scoped)
GET  /api/sessions                  - List user sessions (requires session_id)
GET  /api/sessions/{id}             - Get session with transcript (requires session_id)
POST /api/sessions                  - Create new session
POST /api/sessions/{id}/extend      - Extend session time (requires session_id)
GET  /api/therapy/styles            - List therapy styles (requires session_id)
GET  /api/therapy/plan              - Get therapy plan (requires session_id)
GET  /api/workflow/next             - Get next workflow action (requires session_id)
POST /api/workflow/complete_profile - Complete profile step
POST /api/workflow/select_therapy_style - Select therapy style
POST /api/workflow/start_therapy    - Start first plan-linked therapy session
```

### WebSocket Events

```
Client → Server:
  - chat_message          Send message, receive streaming response
  - end_session           End session

Server → Client:
  - chat_response_chunk   Streaming message chunks
  - session_started       Session created
  - workflow_next_action  Workflow state
  - connected             Connection established
  - session_ended         Session ended
  - assessment_recommendations Style recommendations
  - typing_start/stop     Therapist typing (optional)
  - error                 Error occurred
```

## Operations and Playbooks

Local setup and maintainer commands are summarized in the root `README.md`.
