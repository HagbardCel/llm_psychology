# Codebase Assessment - Modernization and Lean Cleanup

Date: 2026-01-01
Scope: Backend, frontend, console UI, tests, docs, and repo hygiene.

## Overall Assessment

The architecture is strong and already aligned with clean layering, Trio-first
concurrency, and explicit workflow orchestration. The main gaps for a modern,
lean, single-user local tool are legacy compatibility layers, stale docs and
artifacts, and dependency bloat. Most improvements are cleanup and simplification
rather than structural rewrites.

## High Priority - Remove Legacy and Dead Weight

1) Remove legacy compatibility paths and stubs
- `frontend/src/contexts/AppContext.tsx`: legacy state/actions are deprecated and
  appear unused by current components. Remove the shim and update tests.
- `src/psychoanalyst_app/agents/trio_reflection_agent.py`: "LEGACY INTERFACE"
  block is still present. Either promote these methods as supported APIs or
  move orchestration to `TrioPlanningAgent` and remove the legacy label.
- `src/psychoanalyst_app/config.py`: remove `GEMINI_API_KEY` alias and the
  `model_post_init` shim once you standardize on `GOOGLE_API_KEY`.
- `src/psychoanalyst_app/services/rag_service.py`: remove the legacy
  `domain_knowledge_path` fallback if you standardize on style packs.
- `console-ui/src/websocket_protocol.py`: remove "backward compatibility" aliases
  if no longer needed.

2) Remove legacy artifacts checked into the repo
- `src/psychoanalyst_app/data/vector_db/`: contains a Chroma DB artifact that is
  not used by the FAISS RAG path. Remove and add a gitignore rule for this path.
- `out_e2e`: delete if generated output.
- `todos/` and `docs/archive/` and `docs/legacy/`: archive outside the repo if
  you want history, otherwise remove to keep documentation lean.

3) Remove unused dependencies and mypy overrides
- `pyproject.toml`, `requirements.in`, `requirements.txt`: auth dependencies
  (PyJWT, passlib, python-multipart, bcrypt) appear unused in code. Remove.
- `pyproject.toml`: mypy overrides for `chromadb`, `textual`, `dotenv` are legacy.
  Remove to reflect current imports.
- `requirements.in`: `langgraph` and `langchain-community` are not used in the
  codebase. Remove or move to optional extras.

## Backend Improvements (Maintainability and Correctness)

- `src/psychoanalyst_app/container/service_container.py` ignores
  `Settings.DATABASE_POOL_SIZE` and `Settings.DATABASE_POOL_TIMEOUT`. Wire these
  into `TrioSQLiteExecutor` or remove the unused settings.
- `src/psychoanalyst_app/services/db/executor.py` sets `row_factory` on a pooled
  connection but never resets it, which can leak row formats to other callers.
  Save and restore the prior row factory inside the context manager.
- `src/psychoanalyst_app/agents/trio_assessment_agent.py` relies on string
  heuristics in message history to detect phase changes. Track assessment state
  explicitly in `ConversationContext` or persistent metadata instead.
- `src/psychoanalyst_app/agents/trio_assessment_agent.py` has TODOs for scoring
  and key topic extraction. Either implement or remove these fields from the
  recommendation payload to avoid misleading data.
- `src/psychoanalyst_app/agents/trio_therapist_agent.py` has TODOs for topic
  detection that gate session extension logic. Implement or simplify the rule.
- `src/psychoanalyst_app/api/session_routes.py` `extend_session` is a stub.
  Implement or remove the endpoint and its client calls.
- `src/psychoanalyst_app/utils/ws_messages.py` and frontend/console WS constants
  are manually duplicated. Consider generating shared WS types or centralizing
  message type constants to avoid drift.
- Packaging: `pyproject.toml` includes package data for
  `psychoanalyst_app/data/domain_knowledge/**/*`, but the actual data lives in
  `data/domain_knowledge/`. Either move the data into the package or update the
  packaging config and RAG path.

## Frontend Improvements

- `frontend/src/contexts/AppContext.tsx`: remove legacy compatibility layer
  once confirmed unused; update `frontend/src/contexts/__tests__/AppContext.test.tsx`.
- `frontend/src/pages/SettingsPage.tsx`: "Reset progress" is disabled and always
  errors. Remove the UI or implement the backend and hook.
- `frontend/README.md` is stale (mentions `main_launcher.py`, Context API, and
  local-only commands). Update to match the current React Query and Docker flow.

## Tests - What to Keep, Remove, and Add

Keep:
- The existing unit and integration tests are solid and cover the Trio-first
  orchestration, agent behaviors, and API routes.

Remove or relocate:
- `tests/run_tests.py`: runs pytest on the host and ignores the Docker-first rule.
- `tests/reproduce_hang.py`, `tests/reproduce_rate_limit_sharing.py`,
  `tests/load_test_runner.py`, `tests/check_db.py`, `tests/check_actual_db.py`:
  these are scripts, not tests. Move to `scripts/` or delete.

Fix test defaults:
- `docker-compose.yml` runs `pytest` without excluding `real_llm`. Default test
  targets should skip `real_llm` tests unless explicitly requested.

Missing tests to consider:
- Session extension endpoint behavior (or remove the endpoint).
- `TrioSQLiteExecutor` row_factory reset to avoid pooled connection leakage.
- Assessment state tracking (if you move away from message-history heuristics).

## Documentation Assessment

Outdated or conflicting docs:
- `docs/ARCHITECTURE.md` mentions legacy `conduct_session` methods that no longer
  exist. Update or remove those references.
- `docs/QUICKSTART.md` uses host Python commands (`python scripts/purge_databases.py`)
  which conflicts with Docker-only guidance. Provide Docker alternatives.
- `docs/README.md` and `docs/TECH_STACK.md` use "last verified" dates far in the
  future; update to actual dates or remove the "last verified" fields.
- `tests/README.md` does not match the current test tree and still mentions
  deleted legacy test files.

Lean doc structure recommendation:
- Keep: `docs/README.md`, `docs/ARCHITECTURE.md`, `docs/TYPE_SYSTEM.md`,
  `docs/WEBSOCKET_PROTOCOL.md`, `docs/contracts/HTTP_API_CONTRACT.md`,
  `docs/session_lifecycle.md`, `docs/user_journey.md`.
- Move legacy plans and archived assessments to an external archive or a single
  `docs/archive/` folder with an index, then remove `docs/legacy/` entirely.

## Suggested Cleanup Order

1) Remove legacy compatibility layers in frontend/backend and update affected tests.
2) Trim dependencies and unused config fields; update `pyproject.toml` and
   `requirements.in` accordingly.
3) Delete stale artifacts (`src/psychoanalyst_app/data/vector_db`, `out_e2e`,
   script-style tests) and consolidate docs.
