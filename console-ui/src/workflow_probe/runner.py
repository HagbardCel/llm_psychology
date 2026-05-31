"""Run the one supported local full-stack workflow probe."""

from __future__ import annotations

import argparse
from functools import partial
import logging
import os
from pathlib import Path
import sys
import uuid

import httpx
import trio

from ..console_client import ConsoleClient
from ..event_sink import CompositeConsoleEventSink
from ..llm_user_simulator import LocalLLMUserSimulatorError
from ..output import ConsoleOutput, setup_logging
from .assertions import run_assertions
from .db_snapshot import session_enrichment_complete, snapshot_and_extract
from .local_user import LocalUser
from .recorder import ProbeRecorder
from .scenario import load_scenario


async def run_probe(args: argparse.Namespace) -> int:
    if args.check_local_llm:
        if os.getenv("PROBE_DETERMINISTIC_USER", "").lower() != "true":
            await check_local_llm()
        print("PASS: local OpenAI-compatible endpoint is available")
        return 0

    scenario = load_scenario(args.scenario)
    recorder = ProbeRecorder(args.output_dir, scenario["id"])
    recorder.debug_raw_polls = bool(scenario.get("debug_raw_poll_events", False))
    user_id = f"console_probe_{uuid.uuid4().hex}"
    recorder.user_id = user_id
    setup_logging(str(Path(args.output_dir) / "console.log"))
    output = ConsoleOutput(logging.getLogger("console_ui.probe"))
    status = "FAIL"
    exit_code = 1
    try:
        await check_backend(args.backend_url)
        if os.getenv("PROBE_DETERMINISTIC_USER", "").lower() != "true":
            await check_local_llm()
        local_user = LocalUser(scenario, recorder)
        sink = CompositeConsoleEventSink(recorder, local_user)
        client = ConsoleClient(
            backend_url=args.backend_url,
            websocket_url=args.websocket_url,
            websocket_origin=args.websocket_origin,
            user_id=user_id,
            output=output,
            input_provider=local_user,
            event_sink=sink,
            api_timeout_seconds=float(
                scenario.get("limits", {}).get("api_timeout_seconds", 180)
            ),
        )
        timeout = float(scenario.get("limits", {}).get("overall_timeout_seconds", 420))
        with trio.fail_after(timeout):
            await client.run()
        if any(event["kind"] == "session_ended" for event in recorder.events):
            await wait_for_plan_update(args.backend_url, user_id, scenario, recorder)
            await wait_for_session_enrichment(args.db_path, user_id, scenario, recorder)
        recorder.created_rows = await trio.to_thread.run_sync(
            partial(
                snapshot_and_extract,
                args.db_path,
                args.output_dir,
                user_id,
                recorder.observed_session_ids(),
            )
        )
        status = "PASS" if await run_assertions(recorder, scenario) else "FAIL"
        exit_code = 0 if status == "PASS" else 1
    except LocalLLMUserSimulatorError as exc:
        await recorder.record("error", message="Local user simulator failed", reason=exc.reason, data=exc.metadata)
        exit_code = 3
    except trio.TooSlowError:
        await recorder.record("error", message="Workflow probe watchdog timeout")
        status = "TIMEOUT"
        exit_code = 5
    except Exception as exc:
        await recorder.record("error", message="Workflow probe failed", data=repr(exc))
        exit_code = 2
    finally:
        if not recorder.created_rows:
            recorder.created_rows = await trio.to_thread.run_sync(
                partial(
                    snapshot_and_extract,
                    args.db_path,
                    args.output_dir,
                    user_id,
                    recorder.observed_session_ids(),
                )
            )
        await recorder.write_artifacts(status, scenario)
    print(f"{status}: local workflow probe")
    print(f"Artifacts: {args.output_dir}")
    return exit_code


async def check_backend(base_url: str) -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{base_url.rstrip('/')}/health")
        response.raise_for_status()


async def check_local_llm() -> None:
    base_url = os.getenv("LLM_BASE_URL")
    model = os.getenv("MODEL_NAME")
    if not base_url or not model:
        raise RuntimeError("LLM_BASE_URL and MODEL_NAME must be configured in .env")
    headers = {}
    if api_key := os.getenv("LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
        response.raise_for_status()


async def wait_for_plan_update(base_url: str, user_id: str, scenario: dict, recorder: ProbeRecorder) -> None:
    timeout = float(scenario.get("limits", {}).get("plan_update_timeout_seconds", 120))
    with trio.move_on_after(timeout) as scope:
        while True:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{base_url.rstrip('/')}/api/user/status",
                    params={"user_id": user_id},
                )
                response.raise_for_status()
                state = response.json().get("workflow_state")
            await recorder.record("post_session_state", workflow_state=state)
            if state == "plan_update_complete":
                return
            if state == "plan_update_failed":
                raise RuntimeError("Post-session plan update failed")
            await trio.sleep(2)
    if scope.cancelled_caught:
        raise RuntimeError("Timed out waiting for post-session plan update")


async def wait_for_session_enrichment(
    db_path: str, user_id: str, scenario: dict, recorder: ProbeRecorder
) -> None:
    """Require asynchronous Tier 2 enrichment before declaring probe success."""
    timeout = float(scenario.get("limits", {}).get("enrichment_timeout_seconds", 120))
    session_ids = recorder.observed_session_ids()
    with trio.move_on_after(timeout) as scope:
        while True:
            complete = await trio.to_thread.run_sync(
                partial(session_enrichment_complete, db_path, user_id, session_ids)
            )
            await recorder.record("post_session_enrichment", complete=complete)
            if complete:
                return
            await trio.sleep(2)
    if scope.cancelled_caught:
        raise RuntimeError("Timed out waiting for post-session enrichment")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="/app/scenarios/workflow-probes/first_session_smoke.json")
    parser.add_argument("--output-dir", default="/app/logs/workflow-probes/manual")
    parser.add_argument("--db-path", default=os.getenv("DATABASE_PATH", "/app/data/runtime.sqlite"))
    parser.add_argument("--backend-url", default=os.getenv("BACKEND_URL", "http://api-probe:8000"))
    parser.add_argument("--websocket-url", default=os.getenv("WEBSOCKET_URL", "http://api-probe:8000"))
    parser.add_argument("--websocket-origin", default=os.getenv("WEBSOCKET_ORIGIN", "http://localhost:5173"))
    parser.add_argument("--check-local-llm", action="store_true")
    return parser


def cli() -> int:
    return trio.run(run_probe, build_parser().parse_args())


if __name__ == "__main__":
    sys.exit(cli())
