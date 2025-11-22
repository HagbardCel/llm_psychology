# Session Resumption Implementation Plan

**Date:** 2025-11-15
**Objective:** Implement contextual therapist greetings for continuing therapy sessions
**Priority:** High - Critical UX gap

---

## Table of Contents
1. [Problem Statement](#problem-statement)
2. [Current Architecture Analysis](#current-architecture-analysis)
3. [Proposed Solution](#proposed-solution)
4. [Detailed Implementation Plan](#detailed-implementation-plan)
   - Step 0: Configuration Management
   - Step 1: Update Data Models with Enhanced Analysis
   - Step 2: Enhance Reflection Agent's Analysis
   - Step 3: Update Psychoanalyst Agent for On-Demand Generation
   - Step 4: Update Server Logic
   - Step 5: Update Database Service
5. [Testing Strategy](#testing-strategy)
6. [Migration & Rollout](#migration--rollout)
7. [Future Enhancements](#future-enhancements)
8. [Reviewer's Feedback and Refinements](#reviewers-feedback-and-refinements)

---

## Problem Statement

### Current Behavior
When users return for continuing therapy sessions, they receive:
```
✅ Your therapy session has begun.

💬 You can now chat with your therapist. Type 'quit' or 'exit' to end the session.
============================================================

Your response: [waiting for user to speak first]
```

### Expected Behavior
Users should receive a contextual therapist greeting:
```
✅ Your therapy session has begun.

💬 You can now chat with your therapist. Type 'quit' or 'exit' to end the session.
============================================================

THERAPIST: Welcome back! Last session we explored your work-related anxiety,
and you mentioned wanting to set better boundaries with your colleagues.
You seemed hopeful about trying the thought-challenging techniques we discussed.
How have things been progressing since then?

Your response:
```

### Root Cause
**Critical architectural gap**: The Reflection Agent performs comprehensive session analysis (themes, progress, emotional state, patterns) but these insights are **not fed forward** to inform the Psychoanalyst Agent's opening in the next session.

---

## Current Architecture Analysis

### Agent Flow
```
THERAPY SESSION ENDS
    ↓
PSYCHOANALYST AGENT
    └─→ Returns next_action="transition", next_state=REFLECTION_IN_PROGRESS
    ↓
WORKFLOW ENGINE transitions user to REFLECTION_IN_PROGRESS
    ↓
REFLECTION AGENT (orchestrates two sub-agents)
    ├─→ MEMORY AGENT
    │     └─→ Analyzes session context
    │     └─→ Builds therapeutic memory (all sessions)
    │     └─→ Identifies patterns
    │     └─→ Generates continuity context
    │
    └─→ PLANNING AGENT
          └─→ Assesses plan effectiveness
          └─→ Recommends plan adjustments
          └─→ Updates therapy plan
    ↓
REFLECTION AGENT
    └─→ Returns comprehensive reflection
    └─→ Stores updated therapy plan
    └─→ Transitions to PLAN_COMPLETE
    ↓
USER STATUS = PLAN_COMPLETE (ready for next session)
```

### What Reflection Agent Currently Produces

**Session Context** (from MemoryAgent):
```python
{
    "key_themes": ["work anxiety", "boundary setting", "perfectionism"],
    "emotional_state": "anxious but hopeful",
    "insights": ["Client recognizes pattern of overcommitment", ...],
    "progress_indicators": ["Increased self-awareness", "Openness to CBT", ...]
}
```

**Therapeutic Memory** (aggregated across all sessions):
```python
{
    "total_sessions": 5,
    "relationship_quality": "developing",  # building → developing → established → strong
    "dominant_themes": [
        {"theme": "work anxiety", "frequency": 4, "sessions": [1,2,3,5]},
        {"theme": "perfectionism", "frequency": 3, "sessions": [1,3,5]}
    ],
    "emotional_progression": [
        {"session": 1, "state": "overwhelmed and anxious"},
        {"session": 2, "state": "reflective"},
        ...
    ]
}
```

**Plan Assessment** (from PlanningAgent):
```python
{
    "effectiveness_score": 7.5,
    "analysis": "CBT techniques showing promise; client engaging well",
    "adjustments_needed": True,
    "recommendations": [
        "Increase focus on boundary-setting exercises",
        "Explore childhood patterns in next 2 sessions"
    ]
}
```

### The Missing Link

**Problem**: This rich analysis is stored in the database but **never retrieved** by the Psychoanalyst Agent when starting a new session.

**Current Psychoanalyst Agent Behavior**:
- Initial session prompt uses only: user profile + therapy plan (focus, goals, techniques)
- Does NOT access: previous session summaries, therapeutic memory, reflection insights, continuity context

---

## Proposed Solution

### Architecture: Session Briefing Handoff

Create a **session briefing artifact** that the Reflection Agent generates and stores with the therapy plan, which the Psychoanalyst Agent retrieves when starting the next session.

```
REFLECTION AGENT (end of session N)
    ↓
Generates SESSION BRIEFING for next session
    ├─→ Continuity points (what to follow up on)
    ├─→ Emotional progression summary
    ├─→ Unresolved themes
    ├─→ Progress highlights
    └─→ Recommended opening tone/focus
    ↓
Stores in TherapyPlan.session_briefing
    ↓
PLAN_COMPLETE
    ↓
[User returns for session N+1]
    ↓
SERVER detects PLAN_COMPLETE user
    └─→ Sets has_initial_message=True
    ↓
PSYCHOANALYST AGENT starts new session
    └─→ Retrieves therapy plan
    └─→ Finds session_briefing
    └─→ Generates contextual resumption prompt
    └─→ Streams to client
    ↓
CLIENT displays: THERAPIST: [contextual greeting]
    ↓
USER can respond with context
```

### Design Principles

1. **Separation of Concerns**:
   - Reflection Agent = Analysis & Planning
   - Psychoanalyst Agent = Conversation & Therapy
   - Briefing = Clean handoff between them

2. **Agent Autonomy**:
   - Reflection Agent decides WHAT to highlight for next session
   - Psychoanalyst Agent decides HOW to phrase the opening
   - No rigid templates; LLM generates natural language

3. **Backward Compatibility**:
   - If no briefing exists → fall back to current behavior
   - Existing therapy plans continue to work
   - Gradual rollout possible

4. **Progressive Enhancement**:
   - Phase 1: Basic briefing for resumption prompts
   - Phase 2: Enhanced context in ongoing conversation
   - Phase 3: Advanced relationship tracking

---

## Detailed Implementation Plan

### Phase 1: Core Session Briefing (MVP)

#### Step 0: Configuration Management
**File:** `src/config.py`

**Purpose:** Add session resumption configuration to the existing `Settings` class. This leverages the existing pydantic-settings infrastructure for environment variable support and validation.

**Update Existing Settings Class:**
```python
# In src/config.py

from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    """Application settings with environment variable support."""

    # ... existing settings ...

    # Session Resumption Configuration
    BRIEFING_VALIDITY_DAYS: int = Field(
        default=30,
        description="Number of days a briefing is considered fresh"
    )
    STALE_BRIEFING_DAYS: int = Field(
        default=90,
        description="Days after which briefing is considered stale"
    )

    # Content Limits
    MAX_CONTINUITY_POINTS: int = Field(default=10, ge=1, le=20)
    MAX_PROGRESS_HIGHLIGHTS: int = Field(default=10, ge=1, le=20)
    MAX_UNRESOLVED_ISSUES: int = Field(default=10, ge=1, le=20)
    MAX_KEY_THEMES: int = Field(default=10, ge=1, le=20)
    MAX_SUGGESTED_QUESTIONS: int = Field(default=3, ge=1, le=5)
    MAX_SESSION_GOALS: int = Field(default=3, ge=1, le=5)

    # Quality Constraints
    MIN_NARRATIVE_LENGTH: int = Field(default=50, ge=20)
    MAX_NARRATIVE_LENGTH: int = Field(default=1500, le=3000)
    MAX_OBSERVATIONS_LENGTH: int = Field(default=1000, le=2000)
    MAX_PLAN_NOTES_LENGTH: int = Field(default=1000, le=2000)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Global settings instance (existing pattern)
settings = Settings()


# Backwards-compatible Config class (if needed for existing code)
class Config:
    """Backwards-compatible config wrapper."""

    def __init__(self):
        self._settings = settings

    def __getattr__(self, name):
        return getattr(self._settings, name)


config = Config()
```

**Environment Variable Support (.env file):**
```bash
# Add to .env file (optional - defaults will be used if not set)

# Session resumption configuration
BRIEFING_VALIDITY_DAYS=30
STALE_BRIEFING_DAYS=90
MAX_CONTINUITY_POINTS=10
MAX_KEY_THEMES=10
```

**Usage Pattern:**
```python
from config import settings

# In Reflection Agent
def _generate_session_briefing(self, ...):
    continuity_points = briefing_data['key_themes'][:settings.MAX_CONTINUITY_POINTS]

    # Validate narrative length
    if len(narrative) < settings.MIN_NARRATIVE_LENGTH:
        raise ValueError(f"Narrative too short (min: {settings.MIN_NARRATIVE_LENGTH})")

# In Psychoanalyst Agent
def get_briefing_status(self, briefing: Dict[str, Any]) -> BriefingStatus:
    age_days = (datetime.now() - datetime.fromisoformat(briefing["generated_at"])).days

    if age_days <= settings.BRIEFING_VALIDITY_DAYS:
        return BriefingStatus.FRESH
    elif age_days <= settings.STALE_BRIEFING_DAYS:
        return BriefingStatus.STALE
    else:
        return BriefingStatus.VERY_STALE
```

**Benefits of This Approach:**
- ✅ Integrates with existing config infrastructure
- ✅ Supports environment variables for deployment flexibility
- ✅ Pydantic validation ensures type safety and constraints
- ✅ No need for separate config class or global instance
- ✅ Consistent with existing codebase patterns

---

#### Step 0.1: Trio Integration Patterns

**Purpose:** Document the Trio concurrency patterns that will be used throughout the session resumption implementation. All async operations must follow these patterns for consistency with the existing codebase.

**Core Patterns:**

1. **Blocking I/O Operations** (Database, LLM calls):
```python
# Pattern: trio.to_thread.run_sync() for all blocking operations
import trio

# Database operations (from trio_db_service.py)
async def save_therapy_plan(self, plan: TherapyPlan) -> bool:
    return await trio.to_thread.run_sync(self._sync_save_therapy_plan, plan)

async def get_therapy_plan(self, user_id: str) -> Optional[TherapyPlan]:
    return await trio.to_thread.run_sync(self._sync_get_therapy_plan, user_id)

# LLM operations (from llm_service.py)
async def generate_response_stream(
    self, prompt: str, context: Optional[List[Dict[str, str]]] = None
) -> List[str]:
    def _stream_blocking():
        chunks = []
        for chunk in self.llm.stream(messages):
            chunk_text = chunk.content
            if chunk_text:
                chunks.append(chunk_text)
        return chunks

    return await trio.to_thread.run_sync(_stream_blocking)
```

2. **Streaming Responses** (For on-demand greeting generation):
```python
# Pattern: AsyncIterator[str] for chunk-by-chunk streaming
from typing import AsyncIterator

async def stream_greeting(
    self,
    user_profile: UserProfile,
    therapy_plan: TherapyPlan
) -> AsyncIterator[str]:
    """Stream greeting chunks as they are generated."""
    prompt = self._build_resumption_prompt(user_profile, therapy_plan, briefing)
    conversation_history = self._build_conversation_history(context)

    # Use conversation manager's streaming interface
    async for chunk in self.conversation_manager.stream_response(
        prompt, context, use_rag=False
    ):
        yield chunk
```

3. **WebSocket Communication** (Memory channels):
```python
# Pattern: Trio memory channels for WebSocket streaming
import trio
from trio import MemoryReceiveChannel, MemorySendChannel

async def _send_resumption_greeting(
    self,
    user_id: str,
    session_id: str,
    send_channel: MemorySendChannel
) -> None:
    """Send streamed greeting through memory channel."""
    agent = await self.orchestrator.get_or_create_agent("PSYCHOANALYST", user_id)

    # Stream chunks directly to WebSocket
    async for chunk in agent.stream_initial_greeting(user_profile, therapy_plan):
        await send_channel.send({
            "type": "chat_response_chunk",
            "data": {
                "chunk": chunk,
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "is_complete": False
            }
        })

    # Send completion marker
    await send_channel.send({
        "type": "chat_response_chunk",
        "data": {
            "chunk": "",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "is_complete": True
        }
    })
```

4. **Structured Concurrency** (Nurseries):
```python
# Pattern: Nursery for managing concurrent tasks (from trio_server.py)
async def ws_endpoint(self, user_id: str):
    """WebSocket endpoint with structured concurrency."""
    send_channel, send_channel_receiver = trio.open_memory_channel(100)
    receive_channel_sender, receive_channel = trio.open_memory_channel(100)

    async with trio.open_nursery() as nursery:
        # Both tasks run concurrently but are supervised
        nursery.start_soon(
            self._websocket_reader,
            websocket,
            receive_channel_sender
        )
        nursery.start_soon(
            self._websocket_writer,
            websocket,
            send_channel_receiver
        )
        # Nursery ensures both tasks complete or are cancelled together
```

**Error Handling Philosophy:**

All operations follow a **fail-fast** approach:
- NO fallback messages or graceful degradation
- Let exceptions propagate with full stack traces
- Use proper logging at error boundaries
- Example:
```python
async def _generate_session_briefing(...) -> Dict[str, Any]:
    """Generate briefing - raises on failure."""
    briefing_json_str = await trio.to_thread.run_sync(
        self.llm_service.generate, messages
    )

    try:
        briefing_data = json.loads(briefing_json_str)
        validated_briefing = SessionBriefing(**briefing_data)
        return validated_briefing.dict()
    except (json.JSONDecodeError, ValidationError) as e:
        logger.error(f"Failed to generate/validate session briefing: {e}")
        raise  # Propagate error, don't fall back
```

**Integration Points:**

| Component | Trio Pattern | Notes |
|-----------|--------------|-------|
| Reflection Agent | `trio.to_thread.run_sync()` | LLM call for briefing generation |
| Psychoanalyst Agent | `AsyncIterator[str]` | Streaming greeting generation |
| Server | Memory channels + nursery | WebSocket streaming orchestration |
| Database Service | `trio.to_thread.run_sync()` | All persistence operations |
| LLM Service | `trio.to_thread.run_sync()` | Wraps blocking LangChain calls |

---

#### Step 1: Update Data Models with Enhanced Analysis

**File:** `src/models/briefing_models.py`



**Purpose:** The `SessionBriefing` model is updated to capture the deeper analysis from the Reflection Agent. The `pre_generated_greeting` is removed, and new fields for richer context are added.



```python

"""Pydantic models for session briefing validation and type safety."""



from pydantic import BaseModel, Field, validator

from typing import List, Optional

from datetime import datetime

from enum import Enum



class BriefingStatus(Enum):

    FRESH = "fresh"

    STALE = "stale"

    VERY_STALE = "very_stale"

    INVALID = "invalid"



class EmotionalSummary(BaseModel):
    """Emotional state tracking across sessions."""
    last_session: str = Field(..., description="Emotional state during last session")
    trend: str = Field(..., description="Overall trend: 'improving', 'stable', 'declining', 'fluctuating'")
    note: str = Field(..., max_length=500, description="Contextual note about emotional progression")

    @validator('trend')
    def validate_trend(cls, v):
        allowed_trends = ['improving', 'stable', 'declining', 'fluctuating']
        if v not in allowed_trends:
            raise ValueError(f"Trend must be one of {allowed_trends}")
        return v


class KeyTheme(BaseModel):
    """Individual therapy theme tracking."""
    theme: str = Field(..., min_length=3, max_length=100)
    status: str = Field(..., description="'ongoing', 'newly introduced', 'underlying', 'emerging', 'resolved'")
    priority: str = Field(..., description="'high', 'medium', 'low'")
    frequency: int = Field(..., ge=1, description="Number of sessions where discussed")
    first_appearance: str = Field(..., description="Session ID where first discussed")
    last_discussed: str = Field(..., description="Session ID where last discussed")

    @validator('status')
    def validate_status(cls, v):
        allowed_statuses = ['ongoing', 'newly introduced', 'underlying', 'emerging', 'resolved']
        if v not in allowed_statuses:
            raise ValueError(f"Status must be one of {allowed_statuses}")
        return v

    @validator('priority')
    def validate_priority(cls, v):
        allowed_priorities = ['high', 'medium', 'low']
        if v not in allowed_priorities:
            raise ValueError(f"Priority must be one of {allowed_priorities}")
        return v



class RecommendedApproach(BaseModel):

    """Enhanced guidance for the next session."""

    opening_tone: str

    opening_focus: str

    things_to_avoid: str

    # NEW: More explicit guidance

    suggested_questions: List[str] = Field(max_items=3)

    therapeutic_goals_for_session: List[str] = Field(max_items=3)



class SessionBriefing(BaseModel):

    """Complete session briefing for therapy resumption."""

    briefing_type: str = "resumption"

    generated_at: datetime

    session_count: int

    last_session_id: str

    last_session_date: str



    # REMOVED: pre_generated_greeting

    # NEW: Richer analytical fields

    narrative_handoff: str = Field(..., min_length=50, max_length=1500)

    patient_observations: str = Field(..., max_length=1000)

    plan_progression_notes: str = Field(..., max_length=1000)



    relationship_quality: str

    continuity_points: List[str] = Field(max_items=10)

    emotional_summary: EmotionalSummary

    key_themes: List[KeyTheme] = Field(max_items=10)

    progress_highlights: List[str] = Field(max_items=10)

    unresolved_issues: List[str] = Field(max_items=10)

    recommended_approach: RecommendedApproach

    @validator('continuity_points')
    def validate_continuity_points(cls, v):
        if not v:
            raise ValueError("At least one continuity point required")
        return v

    @validator('key_themes')
    def validate_key_themes(cls, v):
        if not v:
            raise ValueError("At least one key theme required")
        return v

    @validator('narrative_handoff')
    def validate_narrative_handoff(cls, v):
        if len(v.strip()) < 50:
            raise ValueError("Narrative handoff too short - needs substantial summary")
        return v

```



---



#### Step 2: Enhance Reflection Agent's Analysis

**File:** `src/agents/trio_reflection_agent.py`



**Purpose:** The Reflection Agent's primary role is now to perform a deep, holistic analysis of the completed session and generate the rich `SessionBriefing` object. It no longer handles any greeting generation.



**Update `_generate_session_briefing` Method:**

```python

async def _generate_session_briefing(

    self,

    session_context: Dict[str, Any],

    therapeutic_memory: Dict[str, Any],

    plan_assessment: Dict[str, Any],

    session_transcript: str

) -> Dict[str, Any]:

    """

    Performs a deep analysis of the session and generates a rich briefing

    for the next therapist agent. This is now a single, comprehensive LLM call.

    """

    # 1. Construct a detailed prompt for the LLM

    analysis_prompt = f"""You are a supervising psychoanalyst conducting a comprehensive review of a completed therapy session. Your role is to create a detailed "Session Briefing" that will be used by the therapist who conducts the next session with this patient.

PATIENT CONTEXT:
- Total Sessions Completed: {therapeutic_memory.get('total_sessions', 0)}
- Therapeutic Relationship Quality: {therapeutic_memory.get('relationship_quality', 'building')}
- Therapy Style: {therapy_plan.selected_therapy_style if therapy_plan else 'Not specified'}

PREVIOUS SESSION DATA:
Session Transcript:
{session_transcript}

Session Analysis (from Memory Agent):
- Key Themes: {json.dumps(session_context.get('key_themes', []), indent=2)}
- Emotional State: {session_context.get('emotional_state', 'Not assessed')}
- Insights: {json.dumps(session_context.get('insights', []), indent=2)}
- Progress Indicators: {json.dumps(session_context.get('progress_indicators', []), indent=2)}

Therapeutic Memory (Aggregated Across All Sessions):
{json.dumps(therapeutic_memory, indent=2)}

Treatment Plan Assessment (from Planning Agent):
{json.dumps(plan_assessment, indent=2)}

YOUR TASK:
Generate a complete SessionBriefing JSON object with the following structure. Each field must be carefully synthesized from the above data:

{{
  "briefing_type": "resumption",
  "generated_at": "{datetime.now().isoformat()}",
  "session_count": {therapeutic_memory.get('total_sessions', 0)},
  "last_session_id": "{session_context.get('session_id', 'unknown')}",
  "last_session_date": "{session_context.get('session_date', datetime.now().date().isoformat())}",

  "narrative_handoff": "<REQUIRED: 3-4 sentence narrative that captures the essence of the last session. What was the emotional arc? What core themes emerged? What progress or challenges occurred? This should read like a supervisor briefing the next therapist.>",

  "patient_observations": "<REQUIRED: 2-3 sentences about HOW the patient communicated, not just WHAT they said. Note: communication style, openness level, defensiveness, engagement, any shifts in behavior or presentation compared to previous sessions.>",

  "plan_progression_notes": "<REQUIRED: 2-3 sentences assessing how this session advanced the overall treatment plan. Did it move forward as expected? Were there deviations? Is the plan still appropriate?>",

  "relationship_quality": "<One of: 'building', 'developing', 'established', 'strong'>",

  "continuity_points": [
    "<Most important topic/issue from last session that should be followed up on>",
    "<Second most important continuity point>",
    "<Additional points as needed - maximum 10 total>"
  ],

  "emotional_summary": {{
    "last_session": "<Emotional state during the last session>",
    "trend": "<One of: 'improving', 'stable', 'declining', 'fluctuating'>",
    "note": "<Brief note explaining the emotional progression or context>"
  }},

  "key_themes": [
    {{
      "theme": "<Theme name>",
      "status": "<One of: 'ongoing', 'newly introduced', 'underlying', 'emerging', 'resolved'>",
      "priority": "<One of: 'high', 'medium', 'low'>",
      "frequency": <number of sessions this theme has appeared>,
      "first_appearance": "<session ID>",
      "last_discussed": "<session ID>"
    }}
    // Include all relevant themes, maximum 10
  ],

  "progress_highlights": [
    "<Specific achievement or breakthrough from this or recent sessions>",
    "<Additional progress point>",
    // Maximum 10 highlights
  ],

  "unresolved_issues": [
    "<Issue or theme that remains unaddressed or needs further exploration>",
    "<Additional unresolved issue>",
    // Maximum 10 issues
  ],

  "recommended_approach": {{
    "opening_tone": "<Warm and welcoming | Gentle and supportive | Direct and focused | Curious and exploratory>",
    "opening_focus": "<1-2 sentences: What should the therapist focus on when opening the next session?>",
    "things_to_avoid": "<1-2 sentences: What topics or approaches might not be helpful right now?>",
    "suggested_questions": [
      "<Specific open-ended question that would be good to start with>",
      "<Second suggested question>",
      "<Third suggested question - maximum 3 total>"
    ],
    "therapeutic_goals_for_session": [
      "<Concrete, achievable goal for the upcoming session>",
      "<Second goal>",
      "<Third goal - maximum 3 total>"
    ]
  }}
}}

CRITICAL REQUIREMENTS:
1. Output ONLY valid JSON - no markdown code blocks, no explanations
2. All string fields must use double quotes
3. narrative_handoff must be at least 50 characters and no more than 1500
4. patient_observations must be no more than 1000 characters
5. plan_progression_notes must be no more than 1000 characters
6. At least one continuity_point and one key_theme are required
7. Use specific, concrete language - avoid vague therapeutic jargon
8. Base all analysis strictly on the provided session data
9. Ensure all enum values match exactly (case-sensitive)

Generate the complete JSON object now:"""



    # 2. Call LLM to generate the structured JSON briefing using Trio

    messages = [{"role": "system", "content": analysis_prompt}]

    briefing_json_str = await trio.to_thread.run_sync(
        self.llm_service.generate_response,
        analysis_prompt,
        None  # No conversation history needed for this analysis
    )



    # 3. Parse and validate the response

    try:
        briefing_data = json.loads(briefing_json_str)

        # Add metadata not generated by LLM (these are auto-filled from context)
        briefing_data["generated_at"] = datetime.now().isoformat()
        briefing_data["session_count"] = therapeutic_memory.get('total_sessions', 0)
        briefing_data["last_session_id"] = session_context.get('session_id', 'unknown')

        # Validate with Pydantic model
        validated_briefing = SessionBriefing(**briefing_data)
        return validated_briefing.dict()

    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON for session briefing: {e}")
        logger.error(f"Raw LLM output: {briefing_json_str}")
        raise  # Fail fast - don't fall back

    except ValidationError as e:
        logger.error(f"Session briefing failed Pydantic validation: {e}")
        logger.error(f"Invalid briefing data: {json.dumps(briefing_data, indent=2)}")
        raise  # Fail fast - don't fall back

```



**Update `process_reflection()` method:**

```python

async def process_reflection(

    self,

    session: Session,

    context: ConversationContext

) -> AgentResponse:

    """Process reflection on completed therapy session."""

    # ... existing code for analysis ...



    # REMOVED: Pre-generation logic is gone.

    # Generate the enhanced session briefing (raises on failure - fail fast)
    session_briefing = await self._generate_session_briefing(
        session_context=session_context,
        therapeutic_memory=memory,
        plan_assessment=plan_assessment,
        session_transcript=session.get_transcript_string()  # Assuming helper method
    )

    # Update therapy plan with the new, rich briefing
    updated_plan.session_briefing = session_briefing
    logger.info(f"Successfully generated session briefing for session {session.session_id}")



    # Store updated plan

    await trio.to_thread.run_sync(

        self.db_service.save_therapy_plan,

        updated_plan

    )

    # ... rest of existing code ...

```



---



#### Step 3: Update Psychoanalyst Agent for On-Demand Generation

**File:** `src/agents/trio_psychoanalyst_agent.py`



**Purpose:** The Psychoanalyst Agent is now solely responsible for generating the greeting on-demand, using the rich briefing provided by the Reflection Agent.



**Update Agent Methods:**

```python

# In TrioPsychoanalystAgent



def get_briefing_status(self, briefing: Dict[str, Any]) -> BriefingStatus:

    """

    Determines the status of a briefing based on its age.

    (This method remains the same as the previous revision).

    """

    # ... logic using sr_config to return FRESH, STALE, etc. ...



async def get_initial_prompt(

    self,

    user_profile: UserProfile,

    therapy_plan: Optional[TherapyPlan]

) -> str:

    """

    Builds the initial system prompt for the therapy session.

    This is the main entry point for generating an opening message prompt.

    """

    from models.briefing_models import BriefingStatus



    if therapy_plan and therapy_plan.session_briefing:

        briefing = therapy_plan.session_briefing

        status = self.get_briefing_status(briefing)



        # Use resumption prompt for FRESH and STALE briefings

        if status in [BriefingStatus.FRESH, BriefingStatus.STALE]:

            logger.info(f"Using session briefing (status: {status.value})")

            return self._build_resumption_prompt(

                user_profile,

                therapy_plan,

                briefing,

                status

            )

        else:

            logger.warning(

                f"Briefing is {status.value}; falling back to generic greeting."

            )



    # Fall back to first-session or generic logic

    # ...



async def _build_resumption_prompt(
    self,
    user_profile: UserProfile,
    therapy_plan: TherapyPlan,
    briefing: Dict[str, Any],
    status: BriefingStatus
) -> str:
    """
    Builds prompt for resuming therapy session using the enhanced briefing.
    Returns system prompt that will generate the opening greeting.
    """

    # Extract briefing components
    narrative = briefing.get("narrative_handoff", "")
    observations = briefing.get("patient_observations", "")
    plan_notes = briefing.get("plan_progression_notes", "")
    relationship = briefing.get("relationship_quality", "building")
    session_number = briefing.get("session_count", 0) + 1
    recommended = briefing.get("recommended_approach", {})

    # Format continuity points
    continuity_points = briefing.get("continuity_points", [])
    continuity_text = "\n".join([f"  - {point}" for point in continuity_points[:3]])

    # Format key themes with priority
    key_themes = briefing.get("key_themes", [])
    high_priority_themes = [t for t in key_themes if t.get("priority") == "high"]
    themes_text = ", ".join([t.get("theme", "") for t in high_priority_themes[:3]])

    # Format suggested questions
    suggested_questions = recommended.get("suggested_questions", [])
    questions_text = "\n".join([f"  {i+1}. {q}" for i, q in enumerate(suggested_questions)])

    prompt = f"""You are conducting a {therapy_plan.selected_therapy_style} therapy session. This is session #{session_number} with {user_profile.name}.

THERAPEUTIC CONTEXT:
Relationship Stage: {relationship.capitalize()}
Last Session Date: {briefing.get("last_session_date", "Recent")}

SUPERVISOR'S BRIEFING:
{narrative}

CLINICAL OBSERVATIONS FROM PREVIOUS SESSION:
{observations}

TREATMENT PLAN PROGRESSION:
{plan_notes}

EMOTIONAL STATE:
- Current: {briefing.get("emotional_summary", {}).get("last_session", "Not specified")}
- Trend: {briefing.get("emotional_summary", {}).get("trend", "Not specified")}
- Note: {briefing.get("emotional_summary", {}).get("note", "")}

CONTINUITY POINTS TO FOLLOW UP ON:
{continuity_text}

CURRENT HIGH-PRIORITY THEMES:
{themes_text if themes_text else "No specific themes identified"}

PROGRESS HIGHLIGHTS:
{chr(10).join([f"  ✓ {h}" for h in briefing.get("progress_highlights", [])[:3]])}

UNRESOLVED ISSUES REQUIRING ATTENTION:
{chr(10).join([f"  • {issue}" for issue in briefing.get("unresolved_issues", [])[:3]])}

RECOMMENDED APPROACH FOR THIS SESSION:
Tone: {recommended.get("opening_tone", "Warm and welcoming")}
Focus: {recommended.get("opening_focus", "General check-in")}
Avoid: {recommended.get("things_to_avoid", "Pushing too hard")}

Suggested Opening Questions (choose one or synthesize your own based on the above):
{questions_text}

Session Goals:
{chr(10).join([f"  {i+1}. {g}" for i, g in enumerate(recommended.get("therapeutic_goals_for_session", []))])}

YOUR TASK:
The patient has just entered the session. They have not spoken yet. Based on the comprehensive briefing above, generate a natural, conversational opening greeting that:

1. Welcomes them back warmly and authentically
2. Demonstrates continuity by referencing something specific from your last session together
3. Acknowledges their emotional state or progress if appropriate
4. Invites them to begin speaking in an open-ended way
5. Maintains the recommended tone and focus

IMPORTANT CONSTRAINTS:
- Keep your greeting to 2-4 sentences
- Be specific and personal - reference actual themes or topics from the briefing
- Sound natural and conversational, not scripted or formulaic
- Don't overwhelm them with everything from the briefing - choose what feels most relevant
- Match the therapeutic style ({therapy_plan.selected_therapy_style}) in your language and approach

Generate your opening greeting now:"""



    # Add specific guidance for STALE briefings
    if status == BriefingStatus.STALE:
        days_since = (datetime.now() - datetime.fromisoformat(briefing.get("generated_at", datetime.now().isoformat()))).days
        prompt += f"""

IMPORTANT - STALE BRIEFING NOTICE:
It has been approximately {days_since} days since the last session. The briefing above may not reflect the patient's current state. When generating your greeting:

1. Acknowledge the time gap explicitly but gently
2. Don't assume they're in the same emotional place as the briefing suggests
3. Be more open-ended and exploratory rather than assuming continuity
4. Focus on "what's been on your mind recently" rather than specific past themes
5. Use the briefing as background context, not as current truth

Example approach: "Welcome back, {user_profile.name}. It's been a while since we last spoke. I'm curious to hear what's been on your mind recently."
"""

    return prompt

```

---

#### Step 3.5: WebSocket Streaming Integration

**File:** `src/agents/trio_psychoanalyst_agent.py`

**Purpose:** Enable the Psychoanalyst Agent to stream the greeting chunk-by-chunk as it's generated, providing immediate feedback to the user and reducing perceived latency.

**Add Streaming Method to Agent:**

```python
# In TrioPsychoanalystAgent class

async def stream_initial_greeting(
    self,
    user_profile: UserProfile,
    therapy_plan: TherapyPlan
) -> AsyncIterator[str]:
    """
    Stream the initial greeting for a resuming therapy session.
    Yields chunks as they are generated by the LLM.

    Args:
        user_profile: User's profile information
        therapy_plan: Current therapy plan with session_briefing

    Yields:
        str: Chunks of the greeting message as they are generated

    Raises:
        ValueError: If therapy_plan or session_briefing is missing
    """
    if not therapy_plan or not therapy_plan.session_briefing:
        raise ValueError("Therapy plan with session briefing required for greeting generation")

    briefing = therapy_plan.session_briefing
    status = self.get_briefing_status(briefing)

    # Build the resumption prompt
    system_prompt = await self._build_resumption_prompt(
        user_profile,
        therapy_plan,
        briefing,
        status
    )

    # Create a minimal conversation context for streaming
    # (no previous messages since this is the opening)
    from orchestration.models import ConversationContext

    temp_context = ConversationContext(
        session_id="greeting_generation",
        user_profile=user_profile,
        therapy_plan=therapy_plan,
        message_history=[],
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=45
    )

    # Stream using ConversationManager's existing stream_response method
    # This ensures consistency with regular message streaming
    async for chunk in self.conversation_manager.stream_response(
        system_prompt,
        temp_context,
        use_rag=False  # Don't use RAG for greeting generation
    ):
        yield chunk

    logger.info(f"Completed streaming greeting for user {user_profile.user_id}")
```

**Integration with Server (Preview for Step 4):**

The server's `_send_resumption_greeting()` method will consume this stream:

```python
# In trio_server.py

async def _send_resumption_greeting(
    self,
    user_id: str,
    session_id: str,
    send_channel: MemorySendChannel
) -> None:
    """
    Send contextual resumption greeting by streaming from agent.
    Raises exceptions on failure (fail-fast).
    """
    logger.info(f"Generating resumption greeting for user {user_id}")

    # Get therapy plan and user profile
    therapy_plan = await trio.to_thread.run_sync(
        self.db_service.get_therapy_plan, user_id
    )
    if not therapy_plan or not therapy_plan.session_briefing:
        raise ValueError(f"No therapy plan or briefing found for user {user_id}")

    user_profile = await trio.to_thread.run_sync(
        self.db_service.get_user_profile, user_id
    )
    if not user_profile:
        raise ValueError(f"No user profile found for user {user_id}")

    # Get the agent
    agent = await self.orchestrator.get_or_create_agent("PSYCHOANALYST", user_id)

    # Stream the greeting chunk-by-chunk
    try:
        async for chunk in agent.stream_initial_greeting(user_profile, therapy_plan):
            await send_channel.send({
                "type": "chat_response_chunk",
                "data": {
                    "chunk": chunk,
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat(),
                    "is_complete": False
                }
            })

        # Send completion marker
        await send_channel.send({
            "type": "chat_response_chunk",
            "data": {
                "chunk": "",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "is_complete": True
            }
        })

        logger.info(f"Successfully streamed resumption greeting for user {user_id}")

    except Exception as e:
        logger.error(f"Error streaming resumption greeting: {e}")
        raise  # Fail fast - let error propagate to WebSocket handler
```

**Message Flow:**

```
1. User reconnects → Server detects PLAN_COMPLETE status
2. Server calls _send_resumption_greeting()
3. Agent.stream_initial_greeting() generates prompt
4. ConversationManager streams LLM response chunks
5. Each chunk → send_channel → WebSocket → Client
6. Client displays chunks as they arrive (progressive rendering)
7. Completion marker sent → Client knows greeting is complete
```

**Benefits of Streaming:**
- **Lower perceived latency**: User sees response starting within 1-2 seconds
- **Better UX**: Progressive text appearance feels more natural
- **Failure visibility**: If LLM fails mid-generation, client sees partial message + error
- **Consistent pattern**: Matches existing conversation streaming infrastructure

---

#### Step 4: Update Server Logic
**File:** `src/trio_server.py`

**Purpose:** The server logic uses fail-fast error handling with streaming. All fallback logic, metrics, and retry mechanisms are removed. Errors propagate immediately with full stack traces.

**Update `_send_resumption_greeting()`:**

```python
async def _send_resumption_greeting(
    self,
    user_id: str,
    session_id: str,
    send_channel: MemorySendChannel
) -> None:
    """
    Send contextual resumption greeting by streaming from Psychoanalyst Agent.

    This method implements fail-fast error handling:
    - Raises ValueError if therapy plan or briefing is missing
    - Raises ValueError if user profile is missing
    - Lets LLM generation errors propagate with full stack trace
    - No fallback messages or graceful degradation

    Args:
        user_id: User ID for greeting generation
        session_id: Active session ID
        send_channel: Trio memory channel for WebSocket communication

    Raises:
        ValueError: If required data (plan, briefing, profile) is missing
        Exception: Any LLM or streaming errors propagate directly
    """
    logger.info(f"Generating resumption greeting for user {user_id}, session {session_id}")

    # Get therapy plan using Trio pattern
    therapy_plan = await trio.to_thread.run_sync(
        self.db_service.get_therapy_plan, user_id
    )

    if not therapy_plan:
        raise ValueError(f"No therapy plan found for user {user_id}")

    if not therapy_plan.session_briefing:
        raise ValueError(f"Therapy plan missing session briefing for user {user_id}")

    # Get user profile using Trio pattern
    user_profile = await trio.to_thread.run_sync(
        self.db_service.get_user_profile, user_id
    )

    if not user_profile:
        raise ValueError(f"No user profile found for user {user_id}")

    # Get or create Psychoanalyst agent
    agent = await self.orchestrator.get_or_create_agent("PSYCHOANALYST", user_id)

    # Stream the greeting chunk-by-chunk (raises on error - fail fast)
    logger.debug(f"Starting greeting stream for user {user_id}")

    async for chunk in agent.stream_initial_greeting(user_profile, therapy_plan):
        await send_channel.send({
            "type": "chat_response_chunk",
            "data": {
                "chunk": chunk,
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "is_complete": False
            }
        })

    # Send completion marker
    await send_channel.send({
        "type": "chat_response_chunk",
        "data": {
            "chunk": "",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "is_complete": True
        }
    })

    logger.info(f"Successfully streamed resumption greeting for user {user_id}")
```

**Integration into WebSocket Handler:**

The resumption greeting is triggered when a user with `PLAN_COMPLETE` status starts a session:

```python
async def _handle_session_request_ws(self, data: dict, user_id: str, send_channel) -> None:
    """Handle session start request via WebSocket."""
    session_type = data.get("session_type", "therapy")

    # Get user profile and status
    user_profile = await trio.to_thread.run_sync(
        self.db_service.get_user_profile, user_id
    )

    if not user_profile:
        raise ValueError(f"User profile not found for {user_id}")

    # Determine if this is a resuming session
    has_initial_message = user_profile.status == UserStatus.PLAN_COMPLETE

    # Create session
    session = await self.orchestrator.start_session(user_id, session_type)

    # Send session_started message
    await send_channel.send({
        "type": "session_started",
        "data": {
            "session_id": session.session_id,
            "has_initial_message": has_initial_message,
            "timestamp": datetime.now().isoformat()
        }
    })

    # If resuming session, stream the contextual greeting
    if has_initial_message:
        # Raises on failure - error propagates to WebSocket error handler
        await self._send_resumption_greeting(user_id, session.session_id, send_channel)
```

**Error Handling at WebSocket Level:**

Errors from resumption greeting propagate to the WebSocket handler:

```python
async def _websocket_reader(self, websocket, receive_channel_sender):
    """Read messages from WebSocket and process them."""
    try:
        async for message in websocket:
            # ... process messages ...
    except ValueError as e:
        # Data validation errors (missing plan, profile, etc.)
        logger.error(f"Validation error in WebSocket: {e}")
        await websocket.send_json({
            "type": "error",
            "data": {
                "error": str(e),
                "error_type": "validation_error"
            }
        })
        raise
    except Exception as e:
        # All other errors (LLM failures, etc.)
        logger.error(f"Error in WebSocket reader: {e}", exc_info=True)
        await websocket.send_json({
            "type": "error",
            "data": {
                "error": str(e),
                "error_type": type(e).__name__
            }
        })
        raise
```

---

#### Step 5: Update Database Service
    """
    Save or update therapy plan.

    Includes session_briefing field (serialized as JSON).
    """
    try:
        cursor = self.conn.cursor()

        # Serialize session_briefing to JSON
        session_briefing_json = None
        if plan.session_briefing:
            session_briefing_json = json.dumps(plan.session_briefing)

        cursor.execute(
            """
            INSERT OR REPLACE INTO therapy_plans
            (plan_id, user_id, selected_style, plan_details, version,
             created_at, updated_at, session_briefing)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan.plan_id,
                plan.user_id,
                plan.selected_style,
                json.dumps(plan.plan_details),
                plan.version,
                plan.created_at.isoformat(),
                plan.updated_at.isoformat(),
                session_briefing_json  # NEW
            )
        )

        self.conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"Error saving therapy plan: {e}")
        return False
```

**Update `get_therapy_plan()` to deserialize session_briefing:**
```python
def get_therapy_plan(self, user_id: str) -> Optional[TherapyPlan]:
    """
    Get therapy plan for user.

    Deserializes session_briefing from JSON.
    """
    try:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT plan_id, user_id, selected_style, plan_details,
                   version, created_at, updated_at, session_briefing
            FROM therapy_plans
            WHERE user_id = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (user_id,)
        )

        row = cursor.fetchone()
        if not row:
            return None

        # Deserialize session_briefing
        session_briefing = None
        if row[7]:  # session_briefing column
            try:
                session_briefing = json.loads(row[7])
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse session_briefing for user {user_id}")

        return TherapyPlan(
            plan_id=row[0],
            user_id=row[1],
            selected_style=row[2],
            plan_details=json.loads(row[3]),
            version=row[4],
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
            session_briefing=session_briefing  # NEW
        )
    except sqlite3.Error as e:
        logger.error(f"Error getting therapy plan: {e}")
        return None
```

**Database Migration:**
```python
# Add to database initialization or migration script
def migrate_add_session_briefing(conn):
    """Add session_briefing column to therapy_plans table."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            ALTER TABLE therapy_plans
            ADD COLUMN session_briefing TEXT
            """
        )
        conn.commit()
        logger.info("Added session_briefing column to therapy_plans table")
        return True
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            logger.info("session_briefing column already exists")
            return True
        else:
            logger.error(f"Error adding session_briefing column: {e}")
            return False
```

---

## Testing Strategy

### Unit Tests

#### Test 1: Reflection Agent Briefing Generation
**File:** `tests/unit/test_trio_reflection_agent.py`

```python
@pytest.mark.trio
async def test_generate_session_briefing():
    """Test that reflection agent generates proper session briefing."""
    # Setup
    agent = create_test_reflection_agent()

    session_context = {
        "key_themes": ["work anxiety", "boundary setting"],
        "emotional_state": "anxious but hopeful",
        "insights": ["Client recognizes overcommitment pattern"],
        "progress_indicators": ["Increased self-awareness"]
    }

    memory = {
        "total_sessions": 3,
        "relationship_quality": "developing",
        "dominant_themes": [
            {"theme": "work anxiety", "frequency": 3}
        ]
    }

    plan_assessment = {
        "recommendations": ["Focus on boundary-setting exercises"]
    }

    # Execute
    briefing = await agent._generate_session_briefing(
        session_context, memory, plan_assessment, mock_plan
    )

    # Assert
    assert briefing["briefing_type"] == "resumption"
    assert briefing["relationship_quality"] == "developing"
    assert len(briefing["continuity_points"]) > 0
    assert "work anxiety" in str(briefing["key_themes"])
    assert briefing["recommended_approach"]["opening_tone"] == "warm and acknowledging"
```

#### Test 2: Psychoanalyst Agent Resumption Prompt
**File:** `tests/unit/test_trio_psychoanalyst_agent.py`

```python
@pytest.mark.trio
async def test_build_resumption_prompt():
    """Test that psychoanalyst builds appropriate resumption prompt."""
    # Setup
    agent = create_test_psychoanalyst_agent()

    briefing = {
        "relationship_quality": "developing",
        "continuity_points": ["Explored work anxiety"],
        "key_themes": [{"theme": "work anxiety", "status": "ongoing", "priority": "high"}],
        "progress_highlights": ["Used thought challenging"],
        "recommended_approach": {
            "opening_tone": "warm",
            "opening_focus": "Check in on boundary setting"
        }
    }

    # Execute
    prompt = await agent._build_resumption_prompt(
        mock_profile, mock_plan, briefing, []
    )

    # Assert
    assert "work anxiety" in prompt
    assert "thought challenging" in prompt
    assert "warm" in prompt
    assert "continuation" in prompt.lower() or "resuming" in prompt.lower()
```

#### Test 3: Session Briefing Persistence
**File:** `tests/unit/test_trio_db_service.py`

```python
def test_save_and_load_therapy_plan_with_briefing():
    """Test that session briefing persists correctly."""
    # Setup
    db_service = create_test_db_service()

    briefing = {
        "briefing_type": "resumption",
        "continuity_points": ["Test point"],
        "relationship_quality": "building"
    }

    plan = TherapyPlan(
        plan_id="test-plan",
        user_id="test-user",
        selected_style="CBT",
        plan_details={"focus": "test"},
        version=1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        session_briefing=briefing
    )

    # Execute
    success = db_service.save_therapy_plan(plan)
    assert success

    loaded_plan = db_service.get_therapy_plan("test-user")

    # Assert
    assert loaded_plan is not None
    assert loaded_plan.session_briefing is not None
    assert loaded_plan.session_briefing["briefing_type"] == "resumption"
    assert loaded_plan.session_briefing["relationship_quality"] == "building"
```

### Integration Tests

#### Test 4: Full Session Resumption Flow
**File:** `tests/integration/test_session_resumption.py`

```python
@pytest.mark.trio
async def test_complete_session_resumption_flow():
    """
    Test complete flow:
    1. Complete therapy session
    2. Reflection generates briefing
    3. Start new session
    4. Receive contextual greeting
    """
    # Phase 1: Complete a therapy session
    user_id = "test_resumption_user"

    # Conduct therapy session
    session1 = await conduct_test_therapy_session(user_id)

    # Trigger reflection
    reflection_response = await trigger_reflection(user_id, session1)

    # Verify briefing was created
    plan = await db_service.get_therapy_plan(user_id)
    assert plan.session_briefing is not None
    assert plan.session_briefing["briefing_type"] == "resumption"

    # Phase 2: Start new session
    session2_messages = await start_new_session(user_id)

    # Verify contextual greeting was sent
    assert len(session2_messages) > 0
    first_message = session2_messages[0]
    assert first_message["type"] == "chat_response_chunk"

    # Greeting should reference previous session
    greeting_content = "".join([m["data"]["chunk"] for m in session2_messages])
    assert "last session" in greeting_content.lower() or "welcome back" in greeting_content.lower()
```

#### Test 5: Greeting Streaming Behavior
**File:** `tests/integration/test_trio_websocket.py`

```python
@pytest.mark.trio
async def test_greeting_streams_progressively():
    """Test that greeting streams chunk-by-chunk, not all at once."""
    # Setup: Create user with PLAN_COMPLETE status and briefing
    user_id = "ws_test_user"
    await setup_resuming_user(user_id)

    # Connect via WebSocket
    async with websocket_client(user_id) as ws:
        # Send session request
        await ws.send_json({
            "type": "session_request",
            "data": {"session_type": "therapy"}
        })

        # Receive session_started
        msg1 = await ws.receive_json()
        assert msg1["type"] == "session_started"
        assert msg1["data"]["has_initial_message"] is True

        # Track chunk arrival times
        chunk_times = []
        chunks = []

        while True:
            msg = await ws.receive_json()
            if msg["type"] == "chat_response_chunk":
                chunk_times.append(datetime.now())
                chunk_data = msg["data"]

                if chunk_data["chunk"]:
                    chunks.append(chunk_data["chunk"])

                if chunk_data["is_complete"]:
                    break

        # Verify progressive streaming (not batched)
        assert len(chunks) > 1, "Should receive multiple chunks, not a single batch"

        # Verify chunks arrive over time (not all at once)
        if len(chunk_times) > 1:
            time_deltas = [(chunk_times[i+1] - chunk_times[i]).total_seconds()
                          for i in range(len(chunk_times)-1)]
            # At least some chunks should have measurable time between them
            assert any(delta > 0 for delta in time_deltas), "Chunks should arrive progressively"

        # Verify complete greeting is contextual
        greeting = "".join(chunks)
        assert len(greeting) > 0
        assert "welcome" in greeting.lower() or "back" in greeting.lower()
```

#### Test 6: Error Handling (Fail-Fast)
**File:** `tests/integration/test_session_resumption.py`

```python
@pytest.mark.trio
async def test_missing_briefing_raises_error():
    """Test that missing briefing causes immediate failure with proper error."""
    # Setup: User with PLAN_COMPLETE but no briefing
    user_id = "test_user_no_briefing"
    await setup_user_without_briefing(user_id)

    # Attempt to start session should raise ValueError
    with pytest.raises(ValueError, match="missing session briefing"):
        async with websocket_client(user_id) as ws:
            await ws.send_json({
                "type": "session_request",
                "data": {"session_type": "therapy"}
            })

            # Should receive error message
            msg = await ws.receive_json()
            assert msg["type"] == "error"
            assert "validation_error" in msg["data"]["error_type"]


@pytest.mark.trio
async def test_llm_failure_propagates():
    """Test that LLM failures propagate immediately without fallback."""
    # Setup: Mock LLM to fail
    user_id = "test_user_llm_fail"
    await setup_resuming_user(user_id)

    with patch.object(LLMService, 'generate_response_stream', side_effect=Exception("LLM unavailable")):
        with pytest.raises(Exception, match="LLM unavailable"):
            async with websocket_client(user_id) as ws:
                await ws.send_json({
                    "type": "session_request",
                    "data": {"session_type": "therapy"}
                })

                # Should receive error message
                msg = await ws.receive_json()
                if msg["type"] == "error":
                    assert "LLM" in msg["data"]["error"] or "unavailable" in msg["data"]["error"]
```

### Manual Testing

#### Test Scenario 1: First-Time User (No Briefing)
```
1. Start with NEW user
2. Complete intake → assessment → first therapy session
3. Verify first therapy session has generic initial prompt
4. Complete session → trigger reflection
5. Verify briefing is created in therapy plan
```

#### Test Scenario 2: Returning User (With Briefing)
```
1. Use user from Scenario 1 (now has briefing)
2. Start new therapy session
3. Verify:
   - has_initial_message=True in session_started
   - Contextual greeting references previous session
   - Greeting acknowledges progress or themes
   - Natural conversational tone
4. Continue conversation
5. Verify therapy continues normally
```

#### Test Scenario 3: Stale Briefing
```
1. Manually set briefing generated_at to 60 days ago (stale but not very stale)
2. Start new session
3. Verify:
   - Greeting is still generated (uses STALE briefing)
   - Greeting acknowledges time gap ("It's been a while...")
   - Greeting is more exploratory, less specific than fresh briefing
4. Manually set briefing generated_at to 100 days ago (very stale)
5. Start new session
6. Verify greeting treats context as background, not current truth
```

#### Test Scenario 4: Error Cases (Fail-Fast Validation)
```
1. Remove session_briefing from therapy plan
2. Attempt to start session with PLAN_COMPLETE user
3. Verify:
   - Immediate ValueError raised
   - Stack trace visible in logs
   - WebSocket receives error message
   - No fallback greeting attempted

4. Mock LLM to return invalid JSON
5. Start session
6. Verify:
   - JSONDecodeError raised
   - Error logged with full LLM output
   - No fallback, session start fails
```

---

## Migration & Rollout

### Database Migration

**Script:** `migrations/add_session_briefing.py`
```python
import sqlite3
import logging

logger = logging.getLogger(__name__)

def migrate_database(db_path: str) -> bool:
    """Add session_briefing column to therapy_plans table."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if column already exists
        cursor.execute("PRAGMA table_info(therapy_plans)")
        columns = [row[1] for row in cursor.fetchall()]

        if "session_briefing" in columns:
            logger.info("session_briefing column already exists")
            return True

        # Add column
        cursor.execute(
            "ALTER TABLE therapy_plans ADD COLUMN session_briefing TEXT"
        )
        conn.commit()
        conn.close()

        logger.info("Successfully added session_briefing column")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False

if __name__ == "__main__":
    import sys
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/psychoanalyst.db"
    success = migrate_database(db_path)
    sys.exit(0 if success else 1)
```

**Run migration:**
```bash
python migrations/add_session_briefing.py data/psychoanalyst.db
python migrations/add_session_briefing.py data/psychoanalyst_usertest.db
```

### Rollout Plan

**Approach**: Sequential deployment in development environment with fail-fast validation at each stage.

**Stage 1: Database Schema**
- Run migration to add `session_briefing` column
- Verify column exists in both dev and test databases
- Test database service can save/load plans with briefing field

**Stage 2: Data Models & Configuration**
- Deploy `briefing_models.py` with Pydantic models
- Update `config.py` with session resumption settings
- Update `data_models.py` to include `session_briefing` in TherapyPlan
- Run unit tests to verify model validation

**Stage 3: Reflection Agent**
- Deploy updated `trio_reflection_agent.py` with briefing generation
- Run reflection agent unit tests
- Verify briefings are generated and persisted correctly
- Check logs for any LLM generation or validation errors

**Stage 4: Psychoanalyst Agent & Server**
- Deploy updated `trio_psychoanalyst_agent.py` with streaming greeting method
- Deploy updated `trio_server.py` with resumption greeting logic
- Run full integration test suite
- Manually test end-to-end flow: session → reflection → new session → greeting

**Validation at Each Stage:**
- All tests must pass before proceeding to next stage
- Check error logs for unexpected exceptions
- Verify fail-fast behavior: errors should surface immediately, not be suppressed

**Logging:**
- Log when briefing is generated (INFO level)
- Log when resumption greeting starts streaming (INFO level)
- Log all errors with full stack traces (ERROR level with exc_info=True)

---

## Future Enhancements

### Phase 2: Enhanced Ongoing Context

**Goal:** Maintain continuity throughout session, not just opening

**Changes:**
1. Add `therapeutic_memory` to `ConversationContext`
2. Update continuation prompts to reference previous sessions
3. Enhanced RAG retrieval including previous session excerpts
4. Theme tracking across conversation turns

### Phase 3: Adaptive Relationship Building

**Goal:** Adjust communication style based on relationship quality

**Features:**
- Relationship quality assessment (new → building → developing → established → strong)
- Adaptive language formality
- Appropriate self-disclosure levels
- Calibrated directness/gentleness

### Phase 4: Progress Visualization

**Goal:** Help users and therapists track therapeutic progress

**Features:**
- Session-by-session theme evolution charts
- Emotional state timeline
- Goal completion tracking
- Intervention effectiveness tracking

### Phase 5: Multi-Session Treatment Plans

**Goal:** Structured therapy protocols spanning multiple sessions

**Features:**
- Protocol templates (e.g., 12-week CBT for anxiety)
- Session-specific goals and techniques
- Milestone tracking
- Automated progress reports

---

## Appendix

### Example Session Briefing (Complete)

```json
{
  "briefing_type": "resumption",
  "generated_at": "2025-11-15T14:30:00",
  "session_count": 5,
  "last_session_id": "uuid-session-5",
  "last_session_date": "2025-11-14",

  "relationship_quality": "developing",

  "continuity_points": [
    "Explored work-related anxiety and identified specific triggers (meetings with supervisor)",
    "Client showed openness to CBT thought-challenging techniques",
    "Made progress recognizing pattern of overcommitment and people-pleasing",
    "Discussed childhood experiences with achievement-focused parents"
  ],

  "emotional_summary": {
    "last_session": "anxious but hopeful",
    "trend": "improving",
    "note": "Client reported feeling more in control by end of session; interested in homework assignment"
  },

  "key_themes": [
    {
      "theme": "work anxiety",
      "status": "ongoing",
      "priority": "high",
      "frequency": 4,
      "first_appearance": "session-1",
      "last_discussed": "session-5"
    },
    {
      "theme": "boundary setting",
      "status": "newly introduced",
      "priority": "high",
      "frequency": 2,
      "first_appearance": "session-4",
      "last_discussed": "session-5"
    },
    {
      "theme": "perfectionism",
      "status": "underlying",
      "priority": "medium",
      "frequency": 3,
      "first_appearance": "session-1",
      "last_discussed": "session-5"
    },
    {
      "theme": "childhood achievement pressure",
      "status": "emerging",
      "priority": "medium",
      "frequency": 1,
      "first_appearance": "session-5",
      "last_discussed": "session-5"
    }
  ],

  "progress_highlights": [
    "Successfully used thought challenging technique between sessions",
    "Increased self-awareness about anxiety triggers",
    "Willing to explore deeper patterns (childhood experiences)"
  ],

  "unresolved_issues": [
    "Childhood patterns related to achievement and parental approval",
    "Fear of disappointing others leading to overcommitment",
    "Specific strategies for setting boundaries with supervisor"
  ],

  "recommended_approach": {
    "opening_tone": "warm and acknowledging",
    "opening_focus": "Check in on thought-challenging homework; explore boundary-setting with supervisor if client brings it up",
    "things_to_avoid": "Rushing into childhood exploration without checking progress on immediate work concerns first",
    "session_goals": [
      "Reinforce CBT techniques if showing progress",
      "Address any barriers to boundary-setting",
      "Continue building therapeutic alliance"
    ]
  },

  "plan_effectiveness": {
    "score": 7.5,
    "working_well": [
      "CBT techniques align with client's analytical style",
      "Psychoeducation about anxiety is well-received"
    ],
    "needs_adjustment": [
      "May need to incorporate more experiential exercises",
      "Consider adding specific boundary-setting protocols"
    ]
  }
}
```

### Example Generated Greeting

**Input:** Above briefing
**Output:**
```
Welcome back! I've been thinking about our last session where you shared
those insights about recognizing your pattern of overcommitment. You seemed
genuinely hopeful about trying the thought-challenging technique we discussed.
How did that go for you this week?
```

---

## Summary

This plan implements a comprehensive session resumption system that:

1. **Leverages existing infrastructure** (Memory Agent, Planning Agent, Reflection Agent)
2. **Maintains separation of concerns** (Reflection analyzes, Psychoanalyst converses)
3. **Provides natural continuity** through contextual greetings
4. **Scales progressively** from basic briefing to advanced relationship tracking
5. **Is backward compatible** with existing therapy plans
6. **Follows TDD principles** with comprehensive test coverage

**Estimated Implementation Time:** 2-3 days
**Risk Level:** Low-Medium (backward compatible, incremental rollout)
**User Impact:** High (significantly improves therapeutic experience)

---

## 9. Reviewer's Feedback and Refinements

This section incorporates feedback and suggestions for potential improvements to the plan, aiming to enhance robustness, scalability, and efficiency.

#### 9.1. Architectural & Design Refinements

*   **Refactor Server-Agent Interaction:**
    *   **Observation:** The current plan in `src/trio_server.py` directly calls the Psychoanalyst Agent's internal method `_build_resumption_prompt`. This creates a tight coupling between the server and the agent's internal implementation.
    *   **Recommendation:** Promote better encapsulation. The server should invoke a high-level, public method on the agent (e.g., `agent.generate_initial_message(user_profile, therapy_plan, session_id, send_channel)`). The agent itself would then be responsible for inspecting the context (e.g., checking for a briefing) and deciding which internal prompt-building logic to use. This makes the agent a more autonomous and swappable component.

*   **Consider Decoupling `session_briefing` from `TherapyPlan` (Long-term):**
    *   **Observation:** Storing the `session_briefing` directly within the `TherapyPlan` is pragmatic for MVP. However, a `TherapyPlan` represents a long-term strategy, while a `session_briefing` is a tactical summary of the *most recent* session. Overwriting the briefing with each new reflection might lose historical context.
    *   **Consideration:** For future scalability and historical analysis, a separate `SessionSummaries` entity or table could store each briefing, linked to the session it concludes. The `TherapyPlan` could then reference the *latest valid summary*. This is a more complex data model but offers better data normalization and historical tracking. For the current MVP, the existing approach is acceptable due to its simplicity.

#### 9.2. Agent & Prompt Engineering Enhancements

*   **Enhance Reflection Agent to Generate Narrative Summary:**
    *   **Observation:** The `_build_resumption_prompt` in the Psychoanalyst Agent is complex, reconstructing context from many discrete data points in the briefing. This makes the prompt brittle and long.
    *   **Recommendation:** Empower the Reflection Agent to do more synthesis. Instead of just providing structured data, it should use an LLM to generate a concise, 2-3 paragraph **narrative summary** of the previous session's key takeaways, progress, and unresolved issues. This narrative could be stored in a new `narrative_handoff` field within the `session_briefing`. The Psychoanalyst Agent's resumption prompt would then primarily inject this pre-digested narrative, making it simpler, more robust, and less prone to breaking with briefing structure changes.

*   **Consolidate Briefing Generation with Structured LLM Call:**
    *   **Observation:** The `_generate_session_briefing` method currently uses several Python helper functions with simple heuristics (e.g., `_assess_emotional_trend`, `_determine_opening_focus`). The plan acknowledges these are placeholders for potential LLM calls. Making multiple small LLM calls can be inefficient and costly.
    *   **Recommendation:** Create a single, powerful prompt for the Reflection Agent. This prompt would take in all relevant raw context (session transcript, memory, plan assessment) and instruct the LLM to generate the entire `session_briefing` JSON object (including the new `narrative_handoff`) in one shot, leveraging function calling or a structured output format. This maximizes LLM synthesis capabilities and improves efficiency.

#### 9.3. Testing Enhancements

*   **Add Quality-Focused Testing for LLM Outputs:**
    *   **Observation:** The current testing strategy focuses on whether the briefing is *generated* and *persists*, and if the prompt *contains* certain keywords. It doesn't explicitly test the *quality* or *relevance* of the generated briefing content or the contextual greeting.
    *   **Recommendation:** Consider adding:
        *   **Snapshot Testing for Prompts:** Store expected prompt structures (or parts of them) as snapshots and compare against generated prompts.
        *   **Evaluation-Based Testing:** For critical LLM outputs (like the narrative summary or the final greeting), use a separate LLM or human evaluation to score the output against a rubric (e.g., relevance, coherence, tone). This is more advanced but crucial for LLM-driven features.
