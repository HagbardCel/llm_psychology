# Test Failures in `out_test_validate` — Debug Notes + Fix Plan

This document summarizes the failures listed in `out_test_validate` and lays out a concrete plan to make the suite green again in the Docker test run.

## 1) What’s failing (from `out_test_validate`)

### Integration
- `tests/integration/test_console_ui_patient_flow.py::test_complete_patient_journey_intake_to_therapy`
- `tests/integration/test_console_ui_patient_flow.py::test_intake_flow_only`
- `tests/integration/test_natural_patient_flow.py::test_natural_patient_flow`
- `tests/integration/test_session_timer_endpoint.py::test_get_session_timer_success`
- `tests/integration/test_session_timer_endpoint.py::test_get_session_timer_not_found`
- `tests/integration/test_session_timer_endpoint.py::test_get_session_timer_requires_auth`
- `tests/integration/test_session_timer_endpoint.py::test_get_session_timer_with_extensions`
- `tests/integration/test_session_timer_endpoint.py::test_get_session_timer_time_up`
- `tests/integration/test_trio_agents.py::test_planning_agent_create_initial_plan`
- `tests/integration/test_trio_agents.py::test_intake_agent_tier1_extraction`
- `tests/integration/test_trio_agents.py::test_reflection_agent_create_initial_plan`
- `tests/integration/test_trio_agents.py::test_reflection_agent_session_enrichment`
- `tests/integration/test_trio_agents.py::test_full_agent_workflow`
- `tests/integration/test_trio_agents.py::test_concurrent_agent_operations`
- `tests/integration/test_trio_agents.py::test_assessment_agent_process_selection`
- `tests/integration/test_trio_agents.py::test_assessment_agent_creates_tier3_and_tier4`
- `tests/integration/test_trio_agents.py::test_reflection_agent_tier3_versioning`
- `tests/integration/test_trio_agents.py::test_reflection_agent_tier3_no_update_when_stable`

### Other
- `tests/test_basic_functionality.py::TestBasicFunctionality::test_data_models`
- `tests/test_basic_functionality.py::TestBasicFunctionality::test_database_service`

### Unit
- `tests/unit/test_trio_reflection_agent.py::test_generate_session_briefing_structure`
- `tests/unit/test_trio_reflection_agent.py::test_process_reflection_updates_plan_with_briefing`

## 2) Root causes (grouped)

### A) Tier 4 fields are now required
`TherapyPlan` is strict (Tier 4 fields required). Several tests still construct `TherapyPlan` with only legacy fields (or with legacy-only attributes like `recommendation_reasoning`).

Symptoms:
- Pydantic `ValidationError` for missing `initial_goals`, `current_progress`, `planned_interventions`.

Where it shows up:
- `tests/test_basic_functionality.py` (`test_data_models`, `test_database_service`)
- `tests/integration/test_session_timer_endpoint.py` (all timer tests create an invalid plan)
- `tests/integration/test_console_ui_patient_flow.py` (manual plan creation missing Tier 4 fields)
- Potentially other integration fixtures using `TherapyPlan(...)`.

### B) Tests/mocks are still using removed “structured response/data” APIs
The implementation moved to Gemini native structured output (`generate_structured_output[_async]` with JSON Schema). Several tests still patch or rely on:
- `generate_structured_response`, `generate_structured_response_async`
- `generate_structured_data`, `generate_structured_data_async`

Symptoms:
- AttributeError / wrong data shape reaching agent code.

Where it shows up:
- `tests/integration/test_trio_agents.py` (Tier 2, Tier 3/Tier 4 patching still uses `generate_structured_data*`)
- `tests/integration/test_natural_patient_flow.py` (mock LLM only implements `generate_structured_response*`)

### C) The shared LLM mock returns schema-incompatible payloads
`tests/conftest.py::mock_llm_service` returns the same generic dict for any schema, but agents now request *different* Pydantic models:
- `PatientProfileExtract` (intake tier1)
- `PlanUpdate` (planning agent)
- `Tier4Extract`, `PatientAnalysis` (assessment)
- `SessionBriefing` (reflection)

Symptoms:
- Pydantic `ValidationError` when `schema.model_validate(...)` runs.

Where it shows up:
- `tests/integration/test_trio_agents.py` (multiple failing agent tests)
- `tests/unit/test_trio_reflection_agent.py` (briefing generation tests)
- `tests/integration/test_console_ui_patient_flow.py` (its custom mock doesn’t expose structured-output methods at all)

### D) TrioServer tests may fail after adding the Tier 2 enrichment worker
`TrioServer._initialize_orchestration()` now always starts the background worker. If a unit test uses a mocked `trio_db_service` that doesn’t implement job-queue methods, the worker crashes immediately and can bring down the nursery/server.

This isn’t listed in `out_test_validate` (the log truncates before the TrioServer tests finish), but it’s a likely next blocker once the above failures are fixed.

## 3) Detailed fix plan (ordered, with acceptance criteria)

### Step 1 — Fix `TherapyPlan` construction in failing tests
Update all failing tests/fixtures that instantiate `TherapyPlan` to include:
- `plan_details` (existing)
- `initial_goals` (non-empty list)
- `current_progress` (non-empty string)
- `planned_interventions` (non-empty list)

Concrete places to change:
- `tests/test_basic_functionality.py`:
  - Add Tier 4 fields to the two `TherapyPlan(...)` constructions.
  - Consider relaxing `GOOGLE_API_KEY` requirements (unit tests shouldn’t require secrets).
- `tests/integration/test_session_timer_endpoint.py`:
  - Either remove plan creation entirely (timer endpoint doesn’t strictly require a plan), or construct a valid minimal plan.
- `tests/integration/test_console_ui_patient_flow.py`:
  - When manually creating a plan, include Tier 4 fields.
- `tests/conftest.py::sample_therapy_plan`:
  - Include Tier 4 fields so any test using the fixture remains valid.

Acceptance:
- `pytest -q tests/test_basic_functionality.py::TestBasicFunctionality::test_data_models` passes.
- `pytest -q tests/integration/test_session_timer_endpoint.py -q` no longer fails at plan instantiation.

### Step 2 — Make the shared `mock_llm_service` schema-aware
Update `tests/conftest.py::mock_llm_service` so `generate_structured_output[_async]` returns *valid* instances per schema.

Recommended approach:
- Implement a `match schema.__name__` style dispatcher:
  - `SessionAnalysis`: return `key_themes`, `emotional_state`, optional lists.
  - `Tier2Enrichment`: return all required Tier 2 fields.
  - `PlanUpdate`: return `focus`, `goals`, `techniques`, `themes`, `timeline` as strings; ensure `goals/techniques` contain bullet/semicolon separators so `_split_bullets()` produces non-empty lists.
  - `PatientProfileExtract`: return `BasicPatientBackground(alias=...)` etc. (alias can be inferred from prompt if needed for assertions like “Sarah Johnson”).
  - `PatientAnalysis`: return the full nested structure with required submodels.
  - `Tier4Extract`: return non-empty `initial_goals` and `planned_interventions`, and non-empty `current_progress`.
  - `SessionBriefing`: return a fully valid payload that passes `models/briefing_models.py` validators (min narrative length, non-empty key themes, etc).

Acceptance:
- `tests/integration/test_trio_agents.py::test_planning_agent_create_initial_plan` passes.
- `tests/integration/test_trio_agents.py::test_intake_agent_tier1_extraction` passes.
- `tests/unit/test_trio_reflection_agent.py::test_generate_session_briefing_structure` passes.

### Step 3 — Update tests that patch old “structured_*” APIs
Replace references to removed APIs in tests:
- `generate_structured_response*` → `generate_structured_output*` (schema-driven)
- `generate_structured_data*` → `generate_structured_output*`

Concrete places to change:
- `tests/integration/test_trio_agents.py`:
  - `test_reflection_agent_session_enrichment`: patch `llm_service.generate_structured_output_async(..., Tier2Enrichment, ...)` to return the exact enrichment payload asserted by the test.
  - Tier 3/Tier 4 tests: patch `generate_structured_output_async(..., PatientAnalysis, ...)` and `... Tier4Extract ...` (or rely on the improved global mock from Step 2).
  - Concurrency/versioning tests: patch the new async structured output method(s) instead of `generate_structured_data_async`.
- `tests/integration/test_natural_patient_flow.py`:
  - Extend its local mock to implement `generate_structured_output_async` and return schema-valid models for the tier extractions used during the flow.

Acceptance:
- All failures in `tests/integration/test_trio_agents.py` go away without relying on removed APIs.

### Step 4 — Fix the console UI flow integration tests’ custom mock LLM
`tests/integration/test_console_ui_patient_flow.py` uses a custom mock that only covers streaming text.

Add to that mock:
- `generate_structured_output_async` / `generate_structured_output` with schema-aware responses (reuse the dispatcher from Step 2, ideally via a shared helper).

Also update the manual `TherapyPlan(...)` construction to include Tier 4 fields (or stop manually creating it and let the orchestrator path create it).

Acceptance:
- `tests/integration/test_console_ui_patient_flow.py::test_intake_flow_only` passes.
- `tests/integration/test_console_ui_patient_flow.py::test_complete_patient_journey_intake_to_therapy` passes.

### Step 5 — Harden TrioServer unit tests against the worker
In `tests/unit/test_trio_server.py`, extend the mocked `trio_db_service` to implement the worker calls:
- `claim_next_session_enrichment_job` → return `None`
- `mark_session_enrichment_job_complete` / `mark_session_enrichment_job_failed` → no-op async mocks

Alternative (if desired): add a config/flag to `TrioServer` to disable the worker in unit tests, but stubbing the DB methods keeps production code lean.

Acceptance:
- `pytest -q tests/unit/test_trio_server.py -q` passes in the Docker test environment.

### Step 6 — Re-run the same command as `out_test_validate`
Run:
- `docker compose --profile test run --rm test`

Acceptance:
- The full suite passes (or any remaining failures have stack traces pointing to a new, smaller set of issues).

## 4) Suggested follow-ups (optional, but improves maintainability)

- Add a shared helper for schema-aware LLM mocks (e.g., `tests/helpers/mock_llm.py`) so integration tests don’t re-implement partial mocks inconsistently.
- Make “basic functionality” tests pytest-native (instead of `unittest`) so they can use the existing pytest fixtures and markers consistently.

