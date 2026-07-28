---
owner: engineering
status: supporting
last_reviewed: 2026-07-21
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
- Historical records, completed plans, legacy migration notes.
- Not canonical for current implementation behavior.
- Must be deleted after durable guidance is incorporated into active docs.
- Recover old context from Git history when needed.

## Active Docs Set
The current active canonical set is:

1. `docs/README.md`
2. `docs/safety-and-data.md`
3. `docs/ui-scope.md`
4. `docs/refactor/target-architecture.md`
5. `docs/refactor/api-v1-contract.md`
6. `docs/refactor/workflow-specification.md`

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
6. Local-link validity across `README.md`, `AGENTS.md`, and all `docs/**/*.md`.

### Review convention
Supporting documents should link back to a relevant canonical document. This
convention is not automated by the validator.

## Related canonical documentation

- [Documentation Index](README.md)
