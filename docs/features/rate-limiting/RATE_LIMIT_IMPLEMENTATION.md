# Rate Limiting Implementation for Real LLM Tests

## Problem

When running `test_natural_patient_flow` with `--no-mocks` flag, the test was hitting Gemini API rate limits:

```
google.api_core.exceptions.ResourceExhausted: 429 Resource has been exhausted (e.g. check quota).
retry_delay: 39 seconds
```

This caused the test to timeout with `TooSlowError` after 134.74 seconds.

**Root Cause**: Making 15-20 sequential LLM API calls within ~2 minutes exceeds the Gemini API's rate quota.

---

## Solution Implemented

As requested by the user: **"Combine 2+3+4, but not 1"**

### Option 2: Add Delays Between API Calls ✅

Added 2-second delays after each `wait_for_response_complete()` call when `use_real_llm` is True:

```python
await wait_for_response_complete(timeout=30 if use_real_llm else 10)

# Rate limiting: delay between API calls for real LLM
if use_real_llm:
    await trio.sleep(2)
```

**Applied to 5 locations**:
1. After initial name message (line 390)
2. After each intake message in the loop (line 441)
3. After "I'm ready for recommendations" message (line 493)
4. After CBT selection message (line 513)
5. After each therapy phase message (line 556)

### Option 3: Increase Test Timeout ✅

Added `@pytest.mark.timeout(300)` decorator to allow 5 minutes for real LLM tests:

```python
@pytest.mark.timeout(300)  # 5 minutes for real LLM with rate limiting
@pytest.mark.slow
async def test_natural_patient_flow(test_server, use_real_llm):
```

### Option 4: Add Slow Marker ✅

Added `@pytest.mark.slow` to mark the test as slow/manual:

```python
@pytest.mark.slow
async def test_natural_patient_flow(test_server, use_real_llm):
```

This allows skipping slow tests in CI with:
```bash
pytest -m "not slow"
```

### Option 1: NOT Implemented ❌

**Intentionally excluded** as per user request: Did NOT reduce the number of intake messages to keep full test coverage.

---

## Files Modified

### tests/integration/test_natural_patient_flow.py

**Line 305-307**: Added test decorators
```python
@pytest.mark.timeout(300)  # 5 minutes for real LLM with rate limiting
@pytest.mark.slow
async def test_natural_patient_flow(test_server, use_real_llm):
```

**Lines 389-391, 440-442, 492-494, 512-514, 555-557**: Added rate limiting delays
```python
# Rate limiting: delay between API calls for real LLM
if use_real_llm:
    await trio.sleep(2)
```

---

## Expected Results

### With Mocks (--no-mocks NOT specified)
- **Duration**: ~13-15 seconds
- **Behavior**: No delays applied (use_real_llm=False)
- **Status**: ✅ Test passes in 13.18s

### With Real LLM (--no-mocks)
- **Duration**: ~3-5 minutes (with 2s delays between calls)
- **API Calls**: 15-20 calls spread over 3+ minutes
- **Rate Limiting**: 2-second delays prevent quota exhaustion
- **Status**: Should pass without rate limit errors

---

## Calculation

**Number of API calls**: ~17 (1 name + 12 intake + 2 assessment + 3 therapy)

**With delays**:
- Time for API calls: ~17 * 10s = 170s (average LLM response time)
- Time for delays: ~17 * 2s = 34s
- Total: ~204s (~3.4 minutes)

**Without delays** (previous behavior):
- Total: ~134s (~2.2 minutes)
- Result: Hit rate limits with 39s retry delay

**Conclusion**: 2-second delays spread the load sufficiently to avoid rate limits while keeping total test time under 5 minutes.

---

## Testing

### Run with Mocks (fast)
```bash
pytest tests/integration/test_natural_patient_flow.py::test_natural_patient_flow -v
# Expected: ~13-15s, no delays applied
```

### Run with Real LLM (slow)
```bash
pytest tests/integration/test_natural_patient_flow.py::test_natural_patient_flow --no-mocks -v
# Expected: ~3-5 minutes with delays, should not hit rate limits
```

### Skip Slow Tests in CI
```bash
pytest -m "not slow"
# Will skip tests marked with @pytest.mark.slow
```

---

## Benefits

1. ✅ **Respects API quotas** - 2s delays prevent rate limit errors
2. ✅ **Maintains test coverage** - All intake messages kept for thorough testing
3. ✅ **Fast mock tests** - No delays when using mocks (~13s)
4. ✅ **Reasonable real LLM duration** - ~3-5 minutes is acceptable for integration tests
5. ✅ **CI-friendly** - Can skip slow tests with `-m "not slow"`
6. ✅ **Clear timeout** - 5-minute timeout prevents hanging indefinitely

---

## Key Takeaways

- **Real LLM tests are slow by nature** - API latency + rate limiting means 3-5 minutes is expected
- **Delays are targeted** - Only applied when `use_real_llm=True`
- **Mock tests stay fast** - No performance impact on development workflow
- **Rate limits are API-imposed** - Cannot be eliminated, only mitigated with delays
- **Test coverage preserved** - All intake topics still covered as per original design

---

## Related Documentation

- [FINAL_IMPLEMENTATION_SUMMARY.md](FINAL_IMPLEMENTATION_SUMMARY.md) - Previous fixes (server coordination, shielding, style detection)
- [REAL_LLM_TEST_DEBUG_PLAN.md](REAL_LLM_TEST_DEBUG_PLAN.md) - Analysis of timeout issues
- [REAL_LLM_TEST_DEBUG_ASSESSMENT.md](REAL_LLM_TEST_DEBUG_ASSESSMENT.md) - Technical assessment of solutions
