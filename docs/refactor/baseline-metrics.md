---
owner: engineering
status: proposed
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Refactor baseline measurement procedure
---

# Baseline Metrics

Source commit: `1693b01907bac827c3861374ea581e6cb629d3c7` (main, 2026-07-11). Measured in the API container with `python scripts/measure_codebase.py --format markdown`.

| Metric | Baseline |
|---|---:|
| Production Python files | 131 |
| Production Python physical LOC | 22,640 |
| Production Python code LOC | 19,223 |
| Test Python files | 80 |
| Test Python physical LOC | 22,160 |
| Test Python code LOC | 17,978 |
| Trio-importing production modules | 24 |
| Service-container importing modules | 11 |
| Pydantic model candidates | 9 |

The Phase 2 baseline refresh must run against the Phase 1 merge commit and record direct dependencies as runtime, development, test, transitive-only, or scheduled for removal. Naming metrics remain diagnostic only and never architecture gates.
