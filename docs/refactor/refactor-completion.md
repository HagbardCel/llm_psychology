---
owner: engineering
status: accepted
last_reviewed: 2026-07-20
review_cycle_days: 90
source_of_truth_for: Completed architecture refactor measurements and acceptance
---

# Refactor Completion

This document is the accepted record of the architecture refactor described in
[Target Architecture](target-architecture.md). It replaces
`baseline-metrics.md`, which existed only to carry the measurement contract and
Phase 1/6 checkpoints forward to this final record.

## Measurement contract

Run natively (stdlib + Git only; no Docker, no project venv):

```bash
python3 scripts/measure_codebase.py --root /path/to/git/worktree --format json
```

The script:

- requires a Git worktree and uses `git ls-files` as the authoritative file set;
- auto-selects `LEGACY_LAYOUT` (`src/psychoanalyst_app` + `console-ui`) or
  `JUNG_LAYOUT` (`src/jung`, client under `src/jung/client`);
- counts **tracked authored text** (UTF-8, no NUL) excluding exact generated paths
  (`requirements.txt` / `requirements-dev.txt` for legacy; `uv.lock` for Jung);
- reports category-specific **Python** LOC for backend, client, tests, and scripts;
- counts HTTP/WebSocket routes via decorator-aware AST detection (not generic
  `.get` / `.route` method calls);
- reads runtime deps from `[project].dependencies`;
- reads development deps from `requirements-dev.in` (legacy / Phase 6) or
  `[dependency-groups].dev` (Phase 7+).

Historical trees must be measured with **this** script via temporary worktrees so
Phase 1, Phase 6, and Phase 7 numbers remain comparable.

## Checkpoint SHAs

| Milestone | Commit |
|---|---|
| Phase 1 start | `1693b01907bac827c3861374ea581e6cb629d3c7` |
| Phase 6 cutover (Phase 6D closure) | `47377ddb681d1fba95d4f317d2be1dc3f6a43baf` |
| Phase 7 final tree | Git tag `refactor-complete` |

## Comparable metrics

| Metric | Phase 1 start | Phase 6 cutover | Phase 7 final |
| --- | ---: | ---: | ---: |
| Backend Python files | 133 | 57 | 58 |
| Backend Python physical LOC | 22,919 | 10,612 | 10,597 |
| Backend Python code LOC | 17,920 | 8,961 | 8,941 |
| Client Python files | 17 | 6 | 6 |
| Client Python physical LOC | 5,202 | 2,311 | 2,282 |
| Test Python physical LOC | 22,092 | 23,657 | 23,062 |
| Script Python physical LOC | 1,504 | 2,766 | 1,372 |
| Tracked authored text physical LOC | 64,895 | 61,131 | 43,926 |
| Tracked authored file count | 323 | 258 | 220 |
| `uv_lock_present` | false | false | true |
| Runtime dependency count | 15 | 10 | 7 |
| Development dependency count | 6 | 5 | 3 |
| Trio importing production modules | 24 | 0 | 0 |
| Legacy namespace importing modules | 98 | 0 | 0 |
| API route count | 24 | 11 | 11 |
| WebSocket endpoint count | 1 | 1 | 1 |
| Stage enum definitions | 0 | 1 | 1 |
| Stage member count | 0 | 7 | 7 |
| CommandName definitions | 0 | 1 | 1 |
| CommandName member count | 0 | 6 | 6 |
| Legacy workflow representation definitions | 3 | 0 | 0 |
| Public concrete store implementations | 0 | 1 | 1 |

Phase 7 final values were produced by the staged two-pass measurement against
the intended final tree (see acceptance notes below).

## Scoped Phase 7 outcome decisions

### mypy removed (Outcome B)

Static typing enforcement was dropped rather than adopted project-wide.
Running mypy with `disallow_untyped_defs` against the Phase 7 tree surfaced 69
errors, disproportionate to the value of introducing and maintaining a new
type-checking gate this late in the refactor. `make typecheck` remains as an
explicit failing target so callers get a clear message instead of silent
success; it is not part of `make test` or `make finalization-check`.

### Worker extraction skipped (optional)

Extracting a dedicated background-worker process/module was scoped as
optional in the target architecture and was skipped: the application layer
remains small and cohesive enough that a separate worker abstraction would add
indirection without a corresponding benefit.

## Acceptance evidence

Pre-merge automated gates (`make finalization-check`: format, lint,
`validate-docs`, `test`, `probe-console`, `smoke-compose-api`) ran on the
Phase 7 branch before merge. The authoritative, durable acceptance record is
the post-merge closure captured in the annotated Git tag `refactor-complete`,
not this document's pre-merge gate run alone.

## Notes

- Backend physical LOC fell from 22,919 to 10,597 (~53.8%), meeting the ≥40%
  backend reduction target.
- Tracked authored text fell from 64,895 to 43,926 (~32.3%). That is slightly
  below the approximate 35–45% repository target because meaningful Jung
  integration, API, and console coverage was retained rather than cut for the
  metric. Architectural invariants take precedence over forcing the percentage.
- Older Phase 1 tables in Git history used a different measurement
  implementation and are not directly comparable to this table.
