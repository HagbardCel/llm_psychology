"""Bounded all-settled orchestration of independent simulation journeys.

The parent schedules subprocesses. Each child is the existing single-run
``python -m evals.simulation`` path. Do not reuse ``bounded_ordered_map``:
that helper is fail-fast and cancels siblings.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from evals.simulation.audit import (
    allocate_suite_directory,
    git_provenance,
    write_run_json,
)
from jung.diagnostics import open_private_file

SUITE_JSON_SCHEMA_VERSION = 1
CHILD_TERMINATE_GRACE_SECONDS = 5.0

SuiteStatus = Literal["complete", "failed", "cancelled"]
ChildStatus = Literal["complete", "failed", "cancelled", "not_started"]
SpawnFn = Callable[..., Awaitable["ChildProcess"]]
OpenLogFn = Callable[..., Any]
CreateSubprocessFn = Callable[..., Awaitable[Any]]


class ChildSpawnError(Exception):
    """Raised when a child process cannot be started."""


class ChildProcess(Protocol):
    returncode: int | None

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    async def wait(self) -> int: ...


@dataclass(frozen=True, slots=True)
class SimulationSuiteConfig:
    scenario_id: str
    sessions: int
    turns_per_session: int
    runs: int
    concurrency: int
    max_intake_turns: int = 12
    requested_style: str = "auto"
    output_dir: Path | None = None
    patient_model: str | None = None
    patient_base_url: str | None = None
    patient_timeout: float = 120.0
    workflow_timeout: float = 600.0
    overall_timeout: float | None = None
    patient_history_chars: int = 40_000
    executable: str = field(default_factory=lambda: sys.executable)


@dataclass
class SimulationChildResult:
    index: int
    path: str
    stdout_log: str
    stderr_log: str
    status: ChildStatus
    exit_code: int | None = None
    child_wall_seconds: float | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class SimulationSuiteResult:
    status: SuiteStatus
    suite_dir: Path
    children: list[SimulationChildResult]
    requested_concurrency: int
    max_observed_concurrency: int
    suite_wall_seconds: float
    run_overlap_factor: float
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class SpawnedChild:
    process: Any
    stdout: Any
    stderr: Any

    @property
    def returncode(self) -> int | None:
        return self.process.returncode

    def terminate(self) -> None:
        if self.process.returncode is None:
            self.process.terminate()

    def kill(self) -> None:
        if self.process.returncode is None:
            self.process.kill()

    async def wait(self) -> int:
        try:
            return await self.process.wait()
        finally:
            close_log_handles(self.stdout, self.stderr)


def validate_runs_and_concurrency(runs: int, concurrency: int) -> None:
    if runs < 1:
        raise ValueError(f"runs must be >= 1, got {runs}")
    if concurrency < 1:
        raise ValueError(f"concurrency must be >= 1, got {concurrency}")
    if concurrency > runs:
        raise ValueError(
            f"concurrency must be <= runs, got concurrency={concurrency} runs={runs}"
        )


def child_run_label(index: int) -> str:
    return f"run-{index:03d}"


def compute_run_overlap_factor(
    child_walls: Sequence[float | None], suite_wall_seconds: float
) -> float:
    """Parent-observed process overlap, not inference parallelism."""
    spawned_total = sum(wall for wall in child_walls if wall is not None)
    if suite_wall_seconds <= 0:
        return 0.0
    return spawned_total / suite_wall_seconds


def close_log_handles(*handles: Any) -> None:
    for handle in handles:
        if handle is None:
            continue
        closer = getattr(handle, "close", None)
        if closer is None:
            continue
        try:
            if getattr(handle, "closed", False):
                continue
            closer()
        except Exception:
            pass


def build_child_argv(
    config: SimulationSuiteConfig,
    *,
    child_output_dir: Path,
) -> list[str]:
    argv = [
        config.executable,
        "-m",
        "evals.simulation",
        "--scenario",
        config.scenario_id,
        "--sessions",
        str(config.sessions),
        "--turns-per-session",
        str(config.turns_per_session),
        "--max-intake-turns",
        str(config.max_intake_turns),
        "--style",
        config.requested_style,
        "--runs",
        "1",
        "--concurrency",
        "1",
        "--output-dir",
        str(child_output_dir),
        "--patient-timeout",
        str(config.patient_timeout),
        "--workflow-timeout",
        str(config.workflow_timeout),
        "--patient-history-chars",
        str(config.patient_history_chars),
    ]
    if config.patient_model is not None:
        argv.extend(["--patient-model", config.patient_model])
    if config.patient_base_url is not None:
        argv.extend(["--patient-base-url", config.patient_base_url])
    if config.overall_timeout is not None:
        argv.extend(["--overall-timeout", str(config.overall_timeout)])
    return argv


def _child_paths(index: int) -> tuple[str, str, str]:
    label = child_run_label(index)
    return (
        f"runs/{label}",
        f"workers/{label}.stdout.log",
        f"workers/{label}.stderr.log",
    )


def _placeholder_child(index: int) -> SimulationChildResult:
    path, stdout_log, stderr_log = _child_paths(index)
    return SimulationChildResult(
        index=index,
        path=path,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        status="not_started",
    )


def _child_result(
    index: int,
    *,
    status: ChildStatus,
    exit_code: int | None = None,
    child_wall_seconds: float | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> SimulationChildResult:
    path, stdout_log, stderr_log = _child_paths(index)
    return SimulationChildResult(
        index=index,
        path=path,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        status=status,
        exit_code=exit_code,
        child_wall_seconds=child_wall_seconds,
        error_code=error_code,
        error_message=error_message,
    )


def _child_record(child: SimulationChildResult) -> dict[str, Any]:
    return {
        "index": child.index,
        "path": child.path,
        "stdout_log": child.stdout_log,
        "stderr_log": child.stderr_log,
        "exit_code": child.exit_code,
        "status": child.status,
        "child_wall_seconds": child.child_wall_seconds,
        "error_code": child.error_code,
        "error_message": child.error_message,
    }


def build_suite_payload(
    *,
    config: SimulationSuiteConfig,
    status: SuiteStatus,
    children: Sequence[SimulationChildResult],
    requested_concurrency: int,
    max_observed_concurrency: int,
    started_at: str,
    completed_at: str,
    suite_wall_seconds: float,
    git_commit: str | None,
    git_worktree_dirty: bool | None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SUITE_JSON_SCHEMA_VERSION,
        "status": status,
        "git_commit": git_commit,
        "git_worktree_dirty": git_worktree_dirty,
        "scenario": config.scenario_id,
        "requested_style": config.requested_style,
        "sessions": config.sessions,
        "turns_per_session": config.turns_per_session,
        "runs": config.runs,
        "requested_concurrency": requested_concurrency,
        "max_observed_concurrency": max_observed_concurrency,
        "started_at": started_at,
        "completed_at": completed_at,
        "suite_wall_seconds": suite_wall_seconds,
        "run_overlap_factor": compute_run_overlap_factor(
            [child.child_wall_seconds for child in children],
            suite_wall_seconds,
        ),
        "children": [_child_record(child) for child in children],
    }
    if error_code is not None:
        payload["error_code"] = error_code
    if error_message is not None:
        payload["error_message"] = error_message
    return payload


def interpret_finished_child(
    *,
    index: int,
    run_dir: Path,
    exit_code: int,
    child_wall_seconds: float,
) -> SimulationChildResult:
    base = _child_result(
        index,
        status="failed",
        exit_code=exit_code,
        child_wall_seconds=child_wall_seconds,
    )
    run_json_path = run_dir / "run.json"
    if not run_json_path.is_file():
        return replace(
            base,
            error_code="missing_run_json",
            error_message=f"missing {run_json_path}",
        )
    try:
        payload = json.loads(run_json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return replace(
            base,
            error_code="malformed_run_json",
            error_message=f"{type(exc).__name__}: {exc}",
        )
    if not isinstance(payload, Mapping):
        return replace(
            base,
            error_code="malformed_run_json",
            error_message="run.json is not a JSON object",
        )
    reported = payload.get("status")
    if exit_code != 0:
        return replace(
            base,
            error_code=str(payload.get("error_code") or "child_exit_nonzero"),
            error_message=(
                str(payload.get("error_message"))
                if payload.get("error_message") is not None
                else f"child exited {exit_code}"
            ),
        )
    if reported != "complete":
        return replace(
            base,
            error_code=str(payload.get("error_code") or "child_run_incomplete"),
            error_message=(
                str(payload.get("error_message"))
                if payload.get("error_message") is not None
                else f"run.json status={reported!r}"
            ),
        )
    return replace(base, status="complete")


async def spawn_child(
    argv: Sequence[str],
    *,
    stdout_path: Path,
    stderr_path: Path,
    create_subprocess: CreateSubprocessFn | None = None,
    open_log: OpenLogFn | None = None,
) -> SpawnedChild:
    opener = open_log or open_private_file
    spawner = create_subprocess or asyncio.create_subprocess_exec
    stdout_handle = None
    stderr_handle = None
    try:
        stdout_handle = opener(stdout_path, mode="w")
        stderr_handle = opener(stderr_path, mode="w")
        process = await spawner(
            *argv,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
    except asyncio.CancelledError:
        close_log_handles(stdout_handle, stderr_handle)
        raise
    except Exception as exc:
        close_log_handles(stdout_handle, stderr_handle)
        raise ChildSpawnError(f"{type(exc).__name__}: {exc}") from exc
    return SpawnedChild(
        process=process,
        stdout=stdout_handle,
        stderr=stderr_handle,
    )


async def terminate_child(
    process: ChildProcess,
    *,
    grace_seconds: float = CHILD_TERMINATE_GRACE_SECONDS,
) -> None:
    if process.returncode is not None:
        await process.wait()
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        async with asyncio.timeout(grace_seconds):
            await process.wait()
            return
    except TimeoutError:
        pass
    except asyncio.CancelledError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        raise
    try:
        process.kill()
    except ProcessLookupError:
        pass
    await process.wait()


def write_suite_json(suite_dir: Path, payload: Mapping[str, Any]) -> None:
    write_run_json(suite_dir / "suite.json", payload)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _all_children_succeeded(children: Sequence[SimulationChildResult]) -> bool:
    return all(child.status == "complete" for child in children)


class _SuiteScheduler:
    def __init__(
        self,
        config: SimulationSuiteConfig,
        *,
        spawn: SpawnFn,
        grace_seconds: float,
        clock: Callable[[], float],
        suite_dir: Path,
    ) -> None:
        self.config = config
        self.spawn = spawn
        self.grace_seconds = grace_seconds
        self.clock = clock
        self.suite_dir = suite_dir
        self.children = [
            _placeholder_child(index) for index in range(1, config.runs + 1)
        ]
        self.started_at = _utc_now()
        self.started_mono = clock()
        self.git_commit, self.git_dirty = git_provenance()
        self.live: dict[int, ChildProcess] = {}
        self.max_observed = 0
        self._active = 0
        self._active_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(config.concurrency)

    async def _mark_spawned(self) -> None:
        async with self._active_lock:
            self._active += 1
            self.max_observed = max(self.max_observed, self._active)

    async def _mark_reaped(self) -> None:
        async with self._active_lock:
            self._active -= 1

    async def _wait_for_child(
        self, index: int, process: ChildProcess, spawned_at: float
    ) -> None:
        try:
            exit_code = await process.wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                await terminate_child(process, grace_seconds=self.grace_seconds)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
            self.children[index - 1] = _child_result(
                index,
                status="failed",
                exit_code=process.returncode,
                child_wall_seconds=self.clock() - spawned_at,
                error_code="child_wait_failed",
                error_message=f"{type(exc).__name__}: {exc}",
            )
            return
        label = child_run_label(index)
        self.children[index - 1] = interpret_finished_child(
            index=index,
            run_dir=self.suite_dir / "runs" / label,
            exit_code=exit_code,
            child_wall_seconds=self.clock() - spawned_at,
        )

    async def _run_one(self, index: int) -> None:
        label = child_run_label(index)
        run_dir = self.suite_dir / "runs" / label
        stdout_path = self.suite_dir / "workers" / f"{label}.stdout.log"
        stderr_path = self.suite_dir / "workers" / f"{label}.stderr.log"
        process: ChildProcess | None = None
        spawned_at: float | None = None
        counted = False
        try:
            async with self._semaphore:
                argv = build_child_argv(self.config, child_output_dir=run_dir)
                try:
                    process = await self.spawn(
                        argv,
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                    )
                except ChildSpawnError as exc:
                    self.children[index - 1] = _child_result(
                        index,
                        status="failed",
                        error_code="child_spawn_failed",
                        error_message=str(exc),
                    )
                    return
                spawned_at = self.clock()
                self.live[index] = process
                await self._mark_spawned()
                counted = True
                try:
                    await self._wait_for_child(index, process, spawned_at)
                finally:
                    self.live.pop(index, None)
                    if counted:
                        await self._mark_reaped()
                        counted = False
        except asyncio.CancelledError:
            if process is not None:
                await terminate_child(process, grace_seconds=self.grace_seconds)
                self.live.pop(index, None)
                if counted:
                    await self._mark_reaped()
                wall = None if spawned_at is None else self.clock() - spawned_at
                self.children[index - 1] = _child_result(
                    index,
                    status="cancelled",
                    exit_code=process.returncode,
                    child_wall_seconds=wall,
                    error_code="cancelled",
                    error_message="parent cancelled",
                )
            raise

    async def _shutdown_live(self) -> None:
        for process in list(self.live.values()):
            try:
                await terminate_child(process, grace_seconds=self.grace_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    def _persist(
        self,
        status: SuiteStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        best_effort: bool = False,
    ) -> SimulationSuiteResult:
        completed_at = _utc_now()
        suite_wall = self.clock() - self.started_mono
        payload = build_suite_payload(
            config=self.config,
            status=status,
            children=self.children,
            requested_concurrency=self.config.concurrency,
            max_observed_concurrency=self.max_observed,
            started_at=self.started_at,
            completed_at=completed_at,
            suite_wall_seconds=suite_wall,
            git_commit=self.git_commit,
            git_worktree_dirty=self.git_dirty,
            error_code=error_code,
            error_message=error_message,
        )
        write_error: str | None = None
        write_message: str | None = None
        try:
            write_suite_json(self.suite_dir, payload)
        except Exception as exc:
            write_error = "suite_json_write_failed"
            write_message = f"{type(exc).__name__}: {exc}"
            if not best_effort:
                status = "failed"
                error_code = write_error
                error_message = write_message
                payload = build_suite_payload(
                    config=self.config,
                    status=status,
                    children=self.children,
                    requested_concurrency=self.config.concurrency,
                    max_observed_concurrency=self.max_observed,
                    started_at=self.started_at,
                    completed_at=completed_at,
                    suite_wall_seconds=suite_wall,
                    git_commit=self.git_commit,
                    git_worktree_dirty=self.git_dirty,
                    error_code=error_code,
                    error_message=error_message,
                )
                try:
                    write_suite_json(self.suite_dir, payload)
                except Exception:
                    pass
        return SimulationSuiteResult(
            status=status,
            suite_dir=self.suite_dir,
            children=list(self.children),
            requested_concurrency=self.config.concurrency,
            max_observed_concurrency=self.max_observed,
            suite_wall_seconds=suite_wall,
            run_overlap_factor=compute_run_overlap_factor(
                [child.child_wall_seconds for child in self.children],
                suite_wall,
            ),
            error_code=error_code or write_error,
            error_message=error_message or write_message,
        )

    async def run(self) -> SimulationSuiteResult:
        try:
            async with asyncio.TaskGroup() as group:
                for index in range(1, self.config.runs + 1):
                    group.create_task(
                        self._run_one(index),
                        name=f"sim-{child_run_label(index)}",
                    )
        except asyncio.CancelledError:
            await self._shutdown_live()
            self._persist("cancelled", best_effort=True)
            raise
        status: SuiteStatus = (
            "complete" if _all_children_succeeded(self.children) else "failed"
        )
        return self._persist(status)


async def run_simulation_suite(
    config: SimulationSuiteConfig,
    *,
    spawn: SpawnFn | None = None,
    grace_seconds: float = CHILD_TERMINATE_GRACE_SECONDS,
    clock: Callable[[], float] = time.perf_counter,
) -> SimulationSuiteResult:
    validate_runs_and_concurrency(config.runs, config.concurrency)
    scheduler = _SuiteScheduler(
        config,
        spawn=spawn or spawn_child,
        grace_seconds=grace_seconds,
        clock=clock,
        suite_dir=allocate_suite_directory(config.output_dir),
    )
    return await scheduler.run()


def exit_code_for_suite(result: SimulationSuiteResult) -> int:
    if result.status == "cancelled":
        return 130
    if result.status == "complete":
        return 0
    return 1
