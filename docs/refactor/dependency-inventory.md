---
owner: engineering
status: accepted
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Target dependency treatment during the architecture refactor
---

# Dependency Inventory

The authoritative dependency classification table lives in [Baseline Metrics](baseline-metrics.md#dependency-classification). This file remains as a stable link target for validators and roadmap references.

Direct dependencies are the non-comment, non-include entries of `requirements.in` and `requirements-dev.in`; locked transitives are deliberately not repeated here.
