# Architecture Redesign: Hybrid Approach with Unified API Gateway

## Executive Summary

This document describes the architecture redesign of the Virtual LLM-Driven Psychoanalyst application to implement a **hybrid architecture** (Option 3) that enables all user interfaces (local, console, web) to provide identical functionality through a unified API gateway.

**Problem**: The local interface provides complete therapy workflow functionality, but remote interfaces (Console UI, Frontend) only have placeholder implementations with no agent integration.

**Solution**: Refactor to a hybrid architecture where:
- Agents contain pure business logic (no UI coupling)
- New orchestration layer handles UI interaction, streaming, and workflow management
- All UIs use the same unified API gateway
- Support for streaming LLM responses

---

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Problem Statement](#problem-statement)
3. [Design Decisions](#design-decisions)
4. [New Architecture Overview](#new-architecture-overview)
5. [Component Specifications](#component-specifications)
6. [Data Flow](#data-flow)
7. [Migration Strategy](#migration-strategy)
8. [Testing Strategy](#testing-strategy)
9. [Success Criteria](#success-criteria)

---

## Current State Analysis

### Local Interface (src/main.py + src/ui/)

**Status**: ✅ Fully Functional

**Capabilities**:
- Complete user profile collection
- Stateful workflow resumption (4 states: NEW, PROFILE_ONLY, INTAKE_COMPLETE, PLAN_COMPLETE)
- Full agent workflow:
  - IntakeAgent: 30-minute conversational intake
  - AssessmentAgent: Style recommendations (Freud, Jung, CBT)
  - PsychoanalystAgent: RAG-enhanced therapy sessions
  - ReflectionAgent: Therapy plan updates
- Time-aware session management with extensions
- Topic tracking
- Complete database persistence

**Implementation Pattern**:
```python
# Direct agent instantiation and synchronous calls
intake_agent = container.get_intake_agent()
intake_agent.conduct_intake(ui, user_profile, duration)

# BaseUI interface with synchronous methods
class BaseUI(ABC):
    @abstractmethod
    def display_message(self, role: str, text: str)

    @abstractmethod
    def get_user_input(self, prompt: str) -> str
```

### Remote Interfaces (Console UI, Frontend)

**Status**: ⚠️ Infrastructure Only (~25% complete)

**What Works**:
- WebSocket connection and authentication (JWT tokens)
- Basic message routing via Socket.IO
- User registration and login
- Session listing API
- Therapy styles metadata API
- Typing indicators
- Connection status tracking

**What's Missing**:
- ❌ No agent integration in WebSocket handlers
- ❌ No intake workflow
- ❌ No assessment workflow with style selection
- ❌ No therapy sessions with LLM
- ❌ No reflection/plan updates
- ❌ No RAG-enhanced responses
- ❌ No streaming LLM responses
- ❌ No session state management
- ❌ No conversation context preservation

**Current Placeholder Implementation**:
```python
# src/websocket_server/message_handler.py
async def _handle_chat_message(self, sid: str, data: dict) -> None:
    # TODO: Integrate with actual psychoanalyst agent
    response = "Let's explore that further. Tell me more..."
    await self.sio.emit('chat_response', {'message': response}, room=sid)
```

### API/WebSocket Server (src/unified_server.py)

**Status**: ⚠️ Partial Implementation

**Implemented Endpoints**:
- `GET /health`: Health check
- `GET /api/user/status`: User workflow status
- `GET /api/sessions`: Session listing
- `GET /api/therapy/styles`: Available therapy styles
- `POST /auth/register`: User registration
- `POST /auth/login`: Authentication
- WebSocket events: `connect`, `disconnect`, `message`, `typing_start/stop`

**Stub Endpoints (Placeholder)**:
- `POST /api/user/profile`: Returns "not yet implemented"
- `GET /api/sessions/{session_id}`: Returns "not yet implemented"
- `POST /api/sessions`: Creates placeholder session ID only

---

## Problem Statement

### Critical Gap: UI Functionality Disparity

The application has a **fundamental architectural issue** where different user interfaces provide vastly different experiences:

| Feature | Local Interface | Console UI | Web Frontend |
|---------|----------------|------------|--------------|
| Intake Workflow | ✅ Full | ❌ None | ❌ None |
| Assessment | ✅ Full | ❌ None | ❌ None |
| Therapy Sessions | ✅ Full | ❌ Placeholder | ❌ Placeholder |
| Reflection | ✅ Full | ❌ None | ❌ None |
| RAG Enhancement | ✅ Yes | ❌ No | ❌ No |
| Streaming Responses | N/A | ❌ No | ❌ No |
| Session Resumption | ✅ Yes | ❌ No | ❌ No |

### Root Causes

1. **UI Coupling**: Agents are tightly coupled to BaseUI interface with synchronous methods (`get_user_input()`)
2. **No Orchestration Layer**: No unified service layer that all UIs can use
3. **Missing Integration**: WebSocket MessageHandler has no agent integration
4. **Synchronous Design**: Current agents expect synchronous conversation loops, incompatible with async WebSocket

### User Impact

- Remote users (console, web) cannot access core therapy functionality
- Frontend is ready for full workflow but backend doesn't provide it
- Inconsistent user experience across interfaces
- No streaming responses for better UX

---

## Design Decisions

### Why Option 3 (Hybrid Architecture)?

We evaluated three options:

| Option | Description | Chosen |
|--------|-------------|--------|
| 1. Keep Agent-Based | Add adapter layer, keep agents as-is | ❌ |
| 2. Service-Oriented | Complete rewrite to services | ❌ |
| 3. Hybrid | Decouple agents from UI, add orchestration | ✅ |

**Why Option 3?**
- Preserves agent separation of concerns (intake, assessment, therapy, reflection)
- Removes UI coupling - agents become pure business logic
- Supports both synchronous (local) and asynchronous (WebSocket) interfaces
- Natural streaming support in orchestration layer
- Incremental migration path (refactor one agent at a time)
- Future-proof for new UI types

### Key Design Principles

1. **Separation of Concerns**
   - **Agents**: Pure business logic (what to do)
   - **Orchestration**: Coordination and state management (when to do it)
   - **Gateways**: UI interaction (how to present it)

2. **UI Agnostic**
   - Agents don't know about UI type
   - Return data, not UI commands
   - Orchestration layer handles UI adaptation

3. **Streaming First**
   - LLM responses stream by default
   - Chunks sent via WebSocket for real-time UX
   - Local UI can consume streams synchronously

4. **Unified API Gateway**
   - All UIs use the same backend API
   - Local UI becomes an API client (via LocalGateway)
   - Consistent behavior across all interfaces

5. **Backward Compatibility**
   - Existing tests should pass
   - Local UI continues to work
   - Gradual migration path

---

## New Architecture Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT INTERFACES                          │
├─────────────┬─────────────────┬─────────────────┬────────────────┤
│  Local UI   │   Console UI    │  Web Frontend   │   Mobile App   │
│  (Terminal) │   (Terminal)    │   (Browser)     │   (Future)     │
└──────┬──────┴────────┬────────┴────────┬────────┴────────┬───────┘
       │               │                 │                 │
       │               │                 │                 │
┌──────▼──────┬────────▼─────────────────▼─────────────────▼───────┐
│             │           UNIFIED API GATEWAY                       │
│ LocalGateway│  WebSocketGateway       RESTGateway                │
│  (Adapter)  │   (Socket.IO)            (HTTP)                     │
└──────┬──────┴────────┬──────────────────┬──────────────────────┬─┘
       │               │                  │                      │
       └───────────────┴──────────────────┴──────────┬───────────┘
                                                      │
                       ┌──────────────────────────────▼──────────────┐
                       │      ORCHESTRATION LAYER                    │
                       │  ┌────────────────────────────────────────┐ │
                       │  │      AgentOrchestrator                 │ │
                       │  │  - Route requests to agents            │ │
                       │  │  - Manage agent lifecycle              │ │
                       │  │  - Coordinate workflows                │ │
                       │  └──────┬──────────────────────────┬──────┘ │
                       │         │                          │        │
                       │  ┌──────▼──────────┐      ┌───────▼──────┐ │
                       │  │ConversationMgr  │      │WorkflowEngine│ │
                       │  │- Stream LLM     │      │- State machine│ │
                       │  │- Context mgmt   │      │- Transitions │ │
                       │  │- RAG retrieval  │      │- Resumption  │ │
                       │  └─────────────────┘      └──────────────┘ │
                       └──────────────────┬──────────────────────────┘
                                          │
                       ┌──────────────────▼──────────────────────────┐
                       │           BUSINESS LOGIC LAYER              │
                       │  ┌──────────────────────────────────────┐   │
                       │  │  IntakeAgent                         │   │
                       │  │  process_message(msg, ctx) → response│   │
                       │  │  - Pure business logic               │   │
                       │  │  - No UI coupling                    │   │
                       │  └──────────────────────────────────────┘   │
                       │  ┌──────────────────────────────────────┐   │
                       │  │  AssessmentAgent                     │   │
                       │  │  generate_recommendations(session)   │   │
                       │  └──────────────────────────────────────┘   │
                       │  ┌──────────────────────────────────────┐   │
                       │  │  PsychoanalystAgent                  │   │
                       │  │  process_message(msg, ctx) → response│   │
                       │  └──────────────────────────────────────┘   │
                       │  ┌──────────────────────────────────────┐   │
                       │  │  ReflectionAgent                     │   │
                       │  │  update_plan(session, plan)          │   │
                       │  └──────────────────────────────────────┘   │
                       └──────────────────┬──────────────────────────┘
                                          │
                       ┌──────────────────▼──────────────────────────┐
                       │            SERVICE LAYER                    │
                       │  LLMService │ RAGService │ DBService        │
                       │  StyleService │ AuthService                 │
                       └─────────────────────────────────────────────┘
```

### Request Flow Example: Chat Message

```
1. User sends message via Web Frontend
   ↓
2. WebSocket event received: 'chat_message'
   ↓
3. WebSocketGateway.handle_chat_message()
   ↓
4. AgentOrchestrator.process_message(user_id, message, session_id)
   ↓
5. WorkflowEngine determines current state → PsychoanalystAgent
   ↓
6. ConversationManager.get_context(session_id)
   ↓
7. PsychoanalystAgent.process_message(message, context)
   - Returns prompt for LLM
   ↓
8. ConversationManager.stream_response(prompt, context)
   - Calls LLMService with streaming
   - Retrieves RAG context
   - Yields chunks
   ↓
9. WebSocketGateway emits chunks:
   - 'typing_start'
   - 'chat_response_chunk' (multiple)
   - 'typing_stop'
   - 'chat_response_complete'
   ↓
10. Frontend displays streaming message
```

---

## Component Specifications

### 1. AgentOrchestrator

**Location**: `src/orchestration/agent_orchestrator.py`

**Responsibilities**:
- Entry point for all requests (WebSocket, REST, local)
- Route requests to appropriate agents based on workflow state
- Manage agent lifecycle
- Coordinate with WorkflowEngine and ConversationManager

**Key Methods**:
```python
class AgentOrchestrator:
    def __init__(
        self,
        service_container: ServiceContainer,
        workflow_engine: WorkflowEngine,
        conversation_manager: ConversationManager
    ):
        self.service_container = service_container
        self.workflow_engine = workflow_engine
        self.conversation_manager = conversation_manager
        self.agents: Dict[AgentType, Any] = {}

    async def process_message(
        self,
        user_id: str,
        message: str,
        session_id: str
    ) -> AsyncIterator[str]:
        """
        Process user message and stream response.

        Returns:
            AsyncIterator yielding response chunks
        """
        # Get workflow state
        state = await self.workflow_engine.get_user_state(user_id)

        # Get appropriate agent
        agent_type = self.workflow_engine.get_current_agent(state)
        agent = self._get_or_create_agent(agent_type)

        # Get conversation context
        context = await self.conversation_manager.get_context(session_id)

        # Process message through agent
        agent_response = await agent.process_message(message, context)

        # Stream LLM response
        async for chunk in self.conversation_manager.stream_response(
            agent_response.content, context
        ):
            yield chunk

        # Handle state transitions
        if agent_response.next_state:
            await self.workflow_engine.transition(
                user_id, agent_response.next_state
            )

    async def start_session(
        self,
        user_id: str,
        session_type: AgentType
    ) -> SessionInfo:
        """Start a new therapy session."""
        pass

    async def get_user_state(self, user_id: str) -> WorkflowState:
        """Get current workflow state for user."""
        return await self.workflow_engine.get_user_state(user_id)
```

**Dependencies**:
- ServiceContainer (for creating agents)
- WorkflowEngine (for state management)
- ConversationManager (for streaming and context)

---

### 2. ConversationManager

**Location**: `src/orchestration/conversation_manager.py`

**Responsibilities**:
- Stream LLM responses token-by-token
- Manage conversation context and history
- Integrate RAG retrieval
- Track conversation topics
- Implement time-aware session management

**Key Methods**:
```python
class ConversationManager:
    def __init__(
        self,
        llm_service: LLMService,
        rag_service: RAGService,
        db_service: DatabaseService
    ):
        self.llm_service = llm_service
        self.rag_service = rag_service
        self.db_service = db_service
        self.active_contexts: Dict[str, ConversationContext] = {}

    async def stream_response(
        self,
        prompt: str,
        context: ConversationContext
    ) -> AsyncIterator[str]:
        """
        Stream LLM response chunks.

        Args:
            prompt: The prompt to send to LLM
            context: Conversation context

        Yields:
            Response chunks as they're generated
        """
        # Retrieve RAG context if needed
        if context.therapy_plan:
            rag_context = await self.rag_service.retrieve_relevant_knowledge(
                prompt, context.therapy_plan.selected_style
            )
            # Augment prompt with RAG context
            prompt = self._augment_prompt(prompt, rag_context)

        # Stream LLM response
        full_response = ""
        async for chunk in self.llm_service.stream_generate(prompt):
            full_response += chunk
            yield chunk

        # Save message to database
        await self.add_message(
            context.session_id,
            "assistant",
            full_response
        )

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str
    ) -> None:
        """Add message to conversation history."""
        pass

    async def get_context(
        self,
        session_id: str
    ) -> ConversationContext:
        """Get conversation context for session."""
        if session_id in self.active_contexts:
            return self.active_contexts[session_id]

        # Load from database
        session = await self.db_service.get_session(session_id)
        user_profile = await self.db_service.get_user_profile(session.user_id)
        therapy_plan = await self.db_service.get_current_therapy_plan(
            session.user_id
        )

        context = ConversationContext(
            session_id=session_id,
            user_profile=user_profile,
            therapy_plan=therapy_plan,
            message_history=session.messages,
            topics_covered=[],
            session_start_time=session.created_at,
            duration_minutes=30
        )

        self.active_contexts[session_id] = context
        return context
```

**Dependencies**:
- LLMService (streaming generation)
- RAGService (knowledge retrieval)
- DatabaseService (persistence)

---

### 3. WorkflowEngine

**Location**: `src/orchestration/workflow_engine.py`

**Responsibilities**:
- State machine for workflow transitions
- Determine next agent based on current state
- Validate state transitions
- Handle workflow resumption

**State Diagram**:
```
NEW
 │
 ├──> INTAKE_IN_PROGRESS
 │         │
 │         ├──> INTAKE_COMPLETE
 │         │         │
 │         │         ├──> ASSESSMENT_IN_PROGRESS
 │         │         │         │
 │         │         │         ├──> ASSESSMENT_COMPLETE
 │         │         │         │         │
 │         │         │         │         ├──> THERAPY_IN_PROGRESS
 │         │         │         │         │         │
 │         │         │         │         │         ├──> REFLECTION_IN_PROGRESS
 │         │         │         │         │         │         │
 │         │         │         │         │         │         └──> PLAN_COMPLETE
 │         │         │         │         │         │                   │
 │         │         │         │         │         │                   └──> (loop back to THERAPY_IN_PROGRESS)
```

**Implementation**:
```python
class WorkflowState(Enum):
    NEW = "new"
    INTAKE_IN_PROGRESS = "intake_in_progress"
    INTAKE_COMPLETE = "intake_complete"
    ASSESSMENT_IN_PROGRESS = "assessment_in_progress"
    ASSESSMENT_COMPLETE = "assessment_complete"
    THERAPY_IN_PROGRESS = "therapy_in_progress"
    REFLECTION_IN_PROGRESS = "reflection_in_progress"
    PLAN_COMPLETE = "plan_complete"

class WorkflowEngine:
    # State → Agent mapping
    STATE_AGENT_MAP = {
        WorkflowState.NEW: AgentType.INTAKE,
        WorkflowState.INTAKE_IN_PROGRESS: AgentType.INTAKE,
        WorkflowState.INTAKE_COMPLETE: AgentType.ASSESSMENT,
        WorkflowState.ASSESSMENT_IN_PROGRESS: AgentType.ASSESSMENT,
        WorkflowState.ASSESSMENT_COMPLETE: AgentType.PSYCHOANALYST,
        WorkflowState.THERAPY_IN_PROGRESS: AgentType.PSYCHOANALYST,
        WorkflowState.REFLECTION_IN_PROGRESS: AgentType.REFLECTION,
        WorkflowState.PLAN_COMPLETE: AgentType.PSYCHOANALYST,
    }

    # Valid transitions
    VALID_TRANSITIONS = {
        WorkflowState.NEW: [WorkflowState.INTAKE_IN_PROGRESS],
        WorkflowState.INTAKE_IN_PROGRESS: [WorkflowState.INTAKE_COMPLETE],
        WorkflowState.INTAKE_COMPLETE: [WorkflowState.ASSESSMENT_IN_PROGRESS],
        # ... etc
    }

    def __init__(self, db_service: DatabaseService):
        self.db_service = db_service

    async def get_user_state(self, user_id: str) -> WorkflowState:
        """Get current workflow state for user."""
        user_status = await self.db_service.get_user_status(user_id)
        return self._map_user_status_to_workflow_state(user_status)

    def get_current_agent(self, state: WorkflowState) -> AgentType:
        """Determine which agent should handle current state."""
        return self.STATE_AGENT_MAP[state]

    async def transition(
        self,
        user_id: str,
        new_state: WorkflowState
    ) -> None:
        """Transition user to new workflow state."""
        current_state = await self.get_user_state(user_id)

        if not self.can_transition(current_state, new_state):
            raise InvalidStateTransitionError(
                f"Cannot transition from {current_state} to {new_state}"
            )

        # Update database
        await self.db_service.update_user_workflow_state(user_id, new_state)

    def can_transition(
        self,
        from_state: WorkflowState,
        to_state: WorkflowState
    ) -> bool:
        """Check if transition is valid."""
        return to_state in self.VALID_TRANSITIONS.get(from_state, [])
```

**Dependencies**:
- DatabaseService (state persistence)

---

### 4. Refactored Agents

#### Before (Current - UI Coupled):
```python
class IntakeAgent:
    def conduct_intake(
        self,
        ui: BaseUI,
        user_profile: UserProfile,
        session_duration: int
    ) -> Session:
        """Conducts intake session."""
        # UI coupled conversation loop
        while not done:
            user_input = ui.get_user_input("You: ")
            response = self._generate_response(user_input)
            ui.display_message("therapist", response)
```

#### After (Refactored - Pure Business Logic):
```python
class IntakeAgent:
    async def process_message(
        self,
        message: str,
        context: ConversationContext
    ) -> AgentResponse:
        """
        Process user message during intake.

        Returns AgentResponse with prompt for LLM and next action.
        """
        # Update topics covered
        current_topic = self._identify_topic(message)
        if current_topic not in context.topics_covered:
            context.topics_covered.append(current_topic)

        # Build prompt
        prompt = self._build_intake_prompt(message, context)

        # Determine if intake is complete
        is_complete = self._is_intake_complete(context)

        return AgentResponse(
            content=prompt,
            next_action="transition" if is_complete else "continue",
            next_state=WorkflowState.INTAKE_COMPLETE if is_complete else None,
            metadata={
                "topics_covered": context.topics_covered,
                "time_remaining": self._calculate_time_remaining(context)
            }
        )

    def _is_intake_complete(self, context: ConversationContext) -> bool:
        """Check if intake session should end."""
        # Time-based
        elapsed = datetime.now() - context.session_start_time
        time_up = elapsed.total_seconds() / 60 >= context.duration_minutes

        # Topic-based
        required_topics = self._get_required_topics()
        topics_covered = len(context.topics_covered) >= len(required_topics)

        return time_up or topics_covered
```

**Key Changes**:
- No UI dependency - returns data instead of displaying it
- Pure function - message + context → response
- Explicit state transitions via `next_state`
- Metadata for orchestrator to use

---

### 5. WebSocketGateway

**Location**: `src/gateways/websocket_gateway.py`

**Responsibilities**:
- Handle WebSocket connections
- Stream agent responses to clients
- Emit typing indicators
- Handle user input events

**Implementation**:
```python
class WebSocketGateway:
    def __init__(
        self,
        sio: socketio.AsyncServer,
        orchestrator: AgentOrchestrator,
        connection_manager: ConnectionManager
    ):
        self.sio = sio
        self.orchestrator = orchestrator
        self.connection_manager = connection_manager

    async def handle_chat_message(self, sid: str, data: dict) -> None:
        """Handle incoming chat message."""
        user_id = self.connection_manager.get_user_id(sid)

        # Emit typing indicator
        await self.sio.emit('typing_start', room=sid)

        # Get response stream from orchestrator
        response_stream = self.orchestrator.process_message(
            user_id=user_id,
            message=data['message'],
            session_id=data.get('session_id')
        )

        # Stream chunks to client
        full_response = ""
        try:
            async for chunk in response_stream:
                full_response += chunk
                await self.sio.emit('chat_response_chunk', {
                    'chunk': chunk,
                    'is_complete': False
                }, room=sid)
        except Exception as e:
            await self.sio.emit('error', {
                'message': str(e)
            }, room=sid)
            return
        finally:
            await self.sio.emit('typing_stop', room=sid)

        # Send completion event
        await self.sio.emit('chat_response_chunk', {
            'chunk': '',
            'is_complete': True,
            'full_response': full_response
        }, room=sid)

    async def handle_session_request(self, sid: str, data: dict) -> None:
        """Handle session start request."""
        user_id = self.connection_manager.get_user_id(sid)
        session_type = AgentType[data['type']]

        session_info = await self.orchestrator.start_session(
            user_id, session_type
        )

        await self.sio.emit('session_started', {
            'session_id': session_info.session_id,
            'agent_type': session_info.agent_type.value,
            'workflow_state': session_info.workflow_state.value
        }, room=sid)
```

**Dependencies**:
- Socket.IO server
- AgentOrchestrator
- ConnectionManager

---

### 6. LocalGateway

**Location**: `src/gateways/local_gateway.py`

**Responsibilities**:
- Adapter for local UI to use orchestrator
- Convert async orchestrator calls to sync for ConsoleUI
- Maintain backward compatibility

**Implementation**:
```python
class LocalGateway:
    def __init__(self, orchestrator: AgentOrchestrator):
        self.orchestrator = orchestrator

    def run_session(self, ui: BaseUI, user_id: str) -> None:
        """Run therapy session through local UI."""
        asyncio.run(self._run_session_async(ui, user_id))

    async def _run_session_async(
        self,
        ui: BaseUI,
        user_id: str
    ) -> None:
        """Async implementation of session."""
        # Get workflow state
        state = await self.orchestrator.get_user_state(user_id)
        ui.display_system_status(f"Current state: {state}")

        # Determine next agent
        workflow_engine = self.orchestrator.workflow_engine
        agent_type = workflow_engine.get_current_agent(state)

        # Start session
        session_info = await self.orchestrator.start_session(
            user_id, agent_type
        )

        ui.display_message(
            "system",
            f"Starting {agent_type.value} session..."
        )

        # Conversation loop
        while True:
            user_input = ui.get_user_input("You: ")

            if user_input.lower() in ["quit", "exit", "bye", "goodbye"]:
                break

            # Stream response (consume synchronously)
            response_stream = self.orchestrator.process_message(
                user_id, user_input, session_info.session_id
            )

            full_response = ""
            async for chunk in response_stream:
                full_response += chunk

            ui.display_message("therapist", full_response)
```

**Dependencies**:
- AgentOrchestrator
- BaseUI interface

---

## Data Flow

### Intake Workflow

```
1. User starts application (any interface)
   ↓
2. LocalGateway/WebSocketGateway queries workflow state
   ↓
3. WorkflowEngine: state = NEW → agent = IntakeAgent
   ↓
4. AgentOrchestrator starts intake session
   ↓
5. User sends message
   ↓
6. IntakeAgent.process_message(message, context)
   - Identifies topic
   - Updates topics_covered
   - Builds prompt for LLM
   - Checks completion criteria
   - Returns AgentResponse
   ↓
7. ConversationManager.stream_response(prompt, context)
   - Retrieves RAG context (if needed)
   - Calls LLMService.stream_generate()
   - Yields chunks
   - Saves message to DB
   ↓
8. Gateway streams chunks to UI
   ↓
9. (Repeat steps 5-8 until complete)
   ↓
10. IntakeAgent signals completion (next_state = INTAKE_COMPLETE)
    ↓
11. WorkflowEngine transitions to INTAKE_COMPLETE
    ↓
12. Next message triggers AssessmentAgent
```

### Assessment Workflow

```
1. WorkflowEngine: state = INTAKE_COMPLETE → agent = AssessmentAgent
   ↓
2. AssessmentAgent.generate_recommendations(intake_session)
   - Analyzes intake transcript
   - Retrieves RAG context for each style (Freud, Jung, CBT)
   - Generates recommendations with explanations
   - Returns List[TherapyStyleRecommendation]
   ↓
3. Gateway sends recommendations to UI
   - Local: ui.present_therapy_style_selection()
   - WebSocket: emit('style_recommendations', recommendations)
   ↓
4. User selects style
   ↓
5. AssessmentAgent.process_selection(selected_style, user_profile)
   - Creates initial TherapyPlan
   - Saves to database
   - Returns AgentResponse with next_state = ASSESSMENT_COMPLETE
   ↓
6. WorkflowEngine transitions to ASSESSMENT_COMPLETE
   ↓
7. Next message triggers PsychoanalystAgent
```

### Therapy Session Workflow

```
1. WorkflowEngine: state = ASSESSMENT_COMPLETE → agent = PsychoanalystAgent
   ↓
2. ConversationManager loads context:
   - UserProfile
   - TherapyPlan (with selected style)
   - Previous messages
   - Session start time
   ↓
3. User sends message
   ↓
4. PsychoanalystAgent.process_message(message, context)
   - Identifies intent
   - Builds style-specific prompt
   - Returns AgentResponse with prompt
   ↓
5. ConversationManager.stream_response(prompt, context)
   - Retrieves RAG context for selected style
   - Augments prompt with domain knowledge
   - Calls LLMService.stream_generate()
   - Yields chunks
   ↓
6. Gateway streams chunks to UI
   ↓
7. (Repeat steps 3-6 for conversation)
   ↓
8. Session end detection:
   - Time limit reached
   - User requests end
   - Extension limit reached
   ↓
9. PsychoanalystAgent signals completion
   ↓
10. WorkflowEngine transitions to REFLECTION_IN_PROGRESS
```

---

## Migration Strategy

### Phase-by-Phase Approach

#### Phase 1: Foundation (Complete ✅)
- ✅ Commit current state
- ✅ Create architecture documentation

#### Phase 2: Core Infrastructure
**Goal**: Create new orchestration components

1. Create `src/orchestration/` directory
2. Implement `workflow_engine.py`
   - WorkflowState enum
   - State machine logic
   - Database integration for state persistence
3. Implement `conversation_manager.py`
   - Streaming infrastructure
   - Context management
   - RAG integration
4. Implement `agent_orchestrator.py`
   - Agent routing
   - Lifecycle management
   - Integration with workflow and conversation
5. Create `src/models/orchestration_models.py`
   - AgentResponse
   - ConversationContext
   - SessionInfo

**Testing**: Unit tests for each component in isolation

#### Phase 3: Refactor Agents
**Goal**: Decouple agents from UI

**Order**: Start simple → complex
1. IntakeAgent (simplest conversation loop)
2. ReflectionAgent (no conversation, just analysis)
3. AssessmentAgent (has selection interaction)
4. PsychoanalystAgent (most complex, needs full streaming)

**For Each Agent**:
1. Create `.old` backup
2. Implement new `process_message()` method
3. Extract business logic from conversation loop
4. Update tests to new interface
5. Verify tests pass
6. Remove old methods

#### Phase 4: Gateway Implementation
**Goal**: Connect UIs to orchestrator

1. Implement `WebSocketGateway`
   - Replace placeholders in MessageHandler
   - Add streaming support
   - Integrate with AgentOrchestrator
2. Implement `LocalGateway`
   - Adapter for local UI
   - Async → sync conversion
   - Maintain backward compatibility
3. Update `src/websocket_server/message_handler.py`
   - Remove TODO placeholders
   - Delegate to WebSocketGateway

**Testing**: Integration tests for each gateway

#### Phase 5: API Endpoints
**Goal**: Complete REST API

1. Implement `POST /api/user/profile`
2. Implement `GET /api/sessions/{session_id}`
3. Implement `POST /api/therapy/plan`
4. Implement `GET /api/therapy/plan`
5. Implement `POST /api/sessions/{session_id}/extend`

**Testing**: API endpoint tests

#### Phase 6: Frontend Updates
**Goal**: Add streaming support in React app

1. Update `useWebSocket.ts`
   - Add `chat_response_chunk` handler
   - Implement streaming message state
2. Update `TherapySession.tsx`
   - Display streaming messages
   - Show typing indicators
3. Test with live WebSocket server

#### Phase 7: Local UI Migration
**Goal**: Local UI uses orchestrator

1. Update `src/main.py`
   - Initialize AgentOrchestrator
   - Create LocalGateway
   - Replace direct agent calls with gateway
2. Verify all workflows work
3. Run existing integration tests

#### Phase 8: Testing
**Goal**: Comprehensive test coverage

1. Unit tests for new components
2. Integration tests for workflows
3. End-to-end tests (all interfaces)
4. Performance benchmarks
5. Load testing

#### Phase 9: Documentation & Cleanup
**Goal**: Production ready

1. Update README.md
2. Update CLAUDE.md
3. Create API documentation (OpenAPI)
4. Create WebSocket event documentation
5. Code cleanup and linting
6. Final commit

### Rollback Strategy

Each phase has a rollback point:
- Git tags: `phase-1-complete`, `phase-2-complete`, etc.
- Backup files: `*.old` for refactored components
- Feature flags: Toggle between old/new implementations
- Separate branches: `main` (stable), `architecture-redesign` (work)

---

## Testing Strategy

### Unit Tests

**New Test Files**:
- `tests/unit/test_workflow_engine.py`
  - State transitions
  - Agent mapping
  - Validation logic

- `tests/unit/test_conversation_manager.py`
  - Context loading
  - Streaming logic
  - RAG integration

- `tests/unit/test_agent_orchestrator.py`
  - Request routing
  - Agent lifecycle
  - State coordination

- `tests/unit/test_websocket_gateway.py`
  - Message handling
  - Streaming events
  - Error handling

- `tests/unit/test_local_gateway.py`
  - Async/sync conversion
  - UI interaction

**Updated Test Files**:
- `tests/unit/test_*_agent.py`
  - Update for new `process_message()` interface
  - Test business logic only (no UI mocking)

### Integration Tests

**New Test Files**:
- `tests/integration/test_orchestration_flow.py`
  - Full workflow through orchestrator
  - Intake → Assessment → Therapy → Reflection
  - State transitions

- `tests/integration/test_websocket_streaming.py`
  - WebSocket connection
  - Message streaming
  - Event handling

- `tests/integration/test_local_gateway_integration.py`
  - Local UI through gateway
  - Backward compatibility

### End-to-End Tests

**Scenarios**:
1. New user complete flow (local UI)
2. New user complete flow (console UI)
3. New user complete flow (web frontend)
4. Resume intake (all interfaces)
5. Resume therapy session (all interfaces)
6. Concurrent users (WebSocket)

---

## Success Criteria

### Functional Requirements

✅ **Feature Parity**: All UIs provide identical functionality
- Intake workflow
- Assessment with style selection
- RAG-enhanced therapy sessions
- Reflection and plan updates
- Session resumption

✅ **Streaming**: WebSocket clients receive streamed LLM responses
- Chunks emitted in real-time
- Typing indicators
- Progress feedback

✅ **State Management**: Workflow state persists correctly
- Users can disconnect and reconnect
- Session resumption works
- State transitions are valid

✅ **Backward Compatibility**: Local UI continues to work
- Existing tests pass
- Same user experience
- No regression

### Technical Requirements

✅ **Test Coverage**:
- All new components have unit tests
- Integration tests cover workflows
- E2E tests cover all interfaces
- Code coverage > 80%

✅ **Performance**:
- Response time ≤ current implementation
- Streaming starts within 500ms
- No memory leaks
- Handles concurrent users

✅ **Code Quality**:
- Passes linting (ruff)
- Passes formatting (black)
- Type hints (mypy)
- Documentation complete

✅ **Documentation**:
- Architecture diagrams
- API documentation (OpenAPI)
- WebSocket event documentation
- Development guide updated

---

## Future Enhancements

### Phase 2 Enhancements (Post-Launch)

1. **Mobile App Support**
   - Native mobile apps can use same API
   - Push notifications via WebSocket
   - Offline support

2. **Advanced Features**
   - Session pause/resume
   - Interrupt and restart
   - Multi-session support
   - Session sharing

3. **Performance Optimizations**
   - Caching layer (Redis)
   - Connection pooling
   - Load balancing
   - Horizontal scaling

4. **Monitoring**
   - Metrics (Prometheus)
   - Logging (ELK stack)
   - Distributed tracing
   - Error tracking (Sentry)

---

## References

- **Current Implementation**: See `src/main.py`, `src/agents/`, `src/ui/`
- **WebSocket Server**: See `src/unified_server.py`, `src/websocket_server/`
- **Frontend**: See `frontend/src/`
- **Console UI**: See `console-ui/`
- **Testing Guide**: See `tests/README.md`
- **Original Architecture**: See `ARCHITECTURE_IMPROVEMENTS.md`

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2025-11-07 | 1.0 | Initial architecture redesign document |

---

## Contributors

- Hagbard Celine (fwissbrock@gmail.com)
- Claude Code (architecture design assistance)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
