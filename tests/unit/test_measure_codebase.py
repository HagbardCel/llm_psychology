import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_codebase.py"
_SPEC = importlib.util.spec_from_file_location("measure_codebase", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
measure = _MODULE.measure


def test_measure_codebase_separates_source_and_tests():
    metrics = measure(Path(__file__).resolve().parents[2])

    assert metrics["production_python_files"] > 0
    assert metrics["test_python_files"] > 0
    assert (
        metrics["production_python_physical_loc"]
        >= metrics["production_python_code_loc"]
    )


def test_measure_codebase_uses_tokens_ast_and_excludes_generated_paths(tmp_path):
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "console-ui").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "requirements.in").write_text("pydantic\n# comment\ntrio>=1\n")
    (tmp_path / "requirements-dev.in").write_text("-r requirements.in\npytest\n")
    (tmp_path / "src" / "app" / "models.py").write_text(
        "from pydantic import BaseModel\nimport trio\n\nclass Model(BaseModel):\n    value: str\n\n# ignored\n"
    )
    (tmp_path / "src" / "app" / "workflow.py").write_text(
        "from enum import Enum\nclass WorkflowState(Enum):\n    NEW = 'new'\n    READY = 'ready'\n"
    )
    (tmp_path / "src" / "app" / "db.py").write_text(
        "SQL = 'CREATE TABLE sessions (id text)'\n"
    )
    (tmp_path / "src" / "app" / "user_routes.py").write_text(
        "def register(bp):\n    bp.route('/user')\n    bp.route('/state')\n"
    )
    (tmp_path / "src" / "app" / "ws_handler.py").write_text(
        "def register(app):\n    app.websocket('/ws')\n"
    )
    (tmp_path / "data" / "ignored.py").write_text("not valid python")

    metrics = measure(tmp_path)

    assert metrics["production_python_files"] == 5
    assert metrics["production_python_code_loc"] == 14
    assert metrics["pydantic_model_candidates"] == 1
    assert metrics["trio_importing_production_modules"] == 1
    assert metrics["api_route_count"] == 2
    assert metrics["user_scoped_route_count"] == 2
    assert metrics["websocket_endpoint_count"] == 1
    assert metrics["sqlite_table_count"] == 1
    assert metrics["workflow_state_member_count"] == 2
    assert metrics["direct_dependency_count"] == 3


def test_measure_output_is_stable_across_runs():
    root = Path(__file__).resolve().parents[2]
    first = measure(root)
    second = measure(root)
    assert first == second


def test_measure_detects_from_trio_import_and_service_container(tmp_path):
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "trio_module.py").write_text("from trio import sleep\n")
    (tmp_path / "src" / "app" / "container_user.py").write_text(
        "import psychoanalyst_app.container.service_container\n"
    )
    (tmp_path / "requirements.in").write_text("trio\n")
    metrics = measure(tmp_path)
    assert metrics["trio_importing_production_modules"] == 1
    assert metrics["service_container_importing_modules"] == 1
