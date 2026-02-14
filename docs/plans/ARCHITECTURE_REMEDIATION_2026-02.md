# Architecture Remediation Plan (2026-02)

## Scope
Implements the P0/P1 contract and protocol consistency findings from
`docs/assessment/2026-02-02_architecture_assessment.md`.

## Implemented (P0)
- Canonical contract naming enforced as `Session` + `session_id` in schema/type pipelines.
- Added machine-readable WS protocol source of truth: `schemas/ws_protocol.json`.
- Updated schema generation to preserve non-model protocol specs (`ws_protocol.json`).
- Updated schema validation to validate `ws_protocol.json` structure.
- Regenerated WS protocol constants from schema for:
  - `src/psychoanalyst_app/utils/ws_protocol.py`
  - `console-ui/src/websocket_protocol.py`
  - `frontend/src/types/ws_protocol.generated.ts`
- Consolidated frontend WS message/version constants to generated values in
  `frontend/src/types/websocket.ts`.
- Added CI checks for legacy naming drift (`session_block_id` / `SessionBlock`) in
  schemas and generated frontend API types.
- Added CI job to verify WS protocol generated files are up to date.
- Removed stale broken gateway import in `src/psychoanalyst_app/gateways/__init__.py`.
- Marked `docs/session_block_lifecycle.md` as deprecated and pointed to
  `docs/session_lifecycle.md`.

## Implemented (P1 guardrails)
- Removed non-blocking bypass for frontend type-check in `.github/workflows/type-safety.yml`.
- Added schema generation unit tests for:
  - canonical `session_id` contract
  - absence of legacy `SessionBlock` naming
  - `ws_protocol.json` preservation during schema generation

## Remaining Follow-up
- Frontend currently has existing TypeScript errors unrelated to this migration; these
  should be addressed to keep the stricter CI path green.
- Broader layer-boundary refactors (agent I/O reduction, orchestration hardening) remain
  future work.
