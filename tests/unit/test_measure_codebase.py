"""Unit tests for scripts/measure_codebase.py."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_codebase.py"
_SPEC = importlib.util.spec_from_file_location("measure_codebase", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
measure = _MODULE.measure
MeasurementError = _MODULE.MeasurementError
main = _MODULE.main


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    )


def _init_repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "measure@example.com")
    _git(root, "config", "user.name", "Measure Test")


def _commit_all(root: Path, message: str = "init") -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)


def test_measure_rejects_non_git_root(tmp_path: Path) -> None:
    with pytest.raises(MeasurementError, match="not a Git worktree"):
        measure(tmp_path)


def test_measure_jung_layout_and_authored_text(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "src/jung/api").mkdir(parents=True)
    (tmp_path / "src/jung/client").mkdir(parents=True)
    (tmp_path / "src/jung/domain").mkdir(parents=True)
    (tmp_path / "src/jung/persistence").mkdir(parents=True)
    (tmp_path / "src/jung/styles/demo").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "docs").mkdir()

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "jung"\ndependencies = ["fastapi", "pydantic"]\n'
        '[dependency-groups]\ndev = ["pytest", "ruff"]\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("# generated\n" + ("x\n" * 50), encoding="utf-8")
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\n", encoding="utf-8")
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nasyncio_mode = auto\n", encoding="utf-8"
    )
    (tmp_path / "docs/readme.md").write_text("# Docs\n\nHello\n", encoding="utf-8")
    (tmp_path / "src/jung/styles/demo/prompt.txt").write_text(
        "be helpful\n", encoding="utf-8"
    )
    (tmp_path / "src/jung/domain/models.py").write_text(
        "from enum import StrEnum\n"
        "class Stage(StrEnum):\n"
        "    SETUP = 'setup'\n"
        "    INTAKE = 'intake'\n"
        "class CommandName(StrEnum):\n"
        "    UPDATE_PROFILE = 'update_profile'\n",
        encoding="utf-8",
    )
    (tmp_path / "src/jung/persistence/sqlite_store.py").write_text(
        "class SQLiteStore:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "src/jung/api/routes.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.get('/state')\n"
        "async def state():\n"
        "    return {}\n"
        "@router.post('/sessions')\n"
        "async def start():\n"
        "    return {}\n"
        "def helper(payload):\n"
        "    return payload.get('session_id')\n",
        encoding="utf-8",
    )
    (tmp_path / "src/jung/api/websocket.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.websocket('/chat')\n"
        "async def chat():\n"
        "    return None\n",
        encoding="utf-8",
    )
    (tmp_path / "src/jung/client/console.py").write_text(
        "print('console')\n", encoding="utf-8"
    )
    (tmp_path / "tests/test_example.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "scripts/tool.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "binary.dat").write_bytes(b"\x00\x01\x02\x03")

    _commit_all(tmp_path)

    # Untracked authored text must not count.
    (tmp_path / "untracked.md").write_text("# secret\n", encoding="utf-8")

    metrics = measure(tmp_path)

    assert metrics["layout"] == "jung"
    assert metrics["backend_python_files"] == 4  # models, store, routes, websocket
    assert metrics["client_python_files"] == 1
    assert metrics["client_python_physical_loc"] == 1
    assert metrics["test_python_physical_loc"] == 2
    assert metrics["script_python_physical_loc"] == 1
    assert metrics["api_route_count"] == 2
    assert metrics["websocket_endpoint_count"] == 1
    assert metrics["stage_enum_definitions"] == 1
    assert metrics["stage_member_count"] == 2
    assert metrics["command_name_definitions"] == 1
    assert metrics["command_name_member_count"] == 1
    assert metrics["legacy_workflow_representation_definitions"] == 0
    assert metrics["public_concrete_store_implementations"] == 1
    assert metrics["runtime_dependency_count"] == 2
    assert metrics["development_dependency_count"] == 2
    assert metrics["uv_lock_present"] is True
    # uv.lock excluded from authored text; .txt/.ini/Makefile/Dockerfile/.md count
    assert metrics["tracked_authored_file_count"] >= 10
    authored_paths_hint = metrics["tracked_authored_text_physical_loc"]
    assert authored_paths_hint > 0
    # untracked.md must not inflate count if we remeasure after deleting it
    (tmp_path / "untracked.md").unlink()
    assert (
        measure(tmp_path)["tracked_authored_text_physical_loc"] == authored_paths_hint
    )


def test_measure_excludes_uv_lock_and_fails_on_missing_tracked(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "src/jung").mkdir(parents=True)
    (tmp_path / "src/jung/__init__.py").write_text("PACKAGE = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="jung"\ndependencies=[]\n', encoding="utf-8"
    )
    _commit_all(tmp_path, "before lock")
    before = measure(tmp_path)
    assert before["uv_lock_present"] is False

    (tmp_path / "uv.lock").write_text("x\n" * 100, encoding="utf-8")
    _commit_all(tmp_path, "add generated lock")
    after = measure(tmp_path)
    assert after["uv_lock_present"] is True
    assert after["tracked_authored_file_count"] == before["tracked_authored_file_count"]
    assert (
        after["tracked_authored_text_physical_loc"]
        == before["tracked_authored_text_physical_loc"]
    )

    (tmp_path / "src/jung/__init__.py").unlink()
    with pytest.raises(MeasurementError, match="tracked path missing"):
        measure(tmp_path)


def test_measure_jung_hybrid_excludes_generated_requirements(tmp_path: Path) -> None:
    """Phase 6 hybrid: Jung layout + generated requirements, no uv.lock."""
    _init_repo(tmp_path)
    (tmp_path / "src/jung").mkdir(parents=True)
    (tmp_path / "src/jung/__init__.py").write_text("PACKAGE = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="jung"\ndependencies=["fastapi"]\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements-dev.in").write_text(
        "pytest\nruff\nblack\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path, "hybrid before generated")
    before = measure(tmp_path)
    assert before["layout"] == "jung"
    assert before["uv_lock_present"] is False
    assert before["development_dependency_count"] == 3
    before_files = before["tracked_authored_file_count"]
    before_loc = before["tracked_authored_text_physical_loc"]

    (tmp_path / "requirements.txt").write_text("fastapi==1\n" * 80, encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("pytest==1\n" * 80, encoding="utf-8")
    _commit_all(tmp_path, "add generated requirements")
    after = measure(tmp_path)
    assert after["layout"] == "jung"
    assert after["uv_lock_present"] is False
    assert after["development_dependency_count"] == 3
    assert after["tracked_authored_file_count"] == before_files
    assert after["tracked_authored_text_physical_loc"] == before_loc


def test_jung_route_detector_ignores_ordinary_get_calls(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "src/jung/api").mkdir(parents=True)
    (tmp_path / "src/jung/api/noise.py").write_text(
        "def f(dictionary, client, object):\n"
        "    dictionary.get('x')\n"
        "    client.get('/api')\n"
        "    object.route(value=1)\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="jung"\ndependencies=[]\n', encoding="utf-8"
    )
    _commit_all(tmp_path)
    metrics = measure(tmp_path)
    assert metrics["api_route_count"] == 0
    assert metrics["websocket_endpoint_count"] == 0


def test_legacy_layout_blueprint_routes_and_dev_requirements(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "src/psychoanalyst_app/api").mkdir(parents=True)
    (tmp_path / "console-ui").mkdir()
    (tmp_path / "src/psychoanalyst_app/api/user_routes.py").write_text(
        "from quart import Blueprint\n"
        "def create_user_routes(server):\n"
        "    bp = Blueprint('user', __name__)\n"
        "    @bp.route('/status', methods=['GET'])\n"
        "    async def status():\n"
        "        return {}\n"
        "    @bp.route('/login', methods=['POST'])\n"
        "    async def login():\n"
        "        return {}\n"
        "    return bp\n",
        encoding="utf-8",
    )
    (tmp_path / "src/psychoanalyst_app/api/ws_handler.py").write_text(
        "def register(app):\n"
        "    @app.websocket('/ws')\n"
        "    async def ws():\n"
        "        return None\n",
        encoding="utf-8",
    )
    (tmp_path / "src/psychoanalyst_app/workflow.py").write_text(
        "from enum import Enum\n"
        "class WorkflowState(Enum):\n"
        "    NEW = 'new'\n"
        "class RequiredWorkflowAction(Enum):\n"
        "    GO = 'go'\n",
        encoding="utf-8",
    )
    (tmp_path / "console-ui/main.py").write_text("print('ui')\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="psychoanalyst-app"\ndependencies=["trio", "quart"]\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements-dev.in").write_text(
        "-r requirements.in\nblack\nruff\npytest\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path, "legacy before generated")
    before = measure(tmp_path)
    assert before["layout"] == "legacy"
    assert before["backend_python_files"] == 3
    assert before["client_python_files"] == 1
    assert before["api_route_count"] == 2
    assert before["websocket_endpoint_count"] == 1
    assert before["legacy_workflow_representation_definitions"] == 2
    assert before["stage_enum_definitions"] == 0
    assert before["runtime_dependency_count"] == 2
    assert before["development_dependency_count"] == 3
    assert before["uv_lock_present"] is False
    before_files = before["tracked_authored_file_count"]
    before_loc = before["tracked_authored_text_physical_loc"]

    (tmp_path / "requirements.txt").write_text("trio==1\n" * 50, encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("black==1\n" * 50, encoding="utf-8")
    _commit_all(tmp_path, "add generated requirements")
    after = measure(tmp_path)
    assert after["tracked_authored_file_count"] == before_files
    assert after["tracked_authored_text_physical_loc"] == before_loc
    assert after["development_dependency_count"] == 3


# Accepted Phase 7 closure values. Product changes that intentionally alter
# routes, dependencies, or contract members must update this baseline.
ACCEPTED_EXACT = {
    "layout": "jung",
    "uv_lock_present": True,
    "runtime_dependency_count": 7,
    "development_dependency_count": 3,
    "trio_importing_production_modules": 0,
    "legacy_namespace_importing_modules": 0,
    "api_route_count": 11,
    "websocket_endpoint_count": 1,
    "stage_enum_definitions": 1,
    "stage_member_count": 7,
    "command_name_definitions": 1,
    "command_name_member_count": 6,
    "legacy_workflow_representation_definitions": 0,
    "public_concrete_store_implementations": 1,
}

# Aggregate refactor-closure maxima — not per-module line-budget rules.
# Values filled after final staged remasure; keep as placeholders until then.
MAXIMUMS = {
    "backend_python_physical_loc": 10_637,
    "tracked_authored_text_physical_loc": 43_738,
    "tracked_authored_file_count": 220,
}


def test_measure_current_repository() -> None:
    root = Path(__file__).resolve().parents[2]
    metrics = measure(root)
    for key, expected in ACCEPTED_EXACT.items():
        assert metrics[key] == expected, f"{key}: {metrics[key]!r} != {expected!r}"
    for key, maximum in MAXIMUMS.items():
        assert metrics[key] <= maximum, f"{key}: {metrics[key]} > {maximum}"


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _init_repo(tmp_path)
    (tmp_path / "src/jung").mkdir(parents=True)
    (tmp_path / "src/jung/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="jung"\ndependencies=[]\n', encoding="utf-8"
    )
    _commit_all(tmp_path)
    assert main(["--root", str(tmp_path), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["layout"] == "jung"
