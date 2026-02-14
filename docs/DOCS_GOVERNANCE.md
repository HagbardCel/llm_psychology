---
owner: engineering
status: supporting
last_reviewed: 2026-02-14
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

### Archived
- Historical records, completed plans, legacy migration notes.
- Not canonical for current implementation behavior.
- Must stay under `docs/archive/` or `docs/legacy/`.

## Active Docs Set
The current active canonical set is:

1. `docs/README.md`
2. `docs/design-principles.md`
3. `docs/ARCHITECTURE.md`
4. `docs/user_journey.md`
5. `docs/session_lifecycle.md`
6. `docs/contracts/HTTP_API_CONTRACT.md`
7. `docs/WEBSOCKET_PROTOCOL.md`
8. `docs/TYPE_SYSTEM.md`
9. `docs/data-models.md`
10. `docs/agents/README.md`
11. `docs/assessments/README.md`

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
4. If a doc becomes historical, move it to `docs/archive/` or `docs/legacy/`.

## Validation
Use the docs metadata validator:

```bash
make validate-docs
```

The validator enforces:
1. Required front matter keys on all active docs.
2. ISO date format for `last_reviewed`.
3. `status: active` for active docs.
4. Active docs are indexed in `docs/README.md` under `Active Docs (Canonical)`.
