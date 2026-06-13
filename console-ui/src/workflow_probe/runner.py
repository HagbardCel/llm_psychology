"""Run the one supported local full-stack workflow probe."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from functools import partial
from pathlib import Path

import httpx
import trio

from ..console_client import ConsoleClient
from ..event_sink import CompositeConsoleEventSink
from ..llm_user_simulator import LocalLLMUserSimulatorError
from ..output import ConsoleOutput, setup_logging
from .assertions import run_assertions
from .db_snapshot import snapshot_and_extract
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
        post_session_id = _post_session_update_session_id(recorder.events)
        if post_session_id:
            await wait_for_post_session_update(
                args.backend_url,
                user_id,
                post_session_id,
                scenario,
                recorder,
            )
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
        await recorder.record(
            "error",
            message="Local user simulator failed",
            reason=exc.reason,
            data=exc.metadata,
        )
        exit_code = 3
    except trio.TooSlowError:
        await recorder.record("error", message="Workflow probe watchdog timeout")
        status = "TIMEOUT"
        exit_code = 5
    except Exception as exc:
        await recorder.record(
            "error",
            message="Workflow probe failed",
            exception=repr(exc),
        )
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
    failure_summary_path = Path(args.output_dir) / "failure_summary.md"
    if status != "PASS" and failure_summary_path.exists():
        print(failure_summary_path.read_text(encoding="utf-8").strip())
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


async def wait_for_post_session_update(
    base_url: str,
    user_id: str,
    session_id: str,
    scenario: dict,
    recorder: ProbeRecorder,
) -> None:
    timeout = float(scenario.get("limits", {}).get("plan_update_timeout_seconds", 120))
    job_id = f"post_session_update:{session_id}"
    last_status: dict | None = None
    with trio.move_on_after(timeout) as scope:
        while True:
            websocket_status = _latest_job_status(recorder.events, job_id)
            if websocket_status:
                last_status = websocket_status
                if websocket_status.get("status") == "complete":
                    return
                if websocket_status.get("status") == "failed":
                    raise RuntimeError(
                        f"Post-session update failed: {websocket_status}"
                    )
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{base_url.rstrip('/')}/api/jobs/{job_id}",
                    params={"user_id": user_id},
                )
                response.raise_for_status()
                status = response.json()
            last_status = status
            await recorder.record(
                "post_session_job_status",
                job_id=job_id,
                job_type=status.get("job_type"),
                status=status.get("status"),
                current_step=status.get("current_step"),
                workflow_state=status.get("workflow_state"),
                session_id=session_id,
                delivery_source="http_fallback",
                data=status,
            )
            if status.get("status") == "complete":
                return
            if status.get("status") == "failed":
                raise RuntimeError(f"Post-session update failed: {status}")
            await trio.sleep(2)
    if scope.cancelled_caught:
        raise RuntimeError(
            f"Timed out waiting for post-session update: {last_status}"
        )


def _needs_post_session_follow_up(events: list[dict]) -> bool:
    """Post-session jobs only run after therapy sessions enter plan update."""
    for event in events:
        if event.get("kind") != "session_ended":
            continue
        data = event.get("data")
        if (
            isinstance(data, dict)
            and data.get("workflow_state") == "plan_update_in_progress"
        ):
            return True
    return False


def _post_session_update_session_id(events: list[dict]) -> str | None:
    for index, event in enumerate(events):
        if event.get("kind") != "session_ended":
            continue
        data = event.get("data")
        if (
            isinstance(data, dict)
            and data.get("workflow_state") == "plan_update_in_progress"
        ):
            if data.get("session_id"):
                return data.get("session_id")
            for previous in reversed(events[:index]):
                session_id = previous.get("session_id")
                if session_id:
                    return session_id
                previous_data = previous.get("data")
                if isinstance(previous_data, dict) and previous_data.get("session_id"):
                    return previous_data.get("session_id")
    return None


def _latest_job_status(events: list[dict], job_id: str) -> dict | None:
    for event in reversed(events):
        if event.get("kind") != "job_status" or event.get("job_id") != job_id:
            continue
        data = event.get("data")
        return data if isinstance(data, dict) else None
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        default="/app/scenarios/workflow-probes/first_session_smoke.json",
    )
    parser.add_argument("--output-dir", default="/app/logs/workflow-probes/manual")
    parser.add_argument(
        "--db-path",
        default=os.getenv("DATABASE_PATH", "/app/data/runtime.sqlite"),
    )
    parser.add_argument(
        "--backend-url", default=os.getenv("BACKEND_URL", "http://api-probe:8000")
    )
    parser.add_argument(
        "--websocket-url", default=os.getenv("WEBSOCKET_URL", "http://api-probe:8000")
    )
    parser.add_argument(
        "--websocket-origin", default=os.getenv("WEBSOCKET_ORIGIN", "http://localhost")
    )
    parser.add_argument("--check-local-llm", action="store_true")
    return parser


def cli() -> int:
    return trio.run(run_probe, build_parser().parse_args())


if __name__ == "__main__":
    sys.exit(cli())
