# Local-Lean Assessment Follow-up (2026-01-01)

## Scope
This review re-evaluates the improvement list from `docs/assessments/project/CODEBASE_ASSESSMENT_2025-12-22_LOCAL_LEAN.md` against the current codebase. The focus is on identifying which items are **still not implemented** and **still desirable** given recent changes.

## Summary
- **Implemented since 2025-12-22**: documentation alignment, WS protocol alignment across clients, config/auth simplification, orchestration refactor, RAG/style unification, frontend stub removal.
- **Partially implemented**: CLAUDE.md reference cleanup (only legacy/archive docs remain), profile merge centralization, error response helpers.
- **Still desirable and not implemented**: dependency/tooling slimming, single WS protocol source of truth, versionService using apiClient, unresolved agent TODOs, docker-vs-local story alignment, optional lean defaults (rate limiting/logging).

---

## Implemented / Resolved Since 2025-12-22

### Documentation and contract alignment
- Native WebSocket examples in quickstart are already in place. See `docs/QUICKSTART.md`.
- Session lifecycle paths now point at Trio server and WS handler. See `docs/session_lifecycle.md`.
- WS protocol spec updated and aligned with current events. See `docs/WEBSOCKET_PROTOCOL.md`.

### WebSocket protocol consolidation (client alignment)
- Frontend message types now match backend events and docs. See `frontend/src/types/websocket.ts`.
- Console protocol matches docs and frontend version. See `console-ui/src/websocket_protocol.py`.

### Configuration and auth simplification
- Config is passed via `Settings` and container; no global settings singleton. See `src/psychoanalyst_app/config.py`, `src/psychoanalyst_app/trio_server.py`.
- Auth layer is removed from routes. No `require_auth` or auth middleware in `src/psychoanalyst_app/api`.

### Orchestration refactor and error handling
- `process_message` has been split into helpers and now logs + re-raises instead of emitting stack traces. See `src/psychoanalyst_app/orchestration/process_messages.py`, `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py`.

### RAG + style pack unification
- RAG service loads knowledge only from style packs; domain knowledge path removed. See `src/psychoanalyst_app/services/rag_service.py`.

### Frontend lean pass
- Settings reset stub removed. See `frontend/src/pages/SettingsPage.tsx`.
- WebSocket client no longer sends unused client events (no ping/typing commands). See `frontend/src/services/websocketService.ts`.

---

## Partially Implemented (Still Desirable)

### CLAUDE.md reference cleanup
- References remain only in legacy/archive docs. See `docs/legacy/` and `docs/archive/` matches for `CLAUDE.md`.
- If those folders remain part of the searchable docs set, removing or annotating those references is still useful to reduce confusion.

### Profile merge centralization
- `merge_user_profile` exists and is used in orchestration flows. See `src/psychoanalyst_app/orchestration/profile_helpers.py`.
- HTTP profile update endpoints still reimplement merge logic. See `src/psychoanalyst_app/api/user_routes.py`.
- Still desirable to reuse `merge_user_profile` (or `ensure_user_profile`) for PUT/PATCH to keep updates consistent and reduce duplication.

### Error response helpers
- There is a `validation_error_response` helper, but general error shaping is still ad-hoc. See `src/psychoanalyst_app/api/http_errors.py`.
- Still desirable if you want fully consistent error envelopes across routes.

---

## Not Implemented and Still Desirable

### 1) Frontend API consistency: version service should use apiClient
- `frontend/src/services/versionService.ts` uses raw `fetch` rather than the shared `apiClient`.
- Still desirable to reduce duplicated base URL handling, headers, and error shaping.

### 2) Dependencies and tooling slimming
- `chromadb.*` mypy override remains. See `pyproject.toml`.
- `torchvision` and `torchaudio` remain in dependencies and lockfiles. See `pyproject.toml`, `requirements.txt`.
- Auth-related deps (`PyJWT`, `passlib`, `bcrypt`) remain despite auth removal. See `pyproject.toml`.
- Still desirable to trim these if they are unused (lower install footprint, faster Docker builds).

### 3) Single WS protocol source of truth
- Protocol constants exist separately in frontend and console, and there is no backend constant. See `frontend/src/types/websocket.ts`, `console-ui/src/websocket_protocol.py`.
- Docs imply a backend source, but none exists. Still desirable to generate protocol types (or a JSON schema) once and consume everywhere to prevent future drift.

### 4) Agent TODO cleanups
- `trio_assessment_agent` still uses placeholder scoring/key topic extraction. See `src/psychoanalyst_app/agents/trio_assessment_agent.py`.
- `trio_therapist_agent` still references TODO topic detection. See `src/psychoanalyst_app/agents/trio_therapist_agent.py`.
- Still desirable to either implement or remove placeholders to keep the codebase lean and decisive.

### 5) Docker-only vs local workflow alignment
- Makefile exposes both Docker and local targets, and docs describe local alternatives. See `Makefile`, `docs/README.md`.
- If the project policy is Docker-only (as in AGENTS.md), it is still desirable to remove or clearly deprecate local targets and local instructions to avoid confusion.

### 6) Lean defaults (decision points)
- `LLM_RATE_LIMIT_ENABLED` defaults to true. See `src/psychoanalyst_app/config.py`.
- Logging defaults include file output in `logs/`. See `src/psychoanalyst_app/config.py`.
- If the local-lean goal is to reduce friction, it is still desirable to consider disabling rate limiting by default and limiting file logging to opt-in.

---

## Items Likely No Longer Necessary

- Strictly minimizing the WS protocol beyond the current set is less compelling now that `workflow_next_action` and typing events are part of active UX flows. The current protocol appears minimal for the existing features.

---

## Suggested Next Focus (If You Want to Continue the Lean Pass)

1. Remove unused dependencies and mypy overrides (chromadb, torchaudio, torchvision, auth deps).
2. Consolidate WS protocol constants into a single generated source.
3. Convert `versionService` to use `apiClient` for consistent HTTP behavior.
4. Reuse `merge_user_profile` in HTTP update endpoints.
5. Resolve agent TODOs (either implement or explicitly remove).
6. Decide on Docker-only vs hybrid workflow and simplify docs/Makefile accordingly.

