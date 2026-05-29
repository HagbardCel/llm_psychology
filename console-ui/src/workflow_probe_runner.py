"""Run console workflow probes with scripted or local-LLM simulated users."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import trio

from .console_client import ConsoleClient
from .input_providers import LLMSimulatedUserProvider, ScriptedInputProvider
from .llm_user_simulator import LocalLLMUserSimulator, LocalLLMUserSimulatorError
from .output import ConsoleOutput, setup_logging
from .protocol_recorder import ProtocolRecorder, env_trace_prompts_enabled


EXIT_ASSERTION_FAILURE = 1
EXIT_CONFIG_ERROR = 2
EXIT_SIMULATOR_UNAVAILABLE = 3
EXIT_BACKEND_UNAVAILABLE = 4
EXIT_TIMEOUT = 5
EXIT_UNEXPECTED = 6


async def run_probe(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    scenario_id = scenario.get("id") or Path(args.scenario).stem
    output_dir = Path(args.output_dir)
    log_path = args.console_log_path or str(output_dir.parent / "console-ui-probe.log")
    setup_logging(log_path)
    output = ConsoleOutput(logging.getLogger("console_ui.probe"))
    recorder = ProtocolRecorder(
        output_dir=output_dir,
        scenario_id=scenario_id,
        redact_model_context=not env_trace_prompts_enabled(),
    )

    try:
        await check_backend(args.backend_url)
    except Exception as exc:
        await recorder.record_error("Backend unavailable", str(exc))
        await recorder.write_summary("FAIL", scenario)
        print(f"FAIL: backend unavailable: {exc}")
        print(f"See: {recorder.latest_md_path}")
        return EXIT_BACKEND_UNAVAILABLE

    try:
        provider = build_provider(args.mode, scenario, recorder)
    except Exception as exc:
        await recorder.record_error("Failed to configure input provider", str(exc))
        await recorder.write_summary("FAIL", scenario)
        print(f"FAIL: provider configuration error: {exc}")
        print(f"See: {recorder.latest_md_path}")
        return EXIT_CONFIG_ERROR

    user_id = args.user_id or scenario.get("user_id") or new_probe_user_id()
    limits = scenario.get("limits") or {}
    workflow_preferences = scenario.get("workflow_preferences") or {}
    if workflow_preferences.get("profile_selection") == "create_new":
        limits = {**limits, "profile_selection": "create_new"}
    client = ConsoleClient(
        backend_url=args.backend_url,
        websocket_url=args.websocket_url,
        websocket_origin=args.websocket_origin or args.backend_url,
        user_id=user_id,
        output=output,
        input_provider=provider,
        recorder=recorder,
        probe_limits=limits,
    )

    status = "FAIL"
    try:
        overall_timeout = float(limits.get("overall_timeout_seconds", 180))
        with trio.move_on_after(overall_timeout) as scope:
            await client.run()
        if scope.cancelled_caught:
            await recorder.record_error("Overall probe timeout")
            status = "TIMEOUT"
            return_code = EXIT_TIMEOUT
        elif _recorded_simulator_failure(recorder) is not None:
            status = "FAIL"
            return_code = EXIT_SIMULATOR_UNAVAILABLE
        else:
            passed = await run_assertions(
                recorder=recorder,
                scenario=scenario,
                backend_url=args.backend_url,
                user_id=user_id,
            )
            status = "PASS" if passed else "FAIL"
            return_code = 0 if passed else EXIT_ASSERTION_FAILURE
    except httpx.HTTPError as exc:
        await recorder.record_error("Local user simulator unavailable", str(exc))
        status = "FAIL"
        return_code = EXIT_SIMULATOR_UNAVAILABLE
    except LocalLLMUserSimulatorError as exc:
        await recorder.record_error(
            "Local user simulator failed",
            {"reason": exc.reason, **exc.metadata},
        )
        status = "FAIL"
        return_code = EXIT_SIMULATOR_UNAVAILABLE
    except Exception as exc:
        simulator_error = _find_nested_exception(exc, LocalLLMUserSimulatorError)
        if simulator_error is not None:
            await recorder.record_error(
                "Local user simulator failed",
                {"reason": simulator_error.reason, **simulator_error.metadata},
            )
            status = "FAIL"
            return_code = EXIT_SIMULATOR_UNAVAILABLE
        else:
            await recorder.record_error("Unexpected probe exception", repr(exc))
            status = "FAIL"
            return_code = EXIT_UNEXPECTED
    finally:
        await recorder.write_summary(status, scenario)

    print(f"{status}: Console workflow probe completed.")
    print(f"See: {recorder.latest_md_path}")
    print(f"Trace: {recorder.latest_jsonl_path}")
    return return_code


def load_scenario(path: str) -> dict[str, Any]:
    scenario_path = Path(path)
    with scenario_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def build_provider(
    mode: str, scenario: dict[str, Any], recorder: ProtocolRecorder
) -> ScriptedInputProvider | LLMSimulatedUserProvider:
    fallback = scenario.get(
        "fallback_response",
        "I'm feeling anxious about work and would like to understand it better.",
    )
    prompt_responses = scenario.get("prompt_responses") or {}
    scripted_responses = scenario.get("scripted_responses") or []

    if mode == "scripted":
        return ScriptedInputProvider(
            responses=scripted_responses,
            prompt_responses=prompt_responses,
            fallback_response=fallback,
        )
    if mode == "local-llm":
        simulator = LocalLLMUserSimulator.from_env(recorder=recorder)
        return LLMSimulatedUserProvider(
            simulator=simulator,
            scenario=scenario,
            fallback_response=fallback,
        )
    raise ValueError(f"Unsupported probe mode: {mode}")


def _recorded_simulator_failure(
    recorder: ProtocolRecorder,
) -> dict[str, Any] | None:
    for event in reversed(recorder.events):
        if (
            event.get("kind") == "error"
            and event.get("message") == "Local user simulator failed"
        ):
            data = event.get("data")
            return data if isinstance(data, dict) else {}
    return None


def _find_nested_exception(
    exc: BaseException, target_type: type[LocalLLMUserSimulatorError]
) -> LocalLLMUserSimulatorError | None:
    if isinstance(exc, target_type):
        return exc

    nested = getattr(exc, "exceptions", None)
    if not nested:
        return None

    for child in nested:
        match = _find_nested_exception(child, target_type)
        if match is not None:
            return match
    return None


async def check_backend(backend_url: str) -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{backend_url.rstrip('/')}/health")
        response.raise_for_status()


def new_probe_user_id() -> str:
    return f"console_probe_{uuid.uuid4().hex}"


async def run_assertions(
    recorder: ProtocolRecorder,
    scenario: dict[str, Any],
    backend_url: str,
    user_id: str,
) -> bool:
    criteria = scenario.get("success_criteria") or {}
    passed = True

    async def assert_event(
        name: str, condition: bool, detail: str | None = None
    ) -> None:
        nonlocal passed
        passed = passed and condition
        await recorder.record_assertion(name, condition, detail)

    await assert_event(
        "no_ws_errors",
        not criteria.get("require_no_ws_errors", True) or not recorder.has_ws_error(),
    )
    await assert_event(
        "session_started",
        recorder.count_events("ws_event", type="session_started") >= 1,
    )
    if criteria.get("require_profile_created"):
        await assert_event(
            "profile_created",
            recorder.count_events("profile_created") >= 1,
        )
    if criteria.get("require_therapy_style_selected"):
        await assert_event(
            "therapy_style_selected",
            recorder.count_events("therapy_style_selected") >= 1,
        )
    await assert_event(
        "min_user_messages",
        recorder.count_events("user_input", prompt_kind="chat")
        >= int(criteria.get("require_min_user_messages", 1)),
    )
    await assert_event(
        "min_assistant_messages",
        recorder.count_events("assistant_response")
        >= int(criteria.get("require_min_assistant_messages", 1)),
    )

    required_actions = criteria.get("require_workflow_actions") or []
    actions = set(recorder.workflow_actions())
    for action in required_actions:
        await assert_event(f"workflow_action_{action}", action in actions)

    if min_unique := criteria.get("require_unique_user_messages"):
        await assert_event(
            "unique_user_messages",
            len(set(_chat_user_messages(recorder))) >= int(min_unique),
            detail=f"unique={len(set(_chat_user_messages(recorder)))}",
        )

    if min_unique := criteria.get("require_assistant_response_variation"):
        await assert_event(
            "assistant_response_variation",
            len(set(_assistant_messages(recorder))) >= int(min_unique),
            detail=f"unique={len(set(_assistant_messages(recorder)))}",
        )

    if criteria.get("fail_on_user_sim_fallback"):
        criteria.setdefault("max_user_sim_fallback_rate", 0)

    if "max_user_sim_fallback_rate" in criteria:
        fallback_count = _fallback_count(recorder)
        chat_turns = recorder.count_events("user_input", prompt_kind="chat")
        fallback_rate = _fallback_rate(recorder)
        await assert_event(
            "user_sim_fallback_rate",
            fallback_rate <= float(criteria["max_user_sim_fallback_rate"]),
            detail=(
                f"fallbacks={fallback_count}, chat_turns={chat_turns}, "
                f"rate={fallback_rate:.2f}, "
                f"max={float(criteria['max_user_sim_fallback_rate']):.2f}"
            ),
        )

    if "max_wait_seconds_before_style_selection" in criteria:
        wait_seconds = recorder.total_wait_seconds_before("select_therapy_style")
        max_wait = float(criteria["max_wait_seconds_before_style_selection"])
        await assert_event(
            "wait_before_style_selection",
            wait_seconds <= max_wait,
            detail=f"wait_seconds={wait_seconds:.1f}, max={max_wait:.1f}",
        )

    forbidden_assistant_phrases = criteria.get("forbid_assistant_phrases") or []
    for phrase in forbidden_assistant_phrases:
        phrase_text = str(phrase)
        if not phrase_text:
            continue
        await assert_event(
            f"forbid_assistant_phrase_{phrase_text[:32]}",
            not _assistant_phrase_present(recorder, phrase_text),
            detail=f"phrase={phrase_text!r}",
        )

    forbidden = criteria.get("forbid_assistant_phrases_before_turn") or []
    for rule in forbidden:
        phrase = str(rule.get("phrase", ""))
        min_turn = int(rule.get("min_turn", 0))
        if not phrase:
            continue
        await assert_event(
            f"forbid_assistant_phrase_before_turn_{phrase[:24]}",
            not _assistant_phrase_before_turn(recorder, phrase, min_turn),
            detail=f"phrase={phrase!r}, min_turn={min_turn}",
        )

    if final_state := criteria.get("require_final_workflow_state"):
        status = await fetch_user_status(backend_url, user_id, recorder.latest_session_id())
        await recorder.record("final_user_status", data=status)
        actual_state = (
            status.get("workflow_state")
            or status.get("status")
            or recorder.latest_workflow_state()
        )
        therapy_reached = _therapy_reached(recorder)
        if final_state == "therapy_in_progress" and recorder.session_end_seen():
            final_state_passed = therapy_reached
        else:
            final_state_passed = actual_state == final_state
        await assert_event(
            "final_workflow_state",
            final_state_passed,
            detail=(
                f"expected={final_state}, actual={actual_state}, "
                f"therapy_reached={therapy_reached}, "
                f"session_end_seen={recorder.session_end_seen()}, "
                f"session_end_workflow_state={recorder.session_end_workflow_state()}, "
                f"status_error={status.get('error')}"
            ),
        )

    return passed


async def fetch_user_status(
    backend_url: str, user_id: str, session_id: str | None
) -> dict[str, Any]:
    if not session_id:
        return {"error": "No session id recorded"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{backend_url.rstrip('/')}/api/user/status",
                params={"user_id": user_id, "session_id": session_id},
            )
            if response.is_error:
                return {
                    "error": (
                        f"GET /api/user/status failed with "
                        f"{response.status_code}: {response.text[:500]}"
                    )
                }
            return response.json()
    except httpx.HTTPError as exc:
        return {"error": str(exc) or exc.__class__.__name__}


def _chat_user_messages(recorder: ProtocolRecorder) -> list[str]:
    return [
        str(event.get("text") or "")
        for event in recorder.events
        if event.get("kind") == "user_input" and event.get("prompt_kind") == "chat"
    ]


def _assistant_messages(recorder: ProtocolRecorder) -> list[str]:
    return [
        str(event.get("text") or "")
        for event in recorder.events
        if event.get("kind") == "assistant_response"
    ]


def _fallback_count(recorder: ProtocolRecorder) -> int:
    return sum(
        1
        for event in recorder.events
        if event.get("kind") == "user_sim_model_call" and event.get("fallback_used")
    )


def _fallback_rate(recorder: ProtocolRecorder) -> float:
    chat_turns = recorder.count_events("user_input", prompt_kind="chat")
    if not chat_turns:
        return 0.0
    return _fallback_count(recorder) / chat_turns


def _assistant_phrase_present(recorder: ProtocolRecorder, phrase: str) -> bool:
    phrase_lower = phrase.lower()
    return any(
        phrase_lower in str(event.get("text") or "").lower()
        for event in recorder.events
        if event.get("kind") == "assistant_response"
    )


def _therapy_reached(recorder: ProtocolRecorder) -> bool:
    actions = recorder.workflow_actions()
    return (
        "continue_therapy" in actions
        and recorder.therapy_assistant_turns_after_style_selection() >= 1
    )


def _assistant_phrase_before_turn(
    recorder: ProtocolRecorder, phrase: str, min_turn: int
) -> bool:
    chat_turns = 0
    phrase_lower = phrase.lower()
    for event in recorder.events:
        if event.get("kind") == "user_input" and event.get("prompt_kind") == "chat":
            chat_turns += 1
        if event.get("kind") != "assistant_response":
            continue
        text = str(event.get("text") or "").lower()
        if phrase_lower in text and chat_turns < min_turn:
            return True
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True)
    parser.add_argument(
        "--backend-url", default=os.getenv("BACKEND_URL", "http://localhost:8000")
    )
    parser.add_argument(
        "--websocket-url", default=os.getenv("WEBSOCKET_URL", "http://localhost:8000")
    )
    parser.add_argument("--websocket-origin", default=os.getenv("WEBSOCKET_ORIGIN"))
    parser.add_argument("--user-id", default=os.getenv("USER_ID"))
    parser.add_argument("--output-dir", default="logs/workflow-probes")
    parser.add_argument("--console-log-path")
    parser.add_argument("--mode", choices=["scripted", "local-llm"], default="scripted")
    return parser


def cli() -> int:
    return trio.run(run_probe, build_parser().parse_args())


if __name__ == "__main__":
    sys.exit(cli())
