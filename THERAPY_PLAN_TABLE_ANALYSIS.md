# Therapy Plans Table Analysis

## Table Structure

```sql
CREATE TABLE therapy_plans (
    plan_id TEXT PRIMARY KEY,              -- Unique UUID for each plan
    user_id TEXT NOT NULL,                 -- Foreign key to user
    created_at TEXT NOT NULL,              -- ISO timestamp of first creation
    updated_at TEXT NOT NULL,              -- ISO timestamp of last update
    plan_details TEXT NOT NULL,            -- JSON object with plan content
    version INTEGER NOT NULL,              -- Plan version number (1, 2, 3...)
    selected_therapy_style TEXT,           -- "freud", "jung", "cbt"
    session_briefing TEXT                  -- JSON for session resumption
)
```

## Key Characteristics

### 1. **One-to-Many Relationship**
- One user can have MULTIPLE plans
- Each plan has a unique `plan_id` (UUID)
- Plans are **versioned** (version 1, 2, 3...)

### 2. **When Plans Are Created**

#### **Initial Plan Creation** (Version 1)
**Trigger**: User selects therapy style after assessment
**Creator**: `TrioPlanningAgent.create_initial_plan()`
**Location**: [trio_planning_agent.py:174-182](src/agents/trio_planning_agent.py#L174-L182)

```python
therapy_plan = TherapyPlan(
    plan_id=str(uuid.uuid4()),           # New UUID
    user_id=user_id,
    created_at=datetime.now(),
    updated_at=datetime.now(),
    plan_details={...},                  # LLM-generated plan
    version=1,                           # First version
    selected_therapy_style="freud"       # User's choice
)
```

#### **Updated Plans** (Version 2, 3, ...)
**Trigger**: After each therapy session completes
**Creator**: `TrioPlanningAgent.update_plan()`
**Location**: [trio_planning_agent.py:259-267](src/agents/trio_planning_agent.py#L259-L267)

```python
updated_plan = TherapyPlan(
    plan_id=str(uuid.uuid4()),           # NEW UUID (different from v1!)
    user_id=user_id,
    created_at=current_plan.created_at,  # Original creation date
    updated_at=datetime.now(),           # Now
    plan_details={...},                  # Updated content
    version=current_plan.version + 1,    # Increment version
    selected_therapy_style=current_plan.selected_therapy_style  # Unchanged
)
```

### 3. **Plan Retrieval**

The system uses `get_latest_therapy_plan(user_id)` which:
```sql
SELECT * FROM therapy_plans
WHERE user_id = ?
ORDER BY updated_at DESC
LIMIT 1
```

This returns the **most recent plan** for the user.

## Example: User Journey with Multiple Plans

```
User: john_doe

Plan 1 (Initial - after assessment):
├─ plan_id: a1b2c3d4-...
├─ user_id: john_doe
├─ version: 1
├─ selected_therapy_style: "freud"
├─ plan_details: {focus: "anxiety", goals: [...], ...}
├─ created_at: 2025-12-01 10:00:00
└─ updated_at: 2025-12-01 10:00:00

... User completes therapy session 1 ...

Plan 2 (After session 1 reflection):
├─ plan_id: e5f6g7h8-...  (NEW UUID)
├─ user_id: john_doe
├─ version: 2
├─ selected_therapy_style: "freud"  (SAME)
├─ plan_details: {focus: "anxiety + work stress", ...}
├─ created_at: 2025-12-01 10:00:00  (ORIGINAL)
└─ updated_at: 2025-12-01 11:30:00  (NEW)

... User completes therapy session 2 ...

Plan 3 (After session 2 reflection):
├─ plan_id: i9j0k1l2-...  (ANOTHER NEW UUID)
├─ user_id: john_doe
├─ version: 3
├─ selected_therapy_style: "freud"  (STILL SAME)
├─ plan_details: {focus: "work stress + relationships", ...}
├─ created_at: 2025-12-01 10:00:00  (ORIGINAL)
└─ updated_at: 2025-12-01 13:00:00  (NEW)
```

**Database State:**
```
therapy_plans table:
- 3 rows for user "john_doe"
- plan_id values: a1b2c3d4, e5f6g7h8, i9j0k1l2
- versions: 1, 2, 3
- selected_therapy_style: all "freud"
```

## Duplication Question: Will Option A Cause Duplicates?

### Scenario: HTTP Endpoint Creates Minimal Plan

If `POST /api/therapy/plan` creates:
```python
# HTTP endpoint creates this:
plan = TherapyPlan(
    plan_id=str(uuid.uuid4()),      # UUID-1
    user_id=user_id,
    version=1,
    selected_therapy_style="freud",
    plan_details={},                # EMPTY - no LLM call yet
    created_at=datetime.now(),
    updated_at=datetime.now()
)
```

And later PlanningAgent creates:
```python
# PlanningAgent creates this:
plan = TherapyPlan(
    plan_id=str(uuid.uuid4()),      # UUID-2 (DIFFERENT)
    user_id=user_id,
    version=1,                      # ALSO version 1!
    selected_therapy_style="freud",
    plan_details={...},             # FULL LLM-generated content
    created_at=datetime.now(),
    updated_at=datetime.now()
)
```

**Result:**
- ✅ **No duplicate error** (different plan_ids, no UNIQUE constraint violation)
- ⚠️ **But LOGICAL duplication** - two version=1 plans for same user
- ⚠️ **Incorrect behavior** - HTTP plan becomes orphaned
- ❌ **`get_latest_therapy_plan()` returns wrong plan** (whichever has latest `updated_at`)

## Solution: HTTP Endpoint Should NOT Create Full Plan

### ✅ **Correct Approach: Minimal State Update**

The HTTP endpoint should:
1. Validate therapy_style
2. Update user status to PLAN_COMPLETE
3. **NOT create TherapyPlan object**

The actual TherapyPlan creation happens later when:
- User starts first WebSocket session
- AssessmentAgent → ReflectionAgent → PlanningAgent creates full plan with LLM

### Why This Works

```
Frontend Flow:
1. User fills intake form → POST /api/user/profile
   └─ Creates UserProfile (status: PROFILE_ONLY)

2. User selects therapy style → POST /api/therapy/plan
   └─ Updates UserProfile (status: PLAN_COMPLETE)
   └─ Does NOT create TherapyPlan yet

3. User starts session → WebSocket /ws
   └─ AssessmentAgent creates full TherapyPlan (version 1)
   └─ Includes LLM-generated plan_details
```

This prevents duplication because only ONE component creates TherapyPlan objects.

## Revised Recommendation

**POST /api/therapy/plan should:**
```python
async def _create_therapy_plan(self):
    data = await request.get_json()
    user_id = data.get("user_id")
    therapy_style = data.get("therapy_style")

    # Validate style
    style_service = self.container.get("style_service")
    if therapy_style not in style_service.get_available_styles():
        return jsonify({"error": f"Invalid therapy style: {therapy_style}"}), 400

    # Get profile
    profile = await self.db_service.get_user_profile(user_id)
    if not profile:
        return jsonify({"error": "User profile not found"}), 404

    # Update status to PLAN_COMPLETE
    # The style selection is stored transiently for the AssessmentAgent
    profile.status = UserStatus.PLAN_COMPLETE
    profile.updated_at = datetime.now()
    await self.db_service.save_user_profile(profile)

    # Return updated profile (NO TherapyPlan created here)
    return jsonify(profile.to_dict()), 201
```

**But wait - how does AssessmentAgent know which style the user selected?**

The user selection happens in the WebSocket flow:
1. Frontend navigates to therapy session
2. Opens WebSocket connection
3. AssessmentAgent asks "Which style?" (already has recommendations)
4. User responds "freud" via WebSocket
5. AssessmentAgent creates TherapyPlan with selected style

**So the HTTP endpoint is redundant in the WebSocket flow!**

## Architecture Mismatch Discovery

The frontend has TWO ways to select therapy style:

### Path A: WebSocket (Original Design)
```
IntakePage (WebSocket)
  → IntakeAgent collects info
  → AssessmentAgent recommends styles
  → User types "freud"
  → AssessmentAgent creates TherapyPlan
```

### Path B: HTTP REST (Frontend Implementation)
```
IntakePage (HTTP form)
  → POST /api/user/profile
AssessmentPage (HTTP)
  → Displays hardcoded styles
  → User clicks button
  → POST /api/therapy/plan
  → Need to create something?
```

**The frontend bypasses the WebSocket Assessment flow entirely!**

## Final Answer: Yes, Store in TherapyPlan, But...

**Option A is correct, but implementation must be:**

```python
async def _create_therapy_plan(self):
    """Create therapy plan when user selects style via HTTP (not WebSocket)."""
    data = await request.get_json()
    user_id = data.get("user_id")
    therapy_style = data.get("therapy_style")

    # Validate
    style_service = self.container.get("style_service")
    if therapy_style not in style_service.get_available_styles():
        return jsonify({"error": f"Invalid therapy style"}), 400

    profile = await self.db_service.get_user_profile(user_id)
    if not profile:
        return jsonify({"error": "User profile not found"}), 404

    # Create minimal TherapyPlan (version 1)
    # The PlanningAgent will create detailed plans LATER during sessions
    plan = TherapyPlan(
        plan_id=str(uuid.uuid4()),
        user_id=user_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        plan_details={
            "focus": "To be determined in first session",
            "goals": [],
            "techniques": [],
            "themes": []
        },
        version=1,
        selected_therapy_style=therapy_style
    )

    await self.db_service.save_therapy_plan(plan)

    # Update user status
    profile.status = UserStatus.PLAN_COMPLETE
    profile.updated_at = datetime.now()
    await self.db_service.save_user_profile(profile)

    return jsonify(profile.to_dict()), 201
```

**This ensures:**
- ✅ Only ONE version=1 plan per user
- ✅ Frontend and WebSocket paths both work
- ✅ `selected_therapy_style` is stored correctly
- ✅ No duplicates (same user won't create another v1 plan)
- ✅ PlanningAgent updates create v2, v3, etc.
