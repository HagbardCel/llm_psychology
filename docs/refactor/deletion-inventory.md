---
owner: engineering
status: completed
last_reviewed: 2026-07-16
review_cycle_days: 30
source_of_truth_for: Planned legacy deletion inventory
---

# Deletion Inventory

> Planning inventory only; no row authorizes deletion before its replacement and listed characterization coverage exist.

Phase 5 exit evidence: `make validate-refactor-phase-5` (scoped ruff, static/runtime validator, `phase-5-test` including resilience modules). Phase 6 execution slices are grouped by **Owner PR** below; see also [architecture-refactor-roadmap.md § Phase 6](architecture-refactor-roadmap.md#phase-6--cutover-and-legacy-deletion).

| Path / symbols | Responsibility | Target | Test action | Blocker | Phase | Status | Owner PR | Confidence |
|---|---|---|---|---|---:|---|---|---|
| `api/user_routes.py`, `context/user_context.py`, user DTO IDs | registration/login/user scoping | singleton profile and `/api/v1` | rewrite_api | v1 profile contract | 6 | planned | phase-6-auth-removal | confirmed |
| `container/service_container.py`, agent registry/factory | string service lookup | typed composition root | delete_with_component | application construction | 6 | planned | phase-6-composition | confirmed |
| `orchestration/trio_*`, `active_sessions.py`, `workflow_transitions.py` | lifecycle/concurrency | `TherapyApplication`, `Stage`, supervisor | rewrite_application | target application | 6 | planned | phase-6-orchestration | confirmed |
| `orchestration/response_jobs.py`, `job_status.py`, `api/job_routes.py` | job tree/retries | `Operation` and `ChatTurn` | rewrite_api | operation schema/recovery | 6 | planned | phase-6-jobs | confirmed |
| `services/trio_db_service.py`, `services/db/{executor,repositories,facade}*` | persistence stack | `SQLiteStore` (`src/jung/persistence/sqlite_store.py`) | port | store transactions | 6 | planned (Phase 2 target exists) | phase-6-persistence | confirmed |
| `api/ws_handler.py`, `utils/ws_protocol.py`, generated WS constants | legacy transport protocol | discriminated v1 events | rewrite_api | v1 adapter | 6 | planned | phase-6-ws-protocol | confirmed |
| `console-ui/src/console_client.py` legacy networking path | legacy HTTP/WS client | `jung.client` (`JungApiClient`, console) | rewrite_api | v1 client/console | 6 | planned | phase-6-console-ui | likely |
| `src/psychoanalyst_app/trio_server.py`, Quart app wiring | legacy HTTP/WS server | `jung.api` FastAPI app | rewrite_api | v1 API cutover | 6 | planned | phase-6-server | confirmed |
| legacy HTTP routes/DTOs under `src/psychoanalyst_app/api/` | multi-user workflow/job HTTP | `/api/v1` matrix | rewrite_api | contract parity | 6 | planned | phase-6-http | confirmed |
| `schemas/ws_protocol.json`, `console-ui/src/websocket_protocol.py` | generated legacy protocol | `jung.api.contracts` WS union | delete_with_component | generated contract validation | 6 | planned | phase-6-ws-protocol | confirmed |
| planning/memory/reflection agent wiring | cross-agent orchestration | phase helpers/processors | port | typed processors | 6 | planned | phase-6-agents | likely |
| LangChain provider graph, inactive RAG modules, key rotation | speculative infrastructure | `LLMGateway` | rewrite_application | OpenAI adapter | 6 | planned | phase-6-llm | likely |
| `user_id` persistence columns and legacy DTO fields | multi-user identity | singleton profile (no `user_id` on `/api/v1`) | rewrite_api | schema reset | 6 | planned | phase-6-auth-removal | confirmed |
| legacy workflow probes and removed-frontend fixtures | obsolete full-stack probes | `tests/e2e/test_console_v1_workflow.py` + workflow probes | delete_redundant | console v1 probe | 6 | planned | phase-6-tests | discovery-needed |
| duplicate Compose services, stale entry points (`psychoanalyst_app` CLI) | duplicate packaging workflow | `jung-api` / `jung-console` | delete_redundant | cutover runtime | 7 | planned | phase-7-packaging | likely |
| obsolete refactor/legacy documentation referencing dual APIs | dual-contract docs | target-only docs | delete_redundant | Phase 6 cutover | 7 | planned | phase-7-docs | discovery-needed |
