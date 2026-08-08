---
owner: engineering
status: supporting
last_reviewed: 2026-08-08
review_cycle_days: 90
source_of_truth_for: Documentation governance policy and active-doc standards
---

# Documentation Governance

## Purpose
This policy defines how documentation stays lean, current, and easy to navigate.
It establishes a strict active-doc set and a predictable review process.

## Documentation Classes

### Active
- Canonical docs used for day-to-day engineering work.
- Must include required metadata front matter.
- Must be listed in `docs/README.md` under `Active Docs (Canonical)`.

### Supporting
- Useful implementation notes and focused references.
- May evolve quickly and can defer broad editorial cleanup.
- Must link back to an active canonical document for context.

### Historical
- Historical records, completed plans, migration notes.
- Not canonical for current implementation behavior.
- Must be deleted after durable guidance is incorporated into active docs.
- Recover old context from Git history when needed.

## Active Docs Set

The executable active set is defined by `ACTIVE_DOCS` in
`scripts/validate_docs_metadata.py` and is mirrored exactly under
`Active Docs (Canonical)` in `docs/README.md`. Validation enforces their
agreement. Do not maintain a third numbered copy of that list here.

## Documentation ownership

| Subject | Owner |
|---|---|
| First run | root `README.md` |
| Architecture / tech stack / `src/jung` layout / UI policy | `docs/architecture.md` |
| Runtime synchronization / task ownership | `docs/architecture.md` |
| Workflow / recovery / command-conflict semantics | `docs/workflow.md` |
| HTTP semantics + complete WebSocket wire contract | `docs/api-v1.md` |
| Generated HTTP request/response schema only | `/api/v1/openapi.json` (OpenAPI; Swagger/ReDoc disabled) |
| Persistence model | `docs/database.md` + DDL in `src/jung/persistence/schema.sql` |
| Developer workflow / commands | `docs/development.md` + `Makefile` |
| Environment configuration | `docs/development.md` for guidance; `.env.example` for supported examples; runtime settings code (`src/jung/config.py`, `src/jung/api/settings.py`) for parsing/defaults |
| Safety / erasure | `docs/safety-and-data.md` |
| Test layout | `tests/README.md` |
| Eval philosophy | `evals/README.md` |
| Agent-only instructions | `AGENTS.md` |

## Required Front Matter for Active Docs
All active docs must include this metadata block at the top:

```yaml
---
owner: engineering
status: active
last_reviewed: YYYY-MM-DD
review_cycle_days: 90
source_of_truth_for: <short scope statement>
---
```

### Field Rules
1. `owner`: stable team label, not an individual name.
2. `status`: must be `active` for active docs.
3. `last_reviewed`: ISO date (`YYYY-MM-DD`).
4. `review_cycle_days`: positive integer.
5. `source_of_truth_for`: one concise sentence of scope.

## Update Rules
1. If behavior/contracts change, update the canonical active doc in the same PR.
2. Do not duplicate canonical guidance in multiple active docs; link instead.
3. Keep top-level docs concise and route deep details to focused pages.
4. If a doc becomes historical, incorporate any durable guidance into an active
   doc and delete the historical file. Do not create archive folders.

## Validation

### Automated enforcement
Use the docs metadata validator:

```bash
make validate-docs
```

The validator enforces:
1. Required front matter keys on all active docs.
2. ISO date format for `last_reviewed`.
3. `status: active` for active docs.
4. Active docs are indexed in `docs/README.md` under `Active Docs (Canonical)`
   with exactly the canonical links in the documented order: no missing,
   unexpected, duplicate, or reordered links.
5. Reviews are not overdue: a document remains valid through
   `last_reviewed + review_cycle_days` and fails validation the following day.
6. Local-link validity across `README.md`, `AGENTS.md`, `docs/**/*.md`,
   `tests/README.md`, and `evals/README.md`.

### Review convention
Supporting documents should link back to a relevant canonical document. This
convention is not automated by the validator.

## Related canonical documentation

- [Documentation Index](README.md)
