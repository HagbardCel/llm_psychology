---
name: Fix Syntax Error and Improve Error Messages
overview: Fix the Python syntax error in trio_conversation_manager.py that prevents the api-usertest container from starting, and enhance the Makefile to provide clear error messages when containers fail to start.
todos: []
---

# Fix Syntax Error and Improve Error Messages

## Root Cause Analysis

The `make ui-console-test` command fails because:

1. **Primary Issue**: Python syntax error in `trio_conversation_manager.py` line 494 - nested f-string with escaped quotes containing backslashes, which Python doesn't allow in f-string expressions.
2. **Secondary Issue**: The Makefile doesn't verify that the `api-usertest` container started successfully before attempting to run `console-ui-usertest`, leading to cryptic error messages.

## Implementation Plan

### 1. Fix Syntax Error in `trio_conversation_manager.py`

**File**: [`src/psychoanalyst_app/orchestration/trio_conversation_manager.py`](src/psychoanalyst_app/orchestration/trio_conversation_manager.py)

**Issue**: Line 494 uses a nested f-string with escaped quotes:

```python
f"{[f\"{m['role']}: {m['content'][:30]}...\" for m in history[-3:]]}"
```

**Fix**: Replace the nested f-string with a list comprehension using regular string formatting:

```python
f"{[f\"{m['role']}: {m['content'][:30]}...\" for m in history[-3:]]}"
```

Should become:

```python
f"{[f'{m[\"role\"]}: {m[\"content\"][:30]}...' for m in history[-3:]]}"
```

Or better yet, use a helper function or string concatenation to avoid nested f-strings entirely.

### 2. Enhance Makefile Error Handling

**File**: [`Makefile`](Makefile)

**Changes needed**:

- Add a check after starting `api-usertest` to verify it's running and healthy
- Display container logs if startup fails
- Provide clear error messages with actionable guidance
- Check container exit status before proceeding to `console-ui-usertest`

**Specific improvements**:

- After line 399 (starting api-usertest), add a check to wait for the container to be healthy
- If the container fails, display the last 50 lines of logs with a clear error message
- Exit with a helpful error message pointing to the logs and common issues
- Apply similar improvements to other UI test targets (`ui-web-test`, `ui-all-test`)

### 3. Improve Error Messages

**Enhancements**:

- When `api-usertest` fails to start, show:
  - Clear error header
  - Last 50 lines of container logs
  - Common causes (syntax errors, missing env vars, port conflicts)
  - Suggested debugging commands (`make docker-logs-api`, `docker compose logs api-usertest`)
- Add a helper target or function to check container health before proceeding

## Files to Modify

1. [`src/psychoanalyst_app/orchestration/trio_conversation_manager.py`](src/psychoanalyst_app/orchestration/trio_conversation_manager.py) - Fix syntax error at line 494
2. [`Makefile`](Makefile) - Enhance `ui-console-test`, `ui-web-test`, and `ui-all-test` targets with error checking and clear messages

## Testing

After fixes:

1. Run `make ui-console-test` - should start successfully
2. Verify error messages are clear if containers fail
3. Test that syntax errors are caught and reported clearly