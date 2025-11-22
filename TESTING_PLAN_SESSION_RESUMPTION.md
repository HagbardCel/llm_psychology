# Session Resumption Testing Plan

**Feature**: Contextual therapist greetings for continuing therapy sessions
**Status**: Implementation complete, testing phase
**Date**: 2025-11-16

## Overview

This document outlines a comprehensive testing strategy for the session resumption feature. The implementation includes:

- **Configuration** (src/config.py): Session resumption settings
- **Data Models** (src/models/briefing_models.py): Pydantic validation models
- **Database** (src/services/trio_db_service.py): Session briefing persistence
- **Reflection Agent** (src/agents/trio_reflection_agent.py): Briefing generation
- **Psychoanalyst Agent** (src/agents/trio_psychoanalyst_agent.py): Resumption prompts
- **Server** (src/trio_server.py): WebSocket streaming of greetings

## Testing Strategy

### Phase 1: Unit Tests
Test individual components in isolation with mocked dependencies.

### Phase 2: Integration Tests
Test complete workflows from session → reflection → resumption.

### Phase 3: Manual Testing
End-to-end validation with real LLM responses.

---

## Phase 1: Unit Tests

### 1.1 Briefing Models Validation Tests
**File**: `tests/unit/test_briefing_models.py`

#### Test Cases:

**Test: Valid SessionBriefing Creation**
- Create SessionBriefing with all valid fields
- Verify all fields populated correctly
- Assert no validation errors

**Test: Narrative Length Validation**
- Test narrative_handoff < 50 chars → ValidationError
- Test narrative_handoff > 1500 chars → ValidationError
- Test narrative_handoff = 50 chars → Success
- Test narrative_handoff = 1500 chars → Success

**Test: List Length Validation**
- Test continuity_points with 11 items → ValidationError
- Test continuity_points with 10 items → Success
- Test key_themes with 11 items → ValidationError
- Test progress_highlights with 10 items → Success

**Test: EmotionalSummary Validation**
- Test with valid dominant_emotions list
- Test with invalid dominant_emotions (empty) → ValidationError
- Test breakthrough_moments as optional field

**Test: KeyTheme Validation**
- Test with valid theme and description
- Test with empty theme → ValidationError
- Test with empty description → ValidationError

**Test: RecommendedApproach Validation**
- Test with valid suggested_questions (≤3)
- Test with 4 suggested_questions → ValidationError
- Test with valid session_goals (≤3)

**Test: BriefingStatus Enum**
- Test all enum values (FRESH, STALE, VERY_STALE, INVALID)
- Verify string values correct

---

### 1.2 Database Service Tests
**File**: `tests/unit/test_trio_db_service_briefing.py`

#### Test Cases:

**Test: Save TherapyPlan with session_briefing**
- Create TherapyPlan with valid session_briefing dict
- Call save_therapy_plan()
- Retrieve from database
- Assert session_briefing matches original
- Verify JSON serialization correct in DB

**Test: Save TherapyPlan without session_briefing**
- Create TherapyPlan with session_briefing=None
- Save and retrieve
- Assert session_briefing is None

**Test: Retrieve TherapyPlan with invalid JSON in session_briefing**
- Manually insert row with malformed JSON in session_briefing column
- Call get_latest_therapy_plan()
- Assert returns TherapyPlan with session_briefing=None
- Verify warning logged

**Test: Retrieve TherapyPlan with valid JSON session_briefing**
- Insert valid SessionBriefing JSON
- Retrieve via get_latest_therapy_plan()
- Assert deserialization successful
- Verify all nested fields present

---

### 1.3 Reflection Agent Tests
**File**: `tests/unit/test_trio_reflection_agent_briefing.py`

#### Test Cases:

**Test: _generate_session_briefing with valid LLM response**
- Mock llm_service.generate_response to return valid SessionBriefing JSON
- Call _generate_session_briefing() with sample session data
- Assert returns dict with all required fields
- Verify Pydantic validation passed

**Test: _generate_session_briefing with invalid JSON response**
- Mock LLM to return malformed JSON
- Call _generate_session_briefing()
- Assert raises json.JSONDecodeError (fail-fast)
- Verify no fallback message

**Test: _generate_session_briefing with validation errors**
- Mock LLM to return JSON missing required fields
- Call _generate_session_briefing()
- Assert raises ValidationError (fail-fast)
- Verify error message contains field name

**Test: _generate_session_briefing with field length violations**
- Mock LLM to return narrative_handoff > 1500 chars
- Assert raises ValidationError
- Verify error message mentions length constraint

**Test: process_reflection saves briefing to database**
- Mock _generate_session_briefing to return valid briefing
- Mock db_service.save_therapy_plan
- Call process_reflection()
- Assert save_therapy_plan called with updated TherapyPlan
- Verify updated_plan.session_briefing is set

**Test: process_reflection propagates briefing generation errors**
- Mock _generate_session_briefing to raise ValidationError
- Call process_reflection()
- Assert ValidationError propagates (fail-fast)
- Verify save_therapy_plan NOT called

---

### 1.4 Psychoanalyst Agent Tests
**File**: `tests/unit/test_trio_psychoanalyst_agent_resumption.py`

#### Test Cases:

**Test: get_briefing_status with FRESH briefing**
- Create briefing with generated_at = 10 days ago
- Call get_briefing_status()
- Assert returns BriefingStatus.FRESH

**Test: get_briefing_status with STALE briefing**
- Create briefing with generated_at = 60 days ago
- Assert returns BriefingStatus.STALE

**Test: get_briefing_status with VERY_STALE briefing**
- Create briefing with generated_at = 100 days ago
- Assert returns BriefingStatus.VERY_STALE

**Test: get_briefing_status boundary cases**
- Test at exactly BRIEFING_VALIDITY_DAYS (30) → FRESH
- Test at BRIEFING_VALIDITY_DAYS + 1 (31) → STALE
- Test at exactly STALE_BRIEFING_DAYS (90) → STALE
- Test at STALE_BRIEFING_DAYS + 1 (91) → VERY_STALE

**Test: _build_resumption_prompt with FRESH briefing**
- Create valid briefing + user_profile + therapy_plan
- Mock llm_service.generate_response
- Call _build_resumption_prompt() with FRESH status
- Assert prompt includes narrative_handoff
- Assert prompt includes patient_observations
- Assert prompt includes continuity_points
- Assert prompt does NOT mention time gap

**Test: _build_resumption_prompt with STALE briefing**
- Create briefing 60 days old
- Call _build_resumption_prompt() with STALE status
- Assert prompt mentions time gap
- Assert prompt includes "60 days since last session"

**Test: _build_initial_session_prompt uses resumption for FRESH**
- Create TherapyPlan with FRESH session_briefing
- Mock _build_resumption_prompt
- Call _build_initial_session_prompt()
- Assert _build_resumption_prompt called
- Assert standard prompt NOT used

**Test: _build_initial_session_prompt uses resumption for STALE**
- Create TherapyPlan with STALE session_briefing
- Mock _build_resumption_prompt
- Call _build_initial_session_prompt()
- Assert _build_resumption_prompt called

**Test: _build_initial_session_prompt falls back for VERY_STALE**
- Create TherapyPlan with VERY_STALE session_briefing
- Call _build_initial_session_prompt()
- Assert returns standard prompt
- Assert _build_resumption_prompt NOT called

**Test: _build_initial_session_prompt falls back when no briefing**
- Create TherapyPlan with session_briefing=None
- Call _build_initial_session_prompt()
- Assert returns standard prompt

**Test: _build_resumption_prompt includes all briefing components**
- Create comprehensive SessionBriefing with all fields
- Call _build_resumption_prompt()
- Mock LLM call and capture prompt
- Assert prompt includes:
  - narrative_handoff
  - patient_observations
  - plan_progression_notes
  - continuity_points
  - emotional_summary.dominant_emotions
  - key_themes
  - progress_highlights
  - unresolved_issues
  - recommended_approach.suggested_questions

---

### 1.5 Server Logic Tests
**File**: `tests/unit/test_trio_server_resumption.py`

#### Test Cases:

**Test: Session request for PLAN_COMPLETE state triggers resumption**
- Mock orchestrator.get_or_create_workflow_state() → PLAN_COMPLETE
- Mock orchestrator.process_message() to yield chunks
- Call session request handler
- Assert orchestrator.process_message() called with empty message
- Verify WebSocket receives chat_response_chunk messages
- Verify final message has is_complete=True

**Test: Session request for NEW state uses simple welcome**
- Mock state → NEW
- Call session request handler
- Assert simple welcome message sent
- Assert orchestrator.process_message() NOT called

**Test: Session request for IN_SESSION state has no initial message**
- Mock state → IN_SESSION
- Call session request handler
- Assert no initial message sent
- Assert ready for user input

**Test: Resumption greeting streaming**
- Mock orchestrator.process_message() to yield ["Hello ", "there ", "friend"]
- Call session request handler for PLAN_COMPLETE
- Collect all WebSocket messages
- Assert 4 messages total (3 chunks + 1 completion)
- Verify chunks in order
- Verify last message has is_complete=True

---

## Phase 2: Integration Tests

### 2.1 Full Session Resumption Flow
**File**: `tests/integration/test_session_resumption_flow.py`

#### Test Cases:

**Test: Complete flow - Session → Reflection → Briefing → Resumption**

**Setup:**
1. Create user with PLAN_COMPLETE status
2. Create existing TherapyPlan (no briefing yet)

**Flow:**
1. Simulate therapy session with sample messages
2. End session
3. Call ReflectionAgent.process_reflection()
4. Assert TherapyPlan saved with session_briefing
5. Retrieve TherapyPlan from database
6. Assert session_briefing deserialized correctly
7. Create new session for same user
8. Call PsychoanalystAgent._build_initial_session_prompt()
9. Assert resumption prompt generated (not standard prompt)
10. Verify prompt references previous session content

**Assertions:**
- SessionBriefing generated with valid structure
- All required fields present
- Narrative length within bounds
- Briefing saved to database
- Briefing retrieved correctly
- Resumption prompt includes briefing content

---

**Test: Multiple sessions build on previous briefings**

**Setup:**
1. User completes Session 1
2. Generate briefing 1
3. User completes Session 2
4. Generate briefing 2 (overwrites briefing 1)

**Flow:**
1. Session 1 → Reflection → Briefing 1
2. Verify Briefing 1 has session_count=1
3. Session 2 → Reflection → Briefing 2
4. Verify Briefing 2 has session_count=2
5. Verify Briefing 2.last_session_id = Session 2 ID
6. Session 3 start → Uses Briefing 2 for resumption

**Assertions:**
- Each briefing references correct session
- Briefings overwrite previous ones (latest only)
- Resumption always uses latest briefing

---

**Test: Briefing age affects resumption prompt**

**Flow:**
1. Generate briefing with generated_at = 20 days ago
2. Call get_briefing_status() → FRESH
3. Build resumption prompt
4. Assert no time gap mention
5. Modify briefing: generated_at = 60 days ago
6. Call get_briefing_status() → STALE
7. Build resumption prompt
8. Assert time gap mentioned

---

**Test: No briefing falls back gracefully**

**Flow:**
1. Create TherapyPlan with session_briefing=None
2. Call _build_initial_session_prompt()
3. Assert returns standard INITIAL_SESSION_PROMPT
4. Verify no errors raised

---

### 2.2 WebSocket Streaming Integration
**File**: `tests/integration/test_trio_websocket_resumption.py`

#### Test Cases:

**Test: Resumption greeting streams via WebSocket**

**Setup:**
1. Start Trio server
2. Connect WebSocket client
3. Create user with PLAN_COMPLETE + briefing

**Flow:**
1. Send session_request message
2. Collect all incoming messages
3. Assert first messages are chat_response_chunk
4. Assert chunks arrive incrementally (not all at once)
5. Assert final message has is_complete=True
6. Concatenate all chunks
7. Verify full greeting is coherent

**Assertions:**
- Streaming works (multiple chunks)
- Chunks arrive in order
- Completion marker sent
- Full greeting references briefing content

---

**Test: Error in resumption propagates to WebSocket**

**Setup:**
1. Mock LLM to raise exception during resumption prompt generation

**Flow:**
1. Send session_request for PLAN_COMPLETE user
2. Assert WebSocket receives error message
3. Verify error contains stack trace (fail-fast)
4. Verify no partial greeting sent

---

### 2.3 Database Persistence Integration
**File**: `tests/integration/test_briefing_persistence.py`

#### Test Cases:

**Test: Briefing survives database round-trip**

**Flow:**
1. Create SessionBriefing with all fields populated
2. Create TherapyPlan with briefing
3. Save to database
4. Close database connection
5. Reopen database connection
6. Retrieve TherapyPlan
7. Assert session_briefing matches original
8. Validate all nested structures intact

**Assertions:**
- JSON serialization preserves data
- Deserialization reconstructs objects
- No data loss in round-trip

---

**Test: Database migration adds column to existing tables**

**Setup:**
1. Create fresh database without migration
2. Insert TherapyPlan (old schema, no session_briefing column)

**Flow:**
1. Run migration script
2. Verify session_briefing column added
3. Insert new TherapyPlan with session_briefing
4. Retrieve old plan → session_briefing=None
5. Retrieve new plan → session_briefing populated

---

## Phase 3: Edge Cases and Error Handling

### 3.1 Error Handling Tests
**File**: `tests/unit/test_resumption_error_handling.py`

#### Test Cases:

**Test: LLM returns empty response for briefing**
- Mock LLM to return empty string
- Call _generate_session_briefing()
- Assert raises json.JSONDecodeError
- Verify fail-fast (no fallback)

**Test: LLM returns partial JSON for briefing**
- Mock LLM to return truncated JSON
- Call _generate_session_briefing()
- Assert raises json.JSONDecodeError

**Test: LLM returns JSON with wrong schema**
- Mock LLM to return valid JSON but missing required fields
- Call _generate_session_briefing()
- Assert raises ValidationError
- Verify error message identifies missing field

**Test: Database write fails during briefing save**
- Mock db_service.save_therapy_plan to raise exception
- Call process_reflection()
- Assert exception propagates
- Verify no silent failure

**Test: Database returns corrupted JSON**
- Insert row with invalid JSON in session_briefing
- Call get_latest_therapy_plan()
- Assert returns plan with session_briefing=None
- Verify warning logged (not error)

---

### 3.2 Edge Cases
**File**: `tests/integration/test_resumption_edge_cases.py`

#### Test Cases:

**Test: Very first session (no previous sessions)**
- User has PLAN_COMPLETE status
- TherapyPlan exists but session_briefing=None
- Call _build_initial_session_prompt()
- Assert standard prompt used
- Verify no errors

**Test: Briefing exactly at 30-day boundary**
- Create briefing with generated_at = exactly 30 days ago
- Call get_briefing_status()
- Assert returns FRESH (not STALE)

**Test: Briefing exactly at 90-day boundary**
- Create briefing with generated_at = exactly 90 days ago
- Call get_briefing_status()
- Assert returns STALE (not VERY_STALE)

**Test: Briefing with minimal content (all lists empty)**
- Create SessionBriefing with:
  - continuity_points = []
  - progress_highlights = []
  - unresolved_issues = []
- Call _build_resumption_prompt()
- Assert prompt still generated
- Verify no crashes with empty lists

**Test: Briefing with maximum content (all lists at max length)**
- Create SessionBriefing with:
  - continuity_points = 10 items
  - key_themes = 10 items
  - progress_highlights = 10 items
- Assert validation passes
- Call _build_resumption_prompt()
- Verify prompt includes all items

**Test: User switches therapy styles between sessions**
- Session 1: selected_therapy_style = "freud"
- Generate briefing
- Update TherapyPlan: selected_therapy_style = "jung"
- Call _build_resumption_prompt()
- Assert prompt uses Jung style
- Verify briefing still references Freud session (historical)

**Test: Multiple concurrent sessions for same user**
- Start Session A
- Start Session B (same user)
- Complete Session A → generates Briefing A
- Complete Session B → generates Briefing B
- Assert only Briefing B persists (latest wins)

---

## Phase 4: Manual Testing

### 4.1 End-to-End Manual Test Scenarios

#### Scenario 1: Happy Path - Returning User
**Steps:**
1. Start application with existing user (PLAN_COMPLETE)
2. Connect via WebSocket
3. Send session_request
4. Observe incoming greeting
5. Verify greeting:
   - References previous session content
   - Mentions specific themes discussed
   - Feels personal and contextual
6. Continue conversation
7. End session
8. Verify new briefing generated
9. Disconnect and reconnect
10. Verify next resumption uses new briefing

**Success Criteria:**
- Greeting streams chunk-by-chunk
- Content is relevant to previous session
- Tone matches therapy style
- No generic "welcome back" message

---

#### Scenario 2: Stale Briefing (60 days)
**Steps:**
1. Manually set briefing generated_at to 60 days ago
2. Start session
3. Observe greeting
4. Verify greeting acknowledges time gap
5. Verify greeting still references previous content

**Success Criteria:**
- Time gap mentioned naturally
- Previous context still present
- Encouraging tone about returning

---

#### Scenario 3: Very Stale Briefing (100+ days)
**Steps:**
1. Set briefing generated_at to 100 days ago
2. Start session
3. Observe greeting
4. Verify falls back to standard welcome

**Success Criteria:**
- Standard prompt used
- No confusing old references
- Fresh start implied

---

#### Scenario 4: First Session After Assessment
**Steps:**
1. Create new user
2. Complete intake → assessment → plan
3. Start first therapy session
4. Verify NO resumption greeting (standard welcome)
5. Complete session
6. Verify briefing generated
7. Start second session
8. Verify resumption greeting now present

**Success Criteria:**
- First session uses standard prompt
- Briefing created after first session
- Second session uses resumption

---

#### Scenario 5: Error During Briefing Generation
**Steps:**
1. Complete therapy session
2. Trigger LLM error during reflection (e.g., API rate limit)
3. Observe error handling
4. Verify stack trace visible
5. Verify no partial briefing saved
6. Retry reflection
7. Verify briefing generated successfully

**Success Criteria:**
- Clear error message with stack trace
- No silent failure
- No corrupted data in database
- Retry succeeds

---

#### Scenario 6: Long Therapy Relationship (10+ sessions)
**Steps:**
1. Simulate 10 consecutive sessions
2. After each session, verify briefing generated
3. On 11th session start
4. Verify resumption prompt includes:
   - High session count (e.g., "session #11")
   - Deep relationship quality
   - Long-term themes

**Success Criteria:**
- Briefing reflects long-term relationship
- Prompt acknowledges ongoing therapy
- Content shows progression over time

---

### 4.2 Performance Observations

**Manual Performance Checklist:**
- [ ] Briefing generation completes within 10 seconds
- [ ] Resumption greeting starts streaming within 2 seconds
- [ ] Full greeting delivered within 5 seconds
- [ ] Database save operations < 100ms
- [ ] No blocking on main event loop
- [ ] WebSocket remains responsive during generation

**Notes:**
- Record actual timings during manual testing
- If performance issues found, investigate specific bottlenecks
- No formal SLAs, but user experience should feel responsive

---

## Test Execution Plan

### Order of Execution:

1. **Unit Tests First** (fastest feedback)
   - Run: `pytest tests/unit/test_briefing_models.py -v`
   - Run: `pytest tests/unit/test_trio_db_service_briefing.py -v`
   - Run: `pytest tests/unit/test_trio_reflection_agent_briefing.py -v`
   - Run: `pytest tests/unit/test_trio_psychoanalyst_agent_resumption.py -v`
   - Run: `pytest tests/unit/test_trio_server_resumption.py -v`
   - Run: `pytest tests/unit/test_resumption_error_handling.py -v`

2. **Integration Tests** (slower, more comprehensive)
   - Run: `pytest tests/integration/test_session_resumption_flow.py -v`
   - Run: `pytest tests/integration/test_trio_websocket_resumption.py -v`
   - Run: `pytest tests/integration/test_briefing_persistence.py -v`
   - Run: `pytest tests/integration/test_resumption_edge_cases.py -v`

3. **Full Suite**
   - Run: `make test` (all tests)
   - Run: `make test-validate` (isolated Docker)

4. **Manual Testing**
   - Follow scenarios 1-6
   - Record observations
   - Document any issues

---

## Success Criteria

### Code Coverage:
- [ ] Unit tests cover >90% of new code
- [ ] All new methods have dedicated tests
- [ ] All error paths tested

### Functionality:
- [ ] Briefing generation produces valid JSON
- [ ] Pydantic validation catches all schema violations
- [ ] Database persistence works correctly
- [ ] Resumption prompts include briefing content
- [ ] WebSocket streaming delivers chunks correctly
- [ ] Error handling follows fail-fast principle

### Edge Cases:
- [ ] Boundary conditions tested (30/90 day limits)
- [ ] Empty/minimal briefings handled
- [ ] Maximum content lengths validated
- [ ] Missing briefings fall back gracefully

### Integration:
- [ ] Full flow works end-to-end
- [ ] Multiple sessions build on each other
- [ ] Concurrent operations don't corrupt data
- [ ] Database migrations work on existing DBs

### Manual Validation:
- [ ] Greetings feel natural and contextual
- [ ] Time gaps acknowledged appropriately
- [ ] Performance is acceptable
- [ ] No user-facing errors in happy path

---

## Notes

- **Fail-Fast**: All tests should verify that errors propagate (no silent failures)
- **Trio Patterns**: Tests must use pytest-trio for async code
- **Mocking**: Use mocks to isolate components and avoid LLM API calls in tests
- **Real LLM**: Manual testing should use real LLM to verify prompt quality
- **Database**: Integration tests should use separate test database
- **Fixtures**: Reuse existing fixtures from conftest.py where possible

---

## Risk Areas

**High Risk:**
- LLM response validation (invalid JSON, wrong schema)
- Database JSON serialization/deserialization
- Date calculations for briefing age
- WebSocket streaming error propagation

**Medium Risk:**
- Pydantic model validators
- Edge cases with empty briefings
- Concurrent session handling

**Low Risk:**
- Configuration loading
- Enum value handling
- Standard prompt fallback

Prioritize testing high-risk areas first.
