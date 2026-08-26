# Phase 8C — closed experiment

Phase 8C measured whether overlapping independent `simulate-local-llm`
journeys reduced wall-clock time against a serial local backend.

**Outcome:** no demonstrated present value for maintaining multi-journey
orchestration in Jung. The suite runner (`--runs` / simulation `--concurrency`)
was removed during Phase 8 lean closure.

Frozen measurements and protocol history:
[`OUTCOME.md`](OUTCOME.md).

Do not rerun C1/C2/C4 or reintroduce suite concurrency without a new,
explicitly justified engineering requirement.
