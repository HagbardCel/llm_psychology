# Refined Patient Information System — Improvements (Implemented)

This document tracks the improvements planned for `docs/features/refined_patient_information_system.md` and the current implementation status. It focuses on correctness, latency safety (no hidden LLM calls on read paths), reliability, and auditability.

## Key decisions (current)

1. **No JSON scraping/parsing of LLM output**: all tier extraction/enrichment uses **Gemini structured output** (JSON Schema) via LangChain’s `with_structured_output(..., method="json_schema")`.
2. **No LLM calls on read paths**: building live-session context must be deterministic and fast.
3. **Async enrichment is safe only with explicit gating**: if a consumer needs Tier 2, it must either operate without it or explicitly wait.
4. **Tier 4 is strict**: treatment trajectory fields are required and validated (no empty defaults).
5. **Tier 3 version allocation is atomic**: prevent `(user_id, version)` collisions under concurrency.

## Implementation status

### A) Gemini native structured outputs (no JSON scraping)

**Implemented**
- `src/services/llm_service.py` exposes `generate_structured_output()` / `generate_structured_output_async()` using `method="json_schema"`.
- Tier-related agents use schema models instead of parsing raw JSON text:
  - `src/agents/trio_intake_agent.py` (`PatientProfileExtract`)
  - `src/agents/trio_assessment_agent.py` (`PatientAnalysis`, `Tier4Extract`)
  - `src/agents/trio_reflection_agent.py` (Tier 1 patching, Tier 2 enrichment, Tier 3 updates, session briefing)
  - `src/agents/trio_memory_agent.py` (`SessionAnalysis`)
  - `src/agents/trio_planning_agent.py` (`PlanUpdate`)

### B) Tier 2 enrichment async-safe (and your question)

**Does enqueuing enrichment async risk invalidating downstream dependencies on enriched content?**

Yes—if downstream code assumes Tier 2 fields exist synchronously. The current implementation avoids this by ensuring “read paths” never block on enrichment and by making “Tier 2 required” an explicit choice.

**Implemented**
- DB-backed queue `session_enrichment_jobs` + worker:
  - `src/services/migration_service.py` (migration 7)
  - `src/services/trio_db_service.py` (enqueue/claim/complete/fail)
  - `src/services/session_enrichment_worker.py`
  - `src/services/session_enrichment_service.py`
- Worker is started in both primary runtimes:
  - `src/trio_server.py` (server)
  - `src/main.py` (terminal UI)
- Psychoanalyst context load is read-only:
  - `src/agents/trio_psychoanalyst_agent.py` loads `enriched_only=True`; if enrichment is missing it enqueues jobs and degrades gracefully.

### C) Tier 4 data integrity (meaningful treatment trajectory)

**Implemented**
- `src/models/data_models.py` makes `plan_details`, `initial_goals`, `current_progress`, `planned_interventions` required and validated.
- `src/models/structured_output_models.py` makes Tier 4 extraction strict (`Tier4Extract`).
- Plan creation paths always populate Tier 4 fields:
  - `src/agents/trio_planning_agent.py`
  - `src/orchestration/trio_agent_orchestrator.py`
- Migration ensures existing rows are non-empty:
  - `src/services/migration_service.py` (migration 6).

### D) Tier 3 versioning under concurrency

**Implemented**
- Atomic “next version” allocation + supersede in one DB operation:
  - `src/services/trio_db_service.py` (`save_patient_analysis_next_version_and_supersede`).

### E) DB correctness (foreign keys)

**Implemented**
- SQLite FK enforcement enabled on both migration and runtime connections:
  - `src/services/migration_service.py`
  - `src/services/trio_db_service.py`

### F) Tier 1 audit trail (rare updates)

**Implemented**
- Append-only `patient_profile_history`:
  - `src/services/migration_service.py` (migration 8)
  - `src/services/trio_db_service.py` (writes history on update + read API)

## Remaining work (testing only)

- Integration/e2e tests for worker lifecycle + concurrency scenarios (unit tests cover most logic, but Trio-based integration tests require an environment where Trio’s IO manager can start).

