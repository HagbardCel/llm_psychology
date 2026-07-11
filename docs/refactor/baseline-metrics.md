---
owner: engineering
status: accepted
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Refactor baseline measurement procedure
---

# Baseline Metrics

Phase 1 completion commit: `b127296143e5346d5fedbb369bad3781682acf3b7`. Captured on 2026-07-11 in the API container with:

```bash
docker compose run --rm api python scripts/measure_codebase.py --format markdown
```

Historical Phase 1 starting commit: `1693b01907bac827c3861374ea581e6cb629d3c7` (`main`). The measurement script was introduced after that starting commit, so the starting values below are retained evidence rather than regenerable output from that exact tree.

| Metric | Phase 1 start | Phase 1 completion |
|---|---:|---:|
| Production Python files | 131 | 131 |
| Production Python physical LOC | 22,640 | 22,640 |
| Production Python code LOC | 19,223 | 17,630 |
| Test Python files | 80 | 82 |
| Test Python physical LOC | 22,160 | 22,909 |
| Test Python code LOC | 17,978 | 18,272 |
| Trio-importing production modules | 24 | 24 |
| Service-container importing modules | 11 | 7 |
| Persistence abstraction modules | 9 | 14 |
| Pydantic model candidates | 9 | 63 |

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

The baseline command, SHA, definitions, limitations, targets, dependency table, and generated machine-readable metric keys are validated by `make validate-refactor-phase-1`.

Required metric keys: `production_python_files`, `production_python_physical_loc`, `production_python_code_loc`, `test_python_files`, `test_python_physical_loc`, `test_python_code_loc`, `console_python_files`, `console_python_physical_loc`, `console_python_code_loc`, `script_python_files`, `script_python_physical_loc`, `script_python_code_loc`, `executable_configuration_files`, `direct_dependency_count`, `trio_importing_production_modules`, `service_container_importing_modules`, `persistence_abstraction_modules`, `pydantic_model_candidates`, `api_route_count`, `user_scoped_route_count`, `websocket_endpoint_count`, `sqlite_table_count`, `workflow_state_member_count`, and `workflow_action_member_count`.
