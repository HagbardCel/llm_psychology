"""Deterministic tests for simulation-suite orchestration."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from evals.simulation import __main__ as sim_main
from evals.simulation.runner import SimulationConfig, SimulationResult
from evals.simulation.suite import (
    ChildSpawnError,
    SimulationSuiteConfig,
    SimulationSuiteResult,
    build_child_argv,
    compute_run_overlap_factor,
    exit_code_for_suite,
    interpret_finished_child,
    run_simulation_suite,
    spawn_child,
    validate_runs_and_concurrency,
)


class FakeProcess:
    def __init__(
        self,
        exit_code: int = 0,
        *,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.exit_code = exit_code
        self.gate = gate
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True
        if self.gate is not None:
            self.gate.set()

    def kill(self) -> None:
        self.killed = True
        if self.gate is not None:
            self.gate.set()

    async def wait(self) -> int:
        if self.gate is not None:
            await self.gate.wait()
        if self.terminated:
            self.returncode = -15
            return self.returncode
        if self.killed:
            self.returncode = -9
            return self.returncode
        self.returncode = self.exit_code
        return self.exit_code


def _config(tmp_path: Path, **overrides: Any) -> SimulationSuiteConfig:
    payload: dict[str, Any] = {
        "scenario_id": "anxiety_sleep",
        "sessions": 1,
        "turns_per_session": 1,
        "runs": 2,
        "concurrency": 1,
        "output_dir": tmp_path / "suite",
        "requested_style": "auto",
    }
    payload.update(overrides)
    return SimulationSuiteConfig(**payload)


def _write_run_json(argv: Sequence[str], *, status: str = "complete") -> Path:
    output_dir = Path(argv[list(argv).index("--output-dir") + 1])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "run.json").write_text(
        json.dumps({"status": status}),
        encoding="utf-8",
    )
    return output_dir


def _output_dir_from_argv(argv: Sequence[str]) -> Path:
    return Path(argv[list(argv).index("--output-dir") + 1])


def _touch_logs(stdout_path: Path, stderr_path: Path) -> None:
    stdout_path.write_text("out\n", encoding="utf-8")
    stderr_path.write_text("err\n", encoding="utf-8")


async def _complete_spawn(
    argv: Sequence[str],
    *,
    stdout_path: Path,
    stderr_path: Path,
    status: str = "complete",
    exit_code: int = 0,
) -> FakeProcess:
    _write_run_json(argv, status=status)
    _touch_logs(stdout_path, stderr_path)
    return FakeProcess(exit_code=exit_code)


def test_cli_defaults_runs_and_concurrency() -> None:
    parser = sim_main.build_parser()
    args = parser.parse_args(
        ["--scenario", "anxiety_sleep", "--sessions", "1", "--turns-per-session", "1"]
    )
    assert args.runs == 1
    assert args.concurrency == 1


def test_cli_rejects_non_positive_runs_and_concurrency() -> None:
    parser = sim_main.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--scenario",
                "anxiety_sleep",
                "--sessions",
                "1",
                "--turns-per-session",
                "1",
                "--runs",
                "0",
            ]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--scenario",
                "anxiety_sleep",
                "--sessions",
                "1",
                "--turns-per-session",
                "1",
                "--concurrency",
                "0",
            ]
        )


def test_cli_rejects_concurrency_greater_than_runs() -> None:
    with pytest.raises(SystemExit):
        sim_main.main(
            [
                "--scenario",
                "anxiety_sleep",
                "--sessions",
                "1",
                "--turns-per-session",
                "1",
                "--runs",
                "2",
                "--concurrency",
                "3",
            ]
        )


def test_validate_runs_and_concurrency() -> None:
    validate_runs_and_concurrency(4, 4)
    with pytest.raises(ValueError, match="runs must be >= 1"):
        validate_runs_and_concurrency(0, 1)
    with pytest.raises(ValueError, match="concurrency must be >= 1"):
        validate_runs_and_concurrency(1, 0)
    with pytest.raises(ValueError, match="concurrency must be <= runs"):
        validate_runs_and_concurrency(2, 3)


def test_main_runs_1_uses_legacy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_run(config: SimulationConfig) -> SimulationResult:
        seen["config"] = config
        return SimulationResult(status="complete", run_dir=Path("legacy"))

    async def fake_suite(*_args: Any, **_kwargs: Any) -> SimulationSuiteResult:
        raise AssertionError("suite path must not run when runs=1")

    monkeypatch.setattr(sim_main, "run_simulation", fake_run)
    monkeypatch.setattr(sim_main, "run_simulation_suite", fake_suite)
    code = sim_main.main(
        ["--scenario", "anxiety_sleep", "--sessions", "1", "--turns-per-session", "1"]
    )
    assert code == 0
    assert seen["config"].sessions == 1


def test_main_runs_gt_1_uses_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_run(*_args: Any, **_kwargs: Any) -> SimulationResult:
        raise AssertionError("legacy path must not run when runs>1")

    async def fake_suite(config: SimulationSuiteConfig) -> SimulationSuiteResult:
        seen["config"] = config
        return SimulationSuiteResult(
            status="complete",
            suite_dir=Path("suite"),
            children=[],
            requested_concurrency=config.concurrency,
            max_observed_concurrency=1,
            suite_wall_seconds=1.0,
            run_overlap_factor=1.0,
        )

    monkeypatch.setattr(sim_main, "run_simulation", fake_run)
    monkeypatch.setattr(sim_main, "run_simulation_suite", fake_suite)
    code = sim_main.main(
        [
            "--scenario",
            "anxiety_sleep",
            "--sessions",
            "1",
            "--turns-per-session",
            "1",
            "--runs",
            "2",
            "--concurrency",
            "1",
        ]
    )
    assert code == 0
    assert seen["config"].runs == 2


def test_main_keyboard_interrupt_returns_130(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_suite(*_args: Any, **_kwargs: Any) -> SimulationSuiteResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(sim_main, "run_simulation_suite", fake_suite)
    code = sim_main.main(
        [
            "--scenario",
            "anxiety_sleep",
            "--sessions",
            "1",
            "--turns-per-session",
            "1",
            "--runs",
            "2",
        ]
    )
    assert code == 130


def test_child_argv_round_trips_resolved_args() -> None:
    parser = sim_main.build_parser()
    parent = parser.parse_args(
        [
            "--scenario",
            "social_anxiety",
            "--sessions",
            "2",
            "--turns-per-session",
            "4",
            "--max-intake-turns",
            "9",
            "--style",
            "jung",
            "--patient-model",
            "patient-model",
            "--patient-base-url",
            "http://127.0.0.1:9/v1",
            "--patient-timeout",
            "30",
            "--workflow-timeout",
            "40",
            "--overall-timeout",
            "50",
            "--patient-history-chars",
            "1000",
            "--runs",
            "4",
            "--concurrency",
            "2",
        ]
    )
    config = sim_main.suite_config_from_args(parent)
    child_argv = build_child_argv(config, child_output_dir=Path("/tmp/run-001"))
    parsed = parser.parse_args(child_argv[3:])
    assert parsed.scenario == parent.scenario
    assert parsed.sessions == parent.sessions
    assert parsed.turns_per_session == parent.turns_per_session
    assert parsed.max_intake_turns == parent.max_intake_turns
    assert parsed.style == parent.style
    assert parsed.patient_model == parent.patient_model
    assert parsed.patient_base_url == parent.patient_base_url
    assert parsed.patient_timeout == parent.patient_timeout
    assert parsed.workflow_timeout == parent.workflow_timeout
    assert parsed.overall_timeout == parent.overall_timeout
    assert parsed.patient_history_chars == parent.patient_history_chars
    assert parsed.runs == 1
    assert parsed.concurrency == 1
    assert parsed.output_dir == Path("/tmp/run-001")


def test_child_argv_omits_none_optionals() -> None:
    parser = sim_main.build_parser()
    parent = parser.parse_args(
        ["--scenario", "anxiety_sleep", "--sessions", "1", "--turns-per-session", "1"]
    )
    config = sim_main.suite_config_from_args(parent)
    argv = build_child_argv(config, child_output_dir=Path("/tmp/run-001"))
    assert "--patient-model" not in argv
    assert "--patient-base-url" not in argv
    assert "--overall-timeout" not in argv
    assert "None" not in argv
    assert argv.count("--runs") == 1
    assert argv[argv.index("--runs") + 1] == "1"
    assert argv[argv.index("--concurrency") + 1] == "1"


def test_overlap_factor_excludes_unspawned_children() -> None:
    assert compute_run_overlap_factor(
        [100.0, None, 90.0, 95.0], 120.0
    ) == pytest.approx(285.0 / 120.0)
    assert compute_run_overlap_factor([None, None], 5.0) == 0.0
    assert compute_run_overlap_factor([10.0], 0.0) == 0.0


def test_interpret_mixed_exit_and_run_json(tmp_path: Path) -> None:
    failed_dir = tmp_path / "failed"
    failed_dir.mkdir()
    (failed_dir / "run.json").write_text(
        json.dumps({"status": "failed", "error_code": "mechanical_audit_failed"}),
        encoding="utf-8",
    )
    failed = interpret_finished_child(
        index=1,
        run_dir=failed_dir,
        exit_code=0,
        child_wall_seconds=1.0,
    )
    assert failed.status == "failed"
    assert failed.error_code == "mechanical_audit_failed"

    complete_dir = tmp_path / "complete"
    complete_dir.mkdir()
    (complete_dir / "run.json").write_text(
        json.dumps({"status": "complete"}),
        encoding="utf-8",
    )
    mixed = interpret_finished_child(
        index=2,
        run_dir=complete_dir,
        exit_code=1,
        child_wall_seconds=1.0,
    )
    assert mixed.status == "failed"
    assert mixed.error_code == "child_exit_nonzero"


async def test_suite_success_and_artifact_layout(tmp_path: Path) -> None:
    existed_before_spawn: list[bool] = []

    async def spawn(
        argv: Sequence[str], *, stdout_path: Path, stderr_path: Path
    ) -> FakeProcess:
        run_dir = _output_dir_from_argv(argv)
        existed_before_spawn.append(run_dir.exists())
        return await _complete_spawn(
            argv, stdout_path=stdout_path, stderr_path=stderr_path
        )

    result = await run_simulation_suite(
        _config(tmp_path, runs=2, concurrency=2), spawn=spawn
    )
    assert result.status == "complete"
    assert exit_code_for_suite(result) == 0
    assert len(result.children) == 2
    assert [child.index for child in result.children] == [1, 2]
    assert [child.path for child in result.children] == [
        "runs/run-001",
        "runs/run-002",
    ]
    assert existed_before_spawn == [False, False]
    suite_dir = result.suite_dir
    assert (suite_dir / "runs").is_dir()
    assert (suite_dir / "workers").is_dir()
    payload = json.loads((suite_dir / "suite.json").read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["requested_style"] == "auto"
    assert payload["requested_concurrency"] == 2
    assert 1 <= payload["max_observed_concurrency"] <= 2
    assert payload["children"][0]["status"] == "complete"
    assert (suite_dir / "workers" / "run-001.stdout.log").is_file()
    assert (suite_dir / "workers" / "run-002.stderr.log").is_file()


async def test_concurrency_never_exceeds_bound(tmp_path: Path) -> None:
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def spawn(
        argv: Sequence[str], *, stdout_path: Path, stderr_path: Path
    ) -> FakeProcess:
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        _write_run_json(argv)
        _touch_logs(stdout_path, stderr_path)
        gate = asyncio.Event()

        class CountingProcess(FakeProcess):
            async def wait(self) -> int:  # type: ignore[override]
                nonlocal active
                await asyncio.sleep(0.05)
                gate.set()
                try:
                    return await super().wait()
                finally:
                    async with lock:
                        active -= 1

        return CountingProcess(gate=gate)

    result = await run_simulation_suite(
        _config(tmp_path, runs=4, concurrency=2),
        spawn=spawn,
    )
    assert result.status == "complete"
    assert peak <= 2
    assert result.max_observed_concurrency <= 2
    assert result.max_observed_concurrency >= 1


async def test_one_child_failure_siblings_continue(tmp_path: Path) -> None:
    async def spawn(
        argv: Sequence[str], *, stdout_path: Path, stderr_path: Path
    ) -> FakeProcess:
        run_dir = _output_dir_from_argv(argv)
        status = "failed" if run_dir.name == "run-002" else "complete"
        exit_code = 1 if status == "failed" else 0
        return await _complete_spawn(
            argv,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            status=status,
            exit_code=exit_code,
        )

    result = await run_simulation_suite(
        _config(tmp_path, runs=3, concurrency=2),
        spawn=spawn,
    )
    assert result.status == "failed"
    assert exit_code_for_suite(result) == 1
    assert [child.status for child in result.children] == [
        "complete",
        "failed",
        "complete",
    ]


async def test_spawn_failure_siblings_continue(tmp_path: Path) -> None:
    async def spawn(
        argv: Sequence[str], *, stdout_path: Path, stderr_path: Path
    ) -> FakeProcess:
        run_dir = _output_dir_from_argv(argv)
        if run_dir.name == "run-002":
            raise ChildSpawnError("exec failed")
        return await _complete_spawn(
            argv, stdout_path=stdout_path, stderr_path=stderr_path
        )

    result = await run_simulation_suite(
        _config(tmp_path, runs=3, concurrency=2),
        spawn=spawn,
    )
    assert result.status == "failed"
    assert result.children[1].status == "failed"
    assert result.children[1].error_code == "child_spawn_failed"
    assert result.children[1].child_wall_seconds is None
    assert result.children[0].status == "complete"
    assert result.children[2].status == "complete"
    payload = json.loads((result.suite_dir / "suite.json").read_text(encoding="utf-8"))
    spawned_walls = [
        child["child_wall_seconds"]
        for child in payload["children"]
        if child["child_wall_seconds"] is not None
    ]
    assert payload["run_overlap_factor"] == pytest.approx(
        compute_run_overlap_factor(
            [child["child_wall_seconds"] for child in payload["children"]],
            payload["suite_wall_seconds"],
        )
    )
    assert len(spawned_walls) == 2


async def test_missing_and_malformed_run_json(tmp_path: Path) -> None:
    async def spawn(
        argv: Sequence[str], *, stdout_path: Path, stderr_path: Path
    ) -> FakeProcess:
        run_dir = _output_dir_from_argv(argv)
        _touch_logs(stdout_path, stderr_path)
        if run_dir.name == "run-001":
            return FakeProcess(0)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run.json").write_text("{not-json", encoding="utf-8")
        return FakeProcess(0)

    result = await run_simulation_suite(
        _config(tmp_path, runs=2, concurrency=1),
        spawn=spawn,
    )
    assert result.status == "failed"
    assert result.children[0].error_code == "missing_run_json"
    assert result.children[1].error_code == "malformed_run_json"


async def test_suite_json_write_failure_is_infrastructure_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def spawn(
        argv: Sequence[str], *, stdout_path: Path, stderr_path: Path
    ) -> FakeProcess:
        return await _complete_spawn(
            argv, stdout_path=stdout_path, stderr_path=stderr_path
        )

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("evals.simulation.suite.write_suite_json", boom)
    result = await run_simulation_suite(_config(tmp_path, runs=2), spawn=spawn)
    assert result.status == "failed"
    assert result.error_code == "suite_json_write_failed"
    assert exit_code_for_suite(result) == 1


async def test_parent_cancellation_terminates_and_reraises(tmp_path: Path) -> None:
    spawned = asyncio.Event()
    processes: list[FakeProcess] = []

    async def spawn(
        argv: Sequence[str], *, stdout_path: Path, stderr_path: Path
    ) -> FakeProcess:
        _touch_logs(stdout_path, stderr_path)
        process = FakeProcess(gate=asyncio.Event())
        processes.append(process)
        spawned.set()
        return process

    task = asyncio.create_task(
        run_simulation_suite(
            _config(tmp_path, runs=3, concurrency=1),
            spawn=spawn,
            grace_seconds=0.05,
        )
    )
    await spawned.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes
    assert processes[0].terminated or processes[0].killed
    payload = json.loads(
        (tmp_path / "suite" / "suite.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "cancelled"
    assert len(payload["children"]) == 3
    assert payload["children"][0]["status"] == "cancelled"
    assert payload["children"][1]["status"] == "not_started"
    assert payload["children"][2]["status"] == "not_started"


async def test_spawn_child_closes_handles_on_failure(tmp_path: Path) -> None:
    handles: list[Any] = []

    class TrackingHandle:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    def open_log(_path: Path, *, mode: str = "w") -> TrackingHandle:
        handle = TrackingHandle()
        handles.append(handle)
        return handle

    async def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("cannot exec")

    with pytest.raises(ChildSpawnError):
        await spawn_child(
            ["does-not-run"],
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
            create_subprocess=boom,
            open_log=open_log,
        )
    assert len(handles) == 2
    assert all(handle.closed for handle in handles)
