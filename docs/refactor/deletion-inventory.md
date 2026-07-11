---
owner: engineering
status: proposed
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Planned legacy deletion inventory
---

# Deletion Inventory

> Target planning inventory; deletion occurs in Phases 6–7.

| Current area | Replacement/removal | Phase |
|---|---|---|
| User routes, DTO IDs, user repositories | Singleton profile/state | 6 |
| `ServiceContainer`, agent factory | Typed composition root | 6 |
| Trio orchestrator/workflow/conversation managers | `TherapyApplication`, workflow, supervisor | 6 |
| `AgentResponse`, nested note/planning/memory agents | Typed processor results/helpers | 6 |
| Trio DB executor, repos, facade, migration compatibility | `SQLiteStore` and fresh schema | 6 |
| Job tree/status DTOs | `Operation` plus `ChatTurn` | 6 |
| LangChain provider graph, no-op RAG, cloud key/rate services | OpenAI-compatible gateway only | 6 |
| Generated WS constants and version negotiation | Small discriminated contracts | 6 |
| Duplicate Compose services and Docker-only developer workflow | Simplified package workflow | 7 |

Each Phase 6 PR updates this table with symbols, affected tests, blockers, and completion status before deleting a category.
