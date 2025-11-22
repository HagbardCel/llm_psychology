# Test Fixes - Quick Action Plan
**Generated**: 2025-11-16
**Source**: TEST_FAILURE_ANALYSIS.md

## 🚀 30-Minute Quick Wins (19 tests → 75% passing)

### Fix 1: Service Container Imports (10 min, 7 tests)
**File**: `/home/fabian/Projects/llm_psychology/psychoanalyst_app/src/container/service_container.py`

Replace these imports:
```python
# Lines 263, 289, 320, 347, 380, 407
from agents.intake_agent import IntakeAgent
from agents.assessment_agent import AssessmentAgent
from agents.psychoanalyst_agent import PsychoanalystAgent
from agents.reflection_agent import ReflectionAgent
from agents.memory_agent import MemoryAgent
from agents.planning_agent import PlanningAgent
```

With:
```python
from agents.trio_intake_agent import TrioIntakeAgent
from agents.trio_assessment_agent import TrioAssessmentAgent
from agents.trio_psychoanalyst_agent import TrioPsychoanalystAgent
from agents.trio_reflection_agent import TrioReflectionAgent
from agents.trio_memory_agent import TrioMemoryAgent
from agents.trio_planning_agent import TrioPlanningAgent
```

Also update class instantiations (use Find & Replace).

---

### Fix 2: Health Check Async (5 min, 5 tests)
**File**: `/home/fabian/Projects/llm_psychology/psychoanalyst_app/tests/unit/test_service_container.py`

Add `await` to lines 271, 284, 296, 307, 319:
```python
# Before:
health = container.health_check()

# After:
health = await container.health_check()
```

Ensure test methods are `async` and have `@pytest.mark.trio` decorator.

---

### Fix 3: Missing Fixtures (15 min, 7 tests)
**File**: `/home/fabian/Projects/llm_psychology/psychoanalyst_app/tests/conftest.py`

Add these fixtures:
```python
@pytest.fixture
async def test_db_service(tmp_path):
    """Database service for unit tests."""
    db_path = tmp_path / "test.db"
    service = TrioDatabaseService(db_path=str(db_path))
    await service.initialize_database()
    yield service
    await service.shutdown()

@pytest.fixture
def mock_service_container(trio_db_service, mock_llm_service, mock_rag_service):
    """Mock service container with all dependencies."""
    # Note: Check if 'mock_mock_service_container' was a typo
    container = ServiceContainer()
    container.register('trio_db_service', trio_db_service)
    container.register('llm_service', mock_llm_service)
    container.register('rag_service', mock_rag_service)
    # Add other required services
    return container
```

---

## 📊 Next Phase: Medium Complexity (1 hour, 8 tests → 81% passing)

### Fix 4: Briefing Data Format (45-60 min, 8 tests)

Update test fixtures in these files to use complete `SessionBriefing` Pydantic model:
- `tests/unit/test_trio_psychoanalyst_agent.py`
- `tests/unit/test_trio_db_service.py`

**Template** (from `src/models/briefing_models.py`):
```python
from models.briefing_models import (
    SessionBriefing, KeyTheme, EmotionalSummary, RecommendedApproach
)

briefing = SessionBriefing(
    briefing_type="resumption",
    generated_at="2025-11-15T10:00:00Z",
    session_count=3,
    last_session_id="session_003",
    last_session_date="2025-11-14",

    narrative_handoff="Patient exploring work stress...",
    patient_observations="Shows improved awareness...",
    plan_progression_notes="Making steady progress...",

    relationship_quality="strong",
    continuity_points=["Discussed promotion", "Explored coping"],

    emotional_summary=EmotionalSummary(
        last_session="anxious but engaged",
        trend="improving",
        note="Increased emotional awareness"
    ),

    key_themes=[
        KeyTheme(
            theme="work stress",
            status="ongoing",
            priority="high",
            frequency=3,
            first_appearance="session_001",
            last_discussed="session_003"
        )
    ],

    progress_highlights=["Identified triggers"],
    unresolved_issues=["Career decision"],

    recommended_approach=RecommendedApproach(
        opening_tone="warm, validating",
        opening_focus="Check promotion decision",
        things_to_avoid="Rushing solutions",
        suggested_questions=["How have you been?"],
        therapeutic_goals_for_session=["Explore anxiety"]
    )
)
```

**Search & replace**:
- Find: `"key_themes": ["work stress", "anxiety"]`
- Replace with proper `KeyTheme` objects (see template)

---

## 🔴 Complex Investigation (2-3 hours, 19 tests → 94%+ passing)

### Fix 5: Database Schema Issues (2-3 hours, 19 tests)

**Problem**: Test databases not initialized with proper schema

**Investigation checklist**:
1. ✅ Check `trio_db_service.initialize_database()` creates all tables
2. ✅ Verify test fixtures call `initialize_database()`
3. ✅ Ensure schema includes:
   - `user_profiles` table
   - `sessions` table
   - `therapy_plans` table
   - `session_briefing` column in therapy_plans
4. ✅ Check if migrations needed for briefing column
5. ✅ Verify isolation between tests (proper cleanup)

**Files to check**:
- `/home/fabian/Projects/llm_psychology/psychoanalyst_app/src/services/trio_db_service.py` (initialize_database method)
- `/home/fabian/Projects/llm_psychology/psychoanalyst_app/tests/conftest.py` (database fixtures)
- `/home/fabian/Projects/llm_psychology/psychoanalyst_app/tests/integration/test_trio_flow.py`
- `/home/fabian/Projects/llm_psychology/psychoanalyst_app/tests/integration/test_trio_websocket.py`

**Affected tests** (8 in test_trio_flow.py, 9 in test_trio_websocket.py, 2 in test_trio_validation.py):
- All fail with: `sqlite3.OperationalError: no such table: user_profiles/sessions`

---

## 🧹 Minor Cleanup (10 min, 2 tests)

### Fix 6: RAG Service Attribute (5 min, 1 test)
**File**: `tests/unit/test_rag_service.py::TestRAGServiceIntegration::test_init_with_temp_directories`

Error: `AttributeError: 'RAGService' object has no attribute 'domain_collection'`

Find correct attribute name in RAGService class and update test.

---

### Fix 7: Docker Compose Test (2 min, 1 test)
**File**: `tests/test_dev_setup.py::test_dev_service`

Error: `FileNotFoundError: docker-compose not found`

**Fix**: Skip this test in isolated container:
```python
@pytest.mark.skipif(
    os.getenv('CI') or not shutil.which('docker-compose'),
    reason="docker-compose not available in isolated test environment"
)
def test_dev_service():
    ...
```

---

## 📈 Expected Progress

| Phase | Time | Tests Fixed | Cumulative | Pass Rate |
|-------|------|-------------|------------|-----------|
| Start | - | - | 74/124 | 60% |
| After Quick Wins | 30 min | +19 | 93/124 | 75% |
| After Medium | +60 min | +8 | 101/124 | 81% |
| After Complex | +2-3 hrs | +19 | 120/124 | 97% |
| After Cleanup | +10 min | +2 | 122/124 | 98% |

---

## ✅ Testing After Each Fix

Run specific test groups:
```bash
# After Fix 1 (imports)
pytest tests/unit/test_service_container.py::TestServiceContainerAgentCreation -v

# After Fix 2 (health checks)
pytest tests/unit/test_service_container.py::TestServiceContainerHealthCheck -v

# After Fix 3 (fixtures)
pytest tests/unit/test_trio_db_service.py::test_save_therapy_plan_without_briefing -v
pytest tests/unit/test_trio_reflection_agent.py -v

# After Fix 4 (briefing format)
pytest tests/unit/test_trio_psychoanalyst_agent.py -v
pytest tests/unit/test_trio_db_service.py::test_save_and_load_therapy_plan_with_briefing -v

# After Fix 5 (database schema)
pytest tests/integration/test_trio_flow.py -v
pytest tests/integration/test_trio_websocket.py -v
pytest tests/test_trio_validation.py -v

# Full test suite
make test-validate
```

---

## 🎯 Success Criteria

- ✅ At least 116/124 tests passing (94%)
- ✅ All Trio orchestration tests passing (currently 13/13 ✓)
- ✅ All agent creation tests passing
- ✅ All briefing feature tests passing
- ✅ Integration tests stable

---

## 📝 Notes

1. **Trio migration incomplete**: Service container still imports legacy agents
2. **Test data format**: Briefing tests don't match Pydantic model structure
3. **Database setup**: Integration tests lack proper schema initialization
4. **Good news**: Core Trio orchestration is solid (100% passing)
