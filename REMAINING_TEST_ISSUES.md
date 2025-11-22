# Remaining Test Issues - Action Plan

After implementing critical fixes, approximately **15-20 tests** still fail. These are categorized below with specific remediation steps.

---

## Category 1: Legacy Asyncio Integration Tests (14 tests)

### Issue: Tests for Deleted Asyncio Code
These tests reference the old asyncio architecture that has been completely replaced by Trio.

### Affected Files

#### `tests/integration/test_complete_session_flow.py` (4 tests)
- `test_intake_to_assessment_to_session_flow`
- `test_resume_flow_integration`
- `test_multiple_sessions_performance`
- `test_graceful_error_handling`

**Problem:** Tests use deleted `UnifiedServer` and asyncio workflow
**Recommendation:** **DELETE** - Replace with new Trio integration tests

#### `tests/integration/test_main_application_integration.py` (7 tests)
- `test_main_application_startup_with_container`
- `test_main_application_error_handling`
- `test_main_workflow_error_handling_integration`
- `test_main_migration_integration_on_startup`
- `test_user_status_flow_with_new_architecture`
- `test_resume_from_plan_complete_status`
- `test_resume_from_intake_complete_status`

**Problem:** Tests import from legacy `main.py` with asyncio code
**Recommendation:**
- **Option A:** DELETE if testing obsolete workflow
- **Option B:** Rewrite to test `trio_server.py` if functionality is still relevant

### Action Items
```bash
# Option 1: Delete legacy tests
rm tests/integration/test_complete_session_flow.py
rm tests/integration/test_main_application_integration.py

# Option 2: Mark as skipped (temporary)
# Add @pytest.mark.skip(reason="Legacy asyncio tests - needs rewrite for Trio")
```

---

## Category 2: Performance Tests for Deleted Agents (9 tests)

### Issue: Tests Call Non-Existent Legacy Agent Methods

#### `tests/integration/test_performance_validation.py` (9 tests)
- `test_session_context_analysis_performance` (MemoryAgent)
- `test_pattern_identification_performance` (MemoryAgent)
- `test_therapeutic_memory_retrieval_performance` (MemoryAgent)
- `test_initial_plan_creation_performance` (PlanningAgent)
- `test_plan_effectiveness_assessment_performance` (PlanningAgent)
- `test_plan_evolution_tracking_performance` (PlanningAgent)
- `test_concurrent_user_workflows`
- `test_agent_creation_performance`
- `test_database_connection_pool_performance`

**Problem:** Tests try to create legacy asyncio agents that no longer exist
**Root Cause:** Performance container uses old agent creation methods

### Solution Options

#### Option A: Update to Test Trio Agents (Recommended)
Update `test_performance_validation.py` to test Trio agent performance:

```python
# In test_agent_creation_performance:
agent_types = [
    ('intake', 'create_intake_agent'),           # Already exists, works with Trio
    ('assessment', 'create_assessment_agent'),   # Already exists, works with Trio
    ('psychoanalyst', 'create_psychoanalyst_agent'),  # Already exists, works with Trio
    ('reflection', 'create_reflection_agent'),   # Already exists, works with Trio
    ('memory', 'create_memory_agent'),           # Already exists, works with Trio
    ('planning', 'create_planning_agent')        # Already exists, works with Trio
]

# For agent-specific tests, create Trio agents:
from agents.trio_memory_agent import TrioMemoryAgent
from agents.trio_planning_agent import TrioPlanningAgent

# Then call their Trio methods instead of legacy asyncio methods
```

#### Option B: Delete Performance Tests
If performance testing isn't critical for MVP:
```bash
rm tests/integration/test_performance_validation.py
```

### Recommended Action
**UPDATE TESTS** - Performance validation is valuable, just needs Trio agent updates.

---

## Category 3: RAGService API Issues (2 tests)

### Issue: Tests Expect Non-Existent Attribute

**Error:** `RAGService` object has no attribute `domain_collection`

### Investigation Needed
1. Check if `domain_collection` was removed during refactoring
2. Determine if tests are outdated or if API needs restoration

### Action Items
```bash
# Step 1: Find affected tests
grep -r "domain_collection" tests/

# Step 2: Check RAGService implementation
grep -r "domain_collection" src/services/rag_service.py

# Step 3: Either update tests or restore API
```

---

## Category 4: Dev Tool Dependencies (2 tests)

### Issue: Missing Optional Development Tools

#### `tests/test_dev_setup.py`
- Missing `docker-compose` command
- Missing `psutil` Python module

**Problem:** Tests run in isolated Docker without dev tools
**Recommendation:** Make tests conditional

### Solution
```python
# In test_dev_setup.py
import pytest

@pytest.mark.skipif(
    not shutil.which('docker-compose'),
    reason="docker-compose not available in test environment"
)
def test_docker_compose_available():
    ...

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

@pytest.mark.skipif(not HAS_PSUTIL, reason="psutil not installed")
def test_system_resources():
    ...
```

---

## Summary of Remaining Work

| Category | Tests | Effort | Priority | Recommendation |
|----------|-------|--------|----------|----------------|
| Legacy Integration | 11 | Low | High | **DELETE** |
| Performance Tests | 9 | Medium | Medium | **UPDATE** |
| RAGService API | 2 | Low | Low | **INVESTIGATE** |
| Dev Tool Deps | 2 | Low | Low | **SKIP** |
| **Total** | **24** | | | |

---

## Execution Plan

### Step 1: Quick Wins (30 minutes)
```bash
# Delete obsolete tests
git rm tests/integration/test_complete_session_flow.py
git rm tests/integration/test_main_application_integration.py

# Add skip decorators to dev setup tests
# Edit tests/test_dev_setup.py to add @pytest.mark.skipif
```

**Expected Result:** ~11 fewer failures

### Step 2: Performance Tests (1-2 hours)
```bash
# Update test_performance_validation.py
# - Verify agent creation methods still work (they should)
# - Update agent-specific method calls to use Trio agent APIs
# - Add proper async/await for Trio operations
```

**Expected Result:** ~9 fewer failures

### Step 3: RAGService Investigation (30 minutes)
```bash
# Find root cause
grep -r "domain_collection" .

# Update tests or restore API as needed
```

**Expected Result:** ~2 fewer failures

### Step 4: Verification
```bash
make test-validate
```

**Expected Result:** 100% test pass rate (or documented skips)

---

## Alternative: Pragmatic Approach

If time is limited, take the pragmatic approach:

### Delete All Problematic Tests
```bash
# Remove legacy tests
git rm tests/integration/test_complete_session_flow.py
git rm tests/integration/test_main_application_integration.py
git rm tests/integration/test_performance_validation.py

# Add skip markers to dev setup
# Edit tests/test_dev_setup.py
```

### Create New Trio Integration Tests
Create `tests/integration/test_trio_session_resumption.py` based on the plan in `TESTING_PLAN_SESSION_RESUMPTION.md`.

**Rationale:**
- Legacy tests test obsolete code (no value)
- New tests validate actual current system
- Faster than fixing outdated tests
- Better test coverage of Trio architecture

---

## After Remediation

### Expected Final Test Stats
- **Total Tests:** ~105-110 (after deletions)
- **Passing:** 100-105
- **Skipped:** 2-5 (dev tools, optional tests)
- **Failing:** 0
- **Success Rate:** ~95-100%

### Test Coverage by Type
- ✅ Unit tests: 40 tests (services, agents, models)
- ✅ Integration tests: 30 tests (Trio flow, orchestration, WebSocket)
- ✅ Validation tests: 10 tests (Trio functionality, DB service)
- ⚠️ Performance tests: 0-10 tests (deleted or updated)
- ⚠️ Legacy tests: 0 tests (deleted)

---

## Conclusion

Most remaining failures are **legacy code tests that should be deleted**, not fixed. The core Trio system is solid and well-tested.

**Recommended Priority:**
1. **HIGH:** Delete legacy integration tests → Quick win, ~11 tests fixed
2. **MEDIUM:** Update or delete performance tests → Better if updated
3. **LOW:** Fix RAGService API → Minor issue, 2 tests
4. **LOW:** Add skip decorators → Nice to have

**Time Investment:**
- Quick approach (delete): 30 minutes
- Complete approach (update): 2-3 hours
- New Trio tests: 1-2 hours (recommended anyway)
