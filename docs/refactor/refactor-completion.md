---
owner: engineering
status: accepted
last_reviewed: 2026-07-21
review_cycle_days: 90
source_of_truth_for: Completed architecture refactor measurements and acceptance
---

# Refactor Completion

This document is the accepted record of the architecture refactor described in
[Target Architecture](target-architecture.md). It replaces
`baseline-metrics.md`, which existed only to carry the measurement contract and
Phase 1/6 checkpoints forward to this final record.

## Measurement provenance

The comparable metrics below are a **frozen historical comparison**. They were
produced at the Phase 7 measured commit using `scripts/measure_codebase.py`
available in that commit's Git history. That measurement tooling was removed
during repository closure and is not maintained as ongoing governance.

## Checkpoint SHAs

| Milestone | Commit |
|---|---|
| Phase 1 start | `1693b01907bac827c3861374ea581e6cb629d3c7` |
| Phase 6 cutover (Phase 6D closure) | `47377ddb681d1fba95d4f317d2be1dc3f6a43baf` |
| Phase 7 measured tree | `feb2af3d4d72cd7383164d673de4515e1d153457` |
| Repository closure acceptance | annotated tag `refactor-complete` |

The Phase 7 measured tree and the later closure tree are intentionally
different. The closure tree is smaller and was not re-measured by the removed
permanent measurement tooling.

## Comparable metrics

| Metric | Phase 1 start | Phase 6 cutover | Phase 7 measured tree |
| --- | ---: | ---: | ---: |
| Backend Python files | 133 | 57 | 58 |
| Backend Python physical LOC | 22,919 | 10,612 | 10,637 |
| Backend Python code LOC | 17,920 | 8,961 | 8,974 |
| Client Python files | 17 | 6 | 6 |
| Client Python physical LOC | 5,202 | 2,311 | 2,282 |
| Test Python physical LOC | 22,092 | 23,657 | 23,164 |
| Script Python physical LOC | 1,504 | 2,766 | 1,377 |
| Tracked authored text physical LOC | 64,895 | 60,933 | 40,353 |
| Tracked authored file count | 323 | 256 | 212 |
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

Phase 7 measured-tree values were produced by the staged two-pass measurement
against commit `feb2af3d4d72cd7383164d673de4515e1d153457`.

## Scoped Phase 7 outcome decisions

### mypy removed (Outcome B)

Static typing enforcement was dropped rather than adopted project-wide.
Running mypy with `disallow_untyped_defs` against the Phase 7 measured tree
surfaced 69 errors, disproportionate to the value of introducing and
maintaining a new type-checking gate this late in the refactor. mypy and the
`typecheck` Make target were removed. Ruff enforces a production McCabe
threshold of 20; the Phase 7 measured tree had zero production `C901`
violations.

### Worker extraction skipped (optional)

Extracting a dedicated background-worker process/module was scoped as optional
in the target architecture and was skipped. A separate background-worker
process was not introduced. For this local single-process application, task
supervision remains in-process and a separate deployment boundary would add
operational complexity without architectural benefit. Internal application
decomposition is independent of that decision.

## Acceptance evidence

Pre-merge automated gates (`make finalization-check`: format, lint,
`validate-docs`, `test`, `probe-console`, `smoke-compose-api`) ran on the
Phase 7 branch before merge.

The durable repository closure record, captured by the annotated Git tag
`refactor-complete`, requires all of the following on the accepted `main`
commit:

1. green Release Gate (`make finalization-check`);
2. `make smoke-local-llm` against a real OpenAI-compatible model on that same
   commit;
3. an annotated `refactor-complete` tag whose peeled target resolves to that
   commit.

If the configured real model is unavailable or the smoke fails, the closure PR
may remain merged, but repository closure is incomplete and the tag must not be
created.

## Notes

- Backend physical LOC fell from 22,919 to 10,637 (~53.6%), meeting the ≥40%
  backend reduction target.
- Tracked authored text fell from 64,895 to 40,353 (~37.8%), within the
  approximate 35–45% repository target. Transitional plans were removed; the
  remaining authored mass reflects retained target-architecture tests,
  API/client coverage, and canonical documentation.
- Phase 6 authored-text and file-count figures exclude generated
  `requirements.txt` / `requirements-dev.txt` under the Jung layout (layout-
  independent generated-path handling).
- Older Phase 1 tables in Git history used a different measurement
  implementation and are not directly comparable to this table.
