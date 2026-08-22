"""Phase-local direct patient benchmark for Phase 8D."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from evals.simulation.audit import (
    sanitize_patient_extra_body_provenance,
    write_run_json,
)
from evals.simulation.patient import (
    PatientSimulator,
    PatientTurnContext,
    VisibleTurn,
    resolve_patient_endpoint,
)
from evals.simulation.scenarios import get_scenario
from jung.config import load_settings
from jung.diagnostics import sanitize_url

ContextId = Literal["A", "B", "C", "D"]
ArmId = Literal["P0", "P1", "P2"]

BALANCED_P0_P1_SEQUENCE: tuple[tuple[ArmId, ContextId], ...] = (
    ("P0", "A"),
    ("P1", "A"),
    ("P0", "B"),
    ("P1", "B"),
    ("P1", "C"),
    ("P0", "C"),
    ("P1", "D"),
    ("P0", "D"),
)

P2_CONTEXT_ORDER: tuple[ContextId, ...] = ("A", "B", "C", "D")


@dataclass(frozen=True, slots=True)
class SessionTransport:
    base_url: str
    model: str
    api_key: str
    default_headers: dict[str, str] | None
    extra_body: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ContextCallResult:
    arm: ArmId
    context_id: ContextId
    latency_seconds: float
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    output_chars: int
    output_text: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "arm": self.arm,
            "context_id": self.context_id,
            "latency_seconds": self.latency_seconds,
            "finish_reason": self.finish_reason,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "output_chars": self.output_chars,
            "output_text": self.output_text,
        }
        if self.error is not None:
            payload["error"] = self.error
        return payload


def session_transport_from_settings() -> SessionTransport:
    settings = load_settings()
    return SessionTransport(
        base_url=settings.llm_base_url,
        model=settings.model_name,
        api_key=settings.llm_api_key or "",
        default_headers=(
            dict(settings.llm_default_headers)
            if settings.llm_default_headers is not None
            else None
        ),
        extra_body=(
            dict(settings.llm_extra_body)
            if settings.llm_extra_body is not None
            else None
        ),
    )


def build_p1_patient_extra_body(
    session_extra_body: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Structural copy of session extra_body with thinking controls disabled."""
    base = dict(session_extra_body) if session_extra_body is not None else {}
    copied = json.loads(json.dumps(base))
    if not isinstance(copied, dict):
        copied = {}
    kwargs = copied.get("chat_template_kwargs")
    if isinstance(kwargs, dict):
        nested = dict(kwargs)
        nested["enable_thinking"] = False
        copied["chat_template_kwargs"] = nested
    elif "chat_template_kwargs" not in copied:
        copied["chat_template_kwargs"] = {"enable_thinking": False}
    else:
        copied["chat_template_kwargs"] = {"enable_thinking": False}
    return copied


def _sanitize_p2_candidate(
    p2_candidate: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if p2_candidate is None:
        return None
    sanitized: dict[str, Any] = {}
    for key, value in p2_candidate.items():
        if key == "patient_base_url" and isinstance(value, str):
            sanitized[key] = sanitize_url(value)
        elif key == "patient_extra_body":
            sanitized[key] = sanitize_patient_extra_body_provenance(value)
        else:
            sanitized[key] = value
    return sanitized


def social_anxiety_contexts() -> dict[ContextId, PatientTurnContext]:
    scenario = get_scenario("social_anxiety")
    return {
        "A": PatientTurnContext(
            scenario=scenario,
            phase="intake",
            session_number=0,
            turn_number=1,
            visible_history=(),
        ),
        "B": PatientTurnContext(
            scenario=scenario,
            phase="intake",
            session_number=0,
            turn_number=2,
            visible_history=(
                VisibleTurn("patient", "I get really nervous before seminars."),
                VisibleTurn(
                    "therapist",
                    "Tell me more about what happens in your body beforehand.",
                ),
            ),
        ),
        "C": PatientTurnContext(
            scenario=scenario,
            phase="therapy",
            session_number=1,
            turn_number=1,
            visible_history=(
                VisibleTurn("patient", "Last week I almost skipped the group meeting."),
                VisibleTurn("therapist", "What made you decide to go anyway?"),
            ),
        ),
        "D": PatientTurnContext(
            scenario=scenario,
            phase="therapy",
            session_number=2,
            turn_number=3,
            visible_history=(
                VisibleTurn(
                    "patient",
                    "I've been replaying a comment I made in class over and over.",
                ),
                VisibleTurn("therapist", "What felt most embarrassing about it?"),
                VisibleTurn(
                    "patient",
                    "I think everyone noticed I was blushing, and I wanted to leave.",
                ),
                VisibleTurn(
                    "therapist",
                    "When that happens, what do you usually tell yourself afterward?",
                ),
            ),
        ),
    }


def arm_endpoint_config(
    arm: ArmId,
    session: SessionTransport,
    *,
    p2_base_url: str | None = None,
    p2_model: str | None = None,
    p2_extra_body: dict[str, Any] | None = None,
):
    if arm == "P0":
        return resolve_patient_endpoint(
            session_base_url=session.base_url,
            session_model=session.model,
            session_api_key=session.api_key,
            session_default_headers=session.default_headers,
            session_extra_body=session.extra_body,
            patient_extra_body=None,
        )
    if arm == "P1":
        return resolve_patient_endpoint(
            session_base_url=session.base_url,
            session_model=session.model,
            session_api_key=session.api_key,
            session_default_headers=session.default_headers,
            session_extra_body=session.extra_body,
            patient_extra_body=build_p1_patient_extra_body(session.extra_body),
        )
    if p2_base_url is None:
        raise ValueError("P2 requires an explicit patient base URL")
    return resolve_patient_endpoint(
        session_base_url=session.base_url,
        session_model=session.model,
        session_api_key=session.api_key,
        session_default_headers=session.default_headers,
        session_extra_body=session.extra_body,
        patient_base_url=p2_base_url,
        patient_model=p2_model,
        patient_extra_body=p2_extra_body,
    )


async def _run_one_call(
    simulator: PatientSimulator,
    *,
    arm: ArmId,
    context_id: ContextId,
    context: PatientTurnContext,
) -> ContextCallResult:
    started = time.perf_counter()
    try:
        evidence = await simulator.generate(context)
    except Exception as exc:
        return ContextCallResult(
            arm=arm,
            context_id=context_id,
            latency_seconds=time.perf_counter() - started,
            finish_reason=None,
            prompt_tokens=None,
            completion_tokens=None,
            output_chars=0,
            output_text="",
            error=f"{type(exc).__name__}: {exc}",
        )
    return ContextCallResult(
        arm=arm,
        context_id=context_id,
        latency_seconds=evidence.latency_seconds,
        finish_reason=evidence.finish_reason,
        prompt_tokens=evidence.prompt_tokens,
        completion_tokens=evidence.completion_tokens,
        output_chars=len(evidence.submitted_text),
        output_text=evidence.submitted_text,
    )


def _arm_totals(calls: Sequence[ContextCallResult]) -> dict[str, Any]:
    latencies = [call.latency_seconds for call in calls if call.error is None]
    return {
        "calls": len(calls),
        "latency_seconds_total": sum(latencies),
        "failures": sum(1 for call in calls if call.error is not None),
    }


def _allocate_run_directory(base: Path | None = None) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
        candidate = base / f"run-{stamp}"
    else:
        candidate = Path("logs") / "phase8d" / f"run-{stamp}"
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def build_benchmark_payload(
    *,
    invocation: str,
    session: SessionTransport,
    calls: Sequence[ContextCallResult],
    p2_candidate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    by_arm: dict[str, list[ContextCallResult]] = {"P0": [], "P1": [], "P2": []}
    for call in calls:
        by_arm[call.arm].append(call)
    return {
        "schema": "phase8d-patient-benchmark-v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "invocation": invocation,
        "session": {
            "base_url": sanitize_url(session.base_url),
            "model": session.model,
            "extra_body": sanitize_patient_extra_body_provenance(session.extra_body),
        },
        "p2_candidate": _sanitize_p2_candidate(p2_candidate),
        "calls": [call.to_dict() for call in calls],
        "arm_totals": {
            arm: _arm_totals(items) for arm, items in by_arm.items() if items
        },
    }


async def run_p0_p1_benchmark(
    *,
    p2_candidate_label: str | None = None,
    output_dir: Path | None = None,
    generate=None,
) -> tuple[Path, list[ContextCallResult]]:
    session = session_transport_from_settings()
    contexts = social_anxiety_contexts()
    results: list[ContextCallResult] = []
    simulators: dict[ArmId, PatientSimulator] = {}

    async def _generate(arm: ArmId, context_id: ContextId) -> ContextCallResult:
        if arm not in simulators:
            simulators[arm] = PatientSimulator(arm_endpoint_config(arm, session))
        context = contexts[context_id]
        if generate is not None:
            return await generate(arm, context_id, context)
        return await _run_one_call(
            simulators[arm],
            arm=arm,
            context_id=context_id,
            context=context,
        )

    for arm, context_id in BALANCED_P0_P1_SEQUENCE:
        results.append(await _generate(arm, context_id))

    for simulator in simulators.values():
        await simulator.aclose()

    run_dir = _allocate_run_directory(output_dir)
    candidate_payload = (
        None if p2_candidate_label is None else {"model": p2_candidate_label}
    )
    payload = build_benchmark_payload(
        invocation="p0-p1",
        session=session,
        calls=results,
        p2_candidate=candidate_payload,
    )
    write_run_json(run_dir / "benchmark.json", payload)
    return run_dir, results


async def run_p2_benchmark(
    *,
    patient_base_url: str,
    patient_model: str | None = None,
    patient_extra_body: dict[str, Any] | None = None,
    output_dir: Path | None = None,
    generate=None,
) -> tuple[Path, list[ContextCallResult]]:
    session = session_transport_from_settings()
    contexts = social_anxiety_contexts()
    simulator = PatientSimulator(
        arm_endpoint_config(
            "P2",
            session,
            p2_base_url=patient_base_url,
            p2_model=patient_model,
            p2_extra_body=patient_extra_body,
        )
    )
    results: list[ContextCallResult] = []
    try:
        for context_id in P2_CONTEXT_ORDER:
            context = contexts[context_id]
            if generate is not None:
                results.append(await generate("P2", context_id, context))
            else:
                results.append(
                    await _run_one_call(
                        simulator,
                        arm="P2",
                        context_id=context_id,
                        context=context,
                    )
                )
    finally:
        await simulator.aclose()

    run_dir = _allocate_run_directory(output_dir)
    payload = build_benchmark_payload(
        invocation="p2",
        session=session,
        calls=results,
        p2_candidate={
            "patient_base_url": patient_base_url,
            "patient_model": patient_model,
            "patient_extra_body": patient_extra_body,
        },
    )
    write_run_json(run_dir / "benchmark.json", payload)
    return run_dir, results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.phase8d.patient_benchmark",
        description="Phase-local synthetic patient cost benchmark.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p0_p1 = sub.add_parser("run-p0-p1", help="Run balanced P0/P1 benchmark (8 calls)")
    p0_p1.add_argument(
        "--p2-candidate",
        default=None,
        help="Optional P2 candidate label named before P0/P1 (e.g. gemma4-e4b)",
    )

    p2 = sub.add_parser("run-p2", help="Run P2-only benchmark (4 calls)")
    p2.add_argument("--patient-base-url", required=True)
    p2.add_argument("--patient-model", default=None)
    p2.add_argument(
        "--patient-extra-body-json",
        default=None,
        help="Optional JSON object for P2 patient extra_body",
    )
    return parser


async def _async_main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run-p0-p1":
        run_dir, _ = await run_p0_p1_benchmark(
            p2_candidate_label=args.p2_candidate,
        )
        print(f"wrote {run_dir / 'benchmark.json'}")
        return 0
    extra_body = None
    if args.patient_extra_body_json is not None:
        extra_body = json.loads(args.patient_extra_body_json)
        if not isinstance(extra_body, dict):
            raise SystemExit("patient extra body must be a JSON object")
    run_dir, _ = await run_p2_benchmark(
        patient_base_url=args.patient_base_url,
        patient_model=args.patient_model,
        patient_extra_body=extra_body,
    )
    print(f"wrote {run_dir / 'benchmark.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
