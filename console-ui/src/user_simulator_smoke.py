"""Standalone smoke check for the local LLM simulated-user provider."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import trio

from .input_providers import InputContext
from .llm_user_simulator import LocalLLMUserSimulator, LocalLLMUserSimulatorError
from .protocol_recorder import ProtocolRecorder, env_trace_prompts_enabled


async def run_smoke(args: argparse.Namespace) -> int:
    recorder = ProtocolRecorder(
        output_dir=Path(args.output_dir),
        scenario_id="local_llm_user_simulator_smoke",
        redact_model_context=not env_trace_prompts_enabled(),
    )
    simulator = LocalLLMUserSimulator.from_env(recorder=recorder)
    context = InputContext(
        prompt=(
            "The therapist asks: What brings you here today? "
            "Respond as a plausible user in one sentence."
        ),
        default=None,
        prompt_kind="chat",
        user_id="local_llm_smoke",
        session_id=None,
        workflow_action={"required_action": "start_intake"},
        simulator_phase="You are answering intake questions.",
        pending_recommendations=None,
        transcript_tail=[],
        turn_index=0,
    )
    scenario: dict[str, Any] = {
        "id": "local_llm_user_simulator_smoke",
        "user": {"name": "Smoke Test User", "primary_language": "English"},
        "persona": {
            "presenting_problem": "work-related anxiety",
            "style": "cooperative, concise",
        },
        "workflow_preferences": {"therapy_style": "cbt"},
    }

    try:
        result = await simulator.generate_user_reply(
            scenario=scenario,
            context=context,
            fallback_response="",
        )
    except LocalLLMUserSimulatorError as exc:
        await recorder.record_error(
            "Local user simulator smoke failed",
            {"reason": exc.reason, **exc.metadata},
        )
        await recorder.record_assertion("local_llm_user_reply", False, exc.reason)
        await recorder.write_summary("FAIL", scenario)
        print(f"FAIL: local LLM user simulator returned no valid reply: {exc.reason}")
        print(f"See: {recorder.latest_md_path}")
        return 3

    text = str(result.get("text") or "")
    passed = bool(text.strip())
    await recorder.record_user_input(text, "LLMSimulatedUserProvider", context)
    await recorder.record_assertion("local_llm_user_reply", passed, text[:120])
    await recorder.write_summary("PASS" if passed else "FAIL", scenario)
    print(f"{'PASS' if passed else 'FAIL'}: local LLM user simulator smoke")
    print(f"Reply: {text}")
    print(f"See: {recorder.latest_md_path}")
    return 0 if passed else 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="logs/workflow-probes")
    return parser


def cli() -> int:
    return trio.run(run_smoke, build_parser().parse_args())


if __name__ == "__main__":
    sys.exit(cli())
