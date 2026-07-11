---
owner: engineering
status: accepted
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Refactor baseline measurement procedure
---

# Baseline Metrics

Phase 1 measured tree commit: `3a4989f0d51b04bf413014de9e2a642e16f57695`. Captured on 2026-07-11 in the API container with:

```bash
scripts/measure_phase1_baseline.sh
```

Historical Phase 1 starting commit: `1693b01907bac827c3861374ea581e6cb629d3c7` (`main`). Both columns below were produced by the same `measure_codebase.py` implementation (`tokenize` code LOC, AST import detection, conservative SQL table detection).

| Metric | Phase 1 start | Phase 1 completion |
|---|---:|---:|
| Production Python files | 131 | 131 |
| Production Python physical LOC | 22,640 | 22,640 |
| Production Python code LOC | 17,630 | 17,630 |
| Test Python files | 72 | 82 |
| Test Python physical LOC | 22,092 | 23,110 |
| Test Python code LOC | 17,590 | 18,453 |
| Trio-importing production modules | 24 | 24 |
| Service-container importing modules | 7 | 7 |
| Persistence-related modules | 14 | 14 |
| Pydantic model candidates | 63 | 63 |
| API route count | 23 | 23 |
| Routes in user-named modules | 7 | 7 |
| WebSocket endpoint count | 1 | 1 |
| SQLite table count | 8 | 8 |
| Workflow state member count | 11 | 11 |
| Workflow action member count | 18 | 18 |

`persistence_related_modules` counts files under `services/db` plus production modules importing that package. `routes_in_user_named_modules` counts routes declared in API files whose filename contains `user`; it is an approximate legacy-scope metric, not an exact user-scoped route inventory.

`measure_codebase.py` counts Python code lines with `tokenize` (comments, blank lines, and standalone syntax tokens excluded), parses source with AST for imports/classes/enums/Pydantic subclasses, and separately reports backend, tests, console, scripts, executable configuration, direct dependencies, routes, websocket decorators, tables, and workflow types. SQL table detection is textual and intentionally conservative. Dynamic routes, generated/ignored paths, transitive dependencies, and runtime-only tables are limitations.

| Metric group | Target direction |
|---|---|
| backend physical LOC | reduce 40–55% at cutover |
| repository physical LOC | reduce 35–45% while retaining meaningful coverage |
| Trio/service-container imports | zero at cutover |
| user-scoped routes / legacy websocket endpoints | zero at cutover |
| workflow state/action representations | one `Stage` plus commands |
| persistence layers | one `SQLiteStore` |

## Dependency classification

| Package | Current role | Classification | Target action | Phase |
|---|---|---|---|---:|
| `trio` | async runtime | scheduled for removal | replace with asyncio | 6 |
| `quart-trio` | Trio integration | scheduled for removal | remove | 6 |
| `quart` / `hypercorn` | HTTP server | scheduled for removal | replace with FastAPI/Uvicorn | 5–6 |
| `pydantic` / `pydantic-settings` | contracts/settings | runtime | retain | 2 |
| `httpx` | HTTP client/tests | runtime/test | retain | 5 |
| `trio-websocket` | console/test transport | scheduled for removal | replace with `websockets` client | 5–6 |
| `langchain-core` / provider packages | provider graph | scheduled for removal | remove | 6 |
| RAG-related modules | inactive retrieval | scheduled for removal | remove without replacement | 6 |
| `openai` | absent direct SDK | runtime | introduce in gateway | 3 |
| `pytest-trio` | Trio test runtime | scheduled for removal | replace `pytest-asyncio` | 3–6 |
| `fastapi` / `uvicorn` / `websockets` | absent target transport | runtime/test | introduce | 3–5 |
| `pytest` / `black` / `ruff` / `mypy` | tooling | test/tooling | retain | 1 |

The baseline command, SHA, definitions, limitations, targets, dependency table, and generated machine-readable metric keys are validated by `make validate-refactor-phase-1`. Commit existence for the completion SHA is verified in CI via `scripts/extract_baseline_sha.py` and `git cat-file`.

Required metric keys: `production_python_files`, `production_python_physical_loc`, `production_python_code_loc`, `test_python_files`, `test_python_physical_loc`, `test_python_code_loc`, `console_python_files`, `console_python_physical_loc`, `console_python_code_loc`, `script_python_files`, `script_python_physical_loc`, `script_python_code_loc`, `executable_configuration_files`, `direct_dependency_count`, `trio_importing_production_modules`, `service_container_importing_modules`, `persistence_related_modules`, `pydantic_model_candidates`, `api_route_count`, `routes_in_user_named_modules`, `websocket_endpoint_count`, `sqlite_table_count`, `workflow_state_member_count`, and `workflow_action_member_count`.

## Phase 2 checkpoint (in progress)

Branch `refactor/phase-2-domain-persistence` adds the isolated target package under `src/jung/`:

| Artifact | Location |
|---|---|
| Domain models, commands, errors | `src/jung/domain/` |
| Pure workflow policy | `src/jung/workflow.py` |
| SQLite schema + store | `src/jung/persistence/` |
| Unit tests | `tests/unit/jung/` |
| Integration tests | `tests/integration/jung/` |
| Validation target | `make validate-refactor-phase-2` |

Phase 2 does not modify legacy runtime metrics above. Re-measure at Phase 2 merge for an updated checkpoint row.
