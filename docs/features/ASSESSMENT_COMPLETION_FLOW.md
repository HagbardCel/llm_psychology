# Assessment Completion Flow Changes

## Summary

Implemented a new feature where the system suggests finishing for the day after assessment completion, while allowing users to optionally continue immediately to their first therapy session. When users choose to continue, the therapy session is logged as a separate session.

## Changes Made

### 1. Modified Assessment Agent ([src/agents/trio_assessment_agent.py](../../src/agents/trio_assessment_agent.py))

#### Updated `process_selection` Method
- After creating the therapy plan, the system now suggests finishing for the day
- Presents two clear options:
  1. Finish for today and begin therapy in next session
  2. Continue with first therapy session now
- Returns `await_continuation_choice` action to wait for user's decision

#### Added `_parse_continuation_choice` Method
- Parses user's response to determine their choice
- Recognizes various keywords for "finish" (finish, stop, end, done, later, option 1, etc.)
- Recognizes various keywords for "continue" (continue, start, begin, now, yes, option 2, etc.)
- Returns `None` if choice is unclear, prompting for clarification

#### Updated `process_message` Method
- Added logic to detect when waiting for continuation choice
- Handles user's response:
  - **Finish choice**: Provides a warm closing message and ends the session
  - **Continue choice**: Confirms continuation and transitions to therapy
  - **Unclear choice**: Asks for clarification

### 2. Updated Orchestrator ([src/orchestration/trio_agent_orchestrator.py](../../src/orchestration/trio_agent_orchestrator.py))

#### Enhanced `_handle_agent_response` Method
Added handling for new agent actions:

- **`await_continuation_choice`**: Logs that the agent is waiting for user's decision
- **`end_session`**: Logs that user chose to finish for the day (session ends naturally)
- **`start_therapy`**:
  - Creates a new session for the therapy portion
  - Switches WebSocket registration from assessment session to new therapy session
  - Ensures assessment and therapy are logged as separate sessions
  - Logs the transition with clear session IDs

### 3. Session Timer Verification

#### Reviewed Existing Implementation
The session timer functionality was already properly implemented:

- **ConversationContext** ([src/orchestration/models.py](../../src/orchestration/models.py)):
  - `time_elapsed_minutes`: Calculates time since session start
  - `time_remaining_minutes`: Calculates remaining time (includes extensions)
  - `is_time_up`: Checks if session time has expired
  - `can_extend`: Checks if extensions are still available
  - Extensions add 5 minutes each, maximum 2 extensions

- **PsychoanalystAgent** ([src/agents/trio_psychoanalyst_agent.py](../../src/agents/trio_psychoanalyst_agent.py)):
  - Checks `context.is_time_up` to transition to reflection when time expires
  - Offers extensions when ≤5 minutes remaining via `_should_offer_extension`
  - Tracks time in metadata for client-side display

- **IntakeAgent** ([src/agents/trio_intake_agent.py](../../src/agents/trio_intake_agent.py)):
  - Handles time expiration during intake sessions
  - Maintains state properly when time runs out

#### Created Unit Tests
Added comprehensive unit tests ([tests/unit/test_session_timer.py](../../tests/unit/test_session_timer.py)):
- `test_time_elapsed_calculation`: Verifies elapsed time calculation
- `test_time_remaining_calculation`: Verifies remaining time calculation
- `test_is_time_up`: Verifies time expiration detection
- `test_is_time_not_up`: Verifies ongoing session detection
- `test_can_extend`: Verifies extension availability
- `test_extension_adds_time`: Verifies extensions add 5 minutes each
- `test_time_up_with_extensions`: Verifies time calculations with extensions

## User Flow

### Assessment Completion Flow

1. **User completes intake** → State: `INTAKE_COMPLETE`
2. **Assessment agent presents therapy style recommendations**
3. **User selects a therapy style** (e.g., "CBT", "Freud", "Jung")
4. **System creates therapy plan** and transitions to `ASSESSMENT_COMPLETE`
5. **System suggests finishing for the day**:
   ```
   Excellent choice! I'll be using CBT therapy approach for our sessions.

   Your personalized therapy plan has been created. We've covered a lot of
   ground today through our intake and assessment process.

   I'd suggest we finish here for today to give you time to reflect on what
   we've discussed. However, if you'd prefer, we could start our first therapy
   session right now.

   Would you like to:
   1. Finish for today and begin therapy in our next session
   2. Continue with our first therapy session now

   What would you prefer?
   ```

### Option 1: User Chooses to Finish

User responds: "Let's finish for today" (or "1", "finish", "later", etc.)

**System response**:
```
That sounds like a good plan. Take your time to reflect on what we've
discussed today. I look forward to our first therapy session together.
Take care!
```

**Result**:
- Assessment session ends
- State remains: `ASSESSMENT_COMPLETE`
- Next connection will start a therapy session

### Option 2: User Chooses to Continue

User responds: "Let's continue" (or "2", "continue", "now", etc.)

**System response**:
```
Wonderful! Let's begin our first therapy session. I'm here to support you.
```

**Result**:
- Assessment session is completed and saved
- New therapy session is created automatically
- State transitions to: `THERAPY_IN_PROGRESS`
- User can immediately begin therapy conversation
- Both sessions are logged separately in the database

## Session Logging

### Separate Session Recording

When the user continues to therapy:

1. **Assessment Session** (`session_id_1`):
   - Contains: Intake data, therapy style recommendations, style selection
   - Status: Completed
   - Saved to database with all conversation history

2. **Therapy Session** (`session_id_2`):
   - Contains: First therapy session conversation
   - Status: In Progress
   - Logged as a completely separate session
   - WebSocket connection seamlessly switches to new session

### Implementation Details

- New session created in `_handle_agent_response` when action is `"start_therapy"`
- WebSocket registration automatically switches to new session
- Conversation manager tracks both sessions independently
- Client-side code doesn't need changes (transparent session switching)

## Session Timer

### How It Works

The session timer tracks time from session start and manages extensions:

**Base Duration**: 45 minutes (configurable via `SESSION_DURATION_MINUTES`)

**Time Tracking**:
- Session start time recorded when session begins
- Elapsed time calculated continuously
- Remaining time = (base duration + extensions) - elapsed time

**Extensions**:
- Offered when ≤5 minutes remaining
- Each extension adds 5 minutes
- Maximum 2 extensions allowed (total 55 minutes possible)

**Automatic Transitions**:
- When time expires: Therapy sessions transition to reflection
- Metadata includes time remaining for client-side display

### Testing the Timer

Run the session timer tests:
```bash
make test-unit  # Run all unit tests including timer tests
pytest tests/unit/test_session_timer.py -v  # Run timer tests only
```

## Files Modified

1. **[src/agents/trio_assessment_agent.py](../../src/agents/trio_assessment_agent.py)**
   - Added continuation choice logic
   - Modified assessment completion message
   - Added `_parse_continuation_choice` method

2. **[src/orchestration/trio_agent_orchestrator.py](../../src/orchestration/trio_agent_orchestrator.py)**
   - Added handling for `await_continuation_choice` action
   - Added handling for `end_session` action
   - Added session creation and switching for `start_therapy` action

## Files Created

1. **[tests/unit/test_session_timer.py](../../tests/unit/test_session_timer.py)**
   - Comprehensive unit tests for session timer functionality
   - Validates time calculations, extensions, and expiration

## Testing Recommendations

### Manual Testing

1. **Complete Assessment Flow**:
   - Start a new session
   - Complete intake process
   - View therapy style recommendations
   - Select a therapy style
   - Choose to finish for the day
   - Verify warm closing message
   - Start a new session
   - Verify therapy session starts correctly

2. **Continue to Therapy Flow**:
   - Start a new session
   - Complete intake process
   - View therapy style recommendations
   - Select a therapy style
   - Choose to continue with therapy
   - Verify smooth transition
   - Start therapy conversation
   - Check database: verify two separate sessions logged

3. **Session Timer**:
   - Start a therapy session
   - Monitor time remaining (check metadata)
   - Continue until ≤5 minutes remaining
   - Verify extension offer
   - Continue until time expires
   - Verify automatic transition to reflection

### Automated Testing

```bash
# Run all tests
make test-validate

# Run unit tests only
make test-unit

# Run integration tests
make test-integration

# Run specific session timer tests
pytest tests/unit/test_session_timer.py -v
```

## Configuration

Session duration can be configured in `src/config.py`:

```python
SESSION_DURATION_MINUTES: int = Field(default=45)
```

For testing, use shorter duration:
```python
TEST_SESSION_DURATION_MINUTES: int = Field(default=1)
```

## Database Schema

Sessions are stored in the SQLite database with:
- `session_id`: Unique identifier
- `user_id`: Associated user
- `timestamp`: Session start time
- `transcript`: Full conversation history
- `topics`: Discussed topics

When a user continues to therapy after assessment:
- Assessment session is completed and saved
- New therapy session is created with new `session_id`
- Both sessions linked by `user_id` but tracked independently

## Notes

- The session timer functionality was already properly implemented
- Created comprehensive unit tests to verify timer behavior
- All changes follow the existing Trio-based architecture
- No breaking changes to existing API or WebSocket protocol
- Session switching is transparent to the client
