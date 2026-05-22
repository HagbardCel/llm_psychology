---
owner: engineering
status: active
last_reviewed: 2026-05-22
review_cycle_days: 90
source_of_truth_for: Validation and prioritization of docs/assessments/misc findings for local-laptop use
---

# Misc Assessments Validation Report

## Executive Summary

This report validates the two miscellaneous assessments:

- `docs/assessments/misc/ANALYSIS_REPORT.md`
- `docs/assessments/misc/analysis_results.md`

Both documents identify real implementation risks, but their priorities often assume a production, multi-user, internet-facing deployment. The current project context is different: Docker-based, single-instance, local-laptop operation. Under that constraint, the highest-priority work is not production authentication or horizontal scaling. It is preserving local workflow continuity, avoiding local data loss, and making the backend resilient enough for a single user running real LLM workflows on one machine.

The most important confirmed issue is assessment recommendation persistence. The application can complete an assessment, move the user to `ASSESSMENT_COMPLETE`, and then lose the recommendations on server restart because they live only in process memory. Since the style-selection page disables selection until recommendations are present, this can block the user from continuing.

## Prioritized Remediation Backlog

### P0 - Blocks Core Local Workflow

| Issue | Verdict | Local relevance | Evidence | Recommended action |
| --- | --- | --- | --- | --- |
| Assessment recommendations are process-local only | Confirmed | High. A local container restart, code reload, or crash can strand a user at style selection. | `ResponseHandler` stores recommendations in `_assessment_recommendations` and `emit_assessment_recommendations()` returns silently when absent. `assessment_recommendations_repo.py` exists, but `MigrationService._get_migrations()` only registers migrations 1 and 2, and the initial schema does not create `assessment_recommendations`. | Add migration for `assessment_recommendations`; expose save/get methods through `TrioDatabaseService`; persist recommendations when generated; fall back to DB lookup before re-emitting them. Add a regression test for reconnect after `ASSESSMENT_COMPLETE` with an empty in-memory cache. |

### P1 - High-Value Local Reliability

| Issue | Verdict | Local relevance | Evidence | Recommended action |
| --- | --- | --- | --- | --- |
| SQLite write resilience is weak | Confirmed, but narrower than the assessments state | Medium-high. A single local user can still trigger overlapping writes through chat persistence plus assessment/reflection/enrichment jobs. | Connections enable foreign keys only. No `PRAGMA journal_mode=WAL` or `synchronous=NORMAL` is set in `migration_service.py` or `services/db/executor.py`. The executor uses a pool of SQLite connections, but there is no explicit retry/backoff for `sqlite3.OperationalError: database is locked`. | Enable WAL on startup/migration for file-backed DBs, set `busy_timeout`, and add a small retry helper for locked write transactions. Keep SQLite; PostgreSQL is not needed for the current local target. |
| Local backup/export/restore is absent | Confirmed | Medium-high. The app stores therapy transcripts and plans in a local SQLite file; laptop failure or accidental deletion loses the user history. | No active backup or restore mechanism was found in `src/`; only legacy/archive docs mention backups. Current database path defaults to `data/psychoanalyst.db`. | Add a documented local backup procedure first. A later implementation can provide a Docker command or small app command that safely copies the SQLite DB using SQLite backup APIs. Avoid cloud backup recommendations for the local-only setup. |

### P2 - Important But Not Immediate

| Issue | Verdict | Local relevance | Evidence | Recommended action |
| --- | --- | --- | --- | --- |
| Active session state is in memory | Confirmed, but intentionally documented | Medium. Restarting the server can disrupt mid-session UX, but single-instance local use does not need Redis or horizontal scaling. | `ActiveSessionRegistry` is a dict keyed by user id. `docs/design-principles.md` explicitly says active tracking is in-memory and multi-instance requires sticky sessions or shared state. `ensure_session_id()` can rebind a provided session id when no active session exists, and intake sessions are reused, so this is not a total persistence failure. | Improve reconnect and restart behavior around active sessions before externalizing state. Add tests for restart-like rebinding and document expected mid-session recovery. Defer Redis/shared state until non-local deployment is a goal. |
| Intake topic detection is brittle | Confirmed | Medium. False positives can prematurely finish intake and degrade assessment quality. | `TrioIntakeAgent._identify_covered_topics()` uses lowercased substring matching over recent messages and static keyword lists. Negation and semantic context are not handled. | Keep keyword matching as a cheap baseline, but gate intake completion with structured LLM validation or a stricter completion heuristic. Add tests for negated mentions such as "I do not want to discuss my mother" not counting as family-background coverage. |
| LLM failures lack graceful fallback | Partially confirmed | Medium. Local providers and remote APIs can fail; the user should get recoverable workflow states. | `LLMService` has Trio rate limiting and Gemini API-key rotation for quota, but `stream_response()` and structured generation wrap provider errors in `LLMServiceError`. There is no provider fallback chain, transient retry policy, or circuit breaker. | Add user-facing failure messages and retry affordances around LLM calls first. Provider fallback is useful later, but local-laptop deployments often choose one configured provider deliberately. |
| WebSocket/API reconnection can leave stale UI | Partially confirmed | Medium-low. Native WebSocket preserves ordering while connected, and the client reconnects with exponential backoff, but there is no message replay or heartbeat. | `websocketService.ts` reconnects up to 5 times. WS envelopes in `ws_messages.py` and `schemas/ws_protocol.json` do not include sequence ids. `apiClient.ts` has timeout handling only, while React Query retries queries once. | Prefer reconnect-state-sync over sequence IDs as the first local fix. On reconnect, re-fetch workflow/session state and ensure required events are re-emitted. Sequence IDs and buffering are production-grade protocol work, not urgent for local use. |

### P3 - Low Priority Or Deferred

| Issue | Verdict | Local relevance | Evidence | Recommended action |
| --- | --- | --- | --- | --- |
| Session enrichment worker polls every 0.5 seconds | Confirmed | Low. Wasteful but unlikely to matter on a laptop unless the app is kept idle for long periods. | `run_session_enrichment_worker()` loops forever and sleeps for `poll_interval_seconds=0.5` when no job exists. | Leave until higher-priority workflow gaps are fixed, or increase the default interval. A push channel is optional polish. |
| No authentication/authorization | Confirmed, but priority is overstated for current scope | Low for a private local laptop; high before LAN, shared-machine, or cloud exposure. | HTTP routes accept `user_id` query/body values. WS accepts `/ws?user_id=...` and validates that the profile exists, not that the caller is authenticated. | Document local-only threat model and bind services to local interfaces. Add real auth only before non-local use. |
| No encryption at rest | Confirmed, but priority depends on real-data usage | Low-medium. OS disk encryption may be sufficient for current development; plaintext DB is risky if real sensitive data is stored on an unencrypted machine. | No active `cryptography`, SQLCipher, or field-level encryption was found in runtime code. | Document OS disk encryption as the expected local control. Defer app-level encryption unless storing real sensitive data is an explicit supported use case. |

## Claims That Are Overstated, Outdated, Or Not Actionable

| Claim | Validation result | Rationale |
| --- | --- | --- |
| "RAG disabled" is a defect | Not a bug for current release | `RAG_BACKEND` defaults to `none`, `create_rag_service()` only supports `none`, and `docs/design-principles.md` explicitly says retrieval is deferred and optional. Keep this as future work, not a current issue. |
| Therapy style descriptions are hardcoded in the frontend | Mostly outdated | `AssessmentPage` fetches styles from `api.therapy.getStyles()`, and `/api/therapy/styles` returns descriptions from `StyleService`. The hardcoded frontend copy is only a fallback when a backend style has no description. |
| Optimistic UI is absent | Incorrect | `TherapySession.handleSendMessage()` appends the user message to local transcript state immediately before sending over WebSocket. |
| PHI caching headers are applied broadly | Not confirmed | `cache_utils.py` exists, but the verified usage found was `/api/therapy/styles`, which returns therapy style metadata. Session and therapy plan endpoints inspected do not apply `add_cache_headers()`. Keep watching this, but do not rank it as a current high-severity issue. |
| In-memory active sessions make the app unusable after any restart | Overstated | The limitation is real, but session data itself is persisted. Existing lifecycle code can reuse intake sessions and can rebind a provided session id when no active session exists. The remaining problem is UX continuity and workflow/event recovery, not total data loss. |
| Horizontal scaling is a current blocker | Out of scope | The active docs state multi-instance deployment is not implemented. For the current local-laptop target, this is intentionally deferred. |

## Verification Notes

The following code and docs were used to verify the assessment claims:

- `src/psychoanalyst_app/orchestration/helpers/response_handler.py`: in-memory assessment recommendation cache and re-emission behavior.
- `src/psychoanalyst_app/orchestration/helpers/response_jobs.py`: assessment job stores generated recommendations only in the provided in-memory dict.
- `src/psychoanalyst_app/services/db/repos/assessment_recommendations_repo.py`: unused repository functions for recommendation persistence.
- `src/psychoanalyst_app/services/migration_service.py`: migrations 1 and 2 only; no `assessment_recommendations` table; no WAL setup.
- `src/psychoanalyst_app/services/db/executor.py`: SQLite pool with foreign keys enabled, but no WAL or locked-write retry policy.
- `src/psychoanalyst_app/orchestration/helpers/active_sessions.py` and `session_lifecycle.py`: process-local active session registry and session creation/rebinding behavior.
- `src/psychoanalyst_app/api/request_utils.py` and `api/ws_handler.py`: user/session validation model based on explicit `user_id` and active session ownership, not authentication.
- `frontend/src/services/websocketService.ts`: exponential reconnect without heartbeat, replay, or sequence ids.
- `frontend/src/services/apiClient.ts` and `frontend/src/providers/QueryProvider.tsx`: API timeout handling plus React Query retry for queries.
- `frontend/src/pages/AssessmentPage.tsx` and `src/psychoanalyst_app/api/therapy_routes.py`: style descriptions come from backend style packs with frontend fallback copy.
- `src/psychoanalyst_app/agents/trio_intake_agent.py`: substring-based topic detection.
- `src/psychoanalyst_app/container/factories/infrastructure.py`, `src/psychoanalyst_app/services/rag_service.py`, and `docs/design-principles.md`: RAG is intentionally disabled for the current release.

## Recommended Implementation Order

1. Persist assessment recommendations and add reconnect regression coverage.
2. Enable SQLite WAL and locked-write retry/backoff.
3. Add a local backup/export/restore procedure.
4. Improve reconnect state synchronization around active sessions and assessment/style-selection state.
5. Harden intake completion with structured validation.
6. Improve user-facing LLM failure recovery.
7. Revisit local security hardening only after the core local workflow is stable.

## Testing Recommendations

- Add a backend integration test that simulates `ASSESSMENT_COMPLETE` with empty in-memory recommendation cache and verifies recommendations can still be emitted from SQLite.
- Add DB tests that verify WAL/busy timeout setup for file-backed SQLite connections.
- Add unit tests for intake topic detection false positives and the new completion gate.
- Add frontend or integration coverage for reconnecting to style selection after page refresh/server restart.

No schema or frontend type regeneration is required for this report itself.
