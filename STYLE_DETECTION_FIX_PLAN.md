# Assessment Agent Style Detection Fix Plan

## Problem Summary

**Issue**: Test fails because assessment agent doesn't recognize "I'd like to try CBT." as a valid style selection.

**Root Cause**: The agent's selection detection logic is **too restrictive**. It requires:
1. ✅ `awaiting_selection` flag in metadata (works)
2. ❌ **Exact phrase** "Which approach resonates most with you?" in last assistant message (fails)

## Detailed Analysis

### The Bug

**Location**: [src/agents/trio_assessment_agent.py:93-99](src/agents/trio_assessment_agent.py#L93-L99)

```python
if (
    context.metadata.get("awaiting_selection")
    and "Which approach resonates most with you?" in last_assistant_msg
):
    # User is responding to recommendations
    selected_style = await self._parse_selection(message)
```

### Why It Fails

**Scenario 1**: User sends "I'm ready for recommendations."
- Agent can't parse a style from this
- Returns clarification: "I'm not sure which therapy style you'd like..."
- Sets `awaiting_selection=True` in metadata ✅
- BUT clarification message doesn't contain "Which approach resonates most with you?" ❌

**Scenario 2**: User then sends "I'd like to try CBT."
- Check fails because last_assistant_msg is the clarification text
- Agent thinks we're NOT in selection mode
- Calls `process_assessment()` instead of `process_selection()`
- User gets stuck in `ASSESSMENT_IN_PROGRESS` state

### Evidence from Test Output

```
DEBUG: _parse_selection message="i'm ready for recommendations." styles=['cbt', 'freud', 'jung']
DEBUG: No style found  ← Correctly returns None
DEBUG: Agent response: action=await_selection state=WorkflowState.ASSESSMENT_IN_PROGRESS direct=None
DEBUG: Mock LLM Prompt: "i understood you want to proceed, but i'm not sure which therapy style..."  ← Clarification sent

# User sends "I'd like to try CBT."
DEBUG: _parse_selection message="i'd like to try cbt." styles=['cbt', 'freud', 'jung']
DEBUG: No style found  ← WRONG! This shouldn't be called
DEBUG: Agent response: action=await_selection state=WorkflowState.ASSESSMENT_IN_PROGRESS direct=True  ← Still waiting
```

**The bug**: After clarification, the second "I'd like to try CBT." message should call `process_selection()`, but the string check fails so it doesn't.

---

## Proposed Solutions

### Solution 1: Remove the String Check (RECOMMENDED)

**Estimated Time**: 15 minutes
**Risk**: Very low
**Effectiveness**: Fixes root cause

**Implementation**:

```python
# In src/agents/trio_assessment_agent.py

# OLD (buggy):
if (
    context.metadata.get("awaiting_selection")
    and "Which approach resonates most with you?" in last_assistant_msg
):
    selected_style = await self._parse_selection(message)

# NEW (fixed):
if context.metadata.get("awaiting_selection"):
    selected_style = await self._parse_selection(message)
    if selected_style:
        return await self.process_selection(selected_style, context)
```

**Rationale**:
- The `awaiting_selection` flag is the authoritative signal
- String matching is fragile (fails with clarifications, different phrasings)
- The flag is set correctly by both recommendation and clarification responses
- Simple, reliable, matches intent

**Pros**:
- ✅ Fixes the immediate issue
- ✅ More robust (works with any clarification text)
- ✅ Simpler code (one condition instead of two)
- ✅ Matches the design intent (flag-based state management)

**Cons**:
- ⚠️ Might parse selection earlier than intended in some edge cases
- (But `_parse_selection()` will just return None if no style found)

---

### Solution 2: Fix the String Check Pattern

**Estimated Time**: 30 minutes
**Risk**: Medium
**Effectiveness**: Maintains current logic

**Implementation**:

```python
# Check for multiple possible phrases
selection_indicators = [
    "Which approach resonates most with you?",
    "which therapy style you'd like",  # From clarification
    "specify one of the recommended approaches",  # From clarification
]

if context.metadata.get("awaiting_selection"):
    # Check if any indicator phrase is present
    is_selection_context = any(
        indicator.lower() in last_assistant_msg.lower()
        for indicator in selection_indicators
    )

    if is_selection_context:
        selected_style = await self._parse_selection(message)
        if selected_style:
            return await self.process_selection(selected_style, context)
```

**Pros**:
- ✅ Maintains double-checking logic
- ✅ Handles clarification messages

**Cons**:
- ❌ Still fragile (what if LLM changes wording?)
- ❌ More complex
- ❌ Doesn't address root issue (why have redundant check?)

---

### Solution 3: Add Selection Mode State

**Estimated Time**: 1 hour
**Risk**: High
**Effectiveness**: Most robust long-term

**Implementation**:

```python
# Add explicit selection_mode to conversation context
if context.metadata.get("selection_mode") == "awaiting_style":
    selected_style = await self._parse_selection(message)
    if selected_style:
        return await self.process_selection(selected_style, context)
```

**Changes Required**:
1. Add `selection_mode` field to metadata when returning recommendations
2. Preserve `selection_mode` across messages until selection made
3. Clear `selection_mode` after successful selection

**Pros**:
- ✅ Explicit state machine
- ✅ No fragile string matching
- ✅ Easy to debug (clear state)

**Cons**:
- ❌ Requires metadata changes across multiple calls
- ❌ Higher implementation time
- ❌ Overkill for this issue

---

## Recommended Implementation

**Choose Solution 1** - Remove the string check.

### Reasoning

1. **The `awaiting_selection` flag IS the authoritative state**
   - It's explicitly set when we want the user to select
   - It's part of the agent's response metadata
   - It's designed for this exact purpose

2. **String matching is an anti-pattern here**
   - Fragile (breaks with any wording change)
   - Redundant (flag already tracks state)
   - Causes the exact bug we're seeing

3. **Edge case handling is natural**
   - If user sends random text when `awaiting_selection=True`, `_parse_selection()` returns None
   - We send clarification and keep `awaiting_selection=True`
   - User tries again until style recognized
   - No harm done

### Implementation Steps

1. **Modify assessment agent** (5 min)
   - Remove string check condition
   - Keep flag-based check only

2. **Run tests** (5 min)
   - Verify test passes with mocks
   - Verify behavior is correct

3. **Test real LLM** (5 min)
   - Run with `--no-mocks`
   - Verify CBT selection works
   - Verify plan creation completes

---

## Alternative: Quick Test Fix (If Production Code Can't Change)

If we **can't modify production code**, we can fix the test instead:

**Option A**: Update test message to include magic phrase
```python
# Instead of:
"I'm ready for recommendations."

# Send:
"Which approach resonates most with you? I'd like to try CBT."
```

**Option B**: Skip the intermediate message
```python
# Remove:
await ws.send_message({"message": "I'm ready for recommendations."})

# Just send:
await ws.send_message({"message": "I'd like to try CBT."})
```

**Not Recommended**: These are workarounds that hide the underlying bug.

---

## Testing Plan

### Test 1: Mock Test with Fix
```bash
pytest tests/integration/test_natural_patient_flow.py::test_natural_patient_flow -v
```

**Expected**:
- ✅ "I'm ready for recommendations." → Agent provides recommendations or clarification
- ✅ "I'd like to try CBT." → Agent recognizes CBT, calls `process_selection()`
- ✅ State transitions to `ASSESSMENT_COMPLETE`
- ✅ Test passes

### Test 2: Real LLM with Fix
```bash
pytest tests/integration/test_natural_patient_flow.py::test_natural_patient_flow --no-mocks -v
```

**Expected**:
- ✅ Same behavior as mocks but with real LLM responses
- ✅ Plan creation completes (takes ~60s with shielding)
- ✅ Test passes

### Test 3: Edge Cases
Manually test:
- User says "maybe" when awaiting selection → Should clarify
- User says "I choose Freud" → Should work
- User says "psychodynamic" → Should work (matches "freud" directory)
- User says "random text" → Should ask for clarification again

---

## Additional Improvements (Optional)

### Improve `_parse_selection()` Robustness

```python
async def _parse_selection(self, message: str) -> str | None:
    """Parse user message to identify selected therapy style."""
    message = message.lower()
    available_styles = style_service.get_available_styles()

    # Enhanced matching with synonyms/variations
    style_patterns = {
        "cbt": ["cbt", "cognitive", "behavioral", "cognitive-behavioral"],
        "freud": ["freud", "freudian", "psychoanalysis", "psychoanalytic", "psychodynamic"],
        "jung": ["jung", "jungian", "analytical psychology"],
    }

    for style, patterns in style_patterns.items():
        if style in available_styles:
            for pattern in patterns:
                if pattern in message:
                    return style

    return None
```

**Benefits**:
- ✅ Handles "I want psychoanalysis" → matches "freud"
- ✅ Handles "cognitive behavioral therapy" → matches "cbt"
- ✅ More user-friendly

---

## Summary

### Root Cause
Redundant string check in selection detection logic causes false negatives

### Fix
Remove string check, rely on `awaiting_selection` flag only

### Effort
15 minutes

### Risk
Very low (simplifies logic, removes fragile check)

### Files to Modify
1. [src/agents/trio_assessment_agent.py](src/agents/trio_assessment_agent.py#L93-99) - Remove string check

### Expected Outcome
- ✅ Test passes with mocks
- ✅ Test passes with real LLM
- ✅ Style selection works reliably
- ✅ More robust code
