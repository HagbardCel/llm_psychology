---
owner: engineering
status: accepted
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Planned legacy deletion inventory
---

# Deletion Inventory

> Planning inventory only; no row authorizes deletion before its replacement and listed characterization coverage exist.

| Path / symbols | Responsibility | Target | Test action | Blocker | Phase | Status |
|---|---|---|---|---|---:|---|
| `api/user_routes.py`, `context/user_context.py`, user DTO IDs | registration/login/user scoping | singleton profile and `/api/v1` | rewrite_api | v1 profile contract | 6 | planned |
| `container/service_container.py`, agent registry/factory | string service lookup | typed composition root | delete_with_component | application construction | 6 | planned |
| `orchestration/trio_*`, `active_sessions.py`, `workflow_transitions.py` | lifecycle/concurrency | `TherapyApplication`, `Stage`, supervisor | rewrite_application | target application | 6 | planned |
| `orchestration/response_jobs.py`, `job_status.py`, `api/job_routes.py` | job tree/retries | `Operation` and `ChatTurn` | rewrite_api | operation schema/recovery | 6 | planned |
| `services/trio_db_service.py`, `services/db/{executor,repositories,facade}*` | persistence stack | `SQLiteStore` | port | store transactions | 6 | planned |
| `api/ws_handler.py`, `utils/ws_protocol.py`, generated WS constants | legacy transport protocol | discriminated v1 events | rewrite_api | v1 adapter | 6 | planned |
| planning/memory/reflection agent wiring | cross-agent orchestration | phase helpers/processors | port | typed processors | 6 | planned |
| LangChain provider graph, inactive RAG modules, key rotation | speculative infrastructure | `LLMGateway` | rewrite_application | OpenAI adapter | 6 | planned |
| duplicate Compose profiles/services, Docker-only duplicate commands | duplicate packaging workflow | minimal runtime tooling | delete_redundant | cutover runtime | 7 | planned |
