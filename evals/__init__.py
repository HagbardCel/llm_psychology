"""Opt-in real-model evaluations for the Jung runtime.

Two independent surfaces live here:

- `test_hard_invariants.py`: contractual oracles run by `make evals`.
- `behavioral_report.py`: diagnostic report generator run by `make eval-report`.

Nothing in this package reads environment variables or constructs clients at
import time, so collecting it without a local model configured is safe.
"""
