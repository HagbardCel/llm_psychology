# Patient Flow Analysis - Virtual LLM Psychoanalyst Application

**Document Status:** Generated from code analysis (2025-11-23)
**Codebase Version:** Trio-based architecture (post-migration)

---

## Table of Contents

1. [Overview](#overview)
2. [Complete Patient Journey](#complete-patient-journey)
3. [Agent Deep Dive](#agent-deep-dive)
4. [Orchestration Layer](#orchestration-layer)
5. [Database Operations](#database-operations)
6. [Prompting Strategy](#prompting-strategy)
7. [RAG Integration](#rag-integration)
8. [Session Management](#session-management)
9. [Key Data Flows](#key-data-flows)
10. [Potential Improvements](#potential-improvements)

---

## Overview

The Virtual LLM Psychoanalyst application implements a **state-based, agent-orchestrated therapeutic workflow** using Trio's structured concurrency. The system guides patients through:

1. **Intake** - Information gathering
2. **Assessment** - Therapy style recommendation
3. **Therapy** - Ongoing therapeutic sessions
4. **Reflection** - Post-session analysis and plan updates

**Architecture Highlights:**
- Pure Trio concurrency (no asyncio)
- 6 specialized agents
- SQLite persistence
- ChromaDB RAG system
- WebSocket streaming
- State machine workflow

---

## Complete Patient Journey

### State Machine Flow

```
NEW
 ↓ (User creates account / first message)
INTAKE_IN_PROGRESS
 ↓ (80%+ topics covered OR time expires)
INTAKE_COMPLETE
 ↓ (Automated transition)
ASSESSMENT_IN_PROGRESS
 ↓ (User selects therapy style)
ASSESSMENT_COMPLETE
 ↓ (Therapy plan created)
THERAPY_IN_PROGRESS
 ↓ (Session time expires)
REFLECTION_IN_PROGRESS
 ↓ (Analysis complete)
PLAN_COMPLETE
 ↓ (User resumes therapy)
THERAPY_IN_PROGRESS (loop)
```

**Implementation:** `src/orchestration/trio_workflow_engine.py`

### Valid State Transitions

```python
VALID_TRANSITIONS = {
    NEW: [INTAKE_IN_PROGRESS],
    INTAKE_IN_PROGRESS: [INTAKE_COMPLETE, INTAKE_IN_PROGRESS],
    INTAKE_COMPLETE: [ASSESSMENT_IN_PROGRESS],
    ASSESSMENT_IN_PROGRESS: [ASSESSMENT_COMPLETE, ASSESSMENT_IN_PROGRESS],
    ASSESSMENT_COMPLETE: [THERAPY_IN_PROGRESS],
    THERAPY_IN_PROGRESS: [REFLECTION_IN_PROGRESS, THERAPY_IN_PROGRESS],
    REFLECTION_IN_PROGRESS: [PLAN_COMPLETE, REFLECTION_IN_PROGRESS],
    PLAN_COMPLETE: [THERAPY_IN_PROGRESS, PLAN_COMPLETE],
}
```

### State-to-Agent Mapping

```python
STATE_AGENT_MAP = {
    WorkflowState.NEW: "INTAKE",
    WorkflowState.INTAKE_IN_PROGRESS: "INTAKE",
    WorkflowState.INTAKE_COMPLETE: "ASSESSMENT",
    WorkflowState.ASSESSMENT_IN_PROGRESS: "ASSESSMENT",
    WorkflowState.ASSESSMENT_COMPLETE: "THERAPIST",
    WorkflowState.THERAPY_IN_PROGRESS: "THERAPIST",
    WorkflowState.REFLECTION_IN_PROGRESS: "REFLECTION",
    WorkflowState.PLAN_COMPLETE: "THERAPIST",
}
```

---

## Agent Deep Dive

### 1. TrioIntakeAgent

**File:** `src/agents/trio_intake_agent.py`

**States Handled:**
- NEW
- INTAKE_IN_PROGRESS

**Purpose:** Systematic information gathering for therapeutic assessment

#### Key Methods

**`process_message(message, context)`**
- Entry point called by orchestrator
- Handles name collection for guest users
- Routes to intake conversation
- Returns `AgentResponse` with prompts and state transitions

**`_identify_covered_topics(message_history)`**
- Keyword-based topic detection
- Scans entire conversation transcript
- Returns set of covered topics

**`_is_intake_complete(context)`**
- Time-based: Session duration expired
- Topic-based: ≥80% topics covered (9 of 11)
- Minimum duration: ≥50% of session time elapsed

#### Topics Tracked (11 total)

1. Presenting Problem
2. Current Symptoms
3. Personal History
4. Family Background
5. Relationships
6. Work/School
7. Physical Health
8. Mental Health History
9. Substance Use
10. Coping Mechanisms
11. Support System
12. Goals for Therapy

**Detection Method:** Keyword matching in conversation history

```python
topic_keywords = {
    "Presenting Problem": ["problem", "issue", "concern", "struggling"],
    "Current Symptoms": ["symptom", "feeling", "experience", "lately"],
    "Personal History": ["history", "past", "childhood", "grew up"],
    # ... etc
}
```

#### Prompts Used

**INITIAL_GREETING_PROMPT**
- Welcomes user by name
- Introduces role as therapist
- Explains intake purpose
- Establishes safe space
- Duration: {session_duration} minutes

**CONTINUE_CONVERSATION_PROMPT**
- Time awareness: {remaining_minutes} remaining
- Lists covered topics: {covered_topics}
- Lists pending topics: {pending_topics}
- Guidance:
  - Prioritize critical topics
  - Move systematically
  - Show empathy
  - Wrap up if 2-3 minutes remaining

#### Database Operations

**Reads:**
- User profile (to get name, status)
- Session (to get conversation history)

**Writes:**
- User profile (updates status to INTAKE_IN_PROGRESS, then INTAKE_COMPLETE)
- Session messages (via ConversationManager)

#### Returns

```python
AgentResponse(
    content="<prompt_for_llm>",
    next_action="continue" | "transition",
    next_state=WorkflowState.INTAKE_COMPLETE,  # If complete
    metadata={
        "topics_covered": [...],
        "time_remaining_minutes": float,
        "completion_reason": "time_expired" | "topics_covered",
    }
)
```

---

### 2. TrioAssessmentAgent

**File:** `src/agents/trio_assessment_agent.py`

**States Handled:**
- INTAKE_COMPLETE
- ASSESSMENT_IN_PROGRESS

**Purpose:** Evaluate intake data and recommend therapy styles

#### Key Methods

**`process_message(message, context)`**
- Routes to assessment or selection processing
- Distinguishes between initial assessment and user selection

**`process_assessment(context)`**
- Triggers concurrent style evaluations
- Returns recommendations

**`process_selection(selected_style, context)`**
- Validates style selection
- Delegates plan creation to ReflectionAgent
- Returns plan details

**`_generate_recommendations(message_history)`**
- **Concurrent evaluation** via Trio nursery
- Assesses Freud, Jung, CBT in parallel
- Returns dict of style scores and explanations

```python
async with trio.open_nursery() as nursery:
    for style_id in ["freud", "jung", "cbt"]:
        nursery.start_soon(_assess_style, style_id, session_summary, results)
# All evaluations run concurrently
```

**`create_initial_plan_with_style(intake_session, selected_style)`**
- Calls `TrioReflectionAgent.create_initial_plan()`
- Returns therapy plan

#### Assessment Process

**Per Style:**
1. Retrieve style assessment prompt from `StyleService`
2. Build evaluation prompt with intake session summary
3. Call LLM to score fit (0-100)
4. Extract rationale
5. Return recommendation

**Styles Evaluated:**
- **Freud:** Psychoanalytic, unconscious material, childhood patterns
- **Jung:** Analytical psychology, archetypes, individuation
- **CBT:** Present-focused, behavioral techniques, thought patterns

#### Prompts Used

**Assessment Prompts (per style):**
- `src/psychoanalyst_app/styles/freud/assessment_prompt.txt`
- `src/psychoanalyst_app/styles/jung/assessment_prompt.txt`
- `src/psychoanalyst_app/styles/cbt/assessment_prompt.txt`

Each prompt contains:
- Style philosophy
- Evaluation criteria
- Scoring guidelines
- Output format requirements

#### Database Operations

**Reads:**
- Latest session (intake session)
- User profile

**Writes:**
- Therapy plan (via ReflectionAgent)
- User status (ASSESSMENT_IN_PROGRESS → ASSESSMENT_COMPLETE)

#### Returns

**Assessment Phase:**
```python
AgentResponse(
    content="<formatted_recommendations>",
    next_action="await_selection",
    next_state=None,
    metadata={
        "recommendations": {
            "freud": {"score": 85, "rationale": "..."},
            "jung": {"score": 72, "rationale": "..."},
            "cbt": {"score": 65, "rationale": "..."},
        }
    }
)
```

**Selection Phase:**
```python
AgentResponse(
    content="<plan_confirmation>",
    next_action="transition",
    next_state=WorkflowState.ASSESSMENT_COMPLETE,
    metadata={
        "selected_style": "freud",
        "plan_id": "uuid",
    }
)
```

---

### 3. TrioTherapistAgent

**File:** `src/agents/trio_therapist_agent.py`

**States Handled:**
- ASSESSMENT_COMPLETE (first session)
- THERAPY_IN_PROGRESS
- PLAN_COMPLETE (resumption)

**Purpose:** Conduct therapeutic conversations using selected style

#### Key Methods

**`process_message(message, context)`**
- Main message processing entry point
- Routes to initial, continuation, or resumption prompts
- Manages session timing and extensions

**`_build_initial_session_prompt(context)`**
- First session greeting
- Includes therapy plan context
- RAG-augmented with style knowledge

**`_build_resumption_prompt(context, briefing)`**
- Resuming after gap
- **Rich briefing context** from previous session
- Evaluates briefing freshness:
  - FRESH (≤7 days): Use briefing as-is
  - STALE (7-30 days): Use with gap acknowledgment
  - VERY_STALE (>30 days): Fall back to standard initial

**`_build_continuation_prompt(context)`**
- Multi-turn conversation
- Recent history (last 3 messages)
- RAG-retrieved knowledge
- Time awareness

**`_should_offer_extension(context)`**
- Check if ≤5 minutes remaining
- Verify extensions available (max 2)
- Return boolean

#### Session Flow

1. **Initial Greeting:**
   - Check for session briefing in therapy plan
   - If briefing exists and fresh → resumption prompt
   - Otherwise → standard initial prompt

2. **Conversation:**
   - User sends message
   - Agent builds continuation prompt
   - Includes RAG context (style-filtered)
   - LLM streams response

3. **Time Management:**
   - Default session: 30 minutes
   - Check time remaining after each message
   - Offer extension when ≤5 minutes remaining
   - Max extensions: 2 (5 minutes each)

4. **Session End:**
   - Time expires → transition to REFLECTION_IN_PROGRESS
   - Triggers reflection workflow

#### Prompts Used

**Style-Specific Therapist Prompts:**
- `src/psychoanalyst_app/styles/{style_id}/therapist_prompt.txt`

**Freud Example:**
```
You are a Freudian psychoanalyst. Key characteristics:
- Curious about unconscious mind and behavior influence
- Attends to slips of tongue, dreams, free associations
- Explores childhood experiences and lasting impact
- Helps understand id/ego/superego conflicts
- Patient and allows insights to emerge gradually
- Maintains neutral, analytical stance with empathy

Session approach:
- Encourage free association
- Point out patterns, contradictions, unconscious meanings
- Explore dreams (manifest vs latent content)
- Help understand transference feelings
- Focus on root causes, not quick solutions
```

**Resumption Prompt Structure:**
```
You are conducting session #{session_count} with {user_name}

THERAPEUTIC CONTEXT:
- Relationship Stage: {relationship_quality}
- Last Session Date: {last_session_date}

SUPERVISOR'S BRIEFING:
{narrative_handoff}

CLINICAL OBSERVATIONS:
{patient_observations}

TREATMENT PLAN PROGRESSION:
{plan_progression_notes}

EMOTIONAL STATE:
- Current: {emotional_last_session}
- Trend: {emotional_trend}

CONTINUITY POINTS:
1. {continuity_1}
2. {continuity_2}
3. {continuity_3}

CURRENT HIGH-PRIORITY THEMES:
{key_themes}

PROGRESS HIGHLIGHTS:
{progress_highlights}

UNRESOLVED ISSUES:
{unresolved_issues}

RECOMMENDED APPROACH:
- Tone: {opening_tone}
- Focus: {opening_focus}
- Avoid: {things_to_avoid}

SUGGESTED OPENING QUESTIONS:
1. {question_1}
2. {question_2}
3. {question_3}

Generate your opening greeting now.
```

**STALE Briefing Notice:**
```
IMPORTANT - STALE BRIEFING NOTICE:
It has been approximately {days_since} days since the last session.

When generating your greeting:
1. Acknowledge the time gap explicitly but gently
2. Don't assume they're in the same emotional place
3. Be more open-ended and exploratory
4. Focus on "what's been on your mind recently"
5. Use the briefing as background context, not current truth
```

#### RAG Integration

**During Continuation:**
```python
# Retrieve style-specific knowledge
recent_context = " ".join([msg.content for msg in context.message_history[-3:]])
knowledge = await trio.to_thread.run_sync(
    self.rag_service.retrieve_relevant_knowledge,
    recent_context,
    1,  # Top 1 chunk
    context.therapy_plan.selected_therapy_style  # Filter by style
)

# Augment prompt
prompt = f"""
Relevant theoretical context:
{knowledge}

{therapist_prompt}

Continue the session based on:
{conversation_history}
"""
```

#### Database Operations

**Reads:**
- Therapy plan (for style, focus areas, session briefing)
- Session messages (conversation history)
- User profile

**Writes:**
- Session messages (via ConversationManager)
- User status (when transitioning to reflection)

#### Returns

```python
AgentResponse(
    content="<therapist_prompt>",
    next_action="continue" | "transition" | "offer_extension",
    next_state=WorkflowState.REFLECTION_IN_PROGRESS,  # If time up
    metadata={
        "therapy_style": "freud",
        "time_remaining_minutes": float,
        "can_extend": bool,
        "session_briefing_age_days": int,  # If resumption
    }
)
```

---

### 4. TrioReflectionAgent

**File:** `src/agents/trio_reflection_agent.py`

**States Handled:**
- REFLECTION_IN_PROGRESS

**Purpose:** Analyze completed sessions and update therapy plans

#### Key Methods

**`process_reflection(session, context)`**
- Main entry point for post-session analysis
- Orchestrates memory and planning agents
- Generates session briefing
- Updates therapy plan

**`update_plan(session, current_plan)`**
- Delegates to `TrioPlanningAgent.update_plan()`
- Returns updated therapy plan

**`generate_comprehensive_reflection(session, context)`**
- Combines memory analysis and plan assessment
- Returns structured reflection data

**`_generate_session_briefing(session, context, memory, plan_assessment)`**
- **CRITICAL:** Creates rich briefing for next session
- LLM-based analysis
- Validates output using Pydantic `SessionBriefing` model
- Includes continuity context, themes, recommendations

**`generate_session_summary(session)`**
- LLM-based summary of session
- Used for plan updates

#### Reflection Workflow

1. **Memory Analysis (TrioMemoryAgent):**
   - Extract key themes from transcript
   - Analyze emotional state progression
   - Identify progress indicators
   - Update recurring theme tracking

2. **Planning Assessment (TrioPlanningAgent):**
   - Evaluate current plan effectiveness
   - Recommend adjustments if needed
   - Generate updated plan (version incremented)

3. **Session Briefing Generation:**
   - Combine memory + planning insights
   - LLM creates comprehensive JSON briefing
   - Includes:
     - Narrative handoff
     - Patient observations
     - Plan progression notes
     - Relationship quality
     - Continuity points
     - Emotional summary with trend
     - Key themes with priority
     - Progress highlights
     - Unresolved issues
     - Recommended approach for next session

4. **Persistence:**
   - Save updated therapy plan with embedded briefing
   - Increment plan version
   - Update user status to PLAN_COMPLETE

#### Session Briefing Structure

```json
{
  "briefing_type": "resumption",
  "generated_at": "2025-11-23T10:30:00",
  "session_count": 5,
  "last_session_id": "uuid",
  "last_session_date": "2025-11-23",
  "narrative_handoff": "In this session, the patient explored their recurring anxiety about work deadlines...",
  "patient_observations": "Patient was engaged and reflective, demonstrating growing insight...",
  "plan_progression_notes": "Made significant progress on Goal 2 (understanding anxiety triggers)...",
  "relationship_quality": "developing",
  "continuity_points": [
    "Follow up on the dream about their father that was mentioned briefly",
    "Explore the connection between work anxiety and childhood perfectionism",
    "Check in on the journaling practice suggested last session"
  ],
  "emotional_summary": {
    "last_session": "anxious but hopeful",
    "trend": "improving",
    "note": "Patient showed more emotional regulation compared to previous sessions"
  },
  "key_themes": [
    {
      "theme": "Work-related anxiety",
      "status": "ongoing",
      "priority": "high",
      "frequency": 4,
      "first_appearance": "session-001",
      "last_discussed": "session-005"
    },
    {
      "theme": "Childhood perfectionism",
      "status": "newly_introduced",
      "priority": "medium",
      "frequency": 1,
      "first_appearance": "session-005",
      "last_discussed": "session-005"
    }
  ],
  "progress_highlights": [
    "Successfully identified connection between current anxiety and past experiences",
    "Demonstrated willingness to explore uncomfortable emotions"
  ],
  "unresolved_issues": [
    "Resistance to discussing family dynamics",
    "Avoidance of intimacy topics in relationships"
  ],
  "recommended_approach": {
    "opening_tone": "Warm and welcoming",
    "opening_focus": "Follow up on the dream mentioned last session and explore father relationship",
    "things_to_avoid": "Pushing too hard on family topics if resistance continues",
    "suggested_questions": [
      "How have you been feeling since our last session?",
      "I'm curious about the dream you mentioned - would you like to explore that?",
      "Have you noticed any patterns in your anxiety this week?"
    ],
    "therapeutic_goals_for_session": [
      "Deepen exploration of childhood-present anxiety connection",
      "Build on last session's insight about perfectionism",
      "Gently probe family dynamics if patient shows openness"
    ]
  }
}
```

#### Prompts Used

**SESSION_SUMMARY_PROMPT:**
- Concise summary of session
- Key points discussed
- Emotional tone
- Progress indicators

**Reflection Prompts (from StyleService):**
- `src/psychoanalyst_app/styles/{style_id}/reflection_prompt.txt`
- Style-specific analysis guidance

**Briefing Generation Prompt:**
```
You are an experienced clinical supervisor providing a briefing for the therapist who will conduct the next session.

Based on the session transcript and therapeutic context, create a comprehensive briefing that includes:
1. A narrative handoff (3-4 sentences summarizing the session arc)
2. Clinical observations about the patient's communication style and engagement
3. Notes on how this session advanced the treatment plan
4. Assessment of relationship quality (building/developing/established/strong)
5. Top 3 continuity points for follow-up
6. Emotional state summary with trend
7. Key themes with status and priority
8. Progress highlights
9. Unresolved issues
10. Recommended approach for opening the next session

Format your response as valid JSON matching the SessionBriefing schema.
```

#### Database Operations

**Reads:**
- Session (to analyze)
- Therapy plan (current plan)
- All user sessions (for memory aggregation)

**Writes:**
- Updated therapy plan with:
  - Incremented version
  - Updated plan_details
  - Embedded session_briefing JSON

#### Returns

```python
AgentResponse(
    content="<formatted_reflection_summary>",
    next_action="transition",
    next_state=WorkflowState.PLAN_COMPLETE,
    metadata={
        "plan_id": "uuid",
        "plan_version": int,
        "reflection_data": {...},
        "briefing_generated": bool,
    }
)
```

---

### 5. TrioMemoryAgent

**File:** `src/agents/trio_memory_agent.py`

**Purpose:** Manage session context and therapeutic memory across sessions

**NOT a workflow agent** - called by TrioReflectionAgent

#### Key Classes

**SessionContext:**
```python
session_id: str
timestamp: datetime
key_themes: list[str]          # Extracted themes
emotional_state: str           # Overall emotional tone
insights: list[str]            # Key insights/breakthroughs
progress_indicators: list[str] # Signs of progress
```

**TherapeuticMemory:**
```python
session_contexts: list[SessionContext]
recurring_themes: dict[str, int]        # Theme frequency
emotional_patterns: list[str]           # Progression over time
progress_timeline: list[dict]           # Chronological progress
relationship_quality: str               # Current quality
```

#### Key Methods

**`analyze_session_context(session)`**
- LLM-based analysis of session transcript
- Extracts themes, emotional state, insights
- Returns `SessionContext` object

**`get_therapeutic_memory(user_id)`**
- Aggregates memory across all sessions
- Returns `TherapeuticMemory` object

**`identify_patterns(sessions)`**
- Detects recurring themes
- Analyzes emotional progression
- Identifies treatment trajectory

**`get_continuity_context(topics, user_id)`**
- Provides context for follow-up
- Retrieves relevant past discussions
- Supports seamless session resumption

#### Used By

- `TrioReflectionAgent.generate_comprehensive_reflection()`
- `TrioPlanningAgent.update_plan()` (for context)

---

### 6. TrioPlanningAgent

**File:** `src/agents/trio_planning_agent.py`

**Purpose:** Create and update personalized therapy plans

**NOT a workflow agent** - called by TrioReflectionAgent and TrioAssessmentAgent

#### Key Classes

**PlanningStrategy:**
```python
style_id: str
focus_areas: list[str]
techniques: list[str]
assessment_criteria: list[str]
```

**PlanEvolution:**
```python
version: int
changes: list[str]
rationale: str
timestamp: datetime
```

#### Key Methods

**`create_initial_plan(intake_session, selected_style)`**
- Creates first therapy plan
- Based on intake data and selected style
- Returns `TherapyPlan` object

**`update_plan(session, current_plan)`**
- Updates existing plan based on session
- Increments version
- Returns updated `TherapyPlan`

**`assess_plan_effectiveness(current_plan, memory)`**
- Evaluates current plan success
- Uses therapeutic memory for context
- Returns effectiveness rating and recommendations

**`recommend_plan_adjustments(current_plan, session_context)`**
- Suggests specific changes
- Returns list of recommended adjustments

#### Therapy Plan JSON Structure

```json
{
  "focus": "Primary therapeutic focus areas based on intake and style",
  "goals": "Specific, measurable therapeutic goals for the patient",
  "techniques": "Style-specific techniques to employ (e.g., dream analysis, free association for Freud)",
  "themes": "Key themes to explore during therapy sessions"
}
```

#### Prompts Used

**CREATE_INITIAL_PLAN_PROMPT:**
```
Based on the intake session, create a personalized therapy plan using {style} approach.

Intake Summary:
{session_summary}

Style Guidance:
{style_description}

Create a plan with:
1. Primary focus areas
2. Specific therapeutic goals
3. Recommended techniques (style-appropriate)
4. Key themes to explore

Format as JSON: {"focus": "...", "goals": "...", "techniques": "...", "themes": "..."}
```

**UPDATE_PLAN_PROMPT:**
```
Update the therapy plan based on the latest session.

Current Plan:
{current_plan}

Session Analysis:
{session_summary}

Therapeutic Memory:
{memory_context}

Assess effectiveness and recommend adjustments while maintaining {style} approach.

Return updated plan as JSON.
```

#### Used By

- `TrioAssessmentAgent.create_initial_plan_with_style()` (initial plan)
- `TrioReflectionAgent.update_plan()` (updates)

---

## Orchestration Layer

### TrioAgentOrchestrator

**File:** `src/orchestration/trio_agent_orchestrator.py`

**Purpose:** Main entry point for routing messages to agents

#### Key Responsibilities

1. **Session Management**
   - Create/retrieve sessions
   - Initialize conversation context

2. **Agent Routing**
   - Determine current workflow state
   - Get appropriate agent for state
   - Cache agent instances per user

3. **Message Processing**
   - Add user messages to history
   - Process through agent
   - Stream LLM responses
   - Handle state transitions

4. **State Transitions**
   - Validate transitions
   - Update user status
   - Clear context cache

#### Message Processing Pipeline

```python
async def process_message(user_id, message, session_id=None):
    # 1. Get or create session
    if not session_id:
        session_id = await _create_session(user_id)

    # 2. Add user message to history
    if message.strip():
        await conversation_manager.add_message(session_id, "user", message)

    # 3. Get workflow state
    state = await workflow_engine.get_user_state(user_id)

    # 4. Handle NEW state: create guest profile if needed
    if state == WorkflowState.NEW:
        user_profile = await db_service.get_user_profile(user_id)
        if not user_profile:
            await create_user_profile(user_id, "Guest", "", "")

    # 5. Route to appropriate agent
    agent_type = workflow_engine.get_current_agent(state)
    agent = await _get_or_create_agent(agent_type, user_id)

    # 6. Get conversation context
    context = await conversation_manager.get_context(session_id)

    # 7. Process through agent
    agent_response = await agent.process_message(message, context)

    # 8. Stream response
    if agent_response.metadata.get("is_direct_response"):
        async for chunk in conversation_manager.stream_static_response(
            agent_response.content, context
        ):
            yield chunk
    else:
        async for chunk in conversation_manager.stream_response(
            agent_response.content, context
        ):
            yield chunk

    # 9. Handle state transitions
    await _handle_agent_response(user_id, session_id, agent_response)
```

#### Agent Caching

```python
# Cache key: "{agent_type}_{user_id}"
agent_cache = {}

async def _get_or_create_agent(agent_type, user_id):
    cache_key = f"{agent_type}_{user_id}"

    if cache_key not in agent_cache:
        if agent_type == "INTAKE":
            agent_cache[cache_key] = await _create_intake_agent(user_id)
        elif agent_type == "ASSESSMENT":
            agent_cache[cache_key] = await _create_assessment_agent(user_id)
        # etc.

    return agent_cache[cache_key]
```

**Benefits:**
- Reuse agent instances across messages
- Maintain agent-specific state
- Reduce initialization overhead

#### Session Initialization

```python
async def start_session(user_id, session_type):
    # Create new session
    session_id = await _create_session(user_id)

    # Send proactive greeting for certain states
    state = await workflow_engine.get_user_state(user_id)

    if state in [WorkflowState.NEW, WorkflowState.INTAKE_IN_PROGRESS,
                 WorkflowState.THERAPY_IN_PROGRESS]:
        # Get agent and context
        agent = await _get_or_create_agent(...)
        context = await conversation_manager.get_context(session_id)

        # Process empty message to trigger greeting
        agent_response = await agent.process_message("", context)

        # Stream greeting
        async for chunk in conversation_manager.stream_response(...):
            # Send via WebSocket

    return SessionInfo(session_id=session_id, initial_message_sent=True)
```

---

### TrioConversationManager

**File:** `src/orchestration/trio_conversation_manager.py`

**Purpose:** Streaming, context management, and RAG integration

#### Key Responsibilities

1. **Context Management**
   - Cache `ConversationContext` objects by session_id
   - Load from database on cache miss
   - Provide time-aware context

2. **Message Persistence**
   - Save user and assistant messages
   - Maintain complete transcript
   - Non-blocking (don't fail on errors)

3. **LLM Streaming**
   - Stream responses chunk-by-chunk
   - WebSocket delivery
   - Typing indicators

4. **RAG Integration**
   - Retrieve style-specific knowledge
   - Augment prompts with context
   - Filter by therapy style

#### Streaming Pipeline

```python
async def stream_response(prompt, context, use_rag=True):
    # 1. Retrieve RAG context if therapy plan exists
    rag_context = ""
    if use_rag and context.therapy_plan:
        rag_context = await _retrieve_rag_context(
            prompt,
            context.therapy_plan.selected_therapy_style
        )

        # Augment prompt
        augmented_prompt = f"""
Relevant theoretical context:
{rag_context}

Based on the above context and your therapeutic approach:
{prompt}
"""
    else:
        augmented_prompt = prompt

    # 2. Build conversation history (last 10 messages)
    conversation_history = _build_conversation_history(context)

    # 3. Stream from LLM
    full_response = ""
    async for chunk in _stream_llm_response(augmented_prompt, conversation_history):
        full_response += chunk
        yield chunk

    # 4. Persist assistant message (non-critical)
    await add_message(context.session_id, "assistant", full_response)
```

#### RAG Context Retrieval

```python
async def _retrieve_rag_context(query, therapy_style):
    # Run synchronously in thread
    relevant_docs = await trio.to_thread.run_sync(
        self.rag_service.retrieve_relevant_knowledge,
        query,              # User message or recent context
        3,                  # Top 3 results
        therapy_style       # Filter by source (freud/jung/cbt)
    )

    # Format as context
    return "\n\n".join([doc["content"] for doc in relevant_docs])
```

#### Context Caching

```python
context_cache = {}  # {session_id: ConversationContext}

async def get_context(session_id):
    if session_id not in context_cache:
        # Load from database
        session = await db_service.get_session(session_id)
        user_profile = await db_service.get_user_profile(session.user_id)
        therapy_plan = await db_service.get_current_therapy_plan(session.user_id)

        # Build context
        context_cache[session_id] = ConversationContext(
            session_id=session_id,
            user_profile=user_profile,
            therapy_plan=therapy_plan,
            message_history=session.transcript,
            topics_covered=session.topics,
            session_start_time=session.timestamp,
            duration_minutes=30,
            extensions_used=0,
            max_extensions=2,
        )

    return context_cache[session_id]
```

#### WebSocket Management

```python
websockets = {}  # {session_id: WebSocket}

async def register_websocket(session_id, websocket):
    websockets[session_id] = websocket

async def send_chunk(session_id, chunk):
    if session_id in websockets:
        await websockets[session_id].send(chunk)
```

---

### TrioWorkflowEngine

**File:** `src/orchestration/trio_workflow_engine.py`

**Purpose:** State machine for workflow transitions

#### Key Responsibilities

1. **State Retrieval**
   - Map user status to workflow state
   - Determine current agent

2. **State Transitions**
   - Validate transitions
   - Update database
   - Enforce state machine rules

3. **Event Processing**
   - Map events to next states
   - Handle workflow logic

#### Core Methods

**`get_user_state(user_id)`**
```python
async def get_user_state(user_id):
    user_profile = await db_service.get_user_profile(user_id)
    if not user_profile:
        return WorkflowState.NEW

    # Map UserStatus to WorkflowState
    status_to_state = {
        UserStatus.PROFILE_ONLY: WorkflowState.NEW,
        UserStatus.INTAKE_IN_PROGRESS: WorkflowState.INTAKE_IN_PROGRESS,
        UserStatus.INTAKE_COMPLETE: WorkflowState.INTAKE_COMPLETE,
        # etc.
    }

    return status_to_state[user_profile.status]
```

**`transition(user_id, new_state)`**
```python
async def transition(user_id, new_state):
    current_state = await get_user_state(user_id)

    # Validate transition
    if not can_transition(current_state, new_state):
        raise InvalidTransitionError(...)

    # Map WorkflowState to UserStatus
    state_to_status = {
        WorkflowState.INTAKE_IN_PROGRESS: UserStatus.INTAKE_IN_PROGRESS,
        WorkflowState.INTAKE_COMPLETE: UserStatus.INTAKE_COMPLETE,
        # etc.
    }

    # Update database
    await db_service.update_user_status(user_id, state_to_status[new_state])
```

**`can_transition(from_state, to_state)`**
```python
def can_transition(from_state, to_state):
    return to_state in VALID_TRANSITIONS.get(from_state, [])
```

**`get_current_agent(state)`**
```python
def get_current_agent(state):
    return STATE_AGENT_MAP.get(state, "UNKNOWN")
```

---

## Database Operations

### Schema

**SQLite Database:** `data/psychoanalyst.db`

#### Table: user_profiles

```sql
CREATE TABLE user_profiles (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    birthdate TEXT,                    -- ISO format or NULL
    profession TEXT,                   -- Optional
    status TEXT NOT NULL,              -- UserStatus enum
    created_at TEXT NOT NULL,          -- ISO datetime
    updated_at TEXT NOT NULL           -- ISO datetime
)
```

**UserStatus Values:**
- PROFILE_ONLY
- INTAKE_IN_PROGRESS
- INTAKE_COMPLETE
- ASSESSMENT_IN_PROGRESS
- ASSESSMENT_COMPLETE
- THERAPY_IN_PROGRESS
- REFLECTION_IN_PROGRESS
- PLAN_COMPLETE

#### Table: sessions

```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,           -- ISO datetime
    transcript TEXT NOT NULL,          -- JSON array of messages
    topics TEXT                        -- JSON array of topics
)
```

**Transcript JSON:**
```json
[
  {
    "role": "user",
    "content": "I've been feeling anxious lately...",
    "timestamp": "2025-11-23T10:15:30"
  },
  {
    "role": "assistant",
    "content": "I hear that you've been experiencing anxiety...",
    "timestamp": "2025-11-23T10:15:45"
  }
]
```

#### Table: therapy_plans

```sql
CREATE TABLE therapy_plans (
    plan_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,          -- ISO datetime
    updated_at TEXT NOT NULL,          -- ISO datetime
    plan_details TEXT NOT NULL,        -- JSON with focus, goals, techniques, themes
    version INTEGER NOT NULL,          -- Incremented on each update
    selected_therapy_style TEXT,       -- "freud", "jung", or "cbt"
    session_briefing TEXT              -- JSON SessionBriefing (added in migration_002)
)
```

**Plan Details JSON:**
```json
{
  "focus": "Understanding the connection between childhood experiences and current anxiety patterns",
  "goals": "1) Identify unconscious triggers of anxiety, 2) Develop insight into defense mechanisms, 3) Explore transference in relationships",
  "techniques": "Free association, dream analysis, interpretation of resistance, exploration of childhood memories",
  "themes": "Childhood abandonment fears, perfectionism, authority figures, intimacy avoidance"
}
```

**Session Briefing JSON:**
See [SessionBriefing structure](#session-briefing-structure) in Reflection Agent section.

### TrioDatabaseService

**File:** `src/services/trio_db_service.py`

**Implementation:**
- Synchronous `sqlite3` module
- Operations run in worker threads via `trio.to_thread.run_sync`
- Connection pooling (5 connections)
- Automatic migrations

#### Key Methods

**User Profile Operations:**
```python
await save_user_profile(user_profile: UserProfile)
await get_user_profile(user_id: str) -> UserProfile | None
await update_user_status(user_id: str, status: UserStatus)
```

**Session Operations:**
```python
await save_session(session: Session)
await get_session(session_id: str) -> Session | None
await get_user_sessions(user_id: str, limit: int = 10) -> list[Session]
await update_session_transcript(session_id: str, transcript: list[Message])
```

**Therapy Plan Operations:**
```python
await save_therapy_plan(plan: TherapyPlan)
await get_therapy_plan(plan_id: str) -> TherapyPlan | None
await get_current_therapy_plan(user_id: str) -> TherapyPlan | None
```

**Migration Operations:**
```python
await run_migrations()
```

#### Migration System

**Location:** `src/services/migrations/`

**Migrations:**
1. `migration_001_initial_schema.py` - Initial tables
2. `migration_002_add_session_briefing.py` - Add session_briefing column

**Execution:**
- Tracks applied migrations in `schema_migrations` table
- Runs on service initialization
- Sequential execution

---

## Prompting Strategy

### Prompt Types

#### 1. Agent System Prompts

**Location:** `src/psychoanalyst_app/styles/{style_id}/therapist_prompt.txt`

**Purpose:** Define therapist personality and approach

**Structure:**
- Role definition
- Key characteristics
- Session approach
- Do's and don'ts
- Communication style

**Example (Freud):**
```
You are a Freudian psychoanalyst conducting a therapy session.

ROLE: You embody classical psychoanalytic principles...

KEY CHARACTERISTICS:
- Deeply curious about the unconscious mind
- Attentive to slips of the tongue, dreams, free associations
- Explore childhood experiences and their lasting impact
...

SESSION APPROACH:
- Encourage free association
- Point out patterns and contradictions
- Explore dreams (manifest vs latent content)
...

WHAT TO AVOID:
- Quick fixes or symptom-focused advice
- Excessive self-disclosure
- Judgmental language
```

#### 2. Continuation Prompts

**Built dynamically in agents**

**Components:**
- System prompt (therapist role)
- Current context (therapy plan, time remaining)
- RAG-augmented knowledge
- Recent conversation history
- Specific instructions for response

**Example:**
```
{therapist_prompt}

CURRENT THERAPEUTIC FOCUS:
{therapy_plan.focus}

RELEVANT PSYCHOLOGICAL KNOWLEDGE:
{rag_context}

CONVERSATION HISTORY:
User: {message_n-2}
Assistant: {response_n-2}
User: {message_n-1}
Assistant: {response_n-1}

TIME REMAINING: {time_remaining} minutes

Continue the therapeutic conversation based on the above context.
```

#### 3. Assessment Prompts

**Location:** `src/psychoanalyst_app/styles/{style_id}/assessment_prompt.txt`

**Purpose:** Evaluate patient fit for therapy style

**Structure:**
- Style philosophy
- Evaluation criteria
- Scoring guidelines (0-100)
- Output format requirements

**Example:**
```
Evaluate the patient's suitability for Freudian psychoanalysis.

STYLE PHILOSOPHY:
Freudian psychoanalysis focuses on...

EVALUATION CRITERIA:
1. Presence of unconscious conflicts
2. Willingness to explore childhood
3. Ability to free associate
4. Interest in dreams and symbolism
5. Tolerance for long-term work

SCORING:
Rate 0-100 based on:
- 90-100: Ideal candidate
- 70-89: Good fit
- 50-69: Moderate fit
- <50: Better suited for other approaches

OUTPUT FORMAT:
{
  "score": 85,
  "rationale": "Patient shows strong indicators for psychoanalytic work..."
}
```

#### 4. Reflection Prompts

**Location:** `src/psychoanalyst_app/styles/{style_id}/reflection_prompt.txt`

**Purpose:** Guide post-session analysis

**Structure:**
- Analysis framework
- Focus areas
- Assessment criteria
- Output format

**Example:**
```
Analyze this therapy session from a Freudian perspective.

ANALYSIS FRAMEWORK:
1. Unconscious material revealed
2. Defense mechanisms observed
3. Transference dynamics
4. Resistance patterns
5. Progress toward insight

FOCUS AREAS:
- What unconscious conflicts emerged?
- What childhood material was accessed?
- What resistance was encountered?
- What therapeutic movement occurred?

Provide structured analysis as JSON.
```

#### 5. Session Briefing Prompt

**Built in TrioReflectionAgent**

**Purpose:** Generate comprehensive briefing for next session

**Structure:**
- Supervisor role definition
- Session context
- Therapeutic memory
- Required output fields
- JSON schema validation

**Template:**
```
You are an experienced clinical supervisor providing a briefing for the therapist conducting the next session.

SESSION CONTEXT:
- Session #{session_count}
- Patient: {user_name}
- Style: {therapy_style}
- Date: {session_date}

TRANSCRIPT:
{session_transcript}

CURRENT THERAPY PLAN:
{plan_details}

THERAPEUTIC MEMORY:
- Total sessions: {total_sessions}
- Recurring themes: {recurring_themes}
- Emotional progression: {emotional_patterns}
- Relationship quality: {relationship_quality}

INSTRUCTIONS:
Create a comprehensive briefing that includes:
1. Narrative handoff (3-4 sentences)
2. Clinical observations
3. Plan progression notes
4. Relationship quality assessment
5. Top 3 continuity points
6. Emotional summary with trend
7. Key themes with status and priority
8. Progress highlights
9. Unresolved issues
10. Recommended approach for next session

Format as valid JSON matching SessionBriefing schema:
{json_schema}
```

---

## RAG Integration

### RAG Service

**File:** `src/services/rag_service.py`

**Vector Database:** ChromaDB at `data/vector_db/`

#### Knowledge Sources

**Location:** `data/domain_knowledge/`

**Files:**
- `freud.md` - Freudian psychoanalytic theory
- `jung.md` - Jungian analytical psychology
- `cbt.md` - Cognitive behavioral therapy

**Content:**
- Theoretical foundations
- Key concepts
- Therapeutic techniques
- Clinical applications
- Research findings

#### Retrieval Process

```python
def retrieve_relevant_knowledge(query, top_k, source_filter=None):
    # 1. Query vector database
    results = chroma_client.query(
        collection_name="psychological_knowledge",
        query_texts=[query],
        n_results=top_k,
        where={"source": source_filter} if source_filter else None
    )

    # 2. Format results
    return [
        {
            "content": result["document"],
            "source": result["metadata"]["source"],
            "relevance": result["distance"],
        }
        for result in results
    ]
```

#### Integration Points

**1. During Therapy Sessions (TrioTherapistAgent):**
```python
# Retrieve knowledge based on recent conversation
recent_context = " ".join([msg.content for msg in context.message_history[-3:]])
knowledge = await trio.to_thread.run_sync(
    self.rag_service.retrieve_relevant_knowledge,
    recent_context,
    1,  # Top 1 chunk
    context.therapy_plan.selected_therapy_style
)

# Augment prompt
augmented_prompt = f"""
Relevant theoretical context:
{knowledge[0]["content"]}

{therapist_prompt}

Continue the therapeutic conversation.
"""
```

**2. During Streaming (TrioConversationManager):**
```python
# Retrieve context for user message
if use_rag and context.therapy_plan:
    rag_context = await _retrieve_rag_context(
        prompt,
        context.therapy_plan.selected_therapy_style
    )

    # Augment before sending to LLM
    augmented_prompt = _augment_prompt(prompt, rag_context)
```

#### Benefits

- **Style-specific knowledge:** Filter by therapy style
- **Context-aware:** Retrieves relevant theory for current topic
- **Scalable:** Add new knowledge sources easily
- **Transparent:** LLM sees source material in prompt

---

## Session Management

### Session Lifecycle

#### 1. Session Creation

```python
# In TrioAgentOrchestrator
async def start_session(user_id, session_type):
    # Create session record
    session_id = str(uuid.uuid4())
    session = Session(
        session_id=session_id,
        user_id=user_id,
        timestamp=datetime.now(),
        transcript=[],
        topics=[],
    )
    await db_service.save_session(session)

    # Initialize context
    context = await conversation_manager.get_context(session_id)

    # Send proactive greeting if applicable
    state = await workflow_engine.get_user_state(user_id)
    if state in [NEW, INTAKE_IN_PROGRESS, THERAPY_IN_PROGRESS]:
        await _send_initial_greeting(user_id, session_id, state)

    return SessionInfo(session_id=session_id, initial_message_sent=True)
```

#### 2. Message Processing

```python
# User sends message
User → WebSocket → Server

# Server processes
1. Add message to session transcript
2. Get workflow state
3. Route to appropriate agent
4. Agent returns prompt
5. Stream LLM response
6. Save assistant message
7. Handle state transitions
```

#### 3. Time Management

**ConversationContext Properties:**
```python
@property
def time_elapsed_minutes(self) -> float:
    elapsed = datetime.now() - self.session_start_time
    return elapsed.total_seconds() / 60

@property
def time_remaining_minutes(self) -> float:
    total = self.duration_minutes + (self.extensions_used * 5)
    return total - self.time_elapsed_minutes

@property
def is_time_up(self) -> bool:
    return self.time_remaining_minutes <= 0

@property
def can_extend(self) -> bool:
    return self.extensions_used < self.max_extensions
```

**Extension Handling:**
```python
# In TrioTherapistAgent
if self._should_offer_extension(context):
    return AgentResponse(
        content="<extension_offer_prompt>",
        next_action="offer_extension",
        next_state=None,
        metadata={"can_extend": True}
    )
```

#### 4. Session Completion

**Therapy Session End:**
```python
# When time expires
if context.is_time_up:
    return AgentResponse(
        content="<closing_prompt>",
        next_action="transition",
        next_state=WorkflowState.REFLECTION_IN_PROGRESS,
        metadata={"reason": "time_expired"}
    )
```

**Reflection Trigger:**
```python
# In TrioAgentOrchestrator
if agent_response.next_state == WorkflowState.REFLECTION_IN_PROGRESS:
    # Transition to reflection
    await workflow_engine.transition(user_id, WorkflowState.REFLECTION_IN_PROGRESS)

    # Run reflection
    reflection_agent = await _get_or_create_agent("REFLECTION", user_id)
    await reflection_agent.process_reflection(session, context)
```

### Session Resumption

**Briefing-Aware Resumption:**

```python
# In TrioTherapistAgent._build_initial_session_prompt()

# Check if therapy plan has briefing
if context.therapy_plan and context.therapy_plan.session_briefing:
    briefing = context.therapy_plan.session_briefing

    # Evaluate briefing age
    briefing_status = _get_briefing_status(briefing)

    if briefing_status == BriefingStatus.FRESH:
        # Use briefing as-is
        return _build_resumption_prompt(context, briefing, stale=False)

    elif briefing_status == BriefingStatus.STALE:
        # Use with gap notice
        return _build_resumption_prompt(context, briefing, stale=True)

    else:  # VERY_STALE
        # Fall back to standard initial
        return _build_initial_session_prompt(context)
else:
    # First session
    return _build_initial_session_prompt(context)
```

**Briefing Freshness:**
- **FRESH (≤7 days):** Full briefing context, assume continuity
- **STALE (7-30 days):** Briefing with gap acknowledgment
- **VERY_STALE (>30 days):** Standard initial greeting

---

## Key Data Flows

### Flow 1: Initial Onboarding (NEW → PLAN_COMPLETE)

```
1. User connects → WebSocket established
2. User sends first message
3. Orchestrator creates guest profile (status=NEW)
4. Orchestrator transitions to INTAKE_IN_PROGRESS
5. IntakeAgent greets user, asks for name
6. User provides name
7. IntakeAgent updates profile.name
8. IntakeAgent conducts structured intake
9. User answers questions across 11 topics
10. IntakeAgent tracks topics and time
11. When 80%+ topics covered OR time expires:
    - IntakeAgent transitions to INTAKE_COMPLETE
12. AssessmentAgent takes over
13. AssessmentAgent concurrently evaluates 3 styles
14. AssessmentAgent presents recommendations
15. User selects therapy style (e.g., "freud")
16. AssessmentAgent calls ReflectionAgent
17. ReflectionAgent calls PlanningAgent
18. PlanningAgent creates initial TherapyPlan
19. Plan saved to database (version=1)
20. Status updated to ASSESSMENT_COMPLETE
21. TherapistAgent ready for first session
```

**Database Operations:**
- `save_user_profile(user_id, name="Guest", status=NEW)`
- `update_user_status(user_id, INTAKE_IN_PROGRESS)`
- `save_session(session_id, transcript=[...])`
- `update_session_transcript(session_id, transcript)`
- `update_user_status(user_id, INTAKE_COMPLETE)`
- `update_user_status(user_id, ASSESSMENT_IN_PROGRESS)`
- `save_therapy_plan(plan_id, user_id, plan_details, version=1, style="freud")`
- `update_user_status(user_id, ASSESSMENT_COMPLETE)`

### Flow 2: Therapy Session (THERAPY_IN_PROGRESS → PLAN_COMPLETE)

```
1. User starts new session
2. Orchestrator checks status: ASSESSMENT_COMPLETE or PLAN_COMPLETE
3. TherapistAgent takes over
4. If PLAN_COMPLETE with fresh briefing:
   - Load session_briefing from therapy_plan
   - Build resumption prompt with rich context
   - Send greeting acknowledging continuity
5. Else (first session):
   - Build initial greeting with therapy plan
   - Include RAG context (style-specific knowledge)
6. User shares thoughts/feelings
7. TherapistAgent:
   - Gets recent conversation context
   - Retrieves RAG knowledge (top 1 chunk)
   - Builds continuation prompt
   - LLM streams response
8. Repeat steps 6-7 for ~30 minutes
9. When ≤5 minutes remaining and can_extend:
   - Offer extension
10. When time expires:
    - TherapistAgent transitions to REFLECTION_IN_PROGRESS
11. ReflectionAgent takes over:
    - Calls MemoryAgent → analyze session
    - Calls PlanningAgent → assess plan effectiveness
    - Generates comprehensive session briefing (LLM)
    - Updates therapy plan (version incremented)
    - Embeds session_briefing JSON in plan
12. Transition to PLAN_COMPLETE
13. Ready for next session resumption
```

**Database Operations:**
- `get_current_therapy_plan(user_id)` → Load briefing
- `save_session(session_id, transcript=[...])`
- `update_session_transcript(session_id, transcript)` (after each message)
- `get_user_sessions(user_id, limit=10)` → For memory analysis
- `save_therapy_plan(plan_id, user_id, plan_details, version=2, session_briefing={...})`
- `update_user_status(user_id, PLAN_COMPLETE)`

### Flow 3: RAG Context Retrieval

```
1. User sends message in therapy session
2. TherapistAgent extracts recent context (last 3 messages)
3. ConversationManager checks if therapy_plan exists
4. If therapy_plan:
   - Extract selected_therapy_style (e.g., "freud")
   - Call RAGService.retrieve_relevant_knowledge(
       query=recent_context,
       top_k=1,
       source_filter="freud"
     )
5. RAGService queries ChromaDB:
   - Embed query using embedding model
   - Semantic search in vector DB
   - Filter by source metadata
   - Return top 1 most relevant chunk
6. Format retrieved knowledge
7. Augment prompt:
   ```
   Relevant theoretical context:
   {retrieved_knowledge}

   {therapist_prompt}

   Continue the session.
   ```
8. Send augmented prompt to LLM
9. Stream response to user
```

**RAG Execution:**
- Synchronous ChromaDB operation
- Run in thread: `await trio.to_thread.run_sync(rag_service.retrieve_relevant_knowledge, ...)`
- Non-blocking for Trio event loop

### Flow 4: Session Briefing Generation

```
1. Therapy session completes (time expires)
2. ReflectionAgent.process_reflection() called
3. MemoryAgent analyzes session:
   - Extract key themes
   - Analyze emotional state
   - Identify insights/breakthroughs
   - Track progress indicators
4. MemoryAgent aggregates therapeutic memory:
   - Load all user sessions from DB
   - Identify recurring themes
   - Track emotional progression
   - Assess relationship quality
5. PlanningAgent assesses plan effectiveness:
   - Evaluate current plan against session
   - Recommend adjustments
   - Generate updated plan
6. ReflectionAgent generates briefing:
   - Build comprehensive prompt with:
     - Session transcript
     - Memory analysis
     - Plan assessment
     - SessionBriefing JSON schema
   - Call LLM (synchronous in thread)
   - Parse JSON response
   - Validate against Pydantic SessionBriefing model
7. ReflectionAgent updates therapy plan:
   - Increment plan.version
   - Update plan_details (if changes)
   - Embed session_briefing JSON
   - Save to database
8. Transition to PLAN_COMPLETE
```

**LLM Output Validation:**
```python
try:
    briefing_json = json.loads(llm_response)
    briefing = SessionBriefing(**briefing_json)  # Pydantic validation
except (json.JSONDecodeError, ValidationError) as e:
    # Fallback: create basic briefing
    briefing = _create_fallback_briefing(session)
```

---

## Potential Improvements

### 1. Agent Enhancements

#### Intake Agent

**Current Limitations:**
- Keyword-based topic tracking is fragile
- No semantic understanding of topic coverage
- Fixed 11 topics may not fit all cases

**Improvements:**
1. **Semantic Topic Detection:**
   - Use LLM to evaluate topic coverage instead of keywords
   - More accurate assessment of information gathered
   - Adaptive topic list based on presenting problem

2. **Dynamic Topic Prioritization:**
   - Adjust topic importance based on intake responses
   - Skip irrelevant topics (e.g., substance use if clearly not applicable)
   - Deep-dive on critical topics

3. **Intake Quality Assessment:**
   - LLM-based quality check before completion
   - Identify gaps in critical information
   - Suggest follow-up questions

**Implementation:**
```python
async def _assess_topic_coverage(self, message_history):
    prompt = f"""
    Analyze this intake conversation and identify which clinical topics were thoroughly covered:

    Required topics: {self.required_topics}

    Transcript:
    {message_history}

    For each topic, assess:
    1. Coverage quality (none/minimal/partial/thorough)
    2. Key information obtained
    3. Recommended follow-up questions

    Return as JSON.
    """

    assessment = await llm_service.generate(prompt)
    return parse_topic_assessment(assessment)
```

#### Assessment Agent

**Current Limitations:**
- Only evaluates 3 predefined styles
- Binary selection (one style only)
- No hybrid approach option

**Improvements:**
1. **Hybrid Therapy Styles:**
   - Allow combining styles (e.g., "Jungian-CBT hybrid")
   - Weighted style application (60% Jung, 40% CBT)
   - Dynamic style adaptation during therapy

2. **Expandable Style Library:**
   - Modular style registration system
   - Add new styles without code changes
   - Community-contributed therapy approaches

3. **Contraindication Detection:**
   - Identify styles that may be harmful for patient
   - Flag severe mental health concerns requiring professional referral
   - Warn about limitations of AI therapy

**Implementation:**
```python
class StyleRegistry:
    def register_style(self, style_id, style_pack):
        # Validate style_pack structure
        # Add to available styles
        # Update vector DB with knowledge

    def get_hybrid_plan(self, primary_style, secondary_style, weight=0.6):
        # Combine prompts and knowledge sources
        # Weight RAG retrieval accordingly
```

#### Psychoanalyst Agent

**Current Limitations:**
- Session timing is rigid (30 min + 2x5 min extensions)
- No crisis detection or intervention
- Limited personalization beyond therapy style

**Improvements:**
1. **Adaptive Session Duration:**
   - Dynamic session length based on patient needs
   - Natural conversation endpoints (not just time)
   - Flexible pacing for different topics

2. **Crisis Detection and Response:**
   - Monitor for suicidal ideation, self-harm mentions
   - Provide crisis resources immediately
   - Escalate to human oversight if needed
   - Gentle redirection for out-of-scope requests

3. **Therapeutic Alliance Monitoring:**
   - Track rapport and trust indicators
   - Adjust approach if alliance weakens
   - Metacommunication about therapy process

4. **Intervention Tracking:**
   - Log specific techniques used (interpretation, reflection, etc.)
   - Correlate interventions with patient response
   - Optimize technique selection over time

**Implementation:**
```python
async def _detect_crisis_indicators(self, message):
    crisis_keywords = ["suicide", "kill myself", "end it all", "not worth living"]

    if any(keyword in message.lower() for keyword in crisis_keywords):
        # Detailed LLM analysis
        risk_assessment = await _assess_crisis_risk(message)

        if risk_assessment.severity == "high":
            return CrisisResponse(
                immediate_intervention=True,
                resources=[
                    "National Suicide Prevention Lifeline: 988",
                    "Crisis Text Line: Text HOME to 741741"
                ],
                recommended_action="gentle_engagement_and_resource_provision"
            )

    return None
```

#### Reflection Agent

**Current Limitations:**
- Session briefing relies on single LLM call (can fail)
- No validation of briefing quality
- Limited error handling for malformed briefings

**Improvements:**
1. **Multi-Stage Briefing Generation:**
   - Generate briefing components separately
   - Validate each component independently
   - Combine validated components into final briefing

2. **Briefing Quality Assurance:**
   - LLM evaluates generated briefing for completeness
   - Flag vague or generic content
   - Regenerate low-quality sections

3. **Longitudinal Trend Analysis:**
   - Track patient progress across months
   - Identify long-term patterns
   - Predict therapy trajectory

4. **Supervisor Feedback Loop:**
   - Allow human supervisors to review/edit briefings
   - Learn from supervisor corrections
   - Improve briefing quality over time

**Implementation:**
```python
async def _generate_briefing_with_validation(self, session, context):
    # Stage 1: Generate draft
    draft = await _generate_draft_briefing(session)

    # Stage 2: Quality check
    quality_assessment = await _assess_briefing_quality(draft, session)

    # Stage 3: Regenerate weak sections
    if quality_assessment.needs_improvement:
        for section in quality_assessment.weak_sections:
            draft[section] = await _regenerate_section(section, session)

    # Stage 4: Final validation
    validated_briefing = SessionBriefing(**draft)

    return validated_briefing
```

---

### 2. Orchestration Improvements

#### Workflow Engine

**Current Limitations:**
- Linear state progression
- No branching workflows
- No patient-initiated state changes

**Improvements:**
1. **Branching Workflows:**
   - Allow multiple paths based on patient needs
   - Skip assessment if returning patient
   - Direct access to specific agents (e.g., "I need to talk about a dream")

2. **Patient Agency:**
   - Allow patients to request specific topics
   - Enable style switching mid-therapy
   - Support therapy pause/resume

3. **Automated Workflow Optimization:**
   - Track workflow bottlenecks
   - A/B test different intake flows
   - Optimize for patient engagement

**Implementation:**
```python
class WorkflowEvent(Enum):
    USER_REQUEST_TOPIC = "user_request_topic"
    USER_REQUEST_STYLE_CHANGE = "user_request_style_change"
    CRISIS_DETECTED = "crisis_detected"
    # ...

def get_next_state(current_state, event, context):
    if event == WorkflowEvent.CRISIS_DETECTED:
        return WorkflowState.CRISIS_INTERVENTION

    if event == WorkflowEvent.USER_REQUEST_STYLE_CHANGE:
        return WorkflowState.STYLE_REASSESSMENT

    # Standard transitions
    return VALID_TRANSITIONS[current_state][0]
```

#### Conversation Manager

**Current Limitations:**
- Context cache never expires (memory leak potential)
- No conversation history summarization
- RAG retrieval is simple semantic search

**Improvements:**
1. **Smart Context Management:**
   - LRU cache with expiration
   - Automatic context summarization for long conversations
   - Compress old messages while retaining key information

2. **Advanced RAG:**
   - Hybrid search (semantic + keyword)
   - Re-ranking retrieved chunks
   - Multi-hop reasoning over knowledge base
   - Patient-specific knowledge base (their own history)

3. **Streaming Optimizations:**
   - Chunk batching for reduced latency
   - Predictive pre-loading of RAG context
   - WebSocket connection pooling

**Implementation:**
```python
class ContextCache:
    def __init__(self, max_size=100, ttl_seconds=3600):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl_seconds
        self.timestamps = {}

    async def get(self, session_id):
        # Check expiration
        if session_id in self.timestamps:
            if time.time() - self.timestamps[session_id] > self.ttl:
                del self.cache[session_id]
                del self.timestamps[session_id]
                return None

        return self.cache.get(session_id)

    async def set(self, session_id, context):
        # LRU eviction
        if len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)

        self.cache[session_id] = context
        self.timestamps[session_id] = time.time()
```

---

### 3. Database and Persistence

**Current Limitations:**
- SQLite may not scale to thousands of concurrent users
- No backup/recovery system
- Session transcripts grow unbounded
- No analytics or reporting

**Improvements:**
1. **Database Scalability:**
   - Add PostgreSQL support for production
   - Implement connection pooling
   - Database sharding for large user bases

2. **Transcript Management:**
   - Compress old transcripts
   - Archive inactive sessions to cold storage
   - Implement retention policies (GDPR compliance)

3. **Backup and Recovery:**
   - Automated daily backups
   - Point-in-time recovery
   - Disaster recovery plan

4. **Analytics Database:**
   - Separate analytics DB (e.g., ClickHouse)
   - Track metrics:
     - Session duration distribution
     - Topic coverage patterns
     - Style effectiveness
     - Patient engagement metrics
     - Therapeutic outcome indicators

**Implementation:**
```python
class DatabaseServiceFactory:
    @staticmethod
    def create(db_type: str):
        if db_type == "sqlite":
            return TrioSQLiteDatabaseService()
        elif db_type == "postgresql":
            return TrioPostgresDatabaseService()
        else:
            raise ValueError(f"Unsupported database: {db_type}")

class TrioPostgresDatabaseService:
    async def __init__(self, connection_string):
        self.pool = await asyncpg.create_pool(connection_string)

    async def save_session(self, session):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sessions (session_id, user_id, timestamp, transcript, topics)
                VALUES ($1, $2, $3, $4, $5)
            """, session.session_id, session.user_id, ...)
```

---

### 4. RAG System Enhancements

**Current Limitations:**
- Static knowledge base (requires code deployment to update)
- Simple semantic search
- No citation/source attribution
- Knowledge limited to therapy theory

**Improvements:**
1. **Dynamic Knowledge Base:**
   - Admin interface to add/update knowledge
   - Version control for knowledge sources
   - A/B test different knowledge chunks

2. **Enhanced Retrieval:**
   - Hybrid search (BM25 + semantic)
   - Re-ranking with cross-encoder
   - Multi-query retrieval (generate variations)
   - Hypothetical document embeddings (HyDE)

3. **Source Attribution:**
   - Show patients which theory informs responses
   - Build trust through transparency
   - Enable patient education

4. **Expanded Knowledge:**
   - Research papers on therapy effectiveness
   - Case studies and examples
   - Therapeutic exercises and worksheets
   - Coping strategies database

5. **Patient-Specific RAG:**
   - Index patient's own history
   - Retrieve relevant past discussions
   - Personalized insights based on patterns

**Implementation:**
```python
class HybridRAGService:
    def __init__(self, vector_db, keyword_index):
        self.vector_db = vector_db
        self.keyword_index = keyword_index  # BM25
        self.reranker = CrossEncoderReranker()

    async def retrieve(self, query, top_k, style_filter):
        # 1. Semantic search
        semantic_results = await self.vector_db.query(query, top_k*2, style_filter)

        # 2. Keyword search
        keyword_results = await self.keyword_index.search(query, top_k*2, style_filter)

        # 3. Merge and deduplicate
        combined = merge_results(semantic_results, keyword_results)

        # 4. Re-rank
        reranked = await self.reranker.rerank(query, combined, top_k)

        return reranked

class AttributedResponse:
    content: str
    sources: list[Source]

class Source:
    text: str
    reference: str  # "Freud, S. (1900). The Interpretation of Dreams"
    relevance_score: float
```

---

### 5. Prompt Engineering Improvements

**Current Limitations:**
- Static prompts in text files
- No versioning or A/B testing
- Limited dynamic adaptation
- No prompt optimization feedback loop

**Improvements:**
1. **Prompt Management System:**
   - Database-backed prompt storage
   - Version control for prompts
   - A/B testing framework
   - Performance metrics per prompt

2. **Dynamic Prompt Assembly:**
   - Conditional prompt components
   - Context-aware prompt selection
   - Patient-personalized instructions

3. **Prompt Optimization:**
   - Track prompt effectiveness
   - Automated prompt refinement
   - Feedback from patient engagement metrics

4. **Safety and Guardrails:**
   - Built-in safety instructions
   - Ethical guidelines in every prompt
   - Boundary-setting for AI limitations

**Implementation:**
```python
class PromptManager:
    async def get_prompt(self, prompt_id, context, variant="default"):
        # Load prompt template
        template = await self.db.get_prompt_template(prompt_id, variant)

        # Track usage
        await self.analytics.log_prompt_usage(prompt_id, variant)

        # Dynamic assembly
        assembled = self._assemble_prompt(template, context)

        return assembled

    async def track_effectiveness(self, prompt_id, variant, metrics):
        # Store metrics
        await self.analytics.record_prompt_metrics(prompt_id, variant, metrics)

        # Trigger optimization if needed
        if metrics.engagement_score < threshold:
            await self._trigger_prompt_optimization(prompt_id)
```

---

### 6. Testing and Quality Assurance

**Current State:**
- 126 passing tests, 3 skipped
- Unit and integration tests
- Mocked LLM/RAG services

**Improvements:**
1. **End-to-End Testing:**
   - Real LLM integration tests (with cost controls)
   - Full patient journey tests
   - Multi-session flow validation

2. **Therapeutic Quality Metrics:**
   - Measure response empathy (LLM-as-judge)
   - Evaluate therapeutic adherence to style
   - Detect harmful or inappropriate responses

3. **Load and Performance Testing:**
   - Concurrent user simulation
   - Latency benchmarking
   - Memory leak detection

4. **Regression Testing:**
   - Capture real conversations as test cases
   - Prevent quality degradation
   - Golden dataset for prompt changes

**Implementation:**
```python
class TherapeuticQualityEvaluator:
    async def evaluate_response(self, context, response):
        prompt = f"""
        Evaluate this therapist response for therapeutic quality:

        Patient: {context.last_user_message}
        Therapist: {response}

        Assess:
        1. Empathy (1-10)
        2. Boundary appropriateness (1-10)
        3. Adherence to {context.therapy_style} approach (1-10)
        4. Safety concerns (yes/no + explanation)

        Return as JSON.
        """

        evaluation = await self.llm_service.generate(prompt)
        return parse_evaluation(evaluation)
```

---

### 7. User Experience Enhancements

**Current Limitations:**
- Console-only interface
- No multimedia support
- Limited personalization
- No progress visualization

**Improvements:**
1. **Multi-Modal Interface:**
   - Web UI with rich formatting
   - Voice interface (speech-to-text, text-to-speech)
   - Mobile app for on-the-go access

2. **Multimedia Support:**
   - Share images related to dreams or concerns
   - Audio journaling
   - Video check-ins (with sentiment analysis)

3. **Progress Visualization:**
   - Dashboard showing therapy journey
   - Mood tracking charts
   - Goal progress indicators
   - Theme evolution timeline

4. **Personalization:**
   - Customizable therapist personality (warmth level, formality)
   - Preferred session length
   - Topic preferences and avoidances

5. **Gamification (Optional):**
   - Streaks for consistent engagement
   - Milestones for therapy progress
   - Badges for breakthroughs

**Implementation:**
```python
class ProgressDashboard:
    async def generate_dashboard(self, user_id):
        # Get all sessions
        sessions = await db_service.get_user_sessions(user_id, limit=None)

        # Analyze trends
        emotional_trend = analyze_emotional_progression(sessions)
        theme_evolution = analyze_theme_changes(sessions)
        goal_progress = calculate_goal_achievement(sessions)

        return Dashboard(
            total_sessions=len(sessions),
            emotional_trend=emotional_trend,
            theme_evolution=theme_evolution,
            goal_progress=goal_progress,
            streaks=calculate_streaks(sessions),
            milestones=identify_milestones(sessions),
        )
```

---

### 8. Privacy and Security

**Current Limitations:**
- No encryption at rest
- No user authentication
- Guest accounts only
- No data export/deletion

**Improvements:**
1. **Authentication:**
   - Secure user accounts with passwords/OAuth
   - Multi-factor authentication
   - Session token management

2. **Data Encryption:**
   - Encrypt transcripts at rest (AES-256)
   - TLS for data in transit
   - Encrypted backups

3. **Privacy Controls:**
   - User-initiated data export (GDPR compliance)
   - Right to deletion
   - Granular sharing controls
   - Anonymized analytics opt-in

4. **Audit Logging:**
   - Track all data access
   - Monitor for suspicious activity
   - Compliance reporting

**Implementation:**
```python
class EncryptedDatabaseService:
    def __init__(self, db_service, encryption_key):
        self.db_service = db_service
        self.cipher = AES.new(encryption_key, AES.MODE_GCM)

    async def save_session(self, session):
        # Encrypt transcript
        encrypted_transcript = self.cipher.encrypt(
            json.dumps(session.transcript).encode()
        )

        # Save encrypted data
        session.transcript = encrypted_transcript
        await self.db_service.save_session(session)

    async def get_session(self, session_id):
        session = await self.db_service.get_session(session_id)

        # Decrypt transcript
        decrypted_transcript = self.cipher.decrypt(session.transcript)
        session.transcript = json.loads(decrypted_transcript.decode())

        return session
```

---

### 9. Monitoring and Observability

**Current Limitations:**
- Basic logging only
- No real-time monitoring
- No error tracking
- No performance metrics

**Improvements:**
1. **Structured Logging:**
   - JSON-formatted logs
   - Log levels and categories
   - Correlation IDs for request tracing

2. **Metrics Collection:**
   - Prometheus/Grafana dashboards
   - Key metrics:
     - Active sessions
     - LLM latency (p50, p95, p99)
     - RAG retrieval time
     - Database query performance
     - WebSocket connection count

3. **Error Tracking:**
   - Sentry integration
   - Error grouping and prioritization
   - Stack trace analysis

4. **Alerting:**
   - High error rates
   - Performance degradation
   - Database connection issues
   - Crisis keyword detection

**Implementation:**
```python
class MetricsCollector:
    def __init__(self):
        self.active_sessions = Gauge('active_sessions', 'Number of active therapy sessions')
        self.llm_latency = Histogram('llm_latency_seconds', 'LLM response latency')
        self.rag_retrieval_time = Histogram('rag_retrieval_seconds', 'RAG retrieval time')

    @contextmanager
    def measure_llm_latency(self):
        start = time.time()
        yield
        self.llm_latency.observe(time.time() - start)

    def increment_active_sessions(self):
        self.active_sessions.inc()

    def decrement_active_sessions(self):
        self.active_sessions.dec()
```

---

### 10. Research and Evaluation

**Current Limitations:**
- No outcome measurement
- No effectiveness validation
- No comparison to human therapists
- No research data collection

**Improvements:**
1. **Outcome Tracking:**
   - Pre/post therapy assessments (PHQ-9, GAD-7)
   - Session-by-session progress
   - Long-term follow-up

2. **Effectiveness Research:**
   - Randomized controlled trials
   - Comparison to standard care
   - Subgroup analysis (which patients benefit most)

3. **Data for Research:**
   - Anonymized dataset for research
   - IRB-approved protocols
   - Open science publications

4. **Continuous Improvement:**
   - Regular model updates
   - Prompt refinement based on outcomes
   - Style effectiveness comparison

**Implementation:**
```python
class OutcomeTracker:
    async def administer_assessment(self, user_id, assessment_type):
        if assessment_type == "PHQ-9":
            questions = get_phq9_questions()
        elif assessment_type == "GAD-7":
            questions = get_gad7_questions()

        # Present questionnaire
        responses = await present_questionnaire(user_id, questions)

        # Calculate score
        score = calculate_assessment_score(assessment_type, responses)

        # Store result
        await db_service.save_assessment_result(
            user_id=user_id,
            assessment_type=assessment_type,
            score=score,
            timestamp=datetime.now()
        )

        return score

    async def track_longitudinal_outcomes(self, user_id):
        # Get all assessments
        assessments = await db_service.get_assessment_history(user_id)

        # Analyze trajectory
        trajectory = analyze_trajectory(assessments)

        return OutcomeReport(
            baseline_score=assessments[0].score,
            current_score=assessments[-1].score,
            change=assessments[-1].score - assessments[0].score,
            trajectory=trajectory,
            clinical_significance=assess_clinical_significance(assessments)
        )
```

---

## Summary

This Virtual LLM Psychoanalyst application demonstrates a sophisticated **agent-based architecture** with:

**Strengths:**
- Clean state machine workflow
- Comprehensive session context management
- Rich briefing system for continuity
- RAG-augmented therapeutic knowledge
- Trio-based structured concurrency
- Modular agent design

**Architecture Highlights:**
- 6 specialized agents (Intake, Assessment, Psychoanalyst, Reflection, Memory, Planning)
- SQLite persistence with JSON encoding
- ChromaDB RAG system
- WebSocket streaming
- Comprehensive prompt engineering

**Key Innovation: Session Briefing System**
- Enables seamless resumption across weeks/months
- Rich therapeutic context preservation
- Continuity points for natural follow-up
- Emotional trend tracking
- Recommended approach for next session

**Potential Growth Areas:**
1. Enhanced agent intelligence (semantic topic detection, crisis handling)
2. Workflow flexibility (branching paths, patient agency)
3. Database scalability (PostgreSQL, analytics)
4. Advanced RAG (hybrid search, patient-specific knowledge)
5. Testing rigor (therapeutic quality metrics, E2E tests)
6. UX improvements (multi-modal interface, progress visualization)
7. Privacy/security (encryption, authentication, GDPR compliance)
8. Observability (metrics, alerting, error tracking)
9. Research capabilities (outcome tracking, effectiveness studies)

The system is production-ready for pilot deployments but would benefit from the improvements outlined above for large-scale, high-stakes therapeutic applications.
