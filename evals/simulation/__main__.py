"""CLI entry for ``python -m evals.simulation``."""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from pathlib import Path

from evals.simulation.patient import (
    PATIENT_HISTORY_MAX_CHARS,
    PATIENT_TIMEOUT_SECONDS,
    WORKFLOW_TIMEOUT_SECONDS,
)
from evals.simulation.runner import SimulationConfig, SimulationResult, run_simulation
from evals.simulation.scenarios import get_scenario, list_scenario_ids


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.simulation",
        description="Longitudinal whole-product real-model journey audit (Phase 7F).",
    )
    parser.add_argument(
        "--scenario",
        required=True,
        choices=list_scenario_ids(),
        help="Synthetic patient scenario id",
    )
    parser.add_argument("--sessions", type=_positive_int, required=True)
    parser.add_argument("--turns-per-session", type=_positive_int, required=True)
    parser.add_argument("--max-intake-turns", type=_positive_int, default=12)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Exact run directory; must not already exist",
    )
    parser.add_argument("--patient-model", default=None)
    parser.add_argument("--patient-base-url", default=None)
    parser.add_argument(
        "--patient-timeout",
        type=_positive_float,
        default=PATIENT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--workflow-timeout",
        type=_positive_float,
        default=WORKFLOW_TIMEOUT_SECONDS,
    )
    parser.add_argument("--overall-timeout", type=_positive_float, default=None)
    parser.add_argument(
        "--patient-history-chars",
        type=_positive_int,
        default=PATIENT_HISTORY_MAX_CHARS,
    )
    return parser


def exit_code_for_result(result: SimulationResult) -> int:
    return 0 if result.status == "complete" else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = SimulationConfig(
        scenario=get_scenario(args.scenario),
        sessions=args.sessions,
        turns_per_session=args.turns_per_session,
        max_intake_turns=args.max_intake_turns,
        output_dir=args.output_dir,
        patient_base_url=args.patient_base_url,
        patient_model=args.patient_model,
        patient_timeout=args.patient_timeout,
        workflow_timeout=args.workflow_timeout,
        overall_timeout=args.overall_timeout,
        patient_history_chars=args.patient_history_chars,
        require_provider_trace=True,
    )
    result = asyncio.run(run_simulation(config))
    if result.status == "complete":
        print(f"simulation complete: {result.run_dir}")
    else:
        print(
            f"simulation failed: {result.error_code}: {result.error_message} "
            f"(artifacts: {result.run_dir})",
            file=sys.stderr,
        )
    return exit_code_for_result(result)


if __name__ == "__main__":
    raise SystemExit(main())
