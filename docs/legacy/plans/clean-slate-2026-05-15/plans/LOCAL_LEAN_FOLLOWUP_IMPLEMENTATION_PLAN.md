# Local-Lean Follow-up Implementation Plan

## Purpose
Implement the "Suggested Next Focus" items from `docs/assessments/project/CODEBASE_ASSESSMENT_2025-12-22_LOCAL_LEAN_FOLLOWUP.md` in a safe, junior-friendly sequence. This plan is scoped to the six items listed there.

## Goals
- Reduce dependency footprint without breaking runtime or tests.
- Establish a single source of truth for the WS protocol version and message types.
- Align frontend HTTP usage on the shared `apiClient`.
- Centralize profile merge logic in HTTP routes.
- Resolve agent TODOs with clear, deterministic behavior.
- Align docs and tooling to a Docker-only workflow.

## Non-Goals
- Redesigning the WS protocol payloads beyond the current set.
- Changing the orchestration flow or adding new features.
- Broad refactors outside the six focus items.

## Constraints and Rules
- Run all commands inside containers (Docker-only workflow).
- If HTTP/WS contracts or API-facing models change, update contract docs and regenerate schemas/types.
- Keep changes minimal and deterministic, with tests updated as needed.

## Execution Order
1. Dependency and tooling slimming
2. WS protocol single source of truth
3. Frontend versionService uses apiClient
4. Profile merge centralization in HTTP routes
5. Agent TODO cleanup
6. Docker-only vs local workflow alignment
7. Optional lean defaults (rate limiting/logging) if approved

---

## 1) Dependency and Tooling Slimming

### Files to Review
- `pyproject.toml`
- `requirements.in`
- `requirements-dev.in`
- `requirements.txt`
- `requirements-dev.txt`

### Steps
1. Use `rg` to confirm usage of the following dependencies:
   - `torchvision`, `torchaudio`
   - `PyJWT`, `passlib`, `bcrypt`
   - `chromadb` (mypy override only)
2. If unused, remove these from:
   - `pyproject.toml` dependencies
   - `requirements.in` and `requirements-dev.in`
3. If the team wants to **guarantee CPU-only wheels**, keep `torchvision`/`torchaudio` and document how CPU wheels are enforced:
   - Prefer the CPU index (`https://download.pytorch.org/whl/cpu`) or `+cpu` pins.
   - Verify Docker/CI does **not** set a CUDA extra index (GPU wheels).
3. Regenerate lockfiles (Docker-only):
   - If `uv` is installed in the API image, use `docker compose run --rm api uv pip compile requirements.in -o requirements.txt` and similarly for dev.
   - If not, add a Docker-compatible `make docker-requirements` target that runs `uv` in the API container, then use it.
4. Remove `chromadb.*` from mypy overrides in `pyproject.toml` if not used.

### Acceptance Criteria
- Dependencies removed from `pyproject.toml` and both requirements lockfiles, **or** explicitly retained with CPU-only enforcement documented.
- Tests run green (see Testing section).
- No import errors in app startup.

### Risks
- `sentence-transformers[onnx]` can pull torch extras indirectly. Verify it still works without torchvision/torchaudio.
- If a CUDA index is configured in Docker/CI, GPU wheels can be installed even if dependencies are present; enforce CPU index if needed.

---

## 2) WS Protocol Single Source of Truth

### Proposed Single Source
Create a JSON spec file: `schemas/ws_protocol.json`.

#### Suggested Schema Shape
```
{
  "version": "1.2.3",
  "message_types": {
    "client_to_server": ["chat_message", "end_session"],
    "server_to_client": [
      "connected",
      "session_started",
      "workflow_next_action",
      "chat_response_chunk",
      "typing_start",
      "typing_stop",
      "assessment_recommendations",
      "session_ended",
      "error"
    ]
  }
}
```

### Steps
1. Add `schemas/ws_protocol.json` with the current protocol version and message types.
2. Add a generator script, for example `scripts/generate_ws_protocol.py`, that emits:
   - `src/psychoanalyst_app/utils/ws_protocol.py` (Python constants for backend use)
   - `console-ui/src/websocket_protocol.py` (replace manual constants)
   - `frontend/src/types/ws_protocol.generated.ts` (message types + version)
3. Update imports:
   - Backend uses constants from `src/psychoanalyst_app/utils/ws_protocol.py` in `ws_messages.py` and any other emitter.
   - Console UI uses the generated module instead of hand-maintained values.
   - Frontend re-exports constants from the generated TS file in `frontend/src/types/websocket.ts`.
4. Update docs:
   - `docs/WEBSOCKET_PROTOCOL.md` should reference the JSON spec as the source of truth.
5. Add a README note in `docs/TYPE_SYSTEM.md` or `docs/WEBSOCKET_PROTOCOL.md` describing the generation step.

### Acceptance Criteria
- Single JSON spec drives version and message types for backend, frontend, and console.
- No manual duplication of version or message types across clients.
- WS protocol docs point to the JSON spec.

---

## 3) Frontend versionService Uses apiClient

### Files to Review
- `frontend/src/services/versionService.ts`
- `frontend/src/services/apiClient.ts`

### Steps
1. Replace `fetch` calls in `versionService` with the shared `apiClient`.
2. Align error handling to the standard client behavior.
3. Update tests if any rely on the old `fetch` behavior.

### Acceptance Criteria
- All HTTP calls in `versionService` use `apiClient`.
- No direct `fetch` usage remains in `versionService`.

---

## 4) Profile Merge Centralization in HTTP Routes

### Files to Review
- `src/psychoanalyst_app/orchestration/profile_helpers.py`
- `src/psychoanalyst_app/api/user_routes.py`

### Steps
1. Replace manual profile merge logic in `PUT /api/user/profile` and `PATCH /api/user/profile` with:
   - `merge_user_profile` for merging fields
   - `parse_date_of_birth` for DOB normalization
2. Preserve existing validation rules (status immutability, session validation).
3. Ensure the returned DTOs remain unchanged.

### Acceptance Criteria
- No duplicate merge logic in `user_routes.py`.
- PUT and PATCH behave the same as before from the API perspective.

---

## 5) Agent TODO Cleanup

### Files to Review
- `src/psychoanalyst_app/agents/trio_assessment_agent.py`
- `src/psychoanalyst_app/agents/trio_psychoanalyst_agent.py`

### Decision Required
Pick one of these approaches and document it in the PR:
- Option A: Use the assessment agent LLM to return scores + key topics (preferred).
- Option B: Remove TODOs and make the placeholders explicit and stable.

### Suggested Minimal Implementation (Option A)
- Extend the assessment agent prompt/structured output to include `score` and `key_topics` for each recommendation.
- Parse those LLM fields directly (no deterministic keyword extraction).
- For the psychoanalyst agent TODO, prefer an LLM-provided signal (e.g., a boolean or label in the model output) rather than heuristics.

### Acceptance Criteria
- TODO markers removed or resolved with LLM-provided fields.
- No change in API contract shape.
- Behavior is documented in code comments or docs where needed.

---

## 6) Docker-only vs Local Workflow Alignment

### Files to Review
- `Makefile`
- `docs/README.md`
- Any docs in `docs/` mentioning local commands

### Steps
1. Decide on policy (Docker-only). Confirm with the team.
2. Remove or deprecate `local-*` targets from `Makefile`.
3. Update docs to avoid recommending local Python/Node execution.
4. Ensure `AGENTS.md` and `docs/README.md` are consistent.

### Acceptance Criteria
- Docs and Makefile describe a single Docker-first workflow.
- No local-only instructions in the main docs unless explicitly labeled deprecated.

---

### Files to Review
- `src/psychoanalyst_app/config.py`

---

## Testing Plan (Docker-only)
- Backend quick tests: `make test-dev`
- Backend full suite: `make test-validate`
- Frontend unit tests (if touched): `make test-frontend`
- If WS protocol generation changes TS types: run `docker compose run --rm frontend npm run generate:types` when applicable.

---

## Documentation Updates Checklist
- `docs/WEBSOCKET_PROTOCOL.md` updated if WS constants move.
- `docs/README.md` updated for Docker-only workflow.
- Any new generator steps documented in `docs/TYPE_SYSTEM.md` or protocol docs.

---

## Deliverables
- Updated dependency lists and lockfiles.
- WS protocol JSON spec + generated constants in backend, frontend, console.
- Refactored `versionService` with `apiClient`.
- HTTP profile update routes using shared merge helpers.
- Agent TODOs resolved or explicitly removed with deterministic behavior.
- Docker-only workflow reflected in docs and Makefile.
