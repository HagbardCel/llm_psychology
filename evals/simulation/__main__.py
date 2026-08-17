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
from evals.simulation.suite import (
    SimulationSuiteConfig,
    SimulationSuiteResult,
    exit_code_for_suite,
    run_simulation_suite,
    validate_runs_and_concurrency,
)
from jung.styles import load_styles


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
    style_choices = ("auto", *load_styles())
    parser = argparse.ArgumentParser(
        prog="python -m evals.simulation",
        description="Longitudinal whole-product real-model journey audit.",
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
        "--style",
        choices=style_choices,
        default="auto",
        help=(
            "Therapy style after assessment: auto picks the highest-scored "
            "recommendation; an explicit id selects that style via the real "
            "style-selection API (assessment is never bypassed)"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Exact output directory; must not already exist. With --runs 1 "
            "this is the journey directory. With --runs greater than 1 this "
            "is the suite directory (children under <dir>/runs/run-001, ...)."
        ),
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
    parser.add_argument(
        "--runs",
        type=_positive_int,
        default=1,
        help="Independent replica count (default 1). Values >1 use a suite.",
    )
    parser.add_argument(
        "--concurrency",
        type=_positive_int,
        default=1,
        help=(
            "Maximum simultaneously active replicas (default 1). Must be "
            "<= --runs. Does not parallelize turns inside a journey."
        ),
    )
    return parser


def exit_code_for_result(result: SimulationResult) -> int:
    return 0 if result.status == "complete" else 1


def simulation_config_from_args(args: argparse.Namespace) -> SimulationConfig:
    requested_style = None if args.style == "auto" else args.style
    return SimulationConfig(
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
        requested_style=requested_style,
    )


def suite_config_from_args(args: argparse.Namespace) -> SimulationSuiteConfig:
    return SimulationSuiteConfig(
        scenario_id=args.scenario,
        sessions=args.sessions,
        turns_per_session=args.turns_per_session,
        runs=args.runs,
        concurrency=args.concurrency,
        max_intake_turns=args.max_intake_turns,
        requested_style=args.style,
        output_dir=args.output_dir,
        patient_model=args.patient_model,
        patient_base_url=args.patient_base_url,
        patient_timeout=args.patient_timeout,
        workflow_timeout=args.workflow_timeout,
        overall_timeout=args.overall_timeout,
        patient_history_chars=args.patient_history_chars,
        executable=sys.executable,
    )


def _print_single_result(result: SimulationResult) -> None:
    if result.status == "complete":
        print(f"simulation complete: {result.run_dir}")
        return
    print(
        f"simulation failed: {result.error_code}: {result.error_message} "
        f"(artifacts: {result.run_dir})",
        file=sys.stderr,
    )


def _print_suite_result(result: SimulationSuiteResult) -> None:
    if result.status == "complete":
        print(f"simulation suite complete: {result.suite_dir}")
        return
    detail = result.error_code or result.status
    message = result.error_message or ""
    extra = f": {message}" if message else ""
    print(
        f"simulation suite {result.status}: {detail}{extra} "
        f"(artifacts: {result.suite_dir})",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_runs_and_concurrency(args.runs, args.concurrency)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        if args.runs == 1:
            result = asyncio.run(run_simulation(simulation_config_from_args(args)))
            _print_single_result(result)
            return exit_code_for_result(result)
        suite_result = asyncio.run(run_simulation_suite(suite_config_from_args(args)))
        _print_suite_result(suite_result)
        return exit_code_for_suite(suite_result)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
