# Refined Patient Information System - Implementation Plan

## 1. Executive Summary

### Problem Statement
The current system stores minimal patient information in a simple `UserProfile` model and basic `Session` records. This limits the therapist agent's ability to:
- Maintain context about patient background across sessions
- Track evolving clinical understanding over time
- Monitor treatment progress toward therapeutic goals
- Provide contextually rich, informed therapeutic responses

### Proposed Solution
Implement a tiered patient information structure inspired by psychoanalytic practice, organizing data by volatility and purpose:

- **Tier 1 (Static Background)**: Relatively stable background information collected during intake
- **Tier 2 (Session History)**: Rich session summaries with psychological analysis
- **Tier 3 (Dynamic Analysis)**: Evolving clinical formulation with version history
- **Tier 4 (Treatment Trajectory)**: Treatment goals and progress tracking

### Expected Outcomes
- Richer therapeutic conversations informed by comprehensive patient context
- Better continuity across sessions with detailed history
- Transparent evolution of clinical understanding through versioning
- Goal-oriented therapy with measurable progress tracking

### Timeline
6 weeks, phased implementation (see Section 8)

### Resources Required
- LLM API calls: Additional structured extraction calls (~3-5 per session)
- Storage: JSON-based SQLite storage (~100KB-500KB per patient)
- Development: Data models, database schema, agent modifications, testing

---

## 2. Requirements

### 2.1 Functional Requirements

**FR1: Tier 1 - Static Background**
- System SHALL capture structured patient background during intake
- Background SHALL include: basic info, family, education/work, relational context, analytic frame
- Tier 1 data SHALL be available to all subsequent agents for context

**FR2: Tier 2 - Session History**
- System SHALL enrich each session with psychological summary, dominant affects, key themes, notable interactions
- Session enrichment SHALL occur automatically after session completion
- Enriched sessions SHALL be immutable (no modifications after creation)

**FR3: Tier 3 - Dynamic Analysis**
- System SHALL maintain versioned clinical formulation including: current focus, transference impressions, recurring narratives, defensive organization, analytic orientation
- System SHALL create new versions when clinical understanding evolves
- System SHALL track what changed between versions with change summaries

**FR4: Tier 4 - Treatment Trajectory**
- System SHALL track initial goals, current progress, planned interventions
- System SHALL update treatment progress periodically
- Progress assessments SHALL be qualitative and clinically meaningful

**FR5: Agent Integration**
- Intake Agent SHALL populate Tier 1
- Assessment Agent SHALL create initial Tier 3 and Tier 4
- Psychoanalyst Agent SHALL read all tiers for context (read-only)
- Reflection Agent SHALL enrich sessions and update dynamic tiers

### 2.2 Non-Functional Requirements

**NFR1: Performance**
- Patient profile retrieval: <200ms
- Session enrichment: <30 seconds after session end
- LLM context preparation: <500ms

**NFR2: Scalability**
- Support 100+ session records per patient
- Support 50+ analysis versions per patient
- JSON storage per patient: <5MB

**NFR3: Data Quality**
- Structured extraction accuracy: >90% for Tier 1 fields
- All sessions SHALL have Tier 2 enrichment
- Analysis updates SHALL only occur when meaningful change detected

**NFR4: Reliability**
- Failed enrichment SHALL not block workflow
- System SHALL gracefully handle missing patient data
- Extraction errors SHALL be logged for review

---

## 3. System Design

### 3.1 Data Models (Complete Specifications)

All models defined in [src/models/data_models.py](../src/models/data_models.py) using Pydantic with full validation.

#### Tier 1: Static Background

```python
class BasicPatientBackground(BaseModel):
    """Core demographic and identity information."""

    alias: str = Field(..., min_length=1, max_length=100, description="Patient pseudonym for confidentiality")
    date_of_birth: datetime | None = Field(None, description="Date of birth for age calculation")
    gender: str | None = Field(None, description="Gender identity")
    cultural_background: str | None = Field(None, max_length=500, description="Cultural, ethnic, or religious background")
    primary_language: str = Field(default="English", max_length=50, description="Primary language spoken")

class FamilyConstellation(BaseModel):
    """Family background and dynamics."""

    parents: str | None = Field(None, max_length=1000, description="Information about parents (alive, deceased, relationship quality)")
    siblings: str | None = Field(None, max_length=500, description="Siblings and birth order")
    family_atmosphere: str | None = Field(None, max_length=1000, description="Emotional climate of family of origin")
    significant_events: str | None = Field(None, max_length=1000, description="Major family events (trauma, loss, disruptions)")

class EducationalWorkHistory(BaseModel):
    """Educational and occupational background."""

    education: str | None = Field(None, max_length=500, description="Educational history and achievements")
    work_history: str | None = Field(None, max_length=1000, description="Career history and major job transitions")
    relationship_to_work: str | None = Field(None, max_length=500, description="Psychological relationship to work (identity, conflict, satisfaction)")

class RelationalLifeContext(BaseModel):
    """Current relational and social context."""

    relationships: str | None = Field(None, max_length=1000, description="Romantic relationships, friendships, significant others")
    social_context: str | None = Field(None, max_length=500, description="Social network, isolation, community involvement")
    current_situation: str | None = Field(None, max_length=1000, description="Current life circumstances and stressors")

class AnalyticFrame(BaseModel):
    """Therapeutic frame and preferences."""

    preferred_school: str | None = Field(None, description="Preferred therapeutic approach if specified")
    boundary_notes: str | None = Field(None, max_length=500, description="Special boundary considerations")
    frame_notes: str | None = Field(None, max_length=500, description="Other frame-related notes")

class PatientProfile(BaseModel):
    """
    Tier 1: Static patient background.

    Supplements the existing UserProfile with rich structured background.
    Created during intake, rarely updated.
    """

    user_id: str
    basic_info: BasicPatientBackground
    family: FamilyConstellation
    history: EducationalWorkHistory
    context: RelationalLifeContext
    frame: AnalyticFrame
    created_at: datetime
    updated_at: datetime
```

#### Tier 2: Session History

```python
class DetailedSession(BaseModel):
    """
    Tier 2: Enriched session record with psychological analysis.

    Extends basic Session with clinical summary data.
    Created during session, enriched once by Reflection Agent, then immutable.
    """

    # Standard session fields
    session_id: str
    user_id: str
    timestamp: datetime
    transcript: list[Message]
    topics: list[Topic] = []

    # Tier 2 enrichment fields (added by Reflection Agent)
    psychological_summary: str | None = Field(None, max_length=3000, description="2-3 paragraph clinical summary of session content")
    dominant_affects: list[str] = Field(default_factory=list, description="Primary emotional states observed (e.g., 'anxiety', 'sadness', 'anger')")
    key_themes: list[str] = Field(default_factory=list, description="Major themes and concerns discussed")
    notable_interactions: str | None = Field(None, max_length=1500, description="Significant transference/countertransference moments")
    interpretations: str | None = Field(None, max_length=1000, description="Interpretations offered during session")
    patient_reactions: str | None = Field(None, max_length=1000, description="Patient responses to interventions")
    enriched: bool = Field(default=False, description="Flag indicating Tier 2 data has been added")
```

#### Tier 3: Dynamic Analysis

```python
class CurrentFocus(BaseModel):
    """Current therapeutic focus and salience."""

    theme: str = Field(..., max_length=200, description="Central theme or concern")
    salience: str = Field(..., max_length=500, description="Why this theme is salient now")

class TransferenceImpressions(BaseModel):
    """Observations about transference patterns."""

    idealization: str | None = Field(None, max_length=500, description="Idealizing transference patterns")
    devaluation: str | None = Field(None, max_length=500, description="Devaluing transference patterns")
    boundaries: str | None = Field(None, max_length=500, description="Boundary testing or violations")
    other_patterns: str | None = Field(None, max_length=1000, description="Other notable transference dynamics")

class RecurringNarrative(BaseModel):
    """A recurring story or theme in patient's discourse."""

    title: str = Field(..., max_length=100, description="Short label for this narrative")
    description: str = Field(..., max_length=1000, description="Description of the narrative and its significance")
    first_appeared: str | None = Field(None, description="When this narrative first emerged (session ID or date)")

class DefensiveOrganization(BaseModel):
    """Defensive patterns and coping mechanisms."""

    primary_defenses: list[str] = Field(default_factory=list, description="Main defense mechanisms (e.g., 'intellectualization', 'projection')")
    defensive_style: str | None = Field(None, max_length=500, description="Overall defensive organization")
    flexibility: str | None = Field(None, max_length=300, description="Rigidity vs flexibility of defenses")

class AnalyticOrientation(BaseModel):
    """Therapeutic stance and approach recommendations."""

    pacing: str | None = Field(None, max_length=300, description="Recommended pace of intervention")
    risk_areas: list[str] = Field(default_factory=list, description="Areas requiring caution")
    key_questions: list[str] = Field(default_factory=list, description="Important questions to explore")

class PatientAnalysis(BaseModel):
    """
    Tier 3: Dynamic clinical formulation.

    The analyst's evolving understanding of the patient.
    Versioned - new version created when understanding shifts.
    """

    current_focus: CurrentFocus
    transference: TransferenceImpressions
    narratives: list[RecurringNarrative] = Field(default_factory=list)
    defenses: DefensiveOrganization
    orientation: AnalyticOrientation

class PatientAnalysisVersion(BaseModel):
    """
    Versioned wrapper for PatientAnalysis.

    Tracks evolution of clinical understanding over time.
    """

    analysis_id: str = Field(default_factory=lambda: f"analysis_{uuid.uuid4().hex[:12]}")
    user_id: str
    version: int = Field(..., ge=1, description="Version number (1, 2, 3, ...)")
    analysis_data: PatientAnalysis
    created_at: datetime = Field(default_factory=datetime.now)
    created_by_session: str | None = Field(None, description="Session ID that triggered this version")
    change_summary: str | None = Field(None, max_length=1000, description="What changed from previous version")
    superseded_by: str | None = Field(None, description="Analysis ID of next version (if superseded)")
```

#### Tier 4: Treatment Trajectory

```python
class TherapyPlan(BaseModel):
    """
    Tier 4: Treatment goals and progress tracking.

    Created during assessment, updated periodically during therapy.
    """

    plan_id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:12]}")
    user_id: str
    # Legacy therapy plan fields (already used by the system)
    plan_details: dict[str, Any] = Field(..., description="Structured style-specific plan details")
    session_briefing: dict[str, Any] | None = Field(None, description="Briefing for the next session")
    version: int = Field(..., ge=1, description="Version number of the plan")
    selected_therapy_style: str | None = Field(None, description="Chosen therapy style")

    # Tier 4 treatment-trajectory fields (new)
    initial_goals: list[str] = Field(..., min_items=1, description="Therapeutic goals identified during assessment")
    current_progress: str = Field(..., min_length=1, max_length=2000, description="Qualitative assessment of progress toward goals")
    planned_interventions: list[str] = Field(..., min_items=1, description="Planned therapeutic interventions or directions")
    status: str = Field(default="active", pattern="^(active|paused|completed)$", description="Treatment status")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
```

### 3.2 Database Schema

SQLite schema using JSON storage for flexibility with qualitative data.

```sql
-- Tier 1: Patient Profiles
CREATE TABLE patient_profiles (
    user_id TEXT PRIMARY KEY,
    profile_data TEXT NOT NULL,  -- Serialized PatientProfile JSON
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_patient_profiles_updated ON patient_profiles(updated_at);

-- Tier 2: Extend existing sessions table
ALTER TABLE sessions ADD COLUMN psychological_summary TEXT;
ALTER TABLE sessions ADD COLUMN dominant_affects TEXT; -- JSON array
ALTER TABLE sessions ADD COLUMN key_themes TEXT; -- JSON array
ALTER TABLE sessions ADD COLUMN notable_interactions TEXT;
ALTER TABLE sessions ADD COLUMN interpretations TEXT;
ALTER TABLE sessions ADD COLUMN patient_reactions TEXT;
ALTER TABLE sessions ADD COLUMN enriched INTEGER DEFAULT 0;

-- Tier 3: Patient Analysis with Versioning
CREATE TABLE patient_analysis (
    analysis_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    analysis_data TEXT NOT NULL,  -- Serialized PatientAnalysis JSON
    created_at TEXT NOT NULL,
    created_by_session TEXT,  -- Session that triggered this version
    change_summary TEXT,
    superseded_by TEXT,  -- Points to next version's analysis_id
    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_session) REFERENCES sessions(session_id) ON DELETE SET NULL,
    FOREIGN KEY (superseded_by) REFERENCES patient_analysis(analysis_id) ON DELETE SET NULL,
    UNIQUE(user_id, version)
);

CREATE INDEX idx_analysis_user_version ON patient_analysis(user_id, version DESC);
CREATE INDEX idx_analysis_created ON patient_analysis(created_at);

-- Tier 4: Unified Therapy Plans (includes treatment trajectory fields)
-- NOTE: Migration history previously created a `treatment_plans` table,
-- but the current system stores Tier 4 inside the existing `therapy_plans` table.
ALTER TABLE therapy_plans ADD COLUMN initial_goals TEXT; -- JSON array
ALTER TABLE therapy_plans ADD COLUMN current_progress TEXT;
ALTER TABLE therapy_plans ADD COLUMN planned_interventions TEXT; -- JSON array
ALTER TABLE therapy_plans ADD COLUMN status TEXT;

-- Async Tier 2 enrichment queue (background worker)
CREATE TABLE session_enrichment_jobs (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued', 'processing', 'complete', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
);

-- Tier 1 audit history for rare updates
CREATE TABLE patient_profile_history (
    history_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    previous_profile_data TEXT NOT NULL,
    new_profile_data TEXT NOT NULL,
    change_summary TEXT,
    created_at TEXT NOT NULL,
    created_by_session TEXT,
    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_session) REFERENCES sessions(session_id) ON DELETE SET NULL
);
```

**Indexing Strategy:**
- Primary lookups by `user_id` (most common access pattern)
- Analysis version lookup optimized with DESC index (latest version retrieved most often)
- Treatment plan status for filtering active plans

### 3.3 Tier Structure Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    PATIENT INFORMATION FILE                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  TIER 1: STATIC BACKGROUND (Low Volatility)                │
│  ├─ Basic Info (name, age, culture, language)              │
│  ├─ Family (parents, siblings, atmosphere, events)         │
│  ├─ History (education, work, relationship to work)        │
│  ├─ Context (relationships, social, current situation)     │
│  └─ Frame (school, mode, boundaries)                       │
│  Created: Intake | Updated: Rarely (exception-based)       │
│                                                              │
│  TIER 2: SESSION HISTORY (Medium Volatility)               │
│  ├─ Session transcript                                      │
│  ├─ Psychological summary                                   │
│  ├─ Dominant affects                                        │
│  ├─ Key themes                                              │
│  ├─ Notable interactions                                    │
│  └─ Interpretations & reactions                            │
│  Created: After each session | Updated: Never (immutable)  │
│                                                              │
│  TIER 3: DYNAMIC ANALYSIS (High Volatility, Versioned)     │
│  ├─ Current Focus (theme, salience)                        │
│  ├─ Transference Impressions                               │
│  ├─ Recurring Narratives                                   │
│  ├─ Defensive Organization                                 │
│  └─ Analytic Orientation (pacing, risks, questions)       │
│  Created: Assessment | Updated: When understanding shifts   │
│  Versions: v1, v2, v3... (history preserved)              │
│                                                              │
│  TIER 4: TREATMENT TRAJECTORY (Periodic Updates)           │
│  ├─ Initial Goals                                          │
│  ├─ Current Progress                                       │
│  ├─ Planned Interventions                                  │
│  └─ Status (active/paused/completed)                       │
│  Created: Assessment | Updated: Periodically (~every 5th)  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Implementation Details

### 4.1 Database Service Changes

**File**: [src/services/trio_db_service.py](../src/services/trio_db_service.py)

**New Methods to Add:**

```python
# Tier 1 Methods
async def get_patient_profile(self, user_id: str) -> PatientProfile | None:
    """Retrieve patient profile (Tier 1) for user."""

async def save_patient_profile(self, profile: PatientProfile) -> None:
    """Create or replace patient profile."""

async def update_patient_profile(self, profile: PatientProfile) -> None:
    """Update existing patient profile (rare operation)."""

# Tier 2 Methods
async def get_recent_sessions(self, user_id: str, limit: int = 5) -> list[DetailedSession]:
    """Get recent enriched sessions for context."""

async def update_session_tier2(self, session_id: str, tier2_data: dict) -> None:
    """Add Tier 2 enrichment to session (one-time operation)."""

async def get_session_count(self, user_id: str) -> int:
    """Get total session count for user (for milestone tracking)."""

# Tier 3 Methods
async def get_latest_patient_analysis(self, user_id: str) -> PatientAnalysisVersion | None:
    """Get most recent version of patient analysis."""

async def get_patient_analysis_version(self, user_id: str, version: int) -> PatientAnalysisVersion | None:
    """Get specific version of patient analysis."""

async def get_analysis_history(self, user_id: str) -> list[PatientAnalysisVersion]:
    """Get all analysis versions (for review/audit)."""

async def save_patient_analysis_version(self, analysis: PatientAnalysisVersion) -> None:
    """Save new version of patient analysis."""

async def mark_analysis_superseded(self, old_analysis_id: str, new_analysis_id: str) -> None:
    """Mark previous version as superseded by new version."""

# Tier 4 Methods
async def get_current_therapy_plan(self, user_id: str) -> TherapyPlan | None:
    """Get the latest unified therapy plan (includes Tier 4 fields)."""

async def save_therapy_plan(self, plan: TherapyPlan) -> None:
    """Create or update a therapy plan (versioned)."""
```

**Implementation Notes:**
- All methods use `trio.to_thread.run_sync()` for SQLite operations
- JSON serialization via Pydantic's `.model_dump_json()` and `.model_validate()`
- Error handling for missing data (return `None` instead of raising)
- Transactions for multi-step operations (e.g., creating new version + marking old as superseded)

### 4.2 Agent Modifications Overview

Four agents require modifications:
1. **Intake Agent** - Extract and save Tier 1
2. **Assessment Agent** - Create initial Tier 3 and Tier 4, use Tier 1 for context
3. **Psychoanalyst Agent** - Read all tiers for context (read-only)
4. **Reflection Agent** - Enrich Tier 2, update Tier 3 & 4

Detailed specifications in Section 5.

---

## 5. Agent Data Consumption & Production Patterns

### 5.1 Data Flow Principles

**Core Design Rules:**

1. **Read-Many, Write-Few**: Most agents read patient data; only Reflection Agent writes regularly
2. **Current Data Only in LLM Context**: Prompts include latest/current versions, not historical versions
3. **Progressive Context Accumulation**: Each session enriches the patient file, future sessions benefit from richer context
4. **Selective Updates**: Don't regenerate entire structures; update only fields that changed
5. **LLM-Driven Change Detection**: Use LLM to determine if updates are needed

**Agent Write Permissions:**

| Agent | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|-------|--------|--------|--------|--------|
| **Intake** | ✅ Create | ❌ | ❌ | ❌ |
| **Assessment** | ❌ | ❌ | ✅ Create v1 | ✅ Create initial |
| **Psychoanalyst** | ❌ | ❌ | ❌ | ❌ |
| **Reflection** | ⚠️ Rare updates | ✅ Enrich | ✅ Version updates | ✅ Periodic updates |

**Legend:**
- ✅ Primary writer
- ⚠️ Conditional/rare writes
- ❌ Read-only

**Note**: Session records themselves are created by the workflow engine, not agents directly. Agents only populate/enrich session content.

### 5.2 Intake Agent

**File**: [src/agents/trio_intake_agent.py](../src/agents/trio_intake_agent.py)

#### Data Access Pattern

**Reads**: Nothing (clean slate)

**Writes**: Tier 1 - Complete `PatientProfile` after intake completion

#### Modification Summary

Add `_extract_tier1_data()` method that uses LLM structured output to extract patient background from intake conversation. Called at end of intake to populate PatientProfile. See Appendix A for full prompt template.

### 5.3 Assessment Agent

**File**: [src/agents/trio_assessment_agent.py](../src/agents/trio_assessment_agent.py)

#### Data Access Pattern

**Reads**: Tier 1 - Full `PatientProfile` for background context

**Writes**:
- Tier 3: Initial `PatientAnalysis` (version 1)
- Tier 4: Initial `TherapyPlan` (Tier 4 fields populated)

#### Modification Summary

1. Load Tier 1 at assessment start, inject into prompts for context-aware responses
2. On completion: Create initial clinical formulation (Tier 3 v1) and treatment plan (Tier 4)
3. Use LLM structured output for both extractions

### 5.4 Psychoanalyst Agent

**File**: [src/agents/trio_therapist_agent.py](../src/agents/trio_therapist_agent.py)

#### Data Access Pattern

**Reads**:
- Tier 1: Full `PatientProfile` (background)
- Tier 2: Recent sessions (last 3-5 for continuity)
- Tier 3: Latest `PatientAnalysis` (current understanding)
- Tier 4: Current `TherapyPlan` (goals/progress)

**Writes**: ❌ Nothing (read-only agent)

#### Modification Summary

1. Add `_load_patient_context()` method to load all tiers (current versions only) at session start
2. Format patient file data into LLM-ready context
3. Inject comprehensive context into session prompts
4. **No LLM calls on context load**: Tier 2 is read as “enriched-only” and missing enrichments are queued for background processing

**Key Design**: Only **current/latest** data included in prompts, not version history. This keeps context focused and token count manageable.

### 5.5 Reflection Agent

**File**: [src/agents/trio_reflection_agent.py](../src/agents/trio_reflection_agent.py)

#### Data Access Pattern

**Reads**:
- Tier 1: Current profile (to check for updates)
- Tier 2: Latest session (to enrich)
- Tier 3: Current analysis (to evaluate for updates)
- Tier 4: Current plan (to evaluate for updates)

**Writes**:
- Tier 2: Enriches session with psychological data (ONE TIME)
- Tier 3: Creates new version if understanding changed (CONDITIONAL)
- Tier 4: Updates progress periodically (PERIODIC)
- Tier 1: Updates rarely when new background emerges (RARE)

#### Modification Summary

This is the **primary writer agent**. After each session:

1. **Enrich Tier 2** (always): Session enrichment is queued on session completion and processed asynchronously by a background worker (reflection may also enrich directly when running).
2. **Check Tier 1** (rare): Detect if patient revealed new/corrected background info
3. **Update Tier 3** (conditional): LLM evaluates if clinical formulation should be updated; if yes, create new version
4. **Update Tier 4** (periodic): Every 5th session or when significant progress detected
5. **Generate briefing** (existing): Session briefing for next session

Uses LLM-driven change detection to avoid unnecessary updates.

### 5.6 Database Service Methods Required

Summary of new methods needed in `TrioDatabaseService`:

```python
# Tier 1: 3 methods
get_patient_profile(), save_patient_profile(), update_patient_profile()
get_patient_profile_history()

# Tier 2: 3 methods
get_recent_sessions(), update_session_tier2(), get_session_count()
enqueue_session_enrichment_job(), claim_next_session_enrichment_job(),
mark_session_enrichment_job_complete(), mark_session_enrichment_job_failed()

# Tier 3: 5 methods
get_latest_patient_analysis(), get_patient_analysis_version(),
get_analysis_history(), save_patient_analysis_version(), mark_analysis_superseded()

# Tier 4: 3 methods
get_current_therapy_plan(), save_therapy_plan()
```

Total: **14 new database methods**

---

## 6. Patient File Update Strategy

### 6.1 Update Patterns by Tier

| Tier | Frequency | Trigger | Update Type | Rationale |
|------|-----------|---------|-------------|-----------|
| **Tier 1** | ~5-10% of sessions | Patient reveals/corrects background info | Selective field updates | Background is mostly static; only update when factual info changes |
| **Tier 2** | 100% of sessions | Session ends | Append-only (immutable after enrichment) | Each session creates new record; never modify existing sessions |
| **Tier 3** | ~30-50% of sessions | Clinical understanding evolves | Versioned (new version created) | Understanding evolves gradually; preserve history with versions |
| **Tier 4** | ~20% of sessions | Every 5th session OR significant progress | In-place update | Progress is cumulative; track current state without full versioning |

### 6.2 LLM-Driven Change Detection

Instead of updating everything automatically, use LLM to determine: **"Did anything change that requires an update?"**

**Advantages:**
- Prevents version bloat (only meaningful changes create versions)
- Creates interpretable change history (change summaries explain what shifted)
- Reduces unnecessary writes and LLM costs
- Maintains signal-to-noise ratio in version history

**Implementation Pattern:**

```python
# Pattern: Conditional Update
current_state = load_current_tier_data()
new_session_data = load_latest_session()

# Ask LLM: "Should we update?"
update_decision = llm.evaluate_update_necessity(current_state, new_session_data)

if update_decision.update_needed:
    updated_state = llm.generate_updated_state(current_state, new_session_data)
    save_new_version(updated_state, change_summary=update_decision.change_summary)
else:
    logger.info("No update needed")
```

### 6.3 Example: Complete Reflection Workflow

After each session, Reflection Agent:

1. ✅ **Tier 2 Enrichment** (always): Add psychological summary, affects, themes
2. ⚠️ **Tier 1 Check** (rare, ~5%): LLM detects new background info → selective field update
3. ⚠️ **Tier 3 Update** (conditional, ~30-50%): LLM evaluates if formulation changed → new version if yes
4. ⚠️ **Tier 4 Update** (periodic, ~20%): Every 5th session or significant progress → update progress field

**Typical Output:**
```
✅ Tier 2: Enriched session sess_abc123
✏️ Tier 3: Created new analysis version (v4): "Central theme shifted from work anxiety to underlying attachment concerns"
Reflection complete. Updates: Tier1=False, Tier2=True, Tier3=True, Tier4=False
```

---

## 7. Testing Strategy

### 7.1 Unit Tests (25+ tests)

**File**: `tests/unit/test_data_models.py`
- Pydantic validation for all Tier 1-4 models
- JSON serialization roundtrip tests
- Field constraint validation (max lengths, patterns, required fields)

**File**: `tests/unit/test_tier_extraction.py`
- Prompt format validation (all required fields present)
- Graceful handling of minimal/incomplete data
- Mock LLM responses validation

### 7.2 Integration Tests (25+ tests)

**File**: `tests/integration/test_intake_tier1_flow.py`
- End-to-end: intake conversation → Tier 1 extracted and saved
- Handles missing data gracefully (nulls for unmentioned fields)
- State transition to INTAKE_COMPLETE

**File**: `tests/integration/test_session_tier2_enrichment.py`
- Session end → Reflection enriches with Tier 2 data
- Session immutability after enrichment (no duplicate enrichment)
- All required Tier 2 fields populated

**File**: `tests/integration/test_tier3_versioning.py`
- Assessment creates initial v1
- Reflection creates v2+ with proper linking (superseded_by)
- No version created when LLM determines no change
- Full analysis evolution queryable

**File**: `tests/integration/test_assessment_tier3_tier4.py`
- Assessment uses Tier 1 for context
- Creates initial Tier 3 v1 and Tier 4
- Treatment plan has valid goals and status

**File**: `tests/integration/test_psychoanalyst_with_context.py`
- Psychoanalyst loads all tiers at session start
- Prompts include patient context
- Context loading <500ms

**File**: `tests/integration/test_full_patient_file_lifecycle.py`
- **Full end-to-end**: Intake → Assessment → 3 Sessions → Reflections
- Verifies all 4 tiers populated correctly
- Multiple Tier 3 versions created appropriately

### 7.3 Performance Tests (5+ tests)

**File**: `tests/performance/test_patient_file_performance.py`
- Profile retrieval <200ms
- Context loading (all tiers) <500ms
- Query performance with 100 analysis versions <100ms (latest), <500ms (full history)
- Session enrichment <30s

### 7.4 Test Coverage Targets

- **Unit Tests**: >95% coverage for data models
- **Integration Tests**: 100% coverage of agent workflows
- **Performance Tests**: All SLAs validated
- **Total Test Count Target**: 50+ new tests

---

## 8. Phased Implementation

### Phase 1: Foundation (Week 1)
**Tasks**: Define Pydantic models, create database schema, add DB service methods, unit tests
**Deliverables**: Updated data_models.py, migration SQL, 25 unit tests

### Phase 2: Tier 1 Extraction (Week 2)
**Tasks**: Modify Intake Agent, create extraction prompt, integration tests
**Deliverables**: Modified trio_intake_agent.py, 5 integration tests

### Phase 3: Tier 2 Session Enrichment (Week 2-3)
**Tasks**: Extend Session model, modify Reflection Agent for enrichment, tests
**Deliverables**: DetailedSession model, enrichment logic, 5 integration tests

### Phase 4: Assessment Creates Tier 3 & 4 (Week 3)
**Tasks**: Modify Assessment Agent, create initial formulation/plan, tests
**Deliverables**: Modified trio_assessment_agent.py, prompts, 5 integration tests

### Phase 5: Tier 3 Versioning (Week 4)
**Tasks**: Implement versioning logic, conditional updates, change detection
**Deliverables**: Tier 3 update logic in Reflection Agent, 10 integration tests

### Phase 6: Psychoanalyst Context Loading (Week 4-5)
**Tasks**: Implement context loading, update prompts with patient file
**Deliverables**: Modified trio_therapist_agent.py, 5 integration tests

### Phase 7: Tier 4 & Tier 1 Updates (Week 5)
**Tasks**: Periodic progress updates, rare background corrections
**Deliverables**: Complete Reflection Agent logic, 8 integration tests

### Phase 8: Integration & Testing (Week 5-6)
**Tasks**: Full lifecycle test, performance testing, documentation
**Deliverables**: Full e2e test, performance tests, updated docs

### Phase 9: Deployment (Week 6)
**Tasks**: Database migration, smoke testing, merge
**Deliverables**: Working system, 126+ total tests passing

---

## 9. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **LLM extraction hallucination** | High | High | Use structured output mode with strict schemas; validate against Pydantic models; manual review of first 10 extractions |
| **JSON size exceeds SQLite limit** | Medium | Medium | Implement max field lengths (validated by Pydantic); test with max-size profiles; use TEXT fields (no hard JSON limit in SQLite) |
| **Versioning breaks with bugs** | Low | Medium | Comprehensive versioning tests; transaction safety; ability to manually fix via database if needed |
| **Performance degradation** | Low | Medium | Index optimization (DESC indexes on version); pagination for history views; archive strategy for very old versions |
| **Update logic too aggressive/conservative** | Medium | Medium | Tune LLM prompts for change detection; A/B test update thresholds; monitor update frequencies |

---

## 10. Future Enhancements

Deferred features that may be added later:

### 10.1 Semantic Session Retrieval (Embeddings)
Generate embeddings for session summaries and themes to find similar past sessions via vector search. Would enhance continuity when themes resurface.

### 10.2 Clinician Review Dashboard
Web UI for reviewing patient file, viewing analysis evolution, comparing versions, manual override for extractions.

### 10.3 Multi-Therapist Support
Support supervision or therapy teams with shared patient access, tracking which therapist conducted each session.

### 10.4 Treatment Plan Templates
Predefined goal templates for common presenting problems (anxiety, depression, etc.) for faster initial plan creation.

---

## Appendices

### A. Example Tier 1 Extraction Prompt

```
Analyze this intake conversation and extract patient background information.

CONVERSATION:
[Full transcript here]

TASK:
Extract the following information into structured format. Use null for any information not mentioned.

1. BASIC INFO:
   - alias: Patient's preferred name/pseudonym
   - date_of_birth: If mentioned (format: YYYY-MM-DD)
   - gender: Gender identity if discussed
   - cultural_background: Cultural, ethnic, or religious background
   - primary_language: Primary language (default: English)

2. FAMILY:
   - parents: Information about parents
   - siblings: Siblings and birth order
   - family_atmosphere: Emotional climate of family
   - significant_events: Major family events

3. EDUCATION & WORK:
   - education: Educational history
   - work_history: Career history
   - relationship_to_work: Psychological relationship to work

4. RELATIONAL CONTEXT:
   - relationships: Romantic relationships, friendships
   - social_context: Social network, isolation
   - current_situation: Current life circumstances

5. ANALYTIC FRAME:
   - preferred_school: Preferred therapeutic approach if mentioned
   - boundary_notes: Special considerations
   - frame_notes: Other notes

Return output matching the `PatientProfileExtract` schema (the system uses Gemini structured output / JSON Schema, so no manual JSON scraping is required).
```

### B. Database Query Examples

**Load Current Patient Context:**
```sql
-- Tier 1
SELECT profile_data FROM patient_profiles WHERE user_id = ?;

-- Tier 2: Recent 5 sessions
SELECT * FROM sessions WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5;

-- Tier 3: Latest analysis
SELECT * FROM patient_analysis WHERE user_id = ? ORDER BY version DESC LIMIT 1;

-- Tier 4: Current plan
SELECT * FROM therapy_plans WHERE user_id = ? AND status = 'active';
```

### C. LLM Call Summary

| Agent | LLM Call | Model | Temp | Tokens | Frequency |
|-------|----------|-------|------|--------|-----------|
| Intake | Tier 1 Extraction | pro | 0.1 | ~2000 | Once/user |
| Assessment | Initial Analysis | pro | 0.3 | ~3000 | Once/user |
| Assessment | Initial Plan | pro | 0.3 | ~1500 | Once/user |
| Psychoanalyst | Session Response | pro | 0.7 | ~6000 | Per message |
| Reflection | Tier 2 Enrichment | flash | 0.2 | ~1500 | Per session |
| Reflection | Tier 3 Evaluation | pro | 0.3 | ~3000 | Per session (conditional) |
| Reflection | Tier 4 Update | flash | 0.3 | ~1500 | Every 5th session |

**Estimated Additional Cost**: ~$0.03-0.07 per session

---

**Document Status**: Draft v1.0
**Last Updated**: 2024-12-14
